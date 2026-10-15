# Eval report

**Read this first.** The 41 cases in `eval/cases.jsonl` were drafted by an AI agent from the stored statute text and are all `label_status = unreviewed`. Gold sections were chosen by reading the text (SQL search), not by the retriever, and each is checked to exist in the database; they are labels by a **non-lawyer, not reviewed by counsel**. Numbers below are an engineering signal about retrieval and validation behaviour, not a measure of legal accuracy. One run; the LLM steps are not deterministic.

**Generation model for this report: `qwen2.5:7b` via `localhost:11434`.** Generation numbers describe this model only; retrieval numbers do not depend on it, except the `hybrid+rewrite` column.

Configuration: hybrid = per-act top-3 (vector + BM25, RRF) then pooled global RRF, top 8; query cleaning on (decision 41); no similarity floor; rewriting off (decision 30). BM25 k1=1.5, b=0.75 untuned.

## 1. Retrieval (33 cases with gold; counts, not percentages)

| mode | hit@3 | recall@5 (sum of per-case recall) |
|---|---|---|
| vector | 21/33 | 21.0/33 |
| keyword | 12/33 | 14.5/33 |
| hybrid | 22/33 | 21.5/33 |
| hybrid+rewrite | 26/33 | 26.5/33 |

### By act (gold sections in top 3 / gold sections)

| act | vector | keyword | hybrid | hybrid+rewrite |
|---|---|---|---|---|
| BNS 2023 | 8/16 | 5/16 | 10/16 | 14/16 |
| Arms Act 1959 | 3/5 | 1/5 | 2/5 | 3/5 |
| MV Act 1988 | 3/6 | 1/6 | 3/6 | 3/6 |
| IT Act 2000 | 3/6 | 3/6 | 4/6 | 3/6 |
| TN Harassment of Women 1998 | 4/5 | 2/5 | 3/5 | 4/5 |

### By case type (cases with a gold section in top 3 / cases)

| type | vector | keyword | hybrid | hybrid+rewrite |
|---|---|---|---|---|
| multi_act | 3/5 | 2/5 | 2/5 | 4/5 |
| single | 13/21 | 10/21 | 15/21 | 17/21 |
| temporal | 4/4 | 0/4 | 3/4 | 4/4 |
| underspecified | 1/3 | 0/3 | 2/3 | 1/3 |

## 2. Generation, validation and abstention (hybrid, shipped configuration)

| measure | count |
|---|---|
| citation grounding: shown quotes that resolve in the source PDF | 57/57 |
| shown sections that are not in the retrieved set (invented ids reaching the user) | 0 |
| negative cases correctly abstained | 7/8 |
| non-negative cases wrongly abstained | 0/33 |
| cases with at least one gold section shown | 21/33 |
| shown sections that are gold or acceptable | 26/56 |
| clarify: expected question asked | 4/4 |
| clarify: no question on cases that expect none | 27/29 |
| date regime correct (temporal/underspecified with an expected regime) | 5/5 |
| IPC equivalent shown includes an expected IPC ref (temporal, ipc regime) | 1/3 |
| cases that errored | 0 |

`citation grounding` is true by construction when parsing is right; its value is catching parser or file drift.


## 3. Failures, one line each

