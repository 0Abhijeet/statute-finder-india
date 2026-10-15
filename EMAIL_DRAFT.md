Subject: Statute finder for Indian acts: demo, README, eval

Hi Ravi,

Demo: <render-url> · Code: <github-url> · README has the eval and failures.

**Acts:** BNS 2023, Arms Act 1959, Motor Vehicles Act 1988, IT Act 2000 (central), and the TN Prohibition of Harassment of Women Act 1998. They cover your examples (theft, assault) plus traffic, firearms, cyber and a state act.

**Versioning:** incident date routes to IPC (before 1 Jul 2024) or BNS from the repeal-and-savings clause; IPC numbers come from a comparison table, and the IPC text itself is not in the corpus.

**Eval:** 41 cases, labels unreviewed and by a non-lawyer. Hit@3 on 33 cases: hybrid 22, vector 21, keyword 12. Quotes verified against the PDF: 57/57. Failures: lay wording vs statute wording (BNS 118, 318) and a penalty section that only cross-references another (MV 181).

**Cut:** income tax, TN building rules, IPC text, OCR.

**Tables/images:** the IPC↔BNS table is parsed (527 rows); image-only pages are not.

**Updated data:** hash-checked, idempotent re-ingest; no automatic amendment tracking.

Abhijeeth
