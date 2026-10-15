"""Regenerate data/raw/manifest.json from the files in data/raw/.

Static metadata (act names, URLs, body page ranges, expected counts) lives in META
below and was recorded by hand from the sources; sha256, page count and
retrieved_at (file mtime) are computed. Review the diff before committing.
"""
import datetime as dt
import json
import os
import sys

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.provenance import sha256_of  # noqa: E402

RAW = "data/raw"

META = {
    "bns_2023.pdf": dict(
        role="corpus", act_short_name="bns_2023", act_title="Bharatiya Nyaya Sanhita", year=2023,
        jurisdiction="central", body_pages=[1, 102], toc_pages=None, titles_in_text=False,
        expected_sections=358, expected_basis="third-party sources cite 358; the file has no table of contents",
        drop_spans=[{"page": 1, "from": "vlk/kkj.k", "to": "CG-DL-E-25122023-250883"}],
        source_url="https://www.mha.gov.in/sites/default/files/2024-04/250883_english_01042024.pdf",
        version_note="As enacted (Gazette, 25 Dec 2023, Act 45 of 2023). Commencement date not yet verified from an official source.",
    ),
    "arms_act_1959.pdf": dict(
        role="corpus", act_short_name="arms_act_1959", act_title="Arms Act", year=1959,
        jurisdiction="central", body_pages=[3, 26], toc_pages=[1, 2], titles_in_text=True,
        expected_sections=48, expected_basis="count of the file's arrangement of sections",
        source_url="https://indiacode.gov.in/pdf-viewer/78a46eb4-21bf-49ee-bd08-6b8e8655631c/6330f0c6-34aa-48fe-a110-43253c8c784c",
        version_note="India Code consolidated copy; 'as on' date not stated in the file.",
    ),
    "it_act_2000.pdf": dict(
        role="corpus", act_short_name="it_act_2000", act_title="Information Technology Act", year=2000,
        jurisdiction="central", body_pages=[5, 35], toc_pages=[1, 4], titles_in_text=True,
        expected_sections=125, expected_basis="count of the file's arrangement of sections",
        source_url="https://indiacode.gov.in/pdf-viewer/d41fe391-b9c0-40b1-afdc-ad034c7ac62f/770a7d02-48f2-4274-bab9-10d0f48ee264",
        version_note="India Code consolidated copy; 'as on' date not stated in the file.",
    ),
    "mv_act_1988.pdf": dict(
        role="corpus", act_short_name="mv_act_1988", act_title="Motor Vehicles Act", year=1988,
        jurisdiction="central", body_pages=[10, 120], toc_pages=[3, 9], titles_in_text=True,
        expected_sections=257, expected_basis="count of the file's arrangement of sections",
        source_url="https://indiacode.gov.in/pdf-viewer/2bbbcc40-38f1-4b15-ae94-646b85db4ee7/1d30ea4a-1331-4791-89bf-b820172bf790",
        version_note="India Code consolidated copy, 'As on the 15th August, 2026' (file page 1). First Schedule (pp. 121-172) is image-only and not ingested.",
    ),
    "ipc_1860.pdf": dict(
        role="not_ingested", act_short_name="ipc_1860", act_title="Indian Penal Code", year=1860,
        jurisdiction="central", source_url="https://www.hyderabadpolice.gov.in/PDF/acts/Indianpenalcode1860.pdf",
        version_note="Police-department website print with commentary blocks; not an official source; not ingested (decision 15).",
    ),
    "tn_dangerous_activities_1982.pdf": dict(
        role="not_ingested", act_short_name="tn_dangerous_activities_1982",
        act_title="Tamil Nadu Prevention of Dangerous Activities Act", year=1982, jurisdiction="tamil_nadu",
        source_url="https://prsindia.org/files/bills_acts/acts_states/tamil-nadu/1982/1982TN14.pdf",
        version_note="PRS India OCR scan with visible OCR errors; not ingested (decision 17).",
    ),
    "bns_ipc_comparison_keralaprisons.pdf": dict(
        role="mapping", act_short_name=None, act_title="Correspondence table and comparison summary BNS to IPC",
        year=2023, jurisdiction="central",
        source_url="https://www.keralaprisons.gov.in/userfiles/act-and-rules/comparison_summary_BNS_to_IPC.pdf",
        version_note="Credited to Anil Kishore Yadav, IPS, Director CAPT Bhopal; not an MHA publication.",
    ),
}
META["tn_harassment_women_1998.pdf"] = dict(
    role="corpus", act_short_name="tn_harassment_women_1998",
    act_title="Tamil Nadu Prohibition of Harassment of Women Act", year=1998,
    jurisdiction="tamil_nadu", body_pages=[1, 4], toc_pages=None, titles_in_text=True,
    expected_sections=14, expected_basis="continuity of section numbers; the file has no table of contents",
    source_url="https://www.tnscw.tn.gov.in/departments_cms/uploads/tami_868/subpage_files/The_Tamil_Nadu_Prohibition_Of_Harassment_Of_Women_Act_1998.PDF",
    version_note="Indian Kanoon print hosted on a TN government site: 'version of this document from 21 December 2016'; the file states its content could not be verified. s.5(1) clauses are missing in the source.",
)


def main() -> None:
    files = []
    for name, meta in META.items():
        path = os.path.join(RAW, name)
        if not os.path.exists(path):
            print("MISSING", name)
            continue
        entry = dict(file=name, **meta)
        entry["sha256"] = sha256_of(path)
        entry["page_count"] = len(pymupdf.open(path))
        entry["retrieved_at"] = dt.datetime.fromtimestamp(os.path.getmtime(path)).astimezone().isoformat(timespec="minutes")
        entry["retrieved_at_basis"] = "file modification time on the machine that downloaded it"
        files.append(entry)
    with open(os.path.join(RAW, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"files": files}, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("wrote", len(files), "entries")


if __name__ == "__main__":
    main()
