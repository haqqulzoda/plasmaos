# D1-02 pursuit model bench

Generated 2026-09-29 03:05 UTC by `backend/scripts/bench_pursuit_models.py` (count-only; no source text or model output is recorded).

## Method

- Runs the real `pursuit_analyzer.analyze_pack_items` (same prompt, response schema, single retry, quote/provenance verification) with no database run rows.
- Runs per model and input follow the plan: gemini-3.8-flash: long_rfp x3. Analyzer settings: output cap 32768 tokens, request timeout 90 s, chunk concurrency 3, chunk budget 240 s, run budget 480 s.
- Fallback models are disabled for the bench so each result belongs to one model; a failed run means the model exhausted its retry (the point where production would switch to a fallback).
- `gemini-3.1-pro-preview` is a quality reference only and is excluded from the selection rule.
- google-genai `0.3.0`; latency is wall time of the whole analyzer call including any retry; p90 uses linear interpolation over successful runs.
- Thinking tokens are inferred as `total - prompt - candidates` (the pinned SDK does not surface `thoughts_token_count`).
- Golden coverage (B4a inputs only) is an automated anchor-based proxy for the 19 obligations of `docs/audits/p0r/live-semantic-coverage.md`, evaluated on verified facts; it is not a human adjudication.

## Inputs

| Input | Description | Source ref | Characters | SHA-256 of text | Page markers | Chunks |
| --- | --- | --- | ---: | --- | ---: | ---: |
| long_rfp | Long consulting RFP (tenders.compiled_master_text) | giz:ea0e13e9-b360-452d-8491-8680c6a73d12 | 253,112 | `e525a6600af49172f3cd3d3381c1851c96606127d739569b4217e1593e58ff2b` | 119 | 3 |

## Results by model and input

| Model | Input | Successes | Latency p50 / p90 (s) | Chunks / provider calls per run (median) | Raw requirements (median) | Verified requirements min / median / max | Provenance-rejected (median) | Context origin verbatim / window / none (totals) | Verified positions (median) | Retries used | Failure classes | Golden 19 (min / runs at 19) |
| --- | --- | ---: | --- | --- | ---: | --- | ---: | --- | ---: | ---: | --- | --- |
| gemini-3.8-flash | long_rfp | 3/3 | 64.5 / 66.0 | 9 / 9 | 79 | 64 / 72 / 77 | 7 | 191/23/7 | 3 | 0 | - | - |

## Long-RFP recall against the reference model

Reference set: union of verified requirement quote spans from 3 successful `gemini-3.1-pro-preview` run(s), 84 distinct items (per run: 81, 81, 75). An item matches when spans overlap by >= 50% of the shorter span. The reference is itself imperfect: it defines what a stronger model found, not ground truth.

| Model | Runs | Recall per run | Recall median | Recall of union of runs | Model-only items per run (median) | Model-only items (union of runs) |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| gemini-3.8-flash | 3 | 57%, 64%, 57% | 57% | 67% | 19 | 39 |

A local, gitignored side-by-side list of reference items each model missed is written to `.private-storage/d1_bench/` for human spot-checking; it is not part of this report.


## Selection rule (reported only)

Rule: success ratio >= 8/9 (>= 0.889), p90 latency <= 150 s over successful runs, golden coverage 19/19 on every B4a run.

| Model | Successes (all inputs) | Success rule | Latency p50 / p90 (s) | p90 rule | Golden 19/19 runs | Golden rule | Meets all |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gemini-3.8-flash | 3/3 | pass | 64.5 / 66.0 | pass | 0/0 | n/a | n/a |

## D1 primary-model rule

Rule: golden 19/19 in >= 4/5 B4a runs AND median per-run long-RFP recall >= 75% against the reference set.

| Model | Golden 19/19 runs | Golden rule | Long-RFP recall (median per run) | Recall rule | Qualifies |
| --- | --- | --- | ---: | --- | --- |
| gemini-3.8-flash | 0/0 | fail | 57% | fail | no |

## Thinking, latency, and fallback notes

- **gemini-3.8-flash**: median run latency 64.5 s, p90 66.0 s; median thinking tokens 20,592 vs 27,531 output tokens per successful run; retry used in 0 successful run(s); retry exhausted (fallback would be needed) in 0 of 3 run(s).

Fallback ever needed among candidate models: no (0 run(s) exhausted the primary retry).

## Run notes

- gemini-3.8-flash on the long RFP only, LONG-route chunk size 30,000 characters (overlap 1,500): 9 chunks and 9 provider calls per run. Recall is against the R4 pro-preview reference (84 items).
- Median per-run recall 57% (union 67%): below the 75% decision bar.
