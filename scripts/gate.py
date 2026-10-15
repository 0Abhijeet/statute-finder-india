"""Phase 3 gate: run the user's 10 incidents through retrieve() and print the top 8
with the matched text so each can be hand-checked. For incidents with concrete
expected sections, also report whether they are in the top 5. Section numbers in the
file are the user's hypotheses, not verified labels."""
import asyncio
import json
import sys

sys.path.insert(0, ".")
from src.retrieve import citation, retrieve  # noqa: E402


async def main(mode: str = "hybrid") -> None:
    cases = [json.loads(l) for l in open("eval/gate_incidents.jsonl", encoding="utf-8") if l.strip()]
    for c in cases:
        hits = await retrieve(c["incident"], mode=mode)
        print(f"\n#{c['id']} [{mode}] {c['incident']}\n   user hypothesis: {c['expected_user_hypothesis']}")
        if c.get("expected_sections"):
            top5 = {(h.act, h.number) for h in hits[:5]}
            found = [f"{a}:{n}={'IN top5' if (a, n) in top5 else 'NOT in top5'}" for a, n in c["expected_sections"]]
            print("   gate check:", "; ".join(found))
        for i, h in enumerate(hits, start=1):
            snippet = h.text.replace("\n", " ")[:110]
            print(f"   {i}. {h.act}:{h.number} sim={h.vector_sim:.2f} v#{h.vector_rank} k#{h.keyword_rank} | {snippet}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "hybrid"))
