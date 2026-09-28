# P1 analysis-state audit

## State behavior

| Latest attempt | Customer behavior |
| --- | --- |
| No analysis | Document selection is open and analysis requires an explicit click. |
| Queued/running | A persistent nonblocking status explains that work may continue elsewhere; no ETA is invented. |
| Completed / ready for review | Counts, gaps, requirements, and positions are reviewable. |
| Completed / needs attention | No false no-gaps conclusion appears; review and rerun actions remain explicit. |
| Failed | A generic safe failure and retry action appear; raw provider/schema/model failure text is not exposed. |
| Failed/running after earlier success | The latest attempt state is visible while the last successful result remains reviewable below. |

The display separates processing state from extraction quality. It reports needs-attention, missing-evidence, needs-interpretation, supported, later-stage, and required-position counts and deliberately uses no compliance/readiness percentage.
