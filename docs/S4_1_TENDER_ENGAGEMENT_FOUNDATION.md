# Sprint 4.1 — Canonical Tender Engagement Foundation

## 1. Previous My Bids Model

| Surface | Current model | Identity | Ownership | Creation trigger | Status semantics | Proves engagement? | Proves submission? | Migration risk |
|---|---|---|---|---|---|---|---|---|
| `GET/POST /api/v1/proposals` | `Proposal` | Proposal UUID; unique `(user_id, tender_id)` | Direct `Proposal.user_id`; no `company_profile_id` | Explicit API POST, but some frontend navigation/fallback code issues the POST automatically | `DRAFT`, `GENERATING`, `COMPLETED`, `SUBMITTED` describe proposal preparation | No | No | High if treated as engagement because persisted rows do not record creation reason or profile identity |
| `/dashboard/bids` | Proposal list | Proposal UUID for list/detail links | Backend filters by authenticated `user_id` | Lists existing proposals | Legacy “My Bids” presentation of proposal artifacts | No | No | Naming invites incorrect inference |
| `/dashboard/bids/[id]` | Proposal editor | Tries Proposal UUID first; on 404 treats the parameter as Tender UUID and creates/reuses a proposal | Proposal API ownership gate | Opening with a Tender UUID may create a draft | Bid-preparation artifact | User navigation suggests preparation, but persisted origin is absent | No | Route parameter has dual semantics |
| Tender compliance page | Compliance analysis plus proposal compatibility fallback | Canonical Tender UUID, with Proposal UUID fallback | Explicit compliance ownership tuple | A missing compiled-text fallback calls `POST /proposals` | Decision support; proposal may be incidental setup | No | No | Existing proposal cannot prove explicit prepare intent |
| Hunter | `TenderRecommendation` | `(company_profile_id, tender_id)` | Profile ownership | Worker recommendation generation | Score plus recommendation-only `is_dismissed` | No | No | Hunter dismissal must not be migrated into engagement dismissal |

Answers to the required audit questions:

1. No background worker directly creates Proposal, but frontend routes can call the creation endpoint automatically during navigation or fallback setup.
2. Yes. A Proposal may exist without a distinct, persisted “prepare this bid” user command.
3. No. Proposal creation is insufficient historical evidence for `PREPARING`.
4. Runtime code does not interpret Proposal completion/PDF/export as tender submission. `ProposalStatus.SUBMITTED` exists as a legacy enum value, but there is no runtime writer or outcome mapping for it.
5. There is no canonical saved/favorite tender. Hunter recommendation dismissal and saved compliance analyses are separate concepts.

## 2. Proposal Semantics

Proposal remains a Bid Preparation artifact. PDF generation and DOCX export set
Proposal to `COMPLETED`; they do not write TenderEngagement. Proposal generation,
completion, and existence do not mean a tender was submitted.

## 3. TenderEngagement Purpose

`TenderEngagement` answers one question: how one explicitly identified
user/company profile is currently engaging with one canonical Tender. It does
not represent source status, proposal content, compliance analysis, recommendation
score, submission documents, CRM data, or collaboration state.

## 4. Canonical Identity

The logical identity is:

`(user_id, company_profile_id, tender_id)`

All three values are stable UUIDs. A PostgreSQL unique constraint named
`uq_tender_engagements_owner_tender` enforces one current row per scope. Names,
titles, URLs, hashes, Proposal IDs, and Analysis IDs are not identity.

## 5. Ownership

`user_id` has a restrictive User FK. The composite
`(company_profile_id, user_id)` has a restrictive FK to the corresponding unique
pair on CompanyProfile, so an invalid cross-user profile pairing is rejected by
both the service and database. `tender_id` has a restrictive Tender FK. Customer
reads and writes require the complete tuple. Same-name companies never collide.

The Sprint 4.1 foundation is service-only, so it introduces no customer or admin
API bypass. Future endpoints must retain the existing approved-pilot account gate
and pass the authenticated user UUID; admin status alone does not confer customer
engagement access.

