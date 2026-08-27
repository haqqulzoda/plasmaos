# Sprint 2.1 — Compliance Ownership and Legacy Quarantine

## 1. Historical Ownership Defect

`TenderAnalysis.company_name` historically served two incompatible purposes:
display metadata and authorization identity. Newer rows sometimes stored the
deterministic string `<user UUID>:<company-profile UUID>`, while older rows
stored a company or user display name. Runtime reads also attempted to claim
display-name rows for the currently authenticated user. Two profiles can share
a name, and today's unique name is not proof of historical ownership. Display
name is therefore removed from every authorization decision.

## 2. Canonical Ownership Contract

Customer-visible analyses are owned only when all of the following hold:

- `TenderAnalysis.user_id` references `users.id`;
- `TenderAnalysis.company_profile_id` references `company_profiles.id`;
- `TenderAnalysis.ownership_state = 'OWNED'`;
- the profile belongs to the same user under the existing one-user/one-profile
  product relationship.

Both foreign keys use `ON DELETE RESTRICT`. Compliance analyses and their
forensic artifacts cannot be erased indirectly by deleting an owner record.
Profile/user consistency is established by migration joins and enforced by the
application whenever an owner is written or queried.

## 3. Ownership State

The deliberately narrow state model is:

- `OWNED`: both canonical IDs are present and mutually consistent.
- `QUARANTINED_LEGACY`: both canonical IDs are null because historical
  ownership is not authoritative.

The database check constraint rejects every other tuple. There is no
`INFERRED` state and no guessed assignment workflow.

## 4. Migration

Migration `20260827_0001_s2_1_compliance_ownership` follows Sprint 1 head
`20260826_0002_s1_2_wb_project_enrichment`. It adds the two nullable UUID
foreign keys, ownership state, two indexes, conservative foreign keys, and the
ownership-tuple check. It performs only database-local updates: no network,
LLM, deletion, or compliance-content mutation.

The state server default is `QUARANTINED_LEGACY`. During a rolling migration,
an old application instance can insert a preserved but customer-invisible row;
it cannot create an apparently owned row without canonical identity.

## 5. Deterministic Backfill

The only accepted historical evidence is the already documented exact encoding
`<user UUID>:<profile UUID>`. A row becomes `OWNED` only when the user exists,
the profile exists, and `company_profiles.user_id` equals the decoded user.
Missing users, missing profiles, `no-profile`, mismatches, and malformed tokens
remain quarantined.

## 6. Quarantine Policy

Every display-name-only, empty, malformed, zero-match, unique-current-match, or
multi-match historical row becomes `QUARANTINED_LEGACY` with both owner IDs
null. Quarantine changes only ownership columns. The analysis ID, tender link,
`company_name`, extracted text, JSON result/evidence, hashes, override seal,
timestamps, audit ledger, override logs, and related artifacts are preserved.

Quarantined analyses are excluded from all ordinary customer queries. Existing
admin reproducibility diagnostics remain available only behind the established
`require_admin` dependency and do not claim ownership.

## 7. Same-Name Protection

Every customer predicate requires exact user ID, exact profile ID, and `OWNED`.
Neither equal nor similar names participate. The migration proof includes two
profiles named `Acme Engineering`; their display-name legacy row remains
quarantined. It also includes a single `Unique Engineering` profile; that
unique display-name row remains quarantined as well.

## 8. New Write Path

The analysis endpoint loads the authenticated user's canonical profile through
the existing compliance-profile service. It fails safely if the profile is
missing or empty. Every new `TenderAnalysis` explicitly writes authenticated
`user_id`, canonical `company_profile_id`, `OWNED`, and a descriptive
`company_name` snapshot. The database tuple constraint prevents ownerless
`OWNED` writes.

## 9. Read Authorization

Cached analysis lookup, latest analysis, tender access derived from an existing
analysis, and proposal compliance context now filter on the three canonical
ownership fields. Runtime display-name compatibility and legacy row claiming
have been removed. Quarantined rows cannot appear in customer history.

## 10. Risk Override / Export Authorization

Direct analysis lookup for risk overrides resolves through exact canonical
ownership before any override is read or written. Audit-ledger authorization
uses the same identity tuple. PDF export filters by tender and canonical owner,
and an optional direct `analysis_id` cannot bypass that predicate. Another
tenant's or a quarantined analysis returns not found.

## 11. Preflight Reporting

`backend/scripts/run_s0_3_schema_data_preflight.py` remains read-only and now
reports aggregate `canonical_ownership` counts for owned, quarantined, invalid
FK, user/profile mismatch, invalid tuples, and quarantined legacy remnants. It
continues to report deterministic encoded classifications plus current
zero/unique/multiple display-name matches for diagnostics. Its
`safe_legacy_rows` value is always zero. It emits no analysis content or
customer names and never repairs or claims rows.

## 12. Data Preservation

The disposable existing-database proof seeded ten analyses plus Proposal,
TenderRecommendation, Project/TenderProject, AuditLog, and RiskOverrideLog
artifacts. Before/after comparison of every pre-existing analysis business
field and all related artifact counts was exact. Result: ten historical rows
preserved, two deterministically owned, eight quarantined, zero deletions.

## 13. Rolling Deployment Compatibility

| Combination | Result |
| --- | --- |
| Old code + old schema | Existing behavior; unsafe and only valid before rollout begins. |
| Old code + new schema | Starts and reads old behavior; new analysis inserts default to quarantine, so no false owner is created. |
| New code + old schema | Incompatible because explicit ownership columns do not exist. |
| New code + new schema | Supported canonical behavior. |

Required order: apply the migration first, then promptly roll API instances to
the new code. Do not deploy new code before the migration. After cutover, use
the read-only preflight report to detect any rows quarantined by an overlapping
old instance.

## 14. Test Results

The dedicated disposable PostgreSQL matrix proves:

- fresh database reaches the new single head with zero fabricated analyses;
- representative Sprint 1 database upgrades to the new head;
- valid encoded rows become owned;
- missing, mismatched, display-name, unique-name, empty, and malformed rows are
  quarantined;
- same-name cross-tenant and direct-ID predicates return no row;
- ownerless `OWNED` insertion is rejected;
- old-code insertion on the additive schema defaults to quarantine;
- business data and related artifacts are unchanged;
- `alembic check` reports no operations.

Focused ownership/static tests and the repository regression gates are recorded
in the Sprint 2.1 handoff. The completed local run produced 380 passing backend
tests, 1 approved storage-fixture skip, and 21 passing subtests; the connector
gate produced 195 passing tests, the same single approved skip, and 4 passing
subtests. Project Context produced 18 passing frontend tests and TypeScript
type-checking passed. No production validation was run in this task.

## 15. Deferred Manual Reconciliation

No customer or admin claim UI is introduced. Quarantined analyses remain
preserved for a later, separately authorized reconciliation design. A future
process must require independent authoritative evidence; display-name
uniqueness remains insufficient.

## 16. Production Deployment Considerations

This task does not deploy or access production. A later authorized rollout
should record the read-only preflight aggregates before migration, apply the
migration before code, verify the single Alembic head, roll the API, repeat the
aggregate report, and investigate invalid/mismatch counts (which must remain
zero). Historical quarantine totals are expected and must not be auto-repaired.
