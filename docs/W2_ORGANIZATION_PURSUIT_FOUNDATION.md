# W2 Organization and Pursuit foundation

Date: 2026-09-25  
Baseline: accepted W0/W1 tree derived from `122e50b05760e3740845a744057cb6f2b4a11816`  
Previous Alembic head: `20260912_0001_s10_5_communications`  
W2 Alembic head: `20260925_0002_w2_organization_pursuit`

## Status

W2 establishes `Organization` as the private tenancy root, durable `Membership` records as the authorization relation, and `OrganizationPursuit` as the lifecycle authority. The two W2 migrations are additive. Legacy Company Profiles, Engagements, Proposals, analyses, source Tenders, Projects, and Project Leadership remain in place.

W2 does not add a team management UI, organization switcher, Upload Tender path, private document model, broad Activity system, or Organization deletion endpoint.

## Canonical model

### Organization

Each valid legacy `CompanyProfile` maps to exactly one Organization through a unique `legacy_company_profile_id`. The backfill derives the Organization UUID from the profile UUID. It never compares names, email domains, INN text, or other descriptive values. New onboarding creates the same deterministic Organization and initial membership; company profile edits keep the Organization display name synchronized.

### Membership

One durable row exists for each Organization and User pair. Roles are `OWNER` and `MEMBER`; states are `INVITED`, `ACTIVE`, and `REVOKED`. Invitation and activation are separate commands. Reinvitation reuses the durable membership identity.

Organization resources require an approved, enabled platform User and an ACTIVE Membership in the resource Organization. Platform account state and Membership state remain independent. Restoring a platform User does not change a revoked Membership.

OWNER commands use a PostgreSQL transaction advisory lock scoped to the Organization. Demotion and revocation lock the affected rows and recheck active owners. Concurrent attempts cannot remove every active owner. Revocation transfers owned pursuits to a supplied active same Organization Membership or sets the owner to `NULL` in the same transaction.

### Organization context

The resolver behaves as follows:

- one ACTIVE Membership: resolve it automatically;
- multiple ACTIVE Memberships: require `X-Organization-ID` on the new Organization and Pursuit APIs;
- no ACTIVE Membership: deny private Organization resources;
- explicit context: validate it against an ACTIVE Membership before reading the resource.

No context is selected from descriptive company data.

### OrganizationPursuit

`OrganizationPursuit` owns private source opportunity lifecycle state. `SOURCE` rows require `source_tender_id`; `UPLOAD` rows require it to be null. W2 implements source pursuit creation only. A partial unique index enforces one SOURCE pursuit for each Organization and Tender. The optional owner uses a composite foreign key to enforce that it belongs to the same Organization.

Lifecycle stages retain the existing `SAVED`, `EVALUATING`, `PREPARING`, `SUBMITTED`, `WON`, `LOST`, and `DISMISSED` meanings. Closed or archived pursuits require an explicit reopen command with an explicit active destination. Reopen updates the existing Pursuit UUID and appends a `REOPEN` event.

The narrow `PursuitLifecycleEvent` ledger records create, transition, correction, reopen, and legacy backfill events. A database trigger rejects update and delete operations on persisted events.

## APIs

The new routes are:

- `GET /api/v1/organizations`
- `GET /api/v1/organizations/context`
- `GET /api/v1/organizations/{organization_id}/members`
- `POST /api/v1/organizations/{organization_id}/invitations`
- `POST /api/v1/organizations/memberships/{membership_id}/activate`
- `PATCH /api/v1/organizations/{organization_id}/members/{membership_id}/role`
- `POST /api/v1/organizations/{organization_id}/members/{membership_id}/revoke`
- `GET /api/v1/pursuits`
- `POST /api/v1/pursuits/source`
- `GET /api/v1/pursuits/{pursuit_id}`
- `POST /api/v1/pursuits/{pursuit_id}/transition`
- `POST /api/v1/pursuits/{pursuit_id}/reopen`
- `PATCH /api/v1/pursuits/{pursuit_id}/owner`

The Organization header is allowed by CORS. New routes return not found for inaccessible Organization scoped resources to limit identifier enumeration.

## Legacy compatibility

Each valid legacy Engagement is mapped to a deterministic, separate Pursuit UUID. Its Engagement UUID is retained as unique `legacy_engagement_id`; a check constraint prevents it from equaling the Pursuit UUID. New source pursuits also receive a separate compatibility UUID.

After cutover, lifecycle writes go only to `organization_pursuits`. `tender_engagements` remains read only historical state. The legacy service adapts `/my-tenders`, `/my-tenders/{engagement_id}`, `/tenders/{id}/engagement`, Bid Preparation, and semantic action commands to the canonical Pursuit service while returning the compatibility Engagement UUID expected by existing clients.

My Tenders uses three fixed, set based queries for page rows, total, and stage counts. It preserves tender identity, stage, pagination, source facts, project projection, deep links, and legacy response IDs.

## Proposal and analysis compatibility

