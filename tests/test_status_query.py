"""Decision 40 (legal-status flags) and decision 41 (query cleaning)."""
import pytest
import pytest_asyncio
from sqlalchemy import func, select

import src.analyze as analyze_mod
from src.database import AsyncSessionLocal
from src.facts import Facts
from src.ingest import ingest_act, load_manifest
from src.models import ProvisionStatus
from src.query import clean_query
from src.status import load_seed, sync_status
from tests.test_ingest import clean_db  # noqa: F401

MANIFEST = {e["file"]: e for e in load_manifest()}


# ---- query cleaning (no DB) -------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("A person asks which law applies to an incident in 2022 where someone caused a serious injury with a knife.",
     "someone caused a serious injury with a knife"),
    ("Which section applies to a man who stole my phone on 12 March 2023?", "a man who stole my phone"),
    ("What law applies when a driver hits a pedestrian", "a driver hits a pedestrian"),
])
def test_clean_query_removes_question_phrasing_and_dates(raw, expected):
    """Proves: the incident-10 failure class: question framing and dates are removed from
    the retrieval query only."""
    out = clean_query(raw)
    assert expected.lower() in out.lower()
    for noise in ("which law", "what law", "which section", "applies", "2022", "2023", "asks"):
        assert noise not in out.lower()


def test_clean_query_leaves_plain_incidents_alone_and_never_empties():
    plain = "Someone secretly takes a stranger's phone from their bag without permission."
    assert clean_query(plain) == plain
    short = "Which law applies?"
    assert clean_query(short) == short          # would leave < 3 words: original kept


# ---- status flags -----------------------------------------------------------------------
def test_seed_file_has_the_two_curated_entries_with_sources():
    rows = {(e["act"], e["section"]): e for e in load_seed()}
    assert rows[("it_act_2000", "66A")]["status"] == "struck_down"
    assert rows[("bns_2023", "106")]["status"] == "not_in_force"
    assert all(e["source_url"].startswith("http") and e["verification"] in ("source_located", "third_party_only")
               for e in rows.values())


@pytest_asyncio.fixture
async def it_corpus(clean_db, monkeypatch):  # noqa: F811
    await ingest_act(MANIFEST["it_act_2000.pdf"])

    async def fake_extract(_):
        return Facts(), {"extraction_failed": False}

    monkeypatch.setattr(analyze_mod, "extract_facts", fake_extract)
    async with AsyncSessionLocal() as db:
        await sync_status(db)


@pytest.mark.asyncio
async def test_sync_is_idempotent(it_corpus):
    async with AsyncSessionLocal() as db:
        n1 = await sync_status(db)
        n2 = await sync_status(db)
        total = (await db.execute(select(func.count(ProvisionStatus.id)))).scalar()
    assert n1 == n2 == total == 2


@pytest.mark.asyncio
async def test_struck_down_section_is_still_shown_with_a_warning(it_corpus):
    """Proves: decision 40: 66A is returned (not hidden) and carries the server-built
    warning, source and verification level; unflagged sections carry none."""
    out = await analyze_mod.analyze("Punishment for sending offensive messages through communication service",
                                    incident_date="2025-01-01", k_per_act=15, k_final=30)
    by = {r["anchor"]: r for r in out["results"]}
    assert "it_act_2000:s66A" in by
    flag = by["it_act_2000:s66A"]["legal_status"]
    assert flag["status"] == "struck_down" and "not an operative offence" in flag["warning"]
    assert flag["source_url"].startswith("http") and flag["verification"] == "source_located"
    assert all("legal_status" not in r for a, r in by.items() if a != "it_act_2000:s66A")


@pytest.mark.asyncio
async def test_analyze_reports_the_cleaned_retrieval_query(it_corpus):
    out = await analyze_mod.analyze("Which law applies to an incident in 2022 where messages were sent online?")
    assert out["retrieval_query"] != out["incident"] and "2022" not in out["retrieval_query"]
    assert out["date"]["regime"] == "ipc"      # date routing still sees the original text
