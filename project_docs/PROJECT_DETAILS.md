# Statute Finder India — Full Project Documentation

**Repo:** `<github-url>` (add after push)
**Live demo:** https://statute-finder-india.onrender.com
**Built:** 13–16 October 2026, solo, against a deadline of Friday 16 Oct 12:00 IST
**Decision log:** `DECISIONS.md` (54 entries, each marked as decided by me, delegated, or forced)

---

## 1. What it is

A web service that takes a free-text description of an incident (and an optional date) and returns the sections of five Indian statutes that may apply, with the exact text, the page of the source PDF, the source URL, and — for incidents before 1 July 2024 — the IPC equivalent from a comparison table.

The statutes: Bharatiya Nyaya Sanhita 2023 (BNS), Arms Act 1959, Motor Vehicles Act 1988, Information Technology Act 2000, and the Tamil Nadu Prohibition of Harassment of Women Act 1998.

**The brief (from Ravi, President of Quascenta):** "Build a RAG over Indian legal acts (central + Tamil Nadu, at least 4–5 acts) so a person can describe an incident and see which sections apply, with citations to the actual text. Example scenarios: theft, income tax, constructing a house. You can choose the acts." Deliverables: working demo, README, eval.

This is not a "chat with a PDF" tool. Inputs are incidents, outputs are sections with provenance, and the system may refuse (abstain) or ask a question instead of answering.

---

## 2. Why it was built this way

### Fixed constraints I gave myself
Python, FastAPI, Postgres + pgvector (Neon), SQLAlchemy 2.x async, Alembic, fastembed `BAAI/bge-small-en-v1.5`, Groq `openai/gpt-oss-20b` through an OpenAI-compatible client, pytest against real Postgres, GitHub Actions, fully pinned dependencies. Infra files (DB engine, Alembic setup, CI) were copied from my earlier RAG project and fixed only where they broke.

### The anti-hallucination rule (non-negotiable)
The model never produces a section number or a quote that reaches the user. It selects among candidates it is given under opaque ids (C1…Cn); the server maps ids back to database rows and builds the citation, quote, page and URL from the row. A validator drops any id not in the candidate set, and every quote is re-read from the PDF at the stored offsets.

### The design table
| Concern | Choice | Reasoning |
|---|---|---|
| PDF text | PyMuPDF | page text + offsets + rectangles for the highlighted-page demo |
| Provenance | list of `(page, start, end)` slices of raw page text per section, source file sha256, URL, retrieval time | a citation can be re-verified by re-opening the file and cutting the same slices |
| Chunking | one chunk per section; sections over ~2,000 chars cut at sub-section markers `(1)`, `(2)`; tails under 60 chars merged | keeps legal structure; embedding model reads ~512 tokens (assumed from model card) |
| Embedded text | header (act, chapter, section, title) + text; quote shown is always the raw text | title vocabulary helps lay queries match |
| Vector search | exact scan, no ANN index | about 1,000 chunks; an approximate index adds recall loss and filtered-query truncation for no gain |
| Keyword search | BM25 over Postgres `english` lexemes (own ~40-line implementation) | Postgres `ts_rank_cd` has no IDF; shown to fail on the knife case |
| Fusion | RRF within each act (guarantees each act a chance), then a second RRF over the pooled candidates | RRF scores are only comparable inside the same lists |
| Abstention | model judgement from candidate text, fixed reason codes; no score floor | cosine and BM25 scores overlap completely between in-scope and out-of-scope queries |
| Date routing | deterministic regex + cut-over at 1 July 2024; year-only 2024 is "ambiguous" | the model must never decide the legal regime |
| Questions | deterministic severity rule, at most 2 questions | the model's guess of "hurt" from the word "injury" was shown to be wrong |
| Status flags | curated table (IT s.66A struck down, BNS s.106(2) reported not in force) with source and verification level | shown with a warning, not hidden |
| Deployment | Render (Docker, free plan) + Neon | same as my earlier project |

---

## 3. Architecture

