# P0R live-attempt evidence

## Boundaries and identity

- Environment: non-production, disposable local Docker only. No production database, customer data, deployment, or production service was accessed.
- Source: the unmodified `B4a Communications Consultant RFP.pdf`, 176,299 bytes, SHA-256 `88d34d5bce1685088d18e104de0c8a5325924cd23d9c0a1cb1f48b4587cd4a3b`.
- Customer path: upload API → malware scan/parser → `READY` → candidate API → fresh sealed pack/run → explicit analysis API → Celery `pursuit_analysis` queue → live Gemini → schema/provenance validation → persistence → customer read API.
- Authority: `google-gemini` / `gemini-3.1-pro-preview`; prompt `pursuit_analysis_p0_v2`; schema `pursuit_analysis_output_p0_v2`; pipeline `pursuit_analysis_pipeline_p0_v2`.
- Attempt limit: three. Exactly three fresh run IDs and three fresh pack IDs were used; no unbounded retry loop ran.
- Instrumentation recorded timing and response byte/character counts only. It did not log source text, model response text, credentials, or secrets.

Wall-clock ISO timestamps establish event order. Latencies below use monotonic timers because the container wall clock received corrections during the long calls; subtracting the ISO timestamps would therefore be misleading.

## Attempt summary

| Attempt | Run / sealed pack | Provider result | Safe raw metric | Verified → persisted | Customer-visible result |
| --- | --- | --- | --- | --- | --- |
| 1 | `37d41081-66d1-4a33-947b-cbb2b9b2b9d8` / `f2fa9b71-4d41-42e5-b4ef-d52a25999aac` | `SCHEMA_OUTPUT_FAILURE`; 344.203338 s; retry 0 | Malformed at JSON char 13,860; exact total unavailable because the pre-instrument SDK failed before returning a response object; ≥13,860 chars | Raw/verified/persisted counts unavailable/0 due parse failure; pre-fix diagnostics transaction did not commit | Pre-fix defect left the disposable row `RUNNING` with a stale lease; it did not claim completion or no gaps |
| 2 | `01dfa335-b85c-4585-826e-438d40dad9b2` / `f317c4cd-e1db-4170-82a8-0a24989fd937` | Success; 51.242189 s; retry 0 | 18,535 chars / 18,567 bytes; raw requirements 15, positions 1 | Requirements 15 → 15; positions 1 → 1; gaps 12; schema/provenance/normalization rejects 0 | `COMPLETED`, `FULL`, `READY_FOR_REVIEW` |
| 3 | `37a39f6c-5aea-42d2-9430-e7478056be5c` / `3dbc87ab-625a-4b4b-96c0-f609f6efe39e` | `SCHEMA_OUTPUT_FAILURE`; 345.994519 s; retry 0 | 366,584 chars / 366,616 bytes; malformed at JSON char 13,860, so typed raw counts were unavailable | Safe failure diagnostics: raw 0/0, verified 0/0, persisted 0/0/0; schema rejects 1, provenance rejects 0 | Retryable `QUEUED`, quality `FAILED`, stage `EXTRACTION`; no completed/no-gaps claim |

## Attempt 1 — defect documented before correction

The provider request began at `2026-09-28T13:24:06.903773Z` and was observed ending at `2026-09-28T13:30:28.023469Z`; the monotonic provider timer recorded 344.203338 seconds. Gemini returned malformed JSON and the SDK raised `JSONDecodeError` for an unterminated string at line 253, column 30, character 13,860. The lease was acquired and renewed at roughly 60-second cadence.

The real failure uncovered a separate runtime defect: after `db.rollback()`, `process_analysis_run()` dereferenced expired `AnalysisPackItem` ORM objects while assembling failure diagnostics. SQLAlchemy raised `MissingGreenlet`, preventing the failure transition from committing. This file was created with that finding before source was changed. The original disposable evidence row remains unaltered as `RUNNING`, preserving the reproduction rather than retroactively rewriting it.

The narrow correction snapshots only primitive input character/page diagnostics before entering the provider path and uses those values after rollback. It also records a schema rejection for `JSONDecodeError` or schema `ValidationError`. Provider, model, prompt, schema, provenance checks, semantic coverage, UI, and W5–W8 behavior were not changed.

## Attempt 2 — accepted live result

- API request: `2026-09-28T13:44:59.553778Z` to `2026-09-28T13:44:59.682573Z`, 0.128755 seconds, HTTP 202.
- Queue wait after the accepted API response: approximately 0.004 seconds; run start `2026-09-28T13:44:59.686672Z`.
- Provider request observed from `2026-09-28T13:44:59.769169Z` to `2026-09-28T13:45:57.343317Z`; monotonic duration 51.242189 seconds.
- Celery task duration: 51.544101 seconds. The residual validation/persistence portion was approximately 0.301912 seconds.
- Customer polling observed the reviewable result 53.038844 seconds after the analysis request was accepted (approximately 53.168 seconds from click/request start).
- Diagnostics: 16,594 input characters, 8 known pages, raw/verified/persisted requirements 15/15/15, raw/verified/persisted positions 1/1/1, persisted gaps 12, schema rejects 0, provenance rejects 0, normalization drops 0, duplicates 0.
- The sealed pack had one immutable item, all eight pages, the exact source SHA-256, and no alternate content. Retained evidence appeared on pages 2, 4, 6, and 7; quotes and source contexts were supported and every locator was in bounds.

## Attempt 3 — post-fix failure truth

- API request: `2026-09-28T13:45:59.235796Z` to `2026-09-28T13:45:59.277492Z`, 0.041662 seconds, HTTP 202; queue pickup was effectively immediate.
- Provider request observed from `2026-09-28T13:45:59.309369Z` to `2026-09-28T13:52:21.462305Z`; monotonic duration 345.994519 seconds.
- The SDK response-parse hook measured 366,584 characters / 366,616 bytes without logging content. JSON parsing failed at line 253, column 30, character 13,860.
- Customer polling observed the truthful retryable failure state after 348.793352 seconds. The approximately 2.799-second residual includes failure persistence and polling delay, so it is an upper bound on persistence itself.
- Heartbeat/lease samples show acquisition followed by renewal at roughly 60–66-second intervals, then both lease fields cleared when failure was persisted.
- Failure persisted as stage `EXTRACTION`, quality `FAILED`, schema-rejected count 1, with all input size/page diagnostics intact. The prior accepted Attempt 2 remained intact with its 15 requirements, 1 position, and 12 gaps. No duplicate run or result corruption occurred.

## Passive read check

Two successive latest-analysis GETs and a context GET returned HTTP 200. The customer projection was stable and complete database snapshots of all W4 analysis tables were byte-for-byte equivalent before and after those reads. Reads invoked no AI, parsing, source fetch, rerun, or mutation.
