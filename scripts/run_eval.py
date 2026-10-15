"""Phase 6 eval runner (decision 44, option C).

Retrieval metrics (hit@3, recall@5) for vector / keyword / hybrid on every case that has
gold sections; generation metrics (citation grounding, abstention, clarify, regime,
answer precision) for hybrid only (the shipped configuration). Writes eval/results.json
and eval/REPORT.md. Cases are eval/cases.jsonl; all labels are unreviewed drafts by a
non-lawyer: numbers are an engineering signal, not legal accuracy.

Usage: python scripts/run_eval.py [--no-llm]    (needs DATABASE_URL, LLM_API_KEY in .env)
"""
import asyncio
import json
import os
import time
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, ".")
from src.answer import RAW_DIR, answer  # noqa: E402
from src.provenance import quote_resolves  # noqa: E402
from src.query import clean_query  # noqa: E402
from src.retrieve import retrieve  # noqa: E402
from src.rewrite import rewrite_query  # noqa: E402

MODES = ("vector", "keyword", "hybrid", "hybrid+rewrite")
ACT_NAMES = {"bns_2023": "BNS 2023", "arms_act_1959": "Arms Act 1959", "mv_act_1988": "MV Act 1988",
             "it_act_2000": "IT Act 2000", "tn_harassment_women_1998": "TN Harassment of Women 1998"}


def load_cases():
    return [json.loads(l) for l in open("eval/cases.jsonl", encoding="utf-8") if l.strip()]


def act_of(anchor: str) -> str:
    return anchor.split(":")[0]


TAG = os.environ.get("EVAL_TAG", "")          # e.g. "ollama": separate partials, results, report
SUF = f".{TAG}" if TAG else ""
PARTIAL_R = f"eval/partial_retrieval{SUF}.jsonl"
PARTIAL_G = f"eval/partial_generation{SUF}.jsonl"
RESULTS_PATH = f"eval/results{SUF}.json"
REPORT_PATH = f"eval/REPORT{SUF}.md"
# generation subset (decision 49): all 8 negatives + 13 others covering every act and case type
SUBSET_IDS = {"s01", "s04", "s06", "s09", "s11", "s14", "s17", "s18", "s20", "m01", "m03", "m05",
              "t01", "t04", "u01", "u02"}


def _load_partial(path):
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                d = json.loads(line)
                out[d["id"]] = d["row"]
    return out


def _append(path, cid, row):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": cid, "row": row}, ensure_ascii=False) + "\n")


async def retrieval_eval(cases):
    """No-LLM part: vector / keyword / hybrid. Rows already holding a valid rewrite are kept."""
    per_case = _load_partial(PARTIAL_R)
    for n, c in enumerate(cases, start=1):
        prev = per_case.get(c["id"])
        if prev and prev.get("_rewrite"):
            continue
        q = clean_query(c["incident"])
        row = {"_rewrite": ""}
        for mode in ("vector", "keyword", "hybrid"):
            row[mode] = await _retrieve_row(c, q, mode, mode)
        per_case[c["id"]] = row
    return per_case


async def _retrieve_row(c, query, mode, label):
    hits = await retrieve(query, k_per_act=3, k_final=8, mode=mode)
    order = [h.anchor for h in hits]
    return {
        "top8": order,
        "gold_rank": {g: (order.index(g) + 1 if g in order else None) for g in c["gold"]},
        "legs": {h.anchor: {"vec": h.vector_rank, "kw": h.keyword_rank, "cos": round(h.vector_sim, 2)}
                 for h in hits if h.anchor in c["gold"]},
    }


async def rewrite_eval(cases, per_case):
    """LLM part of the baseline: fill in missing rewrites (small token budget, paced) and
    retrieve with them. Appends each finished case so a crash loses nothing."""
    todo = [c for c in cases if not per_case[c["id"]].get("_rewrite")]
    for n, c in enumerate(todo, start=1):
        rw = ""
        for _ in range(2):  # an empty reply (reasoning used the budget) gets one more try
            await asyncio.sleep(float(os.environ.get("EVAL_PACE", "7")) if TAG else 7)
            rw = await rewrite_query(c["incident"])
            if rw:
                break
        row = per_case[c["id"]]
        row["_rewrite"] = rw
        q = clean_query(c["incident"])
        row["hybrid+rewrite"] = await _retrieve_row(c, f"{q} {rw}".strip(), "hybrid", "hybrid+rewrite")
        _append(PARTIAL_R, c["id"], row)
        print(f"[rewrite {n}/{len(todo)}] {c['id']} ok={bool(rw)}", flush=True)
    # cases whose rewrite stayed empty fall back to plain hybrid so the table is complete
    for c in cases:
        row = per_case[c["id"]]
        if "hybrid+rewrite" not in row:
            row["hybrid+rewrite"] = row["hybrid"]
    return per_case


