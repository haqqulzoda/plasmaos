# World Bank Project Enrichment Auto-Drain Hotfix

## 1. Production Symptom

Some World Bank tenders displayed Project Context while most retained
`Project details are being prepared.` Workers successfully processed the jobs
they received, but production made no progress after each explicitly queued
batch finished.

## 2. Root Cause

The previous flow was:

`WB refresh -> canonical Project/TenderProject linkage -> claim at most 50 ->`
`publish per-Project jobs -> worker persists status`

The World Bank refresh called the bounded dispatcher once. The manual operator
command could also call it once. Nothing reconciled the remaining eligible rows,
so Celery correctly became idle after consuming the published batch. A worker
does not scan PostgreSQL for work; it consumes broker messages.

Local did not show the production symptom because local reconciliation had
already attempted all 416 World Bank Projects (369 fresh successes, 2 partial,
45 terminal failures, and 0 eligible at validation time). Small refreshes also
fit inside one batch and hid the missing continuation mechanism.

## 3. Previous Dispatch Model

- Tender refresh created or reused `(source_system, external_project_id)` and
  linked the Tender through `TenderProject`.
- Refresh invoked `enqueue_world_bank_project_enrichment_batch()` once.
- The claim used PostgreSQL `FOR UPDATE SKIP LOCKED`, marked rows `queued`, and
  committed before publishing existing per-Project Celery jobs.
- The worker fetched and normalized official World Bank data, merged Project
  metadata, reconciled leadership history, and persisted its result.
- No scheduler invoked the claim again. The operator command was the only
  non-refresh recovery path.

## 4. New Automatic Dispatch Model

The immediate refresh dispatch and operator command remain intact. In addition,
the existing Celery Beat process now publishes
`app.workers.project_enrichment_tasks.dispatch_world_bank_project_enrichment_backlog`
every 60 seconds. Each invocation measures the backlog, claims one bounded
batch, publishes the existing per-Project tasks, logs aggregate results, and
returns without making World Bank HTTP requests.

The periodic reconciliation is durable with respect to worker loss, broker
restart, missed invocations, and deployment during a backlog: a later Beat run
continues from persisted database state.

## 5. Eligibility Contract

The claim and observability query share one SQL predicate:

- `never_attempted`: eligible immediately.
- explicit `stale`, or `successful`/`partial` older than seven days: eligible.
- `source_unavailable`, or `failed/dispatch_failure`: eligible after the
  persisted 15-minute retry backoff.
- `queued`/`running` whose 30-minute lease expired: eligible.
- fresh success, fresh partial, transient failure in retry wait, and an active
  queued/running lease: not eligible.
- non-retryable `failed` rows: terminal and not automatically requeued.
- only canonical World Bank Projects linked through `TenderProject` are claimed.

No second in-memory eligibility definition was introduced.

## 6. Fairness

Ordering is deterministic: never attempted, stale success/partial, due
retryable failure, then expired lease; ties use oldest enrichment time,
creation time, and Project UUID. A repeatedly failing Project therefore cannot
starve untouched Projects.

## 7. Batch / Rate Policy

Automatic batches default to 25 and are clamped to at most 30. The operator
maximum remains 50. The existing per-Project task remains `rate_limit="30/m"`.

Configuration:

- `WORLD_BANK_AUTODRAIN_INTERVAL_SECONDS` (default and minimum `60`)
- `WORLD_BANK_AUTODRAIN_BATCH_SIZE` (default `25`, clamped to `1..30`)
- `WORLD_BANK_ENRICHMENT_RETRY_BACKOFF_SECONDS` (default `900`, minimum `60`)

Production Compose currently runs one worker consuming the `celery` queue, so
the task rate limit gates official-source calls to approximately 30/minute.
Celery's built-in rate limit is per worker instance, not a distributed global
limit. If the `celery` worker is scaled horizontally, a global source limiter
must be added or worker-specific rates reduced before scaling.

## 8. Lease/Deduplication

Claims continue to use PostgreSQL `FOR UPDATE SKIP LOCKED`. Claimed rows are
committed as `queued` before publishing, so concurrent dispatchers cannot claim
the same active row. A dispatcher crash after commit but before publish leaves a
recoverable lease, not a permanently stranded row. A queued/running lease is
reclaimed after 30 minutes.

The disposable PostgreSQL concurrency proof ran two dispatchers together:
each claimed 25, producing 50 unique active jobs and zero duplicates.

## 9. Retry Policy

