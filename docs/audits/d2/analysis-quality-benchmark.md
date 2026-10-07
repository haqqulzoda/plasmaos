# D2 analysis quality — stability benchmark (TASK 0 / 0b)

Count-only. Raw per-run numbers: [`analysis-quality-benchmark.json`](analysis-quality-benchmark.json).

Inputs: the B4a Communications Consultant RFP (private upload, golden set of 19 obligations) and the
Mongolia REOI OP00468882 official notice, analysed through the local shared stack's API in the
synthetic organization, 5 runs each, submitted one at a time (each run completes before the next starts).

| Round | Pipeline | Prompt | Code |
|---|---|---|---|
| 1 baseline | `pursuit_analysis_pipeline_d2_v1` | `pursuit_analysis_d2_v1` | shared stack `1e813cd` |
| 2 two passes | `pursuit_analysis_pipeline_d2_v2` | `pursuit_analysis_d2_v1` | `dc6f63d` |
| 3 restatement instruction | `pursuit_analysis_pipeline_d2_v2` | `pursuit_analysis_d2_v2` | this commit |

## Results

| | Round 1 | Round 2 | Round 3 |
|---|---|---|---|
| B4a golden 19/19 (requirements + notes + positions) | 2/5 | 5/5 | **5/5** |
| B4a misses | "Printed and electronic submission" ×3 | — | — |
| B4a requirements min/median/max | 12/13/13 | 13/14/15 | 13/14/15 |
| B4a notes min/median/max | 2/4/4 | 2/5/7 | 4/5/6 |
| REOI requirements (all) min/median/max | 5/6/10 | 6/9/11 | 5/6/7 |
| REOI current-stage requirements | 5,5,5,8,5 | 9,5,8,8,9 | **5,4,4,5,5** (spread 1) |
| REOI 5 core items (requirements or notes) | — | — | **5/5** |
| REOI duplicated criteria | restated bullet list in 1/5 | restated bullet list in 4/5 | **none** |
| B4a provider time per run p50 / p90 | — | — | **57.0 s** / 69.5 s |
| REOI provider time per run p50 / p90 | — | — | **32.0 s** / 33.0 s |
| Queue wait (start − creation) | — | — | 0.0–1.3 s |

Provider time per run is the slower of the two concurrent passes (each pass's wall time is recorded
in the run's `extraction_diagnostics.passes`). Rounds 1–2 recorded only client-side end-to-end latency
(B4a p50 49 s → 79 s, REOI 41 s → 45 s), which also includes worker pick-up.

The REOI notice states its shortlisting criteria twice: a numbered list (general experience, specific
experience, licences, organizational and technical capability) and a bulleted restatement. Round 2's
second pass recovered the bulleted list in most runs, which raised the count and its spread; round 3's
instruction makes both passes keep only the most complete statement. In 2/5 round-3 runs the joint-venture
rule was classified as a submission instruction by both passes and is therefore a note, not a requirement.

One round-3 REOI attempt received a Gemini `500 INTERNAL` in pass 1; 500 is not retried by the chunk
retry policy (only 429/503/504), so the worker task failed and the run was redelivered and completed
(total 101.7 s, provider 33.0 s). Pre-existing behaviour.

## Gate (TASK 0b, as redefined)

| | Criterion | Measured | Result |
|---|---|---|---|
| a | B4a golden 19/19 in 5/5 | 5/5 | PASS |
| b | REOI 5 core items in requirements or notes, 5/5 | 5/5 (JV rule a note in 2/5) | PASS |
| c | No duplicated criterion | none | PASS |
| d | REOI current-stage requirement spread ≤ 2 | 1 (4–5) | PASS |
| e | B4a p50 provider time ≤ 60 s; REOI ≤ 45 s | 57.0 s; 32.0 s | PASS (monitored in production) |