def retrieval_metrics(cases, per_case):
    out = {}
    scored = [c for c in cases if c["gold"]]
    for mode in MODES:
        hit3 = sum(any((per_case[c["id"]][mode]["gold_rank"][g] or 99) <= 3 for g in c["gold"]) for c in scored)
        rec5 = sum(sum((per_case[c["id"]][mode]["gold_rank"][g] or 99) <= 5 for g in c["gold"]) / len(c["gold"])
                   for c in scored)
        by_act = defaultdict(lambda: [0, 0])  # act -> [gold anchors in top3, gold anchors]
        for c in scored:
            for g in c["gold"]:
                by_act[act_of(g)][1] += 1
                by_act[act_of(g)][0] += (per_case[c["id"]][mode]["gold_rank"][g] or 99) <= 3
        by_type = defaultdict(lambda: [0, 0])
        for c in scored:
            by_type[c["type"]][1] += 1
            by_type[c["type"]][0] += any((per_case[c["id"]][mode]["gold_rank"][g] or 99) <= 3 for g in c["gold"])
        out[mode] = {"n": len(scored), "hit@3": hit3, "recall@5_sum": round(rec5, 2),
                     "by_act": {a: tuple(v) for a, v in by_act.items()},
                     "by_type": {t: tuple(v) for t, v in by_type.items()}}
    return out


async def generation_eval(cases):
    """Resumable and bounded: each case has a hard timeout; results are appended as they finish."""
    results = _load_partial(PARTIAL_G)
    for n, c in enumerate(cases, start=1):
        prev = results.get(c["id"])
        if prev and "error" not in prev and prev.get("reason") != "generation_error":
            continue  # finished; cases that failed on the API are re-run
        try:
            out = await asyncio.wait_for(
                answer(c["incident"], c["incident_date"], today=date(2026, 10, 14)), timeout=300)
        except Exception as e:  # keep going; record
            results[c["id"]] = {"error": f"{type(e).__name__}: {e}"[:200]}
            _append(PARTIAL_G, c["id"], results[c["id"]])
            print(f"[generation {n}/{len(cases)}] {c['id']} ERROR {type(e).__name__}", flush=True)
            await _pace()
            continue
        a = out["answer"]
        shown = [i for g in a["groups"] for i in g["items"]]
        grounded = 0
        for it in shown:
            seg = await _segments(it["anchor"])
            ok = bool(seg) and quote_resolves(os.path.join(RAW_DIR, seg["filename"]), seg["segments"], it["quote"])
            grounded += ok
        retrieved = {r["anchor"] for r in out["results"]}
        results[c["id"]] = {
            "abstained": a["abstained"], "reason": a["reason"], "notices": a["notices"],
            "shown": [i["anchor"] for i in shown],
            "shown_not_in_retrieved": [i["anchor"] for i in shown if i["anchor"] not in retrieved],
            "n_grounded": grounded, "n_shown": len(shown),
            "questions": [q["fact"] for q in out["questions"]],
            "regime": out["date"]["regime"],
            "ipc_refs": sorted({e["ipc_ref"] for i in shown for e in i.get("ipc_equivalents", [])}),
            "retrieved": [r["anchor"] for r in out["results"]],
        }
        _append(PARTIAL_G, c["id"], results[c["id"]])
        print(f"[generation {n}/{len(cases)}] {c['id']} abstained={a['abstained']} reason={a['reason']} "
              f"shown={len(shown)}", flush=True)
        await _pace()
    return results


_seg_cache = {}
_last = [0.0]


