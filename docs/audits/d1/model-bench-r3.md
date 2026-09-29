# D1-02 pursuit model bench

Generated 2026-09-29 02:17 UTC by `backend/scripts/bench_pursuit_models.py` (count-only; no source text or model output is recorded).

## Method

- Runs the real `pursuit_analyzer.analyze_pack_items` (same prompt, response schema, single retry, quote/provenance verification) with no database run rows.
- Runs per model and input follow the plan: gemini-3.8-flash: b4a_full x5, reoi_1 x5, reoi_2 x5, long_rfp x3; gemini-3.7-flash: b4a_full x5, reoi_1 x5, reoi_2 x5, long_rfp x3. Analyzer settings: output cap 32768 tokens, request timeout 90 s, chunk concurrency 3, chunk budget 240 s, run budget 480 s.
- Fallback models are disabled for the bench so each result belongs to one model; a failed run means the model exhausted its retry (the point where production would switch to a fallback).
- `gemini-3.1-pro-preview` is a quality reference only and is excluded from the selection rule.
- google-genai `0.3.0`; latency is wall time of the whole analyzer call including any retry; p90 uses linear interpolation over successful runs.
- Thinking tokens are inferred as `total - prompt - candidates` (the pinned SDK does not surface `thoughts_token_count`).
- Golden coverage (B4a inputs only) is an automated anchor-based proxy for the 19 obligations of `docs/audits/p0r/live-semantic-coverage.md`, evaluated on verified facts; it is not a human adjudication.

## Inputs

| Input | Description | Source ref | Characters | SHA-256 of text | Page markers | Chunks |
| --- | --- | --- | ---: | --- | ---: | ---: |
| b4a_full | B4a Communications Consultant RFP, full extracted text of the local upload | private_document_source_sha256:88d34d5b | 16,594 | `8b8c971137f64dd972f469a2bd5b91ffc14f5e8bdc27ad23f5de67cf0c034c7b` | 8 | 1 |
| reoi_1 | World Bank Request for Expression of Interest (tenders.description) | world_bank:OP00464527 | 6,907 | `c94db0cddffb434cdcb3e587f36be3e03cd97ea9db63901391f1dd94ef231ed9` | 0 | 1 |
| reoi_2 | World Bank Request for Expression of Interest (tenders.description) | world_bank:OP00465103 | 6,784 | `f86e06fb02c309a44b9d24e95fd3e80e00a2c04cb741b3034efdddbadffef489` | 0 | 1 |
| long_rfp | Long consulting RFP (tenders.compiled_master_text) | giz:ea0e13e9-b360-452d-8491-8680c6a73d12 | 253,112 | `e525a6600af49172f3cd3d3381c1851c96606127d739569b4217e1593e58ff2b` | 119 | 3 |

## Results by model and input

| Model | Input | Successes | Latency p50 / p90 (s) | Raw requirements (median) | Verified requirements min / median / max | Provenance-rejected (median) | Context origin verbatim / window / none (totals) | Verified positions (median) | Retries used | Failure classes | Golden 19 (min / runs at 19) |
| --- | --- | ---: | --- | ---: | --- | ---: | --- | ---: | ---: | --- | --- |
| gemini-3.8-flash | b4a_full | 5/5 | 17.6 / 29.1 | 11 | 9 / 11 / 11 | 0 | 25/30/1 | 1 | 0 | - | 14 / 0 |
| gemini-3.8-flash | reoi_1 | 5/5 | 12.4 / 14.3 | 8 | 7 / 8 / 8 | 0 | 18/14/11 | 1 | 0 | - | - |
| gemini-3.8-flash | reoi_2 | 5/5 | 15.2 / 15.9 | 7 | 7 / 7 / 8 | 0 | 17/7/17 | 1 | 0 | - | - |
| gemini-3.8-flash | long_rfp | 3/3 | 27.8 / 34.0 | 41 | 29 / 35 / 36 | 7 | 63/32/9 | 1 | 0 | - | - |
| gemini-3.7-flash | b4a_full | 5/5 | 14.8 / 68.8 | 9 | 9 / 9 / 10 | 0 | 12/36/3 | 1 | 1 | - | 14 / 0 |
| gemini-3.7-flash | reoi_1 | 5/5 | 11.1 / 15.1 | 7 | 4 / 7 / 11 | 0 | 24/8/8 | 1 | 0 | - | - |
| gemini-3.7-flash | reoi_2 | 5/5 | 9.5 / 10.3 | 7 | 6 / 7 / 8 | 0 | 15/11/13 | 1 | 0 | - | - |
| gemini-3.7-flash | long_rfp | 3/3 | 23.3 / 27.6 | 33 | 28 / 30 / 33 | 4 | 50/39/5 | 1 | 0 | - | - |

