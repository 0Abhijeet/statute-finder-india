"""PDF -> sections, with provenance captured at parse time.

A section is stored as a list of Segments. Each Segment is an exact slice of one
page's raw PyMuPDF text (`page.get_text()`), so a stored citation can later be
re-verified by re-reading the file: raw_page_text[start:end] == segment text.
Footnote blocks, page numbers and chapter headings are excluded by slicing, never
by editing text.
"""
import re
from dataclasses import dataclass, field

import pymupdf

# "12.", "12A.", "4-A.", optionally preceded by an amendment marker like "1[".
HEAD_RE = re.compile(r"^\s*(?:\d{1,2}\[)?\s*(\d{1,3}(?:-?[A-Z]{1,2})?)\.\s*(\S.*)$")
# What a footnote line starts with after its number ("1. Ins. by Act ..."). Kept
# strict on purpose: a loose prefix like "Rep" rejects the real heading
# "46. Repeal of Act 11 of 1878" (found in the Arms Act).
FOOT_RE = re.compile(
    r"^(Ins\.|Subs\.|Sub\.|Omitted|Rep\.|Added|The words|The figures?|The brackets|"
    r"Clause|Sub-?section|Proviso|Came into|Substituted|Inserted|Repealed by|"
    r"Renumbered|Re-numbered|w\.e\.f|See |Vide |Now |Cl\.|S\.\s)",
    re.I,
)
CHAPTER_RE = re.compile(r"^\s*CHAPTER\s*([IVXLC]+[A-Z]?|\d{1,2}[A-Z]?)\s*$")
LEAD_JUNK_RE = re.compile(r"^\s*(THE GAZETTE OF INDIA EXTRAORDINARY|\[Part II.*|Sec\. ?\d+\])\s*$")
DASHES = "—―–"

def _is_omitted(rest: str) -> bool:
    """Heading line says "[Omitted.]" / "... Omitted by ..." (not merely mentions repeal)."""
    r = re.sub(r"^\d{1,2}\[", "", rest.strip())
    head = r[:160]
    return bool(
        (r.startswith("[") and re.search(r"Omitted|Repealed", head))
        or re.search(r"[^A-Za-z](Omitted|Repealed) by[^A-Za-z]", head)
    )


_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X",
          11: "XI", 12: "XII", 13: "XIII", 14: "XIV", 15: "XV", 16: "XVI", 17: "XVII", 18: "XVIII", 19: "XIX", 20: "XX"}


def _chapter_label(raw: str) -> str:
    return _ROMAN.get(int(raw), raw) if raw.isdigit() else raw


@dataclass
class Segment:
    page: int      # 1-indexed
    start: int     # offset into page.get_text()
    end: int


@dataclass
class ParsedSection:
    number: str
    title: str | None
    chapter: str | None          # e.g. "VI"
    chapter_title: str | None
    status: str                  # "in_force" | "omitted"
    segments: list[Segment] = field(default_factory=list)
    text: str = ""

    @property
    def page_start(self) -> int:
        return self.segments[0].page

    @property
    def page_end(self) -> int:
        return self.segments[-1].page


def _key(number: str) -> tuple[int, str]:
    m = re.match(r"(\d+)-?([A-Z]*)$", number)
    return int(m.group(1)), m.group(2)


def normalise_number(number: str) -> str:
    """'4-A' -> '4A' so ids are consistent with the rest of the corpus."""
    return number.replace("-", "")


def _clean_title(rest: str, next_line: str | None) -> str | None:
    cand = re.sub(r"^\d{1,2}\[", "", rest.strip())
    if not any(d in cand for d in DASHES) and next_line and not next_line.strip().startswith("("):
        cand = cand + " " + next_line.strip()
    idx = min((cand.find(d) for d in DASHES if d in cand), default=-1)
    if idx <= 0:
        return None
    title = re.sub(r"\d{1,2}\[|\]", "", cand[:idx]).strip(" .")
    if not title or len(title) > 200:
        return None
    return title


