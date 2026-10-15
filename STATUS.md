# STATUS

Deadline: Fri 16 Oct 2026 12:00 IST. Solo.

## Phase checklist
- [x] Phase 0 skeleton: files created; requirements.txt locked and verified in a clean venv; db/alembic-upgrade/pytest-with-DB not yet run (Docker not running)
- [x] Phase 1 sources and parse test: corpus fixed (decision 15, 17); parse counts verified for all 5 acts; waiting for 'go' to start Phase 2
- [x] Phase 2 schema and ingest: complete and verified on the local docker db; waiting for 'go' to start Phase 3
- [x] Phase 3 retrieval: per-act + pooled global RRF, BM25 keyword leg, /retrieve, 30 tests; gate run with BM25 (see Verified); gate accepted by the user except BNS 115; teach-back passed
- [x] Phase 4 facts, clarifying questions, dates: built and tested (54 tests); live extraction run on the 10 gate incidents; waiting for 'go' for Phase 5; severity rule added (decision 36), 67 tests
- [x] Phase 5 generation and validator: built (src/answer.py, src/status.py, src/query.py; migrations 0001-0003; 84 tests); status flags + query cleaning added (decisions 40-42); teach-back question still unanswered
- [ ] Phase 6 eval
- [ ] Phase 7 packaging

## Verified
- Pinned versions seen in the old project's venv (`pip freeze`): fastapi 0.141.1, uvicorn 0.52.4, SQLAlchemy 2.0.52, asyncpg 0.31.0, alembic 1.19.1, greenlet 3.5.5, pgvector 0.5.0, fastembed 0.8.0, openai 3.16.2, pytest 9.1.1, pytest-asyncio 1.4.0, httpx 0.28.1, python-dotenv 1.2.3, pypdf 6.16.1.

- `requirements.txt` (61 lines, full freeze, Python 3.12.6): installed into a second fresh venv; `pip freeze` is identical and `pip check` is clean. psycopg2-binary resolved to 2.9.13, greenlet 3.5.6.
- `import src.database, src.models, src.embeddings, src.llm_client` succeeds; `alembic heads` runs (no revisions); `pytest` collects 0 tests.

- Live checks (2026-10-14): `.env` `DATABASE_URL` connects to a Neon pooler DB (`neondb`, PostgreSQL 18.6, empty: 0 public tables; `vector` 0.8.6 available, not yet installed). `LLM_API_KEY` works: one real call to `openai/gpt-oss-20b` via the Groq endpoint returned a reply. No shell-level `DATABASE_URL` set.

- Phase 1 probes (2026-10-14): India Code home reachable, but `bitstream/.../a202345.pdf` (BNS) returned 504 from this machine, so Act PDFs from India Code must be placed by hand. PRS India and keralaprisons.gov.in downloads work.
- `data/raw/tn_dangerous_activities_1982.pdf` (PRS copy, 32 pp, sha256 905f27f562fe...): text layer is OCR with visible errors ("Drug-offenlkrs", "TraJ$c"), 3 near-empty pages, first page is a PRS disclaimer. Third-party, not official. Verbatim quotes from it would carry OCR errors.
- `data/raw/bns_ipc_comparison_keralaprisons.pdf` (38 pp, sha256 3ad875b6162d...): clean text layer, tables detected by PyMuPDF. Credited to Anil Kishore Yadav, IPS, Director, CAPT Bhopal: NOT an MHA publication. No official MHA comparison PDF was found in search.

