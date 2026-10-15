"""Phase 5: generation + validator + abstention (decisions 37-39).

The LLM only SELECTS and GROUPS retrieved candidates and explains why in a sentence or
two. It sees opaque ids (C1..Cn) and sees no section numbers as ids, so it cannot "emit a
section number from memory" and have it accepted: anything that is not a candidate id is
dropped and logged. Every quote, citation, page and URL in the response is read from the
database; each quote is re-verified against the source PDF at the stored offsets."""
import asyncio
import json
import logging
import os
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text

from src.analyze import analyze
from src.database import AsyncSessionLocal
from src.llm_client import LLM_MODEL, create_with_retry, get_llm_client, reasoning_kwargs
from src.provenance import quote_resolves
from src.retrieve import Hit, citation

log = logging.getLogger("statute.validator")

RAW_DIR = "data/raw"
ABSTAIN_REASONS = {"topic_not_in_corpus", "no_matching_provision"}
SERVER_REASONS = {
    "topic_not_in_corpus": "This tool covers the Bharatiya Nyaya Sanhita, the Arms Act 1959, the Motor Vehicles "
                           "Act 1988, the Information Technology Act 2000 and the Tamil Nadu Prohibition of "
                           "Harassment of Women Act 1998. This incident appears to be outside them.",
    "no_matching_provision": "None of the retrieved provisions applies to the facts described.",
    "validation_failed": "The model's answer could not be validated against the retrieved provisions, so no "
                         "sections are shown.",
    "generation_error": "The answer could not be generated. Please try again.",
}


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    why_it_applies: str = Field(max_length=600)
    plain_summary: str | None = Field(default=None, max_length=900)
    punishment: str | None = Field(default=None, max_length=400)
    applies_when: list[str] = Field(default_factory=list, max_length=4)


class Group(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition: str = Field(max_length=300)
    answer_to: str | None = Field(default=None, max_length=80)  # one of the open question's options
    items: list[Item] = []


class Abstain(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: bool = False
    reason: str | None = None


class ModelAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    abstain: Abstain = Abstain()
    groups: list[Group] = []
    not_applicable: list[str] = []


SYSTEM_PROMPT = """You help a layperson see which provisions of five Indian statutes may be relevant to an incident.
You are given CANDIDATE provisions, each with an id like C1. You may ONLY refer to candidates by those ids.
Return ONE JSON object and nothing else:
{"abstain": {"value": false, "reason": null},
 "groups": [{"condition": "<short condition under which these apply>", "answer_to": "<one option of an open question, or null>", "items": [{"id": "C2", "why_it_applies": "<one or two sentences tied to facts in the incident>", "plain_summary": "<up to three plain-English sentences>", "punishment": "<the punishment as the text states it, or null>", "applies_when": ["<short condition>", "<short condition>"]}]}],
 "not_applicable": ["C5"]}
Rules:
- Use only the candidates' text and the stated facts. Do not use outside knowledge of the law. Never write a section number, act name or case name of your own.
- Put a candidate in a group only if the described facts could satisfy it. Group by the condition that decides which apply (for example the severity of harm, the weapon, whether a death occurred). Use "General" if one condition covers all.
- If an open question is listed, make groups for its possible answers instead of guessing, and set "answer_to" to exactly one of that question's listed values (for example "grievous_hurt"); use null when the group does not depend on the answer.
- plain_summary: summarise the candidate text in plain English for a non-lawyer, in at most three sentences of simple words. Use only that text and add nothing from outside it. Keep every number, duration, fine and section reference exactly as written. Keep conditions ("if", "unless", "provided that"). If the text is a definition or a procedure rather than an offence, say so. It is a reading aid, not a replacement for the text.
- punishment: only if the text states a punishment, copy it faithfully in plain words with its numbers exactly as written; otherwise null.
- applies_when: up to three short conditions taken from the text under which the provision applies; an empty list if none are stated.
- why_it_applies must refer to facts in the incident; it must not quote or invent statute text.
- Candidates that do not fit go in not_applicable.
- If NO candidate applies, set "abstain": {"value": true, "reason": "<code>"} and leave groups empty. Codes: "topic_not_in_corpus" when the subject (for example income tax, building or planning permission, civil disputes such as rent or deposits, family law, employment) is not governed by these five statutes; "no_matching_provision" when the topic is covered but no candidate fits.
- Missing facts are not a reason to abstain: use the open questions."""


def _facts_line(facts: dict) -> str:
    known = {k: v for k, v in facts.items() if v != "unknown"}
    return json.dumps(known) if known else "none stated"


def _build_user_prompt(a: dict, ids: dict[str, dict]) -> str:
    lines = [f"INCIDENT: {a['incident']}", f"STATED FACTS: {_facts_line(a['facts'])}",
             f"DATE: {a['date']['note']}"]
    if a["date"]["regime"] in ("ipc", "ambiguous"):
        lines.append("NOTE: for incidents before 1 July 2024 the Indian Penal Code applied and its text is not "
                     "available. Bharatiya Nyaya Sanhita (BNS) candidates are shown as the EQUIVALENT current "
                     "provisions. Select a BNS candidate if it matches the facts and say in why_it_applies that it "
                     "is the equivalent provision. Do not abstain only because the incident predates the BNS.")
    if a["open_conditions"]:
        lines.append("OPEN QUESTIONS (facts still unknown): " + json.dumps(a["open_conditions"]))
    lines.append("CANDIDATES:")
    for cid, r in ids.items():
        lines.append(f"[{cid}] {r['act_title']} {r['year']}, s.{r['number']}\n{r['text'][:1800]}")
    return "\n".join(lines)


def _parse(raw: str) -> ModelAnswer:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    m = re.search(r"\{.*\}", raw, re.S)
    return ModelAnswer.model_validate(json.loads(m.group(0) if m else raw))


async def _call_llm(user_prompt: str, extra_note: str = "") -> str:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt + extra_note}]
    resp = await create_with_retry(
        get_llm_client(), model=LLM_MODEL, messages=msgs, temperature=0, max_tokens=2000,
        response_format={"type": "json_object"}, **reasoning_kwargs(),
    )
    return resp.choices[0].message.content or ""


