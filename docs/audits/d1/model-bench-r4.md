# D1-02 pursuit model bench

Generated 2026-09-29 03:02 UTC by `backend/scripts/bench_pursuit_models.py` (count-only; no source text or model output is recorded).

## Method

- Runs the real `pursuit_analyzer.analyze_pack_items` (same prompt, response schema, single retry, quote/provenance verification) with no database run rows.
- Runs per model and input follow the plan: gemini-3.1-pro-preview: b4a_full x3, reoi_1 x3, reoi_2 x3, long_rfp x3. Analyzer settings: output cap 32768 tokens, request timeout 90 s, chunk concurrency 3, chunk budget 240 s, run budget 480 s.
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

| Model | Input | Successes | Latency p50 / p90 (s) | Chunks / provider calls per run (median) | Raw requirements (median) | Verified requirements min / median / max | Provenance-rejected (median) | Context origin verbatim / window / none (totals) | Verified positions (median) | Retries used | Failure classes | Golden 19 (min / runs at 19) |
| --- | --- | ---: | --- | --- | ---: | --- | ---: | --- | ---: | ---: | --- | --- |
| gemini-3.1-pro-preview (reference) | b4a_full | 3/3 | 85.7 / 87.1 | 1 / 1 | 20 | 20 / 20 / 20 | 0 | 36/27/0 | 1 | 0 | - | 19 / 3 |
| gemini-3.1-pro-preview (reference) | reoi_1 | 3/3 | 40.0 / 43.3 | 1 / 1 | 10 | 8 / 10 / 11 | 0 | 11/9/12 | 1 | 0 | - | - |
| gemini-3.1-pro-preview (reference) | reoi_2 | 3/3 | 37.9 / 46.7 | 1 / 1 | 9 | 9 / 9 / 10 | 0 | 16/3/12 | 1 | 0 | - | - |
| gemini-3.1-pro-preview (reference) | long_rfp | 3/3 | 100.3 / 101.7 | 3 / 3 | 89 | 75 / 82 / 82 | 8 | 188/24/30 | 1 | 0 | - | - |

## Long-RFP recall against the reference model

Reference set: union of verified requirement quote spans from 3 successful `gemini-3.1-pro-preview` run(s), 84 distinct items (per run: 81, 81, 75). An item matches when spans overlap by >= 50% of the shorter span. The reference is itself imperfect: it defines what a stronger model found, not ground truth.

| Model | Runs | Recall per run | Recall median | Recall of union of runs | Model-only items per run (median) | Model-only items (union of runs) |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| gemini-3.8-flash (r3b) | 3 | 38%, 39%, 46% | 39% | 49% | 5 | 8 |
| gemini-3.7-flash (r3b) | 3 | 38%, 42%, 38% | 38% | 44% | 2 | 4 |

A local, gitignored side-by-side list of reference items each model missed is written to `.private-storage/d1_bench/` for human spot-checking; it is not part of this report.


## Selection rule (reported only)

Rule: success ratio >= 8/9 (>= 0.889), p90 latency <= 150 s over successful runs, golden coverage 19/19 on every B4a run.

| Model | Successes (all inputs) | Success rule | Latency p50 / p90 (s) | p90 rule | Golden 19/19 runs | Golden rule | Meets all |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gemini-3.1-pro-preview | 12/12 | pass | 66.8 / 100.3 | pass | 3/3 | pass | reference |

## Thinking, latency, and fallback notes

- **gemini-3.1-pro-preview**: median run latency 66.8 s, p90 100.3 s; median thinking tokens 7,202 vs 3,534 output tokens per successful run; retry used in 0 successful run(s); retry exhausted (fallback would be needed) in 0 of 12 run(s).

Fallback ever needed among candidate models: no (0 run(s) exhausted the primary retry).

## Run notes

- Prompt `pursuit_analysis_d1_v3`, pipeline `pursuit_analysis_pipeline_d1_v3`, exact model contexts (a normalized model context is persisted as the exact source substring). No call returned HTTP 401/402/403.
- The three gemini-3.1-pro-preview long-RFP runs form the fresh reference set (84 distinct requirement items). The recall rows labelled `(r3b)` rescore the stored R3 arm-B flash runs (100,000-character chunks) against this reference; they were not re-run.
- `b4a_full` and both REOIs take the SHORT route and the long RFP (253,112 characters) the LONG route; the bench forces the named model on both routes with no fallbacks.
- Pro-preview is itself the reference, so its own long-RFP recall is not measured; its run-to-run spread was 75 / 82 / 82 verified requirements.