W2 does not modify Proposal lifecycle, Proposal UUIDs, AnalysisVersion snapshots, hashes, evidence, language, or exports. Proposal lists project the canonical Pursuit stage where an exact source pursuit exists. Bid Preparation creates or advances the canonical pursuit.

Existing owned analyses remain keyed to their exact User, Company Profile, and Tender. Compatibility analysis reads additionally require the profile's active Organization Membership. Revocation therefore removes private analysis access without rewriting any TenderAnalysis or AnalysisVersion row. The backfill records unresolved Proposal and owned analysis rows in `tenancy_backfill_exceptions` and never guesses.

The W1 manual price boundary remains unchanged.

## Source and World Bank boundary

`Tender` remains source opportunity authority. Pursuit commands have no write path to Tender, TenderDocument, Project, TenderProject, or ProjectRoleAssignment. Source deadline is returned separately from `internal_target_at`.

World Bank context continues through:

`OrganizationPursuit -> Tender -> TenderProject -> Project -> ProjectRoleAssignment`

Project and Leadership facts are not copied into Organization or Pursuit rows. Leadership does not create Memberships or any future Expert record. Procurement contacts remain source Tender metadata.

## Migration and preflight

Revision A creates Organizations, Memberships, lifecycle state types, and the persistent exception report; it backfills one exact Organization and ACTIVE OWNER per valid Company Profile. Revision B creates pursuits and the append only lifecycle ledger, maps valid Engagements, and reports unresolved Engagement, Proposal, and analysis ownership.

Both backfills use deterministic IDs, conflict safe inserts, exact UUID joins, and count reconciliation. The permanent PostgreSQL proof upgrades a seeded W1 database, fingerprints protected rows, downgrades to W1, reupgrades, and verifies stable IDs and unchanged legacy/source records.

The schema preflight now reports Organization, Membership, Pursuit, owner integrity, source integrity, duplicate source scopes, quarantine counts, legacy mappings, and compatibility only IDs using aggregate queries.

## Performance contracts

- Pursuit list: one set based page query plus one count query after fixed authentication/context queries.
- My Tenders: three set based queries, independent of page size.
- Tender Details: remains within the maintained fixed query budget and reads the pursuit overlay set wise.
- Organization membership lists and pursuit lists have bounded limits and no per row authorization queries.

The disposable release read proof measured the complete HTTP request budgets as follows:

| Route | Measured queries | Budget | Result |
|---|---:|---:|---|
| `GET /api/v1/pursuits` | 4 | 8 | PASS |
| `GET /api/v1/my-tenders` | 8 | 10 | PASS |
| Tender Details | 17 | 17 | PASS |

## Permanent verification

`backend/test_w2_organization_pursuit_foundation.py` covers W1 upgrade, backfill, downgrade/reupgrade, source and history fingerprints, invitation, activation, roles, concurrent final owner protection, revoke transfer and unassignment, multi Organization context, source pursuit uniqueness, same UUID reopen, append only audit, legacy mapping, cross tenant denial, platform disable independence, and analysis revocation.

The existing release wrapper runs the W2 proof as part of the backend suite and retains migration, security, analysis, connector, performance, frontend, Chromium, and dependency gates.

## Measured release validation

Validation ran against pinned local dependencies with disposable PostgreSQL and Redis. It did not access or deploy to production.

| Gate | Result |
|---|---|
| Backend | PASS: 813 passed, 1 skipped, 100 subtests passed |
| Security | PASS: 118 passed |
| Analysis | PASS: 50 passed, 12 subtests passed |
| Connectors and communications | PASS: 198 passed, 1 skipped, 6 subtests passed |
| Migrations | PASS: clean bootstrap, exact head/current, check, preflight, W1 upgrade, downgrade/re-upgrade |
| Scale proof | PASS at 1,000, 10,000, and 100,000 seeded tenders with bounded query counts |
| Frontend | PASS: typecheck, lint, 247 tests, RTL audit, production build |
| Chromium | PASS: 145 of 145 cases |
| Dependencies/configuration | PASS: 24 tests, `pip check`, and `npm audit` with 0 vulnerabilities |
| Permanent release wrapper | PASS: all configured groups completed successfully |

The valid seeded W1 backfill produced zero quarantine rows. Invalid, missing, conflicting, or ambiguous legacy ownership is retained in `tenancy_backfill_exceptions`; no production data was inspected, so production exception counts remain intentionally unknown until an authorized migration rehearsal.

## W2 file inventory

The accepted W0/W1 changes remain in the same uncommitted working tree. The exact W2 touch set is:

