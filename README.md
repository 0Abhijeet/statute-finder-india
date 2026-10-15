# Statute Finder India

Given a free-text description of an incident and an optional date, this service returns the sections of five Indian statutes (Bharatiya Nyaya Sanhita 2023, Arms Act 1959, Motor Vehicles Act 1988, Information Technology Act 2000, Tamil Nadu Prohibition of Harassment of Women Act 1998) that may apply, with the exact text, page number and source of each section. *Informational, not legal advice.*

**Live demo:** _(Render URL: add after deploy)_ · **Demo script:** [DEMO.md](DEMO.md) · **Eval:** [eval/REPORT.md](eval/REPORT.md) · **Decision log:** [DECISIONS.md](DECISIONS.md)

## One real example

Input: `"Someone secretly takes a stranger's phone from their bag without permission."`, incident date `2022-03-10`. Output (trimmed; produced by the pipeline with a local `qwen2.5:7b` model, see "Which model produced which number"):

```json
{
  "date": {"date": "2022-03-10", "regime": "ipc",
           "note": "Incident date 2022-03-10 (exact): before 1 July 2024: the IPC applied."},
  "answer": {"abstained": false, "groups": [{
    "condition": "Theft of personal property without consent",
    "items": [{
      "citation": "Bharatiya Nyaya Sanhita 2023, Chapter XVII, s.303 (pages 78-79 of bns_2023.pdf)",
      "opening_quote": "303. (1) Whoever, intending to take dishonestly any movable property out of the\npossession of any person without that person’s consent, moves that property in order to\nsuch taking, is said to commit theft. ...",
      "source_url": "https://www.mha.gov.in/sites/default/files/2024-04/250883_english_01042024.pdf",
      "retrieved_at": "2026-10-14T12:46:00+00:00",
      "label": "equivalent current provision (BNS, in force from 1 July 2024); the IPC text is not in the corpus",
      "ipc_equivalents": [
        {"bns_ref": "303(1)", "ipc_ref": "378", "subject": "Theft.",
         "mapping_source": "page 30 of bns_ipc_comparison_keralaprisons.pdf"},
        {"bns_ref": "303(2)", "ipc_ref": "379", "subject": "Punishment for theft.",
         "mapping_source": "page 30 of bns_ipc_comparison_keralaprisons.pdf"}],
      "why_it_applies": "The incident involves taking an article (the phone) belonging to another person ... without their consent ..."
    }]}]},
  "disclaimer": "Informational, not legal advice."
}
```

The quote, citation, page and URL are read from the database row; only `why_it_applies` is model-written and it is labelled as such. The "Show the cited page" button in the web page renders that PDF page with the quoted lines highlighted.

## Versioning: before and after 1 July 2024

The same incident, routed by date (deterministic code in `src/dating.py`; the model never decides this):

| incident date | regime | what is shown |
|---|---|---|
| 2022-03-10 | IPC | BNS s.303 as the equivalent provision, with IPC 378 and 379 from the comparison table (page 30 of the table PDF); the IPC text itself is not in the corpus |
| 2024-06-30 | IPC | same |
| 2024-07-01 | BNS | BNS s.303, no IPC mapping |
| 2025-03-10 | BNS | same |
| "in 2024" (year only) | ambiguous | both branches, plus a question asking for the date |
| no date | BNS | today's date is assumed and the output says so |

Source of the rule: BNS s.358 (in the stored official MHA text) repeals the IPC but saves "any penalty, or punishment incurred in respect of any offences committed against the Code"; BNS s.1(2) leaves commencement to a notification. The 1 July 2024 date comes from PIB; the notification itself (S.O. 850(E)) was not checked against the Gazette.

## How it works

```
incident text ──► fact extraction (LLM, fixed schema, extra keys rejected)
              ├─► date routing (regex, deterministic) ──► IPC / BNS / ambiguous
              ├─► severity rule (deterministic) ──► up to 2 clarifying questions
              └─► query cleaning ──► retrieval
retrieval:  per act: vector (bge-small, exact scan) + BM25 over Postgres lexemes, RRF
            → top 3 per act → pooled and re-ranked with RRF → 8 candidates
generation: LLM sees candidates as opaque ids (C1..C8), returns ids + one-line reasons
            validator drops ids not in the set (one retry, then "validation_failed")
            quote + citation + page + URL come from the database row;
            each quote is re-read from the PDF at the stored offsets
```

Key design points (each is an entry in `DECISIONS.md`):

- **Plain-language summaries.** Each shown section can carry a two-to-three-sentence summary written by the model for the passage displayed. It is labelled as model-written, sits next to the verbatim text, and is removed if it contains a figure (digits or number words, e.g. "ten years") that is not in that text.
- **Conditional candidates beside the question.** When a clarifying question is open, the page lists the provisions that would apply under each possible answer. The tags are validated against the question's options.