Worker-level behavior is unchanged: classified timeout/network/429/5xx errors
use at most three Celery retries with exponential countdown. Each attempt
persists `enrichment_last_attempted_at`. After worker retries are exhausted, the
periodic dispatcher waits 15 minutes from the persisted last attempt before it
may claim the row again. Permanent 4xx, identity mismatch, malformed/empty
authoritative responses, and unexpected non-retryable errors remain terminal.

## 10. Beat/Scheduler Deployment

Production Compose already defines both required processes and the shared Redis
broker:

```text
celery -A app.core.celery_app worker --loglevel=info -Q celery,ai_fast_queue
celery -A app.core.celery_app beat --loglevel=info
```

The task module is included in the Celery app, the dispatcher is routed to the
`celery` queue, and Beat has a 60-second schedule with a bounded expiration.
Both services depend on PostgreSQL and Redis. The deployment must recreate both
`celery_worker` and `celery_beat` from the hotfix image.

## 11. Backlog Observability

The dispatcher logs per-run aggregate fields:

`eligible_found`, `claimed`, `dispatched`, `skipped_active_lease`,
`dispatch_failures`, and `duration_ms`.

The following command is read-only and emits JSON counts without Project data:

```bash
docker compose exec backend python scripts/report_world_bank_project_enrichment_backlog.py
```

It reports total World Bank Projects, fresh success, partial, never attempted,
eligible now, queued, running, retry wait, terminal failure, stale, and expired
lease, plus linked active leases used by the per-run skip diagnostic. `stale`
and lease fields are actionable dimensions and can overlap raw status counts.
Capture it immediately after deployment and again later; a falling `eligible_now`
confirms drain progress.

## 12. Drain Test

`python scripts/test_wb_project_enrichment_autodrain.py` bootstrapped a disposable
PostgreSQL database at the existing repository head. With 125 linked eligible
Projects and a batch of 25, scheduled-style invocations produced exactly:

`125 -> 100 -> 75 -> 50 -> 25 -> 0`

No tender refresh and no operator command participated. A separate controlled
source fixture proved two dispatcher batches flowed through the real per-Project
worker implementation and persisted three successes plus one visible partial.
The same matrix proved expired-lease recovery and exclusion of active leases,
retry-wait failures, terminal failures, and fresh partials.

## 13. Production Rollout

No production mutation or deployment was performed during implementation.

1. Build and deploy the hotfix image for `backend`, `celery_worker`, and
   `celery_beat`; do not run a manual backlog loop.
2. Verify the Beat log contains the release identity and sends
   `dispatch_world_bank_project_enrichment_backlog` every minute.
3. Verify worker logs contain `world_bank_project_enrichment_dispatch` aggregate
   lines and successful per-Project task results.
4. Run the read-only backlog report at deployment, after 10 minutes, and after
   the expected drain window. `eligible_now` should trend to zero while fresh
   success/partial/terminal totals explain settled rows.
5. Inspect representative successful, partial, genuinely pending, and terminal
   Tender Details. Roll back the application image if scheduler errors or
   unexpected source-call volume appears; no database rollback is needed.

## 14. Project Context State Semantics

No Project Context or leadership semantics changed. Successful authoritative
fields display normally. Partial records retain available fields and map to the
existing incomplete message. Never-attempted/queued/running work remains pending.
`source_unavailable` and terminal `failed` already map to `unavailable`, so they
do not imply endless preparation. Canonical identity remains visible wherever a
`TenderProject` exists. Project status/date semantics, `teamleadname != TTL`, no
email inference, source provenance, and role history are unchanged.

## 15. Regression Results

- Hotfix fast contracts: 16 passed.
- Sprint 1 focused API/auth/UI contracts: 67 passed; foundation and enrichment
  disposable PostgreSQL matrices passed with zero leaked databases.
- Sprint 2 focused contracts: 27 passed; Sprint 2.1 and frozen Sprint 2.2
  disposable PostgreSQL matrices passed and Alembic drift remained clean.
- World Bank connector: 18 passed in each of UTC, Asia/Tashkent, and
  America/New_York.
- Connector regression gate: 195 passed, 4 subtests passed, 1 existing approved
  storage-fixture skip, zero failures.
- Project Context frontend: 18 passed; TypeScript typecheck passed.
- FastAPI import, Celery worker task imports/registration, Beat registration,
  operator command import/help, Compose validation, and read-only diagnostics
  passed.
- No migration was added and production was not mutated.
