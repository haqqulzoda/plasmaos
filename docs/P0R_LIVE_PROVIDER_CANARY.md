# P0R — Live Provider Canary & Demo-Latency Verification

## Status

P0R passes its bounded live-provider acceptance gate with demo classification `LIVE_DEMO_RISKY`. The exact supplied eight-page Communications Consultant RFP completed the real customer W3→W4 API/worker/provider/validation/persistence/read path once in three controlled attempts. That successful run produced materially correct semantics, exact provenance, a truthful `READY_FOR_REVIEW` state, 12 real gaps, and no AI pricing.

Two provider calls ended in precisely classified `SCHEMA_OUTPUT_FAILURE` results after long execution. The first exposed a rollback-safety defect; it was documented before a narrow correction, and the post-fix third attempt persisted a truthful retryable failure without corrupting the successful result.

## Baseline and environment

- Git commit: `122e50b05760e3740845a744057cb6f2b4a11816` on the accepted dirty W0–P0 worktree.
- Alembic head: `20261002_0001_p0_extraction_trust_gate`; the disposable database was bootstrapped through the supported bootstrap command, verified at head, and `alembic check` reported no drift.
- Environment: isolated non-production local Docker with disposable PostgreSQL, Redis, ClamAV, private storage, API, private-document Celery worker, and analysis Celery worker.
- Provider authority: `google-gemini` / `gemini-3.1-pro-preview`.
- Prompt/schema/pipeline: `pursuit_analysis_p0_v2` / `pursuit_analysis_output_p0_v2` / `pursuit_analysis_pipeline_p0_v2`.
- Analysis worker: queue `pursuit_analysis`, concurrency 1 prefork, soft/hard task limits 600/660 seconds, application lease 300 seconds with 60-second heartbeat, max application attempts 3.
- Credentials were present but never printed. Count-only canary instrumentation logged timing and response sizes, never private source/model content or secrets.

No production system was accessed or deployed, and no provider/model was changed.

## Real customer-path result

The unmodified `B4a Communications Consultant RFP.pdf` was 176,299 bytes with SHA-256 `88d34d5bce1685088d18e104de0c8a5325924cd23d9c0a1cb1f48b4587cd4a3b`. Upload and processing completed `CLEAN`/`READY` with 8 known pages and 16,594 characters. Customer APIs detected Communications Consultant, Town of University Park, UP-2012-01, and the historical 2012-02-17 deadline in `America/New_York`, all with `SOURCE_DETECTED` provenance.

Each attempt used a new immutable run and sealed pack. The accepted run `01dfa335-b85c-4585-826e-438d40dad9b2` persisted 15 requirements, 1 position, and 12 gaps with zero schema, provenance, normalization, or duplicate rejections. It retained all 19 required semantic areas and mandatory/preferred/desired distinctions, exact supported source evidence, and the W1 pricing boundary.

Detailed evidence:

- [Live attempts](audits/p0r/live-attempts.md)
- [Latency breakdown](audits/p0r/latency-breakdown.md)
- [Live semantic coverage](audits/p0r/live-semantic-coverage.md)
- [Demo-readiness decision](audits/p0r/demo-readiness-decision.md)

## Runtime defect and narrow fix

Attempt 1 returned malformed provider JSON. The failure handler rolled back its transaction and then read expired ORM pack-item fields to construct diagnostics, triggering SQLAlchemy `MissingGreenlet`. This left that disposable reproduction row falsely `RUNNING` instead of committing its failure state.

`process_analysis_run()` now snapshots only primitive input character/page diagnostics before entering the provider path and uses those values after rollback. `JSONDecodeError` and schema `ValidationError` also increment the safe schema-rejection diagnostic. A regression forces the exact rollback path and verifies retryable `QUEUED`, quality `FAILED`, cleared lease, `EXTRACTION` stage, schema rejection 1, and retained input size/page counts.

No provider, model, prompt, schema, provenance rule, semantic coverage, pricing behavior, W5–W8 behavior, or UI was changed.

## Validation

Focused validation passed:

- P0 real-RFP plus W4 analysis: 12 passed.
- World Bank/project preservation: 45 passed across the focused project suites.
- Communications: 10 passed.
- P0 frontend trust tests: 5 passed.
- The focused rollback regression: 1 passed.

The definitive permanent `scripts/run_release_gate.sh all` invocation exited 0 against only the disposable loopback database/Redis and local browser/API fixtures. It completed:

- full backend: 846 passed, 1 skipped, 100 subtests passed;
- security: 118 passed;
- analysis: 50 passed, 12 subtests passed;
- connectors: 198 passed, 1 skipped, 6 subtests passed;
- migration heads/current/check/schema preflight: passed;
- scale checks: passed at 1k, 10k, and 100k rows, with at most 5 queries and 25 returned files;
- TypeScript, ESLint, RTL audit, and production build: passed;
- frontend: 297 of 297 passed;
- real Chromium: 203 passed, 0 failed, 0 external requests;
- configuration: 24 passed;
- Python dependency check: no broken requirements;
- npm audit: 0 vulnerabilities.

The retained Chromium result is [results.json](audits/p0r/browser-all/results.json), SHA-256 `e08e1017ca729e749d9139f50bfe9b0e510305a14abe9a0aed0e5d058ca9f1b8`.

Two discarded wrapper invocations diagnosed validation-host conditions before this definitive run: one lacked the required loopback Redis listener, and one was OOM-killed during `next build` while the already-finished live-canary services still consumed the constrained Docker VM. No product assertion failed in either case. The final run used the unchanged wrapper and application, retained loopback Redis, stopped the no-longer-needed canary workers/API/ClamAV, passed every phase, and exited 0.

## Demo and P1 decision

Use `LIVE_DEMO_RISKY`: the correct live run was reviewable in about 53.168 seconds, but the two failures took about 5.7 minutes at the provider before malformed output surfaced. A precomputed successful result should be ready for demos. These observations do not establish an SLA or p50.

P1 may start only after this P0R evidence is accepted, carrying provider schema-output reliability and latency variance as explicit operational risks. P1 must not reopen the P0 trust semantics or W1 pricing boundary merely to improve demo speed. P0R stops here; it does not begin P1.
