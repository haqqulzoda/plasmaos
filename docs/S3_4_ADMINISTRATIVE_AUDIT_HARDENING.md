# Sprint 3.4 — Append-Only Administrative Audit Hardening

## 1. Previous Admin Activity Model

`admin_activity_events` already existed and was the correct table to extend. It
stored `id`, a free-form action, nullable actor FK/label, target FK/email,
reason, metadata JSON, and `created_at`. Writers were the admin lifecycle and
company endpoints, Google allowlist reconciliation, and the repair command.
The Admin overview read the latest 20 rows. Events had no explicit outcome,
source, actor type, state columns, or database immutability. Success writes were
generally in the business transaction, but denials were not durable events.

## 2. Canonical Audit Authority

`AdminActivityEvent` / `admin_activity_events` remains the single authority for
administrative security events. Compliance `AnalysisVersion`, forensic hashes,
`RiskOverrideLog`, tender evidence history, and ordinary logs remain separate.
All runtime writes go through `record_admin_audit_event`; deterministic denials
and post-rollback failures use `record_independent_user_audit_event`, which
ultimately calls the same validated canonical insert service.

## 3. Event Schema

The additive schema retains legacy fields and adds:

- `actor_type`, `actor_email_snapshot`, `actor_role_snapshot`
- `target_resource_type`, `target_resource_id`
- `outcome`
- `previous_state`, `new_state`
- `reason_code`, `request_id`, `source`

The existing `created_at` is exposed as `occurred_at` by the read API. Existing
`actor_label`, target email snapshot, reason text, and safe metadata remain.
Actor and target FKs use `ON DELETE SET NULL`, never cascade.

## 4. Action Taxonomy

Controlled actions are `USER_APPROVED`, `USER_REJECTED`, `USER_DISABLED`,
`USER_RESTORED`, `COMPANY_APPROVED`, `COMPANY_REJECTED`, `COMPANY_DISABLED`,
`ADMIN_GRANTED`, `OPERATOR_GRANTED`, `ALLOWLIST_PRIVILEGE_RECONCILED`, and
`ADMIN_REPAIR_PROMOTION`. A denial uses the attempted action plus a controlled
reason code instead of multiplying action names for each denial condition.

## 5. Outcome Taxonomy

- `SUCCESS`: the security-sensitive transition and audit row committed.
- `DENIED`: an authenticated privileged attempt was intentionally prevented.
- `FAILED`: mutation work began but the transaction failed and rolled back.

Database and service validation limit canonical outcomes to `SUCCESS`,
`DENIED`, and `FAILED`.

## 6. Success Events

Approve, reject, disable, and restore each append exactly one `SUCCESS` event
inside the lifecycle transaction. Company approval/rejection/disable follows
the same rule. Previous and new values use explicit semantic snapshots. New
state records `credentials_invalidated: true`; raw `auth_version` is absent.

## 7. Denied Events

Authenticated admin self-disable/self-reject, last-effective-admin safety,
stale-actor authority, and invalid lifecycle transitions are durable `DENIED`
events. Controlled reason codes are `SELF_ACTION_PROHIBITED`,
`LAST_EFFECTIVE_ADMIN`, `STALE_ACTOR_AUTHORITY`, and
`INVALID_LIFECYCLE_TRANSITION`. Unknown targets return 404 without fabricating
a target event. Routine unauthenticated/non-admin HTTP probes remain ordinary
security/access logs, not durable ledger entries.

## 8. Failed Events

User and company administrative mutation transaction failures explicitly roll
back, then attempt one independent `FAILED` event with
`TRANSACTION_FAILED`. The event states that no transition committed and stores
no exception text or stack trace. A total database outage can necessarily make
both the business operation and the independent audit database unavailable;
the original failure is not mislabeled as success.

## 9. Transactional Semantics

Success audit insertion is flushed and committed in the same SQL transaction
as the mutation. An audit insertion/commit failure rolls the mutation back, so
a committed transition cannot lack its success event. A deterministic denial
first rolls the protected transaction back (also releasing the advisory lock),
then opens a separate short transaction to persist the denial. No partial
lifecycle state is committed to save a denial.

## 10. Append-Only Contract

Runtime code provides create and read operations only. Migration
`20260828_0002_s3_4_admin_audit_hardening` installs a PostgreSQL trigger that
rejects every `UPDATE` or `DELETE` on `admin_activity_events`. Disposable DB
tests proved both statements fail. Because FK nulling is itself an update, a
future hard user delete is effectively restricted while referenced audit rows
exist; Sprint 3.4 adds no user deletion feature.

## 11. Actor / Target Snapshots

