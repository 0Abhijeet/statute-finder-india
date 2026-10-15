"""Curated legal-status flags (decision 40): struck-down or not-in-force provisions.

A flagged provision is still retrieved and shown, but with a warning built here from the
table, never written by the model. Loaded from data/provision_status.json by ingest."""
import json
import os

from sqlalchemy import delete, select, text

from src.models import ProvisionStatus

SEED_PATH = os.path.join("data", "provision_status.json")

_HEADLINE = {
    "struck_down": "STRUCK DOWN: this provision is not an operative offence.",
    "not_in_force": "NOT IN FORCE (in whole or part).",
}


def warning_for(row: dict) -> dict:
    head = _HEADLINE.get(row["status"], "STATUS NOTE.")
    ver = {"source_located": "Source located (judgment/notification not re-read by this tool).",
           "third_party_only": "Reported by third-party outlets only; verify against the official source."
           }.get(row["verification"], "Unverified.")
    return {"status": row["status"], "scope": row["scope"], "warning": f"{head} {row['note']}",
            "verification": row["verification"], "verification_note": ver,
            "source_url": row["source_url"], "source_label": row["source_label"]}


def load_seed(path: str = SEED_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["entries"]


async def sync_status(db, path: str = SEED_PATH) -> int:
    """Replace the table contents with the seed file (idempotent)."""
    entries = load_seed(path)
    await db.execute(delete(ProvisionStatus))
    for e in entries:
        db.add(ProvisionStatus(act_short_name=e["act"], section=e["section"], status=e["status"],
                               scope=e["scope"], note=e["note"], source_url=e["source_url"],
                               source_label=e["source_label"], verification=e["verification"]))
    await db.commit()
    return len(entries)


async def statuses_for(db, anchors: list[str]) -> dict[str, dict]:
    """anchor ("it_act_2000:s66A") -> warning dict."""
    if not anchors:
        return {}
    rows = (await db.execute(select(ProvisionStatus))).scalars().all()
    by_anchor = {f"{r.act_short_name}:s{r.section}": r for r in rows}
    out = {}
    for a in anchors:
        r = by_anchor.get(a)
        if r:
            out[a] = warning_for({"status": r.status, "scope": r.scope, "note": r.note,
                                  "verification": r.verification, "source_url": r.source_url,
                                  "source_label": r.source_label})
    return out
