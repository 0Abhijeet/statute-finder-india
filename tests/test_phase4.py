"""Phase 4: fact schema, clarifying rules, date routing, /analyze. The LLM is faked:
these tests prove the deterministic parts. Real extraction quality is measured live
(scripts/phase4_live.py) and in the Phase 6 eval."""
import json
from datetime import date
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src import facts as facts_mod
from src.clarify import clarifying_questions
from src.dating import CUTOVER, LIMITS, resolve_date
from src.facts import Facts, Harm, Weapon, extract_facts
from src.ingest import ingest_act, ingest_mapping, load_manifest
from tests.test_ingest import clean_db  # noqa: F401

TODAY = date(2026, 10, 14)
MANIFEST = {e["file"]: e for e in load_manifest()}


# ---- date routing (no DB) -------------------------------------------------------------
@pytest.mark.parametrize("text,field,regime,precision", [
    ("stabbed on 30 June 2024", None, "ipc", "exact"),       # last day of the IPC
    ("stabbed on 1 July 2024", None, "bns", "exact"),        # first day of the BNS
    ("it happened on 2024-06-30", None, "ipc", "exact"),
    ("it happened on 15/08/2023", None, "ipc", "exact"),
    ("an incident in 2022 with a knife", None, "ipc", "year"),
    ("in March 2024 someone", None, "ipc", "month"),
    ("in July 2024 someone", None, "bns", "month"),
    ("in 2025 someone", None, "bns", "year"),
    ("in 2024 someone was stabbed", None, "ambiguous", "year"),
    ("someone was stabbed", None, "bns", "default_today"),
    ("someone was stabbed", "2023-01-05", "ipc", "exact"),
    ("in 2022 someone was stabbed", "2025-03-01", "bns", "exact"),  # field overrides text
])
def test_date_routing_before_and_after_1_july_2024(text, field, regime, precision):
    """Proves: the IPC/BNS regime follows the 1 Jul 2024 cut-over exactly, and an
    explicit request field beats a date in the text."""
    r = resolve_date(text, field, TODAY)
    assert r["regime"] == regime and r["precision"] == precision
    assert CUTOVER == date(2024, 7, 1)


def test_missing_date_assumes_today_and_says_so():
    """Proves: decision 35: no date -> today is assumed and the output states it."""
    r = resolve_date("someone took my phone", None, TODAY)
    assert r["assumed_today"] is True and r["date"] == "2026-10-14" and "assumed" in r["note"]


def test_invalid_date_field_falls_back_without_crashing():
    r = resolve_date("x", "not-a-date", TODAY)
    assert r["regime"] == "bns" and r["assumed_today"] is True and "not an ISO date" in r["note"]


# ---- severity rule + clarifying rules (no DB) -------------------------------------------
from src.severity import assess_harm  # noqa: E402

NO_DATE = resolve_date("x", None, TODAY)


@pytest.mark.parametrize("text,llm_harm,harm,established,source", [
    # explicit injury: a severity cue is in the text
    ("He stabbed her and she suffered a grievous injury", Harm.unknown, Harm.grievous_hurt, True, "text_cue"),
    ("A slight injury, a small scratch on the arm after he hit him", Harm.unknown, Harm.hurt, True, "text_cue"),
    ("He stabbed the man and he died", Harm.hurt, Harm.death, True, "text_cue"),
    ("the injury was not serious", Harm.unknown, Harm.hurt, True, "text_cue"),
    ("A driver hits a pedestrian and the pedestrian dies", Harm.unknown, Harm.death, True, "text_cue"),
    ("A young woman takes her own life after being harassed and hit", Harm.unknown, Harm.death, True, "text_cue"),
    # unspecified severity: injury described, no cue -> unknown, even if the LLM guessed
    ("A person stabs someone with a knife during an argument and causes an injury.", Harm.hurt, Harm.unknown, False, "unspecified"),
    ("He hit the pedestrian with his car", Harm.unknown, Harm.unknown, False, "unspecified"),
    ("She was wounded", Harm.grievous_hurt, Harm.unknown, False, "unspecified"),
    # no injury
    ("Someone carries a pistol in public without a valid licence.", Harm.none, Harm.none, False, "no_injury"),
    ("A person threatens to cause serious injury to his neighbour", Harm.unknown, Harm.unknown, False, "no_injury"),
])
def test_severity_rule(text, llm_harm, harm, established, source):
    """Proves: severity comes only from explicit cues. Words like 'injury'/'hurt'/'wounded'
    never establish it, an LLM guess is overridden to unknown, a threat is not an injury."""
    s = assess_harm(text, Facts(harm=llm_harm))
    assert (s.harm, s.established, s.source) == (harm, established, source)
    assert s.injury_described == (source != "no_injury")


