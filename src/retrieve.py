"""Retrieval, no LLM (decisions 26-31).

1. Per act: a vector leg (cosine, exact scan) and a keyword leg (BM25 over Postgres
   lexemes, decision 31) are fused with RRF *within the act*; the act's top `k_per_act`
   sections go into a pool. This guarantees every act a chance (decision 27).
2. The pool is re-ranked globally: each leg ranks the pooled sections by its own
   score and the two ranks are fused with RRF (decision 28). RRF scores from
   different acts are only comparable after this step.
3. No similarity floor (decision 29): scores are returned; abstention is Phase 5.

Omitted sections are never searched (decision 16). Chunk hits roll up to their
parent section; the quote is always the stored chunk text, never the header."""
import asyncio
import re
from dataclasses import dataclass, field

from sqlalchemy import text

from src.bm25 import get_index, query_terms
from src.database import AsyncSessionLocal
from src.embeddings import get_embeddings

RRF_K = 60
CANDIDATES = 20  # per leg, per act


@dataclass
class Hit:
    act: str                   # short_name, e.g. "bns_2023"
    act_title: str
    year: int
    number: str
    anchor: str                # "bns_2023:s103"
    title: str | None
    chapter: str | None
    page_start: int
    page_end: int
    filename: str
    source_url: str
    retrieved_at: str
    text: str                  # best matching chunk (never the embedding header)
    score: float               # global RRF score over the pooled candidates
    vector_sim: float          # best cosine among this section's scored chunks
    vector_rank: int | None    # rank within the pool (1-indexed)
    keyword_rank: int | None
    act_rank: int              # rank within its own act
    chunk_ids: list[int] = field(default_factory=list)
    best_chunk_id: int | None = None   # the chunk whose text is `text` (for the page image)


async def retrieve(
    query: str,
    k_per_act: int = 3,
    k_final: int | None = 8,
    mode: str = "hybrid",          # "hybrid" | "vector" | "keyword" (Phase 6 baselines)
    acts: list[str] | None = None,
) -> list[Hit]:
    assert mode in ("hybrid", "vector", "keyword")
    vec = await asyncio.to_thread(get_embeddings().embed_query, query)
    vec_s = str(list(vec))
    pool: dict[str, Hit] = {}
    kscore_all: dict[int, float] = {}

    async with AsyncSessionLocal() as db:
        terms = await query_terms(db, query) if mode in ("hybrid", "keyword") else []
        if terms:
            kscore_all = (await get_index(db)).score(terms)
            index_act = (await get_index(db)).act_of
        acts_rows = (await db.execute(text("select id, short_name from acts order by short_name"))).all()
        for act_id, short in acts_rows:
            if acts and short not in acts:
                continue
            vleg, kleg = [], []
            if mode in ("hybrid", "vector"):
                vleg = [r.id for r in await db.execute(text("""
                    select ch.id from chunks ch join sections s on s.id = ch.section_id
                    where s.act_id = :a and s.status = 'in_force'
                    order by ch.embedding <=> cast(:v as vector) limit :n"""),
                    {"a": act_id, "v": vec_s, "n": CANDIDATES})]
            if mode in ("hybrid", "keyword") and kscore_all:
                in_act = [(cid, sc) for cid, sc in kscore_all.items() if index_act.get(cid) == act_id]
                kleg = [cid for cid, _ in sorted(in_act, key=lambda x: x[1], reverse=True)[:CANDIDATES]]
            fused: dict[int, float] = {}
            for leg in (vleg, kleg):
                for rank, cid in enumerate(leg, start=1):
                    fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
            if not fused:
                continue
            rows = await db.execute(text("""
                select ch.id, ch.text, s.number, s.anchor, s.title, s.chapter, s.page_start, s.page_end,
                       a.title as act_title, a.year, sf.filename, sf.source_url, sf.retrieved_at,
                       1 - (ch.embedding <=> cast(:v as vector)) as sim
                from chunks ch join sections s on s.id = ch.section_id
                join acts a on a.id = s.act_id
                join source_files sf on sf.id = s.source_file_id
                where ch.id = any(:ids)"""), {"ids": list(fused), "v": vec_s})
            by_section: dict[str, tuple[float, Hit]] = {}
            for r in rows:
                score = fused[r.id]
                cur = by_section.get(r.anchor)
                if cur is None:
                    h = Hit(act=short, act_title=r.act_title, year=r.year, number=r.number, anchor=r.anchor,
                            title=r.title, chapter=r.chapter, page_start=r.page_start, page_end=r.page_end,
                            filename=r.filename, source_url=r.source_url, retrieved_at=r.retrieved_at.isoformat(),
                            text=r.text, score=0.0, vector_sim=float(r.sim), vector_rank=None,
                            keyword_rank=None, act_rank=0, chunk_ids=[r.id], best_chunk_id=r.id)
                    by_section[r.anchor] = (score, h)
                else:
                    best, h = cur
                    h.chunk_ids.append(r.id)
                    h.vector_sim = max(h.vector_sim, float(r.sim))
                    if score > best:
                        by_section[r.anchor] = (score, h)
                        h.text = r.text
                        h.best_chunk_id = r.id
            ranked = sorted(by_section.values(), key=lambda x: x[0], reverse=True)[:k_per_act]
            for n, (_, h) in enumerate(ranked, start=1):
                h.act_rank = n
                pool[h.anchor] = h

        if not pool:
            return []

        # Global re-rank of the pool (decision 28).
        kscore = kscore_all

    hits = list(pool.values())
    by_vec = sorted(hits, key=lambda h: h.vector_sim, reverse=True)
    k_of = {h.anchor: max((kscore.get(c, 0.0) for c in h.chunk_ids), default=0.0) for h in hits}
    by_kw = sorted([h for h in hits if k_of[h.anchor] > 0], key=lambda h: k_of[h.anchor], reverse=True)
    if mode in ("hybrid", "vector"):
        for r, h in enumerate(by_vec, start=1):
            h.vector_rank = r
            h.score += 1.0 / (RRF_K + r)
    if mode in ("hybrid", "keyword"):
        for r, h in enumerate(by_kw, start=1):
            h.keyword_rank = r
            h.score += 1.0 / (RRF_K + r)
    hits.sort(key=lambda h: (h.score, h.vector_sim), reverse=True)
    return hits[:k_final] if k_final else hits


def citation(h: Hit) -> str:
    """Built from DB fields only (addendum item 2). BNS titles are absent by decision 24."""
    parts = [f"{h.act_title} {h.year}"]
    if h.chapter:
        parts.append(f"Chapter {h.chapter}")
    parts.append(f"s.{h.number}" + (f" ({h.title})" if h.title else ""))
    pages = f"page {h.page_start}" if h.page_start == h.page_end else f"pages {h.page_start}-{h.page_end}"
    return f"{', '.join(parts)} ({pages} of {h.filename})"
