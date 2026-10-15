# LEARNING

Interview-ready phrasing. Updated as concepts come up.

## Pinning dependencies
An unpinned install is a different build each day. The old project's CI broke because a fresh install resolved SQLAlchemy 2.1.1, which no longer pulls in `greenlet` automatically; async SQLAlchemy then failed at test collection. Top-level pins fix the versions you name, but their transitive dependencies still float; only a full lock is fully reproducible.

## Approximate-index search can return fewer rows than asked
Approximate vector indexes trade recall for speed. ivfflat searches only `probes` of its `lists` buckets (default 1), so a small table with many lists returned fewer than k rows (5 of 38 questions, 4 of them zero). HNSW has the analogous knob `hnsw.ef_search`, and a `WHERE` filter (e.g. per-act) is applied after the index scan, so filtered queries can also come back short. Tested, not assumed: that is why the ivfflat hook was dropped and will only return as an HNSW setting if a test shows truncation.

## Provenance stored as exact slices, not as cleaned text
A section is stored as the list of (page, start, end) slices of the raw PDF text it came from; the stored text is the concatenation of those slices. A citation is therefore re-checkable: re-open the file, cut the same slices, compare. "Citation resolves" is true by construction when parsing is right, so its value is catching a changed file or a changed parser. Footnotes, page numbers and chapter headings are excluded by choosing where to slice, never by editing the text.

## Chunking a statute
A section is the natural unit, but long sections exceed what the embedding model reads (about 512 tokens, assumed from the model card). Long sections are cut at sub-section markers "(1)", "(2)" and merged up to 2,000 characters; provisos and illustrations stay with the sub-section they follow. A hit on a sub-chunk is returned as its parent section. The header (act, chapter, section, title) is embedded with the text but never shown as the quote.

## Why exact search here
At about 1,000 rows a sequential scan is a few milliseconds and always returns the true nearest neighbours. An approximate index (HNSW, ivfflat) adds a recall trade-off and, with a WHERE act = ... filter, can return fewer than k rows. Considered and rejected; revisit only if the corpus grows.

## Validating a parser against the document's own index
Compare parsed section ids with the file's arrangement of sections. A mismatch always means a bug (and found two in my own first scratch regex: a prefix match that dropped "Repeal of ..." and a wrong last page). A match does not prove the content is complete, so each source also gets a stated quality note.

## Reciprocal rank fusion, and why per-act fusion needs a second pass
RRF scores each item as the sum of 1/(60 + rank) across the ranked lists it appears in, so two lists with incomparable scores (cosine vs a keyword rank score) combine without normalisation. It is rank-based, so it is only comparable among items ranked in the same lists: fusing within each act gives every act's top hit about the same score. Fix used here: pick each act's top sections (the guarantee), pool them, rank the pool per leg, fuse again. Interview question: "why not add the scores?" Answer: different scales; RRF needs only ranks.

## Postgres full-text search is not BM25
ts_rank / ts_rank_cd score a document by term frequency and proximity inside that document. There is no inverse document frequency, so a rare discriminating word ("stab") counts the same as a common one ("person"). Measured here: for "a person stabs someone with a knife during an argument", the relevant section (hurt by a stabbing instrument) ranked outside the top 15 of its act. BM25 weights terms by rarity across the corpus and fixes exactly this.

## Letting the model select, never write, the law
The model gets candidates under opaque ids (C1..Cn) and returns ids plus a short explanation. The server maps ids back to database rows and builds the quote, citation, page and URL from them. Anything outside the candidate set is dropped and logged; if everything is dropped there is one retry, then an explicit "validation_failed" abstention (otherwise an all-dropped answer would look like a legitimate "out of scope"). Each quote is also re-read from the PDF at the stored offsets. Interview question: "what stops hallucinated sections?" Answer: the model never produces the text or the number the user sees; it only chooses among ids that the retrieval step produced, and a validator enforces that.

## Why abstention is a judgement, not a threshold
Measured on 16 queries: top-1 BM25 and cosine scores for in-scope and out-of-scope queries overlap completely (in-scope BM25 8.8-23.9, out-of-scope 7.7-16.5). So the system asks the model to judge fit from the candidate text, constrains the reasons to a fixed vocabulary, and measures the false-answer rate on negative eval cases instead of pretending a threshold exists.
