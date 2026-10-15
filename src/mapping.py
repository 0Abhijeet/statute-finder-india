"""IPC<->BNS correspondence table -> rows. Source is the CAPT Bhopal comparison PDF
(not an MHA publication; see manifest). Rows keep the page they came from."""
import re
from dataclasses import dataclass

import pymupdf

BNS_REF_RE = re.compile(r"^\s*(\d{1,3})(?![0-9A-Za-z])(?:\s*\([0-9A-Za-z]{1,3}\)|\s+\d{1,3}\([0-9A-Za-z]{1,3}\))*\s*$")


@dataclass
class MappingRow:
    bns_ref: str            # "85", "2(2)", "103(1)"
    bns_section: int        # 85, 2, 103
    subject: str
    ipc_ref: str            # "498A", "New", "498A Explanation", ...
    summary: str
    page: int               # 1-indexed page of the comparison PDF


def _cell(v) -> str:
    return re.sub(r"\s+", " ", (v or "").strip())


def parse_mapping(path: str) -> list[MappingRow]:
    doc = pymupdf.open(path)
    rows: list[MappingRow] = []
    for pno, page in enumerate(doc, start=1):
        for table in page.find_tables().tables:
            for r in table.extract():
                cells = [_cell(c) for c in r]
                # Header rows have 6 cells with BNS/IPC captions; data rows have 4.
                if len(cells) == 6:
                    cells = [c for c in cells if c != ""] or cells
                if len(cells) < 4:
                    continue
                ref, subject, ipc, summary = cells[0], cells[1], cells[2], cells[3]
                m = BNS_REF_RE.match(ref)
                if m:
                    rows.append(MappingRow(ref.replace(" ", ""), int(m.group(1)), subject, ipc, summary, pno))
                elif rows and not ref and any(cells[1:]):
                    # continuation of the previous row onto a new page/cell
                    prev = rows[-1]
                    prev.subject = (prev.subject + " " + subject).strip()
                    prev.summary = (prev.summary + " " + summary).strip()
    return rows
