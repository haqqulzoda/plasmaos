# D1-02 pursuit model bench

Generated 2026-09-29 01:23 UTC by `backend/scripts/bench_pursuit_models.py` (count-only; no source text or model output is recorded).

## Method

- Runs the real `pursuit_analyzer.analyze_pack_items` (same prompt, response schema, single retry, quote/provenance verification) with no database run rows.
- Runs per model and input follow the plan: gemini-3.7-flash: b4a_full x5, reoi_1 x5, reoi_2 x5, long_rfp x3; gemini-3.8-flash: b4a_full x5, reoi_1 x5, reoi_2 x5, long_rfp x3; gemini-3.1-pro-preview: long_rfp x3. Analyzer settings: output cap 32768 tokens, request timeout 90 s, chunk concurrency 3, chunk budget 240 s, run budget 480 s.
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

| Model | Input | Successes | Latency p50 / p90 (s) | Raw requirements (median) | Verified requirements (median, min-max) | Provenance-rejected (median) | Verified positions (median) | Retries used | Failure classes | Golden 19 (min / runs at 19) |
| --- | --- | ---: | --- | ---: | --- | ---: | ---: | ---: | --- | --- |
| gemini-3.7-flash | b4a_full | 5/5 | 14.4 / 18.9 | 8 | 2 (0-6) | 6 | 1 | 0 | - | 9 / 0 |
| gemini-3.7-flash | reoi_1 | 5/5 | 12.1 / 14.9 | 6 | 5 (4-7) | 1 | 1 | 0 | - | - |
| gemini-3.7-flash | reoi_2 | 5/5 | 8.6 / 14.0 | 6 | 5 (5-6) | 1 | 1 | 0 | - | - |
| gemini-3.7-flash | long_rfp | 3/3 | 17.1 / 23.0 | 29 | 16 (11-17) | 15 | 0 | 0 | - | - |
| gemini-3.8-flash | b4a_full | 5/5 | 18.4 / 22.2 | 13 | 2 (0-18) | 9 | 1 | 0 | - | 9 / 1 |
| gemini-3.8-flash | reoi_1 | 5/5 | 10.7 / 14.6 | 8 | 5 (5-5) | 4 | 0 | 0 | - | - |
| gemini-3.8-flash | reoi_2 | 5/5 | 13.5 / 15.6 | 7 | 6 (4-8) | 2 | 1 | 0 | - | - |
| gemini-3.8-flash | long_rfp | 3/3 | 29.7 / 30.7 | 36 | 23 (21-24) | 16 | 0 | 0 | - | - |
| gemini-3.1-pro-preview (reference) | long_rfp | 3/3 | 88.7 / 89.7 | 58 | 46 (27-46) | 16 | 2 | 0 | - | - |

## Long-RFP recall against the reference model

Reference set: union of verified requirement quote spans from 3 successful `gemini-3.1-pro-preview` run(s), 46 distinct items (per run: 46, 27, 46). An item matches when spans overlap by >= 50% of the shorter span. The reference is itself imperfect: it defines what a stronger model found, not ground truth.

| Model | Runs | Recall per run | Recall median | Recall of union of runs | Model-only items per run (median) | Model-only items (union of runs) |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| gemini-3.7-flash | 3 | 28%, 20%, 26% | 26% | 35% | 4 | 6 |
| gemini-3.8-flash | 3 | 30%, 33%, 35% | 33% | 41% | 7 | 12 |

A local, gitignored side-by-side list of reference items each model missed is written to `.private-storage/d1_bench/` for human spot-checking; it is not part of this report.


## Selection rule (reported only)

Rule: success ratio >= 8/9 (>= 0.889), p90 latency <= 150 s over successful runs, golden coverage 19/19 on every B4a run.

| Model | Successes (all inputs) | Success rule | Latency p50 / p90 (s) | p90 rule | Golden 19/19 runs | Golden rule | Meets all |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gemini-3.7-flash | 18/18 | pass | 13.7 / 18.1 | pass | 0/5 | fail | no |
| gemini-3.8-flash | 18/18 | pass | 15.7 / 29.1 | pass | 1/5 | fail | no |
| gemini-3.1-pro-preview | 3/3 | pass | 88.7 / 89.7 | pass | 0/0 | n/a | reference |

## Thinking, latency, and fallback notes

- **gemini-3.7-flash**: median run latency 13.7 s, p90 18.1 s; median thinking tokens 942 vs 2,958 output tokens per successful run; retry used in 0 successful run(s); retry exhausted (fallback would be needed) in 0 of 18 run(s).
- **gemini-3.8-flash**: median run latency 15.7 s, p90 29.1 s; median thinking tokens 1,196 vs 3,548 output tokens per successful run; retry used in 0 successful run(s); retry exhausted (fallback would be needed) in 0 of 18 run(s).
- **gemini-3.1-pro-preview**: median run latency 88.7 s, p90 89.7 s; median thinking tokens 15,301 vs 18,646 output tokens per successful run; retry used in 0 successful run(s); retry exhausted (fallback would be needed) in 0 of 3 run(s).

Fallback ever needed among candidate models: no (0 run(s) exhausted the primary retry).

## Run notes

- 39 of 39 planned runs completed; no call returned HTTP 401/402/403 (the bench stops immediately if one does).
- `b4a_full` is the full extracted text of the locally uploaded B4a private document (`private_document_processing_results.extracted_text`, 16,594 characters, SHA-256 `8b8c9711…`, source PDF SHA-256 `88d34d5b…`, 8 known pages), read-only. It replaces the condensed 5,208-character repo fixture used by the first bench (`model-bench.md`), on which the same models scored much higher.
- **Why B4a-full scores low.** Raw output is reasonable (median 8 raw requirements for gemini-3.7-flash, 13 for gemini-3.8-flash) but most facts are rejected at provenance verification (median 6 and 9). A local diagnostic (counts only, not part of the bench) classified the rejections: in 60 of 61 rejected requirement facts across 7 calls (4 gemini-3.7-flash, 3 gemini-3.8-flash) the `original_quote` was found verbatim and the fact was rejected because its `source_context` was not found verbatim in the source; ignoring punctuation and spacing recovered only 1 of the 60, so the model condenses or rewrites the context instead of copying it. The quote/provenance rules were not changed. The rejection rate varies from run to run at temperature 0 (for example gemini-3.8-flash verified 0, 2, 18, 2 and 10 requirements on five runs), which is why the golden coverage ranges from 9/19 to 19/19.
- The same effect is visible on the long RFP: raw 29 / 36 / 58 requirements against 16 / 23 / 46 verified for gemini-3.7-flash / gemini-3.8-flash / gemini-3.1-pro-preview (medians), so the recall gap below combines missed facts and rejected facts.
- Recall uses requirement quote spans only (positions are excluded) and the union of the three gemini-3.1-pro-preview runs, whose per-run verified counts (46, 27, 46) are themselves unstable.
- Latency includes chunk concurrency 3 on the 3-chunk long RFP; the reference model's thinking dominates its 89 s.