- Repository visibility: `.gitignore`.
- Migrations: `backend/alembic/versions/20260925_0001_w2_organization_membership.py`, `backend/alembic/versions/20260925_0002_w2_organization_pursuit.py`.
- API and application wiring: `backend/app/api/deps.py`, `backend/app/api/endpoints/my_tenders.py`, `backend/app/api/endpoints/organizations.py`, `backend/app/api/endpoints/proposals.py`, `backend/app/api/endpoints/pursuits.py`, `backend/app/api/endpoints/tenders.py`, `backend/app/api/endpoints/users.py`, `backend/app/main.py`.
- Models and schemas: `backend/app/models/all_models.py`, `backend/app/models/base.py`, `backend/app/models/tenancy.py`, `backend/app/schemas/tenancy.py`.
- Services: `backend/app/services/analysis_aggregates.py`, `backend/app/services/bid_preparation.py`, `backend/app/services/explorer.py`, `backend/app/services/memberships.py`, `backend/app/services/my_tenders.py`, `backend/app/services/organization_context.py`, `backend/app/services/pursuit_lifecycle.py`, `backend/app/services/pursuits.py`, `backend/app/services/tender_engagements.py`.
- Migration, audit, and compatibility scripts: `backend/scripts/audit_sr2_1_semantic_batch.py`, `backend/scripts/audit_sr2_2_source_refresh_orchestration.py`, `backend/scripts/audit_sr2_3_connector_capability_document_decoupling.py`, `backend/scripts/audit_sr2_4_refresh_activity_source_catalog_newness.py`, `backend/scripts/run_s0_3_schema_data_preflight.py`, `backend/scripts/test_s0_5b3_migration.py`, `backend/scripts/test_s0_5b4_baseline.py`, `backend/scripts/test_s0_5b5_drift.py`, `backend/scripts/test_s1_2_project_enrichment.py`, `backend/scripts/test_s7_2_locale_migration.py`, `backend/scripts/verify_release_migrations.py`, `backend/scripts/verify_s10_5_communications.py`, `backend/scripts/verify_s1_1_project_foundation.py`, `backend/scripts/verify_s2_1_compliance_ownership.py`, `backend/scripts/verify_s2_2_analysis_version_foundation.py`, `backend/scripts/verify_s2_2b_analysis_aggregate_concurrency.py`, `backend/scripts/verify_s2_3_version_aware_compliance_reads.py`, `backend/scripts/verify_s3_3_privileged_account_survivability.py`, `backend/scripts/verify_s3_4_administrative_audit_hardening.py`, `backend/scripts/verify_s3_5_admin_operational_ux_hardening.py`, `backend/scripts/verify_s4_1_tender_engagement_foundation.py`, `backend/scripts/verify_s4_2_my_tenders_list_experience.py`, `backend/scripts/verify_s4_3_bid_preparation_reconciliation.py`, `backend/scripts/verify_s4_4_tender_engagement_workflow_ux.py`, `backend/scripts/verify_s5_2_tender_details_read_model.py`, `backend/scripts/verify_s6_2_unified_explorer_backend.py`, `backend/scripts/verify_wb_project_enrichment_autodrain.py`.
- Tests: `backend/test_release_reads.py`, `backend/test_release_security.py`, `backend/test_release_uploads.py`, `backend/test_s0_3_schema_data_preflight.py`, `backend/test_s0_5b1_unknown_actionability.py`, `backend/test_s0_5b3_tender_recommendation_migration.py`, `backend/test_s0_5b4_baseline_bootstrap.py`, `backend/test_s0_5b5_alembic_drift.py`, `backend/test_s13_on_demand_tender_attachments.py`, `backend/test_s1_1_project_foundation.py`, `backend/test_s1_2_world_bank_project_enrichment.py`, `backend/test_s1_3b_project_context_runtime_recovery.py`, `backend/test_s1_access_hardening.py`, `backend/test_s2_1_compliance_ownership.py`, `backend/test_s2_2_analysis_version_foundation.py`, `backend/test_s2_2b_analysis_aggregate_concurrency.py`, `backend/test_s4_1_tender_engagement_foundation.py`, `backend/test_s4_2_my_tenders_list_experience.py`, `backend/test_s4_3_bid_preparation_reconciliation.py`, `backend/test_s4_4_tender_engagement_workflow_ux.py`, `backend/test_s6_2_unified_explorer_backend.py`, `backend/test_s6_4_hunter_retirement_final_qa.py`, `backend/test_s8_2_analysis_language.py`, `backend/test_s8_3_arabic_ui_locale.py`, `backend/test_sr2_3_connector_capability_document_decoupling.py`, `backend/test_w2_organization_pursuit_foundation.py`, `frontend/tests/release-hardening-browser.py`.
- Documentation: `docs/W2_ORGANIZATION_PURSUIT_FOUNDATION.md`, `docs/audits/w2/migration-backfill-report.md`, `docs/audits/w2/tenant-isolation.md`, `docs/audits/w2/membership-owner-rules.md`, `docs/audits/w2/legacy-compatibility.md`, `docs/audits/w2/world-bank-preservation.md`, `docs/audits/w2/w3-private-document-contract.md`.

Detailed evidence:

- [Migration and backfill](audits/w2/migration-backfill-report.md)
- [Tenant isolation](audits/w2/tenant-isolation.md)
- [Membership and owner rules](audits/w2/membership-owner-rules.md)
- [Legacy compatibility](audits/w2/legacy-compatibility.md)
- [World Bank preservation](audits/w2/world-bank-preservation.md)
- [W3 private document contract](audits/w2/w3-private-document-contract.md)
