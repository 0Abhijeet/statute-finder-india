"""Retrieval tests against real Postgres (fake embeddings: structure, not relevance).
Relevance is measured in the gate (scripts/gate.py) and the Phase 6 eval, not here."""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.ingest import ingest_act, load_manifest
from src.bm25 import Bm25Index, get_index, query_terms
from src.retrieve import citation, retrieve

# Reuse the DB fixture (drop_all guarded by the "_test" name check).
from tests.test_ingest import clean_db  # noqa: F401

MANIFEST = {e["file"]: e for e in load_manifest()}


@pytest_asyncio.fixture
async def three_acts(clean_db):  # noqa: F811
    for f in ("tn_harassment_women_1998.pdf", "arms_act_1959.pdf", "it_act_2000.pdf"):
        await ingest_act(MANIFEST[f])


def test_bm25_rare_terms_outweigh_generic_terms():
    """Proves: IDF works: a term in 1 of 4 chunks outscores one in all 4 (the Postgres
    ts_rank_cd gap that failed the knife incident)."""
    rows = []
    for cid, extra in enumerate(["stab", "", "", ""], start=1):
        rows.append((cid, 1, "person", 1))
        if extra:
            rows.append((cid, 1, extra, 1))
    idx = Bm25Index(rows)
    assert idx.idf("stab") > idx.idf("person")
    scores = idx.score(["person", "stab"])
    assert max(scores, key=scores.get) == 1


@pytest.mark.asyncio
async def test_query_stems_meet_document_stems(three_acts):
    """Proves: the query is stemmed by the same english config as the documents
    ("stabs" and "stabbing" share a stem)."""
    from src.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        a = await query_terms(db, "he stabs people")
        b = await query_terms(db, "stabbing")
        assert set(a) & set(b) == {"stab"}
        idx = await get_index(db)
        assert idx.n > 0 and idx.idf("licenc") > 0


@pytest.mark.asyncio
async def test_per_act_retrieval_caps_each_act_and_can_filter(three_acts):
    """Proves: per-act retrieval (decision 27) returns at most k_per_act per act and
    an `acts` filter restricts to that act."""
    hits = await retrieve("licence for a firearm", k_per_act=2, k_final=None)
    per_act = {}
    for h in hits:
        per_act[h.act] = per_act.get(h.act, 0) + 1
    assert set(per_act) == {"tn_harassment_women_1998", "arms_act_1959", "it_act_2000"}
    assert all(n <= 2 for n in per_act.values())
    only = await retrieve("licence for a firearm", k_per_act=3, acts=["arms_act_1959"])
    assert only and {h.act for h in only} == {"arms_act_1959"}


@pytest.mark.asyncio
async def test_omitted_sections_are_never_returned(three_acts):
    """Proves: decision 16: omitted sections are excluded from retrieval."""
    from src.database import AsyncSessionLocal
    from src.models import Section

    async with AsyncSessionLocal() as db:
        omitted = {r.anchor for r in (await db.execute(select(Section).where(Section.status == "omitted"))).scalars()}
    assert omitted, "fixture should contain omitted IT sections"
    for q in ("Omitted", "Amendment of Act", "Resignation and removal", "Appellate Tribunal"):
        hits = await retrieve(q, k_per_act=10, k_final=None)
        assert not ({h.anchor for h in hits} & omitted)


@pytest.mark.asyncio
async def test_hits_carry_provenance_and_citation_is_built_from_db_fields(three_acts):
    """Proves: every hit has page/file/url from the DB and the citation string is
    assembled from them (addendum item 2), never from model output."""
    hits = await retrieve("penalty for harassment of women", k_per_act=1)
    h = next(x for x in hits if x.act == "tn_harassment_women_1998")
    assert h.page_start >= 1 and h.filename == "tn_harassment_women_1998.pdf" and h.source_url.startswith("http")
    c = citation(h)
    assert "Tamil Nadu Prohibition of Harassment of Women Act 1998" in c
    assert f"s.{h.number}" in c and "tn_harassment_women_1998.pdf" in c


@pytest.mark.asyncio
async def test_retrieve_endpoint_returns_results_and_disclaimer(three_acts):
    """Proves: /retrieve works end to end over ASGI (httpx, not TestClient: one event loop)."""
    from src.app import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/retrieve", json={"incident": "licence for a firearm", "k_final": 5})
    body = r.json()
    assert r.status_code == 200
    assert len(body["results"]) <= 5 and body["disclaimer"] == "Informational, not legal advice."
    assert all("citation" in x for x in body["results"])