- Parse probe results (2026-10-14, PyMuPDF, scratch scripts, not yet in repo). Parsed section headings vs the file's own table of contents:
  - `bns_2023.pdf` (102 pp, sha256 c9da896e7a16...): 358 headings, ids 1-358, pp. 1-102. No TOC in the file; 358 matches the section count cited by third-party sources (not an official check). First attempt found 350; cause: no space after the period ("104.Whoever"); fixed by allowing zero whitespace. Text has missing spaces inside words ("ThisAct maybe", "CHAPTERI"): verbatim quotes will carry that.
  - `arms_act_1959.pdf` (26 pp, sha256 93bf306afce4...): TOC 47, body 47, id sets identical. Footnote lines ("1. Ins. by Act...") look like headings: needed a stoplist.
  - `it_act_2000.pdf` (36 pp, sha256 e71725fa32e8...): TOC 123, body 123, identical. TOC includes "[Omitted.]" entries (not yet counted).
  - `mv_act_1988.pdf` (176 pp, sha256 09d232b162f6...): "[As on the 15th August, 2026]" IndiaCode. TOC 254, body 254 (pp. 10-120), identical. pp. 121-172 are the First Schedule as images (51 pages, no text layer): not parseable without OCR.
  - `ipc_1860.pdf` (258 pp, sha256 a413b050ad22...): NOT an official gazette PDF: a website print ("Home", intro essay, per-section "CLASSIFICATION OF OFFENCE" and "Comments" blocks that are commentary, not statute). TOC has 551 ids. Fix attempt used: TOC-guided matching found 544/551 but the first ids are contaminated by an amendment-history list on pp. 23-24, so that count is NOT trustworthy. IPC parse unresolved.