def test_explicit_injury_asks_no_severity_question():
    f = Facts(weapon=Weapon.sharp)
    qs, conds = clarifying_questions(f, NO_DATE, "He stabbed her and she suffered a grievous injury")
    assert [q["fact"] for q in qs] == []


def test_unspecified_severity_asks_exactly_one_targeted_question():
    f = Facts(weapon=Weapon.sharp, harm=Harm.hurt)  # LLM guessed "hurt"
    qs, conds = clarifying_questions(f, NO_DATE, "A person stabs someone with a knife and causes an injury.")
    assert [q["fact"] for q in qs] == ["harm"]
    assert conds[0] == {"fact": "harm", "values": ["hurt", "grievous_hurt", "death"]}


def test_no_injury_asks_nothing_even_with_a_weapon():
    """Possession is not an injury: no harm question (the pistol-without-licence bug)."""
    qs, _ = clarifying_questions(Facts(weapon=Weapon.firearm, harm=Harm.none), NO_DATE,
                                 "Someone carries a pistol in public without a valid licence.")
    assert qs == []
    qs, _ = clarifying_questions(Facts(weapon=Weapon.sharp), NO_DATE, "He was carrying a knife in the market")
    assert qs == []


def test_unknown_harm_with_no_text_signal_asks_nothing():
    qs, conds = clarifying_questions(Facts(), NO_DATE, "")
    assert qs == [] and conds == []


def test_known_harm_unknown_weapon_asks_about_weapon():
    qs, _ = clarifying_questions(Facts(harm=Harm.unknown, weapon=Weapon.unknown), NO_DATE,
                                 "Someone suffered a grievous injury in a fight")
    assert [q["fact"] for q in qs] == ["weapon"]


def test_two_question_maximum_is_preserved():
    f = Facts(weapon=Weapon.sharp)
    d = resolve_date("in 2024 a man was stabbed and injured", None, TODAY)
    qs, conds = clarifying_questions(f, d, "in 2024 a man was stabbed and injured")
    assert len(qs) == 2 and {q["fact"] for q in qs} == {"harm", "incident_date"} and len(conds) == 2
    # harm known (cue) + weapon unknown + ambiguous year = 2 more questions, still capped at 2
    qs, _ = clarifying_questions(Facts(), d, "in 2024 a man suffered a serious injury")
    assert len(qs) == 2


# ---- schema / extraction with a fake LLM ------------------------------------------------
class _FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=r))])


@pytest.mark.asyncio
async def test_extraction_accepts_valid_json_incl_code_fence(monkeypatch):
    reply = "```json\n" + json.dumps({"harm": "hurt", "weapon": "sharp"}) + "\n```"
    monkeypatch.setattr(facts_mod, "get_llm_client", lambda: _FakeClient([reply]))
    f, meta = await extract_facts("stabbed")
    assert f.harm == Harm.hurt and f.weapon == Weapon.sharp and not meta["extraction_failed"]


@pytest.mark.asyncio
async def test_extraction_rejects_section_numbers_and_bad_enums_then_fails_safe(monkeypatch):
    """Proves: the schema leaves no room for legal conclusions: an extra key like
    `sections` or an out-of-vocabulary value is rejected; after one retry the facts are
    all-unknown and flagged, never an exception."""
    bad = [json.dumps({"harm": "hurt", "sections": ["BNS 115"]}), json.dumps({"harm": "very_bad"})]
    monkeypatch.setattr(facts_mod, "get_llm_client", lambda: _FakeClient(bad))
    f, meta = await extract_facts("stabbed")
    assert f == Facts() and meta["extraction_failed"] is True


@pytest.mark.asyncio
async def test_extraction_survives_api_error(monkeypatch):
    monkeypatch.setattr(facts_mod, "get_llm_client", lambda: _FakeClient([RuntimeError("boom"), RuntimeError("boom")]))
    f, meta = await extract_facts("x")
    assert f == Facts() and meta["extraction_failed"] and "boom" in meta["error"]


# ---- /analyze with DB ----------------------------------------------------------------
@pytest_asyncio.fixture
async def bns_and_mapping(clean_db):  # noqa: F811
    await ingest_act(MANIFEST["bns_2023.pdf"])
    await ingest_mapping(MANIFEST["bns_ipc_comparison_keralaprisons.pdf"])