def validate_ids(ans: ModelAnswer, valid_ids: set[str]) -> tuple[ModelAnswer, list[str]]:
    """Drop ids outside the candidate set, repeated ids, and groups left empty.
    Returns (clean answer, dropped ids)."""
    dropped, seen, groups = [], set(), []
    for g in ans.groups:
        items = []
        for it in g.items:
            if it.id not in valid_ids:
                dropped.append(it.id)
            elif it.id in seen:
                dropped.append(f"{it.id} (repeated)")
            else:
                seen.add(it.id)
                items.append(it)
        if items:
            groups.append(Group(condition=g.condition, answer_to=g.answer_to, items=items))
    na = [i for i in ans.not_applicable if i in valid_ids and i not in seen]
    dropped += [i for i in ans.not_applicable if i not in valid_ids]
    return ModelAnswer(abstain=ans.abstain, groups=groups, not_applicable=na), dropped


async def _segments_for(anchors: list[str]) -> dict[str, dict]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(text("""
            select s.anchor, s.segments, sf.filename from sections s
            join source_files sf on sf.id = s.source_file_id where s.anchor = any(:a)"""), {"a": anchors})
        return {r.anchor: {"segments": r.segments, "filename": r.filename} for r in rows}


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORDNUM = {"two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
            "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fourteen": "14", "fifteen": "15",
            "twenty": "20", "thirty": "30", "fifty": "50", "hundred": "100", "thousand": "1000",
            "lakh": "100000", "crore": "10000000", "one": "1"}
# "one" is only a figure before a unit ("one year"); elsewhere it is a pronoun.
_WORD_RE = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fourteen|fifteen|twenty|thirty|fifty|"
    r"hundred|thousand|lakh|crore)\b|\b(one)(?=\s+(?:year|years|month|months|day|days|hundred|thousand|lakh|"
    r"crore|rupee|rupees))", re.I)


