# D1-02 pursuit model bench

Generated 2026-09-29 00:26 UTC by `backend/scripts/bench_pursuit_models.py` (count-only; no source text or model output is recorded).

## Method

- Runs the real `pursuit_analyzer.analyze_pack_items` (same prompt, response schema, single retry, quote/provenance verification) with no database run rows.
- 3 runs per model per input, sequential. Analyzer settings: output cap 32768 tokens, request timeout 180 s, chunk concurrency 3.
- Fallback models are disabled for the bench so each result belongs to one model; a failed run means the model exhausted its retry (the point where production would switch to a fallback).
- `gemini-3.1-pro-preview` is a quality reference only and is excluded from the selection rule.
- google-genai `0.3.0`; latency is wall time of the whole analyzer call including any retry; p90 uses linear interpolation over successful runs.
- Thinking tokens are inferred as `total - prompt - candidates` (the pinned SDK does not surface `thoughts_token_count`).
- Golden coverage (B4a inputs only) is an automated anchor-based proxy for the 19 obligations of `docs/audits/p0r/live-semantic-coverage.md`, evaluated on verified facts; it is not a human adjudication.

## Inputs

| Input | Description | Source ref | Characters | SHA-256 of text | Page markers | Chunks |
| --- | --- | --- | ---: | --- | ---: | ---: |
| b4a | P0 benchmark B4a Communications Consultant RFP (repo fixture) | fixture:communications_consultant_rfp.txt | 5,208 | `n/a` | 8 | 1 |
| reoi_1 | World Bank Request for Expression of Interest (tenders.description) | world_bank:OP00464527 | 6,907 | `n/a` | 0 | 1 |
| reoi_2 | World Bank Request for Expression of Interest (tenders.description) | world_bank:OP00465103 | 6,784 | `n/a` | 0 | 1 |
| long_rfp | Long consulting RFP (tenders.compiled_master_text) | giz:ea0e13e9-b360-452d-8491-8680c6a73d12 | 253,112 | `n/a` | 119 | 3 |

## Results by model and input

| Model | Input | Successes | Latency p50 / p90 (s) | Raw requirements (median) | Verified requirements (median, min-max) | Provenance-rejected (median) | Verified positions (median) | Retries used | Failure classes | Golden 19 (min / runs at 19) |
| --- | --- | ---: | --- | ---: | --- | ---: | ---: | ---: | --- | --- |
| gemini-3.8-flash | b4a | 3/3 | 14.9 / 15.2 | 7 | 7 (6-7) | 0 | 1 | 0 | - | 12 / 2 |
| gemini-3.8-flash | reoi_1 | 3/3 | 13.1 / 14.2 | 8 | 7 (6-8) | 1 | 0 | 0 | - | - |
| gemini-3.8-flash | reoi_2 | 3/3 | 10.1 / 16.7 | 8 | 5 (4-7) | 2 | 0 | 0 | - | - |
| gemini-3.8-flash | long_rfp | 3/3 | 32.6 / 49.7 | 40 | 22 (17-25) | 20 | 0 | 0 | - | - |
| gemini-3.7-flash | b4a | 3/3 | 10.7 / 12.1 | 9 | 9 (8-9) | 0 | 1 | 0 | - | 19 / 3 |
| gemini-3.7-flash | reoi_1 | 3/3 | 9.8 / 9.9 | 6 | 5 (4-6) | 3 | 0 | 0 | - | - |
| gemini-3.7-flash | reoi_2 | 3/3 | 10.7 / 10.8 | 7 | 5 (5-6) | 1 | 1 | 0 | - | - |
| gemini-3.7-flash | long_rfp | 3/3 | 21.4 / 22.5 | 29 | 17 (9-20) | 18 | 0 | 0 | - | - |
| gemini-3.6-flash | b4a | 3/3 | 32.1 / 32.1 | 9 | 9 (7-9) | 0 | 1 | 0 | - | 15 / 1 |
| gemini-3.6-flash | reoi_1 | 3/3 | 21.1 / 119.5 | 6 | 6 (3-6) | 0 | 1 | 1 | - | - |
| gemini-3.6-flash | reoi_2 | 3/3 | 23.3 / 29.1 | 7 | 7 (4-8) | 0 | 1 | 0 | - | - |
| gemini-3.6-flash | long_rfp | 3/3 | 40.2 / 47.0 | 23 | 15 (10-18) | 10 | 1 | 0 | - | - |
| gemini-3.1-pro-preview (reference) | b4a | 3/3 | 35.9 / 49.3 | 8 | 8 (8-15) | 0 | 1 | 0 | - | 19 / 3 |
| gemini-3.1-pro-preview (reference) | reoi_1 | 3/3 | 36.9 / 43.2 | 8 | 8 (8-11) | 0 | 1 | 0 | - | - |
| gemini-3.1-pro-preview (reference) | reoi_2 | 3/3 | 37.8 / 38.1 | 7 | 6 (6-6) | 2 | 0 | 0 | - | - |
| gemini-3.1-pro-preview (reference) | long_rfp | 2/3 | 92.5 / 100.6 | 54.5 | 38.5 (27-50) | 19.5 | 1 | 0 | PROVIDER_HTTP_402 x1 | - |

