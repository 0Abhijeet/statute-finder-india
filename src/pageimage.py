"""Render the cited PDF page with the quoted text highlighted (decision 46; addendum
item 7). Works from the stored chunk text and the section's stored segments, i.e. the
same slices the validator checks, then finds those lines on the page with PyMuPDF."""
import os

import pymupdf
from sqlalchemy import text

from src.database import AsyncSessionLocal

RAW_DIR = "data/raw"


async def chunk_source(chunk_id: int) -> dict | None:
    async with AsyncSessionLocal() as db:
        r = (await db.execute(text("""
            select c.text, s.segments, s.anchor, sf.filename
            from chunks c join sections s on s.id = c.section_id
            join source_files sf on sf.id = s.source_file_id where c.id = :i"""), {"i": chunk_id})).first()
    if r is None:
        return None
    return {"text": r.text, "segments": r.segments, "anchor": r.anchor, "filename": r.filename}


MAX_LINE_GAP = 60.0  # points: the next quote line must sit just below the previous one


def _contiguous_rects(per_line: list[list]) -> list:
    """per_line[i] = every rectangle where quote line i occurs on the page. Repeated legal
    phrases occur in many places, so pick the single top-to-bottom chain of lines that
    matches the most consecutive quote lines (earliest on ties)."""
    per_line = [sorted(rs, key=lambda r: (r.y0, r.x0)) for rs in per_line if rs]
    if not per_line:
        return []
    best: list = []
    for start in per_line[0]:
        chain, y = [start], start.y0
        for rs in per_line[1:]:
            nxt = next((r for r in rs if y - 2 <= r.y0 <= y + MAX_LINE_GAP), None)
            if nxt is None:
                break
            chain.append(nxt)
            y = nxt.y0
        if len(chain) > len(best):
            best = chain
    return best


def render_highlight(path: str, segments: list[dict], quote: str, zoom: float = 1.6) -> tuple[bytes, int]:
    """Returns (png bytes, 1-indexed page). Highlights each line of the quote that sits on
    the first page that contains any of it."""
    doc = pymupdf.open(path)
    lines = [ln.strip() for ln in quote.split("\n") if len(ln.strip()) >= 4]
    for seg in segments:
        page = doc[seg["page"] - 1]
        raw = page.get_text()[seg["start"]:seg["end"]]
        here = [ln for ln in lines if ln in raw]
        if not here:
            continue
        for rect in _contiguous_rects([page.search_for(ln) for ln in here]):
            page.add_highlight_annot(rect)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), annots=True)
        return pix.tobytes("png"), seg["page"]
    # Quote not found on any stored segment: render the section's first page, unhighlighted.
    page = doc[segments[0]["page"] - 1]
    return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png"), segments[0]["page"]


def pdf_path(filename: str) -> str:
    # filename comes from the database (source_files.filename), never from the request
    return os.path.join(RAW_DIR, os.path.basename(filename))