def _numbers(text_: str) -> set[str]:
    out = {m.group().replace(",", "").rstrip(".") for m in _NUM.finditer(text_)}
    for m in _WORD_RE.finditer(text_):
        out.add(_WORDNUM[(m.group(1) or m.group(2)).lower()])
    return out


def summary_is_grounded(summary: str, sources: list[str]) -> bool:
    """Every figure in a plain-language summary must appear in the verbatim text it
    summarises (a wrong fine or term of years is the damaging failure)."""
    allowed: set[str] = set()
    for src in sources:
        allowed |= _numbers(src)
    return _numbers(summary) <= allowed


_NOT_APPLICABLE = re.compile(
    r"\b(not relevant|not applicable|irrelevant|does not (?:apply|involve|fit|relate)|do not (?:apply|involve)|"
    r"is not the case|not the case here|no relevance)\b", re.I)


def drop_non_applicable(ans: "ModelAnswer") -> tuple["ModelAnswer", list[str]]:
    """Small models sometimes list a candidate in a group while saying it does not apply
    ("not relevant here"). Treat those as not_applicable instead of showing them."""
    groups, moved = [], []
    for g in ans.groups:
        keep = []
        for it in g.items:
            blob = " ".join([g.condition, it.why_it_applies, it.plain_summary or ""])
            if _NOT_APPLICABLE.search(blob):
                moved.append(it.id)
            else:
                keep.append(it)
        if keep:
            groups.append(Group(condition=g.condition, answer_to=g.answer_to, items=keep))
    return ModelAnswer(abstain=ans.abstain, groups=groups,
                       not_applicable=list(dict.fromkeys(ans.not_applicable + moved))), moved


def allowed_answers(open_conditions: list[dict]) -> set[str]:
    return {v for c in open_conditions for v in c.get("values", [])}


_CAND_ID = re.compile(r"\b(?:(?:section|provision|candidate)\s+)?C\d{1,2}\b", re.I)


def _strip_candidate_ids(text: str) -> str:
    """The model sometimes writes "section C1" in its explanation; the opaque ids are internal."""
    return _CAND_ID.sub("the provision", text)


async def _openings(anchors: list[str]) -> dict[str, dict]:
    """First chunk of each section: its operative opening text."""
    if not anchors:
        return {}
    async with AsyncSessionLocal() as db:
        rows = await db.execute(text("""
            select s.anchor, c.id as chunk_id, c.text from chunks c join sections s on s.id = c.section_id
            where s.anchor = any(:a) and c.chunk_no = 0"""), {"a": anchors})
        return {r.anchor: {"chunk_id": r.chunk_id, "text": r.text} for r in rows}


def _abstained(a: dict, reason: str, notices: list[str], **extra) -> dict:
    return {**a, "answer": {"abstained": True, "reason": reason, "message": SERVER_REASONS[reason],
                            "groups": [], "notices": notices}, **extra}


