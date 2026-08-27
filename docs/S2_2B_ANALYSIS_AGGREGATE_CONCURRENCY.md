# Sprint 2.2B — Analysis Aggregate Concurrency Hardening

## 1. Root Concurrency Defect

The Compliance endpoint performed an owned-parent lookup before AI extraction,
then inserted a new `TenderAnalysis` if that earlier lookup found none. Two
first-analysis requests in separate API processes could both observe zero,
complete extraction, and insert separate parents. The existing parent row lock
made version allocation safe only after a common parent already existed.

## 2. Canonical Aggregate Identity

The runtime contract established by Sprint 2.1 is exactly:

```text
(user_id, company_profile_id, tender_id), ownership_state = OWNED
```

All three values are canonical UUID foreign-key identities. `company_name` is a
display snapshot and never participates. Content, input, output, evidence, and
version hashes are execution evidence and never aggregate identity.

## 3. Historical Duplicate Audit

The local application database remains intentionally at the Sprint 1.2 schema,
so it cannot truthfully answer Sprint 2 ownership/version questions and was not
mutated. A controlled representative Sprint 2.2 PostgreSQL database reported:

- total TenderAnalysis parents: 3
- distinct grouped logical keys: 2
- keys with one parent: 1
- keys with multiple parents: 1
- maximum parents per key: 2
- owned multi-parent keys: 1
- quarantined multi-parent keys: 0
- invalid canonical keys: 0

The diagnostic emits aggregates only; it never reads analysis content.

## 4. Historical Duplicate Policy

Historical parents and their v1 snapshots remain separate facts. No row is
deleted, merged, reassigned, or chosen by name/hash. Sprint 2.2 already documents
the newest owned parent (`created_at DESC, id DESC`) as the runtime compatibility
target. Sprint 2.2B retains that explicit rule, locks every matching parent, and
logs `analysis_aggregate_historical_ambiguity` when more than one exists.

An equivalent cached request against the two-parent fixture reused the documented
target, created no third parent/version, and left both parents and all existing
versions/snapshots byte-for-byte unchanged.

## 5. Runtime Canonical Parent Contract

`resolve_or_create_analysis_aggregate()` validates the user/profile relationship,
acquires protection for the exact ID tuple, and then:

- zero owned parents: stages one new owned parent;
- one owned parent: reuses it;
- multiple historical owned parents: logs ambiguity and reuses the existing
  deterministic Sprint 2.2 runtime target without modifying the other parents.

Quarantined rows never enter this lookup and cannot block a legitimate owned
aggregate.

## 6. Database Concurrency Mechanism

The service executes PostgreSQL
`pg_advisory_xact_lock(hashtextextended(canonical_identity, 0))`. The lock is
database-backed, transaction-scoped, and shared across API processes/workers.
A 64-bit hash collision can only serialize unrelated scopes; it cannot merge or
misidentify them because the subsequent query still uses all three UUID columns.

No Python/global lock or request-order assumption exists. Existing parent rows
are additionally selected `FOR UPDATE` before version allocation.

## 7. Ownership Interaction

A new parent must match the authenticated `user_id`, owned
`company_profile_id`, `tender_id`, and `OWNED` state. The service verifies that
the profile belongs to the user before locking/creation. Invalid tuples fail and
roll back. Sprint 2.1 authorization remains parent-based and unchanged.

## 8. Quarantine Interaction

`QUARANTINED_LEGACY` rows have null tenant IDs and are excluded from canonical
resolution. The controlled fixture retained its quarantined parent while a
same-tender legitimate tenant created a separate owned parent.

## 9. First-Analysis Concurrency

Two separate asynchronous SQLAlchemy sessions raced from zero parents. Both used
the same PostgreSQL database and transaction contexts. Final state was one parent
with v1; one request created it and the other reused the completed result.

The endpoint now rechecks cache equivalence under the aggregate lock because the
initial cache lookup may have become stale during AI extraction.