## 6. Status Lifecycle

- `SAVED`: user wants to retain the opportunity.
- `EVALUATING`: company is actively deciding whether to bid.
- `PREPARING`: company is actively preparing a bid.
- `SUBMITTED`: user explicitly records submission.
- `WON`: user explicitly records a successful outcome.
- `LOST`: user explicitly records an unsuccessful outcome.
- `DISMISSED`: company currently does not intend to pursue the tender.

Sprint 4.1 stores current status plus `created_at`, `updated_at`, and
`status_changed_at`. It does not fabricate event timestamps or introduce a status
event ledger.

## 7. Transition Matrix

Normal commands:

| From | Allowed target states |
|---|---|
| `SAVED` | `EVALUATING`, `PREPARING`, `DISMISSED` |
| `EVALUATING` | `SAVED`, `PREPARING`, `DISMISSED` |
| `PREPARING` | `SAVED`, `EVALUATING`, `SUBMITTED`, `DISMISSED` |
| `SUBMITTED` | `WON`, `LOST` |
| `DISMISSED` | `SAVED`, `EVALUATING`, `PREPARING` |
| `WON` | none |
| `LOST` | none |

Explicit corrections are separate from normal commands:

- `SUBMITTED → PREPARING`
- `WON → SUBMITTED` or `LOST`
- `LOST → SUBMITTED` or `WON`

Same-state and all unlisted transitions raise
`TenderEngagementTransitionError`; they never silently no-op.

## 8. Tender Status Separation

`Tender.status` and `TenderEngagement.status` are independent. The service contains
no synchronization code. PostgreSQL proof changed a source Tender from `OPEN` to
`CLOSED` and later `CANCELLED` while the engagement remained `SUBMITTED` and then
`WON` respectively.

## 9. Submission Semantics

Only `mark_submitted` calls the validated lifecycle service with `SUBMITTED`.
Proposal creation, Proposal completion, PDF generation, DOCX export, Compliance
Analysis, deadline passage, source closure, Hunter score, and recommendation score
have no TenderEngagement writer.

## 10. Outcome Semantics

Only `mark_won` and `mark_lost`, or the separately explicit correction command,
write outcomes. Tender metadata, source status, deadlines, proposal activity,
document generation, award snippets, and compliance activity cannot infer `WON`
or `LOST`.

## 11. Dismissal / Re-engagement

Dismissal changes only the engagement row. Tender, Proposal, TenderAnalysis,
AnalysisVersion, Project, and administrative audit rows are preserved.
Re-engagement is supported from `DISMISSED` to `SAVED`, `EVALUATING`, or
`PREPARING`, and database uniqueness ensures the original row is reused.

## 12. Origin Semantics

The immutable creation reason is one of:

- `MANUAL_SAVE`
- `MANUAL_EVALUATION`
- `BID_PREPARATION`
- `LEGACY_PROPOSAL`
- `OTHER_EXPLICIT_USER_ACTION`

Origin is independent of current status. Normal creation deliberately rejects
`LEGACY_PROPOSAL`; that value is reserved for a separately approved, deterministic
reconciliation.

## 13. Proposal Relationship

No new Proposal FK was added. Both entities reference the canonical Tender, while
Proposal remains owned by User under its existing schema. This is the minimum safe
relationship for Sprint 4.1. Proposal creation does not create or mutate an
engagement; that integration remains Sprint 4.3 work.

## 14. Compliance Relationship

Compliance remains decision support. TenderAnalysis and AnalysisVersion creation,
reads, and quarantine paths have no TenderEngagement dependency or writer. A
PostgreSQL test inserted an analysis-only quarantined row and proved the engagement
count did not change.

## 15. Hunter / Recommendation Relationship

Recommendation generation and `TenderRecommendation.is_dismissed` remain separate.
Neither recommendation scores nor Hunter dismissal create or mutate engagement.

## 16. Legacy Proposal Audit