```
incident text ──► fact extraction (LLM, fixed schema, extra keys rejected)
              ├─► date routing (regex)  ──► IPC / BNS / ambiguous
              ├─► severity rule         ──► up to 2 clarifying questions
              └─► query cleaning        ──► retrieval

retrieval   per act: vector (exact cosine) + BM25, RRF  → top 3 per act
            pool of ≤15 sections re-ranked per leg and fused again → 8 candidates

generation  LLM sees candidates as C1..C8, returns {abstain, groups[answer_to, items[id, why,
            plain_summary, punishment, applies_when]], not_applicable}
validator   drop ids not in the set (1 retry, then validation_failed); drop summaries whose
            figures (digits or number words) are not in the quoted text; re-read each quote
            from the PDF; attach IPC equivalents and status warnings from the database
```

### Database schema (Alembic 0001–0003)
- `acts` — short_name, title, year, jurisdiction, version_note, effective_from/to (null until verified), superseded_by
- `source_files` — filename, sha256, source_url, retrieved_at, page_count, role (`corpus`/`mapping`)
- `sections` — act, anchor (`bns_2023:s103`), number, title, chapter, status (`in_force`/`omitted`), text, page_start/end, char_start/end, `segments` (JSON)
- `chunks` — section, chunk_no, header, text, offsets, `embedding vector(384)`, generated `fts tsvector`
- `ipc_bns_mapping` — bns_ref, bns_section, subject, ipc_ref, summary, page (527 rows, all 358 BNS sections)
- `provision_status` — curated struck-down / not-in-force flags with source and verification level

### Corpus (verified against each file's own table of contents where one exists)
| file | source | sections | note |
|---|---|---|---|
| `bns_2023.pdf` | MHA | 358 | as enacted; no section titles; some glued words in the text layer |
| `arms_act_1959.pdf` | India Code | 48 | = file TOC |
| `mv_act_1988.pdf` | India Code, "as on 15 Aug 2026" | 257 | = file TOC; First Schedule (51 image pages) not read |
| `it_act_2000.pdf` | India Code | 125 | = file TOC; 13 omitted |
| `tn_harassment_women_1998.pdf` | Indian Kanoon print on a TN government site | 14 | file says it "could not be verified"; s.5(1) clauses missing in source |
| `bns_ipc_comparison_keralaprisons.pdf` | CAPT Bhopal (not MHA) | 527 rows | parsed with `find_tables` |
| not ingested | IPC 1860 (police-site copy with commentary), TN Dangerous Activities Act (OCR scan) | | |

---

## 4. The debugging log — real problems hit and fixed

Almost nothing worked first time; each item below came from reading real output.

