"""Ingest the manifest's files into Postgres. Idempotent: re-running replaces each
act's sections/chunks (and the mapping rows) with identical content; it never
touches other acts. Verifies each file's sha256 against the manifest first."""
import asyncio
import datetime as dt
import json
import os

from sqlalchemy import delete, select

from src.chunking import build_header, chunk_text
from src.database import AsyncSessionLocal
from src.embeddings import get_embeddings
from src.mapping import parse_mapping
from src.models import Act, Chunk, IpcBnsMapping, Section, SourceFile
from src.parsing import parse_act
from src.provenance import sha256_of
from src.status import sync_status

RAW_DIR = "data/raw"


def load_manifest(raw_dir: str = RAW_DIR) -> list[dict]:
    with open(os.path.join(raw_dir, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)["files"]


def verify_files(entries: list[dict], raw_dir: str = RAW_DIR) -> None:
    """Raise if a file on disk no longer matches the manifest hash."""
    for e in entries:
        if e["role"] == "not_ingested":
            continue
        actual = sha256_of(os.path.join(raw_dir, e["file"]))
        if actual != e["sha256"]:
            raise RuntimeError(f"{e['file']}: sha256 {actual[:12]} != manifest {e['sha256'][:12]}")


async def _upsert_source(db, entry: dict, act_id: int | None) -> SourceFile:
    row = (await db.execute(select(SourceFile).where(SourceFile.sha256 == entry["sha256"]))).scalar_one_or_none()
    if row is None:
        row = SourceFile(sha256=entry["sha256"])
        db.add(row)
    row.act_id = act_id
    row.filename = entry["file"]
    row.source_url = entry["source_url"]
    row.retrieved_at = dt.datetime.fromisoformat(entry["retrieved_at"])
    row.page_count = entry["page_count"]
    row.role = entry["role"]
    await db.flush()
    return row


async def ingest_act(entry: dict, raw_dir: str = RAW_DIR) -> dict:
    path = os.path.join(raw_dir, entry["file"])
    sections = await asyncio.to_thread(
        parse_act, path, tuple(entry["body_pages"]), entry["titles_in_text"], entry.get("drop_spans")
    )
    # One chunk row per short section; sub-chunks for long ones (decision 18).
    plan = []
    for s in sections:
        header = build_header(entry["act_title"], entry["year"], s.chapter, s.number, s.title)
        for n, (a, b) in enumerate(chunk_text(s.text)):
            plan.append((s, n, header, a, b))
    texts = [f"{header}\n{s.text[a:b]}" for s, _, header, a, b in plan]
    vectors = await asyncio.to_thread(get_embeddings().embed_documents, texts)

    async with AsyncSessionLocal() as db:
        try:
            act = (await db.execute(select(Act).where(Act.short_name == entry["act_short_name"]))).scalar_one_or_none()
            if act is None:
                act = Act(short_name=entry["act_short_name"])
                db.add(act)
            act.title, act.year, act.jurisdiction = entry["act_title"], entry["year"], entry["jurisdiction"]
            act.version_note = entry.get("version_note")
            await db.flush()
            src = await _upsert_source(db, entry, act.id)

            await db.execute(delete(Section).where(Section.act_id == act.id))  # chunks cascade
            await db.flush()
            row_for = {}
            for s in sections:
                row = Section(
                    act_id=act.id, source_file_id=src.id,
                    anchor=f"{act.short_name}:s{s.number}", number=s.number,
                    title=s.title, title_source="act_text" if s.title else None,
                    chapter=s.chapter, chapter_title=s.chapter_title, status=s.status,
                    text=s.text, page_start=s.page_start, page_end=s.page_end,
                    char_start=s.segments[0].start, char_end=s.segments[-1].end,
                    segments=[{"page": g.page, "start": g.start, "end": g.end} for g in s.segments],
                )
                db.add(row)
                row_for[s.number] = row
            await db.flush()
            for (s, n, header, a, b), vec in zip(plan, vectors):
                db.add(Chunk(section_id=row_for[s.number].id, chunk_no=n, header=header,
                             text=s.text[a:b], char_start=a, char_end=b, embedding=vec))
            await db.commit()
            return {"act": act.short_name, "sections": len(sections), "chunks": len(plan)}
        except Exception:
            await db.rollback()
            raise


async def ingest_mapping(entry: dict, raw_dir: str = RAW_DIR) -> dict:
    rows = await asyncio.to_thread(parse_mapping, os.path.join(raw_dir, entry["file"]))
    async with AsyncSessionLocal() as db:
        try:
            src = await _upsert_source(db, entry, None)
            await db.execute(delete(IpcBnsMapping).where(IpcBnsMapping.source_file_id == src.id))
            for r in rows:
                db.add(IpcBnsMapping(source_file_id=src.id, bns_ref=r.bns_ref, bns_section=r.bns_section,
                                     subject=r.subject, ipc_ref=r.ipc_ref, summary=r.summary, page=r.page))
            await db.commit()
            return {"mapping_rows": len(rows)}
        except Exception:
            await db.rollback()
            raise


async def ingest_all(raw_dir: str = RAW_DIR) -> list[dict]:
    entries = load_manifest(raw_dir)
    verify_files(entries, raw_dir)
    out = []
    for e in entries:
        if e["role"] == "corpus":
            out.append(await ingest_act(e, raw_dir))
        elif e["role"] == "mapping":
            out.append(await ingest_mapping(e, raw_dir))
    async with AsyncSessionLocal() as db:
        out.append({"provision_status_rows": await sync_status(db)})
    return out


if __name__ == "__main__":
    for line in asyncio.run(ingest_all()):
        print(line)
