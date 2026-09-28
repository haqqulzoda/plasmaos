# P0R demo-readiness decision

## Classification: `LIVE_DEMO_RISKY`

One of three bounded live attempts produced a materially correct, provenance-supported, reviewable result in approximately 53.168 seconds from click/request start. That proves the real W3→W4 workflow can complete successfully with the configured authority.

However, two of three attempts returned malformed provider JSON only after provider durations of 344.203338 and 345.994519 seconds. The successful provider duration was 51.242189 seconds. This variance and 1/3 observed success rate are too risky for a synchronous customer meeting, even though the post-fix failure path is truthful and retryable.

For demonstrations:

- Keep a precomputed successful result available and treat it as the primary fallback.
- A live run may be shown only as an explicitly non-guaranteed canary, never as a timed promise.
- Do not infer an SLA or p50 from these three attempts; only one succeeded.
- Do not change provider/model, weaken semantic/provenance checks, or trim required coverage merely to improve demo timing.

This is not `PRECOMPUTED_DEMO_ONLY` because a clean live end-to-end success exists. It is not `LIVE_DEMO_SAFE` because bounded reliability and tail latency are poor.

## Remaining operational risk

The provider sometimes emits very large malformed structured responses and does so after long execution. The application now records that condition as `SCHEMA_OUTPUT_FAILURE`, preserves safe input diagnostics, clears its lease, exposes `FAILED` quality without a false success/no-gaps message, and retains the prior successful result. Provider schema-output reliability and latency variance remain external operational risks for P1 entry.
