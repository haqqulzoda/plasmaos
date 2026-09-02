# SR-2.2 — Durable Source Refresh Orchestration

## 1. Previous Lifecycle

SR-1 persisted customer-triggered `SourceRefreshJob` rows, but the four
institutional operator sync URLs executed their connectors inline. A running
job had neither an owner nor a renewable lease, and source status used five
serial latest-job queries. The active-source partial unique index prevented two
active rows but could not prevent duplicate broker deliveries from executing
the same row concurrently.

## 2. Canonical Orchestration Authority

`SourceRefreshJob` remains the only source-wide lifecycle aggregate. Customer
refresh, the UzEx `/refresh` alias, and the World Bank, GIZ, ADB, and EBRD
operator sync URLs all call `_request_source_refresh`. Only the Celery worker
calls the source connector executors. Targeted GIZ document hydration remains a
separate `TenderSyncJob` capability.

## 3. SourceRefreshJob Extension

The existing model retains its identity, requester FK, statuses, failure and
health diagnostics, timestamps, active-source unique index, and history. The
additive fields are `trigger_kind`, bounded `options_json`, `unchanged_count`,
`documents_discovered_count`, `documents_queued_count`, `lease_owner`,
`lease_expires_at`, and `heartbeat_at`.

## 4. Trigger Semantics

`customer`, `operator`, and reserved `scheduled` values are explicit at job
creation. Trigger kind is not inferred later from requester role. SR-2.2 adds no
schedule. Customer and operator requests retain the authenticated requester's
user ID; a future scheduled request may use `NULL`.

## 5. Lease Model

Each delivery creates a fresh opaque UUID execution token. A worker atomically
locks the job row and may claim a queued job, renew its own valid lease, or take
over an expired running lease. A different valid owner returns `busy` without
running a connector. Terminal jobs return `terminal` without re-execution.

The default lease is 180 seconds. This is intentionally independent of job age:
a long refresh remains healthy as long as it renews its lease.

## 6. Heartbeat Model

The default heartbeat cadence is 30 seconds and is capped at one half of the
configured lease duration. Heartbeats use a separate short-lived database
session, update only `heartbeat_at` and `lease_expires_at`, and are not emitted
per Tender. A simulated 30-minute run therefore performs approximately 60
bounded heartbeat writes.

## 7. Atomic Claim

Claim uses `SELECT ... FOR UPDATE`. The decision and mutation occur under that
row lock. The active-source unique index remains the creation-time authority;
the lease is execution-time authority.

## 8. Redelivery

The durable job UUID is carried in every broker delivery, but every publication
uses a fresh Celery delivery ID. A redelivery of a terminal job short-circuits.
A redelivery while another valid owner runs returns busy. A delivery after
genuine expiry may take ownership and rerun safely.

## 9. Worker Loss Recovery

Connectors have no checkpoints, so an expired takeover reruns from the
beginning. Claim resets all prior-attempt counters and diagnostics before the
new run. Final counters describe one successful terminal attempt and are never
summed across crashed attempts.

## 10. Terminal Ownership

Terminal writes are an atomic guarded update requiring `running` status, the
current lease owner, and a non-expired lease. A stale owner cannot heartbeat or
overwrite a newer owner's state. Lease loss produces a safe `superseded`
worker result.

## 11. Counter Authority

The worker persists connector-returned, committed `fetched`, `created`,
`updated`, `unchanged`, `skipped`, `rejected`, and `failed` values. SR-2.1
remains authoritative for created/updated/unchanged; unchanged is never derived
arithmetically. UzEx now reports fetched rows and canonical duplicate skips.
Document discovery maps from the connector's truthful attachment discovery
count. `documents_queued_count` remains zero because source refresh does not yet
own document queueing.

## 12. Operator Route Convergence

The existing `/sources/world-bank/sync`, `/sources/giz/sync`,
`/sources/adb/sync`, and `/sources/ebrd/sync` URLs now return
`SourceRefreshResponse` accepted/reused semantics. Their old implementation
functions remain undecorated worker-only connector executors for internal and
test compatibility. No normal HTTP metadata route calls them inline.

## 13. Operator Options

The source-specific allowlist is:

| Source | Persisted bounded options |
|---|---|
| World Bank | `max_pages` 1–100, `rows` 1–100, `active_only`, `dry_run` |
| GIZ | `max_pages` 1–12, `dry_run`; inline `download_documents=true` rejected |
| ADB | `max_items` 1–2000, `max_pages` 1–100, fixed `feed_type`, `dry_run`; `download_documents=true` rejected |
| EBRD | `max_items` 1–200, `detail_items` 0–100, `active_only`, `dry_run` |
| UzEx | no tuning options |