## Long-RFP recall against the reference model

Not available: no successful reference-model run on the long RFP.


## Selection rule (reported only)

Rule: success ratio >= 8/9 (>= 0.889), p90 latency <= 150 s over successful runs, golden coverage 19/19 on every B4a run.

| Model | Successes (all inputs) | Success rule | Latency p50 / p90 (s) | p90 rule | Golden 19/19 runs | Golden rule | Meets all |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gemini-3.8-flash | 12/12 | pass | 14.7 / 31.9 | pass | 2/3 | fail | no |
| gemini-3.7-flash | 12/12 | pass | 10.7 / 20.9 | pass | 3/3 | pass | yes |
| gemini-3.6-flash | 12/12 | pass | 31.3 / 47.8 | pass | 1/3 | fail | no |
| gemini-3.1-pro-preview | 11/12 | pass | 37.8 / 82.4 | pass | 3/3 | pass | reference |

## Thinking, latency, and fallback notes

- **gemini-3.8-flash**: median run latency 14.7 s, p90 31.9 s; median thinking tokens 1,642 vs 3,057 output tokens per successful run; retry used in 0 successful run(s); retry exhausted (fallback would be needed) in 0 of 12 run(s).
- **gemini-3.7-flash**: median run latency 10.7 s, p90 20.9 s; median thinking tokens 894 vs 2,859 output tokens per successful run; retry used in 0 successful run(s); retry exhausted (fallback would be needed) in 0 of 12 run(s).
- **gemini-3.6-flash**: median run latency 31.3 s, p90 47.8 s; median thinking tokens 4,296 vs 2,894 output tokens per successful run; retry used in 1 successful run(s); retry exhausted (fallback would be needed) in 0 of 12 run(s).
- **gemini-3.1-pro-preview**: median run latency 37.8 s, p90 82.4 s; median thinking tokens 3,346 vs 3,151 output tokens per successful run; retry used in 0 successful run(s); retry exhausted (fallback would be needed) in 0 of 12 run(s); 1 run(s) failed on a provider/account error the analyzer does not retry (no fallback path) [PROVIDER_HTTP_402 x1].

Fallback ever needed among candidate models: no (0 run(s) exhausted the primary retry).

## Run notes

- Superseded for the D1 model decision by `model-bench-r2.md` (full B4a text, 90 s timeout, 5 runs). This first bench used the condensed 5,208-character repo fixture for B4a and the previous 180 s timeout.
- 47 of the 48 planned runs completed. The last run (`gemini-3.1-pro-preview` on `long_rfp`, run 3) returned `PROVIDER_HTTP_402` after 1.9 s, and a re-run returned it again. A follow-up single-call probe of `gemini-3.7-flash` also returned 402, so the API key had run out of credit/quota during that bench (a later probe succeeded, so it was restored). The run was not repeated. It affects only the quality reference, not the candidate models.
- `gemini-3.6-flash` on `reoi_1`, run 2: the first attempt failed with malformed JSON (`JSONDecodeError`) and the analyzer's single retry succeeded; the 144 s wall time is the failed attempt plus the retry. This is the only retry in the bench and no fallback was ever needed.
- The bench had 4 inputs (12 runs per model), so the "8/9" success threshold was applied as a ratio (>= 0.889, i.e. 11/12).
- `b4a` is the repo fixture (5,208 characters), a condensed form of the 16,594-character text used in the live P0R attempt; all 19 golden obligations are present in it.
- `long_rfp` is a local GIZ consulting/evaluation tender (119 page markers, 3 chunks) selected by an automated query; override with `--long-tender-id`.