@pytest.mark.asyncio
async def test_analyze_pre_july_2024_attaches_ipc_equivalent_and_labels(bns_and_mapping, monkeypatch):
    """Proves: for a pre-1 Jul 2024 incident, BNS hits carry the IPC equivalent from the
    mapping (with its source page) and are labelled as the equivalent current provision."""
    import src.analyze as analyze_mod

    async def fake_extract(_):
        return Facts(weapon=Weapon.sharp), {"extraction_failed": False}

    monkeypatch.setattr(analyze_mod, "extract_facts", fake_extract)
    out = await analyze_mod.analyze("a man stabbed me in 2022", today=TODAY)
    assert out["date"]["regime"] == "ipc"
    bns = [r for r in out["results"] if r["act"] == "bns_2023"]
    assert bns and all("ipc_equivalents" in r and "equivalent current provision" in r["label"] for r in bns)
    assert any(r["ipc_equivalents"] for r in bns)
    assert all(e["mapping_source"].startswith("page ") for r in bns for e in r["ipc_equivalents"])
    assert [q["fact"] for q in out["questions"]] == ["harm"]
    assert out["limits"] == LIMITS and out["disclaimer"] == "Informational, not legal advice."


@pytest.mark.asyncio
async def test_analyze_post_july_2024_has_no_ipc_equivalents(bns_and_mapping, monkeypatch):
    import src.analyze as analyze_mod

    async def fake_extract(_):
        return Facts(), {"extraction_failed": False}

    monkeypatch.setattr(analyze_mod, "extract_facts", fake_extract)
    out = await analyze_mod.analyze("someone took my phone", incident_date="2025-02-01", today=TODAY)
    assert out["date"]["regime"] == "bns"
    assert all("ipc_equivalents" not in r for r in out["results"])


@pytest.mark.asyncio
async def test_analyze_endpoint(bns_and_mapping, monkeypatch):
    import src.analyze as analyze_mod
    from src.app import app

    async def fake_extract(_):
        return Facts(), {"extraction_failed": False}

    monkeypatch.setattr(analyze_mod, "extract_facts", fake_extract)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/analyze", json={"incident": "someone took my phone", "incident_date": "2023-03-01"})
    assert r.status_code == 200 and r.json()["date"]["regime"] == "ipc"


@pytest.mark.asyncio
async def test_severity_heuristic_does_not_change_retrieved_sections(bns_and_mapping, monkeypatch):
    """Proves: the section list depends only on the incident text, not on the severity
    heuristic or the LLM's facts (user requirement)."""
    import src.analyze as analyze_mod

    outs = []
    for facts in (Facts(), Facts(harm=Harm.death, weapon=Weapon.firearm)):
        async def fake_extract(_, f=facts):
            return f, {"extraction_failed": False}

        monkeypatch.setattr(analyze_mod, "extract_facts", fake_extract)
        outs.append(await analyze_mod.analyze("A person stabs someone with a knife and causes an injury.",
                                              incident_date="2025-02-01", today=TODAY))
    ids = [[r["anchor"] for r in o["results"]] for o in outs]
    assert ids[0] == ids[1] and ids[0]
    assert outs[0]["facts"]["harm"] == outs[1]["facts"]["harm"] == "unknown"   # unspecified either way
    assert outs[0]["severity"]["source"] == "unspecified"


def test_no_weapon_question_for_a_vehicle_collision_or_a_suicide():
    """Found in the eval: 'a drunk driver hits a pedestrian who dies' and 'a woman takes her
    own life' were asked whether a weapon was used."""
    qs, _ = clarifying_questions(Facts(vehicle_involved="yes"), NO_DATE,
                                 "A drunk driver hits a pedestrian and the pedestrian dies")
    assert qs == []
    qs, _ = clarifying_questions(Facts(), NO_DATE, "A young woman takes her own life after being harassed")
    assert qs == []
    qs, _ = clarifying_questions(Facts(), NO_DATE, "A man beat his neighbour and the neighbour died")
    assert [q["fact"] for q in qs] == ["weapon"]


def test_attempt_wording_asks_whether_anyone_was_hurt_not_how_serious():
    """Seen in a user's screenshot: 'tried to stab me' was asked 'how serious was the injury'."""
    from src.severity import assess_harm as _assess

    s = _assess("tried to stab me", Facts(weapon=Weapon.sharp))
    assert s.source == "attempt" and s.injury_described is False
    qs, conds = clarifying_questions(Facts(weapon=Weapon.sharp), NO_DATE, "A man tried to stab me in the back")
    assert [q["fact"] for q in qs] == ["harm"] and "actually hurt" in qs[0]["question"]
    assert conds[0]["values"][0] == "no_injury"
    # an attempt that also states an outcome is not an attempt-only case
    assert _assess("He tried to stab me and injured my arm", Facts()).source != "attempt"
    assert _assess("He tried to kill him and the man died", Facts()).source != "attempt"