1. **BNS parsed to 350 sections, not 358.** The text layer has no space after the full stop in some headings ("104.Whoever"); the heading regex required whitespace. Fixed by allowing none.
2. **My own Phase-1 counts were wrong.** A footnote stoplist matched on the prefix "Rep", so the real heading "46. Repeal of Act 11 of 1878" was dropped from both the table of contents and the body — the two lists agreed because they shared the bug. I also had two wrong last-page numbers. Corrected counts: Arms 48, IT 125, MV 257. Lesson: a parser validated against an index only proves anything if the check is independent of the parser's own filters.
3. **Reading the ingested rows back found Gazette running footers inside 106 of 1,032 chunks** ("THE GAZETTE OF INDIA EXTRAORDINARY", rows of underscores), plus 5–8 character tail chunks ("harm."). 19 parser tests had passed. Fixed by cutting the footer block while slicing and merging tails; added a test.
4. **Gazette front matter (Hindi legacy-font lines) was inside BNS s.1 and a digital-signature block inside s.358** — the sections I quote for commencement and repeal. Fixed with a `drop_spans` entry in the manifest and an end-of-act rule; added a test.
5. **Source quality is uneven.** The IPC "PDF" from a police website mixes commentary into the text; the TN 1982 act from PRS is an OCR scan ("Drug-offenlkrs"); the TN Harassment Act file states it "could not be verified". Decision: IPC used only through the comparison table; the 1982 act dropped; the Harassment Act used with its caveat disclosed.
6. **Per-act fusion produced a meaningless merged ranking.** RRF scores are rank-based, so every act's top hit got the same score and unrelated acts padded the list. Fixed with a pooled second pass.
7. **Postgres full-text search failed on "stabs someone with a knife"** (BNS 118 ranked outside the top 15 of its act): `ts_rank_cd` has no inverse document frequency, so "person" counted as much as "stab". Replaced with BM25 over the same lexemes.
8. **No score threshold separates in-scope from out-of-scope** (BM25 8.8–23.9 vs 7.7–16.5; cosine 0.55–0.70 vs 0.52–0.65). Measured before building abstention; abstention became a model judgement with fixed reason codes.
9. **Reasoning model, empty output.** gpt-oss spent a 600-token budget thinking and returned nothing (HTTP 400 `json_validate_failed`). Fixed with a larger budget and `reasoning_effort=low`.
10. **Prompt wording leaked into facts.** Listing "phones" under `electronic_or_online` made phone theft come out as online=yes.
11. **The severity rule.** The model read "causes an injury" as "hurt". Replaced by a deterministic rule: severity is established only by explicit cue words; "injury/hurt/wounded" are not cues. Later fixes from real runs: "dies" and "takes her own life" were missing cues; "tried to stab me" is an attempt and should ask whether anyone was hurt; a weapon question made no sense for a car crash or a suicide.
12. **A pre-2024 incident abstained** because the prompt never said BNS candidates stand in for the IPC. Added the note.
13. **The shown "quote" for BNS s.303 was an illustration from the middle of the section.** Added the section's opening chunk as a second, separately verified quote.
14. **The model wrote "section C1" in its explanations.** Internal ids are now stripped.
15. **The highlighted page also highlighted repeated phrases in neighbouring sections.** Highlighting now keeps only the contiguous run of quote lines.
16. **A plain-summary figure check that only looked at digits** let "up to ten years" through. It now checks number words.
17. **Small models padded the answer groups** with candidates described as "not relevant here". Those are now moved to `not_applicable`.
18. **A summary of BNS s.101 inverted its meaning** ("kills someone while defending themselves … it is murder"). No figure to catch; disclosed in the README. Card AM (suppress summaries on exception-heavy passages) was considered and deliberately not done (decision 55): the risk is accepted and stated.
19. **Groq free tier limits.** First the per-minute cap (8,000 tokens/min) caused 429s in bursts; then the daily cap (200,000 tokens/day) was exhausted by repeated eval attempts, so one full generation pass (~290,000 tokens) cannot fit in a day. One eval run silently stalled with no progress output for two hours; the runner was rewritten to be resumable with per-case logging and hard timeouts. Two reports I generated showed "8/8 negatives abstained" that were really API errors; I discarded them.
20. **Rewrite baseline silently equal to hybrid.** Empty replies fell back to the original query, so "no gain" meant "all calls failed". Fixed (bigger budget, retry) and the failure count is reported.
21. **`reasoning_effort` rejected by a local model** (`qwen2.5:7b does not support thinking`). Made it an environment setting.
22. **A secret printed to my terminal by a scan I ran.** The Neon password appeared in this session's output; recommended rotation.
23. **Stale servers.** Two screenshots showed old behaviour because `uvicorn` had not been restarted; `/health` and the page footer now show a build marker captured at process start.
24. **CI:** the first run on Linux passed 101 of 102 tests; the failure was a test that still expected `/health` to return exactly `{"status":"ok"}` after I added the build field.

---

## 5. Testing strategy

About 100 tests, run against a real Postgres + pgvector instance and the real PDFs. The embedding model and the LLM are faked in tests, so only the deterministic paths and the plumbing are under test.

- **Parsing** — manifest hashes match files; parsed ids equal each file's own table of contents; stored segments reproduce the text exactly; no page footers or rule lines in section text; BNS s.1 and s.358 free of Gazette junk; mapping covers all 358 BNS sections.
- **Provenance** — a quote resolves at its stored offsets; shifted offsets, wrong page and an invented quote are rejected.
- **Retrieval** — per-act caps and filters; omitted sections never returned; BM25 prefers rare terms; query stems meet document stems; citations are built from DB fields.
- **Facts / dates / questions** — 12-case date table including 30 June vs 1 July 2024; severity rule; two-question cap; retrieval is independent of the severity heuristic; schema rejects extra keys and bad enums.
- **Answers** — invented id dropped and logged; all-dropped triggers one retry then `validation_failed`; model abstention text is the server's; a quote that does not resolve is dropped; summaries with unsupported figures removed; invalid answer tags dropped.
- **UI** — page, health (GET and HEAD), highlighted page image, 404 / 422 handling.

---

## 6. CI/CD