## 10. Re-analysis Concurrency

An existing parent with v1 received two concurrent forced writes. The advisory
scope serialized aggregate resolution and the existing parent lock preserved
version allocation. Final sequence was v1, v2, v3 with valid supersedes lineage.

A concurrent first request plus content-changing forced request produced one
parent with v1/v2 and no split history.

## 11. Proposal Concurrency

Proposal `ai-draft` only selects an existing owned Compliance parent; it does not
create or trigger Compliance analysis. A controlled Proposal read raced direct
creation and final state contained exactly the one direct-analysis parent.

## 12. Dual-Write Interaction

Aggregate resolution, parent creation/reuse, immutable version append, document
snapshots, compatibility-mirror update, and commit remain in one transaction.
First analysis produces parent + v1 atomically. Re-analysis appends to the same
parent before updating its compatibility mirror.

Equivalent non-forced cached requests create no version. Forced or content-
changing requests append a version. Equal hashes never merge separate historical
or tenant aggregates.

## 13. Failure/Rollback

The transaction-level advisory lock releases automatically on commit, rollback,
or connection loss. A controlled failure after staging parent + v1 was rolled
back; queries found neither row. A retry immediately acquired the scope and
committed one parent + v1 with a valid ownership tuple.

## 14. Migration Decision

No migration was added. PostgreSQL transaction advisory locking provides the
required cross-process database correctness without rewriting historical data or
adding a canonical marker. The sole head remains
`20260827_0002_s2_2_analysis_version_foundation`.

Because no marker is persisted, the read-only diagnostic reports
`post_cutover_marker=false` and does not pretend historical single-parent rows
are distinguishable from post-cutover rows.

## 15. Preflight

Run after the Sprint 2.2 schema is present:

```bash
python scripts/report_analysis_aggregate_concurrency.py
```

It reports total parents, logical key distribution, maximum parents, owned
single/multi-parent keys, quarantine keys, and invalid ownership/profile tuples.
It rolls back its read transaction and emits no snapshot/content values.

## 16. Regression Results

- Sprint 2.2B fast contracts: included in 34 focused Sprint 2 tests, all passed.
- Sprint 2.2B disposable fresh/existing PostgreSQL matrix: A–L passed, zero
  leaked databases, clean Alembic check.
- Sprint 2.2: migration/backfill/immutability/snapshots/provenance/dual-write,
  v2/v3 concurrency, risk override, 1,003-row load, and preflight passed.
- Sprint 2.1: fresh/existing ownership matrices passed with historical rows and
  related artifacts preserved.
- Maintained Compliance/security set: 113 passed and 10 subtests passed.
- Sprint 1 focused tests: 51 passed; foundation and enrichment PostgreSQL
  matrices passed with zero leaked databases.
- World Bank auto-drain: 125 to 0 progression, concurrent dispatcher, worker
  chain, leases, retry, terminal, and partial cases passed unchanged.
- Connector gate: 195 passed, 4 subtests passed, 1 existing approved storage
  fixture skip, zero failures.

## 17. Deployment Impact

No deployment or production access occurred.

| Combination | Result |
|---|---|
| Old S2.1 code + S2.2 schema | Unsafe: old writes can create parents without required versions and can still race. |
| New S2.2B code + pre-S2.2 schema | Incompatible because version tables are absent. |
| New S2.2B code + existing S2.2 head | Compatible; this is also the S2.2B schema because no migration was added. |

Compliance writes must remain quiesced while upgrading the database through
Sprint 2.2 and replacing all API instances. Mixed old/new application processes
are unsafe because old processes do not participate in the advisory lock. This
does not add a new migration window, but it makes the already-required all-instance
code cutover important.

## 18. Deferred Sprint 2.3 Work

Version-authoritative reads, history routes/UI, comparison, PDF version selection,
deep links, latest indicators, and rollback remain deferred. Sprint 2.2B changes
only parent creation/selection correctness.
