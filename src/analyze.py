"""Phase 4 orchestration: facts + date routing + clarifying questions + retrieval, with
the IPC<->BNS equivalent attached to BNS hits (decision 21). No answer generation yet."""
import dataclasses
import re
from datetime import date

from sqlalchemy import text

from src.clarify import clarifying_questions
from src.database import AsyncSessionLocal
from src.dating import LIMITS, resolve_date
from src.facts import extract_facts
from src.query import clean_query
from src.retrieve import citation, retrieve
from src.severity import assess_harm
from src.status import statuses_for

DISCLAIMER = "Informational, not legal advice."


def _bns_int(number: str) -> int | None:
    m = re.match(r"\d+", number)
    return int(m.group()) if m else None


async def _mapping_for(bns_numbers: list[int]) -> dict[int, list[dict]]:
    if not bns_numbers:
        return {}
    async with AsyncSessionLocal() as db:
        rows = await db.execute(text("""
            select m.bns_section, m.bns_ref, m.ipc_ref, m.subject, m.summary, m.page, sf.filename, sf.source_url
            from ipc_bns_mapping m join source_files sf on sf.id = m.source_file_id
            where m.bns_section = any(:ns) order by m.bns_section, m.id"""), {"ns": bns_numbers})
        out: dict[int, list[dict]] = {}
        for r in rows:
            out.setdefault(r.bns_section, []).append({
                "bns_ref": r.bns_ref, "ipc_ref": r.ipc_ref, "subject": r.subject, "change_summary": r.summary,
                "mapping_source": f"page {r.page} of {r.filename}", "mapping_source_url": r.source_url,
                "mapping_source_note": "comparison table by CAPT Bhopal; not an MHA publication"})
        return out


async def analyze(incident: str, incident_date: str | None = None, today: date | None = None,
                  k_per_act: int = 3, k_final: int = 8) -> dict:
    facts, meta = await extract_facts(incident)
    date_info = resolve_date(incident, incident_date, today)
    # Deterministic severity rule: the harm fact is overridden only when the text lacks an
    # explicit severity cue. It affects the facts and questions, never retrieval below.
    sev = assess_harm(incident, facts)
    facts = facts.model_copy(update={"harm": sev.harm})
    questions, conditions = clarifying_questions(facts, date_info, incident, sev)
    retrieval_query = clean_query(incident)  # decision 41: meta words/dates out, retrieval only
    hits = await retrieve(retrieval_query, k_per_act=k_per_act, k_final=k_final)  # query text only
    async with AsyncSessionLocal() as db:
        flags = await statuses_for(db, [h.anchor for h in hits])

    show_ipc = date_info["regime"] in ("ipc", "ambiguous")
    mapping: dict[int, list[dict]] = {}
    if show_ipc:
        nums = {n for h in hits if h.act == "bns_2023" and (n := _bns_int(h.number)) is not None}
        mapping = await _mapping_for(sorted(nums))

    results = []
    for h in hits:
        d = dataclasses.asdict(h)
        d["citation"] = citation(h)
        if show_ipc and h.act == "bns_2023":
            n = _bns_int(h.number)
            d["ipc_equivalents"] = mapping.get(n, []) if n is not None else []
            d["label"] = ("equivalent current provision (BNS, in force from 1 July 2024); "
                          "the IPC text is not in the corpus")
        if h.anchor in flags:
            d["legal_status"] = flags[h.anchor]
        results.append(d)

    return {
        "incident": incident,
        "retrieval_query": retrieval_query,
        "facts": facts.model_dump(mode="json"),
        "extraction": meta,
        "severity": {"injury_described": sev.injury_described, "established": sev.established,
                     "source": sev.source, "cues": sev.cues, "llm_harm": sev.llm_harm.value if sev.llm_harm else None},
        "date": date_info,
        "questions": questions,
        "open_conditions": conditions,
        "results": results,
        "limits": LIMITS,
        "disclaimer": DISCLAIMER,
    }
