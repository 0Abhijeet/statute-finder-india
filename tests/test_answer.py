"""Phase 5: validator, abstention, retry. The LLM is faked; quotes, citations and the
PDF re-verification are the real code paths against real Postgres and the real PDFs."""
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import src.analyze as analyze_mod
import src.answer as answer_mod
from src.answer import ModelAnswer, validate_ids
from src.facts import Facts
from src.ingest import ingest_act, load_manifest
from tests.test_ingest import clean_db  # noqa: F401

MANIFEST = {e["file"]: e for e in load_manifest()}
INCIDENT = "Someone carries a pistol in public without a valid licence."


class FakeLLM:
    """Returns queued replies; records the prompts it was given."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        self.calls.append(kw["messages"][-1]["content"])
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=r))])


def sel(*ids, cond="General"):
    return json.dumps({
        "abstain": {"value": False, "reason": None},
        "groups": [{"condition": cond,
                    "items": [{"id": i, "why_it_applies": "Carrying a firearm."} for i in ids]}],
        "not_applicable": [],
    })


@pytest_asyncio.fixture
async def corpus(clean_db, monkeypatch):  # noqa: F811
    await ingest_act(MANIFEST["arms_act_1959.pdf"])
    await ingest_act(MANIFEST["tn_harassment_women_1998.pdf"])

    async def fake_extract(_):
        return Facts(), {"extraction_failed": False}

    monkeypatch.setattr(analyze_mod, "extract_facts", fake_extract)


def use(monkeypatch, replies) -> FakeLLM:
    llm = FakeLLM(replies)
    monkeypatch.setattr(answer_mod, "get_llm_client", lambda: llm)
    return llm


def test_validate_ids_drops_unknown_repeated_and_empties_groups():
    ans = ModelAnswer.model_validate({
        "groups": [
            {"condition": "a", "items": [{"id": "C1", "why_it_applies": "x"},
                                         {"id": "BNS 115", "why_it_applies": "y"}]},
            {"condition": "b", "items": [{"id": "C9", "why_it_applies": "z"},
                                         {"id": "C1", "why_it_applies": "again"}]}],
        "not_applicable": ["C2", "C77"]})
    clean, dropped = validate_ids(ans, {"C1", "C2"})
    assert [i.id for g in clean.groups for i in g.items] == ["C1"]
    assert len(clean.groups) == 1 and clean.not_applicable == ["C2"]
    assert set(dropped) == {"BNS 115", "C9", "C1 (repeated)", "C77"}


@pytest.mark.asyncio
async def test_valid_answer_quotes_and_citations_come_from_the_database(corpus, monkeypatch):
    llm = use(monkeypatch, [sel("C1", "C2")])
    out = await answer_mod.answer(INCIDENT)
    a = out["answer"]
    assert a["abstained"] is False and a["notices"] == []
    items = [i for g in a["groups"] for i in g["items"]]
    assert len(items) == 2
    by_anchor = {r["anchor"]: r for r in out["results"]}
    for it in items:
        assert it["quote"] == by_anchor[it["anchor"]]["text"]            # verbatim, from the DB
        assert "page" in it["citation"] and it["source_file"].endswith(".pdf")
        assert it["why_it_applies_note"].startswith("model-written")
    # the model saw opaque ids, not section anchors
    assert "[C1]" in llm.calls[0] and "arms_act_1959:s" not in llm.calls[0]


@pytest.mark.asyncio
async def test_invented_id_is_dropped_logged_and_noticed(corpus, monkeypatch, caplog):
    """Addendum: a validator drops and logs any ID not in the retrieved set."""
    use(monkeypatch, [sel("C1", "BNS-115", "C99")])
    with caplog.at_level("WARNING", logger="statute.validator"):
        out = await answer_mod.answer(INCIDENT)
    items = [i for g in out["answer"]["groups"] for i in g["items"]]
    assert len(items) == 1
    assert any("BNS-115" in n and "C99" in n for n in out["answer"]["notices"])
    assert "BNS-115" in caplog.text and "C99" in caplog.text


@pytest.mark.asyncio
async def test_all_ids_dropped_triggers_one_retry_then_success(corpus, monkeypatch):
    llm = use(monkeypatch, [sel("BNS 115", "IPC 324"), sel("C1")])
    out = await answer_mod.answer(INCIDENT)
    assert len(llm.calls) == 2 and "ONLY these ids" in llm.calls[1]
    assert out["answer"]["abstained"] is False
    got = [i["anchor"] for g in out["answer"]["groups"] for i in g["items"]]
    assert got == [out["results"][0]["anchor"]]


@pytest.mark.asyncio
async def test_all_ids_dropped_twice_abstains_validation_failed(corpus, monkeypatch):
    llm = use(monkeypatch, [sel("X1"), sel("X2")])
    out = await answer_mod.answer(INCIDENT)
    assert len(llm.calls) == 2
    a = out["answer"]
    assert a["abstained"] is True and a["reason"] == "validation_failed" and a["groups"] == []


@pytest.mark.asyncio
async def test_model_abstention_uses_server_message_and_known_reason(corpus, monkeypatch):
    """Abstention text is the server's, not the model's; unknown codes are mapped."""
    use(monkeypatch, [json.dumps({"abstain": {"value": True, "reason": "topic_not_in_corpus"}, "groups": []})])
    out = await answer_mod.answer("A homeowner builds a floor without planning permission.")
    a = out["answer"]
    assert a["abstained"] and a["reason"] == "topic_not_in_corpus" and "outside" in a["message"]
    use(monkeypatch, [json.dumps({"abstain": {"value": True, "reason": "because I said so"}, "groups": []})])
    out = await answer_mod.answer("A homeowner builds a floor without planning permission.")
    assert out["answer"]["reason"] == "no_matching_provision"


@pytest.mark.asyncio
async def test_quote_that_does_not_resolve_in_the_pdf_is_dropped(corpus, monkeypatch):
    """Addendum item 3: a citation whose quote is not found at the stored offsets in the
    source file is dropped and reported."""
    use(monkeypatch, [sel("C1", "C2")])
    real = answer_mod.quote_resolves
    calls = {"n": 0}

    def flaky(path, segs, quote):
        calls["n"] += 1
        return False if calls["n"] == 1 else real(path, segs, quote)

    monkeypatch.setattr(answer_mod, "quote_resolves", flaky)
    out = await answer_mod.answer(INCIDENT)
    items = [i for g in out["answer"]["groups"] for i in g["items"]]
    assert len(items) == 1 and any("could not be verified" in n for n in out["answer"]["notices"])


@pytest.mark.asyncio
async def test_invalid_json_twice_and_api_error_fail_safe(corpus, monkeypatch):
    use(monkeypatch, ["not json", '{"groups": "nope"}'])
    out = await answer_mod.answer(INCIDENT)
    assert out["answer"]["reason"] == "validation_failed" and out["answer"]["notices"]
    use(monkeypatch, [RuntimeError("boom")])
    out = await answer_mod.answer(INCIDENT)
    assert out["answer"]["reason"] == "generation_error"


@pytest.mark.asyncio
async def test_answer_endpoint(corpus, monkeypatch):
    from src.app import app

    use(monkeypatch, [sel("C1")])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/answer", json={"incident": INCIDENT})
    body = r.json()
    assert r.status_code == 200 and body["answer"]["abstained"] is False
    assert body["disclaimer"] == "Informational, not legal advice." and body["limits"]


def test_candidate_ids_are_stripped_from_model_explanations():
    """Found live: the model wrote 'matches section C1'. Internal ids must not reach users."""
    from src.answer import _strip_candidate_ids

    assert _strip_candidate_ids("aligns with the description in section C1.") == \
        "aligns with the description in the provision."
    assert _strip_candidate_ids("C2 and candidate C10 both fit") == "the provision and the provision both fit"
    assert _strip_candidate_ids("Section 303 of the Act") == "Section 303 of the Act"


@pytest.mark.asyncio
async def test_opening_quote_is_added_when_the_matched_passage_is_not_the_section_start(corpus, monkeypatch):
    """Found in the eval output: the matched chunk for BNS s.303 was an illustration. The
    response also carries the section's opening chunk, verified against the PDF, whenever
    the matched chunk is not chunk 0."""
    from sqlalchemy import text

    from src.database import AsyncSessionLocal

    use(monkeypatch, [sel("C1", "C2", "C3")])
    out = await answer_mod.answer("licence for acquisition and possession of firearms and ammunition")
    items = [i for g in out["answer"]["groups"] for i in g["items"]]
    assert items
    async with AsyncSessionLocal() as db:
        for it in items:
            chunk_no = (await db.execute(text("select chunk_no from chunks where id = :i"),
                                         {"i": it["chunk_id"]})).scalar()
            if chunk_no == 0:
                assert "opening_quote" not in it
            else:
                assert it["opening_quote"] and it["opening_quote"] != it["quote"]
                first = (await db.execute(text("select text from chunks c join sections s on s.id = c.section_id "
                                               "where s.anchor = :a and c.chunk_no = 0"), {"a": it["anchor"]})).scalar()
                assert it["opening_quote"] == first


# ---- plain-language summaries and answer-tagged groups (cards AK, AL) ------------------
def test_summary_figures_must_appear_in_the_source_text():
    """Proves: a plain summary cannot state a fine or term that the quoted text does not contain."""
    from src.answer import summary_is_grounded

    src = "shall be punished with imprisonment which may extend to three years and with fine of 10,000 rupees"
    assert summary_is_grounded("Up to three years in prison and a fine of 10000 rupees.", [src])
    assert summary_is_grounded("It sets a punishment and a fine.", [src])
    assert not summary_is_grounded("The fine is 50000 rupees.", [src])
    assert not summary_is_grounded("Up to 7 years.", [src])


def test_allowed_answers_come_from_the_open_questions():
    from src.answer import allowed_answers

    conds = [{"fact": "harm", "values": ["hurt", "grievous_hurt", "death"]},
             {"fact": "weapon", "values": ["sharp", "firearm"]}]
    assert allowed_answers(conds) == {"hurt", "grievous_hurt", "death", "sharp", "firearm"}
    assert allowed_answers([]) == set()


def _sel_tagged(item_id, answer_to, summary):
    return json.dumps({
        "abstain": {"value": False, "reason": None},
        "groups": [{"condition": "harm type", "answer_to": answer_to,
                    "items": [{"id": item_id, "why_it_applies": "Fits the facts.", "plain_summary": summary}]}],
        "not_applicable": [],
    })


INJURY_INCIDENT = "A man attacked another man with a knife and injured him."


@pytest.mark.asyncio
async def test_group_is_tagged_with_a_valid_answer_and_summary_is_kept(corpus, monkeypatch):
    use(monkeypatch, [_sel_tagged("C1", "grievous_hurt", "This provision deals with licences for firearms.")])
    out = await answer_mod.answer(INJURY_INCIDENT)
    assert [q["fact"] for q in out["questions"]] == ["harm"]
    g = out["answer"]["groups"][0]
    assert g["answer_to"] == "grievous_hurt"
    it = g["items"][0]
    assert it["plain_summary"].startswith("This provision") and "not statute text" in it["plain_summary_note"]
    assert it["quote"]            # the verbatim text is still there next to the summary


@pytest.mark.asyncio
async def test_invalid_answer_tag_is_dropped_and_ungrounded_summary_is_removed(corpus, monkeypatch):
    use(monkeypatch, [_sel_tagged("C1", "very_serious", "The punishment is 99999 years.")])
    out = await answer_mod.answer(INJURY_INCIDENT)
    g = out["answer"]["groups"][0]
    assert g["answer_to"] is None                      # not one of the question's options
    assert "plain_summary" not in g["items"][0]
    assert any("plain-language summary" in n for n in out["answer"]["notices"])


def test_summary_figures_include_number_words():
    """Found live: 'up to ten years' passed a digits-only check."""
    from src.answer import summary_is_grounded

    src = "imprisonment which may extend to three years, or with fine which may extend to twenty thousand rupees"
    assert summary_is_grounded("Up to three years, or a fine of up to twenty thousand rupees.", [src])
    assert not summary_is_grounded("Up to ten years in prison.", [src])
    assert not summary_is_grounded("Up to seven years.", [src])
    assert summary_is_grounded("No one may do this.", [src])        # pronoun "one" is not a figure
    assert not summary_is_grounded("Imprisonment of one year.", [src])


def test_items_the_model_calls_not_applicable_are_moved_out_of_the_groups():
    from src.answer import drop_non_applicable

    ans = ModelAnswer.model_validate({"groups": [
        {"condition": "The incident involves taking property", "items": [
            {"id": "C1", "why_it_applies": "Phone taken without consent.", "plain_summary": "Theft is punishable."}]},
        {"condition": "The incident does not involve kidnapping", "items": [
            {"id": "C2", "why_it_applies": "Not the case here.", "plain_summary": "About kidnapping."}]},
        {"condition": "Other", "items": [
            {"id": "C3", "why_it_applies": "x", "plain_summary": "This is not relevant here."}]}]})
    clean, moved = drop_non_applicable(ans)
    assert [i.id for g in clean.groups for i in g.items] == ["C1"]
    assert set(moved) == {"C2", "C3"} and set(clean.not_applicable) == {"C2", "C3"}


def test_punishment_and_conditions_are_checked_like_the_summary():
    """The user's summarising prompt asks for punishment and applies_when too; a wrong term of
    years in any of the three fields must remove the whole reading aid."""
    from src.answer import summary_is_grounded

    src = "shall be punished with imprisonment for a term which may extend to three years, or with fine, or with both"
    ok = " ".join(["Voluntarily causing hurt is punishable.", "Up to three years, a fine, or both.", "hurt was caused"])
    bad = " ".join(["Voluntarily causing hurt is punishable.", "Up to five years.", "hurt was caused"])
    assert summary_is_grounded(ok, [src])
    assert not summary_is_grounded(bad, [src])