Human events preserve actor UUID, normalized email, and role snapshots. System
and repair paths keep `actor_user_id` null and use truthful `SYSTEM` or
`SERVER_COMMAND` actor types. Target UUID, normalized email snapshot, resource
type, and resource ID preserve readability. A disposable test changed the live
target email after insertion and proved the event snapshot did not change.

## 12. Sensitive Data Policy

Previous/new states are allowlisted to approval status, role, legacy admin
flag, effective-admin semantics, pre-disable provenance, and the boolean
credential-invalidation semantic. The service recursively rejects metadata
keys associated with passwords, tokens, authorization, cookies, sessions,
credentials, secrets, signed URLs, and database/Redis URLs. It does not store
raw `auth_version`, OAuth/Google credentials, headers, IP addresses, user
agents, stack traces, or full ORM dumps.

## 13. Admin Repair

The verified allowlisted repair command emits one
`ADMIN_REPAIR_PROMOTION/SUCCESS` event from `ADMIN_REPAIR_COMMAND`. Its actor is
`SERVER_COMMAND` with no actor user FK even when a caller supplies an actor
email label; the command does not fabricate authenticated human identity. The
command now requires the canonical audit schema before promotion.

## 14. Allowlist Grants

Google reconciliation emits `ADMIN_GRANTED` or `OPERATOR_GRANTED` when that
privilege transition actually occurs, otherwise the narrow reconciliation
action where applicable. The source is `GOOGLE_ALLOWLIST`, actor type is
`SYSTEM`, and the event shares the authentication transaction. A second login
with no role-state change emits no duplicate grant event.

## 15. Concurrency Audit

The Sprint 3.3 PostgreSQL advisory transaction lock remains authoritative.
Disposable races proved one `SUCCESS` plus one `DENIED` for competing admin
removals, and one `SUCCESS` plus one invalid-transition `DENIED` for two admins
disabling the same target. No second lifecycle mutation or duplicate event was
observed.

## 16. Read API

`GET /api/v1/admin/audit-events` lists canonical and legacy events. It accepts
`actor_user_id`, `target_user_id`, `action`, and `outcome` filters. The response
contains safe event fields, snapshots, total, limit, and offset. No detail route
or audit-read meta-event was added.

## 17. Authorization

The audit endpoint uses `require_admin`, whose effective-admin and current
credential-version checks reject ordinary users, operator-only users,
pending/rejected/disabled admin-role rows, and stale credentials. The legacy
Admin overview now also requires an effective admin because it embeds recent
events. Other operator support routes retain their prior authorization.

## 18. Pagination / Indexes

Offset pagination is bounded to 1–100 rows (default 50), with deterministic
`created_at DESC, id DESC` ordering. Existing action, target, email, and time
indexes remain; the migration adds actor, outcome, and `(created_at, id)`
indexes.

## 19. Historical Legacy Policy

Existing rows remain byte-for-byte semantically intact. New fields are nullable
and stay null for historical rows; no actor, outcome, source, or state is
fabricated from current data. Preflight counts these as legacy/partial. The
read API transparently represents their unavailable canonical fields as null.

## 20. Preflight

The read-only preflight now includes `admin_activity_events` schema and volume
plus aggregate counts for total/success/denied/failed, malformed actions,
invalid outcomes, legacy/partial events, canonical rows without source, and
broken actor/target references. It never selects event metadata or state
payloads and performs no repair.

## 21. Regression Results

Focused Sprint 3.1–3.4 tests pass (41 tests), and both Sprint 3.4 disposable
PostgreSQL scenarios pass. The DB
proof covers fresh bootstrap, existing S3.1 history upgrade, exact event counts,
rollback, independent denial/failure durability, grants, repair, filters,
snapshot stability, append-only enforcement, migration round-trip, one head,
and `alembic check`. The complete Linux-compatible backend unit suite passes
354 tests with one approved skip. Sprint 2 ownership/version/concurrency/read
database scripts, Sprint 1 Project/World Bank/enrichment/auto-drain scripts,
and the Sprint 3.3 concurrency script pass against disposable databases with no
leaks. The connector gate passes 195 tests, one approved fixture skip, and four
subtests. Frontend typecheck and production build pass; lint has zero errors and
15 pre-existing warnings. `git diff --check` passes apart from line-ending
notices. The repository has one Alembic head and every disposable `alembic
check` is clean. The legacy `backend/test_ai.py` hard-codes a Windows working
directory and is not part of the Linux release gate.

## 22. Deferred Admin UI Work

No audit-history UI, charts, role-management interface, session dashboard, or
Admin redesign was added. Presentation and usability remain Sprint 3.5 scope.
Sprint 3.4 made no deployment and did not migrate or mutate the configured
database.