| case | type | what happened | diagnosis |
|---|---|---|---|
| s02 | single | retrieval miss (no gold in hybrid top 3) | bns_2023:s318: absent from the top 8 of every mode: neither leg connects the lay wording to the statute wording |
| s02 | single | gold not shown | gold not retrieved; shown: bns_2023:s314 |
| s06 | single | retrieval miss (no gold in hybrid top 3) | arms_act_1959:s3: hybrid rank 6 (vector 1, keyword None): present but below the top 3 |
| s08 | single | gold not shown | gold arms_act_1959:s3 retrieved but not selected by the model; shown: arms_act_1959:s13 |
| s09 | single | retrieval miss (no gold in hybrid top 3) | arms_act_1959:s30: absent from the top 8 of every mode: neither leg connects the lay wording to the statute wording |
| s09 | single | gold not shown | gold not retrieved; shown: arms_act_1959:s17 |
| s12 | single | retrieval miss (no gold in hybrid top 3) | mv_act_1988:s181: absent from the top 8 of every mode: neither leg connects the lay wording to the statute wording |
| s12 | single | gold not shown | gold not retrieved; shown: mv_act_1988:s4, mv_act_1988:s19 |
| s13 | single | retrieval miss (no gold in hybrid top 3) | mv_act_1988:s196: found by vector alone (rank 2) but pushed out of the hybrid top 8 by the per-act/global fusion |
| s13 | single | gold not shown | gold not retrieved; shown: mv_act_1988:s158, mv_act_1988:s134 |
| s18 | single | retrieval miss (no gold in hybrid top 3) | tn_harassment_women_1998:s4: found by vector alone (rank 3) but pushed out of the hybrid top 8 by the per-act/global fusion |
| s18 | single | gold not shown | gold not retrieved; shown: bns_2023:s296 |
| s19 | single | unexpected clarifying question | asked ['weapon'] |
| m01 | multi_act | retrieval miss (no gold in hybrid top 3) | bns_2023:s318: found by vector alone (rank 2) but pushed out of the hybrid top 8 by the per-act/global fusion; it_act_2000:s66D: absent from the top 8 of every mode: neither leg connects the lay wording to the statute wording |
| m01 | multi_act | gold not shown | gold not retrieved; shown: bns_2023:s335, bns_2023:s180 |
| m03 | multi_act | retrieval miss (no gold in hybrid top 3) | mv_act_1988:s185: found by vector alone (rank 6) but pushed out of the hybrid top 8 by the per-act/global fusion; bns_2023:s106: absent from the top 8 of every mode: neither leg connects the lay wording to the statute wording |
| m03 | multi_act | gold not shown | gold not retrieved; shown: mv_act_1988:s161, bns_2023:s101 |
| m03 | multi_act | unexpected clarifying question | asked ['weapon'] |
| m04 | multi_act | retrieval miss (no gold in hybrid top 3) | bns_2023:s118: absent from the top 8 of every mode: neither leg connects the lay wording to the statute wording; arms_act_1959:s25: found by vector alone (rank 2) but pushed out of the hybrid top 8 by the per-act/global fusion |
| m04 | multi_act | gold not shown | gold not retrieved; shown: arms_act_1959:s2, arms_act_1959:s19 |
| n02 | negative | answered an out-of-scope incident | shown: bns_2023:s329; the model judged candidates applicable |
| t01 | temporal | gold not shown | gold bns_2023:s303 retrieved but not selected by the model; shown: bns_2023:s78 |
| t02 | temporal | retrieval miss (no gold in hybrid top 3) | bns_2023:s115: found by vector alone (rank 3) but pushed out of the hybrid top 8 by the per-act/global fusion |
| t02 | temporal | gold not shown | gold not retrieved; shown: bns_2023:s118, bns_2023:s130 |
| u01 | underspecified | retrieval miss (no gold in hybrid top 3) | bns_2023:s118: absent from the top 8 of every mode: neither leg connects the lay wording to the statute wording |
| u01 | underspecified | gold not shown | gold not retrieved; shown: bns_2023:s101 |

## 4. Limits of this eval

- 41 cases, one run, labels unreviewed and by a non-lawyer (see top). Wording of the incidents was written by the same agent that built the retriever, so lay-language coverage is narrower than real users'.
- Gold relevance was fixed by reading section text; `acceptable` lists are judgement calls.
- `hybrid+rewrite` is retrieval-only (decision 44); the rewrite prompt was written after seeing failures on these same cases, so its gain is optimistic. Cosine floors and BM25 parameters are untuned.
- Other acts are the current consolidated text; temporal cases test routing and IPC-equivalent display, not historical text.