async def _pace(min_gap: float | None = None) -> None:
    min_gap = float(os.environ.get("EVAL_PACE", "40")) if min_gap is None else min_gap
    """Groq free tier: 8,000 tokens/min for this model; one case uses ~7k. Keep calls apart."""
    wait = min_gap - (time.time() - _last[0])
    if wait > 0:
        await asyncio.sleep(wait)
    _last[0] = time.time()




async def _segments(anchor):
    from sqlalchemy import text

    from src.database import AsyncSessionLocal
    if anchor not in _seg_cache:
        async with AsyncSessionLocal() as db:
            r = (await db.execute(text("select s.segments, sf.filename from sections s join source_files sf "
                                       "on sf.id = s.source_file_id where s.anchor = :a"), {"a": anchor})).first()
        _seg_cache[anchor] = {"segments": r.segments, "filename": r.filename} if r else None
    return _seg_cache[anchor]


def generation_metrics(cases, gen):
    m = {"citation": [0, 0], "neg_abstain": [0, 0], "false_abstain": [0, 0], "clarify": [0, 0],
         "no_spurious_question": [0, 0], "regime": [0, 0], "ipc_refs": [0, 0],
         "shown_precision": [0, 0], "gold_shown": [0, 0], "invented_ids_shown": 0, "errors": 0}
    for c in cases:
        r = gen.get(c["id"], {})
        if "error" in r:
            m["errors"] += 1
            continue
        m["citation"][0] += r["n_grounded"]; m["citation"][1] += r["n_shown"]
        m["invented_ids_shown"] += len(r["shown_not_in_retrieved"])
        exp = c["expect"]
        if c["type"] == "negative":
            m["neg_abstain"][1] += 1; m["neg_abstain"][0] += bool(r["abstained"])
        else:
            m["false_abstain"][1] += 1; m["false_abstain"][0] += bool(r["abstained"])
            ok_set = set(c["gold"]) | set(c["acceptable"])
            if r["shown"]:
                m["shown_precision"][1] += len(r["shown"]); m["shown_precision"][0] += sum(s in ok_set for s in r["shown"])
            if c["gold"]:
                m["gold_shown"][1] += 1; m["gold_shown"][0] += any(g in r["shown"] for g in c["gold"])
        if "asks" in exp:
            m["clarify"][1] += 1; m["clarify"][0] += set(exp["asks"]) <= set(r["questions"])
        elif c["type"] != "negative":
            m["no_spurious_question"][1] += 1; m["no_spurious_question"][0] += not r["questions"]
        if "regime" in exp:
            m["regime"][1] += 1; m["regime"][0] += r["regime"] == exp["regime"]
        if "ipc_refs" in exp:
            m["ipc_refs"][1] += 1
            # the IPC refs shown must include at least one expected ref when the BNS section is shown
            m["ipc_refs"][0] += bool(set(exp["ipc_refs"]) & set(r["ipc_refs"]))
    return m


def diagnose_retrieval(c, row):
    """One-line, rule-based diagnosis for a hybrid retrieval miss."""
    h = row["hybrid"]
    lines = []
    for g in c["gold"]:
        if (h["gold_rank"][g] or 99) <= 3:
            continue
        rk = h["gold_rank"][g]
        v, k = row["vector"]["gold_rank"][g], row["keyword"]["gold_rank"][g]
        if rk is None and v is None and k is None:
            lines.append(f"{g}: absent from the top 8 of every mode: neither leg connects the lay wording to the statute wording")
        elif rk is None and (v or k):
            lines.append(f"{g}: found by {'vector' if v else 'keyword'} alone (rank {v or k}) but pushed out of the hybrid top 8 by the per-act/global fusion")
        else:
            lines.append(f"{g}: hybrid rank {rk} (vector {v}, keyword {k}): present but below the top 3")
    return "; ".join(lines)