Unknown keys, arbitrary URLs, non-boolean flags, and out-of-range limits are
rejected before persistence. No secrets or credentials are stored.

## 14. Customer Route

`POST /sources/{source_system}/refresh` remains the customer route and exposes
no connector tuning. Approved users may request a refresh; only operators or
admins may use `force=true`.

## 15. Cooldown

The existing default 300-second completed-job cooldown is retained for customer
requests. A recent successful job returns `fresh` and reuses its durable row.
Operator requests are explicit commands and bypass the completed cooldown.

## 16. Force Semantics

Force is operator/admin-only and bypasses only completed cooldown. It never
bypasses a queued job, a running job, active-source uniqueness, or a valid
foreign lease.

## 17. Stale Recovery

A running job is stale only when `lease_expires_at` has elapsed, not because its
`updated_at` is old. Historical running rows without lease metadata receive one
180-second legacy grace window. Queued jobs older than 60 seconds are eligible
for republishing under the same job ID.

## 18. Publish Failure Recovery

A newly committed queued job whose initial publish fails is marked `failed`
with a safe dispatch reason and `retryable=true`, allowing a later request to
create a new job. Republishing an expired running job never terminalizes it on
broker failure; it remains recoverable. Duplicate publications are safe because
claim authority is in PostgreSQL, not the broker.

## 19. Status API

`GET /sources/refresh-status` returns all five known sources, including a
`never` row when no history exists. It exposes job ID, status, trigger,
created/start/heartbeat/lease-expiry/completed timestamps, committed counters,
safe diagnostics, source health, and a safe message.

## 20. Status Query Performance

A window query ranks each source's jobs and returns the latest rows in one SQL
statement. The disposable audit measured exactly one SELECT for five source
statuses, replacing five serial queries.

## 21. Historical Job Compatibility

Historical rows remain in place. `trigger_kind` is nullable because an old
row's trigger cannot be proven. Options and new counters receive safe empty/zero
defaults. No startup path creates or runs refresh work.

## 22. Migration

`20260831_0001_sr2_2_refresh_leases` is the sole additive migration. It extends
only `source_refresh_jobs`, adds a trigger check constraint, a
source/status/completion index, and a partial running-lease-expiry index. A
disposable downgrade/seed/upgrade proof preserved historical jobs and identical
Tender row counts. Alembic reports one clean head.

## 23. Concurrency Tests

The PostgreSQL audit issued 20 concurrent customer requests for UzEx. They
resolved to one active job ID and one broker publication. The lease matrix
proved live-owner exclusion, heartbeat renewal, expired takeover, old-owner
heartbeat rejection, old-owner terminal rejection, new-owner terminal success,
and terminal redelivery short-circuiting.

## 24. Counter Tests

Focused worker tests cover fetched, created, updated, unchanged, skipped,
rejected, failed, fallback, diagnostics, discovery, and zero queued-document
semantics. The SR-2.1 disposable audit remains the large-batch authority for
10,000 unchanged, 4k/2k/4k mixed results, concurrent insert truth, and rollback
counters.

## 25. Source Compatibility

Connector retrieval and persistence bodies were not redesigned. World Bank
Project/TenderProject enrichment remains post-commit and asynchronous. GIZ
targeted hydration remains available. ADB and EBRD retrieval and access
restrictions are unchanged.

## 26. Regression Results

Release evidence completed locally:

- focused SR-2.2/customer/worker: 22 passed;
- connector gate: 195 passed, 1 approved skip, 4 subtests;
- SR-2.1 disposable 10k/mixed/concurrency/rollback matrix: passed;
- Sprint 6: 36 passed;
- Sprint 5 plus Bid Preparation passivity: 29 passed;
- Sprint 3: 54 passed and 54 subtests;
- Sprint 1/World Bank: 85 passed;
- broad root backend sweep excluding the repository's known nonportable legacy
  `test_ai.py`: 561 passed, 1 approved skip, and 75 subtests;
- SR-2.2 disposable existing/fresh database and lease/request/status matrix:
  passed;
- configured local preflight: read-only, zero active jobs, zero stale legacy
  running jobs, and zero detectable negative-counter anomalies. The configured
  local database was intentionally not migrated by the read-only preflight.

## 27. Deferred SR-2.3 Work

Deferred work remains: a connector capability/source enablement registry,
incremental cursors, normalized connector result redesign, ADB document/contact
decoupling, final document queue metrics, stage timings, equal-provenance World
Bank optimization, and source-level HTTP metrics. SR-2.4/SR-3 completion feeds,
polling, notifications, and frontend “New” state are also not implemented.
