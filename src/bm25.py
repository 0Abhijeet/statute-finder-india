"""BM25 over Postgres's own english lexemes (decision 31).

Terms come from the `chunks.fts` tsvector (`unnest(fts)` gives lexeme + positions, so
term frequency = number of positions) and the query is stemmed by the same
`to_tsvector('english', ...)`. So "stabs" and "stabbing" meet at "stab", and nothing
is pinned beyond what is already installed. Scoring is textbook BM25 with the usual
untuned defaults k1=1.5, b=0.75; IDF is computed over all in-force chunks, which is
what Postgres ts_rank_cd lacks (a rare word like "stab" outweighs "person").
"""
import math
from collections import defaultdict

from sqlalchemy import text

K1 = 1.5
B = 0.75


class Bm25Index:
    def __init__(self, rows):
        """rows: iterable of (chunk_id, act_id, lexeme, tf)."""
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.doc_len: dict[int, int] = defaultdict(int)
        self.act_of: dict[int, int] = {}
        for cid, act_id, lex, tf in rows:
            self.postings[lex].append((cid, tf))
            self.doc_len[cid] += tf
            self.act_of[cid] = act_id
        self.n = len(self.doc_len)
        self.avgdl = (sum(self.doc_len.values()) / self.n) if self.n else 0.0

    def idf(self, term: str) -> float:
        df = len(self.postings.get(term, ()))
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def score(self, terms: list[str]) -> dict[int, float]:
        out: dict[int, float] = defaultdict(float)
        for term in dict.fromkeys(terms):
            idf = self.idf(term)
            for cid, tf in self.postings.get(term, ()):
                norm = tf + K1 * (1 - B + B * self.doc_len[cid] / self.avgdl)
                out[cid] += idf * tf * (K1 + 1) / norm
        return out


_cache: dict = {"key": None, "index": None}


async def get_index(db) -> Bm25Index:
    """Built lazily; rebuilt when the set of in-force chunks changes (re-ingest)."""
    key = (await db.execute(text(
        "select count(*), coalesce(max(c.id), 0) from chunks c join sections s on s.id = c.section_id "
        "where s.status = 'in_force'"))).one()
    key = tuple(key)
    if _cache["key"] != key:
        rows = (await db.execute(text("""
            select c.id, s.act_id, t.lexeme, cardinality(t.positions) as tf
            from chunks c join sections s on s.id = c.section_id,
                 lateral unnest(c.fts) as t(lexeme, positions, weights)
            where s.status = 'in_force'"""))).all()
        _cache["index"] = Bm25Index([tuple(r) for r in rows])
        _cache["key"] = key
    return _cache["index"]


async def query_terms(db, query: str) -> list[str]:
    """Stems of the query via Postgres's english config (stopwords dropped)."""
    rows = await db.execute(
        text("select lexeme from unnest(to_tsvector('english', :q)) as t(lexeme, positions, weights)"),
        {"q": query},
    )
    return [r.lexeme for r in rows]