## Long-RFP recall against the reference model

Reference set: union of verified requirement quote spans from 3 successful `gemini-3.1-pro-preview` run(s), 46 distinct items (per run: 46, 27, 46). An item matches when spans overlap by >= 50% of the shorter span. The reference is itself imperfect: it defines what a stronger model found, not ground truth.

| Model | Runs | Recall per run | Recall median | Recall of union of runs | Model-only items per run (median) | Model-only items (union of runs) |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| gemini-3.8-flash | 3 | 41%, 41%, 37% | 41% | 48% | 15 | 20 |
| gemini-3.7-flash | 3 | 39%, 37%, 37% | 37% | 39% | 13 | 21 |

A local, gitignored side-by-side list of reference items each model missed is written to `.private-storage/d1_bench/` for human spot-checking; it is not part of this report.


## Selection rule (reported only)

Rule: success ratio >= 8/9 (>= 0.889), p90 latency <= 150 s over successful runs, golden coverage 19/19 on every B4a run.

| Model | Successes (all inputs) | Success rule | Latency p50 / p90 (s) | p90 rule | Golden 19/19 runs | Golden rule | Meets all |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gemini-3.8-flash | 18/18 | pass | 15.2 / 29.5 | pass | 0/5 | fail | no |
| gemini-3.7-flash | 18/18 | pass | 12.2 / 24.9 | pass | 0/5 | fail | no |

## D1 primary-model rule

Rule: golden 19/19 in >= 4/5 B4a runs AND median per-run long-RFP recall >= 75% against the reference set.

| Model | Golden 19/19 runs | Golden rule | Long-RFP recall (median per run) | Recall rule | Qualifies |
| --- | --- | --- | ---: | --- | --- |
| gemini-3.8-flash | 0/5 | fail | 41% | fail | no |
| gemini-3.7-flash | 0/5 | fail | 37% | fail | no |

## Thinking, latency, and fallback notes

- **gemini-3.8-flash**: median run latency 15.2 s, p90 29.5 s; median thinking tokens 1,162 vs 3,370 output tokens per successful run; retry used in 0 successful run(s); retry exhausted (fallback would be needed) in 0 of 18 run(s).
- **gemini-3.7-flash**: median run latency 12.2 s, p90 24.9 s; median thinking tokens 866 vs 3,114 output tokens per successful run; retry used in 1 successful run(s); retry exhausted (fallback would be needed) in 0 of 18 run(s).

Fallback ever needed among candidate models: no (0 run(s) exhausted the primary retry).

## Run notes

- Arm A: prompt `pursuit_analysis_p0_v2` (unchanged). Neither flash model met the D1 rule, which triggered arm B (`model-bench-r3b.md`).
- gemini-3.7-flash B4a p90 of 68.8 s comes from run 5 (103 s): the first attempt hit the 90 s read timeout (`ReadTimeout`) and the single retry succeeded. This is the only retry in arm A.
- Pipeline `pursuit_analysis_pipeline_d1_v3`: a fact whose verbatim quote verifies is never rejected for its `source_context`; a non-verbatim context is replaced by an exact sealed-text window (`SOURCE_WINDOW`). `provenance_rejected_count` now counts quote failures only, so it is not comparable with r2 (which also counted context failures).
- Same inputs as r2 (B4a full 16,594 characters SHA-256 `8b8c9711…`, Mongolia REOIs OP00464527 and OP00465103, GIZ long RFP `ea0e13e9…`). No call returned HTTP 401/402/403.
- Long-RFP recall reuses the r2 `gemini-3.1-pro-preview` reference set (46 distinct items; pro was not re-run). Matching is by verified quote span, which the context change does not affect.
- Golden coverage now scores only each fact's quote, normalized text and position details, not `source_context`: a window can contain neighbouring list items the model did not extract as facts, and counting them would inflate coverage. r2 and earlier golden scores also read the model-supplied context.
