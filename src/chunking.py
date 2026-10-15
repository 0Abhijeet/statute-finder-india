"""Decision 18: a section becomes one chunk if it is short, otherwise sub-chunks
cut at sub-section boundaries "(1)", "(2)". Provisos and illustrations never start a
chunk: they stay with the sub-section they follow. Decision 19: the embedded string
is header + text; the header is stored separately and never shown as the quote."""
import re

MAX_CHARS = 2000
MIN_TAIL_CHARS = 60
_SUB_RE = re.compile(r"(?m)^\(\d{1,2}[A-Z]?\)")


def chunk_text(text: str, max_chars: int = MAX_CHARS) -> list[tuple[int, int]]:
    """Return (start, end) offsets into `text`; consecutive ranges cover it fully."""
    if len(text) <= max_chars:
        return [(0, len(text))]
    cuts = [m.start() for m in _SUB_RE.finditer(text)]
    # Pieces at sub-section boundaries; anything before the first "(1)" stays with it.
    bounds = sorted({0, *cuts, len(text)})
    pieces = list(zip(bounds, bounds[1:]))
    # Hard-split any single piece that is still too long, at line breaks.
    fine: list[tuple[int, int]] = []
    for a, b in pieces:
        if b - a <= max_chars:
            fine.append((a, b))
            continue
        pos = a
        while b - pos > max_chars:
            nl = text.rfind("\n", pos + 1, pos + max_chars)
            cut = nl + 1 if nl > pos else pos + max_chars
            fine.append((pos, cut))
            pos = cut
        fine.append((pos, b))
    # Greedily merge neighbours while they fit.
    merged: list[tuple[int, int]] = []
    for a, b in fine:
        # A tiny tail ("harm.") is never its own chunk: attach it to the previous one.
        if merged and (b - merged[-1][0] <= max_chars or b - a < MIN_TAIL_CHARS):
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return merged


def build_header(act_title: str, year: int, chapter: str | None, number: str, title: str | None) -> str:
    parts = [f"{act_title} {year}"]
    if chapter:
        parts.append(f"Chapter {chapter}")
    parts.append(f"s.{number}" + (f" {title}" if title else ""))
    return " | ".join(parts)
