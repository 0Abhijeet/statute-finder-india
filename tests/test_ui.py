"""Demo surface (decision 46): HTML page, health, and the highlighted page image."""
import os

import pymupdf
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.database import AsyncSessionLocal
from src.ingest import RAW_DIR, ingest_act, load_manifest
from src.pageimage import render_highlight
from tests.test_ingest import clean_db  # noqa: F401

MANIFEST = {e["file"]: e for e in load_manifest()}
PNG = b"\x89PNG\r\n\x1a\n"


@pytest_asyncio.fixture
async def tn(clean_db):  # noqa: F811
    await ingest_act(MANIFEST["tn_harassment_women_1998.pdf"])


async def _chunk_for(anchor: str) -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(text(
            "select c.id from chunks c join sections s on s.id = c.section_id where s.anchor = :a order by c.chunk_no limit 1"),
            {"a": anchor})).scalar()


@pytest.mark.asyncio
async def test_index_and_health():
    from src.app import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/")
        h = await c.get("/health")
    assert r.status_code == 200 and "Statute Finder India" in r.text and "/page-image?chunk_id=" in r.text
    assert "Informational, not legal advice" in r.text
    body = h.json()
    assert body["status"] == "ok"
    assert body["build"]            # marker of the code this process loaded (shown in the page footer)


@pytest.mark.asyncio
async def test_page_image_is_a_png_of_the_cited_page_and_differs_from_the_plain_page(tn):
    """Proves: the endpoint renders the cited page (not an arbitrary file) with a highlight."""
    from src.app import app

    cid = await _chunk_for("tn_harassment_women_1998:s4")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/page-image", params={"chunk_id": cid})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content.startswith(PNG)
    assert r.headers["x-source-page"] == "2"        # TN s.4 is on page 2 of the source PDF
    plain = pymupdf.open(os.path.join(RAW_DIR, "tn_harassment_women_1998.pdf"))[1].get_pixmap(
        matrix=pymupdf.Matrix(1.6, 1.6)).tobytes("png")
    assert r.content != plain


@pytest.mark.asyncio
async def test_page_image_unknown_chunk_is_404_and_bad_id_is_422(tn):
    from src.app import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/page-image", params={"chunk_id": 99999999})).status_code == 404
        assert (await c.get("/page-image", params={"chunk_id": "../../etc/passwd"})).status_code == 422


def test_render_highlight_falls_back_to_unhighlighted_first_page_when_quote_not_found():
    path = os.path.join(RAW_DIR, "tn_harassment_women_1998.pdf")
    png, page = render_highlight(path, [{"page": 2, "start": 0, "end": 50}], "text that is not on this page at all")
    assert png.startswith(PNG) and page == 2


def test_contiguous_rects_picks_the_chain_not_repeated_phrases_elsewhere():
    """Proves: a phrase repeated in other sections does not get highlighted: only the
    top-to-bottom chain matching the most consecutive quote lines is kept."""
    from src.pageimage import _contiguous_rects

    R = pymupdf.Rect
    line1 = [R(10, 100, 200, 112)]                       # unique first line
    line2 = [R(10, 40, 200, 52), R(10, 114, 200, 126)]   # repeated elsewhere (y=40) and the real one (y=114)
    line3 = [R(10, 128, 200, 140), R(10, 300, 200, 312)]
    got = _contiguous_rects([line1, line2, line3])
    assert [round(r.y0) for r in got] == [100, 114, 128]
    assert _contiguous_rects([]) == [] and _contiguous_rects([[], []]) == []
