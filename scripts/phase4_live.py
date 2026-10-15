"""Live Phase 4 check: real LLM fact extraction + date routing + clarifying questions
for the 10 gate incidents. Needs LLM_API_KEY (from .env) and a populated database."""
import asyncio
import json
import sys

sys.path.insert(0, ".")
from src.analyze import analyze  # noqa: E402


async def main() -> None:
    cases = [json.loads(l) for l in open("eval/gate_incidents.jsonl", encoding="utf-8") if l.strip()]
    for c in cases:
        out = await analyze(c["incident"], k_final=5)
        f = {k: v for k, v in out["facts"].items() if v != "unknown"}
        print(f"\n#{c['id']} {c['incident']}")
        print("   facts (non-unknown):", f, "| extraction_failed:", out["extraction"]["extraction_failed"])
        print("   date:", out["date"]["regime"], "|", out["date"]["note"])
        for q in out["questions"]:
            print("   ASK:", q["question"])
        print("   top5:", ", ".join(f"{r['act'].split('_')[0]}:{r['number']}" for r in out["results"]))


asyncio.run(main())
