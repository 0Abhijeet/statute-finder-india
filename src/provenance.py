"""Re-verify a stored citation against the source file.

The DB stores, per section, the page + char offsets of every segment. A quote
"resolves" only if it occurs in the text re-read from the PDF at exactly those
offsets. True by construction when parsing is right; its value is catching
parser drift or a replaced file.
"""
import hashlib
from functools import lru_cache

import pymupdf


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@lru_cache(maxsize=16)
def _open(path: str):
    return pymupdf.open(path)


def read_segments(path: str, segments: list[dict]) -> str:
    doc = _open(path)
    return "\n".join(doc[s["page"] - 1].get_text()[s["start"]:s["end"]] for s in segments)


def quote_resolves(path: str, segments: list[dict], quote: str) -> bool:
    """True iff `quote` appears in the text re-read from `path` at the stored offsets."""
    if not quote:
        return False
    return quote in read_segments(path, segments)


def locate_quote(path: str, segments: list[dict], quote: str) -> dict | None:
    """Page and in-page offsets of the quote, or None if it does not resolve."""
    doc = _open(path)
    for s in segments:
        text = doc[s["page"] - 1].get_text()[s["start"]:s["end"]]
        i = text.find(quote)
        if i >= 0:
            return {"page": s["page"], "char_start": s["start"] + i, "char_end": s["start"] + i + len(quote)}
    return None