def parse_act(path: str, body_pages: tuple[int, int], titles: bool = True,
              drop_spans: list[dict] | None = None) -> list[ParsedSection]:
    """`titles=False` for sources whose text layer carries no section headings (BNS, MHA
    file): a dash inside the first sentence must not be mistaken for a title.

    `drop_spans`: [{"page", "from", "to"}] literal markers; the text from the start of
    "from" to the end of "to" on that page (Gazette front matter that PyMuPDF extracts
    in the middle of section 1) is left out by slicing around it, never by editing."""
    doc = pymupdf.open(path)
    spans: dict[int, list[tuple[int, int]]] = {}
    for d in drop_spans or []:
        raw_p = doc[d["page"] - 1].get_text()
        a = raw_p.find(d["from"])
        b = raw_p.find(d["to"], a)
        if a < 0 or b < 0:
            raise ValueError(f"drop_span markers not found on page {d['page']}: {d}")
        spans.setdefault(d["page"], []).append((a, b + len(d["to"])))
    sections: list[ParsedSection] = []
    current: ParsedSection | None = None
    last_key = (0, "")
    chapter = chapter_title = None

    for pno in range(body_pages[0], body_pages[1] + 1):
        raw = doc[pno - 1].get_text()
        lines = raw.split("\n")
        starts, o = [], 0
        for ln in lines:
            starts.append(o)
            o += len(ln) + 1

        # Footnote block: from the first "N. Ins./Subs./..." line to page end.
        cut = len(raw)
        for ln, s in zip(lines, starts):
            m = HEAD_RE.match(ln)
            if m and FOOT_RE.match(m.group(2)):
                cut = s
                break
        # Running page footer (BNS Gazette): optional "N" or "Sec. N]", then "THE GAZETTE
        # OF INDIA EXTRAORDINARY", then rows of underscores (which also appear alone at
        # the top of the last page; those are skipped as leading rule lines). PyMuPDF extracts it at the
        # end of the page text; cut it (and anything after) like a footnote block.
        for i, (ln, s) in enumerate(zip(lines, starts)):
            if s >= cut:
                break
            if ln.strip() == "THE GAZETTE OF INDIA EXTRAORDINARY":
                if len(re.sub(r"[^A-Za-z]", "", raw[:s])) < 40:
                    break  # header at the top of the page (e.g. last page): not a footer
                if i > 0 and re.fullmatch(r"\s*(\d+|Sec\.\s*\d+\])\s*", lines[i - 1]):
                    cut = min(cut, starts[i - 1])
                else:
                    cut = min(cut, s)
                break
        # End-of-act rule ("—————") followed by the Gazette signature block: cut there.
        for ln, st in zip(lines, starts):
            if st < cut and re.fullmatch(r"\s*—{5,}\s*", ln):
                cut = st
                break
        # Skip leading blank / bare page-number lines.
        content_start = 0
        for ln, s in zip(lines, starts):
            if not ln.strip() or re.fullmatch(r"\s*\d{1,3}\s*", ln) or re.fullmatch(r"\s*_{10,}\s*", ln) or LEAD_JUNK_RE.match(ln):
                content_start = s + len(ln) + 1
            else:
                break

        # Events on this page, in order: (offset, kind, payload, line_index)
        events = []
        skip_until = -1
        for i, (ln, s) in enumerate(zip(lines, starts)):
            if s >= cut or s < content_start or s <= skip_until:
                continue
            cm = CHAPTER_RE.match(ln)
            if cm:
                j, tl = i + 1, []
                while j < len(lines) and starts[j] < cut:
                    t = lines[j].strip()
                    if t and t == t.upper() and not HEAD_RE.match(lines[j]) and re.search(r"[A-Z]", t):
                        tl.append(t)
                        j += 1
                    elif not t and not tl:
                        j += 1
                    else:
                        break
                end = starts[j] if j < len(lines) else cut
                events.append((s, "chapter", (cm.group(1), " ".join(tl) or None, end), i))
                skip_until = end - 1
                continue
            hm = HEAD_RE.match(ln)
            if hm and not FOOT_RE.match(hm.group(2)):
                k = _key(normalise_number(hm.group(1)))
                if k > last_key and (k[0] - last_key[0] <= 15 or last_key == (0, "")):
                    nxt = lines[i + 1] if i + 1 < len(lines) else None
                    events.append((s, "section", (hm, nxt), i))
                    last_key = k

        pos = content_start
        for off, kind, payload, _ in events:
            if current is not None and off > pos:
                _close_piece(current, pno, raw, pos, off, spans.get(pno, []))
            if kind == "chapter":
                raw_ch, chapter_title, endoff = payload
                chapter = _chapter_label(raw_ch)
                current = None
                pos = endoff
            else:
                hm, nxt = payload
                rest = hm.group(2)
                status = "omitted" if _is_omitted(rest) else "in_force"
                lead = len(raw[off:]) - len(raw[off:].lstrip())
                current = ParsedSection(
                    number=normalise_number(hm.group(1)),
                    title=_clean_title(rest, nxt) if titles else None,
                    chapter=chapter,
                    chapter_title=chapter_title,
                    status=status,
                )
                sections.append(current)
                pos = off + lead
        if current is not None and cut > pos:
            _close_piece(current, pno, raw, pos, cut, spans.get(pno, []))

    for sec in sections:
        sec.text = "\n".join(doc[s.page - 1].get_text()[s.start:s.end] for s in sec.segments)
    return sections


def _close_piece(sec: ParsedSection, pno: int, raw: str, start: int, end: int,
                 drop: list[tuple[int, int]] | None = None) -> None:
    """Append [start, end) of page `pno` as segments, leaving out any dropped spans."""
    cursor = start
    for da, db in sorted(drop or []):
        if db <= cursor or da >= end:
            continue
        _append(sec, pno, raw, cursor, min(da, end))
        cursor = max(cursor, db)
    _append(sec, pno, raw, cursor, end)


def _append(sec: ParsedSection, pno: int, raw: str, start: int, end: int) -> None:
    if end <= start:
        return
    piece = raw[start:end]
    end = start + len(piece.rstrip())
    start = end - len(piece.rstrip().lstrip()) if piece.strip() else start
    if end > start:
        sec.segments.append(Segment(pno, start, end))