async def answer(incident: str, incident_date: str | None = None, today=None, raw_dir: str = RAW_DIR) -> dict:
    a = await analyze(incident, incident_date, today)
    # The candidate set the validator enforces: retrieved sections, omitted ones never present.
    candidates = a["results"]
    if not candidates:
        return _abstained(a, "no_matching_provision", [])
    ids = {f"C{i}": r for i, r in enumerate(candidates, start=1)}
    prompt = _build_user_prompt(a, ids)
    valid = set(ids)
    notices: list[str] = []
    clean: ModelAnswer | None = None

    for attempt in range(2):
        note = "" if attempt == 0 else (
            "\n\nYour previous answer used ids that are not candidates. Use ONLY these ids: " + ", ".join(sorted(valid)))
        try:
            ans = _parse(await _call_llm(prompt, note))
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            log.warning("model answer failed schema validation: %s", str(e)[:200])
            notices.append("The model returned an answer in an invalid format.")
            continue
        except Exception as e:  # API/network
            log.error("generation error: %s", e)
            notices.append(f"Generation failed: {type(e).__name__}: {str(e)[:120]}")
            return _abstained(a, "generation_error", notices)
        if ans.abstain.value:
            reason = ans.abstain.reason if ans.abstain.reason in ABSTAIN_REASONS else "no_matching_provision"
            return _abstained(a, reason, notices)
        cleaned, dropped = validate_ids(ans, valid)
        cleaned, moved = drop_non_applicable(cleaned)
        if moved:
            log.info("moved %s to not_applicable: the model described them as not applying", moved)
        if dropped:
            log.warning("validator dropped ids not in the retrieved set: %s", dropped)
            notices.append(f"{len(dropped)} model-suggested reference(s) were removed because they are not in the "
                           f"retrieved set: {', '.join(dropped)}")
        if any(g.items for g in cleaned.groups):
            clean = cleaned
            break
        if dropped and attempt == 0:
            notices.append("Every reference was invalid; the model was asked once more.")
            continue
        break

    if clean is None:
        return _abstained(a, "validation_failed", notices)

    # Quotes and citations come from the database; re-verify each quote against the PDF.
    seg = await _segments_for([ids[i.id]["anchor"] for g in clean.groups for i in g.items])
    openings = await _openings([ids[i.id]["anchor"] for g in clean.groups for i in g.items])
    allowed = allowed_answers(a["open_conditions"])
    out_groups = []
    for g in clean.groups:
        items = []
        for it in g.items:
            r = ids[it.id]
            s = seg.get(r["anchor"])
            path = os.path.join(raw_dir, s["filename"]) if s else None
            ok = bool(s) and quote_resolves(path, s["segments"], r["text"])
            if not ok:
                log.error("quote did not resolve against %s for %s; citation dropped", path, r["anchor"])
                notices.append(f"A citation for {r['anchor']} was removed because its quote could not be "
                               f"verified against the source file.")
                continue
            hit_for_cite = Hit(**{k: r[k] for k in Hit.__dataclass_fields__})
            item = {
                "anchor": r["anchor"], "chunk_id": r.get("best_chunk_id"),
                "citation": citation(hit_for_cite), "quote": r["text"],
                "page_start": r["page_start"], "page_end": r["page_end"], "source_file": r["filename"],
                "source_url": r["source_url"], "retrieved_at": r["retrieved_at"],
                "why_it_applies": _strip_candidate_ids(it.why_it_applies),
                "why_it_applies_note": "model-written explanation; not statute text",
            }
            op = openings.get(r["anchor"])
            if op and op["text"] != r["text"] and quote_resolves(path, s["segments"], op["text"]):
                # The matched passage can be an illustration deep in the section; also give the
                # section's opening (its operative text), verified the same way.
                item["opening_chunk_id"] = op["chunk_id"]
                item["opening_quote"] = op["text"]
            if it.plain_summary:
                sources = [r["text"]] + ([item["opening_quote"]] if "opening_quote" in item else [])
                claimed = " ".join([it.plain_summary, it.punishment or "", " ".join(it.applies_when)])
                if summary_is_grounded(claimed, sources):
                    item["plain_summary"] = _strip_candidate_ids(it.plain_summary)
                    if it.punishment:
                        item["punishment"] = _strip_candidate_ids(it.punishment)
                    if it.applies_when:
                        item["applies_when"] = [_strip_candidate_ids(x) for x in it.applies_when[:3]]
                    item["plain_summary_note"] = ("model-written reading aid for the passage shown below; "
                                                  "not statute text, may be incomplete")
                else:
                    log.warning("plain summary for %s dropped: figures not in the source text", r["anchor"])
                    notices.append(f"A plain-language summary for {r['anchor']} was removed because it contained "
                                   f"figures that are not in the source text.")
            for k in ("ipc_equivalents", "label", "legal_status"):
                if k in r:
                    item[k] = r[k]
            items.append(item)
        if items:
            answer_to = g.answer_to if g.answer_to in allowed else None
            out_groups.append({"condition": g.condition, "answer_to": answer_to, "items": items})
    if not out_groups:
        return _abstained(a, "validation_failed", notices)
    return {**a, "answer": {"abstained": False, "reason": None, "message": None, "groups": out_groups,
                            "not_applicable": [ids[i]["anchor"] for i in clean.not_applicable],
                            "notices": notices}}