def write_report(cases, per_case, rm, gen, gm, with_llm):
    L = []
    w = L.append
    w("# Eval report\n")
    w("**Read this first.** The 41 cases in `eval/cases.jsonl` were drafted by an AI agent from the stored statute text and "
      "are all `label_status = unreviewed`. Gold sections were chosen by reading the text (SQL search), not by the retriever, "
      "and each is checked to exist in the database; they are labels by a **non-lawyer, not reviewed by counsel**. Numbers below "
      "are an engineering signal about retrieval and validation behaviour, not a measure of legal accuracy. One run; the LLM "
      "steps are not deterministic.\n")
    from urllib.parse import urlparse
    mdl = os.environ.get("LLM_MODEL", "openai/gpt-oss-20b")
    host = urlparse(os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")).netloc
    w(f"**Generation model for this report: `{mdl}` via `{host}`.** Generation numbers describe this model only; retrieval numbers do not depend on it, except the `hybrid+rewrite` column.\n")
    w("Configuration: hybrid = per-act top-3 (vector + BM25, RRF) then pooled global RRF, top 8; query cleaning on (decision 41); "
      "no similarity floor; rewriting off (decision 30). BM25 k1=1.5, b=0.75 untuned.\n")
    n = rm["hybrid"]["n"]
    w(f"## 1. Retrieval ({n} cases with gold; counts, not percentages)\n")
    w("| mode | hit@3 | recall@5 (sum of per-case recall) |\n|---|---|---|")
    for mode in MODES:
        w(f"| {mode} | {rm[mode]['hit@3']}/{n} | {rm[mode]['recall@5_sum']}/{n} |")
    w("\n### By act (gold sections in top 3 / gold sections)\n")
    w("| act | " + " | ".join(MODES) + " |\n|---|" + "---|" * len(MODES))
    for act in ACT_NAMES:
        cells = []
        for mode in MODES:
            a = rm[mode]["by_act"].get(act, (0, 0))
            cells.append(f"{a[0]}/{a[1]}")
        w(f"| {ACT_NAMES[act]} | " + " | ".join(cells) + " |")
    w("\n### By case type (cases with a gold section in top 3 / cases)\n")
    types = sorted({t for r in rm.values() for t in r["by_type"]})
    w("| type | " + " | ".join(MODES) + " |\n|---|" + "---|" * len(MODES))
    for t in types:
        w(f"| {t} | " + " | ".join(f"{rm[m]['by_type'].get(t, (0, 0))[0]}/{rm[m]['by_type'].get(t, (0, 0))[1]}" for m in MODES) + " |")
    if with_llm:
        w("\n## 2. Generation, validation and abstention (hybrid, shipped configuration)\n")
        fa = gm["false_abstain"]; na = gm["neg_abstain"]
        w("| measure | count |\n|---|---|")
        w(f"| citation grounding: shown quotes that resolve in the source PDF | {gm['citation'][0]}/{gm['citation'][1]} |")
        w(f"| shown sections that are not in the retrieved set (invented ids reaching the user) | {gm['invented_ids_shown']} |")
        w(f"| negative cases correctly abstained | {na[0]}/{na[1]} |")
        w(f"| non-negative cases wrongly abstained | {fa[0]}/{fa[1]} |")
        w(f"| cases with at least one gold section shown | {gm['gold_shown'][0]}/{gm['gold_shown'][1]} |")
        w(f"| shown sections that are gold or acceptable | {gm['shown_precision'][0]}/{gm['shown_precision'][1]} |")
        w(f"| clarify: expected question asked | {gm['clarify'][0]}/{gm['clarify'][1]} |")
        w(f"| clarify: no question on cases that expect none | {gm['no_spurious_question'][0]}/{gm['no_spurious_question'][1]} |")
        w(f"| date regime correct (temporal/underspecified with an expected regime) | {gm['regime'][0]}/{gm['regime'][1]} |")
        w(f"| IPC equivalent shown includes an expected IPC ref (temporal, ipc regime) | {gm['ipc_refs'][0]}/{gm['ipc_refs'][1]} |")
        w(f"| cases that errored | {gm['errors']} |")
        w("\n`citation grounding` is true by construction when parsing is right; its value is catching parser or file drift.\n")
    w("\n## 3. Failures, one line each\n")
    w("| case | type | what happened | diagnosis |\n|---|---|---|---|")
    nfail = 0
    for c in cases:
        row = per_case[c["id"]]
        probs = []
        if c["gold"]:
            d = diagnose_retrieval(c, row)
            if d and all((row["hybrid"]["gold_rank"][g] or 99) > 3 for g in c["gold"]):
                probs.append(("retrieval miss (no gold in hybrid top 3)", d))
        r = gen.get(c["id"]) if with_llm else None
        if r and "error" in r:
            probs.append(("generation error", r["error"]))
        elif r:
            if c["type"] == "negative" and not r["abstained"]:
                probs.append(("answered an out-of-scope incident", f"shown: {', '.join(r['shown'][:4])}; the model judged candidates applicable"))
            if c["type"] != "negative" and r["abstained"]:
                got = [g for g in c["gold"] if g in r["retrieved"]]
                why = (f"gold {', '.join(got)} was retrieved but the model abstained ({r['reason']})" if got else
                       f"abstained ({r['reason']}); gold was not among the retrieved candidates")
                probs.append(("wrongly abstained", why))
            if c["type"] != "negative" and not r["abstained"] and c["gold"] and not any(g in r["shown"] for g in c["gold"]):
                got = [g for g in c["gold"] if g in r["retrieved"]]
                probs.append(("gold not shown", (f"gold {', '.join(got)} retrieved but not selected by the model; shown: {', '.join(r['shown'][:4])}" if got else f"gold not retrieved; shown: {', '.join(r['shown'][:4])}")))
            exp = c["expect"]
            if "asks" in exp and not set(exp["asks"]) <= set(r["questions"]):
                probs.append(("missing clarifying question", f"expected {exp['asks']}, got {r['questions']}"))
            if "asks" not in exp and c["type"] != "negative" and r["questions"]:
                probs.append(("unexpected clarifying question", f"asked {r['questions']}"))
            if "regime" in exp and r["regime"] != exp["regime"]:
                probs.append(("wrong date regime", f"expected {exp['regime']}, got {r['regime']}"))
            if r["shown_not_in_retrieved"]:
                probs.append(("INVENTED ID REACHED USER", str(r["shown_not_in_retrieved"])))
        for kind, diag in probs:
            nfail += 1
            w(f"| {c['id']} | {c['type']} | {kind} | {diag} |")
    if nfail == 0:
        w("| (none) | | | |")
    w("\n## 4. Limits of this eval\n")
    w("- 41 cases, one run, labels unreviewed and by a non-lawyer (see top). Wording of the incidents was written by the same "
      "agent that built the retriever, so lay-language coverage is narrower than real users'.\n"
      "- Gold relevance was fixed by reading section text; `acceptable` lists are judgement calls.\n"
      "- `hybrid+rewrite` is retrieval-only (decision 44); the rewrite prompt was written after seeing failures on these same cases, so its gain is optimistic. Cosine floors and BM25 parameters are untuned.\n"
      "- Other acts are the current consolidated text; temporal cases test routing and IPC-equivalent display, not historical text.\n")
    open(REPORT_PATH, "w", encoding="utf-8").write("\n".join(L) + "\n")


async def main(with_llm: bool) -> None:
    cases = load_cases()
    if "--fresh" in sys.argv:
        for pth in (PARTIAL_R, PARTIAL_G):
            if os.path.exists(pth):
                os.remove(pth)
    per_case = await retrieval_eval(cases)
    print('[retrieval, no-LLM modes] done', flush=True)
    if with_llm:
        per_case = await rewrite_eval(cases, per_case)
    else:
        for c in cases:
            per_case[c['id']].setdefault('hybrid+rewrite', per_case[c['id']]['hybrid'])
    rm = retrieval_metrics(cases, per_case)
    gen, gm = {}, {}
    if with_llm:
        gcases = [c for c in cases if c["type"] == "negative" or c["id"] in SUBSET_IDS] if "--subset" in sys.argv else cases
        gen = await generation_eval(gcases)
        gm = generation_metrics(gcases, gen)
    json.dump({"retrieval": per_case, "retrieval_metrics": rm, "generation": gen, "generation_metrics": gm},
              open(RESULTS_PATH, "w", encoding="utf-8"), indent=1, default=list)
    write_report(cases, per_case, rm, gen, gm, with_llm)
    print("hit@3:", {m: f"{rm[m]['hit@3']}/{rm[m]['n']}" for m in MODES})
    if with_llm:
        print("generation:", json.dumps(gm))


if __name__ == "__main__":
    asyncio.run(main("--no-llm" not in sys.argv))
