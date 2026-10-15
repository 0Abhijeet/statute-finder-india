# Demo script (about 90 seconds)

Open the page at `/`. Use the example buttons; every wording below was run end to end and the outcome noted. Keep the model's non-determinism in mind: if a run differs, say what it shows.

## 0:00 Knife attack, with a clarifying question (25 s)
Button **Knife attack**: *"A person stabs someone with a knife during an argument and causes an injury."*
- Say: "No severity is stated, so it asks how serious the injury was, and still shows the provisions grouped by condition."
- Expected: a question ("How serious was the injury...?") and BNS s.118 under a hurt/grievous condition; on some runs BNS s.101 appears under death.
- Click **Show the cited page with the quote highlighted** under BNS s.118: page 39 of `bns_2023.pdf` with the quoted lines highlighted. This is the "open the source" moment: the highlight is computed from the stored page and offsets, not from the model.

## 0:25 Theft with a date toggle (25 s)
Button **Theft, before July 2024** (date 2022-03-10), then **Theft, after July 2024** (date 2025-03-10).
- Say: "Same words, different date. Before 1 July 2024 the IPC applied: it shows the BNS section as the equivalent, with IPC 378 and 379 from the comparison table and the table's page. After, the BNS applies directly."
- Point out the label: "the IPC text is not in the corpus".

## 0:50 Two acts at once (15 s)
Button **Cyber fraud (two acts)**: *"A man pretended to be someone else on social media and cheated a woman of money by getting her to transfer it online."*
- Expected: BNS 318 and 319 (cheating, by personation) and IT s.66D.

## 1:05 A struck-down provision is flagged (10 s)
Button **Struck-down provision**: *"A person sends threatening messages to a woman on social media and posts her private photographs online."*
- Expected: IT s.66A appears with a red "STRUCK DOWN" warning, source link and the verification level; BNS 308 and IT 66E alongside. (The model may not select 66A on every run.)

## 1:15 Out of scope (10 s)
Button **Out of scope**: *"My landlord is refusing to return my security deposit..."*
- Expected: no sections, with the message that the incident appears to be outside the five acts.

## If something goes wrong
- "The answer could not be generated" = the model API rate limit (free tier). Wait a minute and retry; the retrieval-only endpoint `/retrieve` and `/analyze` still work.
- Cold start: the first request after idle loads the embedding model and can take about a minute.

## Things not to claim
- Not legal advice; labels in the eval are unreviewed and by a non-lawyer.
- IPC text is not available; BNS s.106(2) status comes from third-party reports.
