"""Locate candidate gold sections by SQL text search over the stored statute text (not by
the retriever, so labels are not circular). Usage:
    python scripts/find_sections.py "snatching" "defamation" ...   [--act bns_2023] [--n 4]
Prints act:number, status and the first 200 characters of each match."""
import argparse
import asyncio
import re
import sys

sys.path.insert(0, ".")
from sqlalchemy import text  # noqa: E402

from src.database import AsyncSessionLocal  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("terms", nargs="+")
    ap.add_argument("--act", default=None)
    ap.add_argument("--n", type=int, default=4)
    args = ap.parse_args()
    async with AsyncSessionLocal() as db:
        for term in args.terms:
            print(f"\n== {term!r}")
            rows = await db.execute(text("""
                select a.short_name, s.number, s.status, s.text
                from sections s join acts a on a.id = s.act_id
                where s.text ilike :t and (cast(:act as text) is null or a.short_name = :act)
                order by a.short_name, nullif(regexp_replace(s.number, '[^0-9]', '', 'g'), '')::int, s.number
                limit :n"""), {"t": f"%{term}%", "act": args.act, "n": args.n})
            for r in rows:
                body = re.sub(r"\s+", " ", r.text)
                i = body.lower().find(term.lower())
                snippet = body[max(0, i - 60): i + 140]
                print(f"  {r.short_name}:{r.number} [{r.status}] ...{snippet}...")


asyncio.run(main())