- `tn_harassment_women_1998.pdf` (4 pp, sha256 d0133e0d304f..., downloaded 2026-10-14 ~19:47 from https://www.tnscw.tn.gov.in/departments_cms/uploads/tami_868/subpage_files/The_Tamil_Nadu_Prohibition_Of_Harassment_Of_Women_Act_1998.PDF): 14 headings: 1, 2, 3, 4, 4A, 4B, 4C, 5, 6, 7, 7A, 8, 9, 10; no TOC in file, continuity checked by sequence only. It is an Indian Kanoon print hosted on a TN government site; page 1 says "[This is the version of this document from 21 December 2016.]" and "[Note: The original publication document is not available and this content could not be verified.]". Defect: s.5(1) ends "shall, —(2)Any person who fails..." (the clauses of 5(1) are missing in the source). Sub-section markers run together with no spaces/newlines ("(1)This Act").
- `bns_ipc_comparison_keralaprisons.pdf` table check: PyMuPDF `find_tables` found 37 tables / 543 rows; BNS section numbers 1-358 all present in column 0 (0 missing). Rows have 4 or 6 columns (header rows differ) so normalization is needed. Not an official MHA document.
- Corpus per decision 15: BNS, Arms, MV, IT, TN Harassment of Women. `ipc_1860.pdf` and `tn_dangerous_activities_1982.pdf` stay in data/raw/ but are NOT ingested.

- Phase 2 (2026-10-14), parser rewritten into `src/parsing.py` (reads exact page slices; offsets stored per segment). **Correction to the Phase 1 counts above:** the Phase 1 scratch regex dropped any heading whose title started with "Rep"/"Ins"/etc. (e.g. Arms s.46 "Repeal of Act 11 of 1878") and used wrong body ranges, so those counts were slightly low. Corrected, parser vs the file's own TOC: Arms 48 = 48, IT 125 = 125, MV 257 = 257 (id sets identical); BNS 358 (no TOC); TN 14. Omitted sections detected: IT 13, MV 6.
- Section titles: Arms 48/48, IT 112/125, MV 250/257, TN 14/14 have a title in the text; **BNS has none** (the MHA text layer carries no section headings). Pending card.
- IPC<->BNS table: 527 rows covering all 358 BNS sections (`src/mapping.py`), incl. sub-clause rows like "326(a)".
- Chunks (decision 18): BNS 358 sections -> 448 chunks (56 split), Arms 48 -> 65, IT 125 -> 137, MV 257 -> 368, TN 14 -> 14; max chunk 2000 chars.
- Tests: `python -m pytest tests/test_parsing.py` -> 19 passed (manifest hashes, per-act counts, TOC equality, exact segment reproduction, BNS s.103 spot check, omitted detection, quote resolves and tampered offsets rejected, chunk coverage, mapping coverage).

- Local docker db up (pgvector/pgvector:pg16, host port 15433): `alembic upgrade head` -> `downgrade base` -> `upgrade head` clean; tables created: acts, chunks, ipc_bns_mapping, sections, source_files. `python -m pytest` with DATABASE_URL=...statutedb_test: **23 passed** (19 parsing + 4 ingest: idempotent, additive across acts, stored chunks resolve against the PDF, mapping stored with page).
- Real ingest into local dev db `statutedb` with the real fastembed model (~51 s, model downloaded): bns_2023 358 sections/448 chunks, arms_act_1959 48/65, it_act_2000 125/137, mv_act_1988 257/368, tn_harassment_women_1998 14/14, mapping_rows 527 (counts as printed by `python -m src.ingest`; not yet re-read from the database).
- Decision 24: BNS has no titles (title NULL).

- Phase 2 close-out (2026-10-14): read back from the local `statutedb`: acts/sections/chunks = arms 48/65, bns 358/424, it 125/137 (13 omitted), mv 257/367 (6 omitted), tn 14/14; mapping 527 rows, 358 distinct BNS sections; 6 source_files rows with hashes; page/offset spot checks present for bns s.103 (p.34), arms s.3 (pp.5-6), it s.66 (pp.23-24), tn s.4A (p.2).
- Data defect found by reading the first ingest back and fixed: BNS Gazette running footers ("THE GAZETTE OF INDIA EXTRAORDINARY", rows of underscores) were stored inside 106 of 1,032 chunks, and two chunks were 5-8 character tails ("harm."). Parser now cuts the footer block; chunking merges tails under 60 chars. After re-ingest: 1,007 chunks, 0 with footer text, 0 tiny in-force chunks. Two regressions I introduced on the way (BNS 356 sections; MV TOC) were caught by the tests and fixed.
- Informal retrieval sanity (vector only, real embeddings, not an evaluation): "driving without a licence" -> MV s.3, 9, 10, 7; "online fraud through a fake website" -> BNS 318, 335, IT 74, BNS 323; "someone stole my mobile phone" -> IT 66B first, BNS 304 and 303 next; "a person is hit with a knife" -> BNS 312, 101 (an illustration), 118, 307 (BNS 115 voluntarily causing hurt did not appear in the top 4). Suggests vector-only is weak on lay phrasing; Phase 3 measures this properly.
- Tests: 24 passed (19 parsing + footer-absence + 4 ingest) against `statutedb_test`.

- Phase 3 draft probe (local db, informal, 9 queries, not an evaluation): per-act retrieval + RRF within each act works mechanically, but merging acts by fused score is not meaningful (every act's rank-1 gets the same RRF score), so lists are padded with the rank-1 of unrelated acts (e.g. "hit with a knife" -> Arms 35, MV 134 in the top 5). Cosine similarity does not separate in-scope from out-of-scope: out-of-scope "income tax on salary" top-1 0.65 vs in-scope "teased a woman at a bus stop" top-1 0.50.

- Phase 3 gate (2026-10-14, hybrid, local db, `python scripts/gate.py`; expected sections are the USER's hypotheses in eval/gate_incidents.jsonl, label_status user_hypothesis_unverified): #1 knife stabbing: BNS 115 and 118 NOT in top 5 (top: 101, 351, 140); #2 phone theft: BNS 303 rank 1; #3 threat to kill: BNS 351 rank 1; #6 pistol without licence: Arms s.3 rank 1; #7 harassment at bus stop: TN s.4 rank 5, BNS s.79 (insult modesty, text read from db) rank 8; #9 planning permission: only unrelated results (similarity 0.46-0.55), no abstention yet; #10 needs date routing (Phase 4). #4, #5, #8 need the user's hand-check.
- Cause for #1, diagnosed: BNS 118's text contains "stabbing" (stems to "stab", matching the query) but ranks outside the BNS keyword top 15, because Postgres ts_rank_cd has no IDF: generic query words ("person", "someone", "during", "causes") weigh as much as "stab". 118 is vector rank 13 in BNS. Evidence for decision 25's known weakness.
- IT s.66A is stored as in force (the file's text does not mark it omitted). Assumed from general knowledge, NOT verified here: the Supreme Court struck it down in 2015. A retrieved 66A must carry a warning before it is shown as applicable.
- Tests: 29 passed (adds 5 retrieval tests: OR tsquery, per-act caps and filter, omitted never returned, provenance + citation built from db fields, /retrieve over ASGI).

- Phase 3 gate re-run with BM25 keyword leg (decision 31), hybrid, top 8, local db: #1 knife: BNS 118 rank 2, BNS 115 absent (user hypothesis lists both), top 8 = 101, 118, 351, MV 166, IT 66F, TN 4C, Arms 35, MV 134; #2 BNS 303 rank 1 (vector-only 1, keyword-only absent); #3 BNS 351 rank 1; #4 BNS 330, 331, 329 ranks 1-3; #5 MV 184, 122, 134 (rank 3), BNS 281, 106; #6 Arms s.3 rank 1 (earlier run); #7 TN 4 rank 1, BNS 75 rank 2, BNS 79 rank 4; #8 IT 66A rank 1 (struck down per user's note; see below), BNS 308, 351. #9 and #10 unchanged (abstention / date routing not built).
- BNS s.75 text (read from db): sexual harassment (unwelcome physical contact, demand for sexual favours, showing pornography...). MV s.134: duty of driver in case of accident and injury. BNS s.106: causing death by negligence (applies only if death occurred).
- User's hand-check note (from an outside assessment the user pasted, not verified by me): Supreme Court struck down IT s.66A in Shreya Singhal v. Union of India (2015); it must not be presented as an operative offence. IT s.66E concerns privacy violations involving private images.
- Tests: 30 passed (BM25 IDF test, query stems meet document stems, per-act caps, omitted excluded, provenance + citation, /retrieve over ASGI).

- Phase 4 date-rule sources (2026-10-14). From the stored official MHA text (db, after cleanup): BNS s.1(2): "It shall come into force on such date as the Central Government may, by notification in the Official Gazette, appoint, and different dates may be appointed for different provisions". BNS s.358(1)-(2): "The Indian Penal Code is hereby repealed. ... it shall not affect (a) the previous operation of the Code ... (c) any penalty, or punishment incurred in respect of any offences committed against the Code so repealed ... and any such proceeding ... may be instituted, continued or enforced ... as if that Code had not been repealed." From PIB (official press pages found by search; I did not open the notification itself): the three laws "came into force on July 1, 2024". From third-party outlets only (LiveLaw, Verdictum, Taxscan; NOT verified from the Gazette): the commencement notification is MHA S.O. 850(E) dated 23 Feb 2024 and excludes sub-section (2) of BNS s.106 (rash/negligent driving causing death, hit-and-run) from commencement.
- Data defect fixed while reading s.1 and s.358 back: Gazette front matter (Hindi legacy-font lines, "xxxGIDHxxx", PART II header) sat inside s.1 and the digital-signature block inside s.358. Parser now cuts the end-of-act rule line and a manifest `drop_spans` entry slices around the page-1 front matter. Test added. 31 tests pass; BNS re-ingested (423 chunks).
- Correction to my earlier statement that the BNS text layer has no section titles: marginal side-headings ARE in the text (e.g. "Short title, commencement and application." after s.1's text, "Repeal and savings." in s.358) but at misaligned positions (s.358's text also contains "Breach of contract to attend on and supply wants of helpless person.", a different section's marginal title). Decision 24 (no titles) stands; recovering them would be fragile.

- Phase 4 built: `src/facts.py` (fixed schema, pydantic extra=forbid, LLM JSON extraction, fail-safe), `src/dating.py` (deterministic regime, LIMITS), `src/clarify.py` (<=2 questions), `src/analyze.py` + `POST /analyze` (facts, date, questions, open_conditions, results with IPC equivalents for BNS hits when regime is ipc/ambiguous, limits, disclaimer). 54 tests pass: 12-case date table incl. 30 Jun vs 1 Jul 2024, clarify rules, schema rejects extra keys/bad enums and fails safe, /analyze attaches IPC equivalents with mapping page, post-1-Jul has none.
- Live LLM extraction (Groq openai/gpt-oss-20b, 10 gate incidents, 2 rounds = 20 calls, all succeeded on attempt 1 after the fix): first run had a real failure on incident 2: HTTP 400 json_validate_failed with empty output (reasoning model spent the 600-token budget thinking). Fixed with max_tokens 2000 + reasoning_effort low. Prompt tuned twice after seeing these 10 incidents (these are the gate set, not the Phase 6 eval set): "phones" listed under electronic_or_online made phone theft come out online=yes; harm=none now means no one described as hurt.
- Open weakness: for incident 1 ("stabs someone with a knife ... and causes an injury") the model returns harm=hurt although severity is not stated; so the harm clarifying question does NOT fire for that text. It does fire for incident 5 (vehicle, harm unknown). A demo query that does not say "causes an injury" will trigger it.
- Live routing results: incident 10 ("in 2022") -> regime ipc, date 2022-01-01 (year precision); all others default today -> bns. Incident 9 (planning permission) still returns unrelated sections (BNS 46, 290, MV 198A...) because nothing abstains yet.

- Severity rule (user-specified, decision 36), `src/severity.py`: live on the 10 gate incidents: #1 harm=unknown (LLM had said hurt) -> asks 1 harm question; #5 asks; #10 established by cue "serious" -> grievous_hurt, no question; #2-#4, #6-#9 no injury -> no question. Retrieval receives only the incident text; test proves identical sections for different facts. 67 tests pass.
- Abstention evidence (2026-10-14, 10 gate incidents + 6 out-of-scope queries, hybrid): neither cosine nor BM25 top-1 separates in-scope from out-of-scope. In-scope BM25 8.8-23.9, cosine 0.55-0.70; out-of-scope BM25 7.7-16.5, cosine 0.52-0.65. Gate incident 9 (planning permission, out of scope by user label) scores like in-scope ones (BM25 9.3, cosine 0.55). A score floor cannot be the abstention mechanism.

- Phase 5 live run (2026-10-14, real Groq gpt-oss-20b, local db, 10 gate incidents; `python scripts/phase5_live.py`): grouped answers returned for #1-#8 with citations from the db; validator caught 1 repeated id in #1 (noticed + logged); no invented ids seen live. #1: BNS 118 [harm=hurt], BNS 101 [harm=death]; #2: BNS 303; #3: BNS 351; #4: BNS 330, 329; #5: MV 184, MV 134, BNS 281, BNS 106 [death]; #6: Arms 19, 20, 3 (Arms s.25 punishment not retrieved); #7: TN 4, BNS 75, BNS 79; #8: IT 66A, BNS 351, IT 66E; #9 abstained (reason no_matching_provision, not topic_not_in_corpus); #10 abstained no_matching_provision.
- Failures to carry to the Phase 6 report: (a) #10 ("which law applies to an incident in 2022 where someone caused a serious injury with a knife") abstains: retrieval is polluted by meta words ("law applies", "incident", "2022") and BNS 117/118 are not in the top 8, so the model correctly sees no fitting candidate; the IPC-equivalent display never happens. (b) IT s.66A (reported struck down by the user's note, not verified by me) is returned as applicable in #8 with no warning. (c) BNS s.106 is offered for #5 [death]; the s.106(2) carve-out is unverified. (d) BNS 115 never retrieved for #1. (e) Condition names are inconsistent across runs ("any harm", "injury", "hurt or grievous hurt").

- Cards AA/AB/AC implemented (decisions 40-42), 84 tests pass. Live afterwards: #5 BNS 106 now returned with a not_in_force flag (scope: sub-section (2) only, third_party_only); IT s.66A flag unit-tested (struck_down, source_located: Indian Kanoon + SC digital reports URLs found by search, judgment not read by the tool author) but the model did not select 66A on the last live #8 run, so the live warning was not seen on screen; the answer is non-deterministic across runs (repeated ids dropped by the validator in several runs).
- Incident 10 live: query cleaning fixed the retrieval query ("someone caused a serious injury with a knife") but the model still abstained, because the prompt did not say BNS candidates are equivalents for pre-1-July-2024 incidents. After adding that note (prompt change, made after seeing this failure) it selects BNS 124 with IPC equivalents 326A/326B. Hand-check needed: BNS 124 is the permanent-damage/acid provision (also "any other means with the intention of causing..."); BNS 117/118, the more natural fits for a knife, are not retrieved for "serious" (the Act says "grievous"): vocabulary gap, a rewriting candidate for Phase 6.

## Not verified
- S.O. 850(E) and the s.106(2) carve-out from the official Gazette (only third-party reports seen).
- BNS s.115 never appears in the top 8 for the knife incident; reason not diagnosed.
- BM25 parameters (k1=1.5, b=0.75) and CANDIDATES=20 are untuned defaults.
- The Neon database (the `.env` URL) has had nothing applied or ingested; tests must NOT use it (`drop_all`).
- CI itself (not pushed).
- PyMuPDF 1.28.2 is in the lock (62 lines); `pip check` clean; not re-verified in a second fresh venv since adding it.

## What I must do by hand
- Copy `.env.example` to `.env`; set `DATABASE_URL` (new URL), `LLM_API_KEY` (existing Groq key).
- Commits: none made; you run `git commit` at the end.
- Start Docker Desktop, then `docker compose up -d db`.
- Provide any act PDFs the agent cannot download into `data/raw/` (Phase 1).

## Provenance of data/raw/ (as told by the user, 2026-10-14; file timestamps from the user's screenshot)
| file | source | retrieved |
|---|---|---|
| bns_2023.pdf | https://www.mha.gov.in/sites/default/files/2024-04/250883_english_01042024.pdf (Ministry of Home Affairs, not India Code; filename suggests 1 Apr 2024) | 2026-10-14 ~18:16 |
| it_act_2000.pdf | https://indiacode.gov.in/pdf-viewer/d41fe391-b9c0-40b1-afdc-ad034c7ac62f/770a7d02-48f2-4274-bab9-10d0f48ee264 | 2026-10-14 ~18:18 |
| mv_act_1988.pdf | https://indiacode.gov.in/pdf-viewer/2bbbcc40-38f1-4b15-ae94-646b85db4ee7/1d30ea4a-1331-4791-89bf-b820172bf790 | 2026-10-14 ~18:31 |
| arms_act_1959.pdf | https://indiacode.gov.in/pdf-viewer/78a46eb4-21bf-49ee-bd08-6b8e8655631c/6330f0c6-34aa-48fe-a110-43253c8c784c | 2026-10-14 ~18:32 |
| ipc_1860.pdf | https://www.hyderabadpolice.gov.in/PDF/acts/Indianpenalcode1860.pdf (a police department site, not India Code, not a gazette) | 2026-10-14 ~18:51 |
| tn_dangerous_activities_1982.pdf | https://prsindia.org/files/bills_acts/acts_states/tamil-nadu/1982/1982TN14.pdf (downloaded by the agent; third-party, OCR scan) | 2026-10-14 ~01:13 |
| bns_ipc_comparison_keralaprisons.pdf | https://www.keralaprisons.gov.in/userfiles/act-and-rules/comparison_summary_BNS_to_IPC.pdf (downloaded by the agent; credited to CAPT Bhopal, not MHA) | 2026-10-14 ~01:13 |

Note: India Code `pdf-viewer/<uuid>/<uuid>` URLs are viewer links; whether they open without a session or support `#page=` is NOT verified.

## Open after decision 15
- TN act not chosen; no clean PDF yet (the PRS 1982 copy is OCR with errors).
- With IPC as mapping-only, a pre-1 Jul 2024 incident would be routed to IPC section numbers from the mapping table but we would hold no verbatim IPC text to quote (ipc_1860.pdf is a non-official copy with commentary). How to present that is a Phase 2/4 decision, not made.

## Deferred
- Langfuse tracing (decision 6).
- Provider interface details (prompt, output shape, streaming): Phase 5.
- Whether `data/raw/` PDFs are committed or git-ignored: decide at Phase 1.

## HAND-OFF (written 2026-10-15 ~03:55, before the PC shut down)
- Eval run finished. RETRIEVAL numbers are valid (33 cases with gold): hit@3 vector 21/33, keyword 12/33, hybrid 22/33, hybrid+rewrite 24/33 (a few rewrites still failed and fall back to plain hybrid; see the count line in eval/REPORT.md).
- GENERATION numbers are INVALID: all 41 cases returned generation_error because Groq's free tier daily token cap (TPD 200,000 for openai/gpt-oss-20b) was exhausted by the repeated eval attempts (error text: Used 199729, Requested ~3k). The "8/8 negatives abstained" and "33/33 wrongly abstained" in eval/REPORT.md are API errors, not model behaviour. Do not quote them.
- A full generation pass needs about 41 x 7k = ~290k tokens: it does NOT fit in one day on the free tier. Options for the morning: (a) generation on a subset of ~20 cases (all 8 negatives + 12 others, ~140k tokens); (b) cut tokens per case (candidate text 1800 -> ~900 chars, k_final 8 -> 6); (c) a paid Groq tier. The cap is a rolling window; wait until it has recovered before running.
- scripts/run_eval.py now re-runs cases that ended in generation_error (previously they counted as done). partial_generation.jsonl still holds the 41 invalid rows; they will be recomputed.
- Still open: README.md, DEMO.md, email draft (need the live demo wordings verified; also uses LLM tokens, so budget them); Phase 5 teach-back answer from the user; label-review choice (decision 43).
- Deploy: Neon is migrated and ingested; Dockerfile, render.yaml, /health in place; the user pushes to GitHub and connects Render; no commits by the agent.

## UPDATE 2026-10-15 ~14:00
- Full 41-case pipeline run on a local model (qwen2.5:7b via Ollama, read-only on Neon): eval/REPORT.ollama.md. Generation metrics there are VALID for that model only (citation grounding 57/57, invented ids shown 0, negatives abstained 7/8, in-scope wrongly abstained 0/33, gold shown in 21/33). hit@3: vector 21, keyword 12, hybrid 22, hybrid+rewrite 26 (qwen) / 24 (gpt-oss).
- Bugs found and fixed from that run: reasoning_effort sent to a model without thinking (now LLM_REASONING_EFFORT), weapon question on vehicle/suicide cases, "section C1" leaking into explanations, matched passage being an illustration (added opening_quote), model-side timeout env.
- Demo scenarios verified end to end with the local model (knife, theft pre/post, cyber fraud, struck-down flag, out of scope). Docs written: README.md, DEMO.md, EMAIL_DRAFT.md.
- Still to do: (1) hosted-model (Groq) subset run when the daily cap allows: `python scripts/run_eval.py --subset`, then update README "Generation" table; (2) run the DB tests once Docker is up (91+ tests; the new opening_quote/weapon tests need it); (3) user: push to GitHub, connect Render, set DATABASE_URL + LLM_API_KEY; (4) user: Phase 5 teach-back and the label-review choice.

## UPDATE 2026-10-15 ~20:00 (cards AK, AL)
- Implemented plain-language summaries (decision 50) and answer-tagged groups with provisional candidates beside the question (decision 51); two guards added (decision 52). Page verified in jsdom against real local-model outputs (question, provisional candidates, group heading, summary box, page-image button).
- Unit tests pass (figure check incl. number words, answer tags, non-applicable filter). DB-backed tests for the two new end-to-end tests need Docker Desktop running (it was closed): run `python -m pytest -q` with DATABASE_URL=...statutedb_test.
- Pending the user's yes (asked, not done): attempt wording ("tried to stab") should ask 'was anyone hurt' not severity; hide inferred 'no' values in 'Facts understood'.
- Not re-run on the hosted Groq model (token cap). qwen2.5:7b output quality for summaries is mixed (one s.101 summary was off-topic): the hosted model may do better but is unmeasured.