- **Provenance at parse time.** A section is stored as a list of `(page, start, end)` slices of the raw PDF text, plus the source file's sha256, URL and retrieval time (`data/raw/manifest.json`). A citation can be re-verified by re-opening the file and cutting the same slices.
- **The model selects, it does not write the law.** No section number or quote that reaches the user is produced by the model.
- **Abstention is a judgement, not a threshold.** Cosine and BM25 scores for in-scope and out-of-scope queries overlap (in-scope BM25 8.8-23.9, out-of-scope 7.7-16.5), so a score floor was rejected.
- **Exact vector search, no ANN index.** About 1,000 chunks; an approximate index adds recall loss and filtered-query truncation for no speed benefit.
- **Legal-status flags are curated.** IT s.66A (struck down) and BNS s.106(2) (reported not in force) carry a visible warning with a source and a verification level (`data/provision_status.json`).

## Corpus

| source | role | sections | notes |
|---|---|---|---|
| Bharatiya Nyaya Sanhita 2023, MHA PDF | corpus | 358 | as enacted; no section titles in the text layer; some words are glued together in the PDF text ("ThisAct"); stored as extracted |
| Arms Act 1959, India Code | corpus | 48 | |
| Motor Vehicles Act 1988, India Code ("as on 15 Aug 2026") | corpus | 257 | 6 omitted sections stored but not retrieved; the First Schedule (51 image-only pages) is not ingested |
| Information Technology Act 2000, India Code | corpus | 125 | 13 omitted sections stored but not retrieved |
| TN Prohibition of Harassment of Women Act 1998 | corpus | 14 | an Indian Kanoon print hosted on a TN government site that states its content "could not be verified"; the clauses of s.5(1) are missing in that source |
| IPC↔BNS correspondence table (CAPT Bhopal) | mapping | 527 rows, all 358 BNS sections | not an MHA publication |
| IPC 1860 (police-department site copy) | not ingested | | commentary mixed with the text; not an official source |
| TN Prevention of Dangerous Activities Act 1982 (PRS scan) | not ingested | | OCR errors |

Tables and images: the comparison table is parsed with PyMuPDF `find_tables` (37 tables, 527 rows, all BNS sections 1-358 covered). Image-only pages (MV First Schedule) are not read; there is no OCR.

Updating data: every source file's sha256 is in the manifest and a test fails if a file changes; `python -m src.ingest` is idempotent per act. There is no automatic fetching and no amendment tracking.

## Evaluation

41 cases in `eval/cases.jsonl` (21 single-act, 5 multi-act, 8 negative, 4 temporal, 3 underspecified). **All labels are `unreviewed`: drafted by an AI agent from the stored statute text, by a non-lawyer, not reviewed by counsel.** Gold sections were found by SQL text search over the stored statutes (not by the retriever) and each is checked to exist; numbers are an engineering signal, not legal accuracy. Full report with per-act counts and a line per failure: [eval/REPORT.md](eval/REPORT.md) (that file is the `qwen2.5:7b` run; an earlier run on the hosted model produced valid retrieval numbers but its generation step was blocked by the daily token cap, so its generation numbers are not reported).

### Retrieval (33 cases with gold sections; hit@3 = a gold section is in the top 3)

| mode | hit@3 | recall@5 (sum) |
|---|---|---|
| vector only | 21/33 | 21.0 |
| keyword (BM25) only | 12/33 | 14.5 |
| hybrid (shipped) | 22/33 | 21.5 |
| hybrid + LLM query rewrite (not default) | 24/33 (gpt-oss-20b) · 26/33 (qwen2.5:7b) | 24.0 · n/a |

Rewrite prompt was written after seeing these failures, so its gain is optimistic. 7 of 41 gpt-oss rewrites came back empty and fell back to plain hybrid.

### Generation, validation, abstention (all 41 cases, `qwen2.5:7b` on Ollama)

| measure | count |
|---|---|
| quotes shown that resolve in the source PDF | 57/57 |
| sections shown that were not in the retrieved set | 0 |
| out-of-scope cases correctly abstained | 7/8 |
| in-scope cases wrongly abstained | 0/33 |
| in-scope cases with at least one gold section shown | 21/33 |
| shown sections that are gold or acceptable | 26/56 |
| expected clarifying question asked | 4/4 |
| spurious clarifying question | 2/29 (a rule bug since fixed; not re-measured) |
| date regime correct | 5/5 |
| IPC equivalent shown includes an expected IPC ref | 1/3 |

### Which model produced which number

- Retrieval: independent of the generation model. Exception: the rewrite column.
- Generation table: a local `qwen2.5:7b`, **not** the `openai/gpt-oss-20b` (Groq) model the deployed app uses. A full pass on the hosted model did not fit in Groq's free daily token cap (200,000 tokens/day; one pass needs about 290,000). A 21-case subset on the hosted model is the planned check _(update this section if it was run)_.

