"""Ingest tests against a real Postgres + pgvector database.

DANGER: the `clean_db` fixture runs drop_all before and after every test on whatever
DATABASE_URL points at. It refuses to run unless the database name ends in `_test`.
Local:  DATABASE_URL=postgresql://statute:statutepassword@localhost:15433/statutedb_test python -m pytest -v
"""
import os

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from src.database import Base, engine
from src.ingest import RAW_DIR, ingest_act, ingest_mapping, load_manifest
from src.models import Act, Chunk, IpcBnsMapping, Section
from src.provenance import quote_resolves

MANIFEST = {e["file"]: e for e in load_manifest()}
TN = MANIFEST["tn_harassment_women_1998.pdf"]
ARMS = MANIFEST["arms_act_1959.pdf"]
MAPPING = MANIFEST["bns_ipc_comparison_keralaprisons.pdf"]


@pytest_asyncio.fixture
async def clean_db():
    name = os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?")[0]
    assert name.endswith("_test"), f"refusing to drop_all on non-test database {name!r}"
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _counts(db_session_factory):
    async with db_session_factory() as db:
        return {
            "sections": (await db.execute(select(func.count(Section.id)))).scalar(),
            "chunks": (await db.execute(select(func.count(Chunk.id)))).scalar(),
            "acts": (await db.execute(select(func.count(Act.id)))).scalar(),
        }


@pytest.mark.asyncio
async def test_ingest_is_idempotent(clean_db):
    """Proves: re-running ingest for an act yields the same rows, not duplicates."""
    from src.database import AsyncSessionLocal

    first = await ingest_act(TN)
    c1 = await _counts(AsyncSessionLocal)
    second = await ingest_act(TN)
    c2 = await _counts(AsyncSessionLocal)
    assert first == second
    assert c1 == c2 == {"sections": 14, "chunks": 14, "acts": 1}


@pytest.mark.asyncio
async def test_ingest_is_additive_across_acts(clean_db):
    """Proves: ingesting one act does not wipe another."""
    from src.database import AsyncSessionLocal

    await ingest_act(TN)
    await ingest_act(ARMS)
    await ingest_act(TN)
    async with AsyncSessionLocal() as db:
        by_act = dict((await db.execute(
            select(Act.short_name, func.count(Section.id)).join(Section, Section.act_id == Act.id).group_by(Act.short_name)
        )).all())
    assert by_act == {"tn_harassment_women_1998": 14, "arms_act_1959": 48}


@pytest.mark.asyncio
async def test_every_stored_chunk_quote_resolves_against_the_pdf(clean_db):
    """Proves: stored provenance is real: each chunk's text is found in the source
    file at the stored page/offsets. Value: catches parser drift."""
    from src.database import AsyncSessionLocal

    await ingest_act(ARMS)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Section, Chunk).join(Chunk, Chunk.section_id == Section.id))).all()
    assert rows
    path = os.path.join(RAW_DIR, ARMS["file"])
    for section, chunk in rows:
        assert section.text[chunk.char_start:chunk.char_end] == chunk.text
        assert quote_resolves(path, section.segments, chunk.text.split("\n")[0]), section.anchor


@pytest.mark.asyncio
async def test_mapping_rows_stored_with_page(clean_db):
    """Proves: the IPC<->BNS mapping is stored with its source page for citation."""
    from src.database import AsyncSessionLocal

    out = await ingest_mapping(MAPPING)
    async with AsyncSessionLocal() as db:
        n = (await db.execute(select(func.count(IpcBnsMapping.id)))).scalar()
        distinct = (await db.execute(select(func.count(func.distinct(IpcBnsMapping.bns_section))))).scalar()
    assert n == out["mapping_rows"] and distinct == 358