The read-only audit of the configured local development PostgreSQL database at
revision `20260828_0002_s3_4_admin_audit_hardening` reported:

| Metric | Result |
|---|---:|
| Total proposals | 118 |
| Valid User/Profile/Tender relationship | 110 |
| Invalid or missing owner relationship | 8 |
| Proposal owners without a CompanyProfile | 1 |
| Duplicate logical engagement keys | 0 |
| Persisted explicit-user-intent classification | Not determinable |
| Conservatively possibly auto-generated | 118 |
| Proposal statuses | 109 `DRAFT`, 9 `COMPLETED`, 0 `SUBMITTED` |

No customer content was selected or reported. The current schema already rejects
duplicate Proposals per `(user_id, tender_id)`.

## 17. Backfill Decision

Policy A: no Sprint 4.1 engagement backfill. Proposal rows do not persist creation
reason and can be created by compatibility/navigation behavior. Mapping any legacy
Proposal to `PREPARING`, and especially to `SUBMITTED`, would fabricate user intent.
The migration creates schema only.

## 18. Concurrency

Creation uses PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` against the canonical
unique constraint, then returns the one canonical row. Two separate sessions
concurrently creating the same scope returned one `created=true`, one reused row,
and exactly one database row with no 500/error.

Status changes select the exact owned row `FOR UPDATE`. A two-session competing
`PREPARING → SUBMITTED` / `PREPARING → DISMISSED` test produced one successful
transition and one explicit transition conflict. Final status and
`status_changed_at` matched the committed command with no partial state.

## 19. Migration

The single additive revision is
`20260828_0003_s4_1_tender_engagement_foundation`, directly after
`20260828_0002_s3_4_admin_audit_hardening`. It adds two narrow enum types, the
composite CompanyProfile ownership key, the engagement table, restrictive FKs,
indexes, and uniqueness. It performs no network/LLM/source calls and no data
backfill.

Disposable PostgreSQL 16.12 fresh bootstrap reached the new single head with zero
engagement rows and a clean `alembic check`. A representative existing database
upgrade preserved all seeded User, CompanyProfile, Tender, Proposal,
TenderAnalysis, AnalysisVersion, Project, and AdminActivityEvent counts and added
zero engagement rows.

## 20. Preflight

The read-only preflight now reports:

- total engagements and counts for all seven statuses;
- duplicate logical keys;
- invalid User/Profile relationships;
- broken Tender FKs;
- unknown/invalid statuses;
- aggregate-only legacy Proposal candidate classification.

It runs in a read-only transaction, never uses the ORM/application helpers, and
always rolls back. It returned clean engagement integrity on the disposable
upgraded database. On the current local database before migration it truthfully
reports that `tender_engagements` does not yet exist.

## 21. Regression Results

- Sprint 4.1 static/foundation: 42 tests and 7 subtests passed.
- Sprint 4.1 PostgreSQL fresh/existing/concurrency proof: passed.
- Sprint 3 focused: 49 tests and 54 subtests passed; disposable lifecycle,
  survivability, audit, and operational UX scripts passed with zero failures.
- Sprint 2 focused: 35 tests passed; disposable ownership, versions, aggregate
  concurrency, and version-aware read scripts passed with clean Alembic checks.
- Sprint 1/WB focused: 51 tests passed; disposable project, enrichment, and
  auto-drain scripts passed with zero failures and no leaked databases.
- Connector gate: 195 tests and 4 subtests passed; one approved storage fixture
  skip remained.
- Frontend: no files changed, so frontend quality gates were not required.

## 22. Deferred Sprint 4.2 / 4.3 Work

Sprint 4.2 retains the My Tenders list API/UI, filters, counts, sorting, bulk actions,
and empty states. Sprint 4.3 retains Proposal-to-engagement integration, legacy
reconciliation decisions, My Bids naming/route cleanup, and proposal navigation.
Sprint 4.4 retains workflow UI and browser acceptance. No deployment or production
mutation was performed.