### Three real failures and their causes

1. **"Promising to double Rs 50,000 and disappearing" (s02): BNS 318 is absent from the top 8 of every mode.** The section says "deceiving ... fraudulently or dishonestly induces ... delivery of property"; the incident uses none of those words and no leg bridges them. The gpt-oss-20b rewrite did not recover it; the qwen2.5:7b rewrite did (rank 1), so the fix depends on which model rewrites.
2. **"Attacked with a knife" / "shoots his neighbour in the arm" (u01, m04): BNS 118 is absent from every mode.** The text says "voluntarily causes hurt by means of any instrument for shooting, stabbing or cutting"; the lay verbs ("attacked", "shoots") do not overlap with it. The same incident worded "stabs ... causes an injury" does retrieve it (gate case 1), which shows how wording-dependent this is. Neither rewrite recovered u01; the qwen rewrite put 118 at rank 4 for m04, the gpt-oss one did not.
3. **"Teenager drives a scooter with no licence" (s12): MV 181 is absent from every mode.** The offence section only says "drives a motor vehicle in contravention of section 3 or section 4", so lay words match the requirement sections instead of the penalty section. Statutory cross-reference, not vocabulary. Neither rewrite recovered it.

Also visible in the table: in several cases the right section was retrieved but the local model did not select it (s08, t01), and it selects extra sections (26 of 56 shown are gold or acceptable).

## What was cut, and why

| cut | reason |
|---|---|
| Income tax | answers depend on slabs and schedule tables, a second document type for one scenario |
| TN building / planning rules | no suitable Tamil Nadu act in scope; planning permission is answered as out of scope |
| IPC as a corpus act | no official IPC text in hand; used only through the mapping table |
| BNS section titles | marginal headings are in the text but at misaligned positions |
| OCR for image pages | MV First Schedule only |
| ANN index (HNSW) | about 1,000 chunks |
| Tracing (Langfuse) | not needed for the deliverables |
| Full generation eval on the hosted model | daily token cap |
| Procedure (BNSS vs CrPC) | out of scope; stated in every response |

## Known limits

- Labels are unreviewed and by a non-lawyer; wording of the cases was written by the same agent that built the retriever.
- Plain-language summaries are model-written. The figure check catches a wrong number or term of years, not a wrong legal effect: on BNS s.101 (murder, with exceptions) the hosted model wrote that the excepted cases "are murder", which inverts the section. Read the verbatim text beside every summary.
- Retrieval depends on wording (failures above). No similarity floor exists; abstention relies on the model's judgement.
- The deployed model's answers vary between runs, and the validator removes repeated ids silently apart from a notice.
- IT s.66A and BNS s.106(2) flags rest on a located source (66A: Indian Kanoon / Supreme Court digital reports, judgement not re-read) and on third-party reports (106(2)); the notification S.O. 850(E) was not checked against the Gazette.
- Acts other than the BNS are the current consolidated text; versions as on an earlier incident date are not available.
- An offence spanning 1 July 2024 is routed by the date given only.
- Attempts: "tried to stab me" is recognised as an attempt (the question becomes "was anyone actually hurt?"), but retrieval is not tuned for attempt provisions, so the candidates shown mostly cover the case where someone was hurt.
- Free-tier rate limits: a burst of requests returns "The answer could not be generated".

## Run it

```bash
python -m venv venv && venv/Scripts/activate        # Python 3.12
pip install -r requirements.txt                      # fully pinned
cp .env.example .env                                 # set DATABASE_URL and LLM_API_KEY
docker compose up -d db                              # local pgvector on port 15433
alembic upgrade head
python -m src.ingest                                 # parses data/raw/*.pdf per manifest.json
uvicorn src.app:app                                  # http://localhost:8000
```

Tests need a database whose name ends in `_test` (the fixture refuses anything else):

```bash
DATABASE_URL=postgresql://statute:statutepassword@localhost:15433/statutedb_test python -m pytest -v
```

Eval: `python scripts/run_eval.py [--subset]`. It is resumable and paced for Groq's free tier; set `EVAL_TAG`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_REASONING_EFFORT=""` to run it against a local model.

## Deploy (Render + Neon)

1. Run `alembic upgrade head` and `python -m src.ingest` once against the Neon database (the app does not ingest on boot).
2. Push the repository, create a Docker web service (see `render.yaml`), set `DATABASE_URL` (with `?sslmode=require`) and `LLM_API_KEY`.
3. The image downloads the embedding model at build time. Measured locally: peak working set about 290 MB after retrieval, BM25 index load, page-image rendering and a burst of concurrent requests (Windows working set; a Linux container may differ), so the 512 MB free plan should fit; the free plan sleeps after idle and the first request afterwards takes tens of seconds.
