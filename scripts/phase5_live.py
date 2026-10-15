"""Live Phase 5 check: real LLM selection/grouping/abstention on the gate incidents.
Needs LLM_API_KEY (from .env) and a populated database. Prints a compact view for
hand-checking; model-written explanations are shown, quotes are not."""
import asyncio
import json
import sys

sys.path.insert(0, ".")
from src.answer import answer  # noqa: E402


async def main() -> None:
    cases = [json.loads(l) for l in open("eval/gate_incidents.jsonl", encoding="utf-8") if l.strip()]
    for c in cases:
        out = await answer(c["incident"])
        a = out["answer"]
        print(f"\n#{c['id']} {c['incident']}")
        print("   asks:", [q["fact"] for q in out["questions"]], "| regime:", out["date"]["regime"])
        if a["abstained"]:
            print(f"   ABSTAINED: {a['reason']} | notices: {a['notices']}")
        else:
            for g in a["groups"]:
                print(f"   [{g['condition']}]")
                for i in g["items"]:
                    print(f"      {i['anchor']} ({i['citation'].split('(')[-1].rstrip(')')}) :: {i['why_it_applies'][:150]}")
            print("   not_applicable:", a.get("not_applicable"), "| notices:", a["notices"])


asyncio.run(main())
