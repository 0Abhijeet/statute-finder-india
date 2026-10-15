"""Parser, provenance, chunking and mapping tests. No database needed.

These read the real PDFs in data/raw/, so they double as drift detectors: a
replaced file or a changed parser fails here, not silently in the demo.
"""
import copy
import os

import pytest

from src.chunking import MAX_CHARS, MIN_TAIL_CHARS, chunk_text
from src.ingest import RAW_DIR, load_manifest, verify_files
from src.mapping import parse_mapping
from src.parsing import parse_act
from src.provenance import locate_quote, quote_resolves, read_segments

MANIFEST = load_manifest()
CORPUS = [e for e in MANIFEST if e["role"] == "corpus"]
RAW = lambda name: os.path.join(RAW_DIR, name)  # noqa: E731


@pytest.fixture(scope="module")
def parsed():
    return {
        e["act_short_name"]: parse_act(RAW(e["file"]), tuple(e["body_pages"]), e["titles_in_text"], e.get("drop_spans"))
        for e in CORPUS
    }


def test_manifest_hashes_match_files():
    """Proves: a replaced or re-downloaded PDF is noticed before it is ingested."""
    verify_files(MANIFEST)


@pytest.mark.parametrize("entry", CORPUS, ids=lambda e: e["act_short_name"])
def test_section_count_matches_expected(entry, parsed):
    """Proves: parser count sanity per act (see manifest expected_basis)."""
    secs = parsed[entry["act_short_name"]]
    assert len(secs) == entry["expected_sections"]
    assert len({s.number for s in secs}) == len(secs), "duplicate section numbers"


@pytest.mark.parametrize("entry", [e for e in CORPUS if e.get("toc_pages")], ids=lambda e: e["act_short_name"])
def test_body_ids_equal_toc_ids(entry, parsed):
    """Proves: every section in the file's own arrangement of sections was found, and no extra."""
    toc = parse_act(RAW(entry["file"]), tuple(entry["toc_pages"]), True)
    assert {s.number for s in toc} == {s.number for s in parsed[entry["act_short_name"]]}


@pytest.mark.parametrize("entry", CORPUS, ids=lambda e: e["act_short_name"])
def test_segments_reproduce_text_exactly(entry, parsed):
    """Proves: stored text is an exact slice of the PDF at the stored offsets (no editing)."""
    for s in parsed[entry["act_short_name"]]:
        segs = [{"page": g.page, "start": g.start, "end": g.end} for g in s.segments]
        assert read_segments(RAW(entry["file"]), segs) == s.text
        assert s.page_start <= s.page_end and s.text.strip()


def test_known_section_text_bns_103(parsed):
    """Spot check against the real text: BNS s.103 is the murder punishment."""
    s103 = next(s for s in parsed["bns_2023"] if s.number == "103")
    assert s103.text.startswith("103. (1) Whoever commits murder shall be punished")
    assert s103.chapter == "VI"


def test_omitted_sections_flagged(parsed):
    """Proves: omitted sections (decision 16) are detected so they can be excluded from retrieval."""
    omitted = {s.number for s in parsed["it_act_2000"] if s.status == "omitted"}
    assert {"20", "49", "52A"} <= omitted


def test_quote_resolves_and_tampered_offsets_are_rejected(parsed):
    """Addendum item 6: a row whose stored offset does not contain the quote is rejected."""
    entry = next(e for e in CORPUS if e["act_short_name"] == "bns_2023")
    s103 = next(s for s in parsed["bns_2023"] if s.number == "103")
    segs = [{"page": g.page, "start": g.start, "end": g.end} for g in s.segments] if False else \
           [{"page": g.page, "start": g.start, "end": g.end} for g in s103.segments]
    quote = "Whoever commits murder shall be punished with death or imprisonment for"
    assert quote_resolves(RAW(entry["file"]), segs, quote)
    loc = locate_quote(RAW(entry["file"]), segs, quote)
    assert loc and loc["page"] == s103.page_start

    wrong_page = copy.deepcopy(segs)
    wrong_page[0]["page"] = wrong_page[0]["page"] + 1
    assert not quote_resolves(RAW(entry["file"]), wrong_page, quote)

    shifted = copy.deepcopy(segs)
    shifted[0]["start"] += 400
    shifted[0]["end"] += 400
    assert not quote_resolves(RAW(entry["file"]), shifted, quote)

    assert not quote_resolves(RAW(entry["file"]), segs, "a sentence that is not in the Act")
    assert not quote_resolves(RAW(entry["file"]), segs, "")


def test_chunks_cover_each_section_without_gaps(parsed):
    """Proves: chunking neither loses nor duplicates text; chunks respect the size cap."""
    for secs in parsed.values():
        for s in secs:
            cs = chunk_text(s.text)
            assert cs[0][0] == 0 and cs[-1][1] == len(s.text)
            assert all(a[1] == b[0] for a, b in zip(cs, cs[1:]))
            assert all(b - a <= MAX_CHARS + MIN_TAIL_CHARS for a, b in cs)
            assert len(cs) == 1 or all(b - a >= MIN_TAIL_CHARS for a, b in cs), s.number


def test_mapping_covers_every_bns_section():
    """Proves: the IPC<->BNS table parse reaches all 358 BNS sections (a parse-drift check)."""
    entry = next(e for e in MANIFEST if e["role"] == "mapping")
    rows = parse_mapping(RAW(entry["file"]))
    assert {r.bns_section for r in rows} == set(range(1, 359))
    assert all(r.page >= 1 for r in rows)


def test_no_page_footer_or_rule_lines_in_section_text(parsed):
    """Proves: running page footers (Gazette header, rows of underscores) are not
    stored as statute text. Found in the first ingest: 106 of 1,032 chunks."""
    import re

    for secs in parsed.values():
        for s in secs:
            assert "THE GAZETTE OF INDIA EXTRAORDINARY" not in s.text, s.number
            assert not re.search(r"_{10,}", s.text), s.number


def test_bns_s1_and_s358_have_no_gazette_front_matter_or_signature(parsed):
    """Proves: the sections quoted for commencement/repeal are clean (found when reading s.1
    and s.358 back: Gazette header lines and a digital-signature block were inside them)."""
    by = {s.number: s for s in parsed["bns_2023"]}
    for n in ("1", "358"):
        t = by[n].text
        for junk in ("EXTRAORDINARY", "PUBLISHED BY AUTHORITY", "xxxGIDH", "DIWAKAR SINGH", "Digitally signed"):
            assert junk not in t, (n, junk)
    assert "come intoforce on such date as the Central Government may" in by["1"].text
    assert "The Indian Penal Code is herebyrepealed" in by["358"].text