GitHub Actions: Python 3.12, a `pgvector/pgvector:pg16` service container, `pip install -r requirements.txt` (fully pinned), `python -m pytest -v`. CI does not deploy. Deployment is Render connected to the GitHub repository (Docker, free plan); the embedding model is downloaded at image build time. Migrations and ingest are run separately against Neon, not at boot.

---

## 7. Known limitations (own these, don't hide them)

- **Eval labels are unreviewed.** 41 cases drafted by an AI agent from the stored statute text; gold sections were found by SQL text search, not by the retriever; labelled by a non-lawyer, not reviewed by counsel.
- **Generation numbers are from a local model** (`qwen2.5:7b`), not the hosted model, because the hosted model's daily token cap could not fit a full pass.
- **Retrieval depends on wording.** Examples: "promising to double money" misses BNS 318; "attacked with a knife" misses BNS 118; "no licence" misses MV 181 because the penalty section only cross-references the requirement.
- **Plain-language summaries are model-written.** The figure check catches wrong numbers, not a wrong legal effect (BNS s.101 example).
- **IPC text is not in the corpus.** For pre-July-2024 incidents the IPC numbers come from a table by CAPT Bhopal, not an official MHA publication.
- **Commencement notification not verified.** The 1 July 2024 date comes from PIB; S.O. 850(E) and the BNS s.106(2) carve-out were not checked in the Gazette.
- **IT s.66A flag** rests on a located source (Indian Kanoon / Supreme Court digital reports), not a re-read judgment.
- **No amendment tracking**; acts other than the BNS are the current consolidated text only.
- **MV First Schedule** is image-only and not read (no OCR).
- **BNS has no section titles**, and some words are glued in the text layer; quotes show them as extracted.
- **Free-tier realities:** the service sleeps after idle; about 25 full queries per day on the free model quota.
- **No authentication, no rate limiting.**

---

## 8. What I'd do differently at scale

- A paid model tier (or a self-hosted model) so a full eval pass is routine, and a re-run on the hosted model.
- Have a lawyer review the 41 cases and expand to 150+ with real user phrasing.
- Query rewriting on by default only after measuring it per model (it gained 2 cases with gpt-oss and 4 with qwen on this set, and the prompt was written after seeing the failures).
- Parse official gazette sources for the IPC and for each act's versions as on date, so temporal answers quote the law in force at the time.
- Track amendments (a source-of-truth feed) instead of manual flags.
- OCR for image-only schedules; an ANN index only if the corpus grows by an order of magnitude.

---

## 9. Evaluation (numbers exactly as measured)

41 cases: 21 single-act, 5 multi-act, 8 out-of-scope, 4 temporal, 3 underspecified. **Labels unreviewed.**

### Retrieval (33 cases with gold sections; hit@3)
| mode | hit@3 |
|---|---|
| vector only | 21/33 |
| BM25 only | 12/33 |
| hybrid (shipped) | 22/33 |
| hybrid + rewrite | 24/33 (gpt-oss-20b rewrite) · 26/33 (qwen2.5:7b rewrite) |

### Generation (all 41 cases, `qwen2.5:7b` on Ollama, read-only against Neon)
| measure | result |
|---|---|
| quotes shown that resolve in the source PDF | 57/57 |
| sections shown that were not retrieved | 0 |
| out-of-scope cases abstained | 7/8 |
| in-scope cases wrongly abstained | 0/33 |
| in-scope cases with ≥1 gold section shown | 21/33 |
| shown sections that are gold or acceptable | 26/56 |
| expected clarifying question asked | 4/4 |
| date regime correct | 5/5 |

The hosted-model generation run was blocked by the daily token cap and is not reported.

---

## 10. Deployment and runtime facts

- **Live:** https://statute-finder-india.onrender.com; `/health` returns a build marker of the code the process loaded.
- **Memory (measured locally, Windows working set):** about 270 MB after first retrieval (model + BM25 index), 293 MB peak after page-image rendering and a burst of six concurrent searches; the Render free plan is 512 MB.
- **Neon:** migrated (0001–0003) and ingested: BNS 358/423, Arms 48/65, IT 125/137, MV 257/367, TN 14/14 (sections/chunks); 527 mapping rows; 2 status flags.
- **Endpoints:** `POST /answer`, `POST /analyze` (no generation), `POST /retrieve` (no LLM), `GET /page-image?chunk_id=`, `GET /health`, `GET /`.
