# W0 domain authority and target map

Evidence is the ORM under `backend/app/models/`, routers under `backend/app/api/endpoints/`, services under `backend/app/services/`, and customer pages under `frontend/app/dashboard/`. “Shared” means source or platform authority; it does not imply that all endpoints are anonymous. Mutation means current behavior, not a proposed permission.

## Current persistent authorities

| Current model/table | Owner and key relationships | Mutation, API and frontend consumer | Migration sensitivity |
|---|---|---|---|
| `User/users` | Account identity; one `CompanyProfile`; owns proposals, analyses, engagements, deliveries | OAuth and `/api/v1/users/me`; admin approval, disable, restore, `auth_version`; all customer pages | High: account ID is the current authorization root; deletion cascades to profile/proposals and delivery state. |
| `CompanyProfile/company_profiles` | Unique `user_id`; owns readiness, credentials, recommendations | `/users/me/company`, `/vault`; Profile, Vault, Compliance, Dashboard | High: a profile is one-user owned, even when its text describes a firm. Approval is a separate admin gate. |
| `Certification/certifications`, `License/licenses`, `FinancialHistory/financial_history` | Profile FK | `/vault` full replacement PUT; Profile/Vault/Compliance | High: replacement deletes and recreates IDs; these are claims/data, not file proof. |
| `ReadinessDocument/readiness_documents` | Profile FK; optional URL, no stored file-version FK | `/vault/readiness` CRUD; Vault/Compliance | High: PUT keeps ID, DELETE destroys record; `optional_file_url` alone is not verified file evidence. |
| `CompanyCredential/company_credentials` | Profile + `TaxonomyNode` | Compliance/readiness services; Compliance | Medium: credential claim is not an evidence version. |
| `TaxonomyNode/taxonomy_nodes` | Shared taxonomy | Compliance and admin data; Compliance | Medium: reusable category dictionary, not a pursuit requirement identity. |
| `Tender/tenders` | Shared source row; unique `(source_system, external_id)` and `canonical_source_key`; source URL, metadata, status, dates | Source refresh writes; `/tenders`, Explorer, Dashboard, Details, Compliance | Critical: preserve UUID and deep links. No organization owner. |
| `Project/projects` | Shared `(source_system, external_project_id)` | World Bank enrichment; `/tenders/{id}/project-context`, Details | Critical: Project Context and provenance stay source owned. |
| `TenderProject/tender_projects` | One link per Tender to Project, with provenance | Deterministic source linkage; Details | Critical: keep path from source Tender to Project. |
| `ProjectRoleAssignment/project_role_assignments` | Shared Project FK; source identity, native/canonical role, provenance, current/history timestamps | Enrichment merge; Project Context/Details leadership | Critical: cannot be merged into procurement contacts or Expert. |
| `TenderDocument/tender_documents` | Shared Tender FK; source URL, external file ID, storage path, SHA-256, parsed text and download status | Targeted acquisition; `/tenders/{id}/documents`, `/tenders/documents/{id}/download`; Details/Compliance | Critical: no tenant FK; never place private uploads here. No general version table. |
| `TenderSyncJob/tender_sync_jobs` | Requesting user + Tender; active-user/tender uniqueness | Targeted acquisition status; Details | Medium: user requester is not document owner. |
| `SourceRefreshJob/source_refresh_jobs` | Shared source-wide execution; requester optional | `/tenders/sources/*`, source activity, worker; Explorer/Dashboard/Admin | High: leased durable job and counters, but no separate durable attempt history. |
| `TenderEngagement/tender_engagements` | Required user + profile + Tender; composite profile/user FK; unique owner/Tender | `/my-tenders`, `/tenders/{id}/engagement`, transition service; My Tenders/Details | Critical: cannot represent shared organization or upload-origin pursuit without changing foundational constraints. |
| `Proposal/proposals` | Required user + Tender; unique user/Tender | `/proposals` CRUD, prepare, AI draft, upload-TZ, PDF/DOCX; Bid Preparation | Critical: separate artifact lifecycle and pricing fields; no pursuit FK. |
| `TenderAnalysis/tender_analyses` | Required Tender; owned `(user_id, company_profile_id)` or quarantined legacy null tuple | Analyze/read/export; Compliance/Details | Critical: legacy quarantine must stay inaccessible; required Tender blocks upload-only runs. |
| `AnalysisVersion/analysis_versions` | Immutable execution under TenderAnalysis; version sequence/supersedes; hashes and snapshots | Exact-version read, reanalysis, Compliance/Details/export | Critical: preserve IDs, hashes, language, provenance, immutable historical reads. |
| `AnalysisVersionDocumentSnapshot/analysis_version_document_snapshots` | Version FK, optional TenderDocument FK; identity, URL, hash, storage reference/version | Analysis history and export | High: source document snapshot can be reused, but private document version FK is absent. |
| `TenderRequirement/tender_requirements` | Shared Tender + taxonomy node | Legacy compliance taxonomy | Medium: not equivalent to extracted, versioned pursuit requirements. |
| `RiskOverrideLog/risk_override_logs` | User + Tender + optional TenderAnalysis + taxonomy node | `/tenders/{id}/override`; Compliance | High: append-only user action; target needs pursuit, analysis version and organization scope. |
| `TenderRecommendation/tender_recommendations` | Tender + profile, unique pair | Explorer/Dashboard recommendation projections | Medium: rekey to organization only after membership migration. |
| Competitor intelligence | Source metadata/cache and historical participant evidence, no candidate/expert authority | `/tenders/{id}/competitors`, targeted refresh; Details | Medium: Sprint 12R passive reads must stay passive. |
| `NotificationEvent/notification_events`, `NotificationDelivery/notification_deliveries` | Deduped event; per-user delivery/read state | `/notifications`; Notifications | High: explicit recipient selection required under memberships. |
| `NotificationOutbox/notification_outbox` | Committed per-user publication intent, IDs/small payload | Publisher worker | Medium: reuse transactional intent; prevent private content in payload. |
| `Broadcast/broadcasts`, `BroadcastRecipient/broadcast_recipients` | Admin authored, frozen user audience | `/admin/broadcasts`; Admin | Medium: platform broadcast remains distinct from pursuit activity. |
| `AuditLog/audit_logs`, `AdminActivityEvent/admin_activity_events` | Analysis hash chain and admin activity | `/audit`, `/admin/audit-events`; Admin | High: retain historical account/analysis audit across tenant migration. |

Sources: [ORM](../../../backend/app/models/all_models.py), [account and readiness ORM](../../../backend/app/models/company.py), [engagement ORM](../../../backend/app/models/engagement.py), [analysis ORM](../../../backend/app/models/audit.py), [communications ORM](../../../backend/app/models/communications.py), [taxonomy ORM](../../../backend/app/models/taxonomy.py).

## Target logical concepts: one decision each

“NEW” below is an additive target authority, not a W0 implementation. Existing source authority is reused wherever sound.

| Target concept | Decision | Existing reuse or additive need |
|---|---|---|
| Organization | NEW | One organization per existing profile initially; retain profile ID mapping, do not merge by name/email. |
| Membership | NEW | Explicit user to organization role/state. User approval remains platform access, not membership. |
| SourceOpportunity | KEEP | `Tender` is the shared authority, use a product alias; avoid table rename. |
| NoticeVersion | NEW | Add immutable source notice observations/amendments linked to Tender; `last_synced_at` and metadata are insufficient history. |
| OrganizationPursuit | NEW + MIGRATE | New organization-owned root with nullable Tender FK and origin; backfill from Engagement. |
| Document | EXTEND | Retain `TenderDocument` for shared source; add separate private document authority with owner/scope and classification. |
| DocumentVersion | NEW | Immutable bytes/hash, parse, and source/version metadata; source snapshots alone are not a live version authority. |
| AnalysisRun | WRAP FOR COMPATIBILITY + EXTEND | `TenderAnalysis`/`AnalysisVersion` underpin source-linked history; add pursuit scope and private input version links without rewriting versions. |
| Requirement | EXTEND | Reuse extracted version snapshot semantics; add stable run-scoped requirement rows/IDs. `TenderRequirement` remains taxonomy association. |
| Position | NEW | No required-position authority. |
| Firm | NEW | No partner-firm authority; CompanyProfile describes the tenant, not outside firms. |
| ProjectReference | NEW | Past project evidence for firm/expert, separate from shared source `Project`. |
| Expert | NEW | Consent and organization-scoped expert authority; never auto-import ProjectRoleAssignment. |
| CVVersion | NEW | Private DocumentVersion specialization/reference. |
| EvidenceRecord | EXTEND | Migrate eligible readiness/credential records into organization evidence with legacy ID mapping and proof state. |
| Assertion | NEW | Versioned claim with support link and review state. |
| Gap | NEW | Run/requirement-scoped derived and reviewed gap identity. |
| CandidateMatch | NEW | Evidence-backed proposed fit; no historical participant auto-candidate. |
| TeamScenario | NEW | Pursuit-owned scenario and revision. |
| Contribution | NEW | Scenario contribution by firm/expert and position. |
| Availability | NEW | Time window and source/consent on private participant. |
| Commitment | NEW | Explicit participation decision/terms; distinct from availability. |
| RelationshipHistory | NEW | Private, access-controlled firm/expert interaction history. |
| Task | NEW | Pursuit-owned assigned work item. |
| ProposalArtifact | EXTEND + MIGRATE | Keep Proposal IDs/exports for source-linked legacy; add pursuit FK and immutable artifact versions/evidence pack. |
| RefreshRun / Attempt | EXTEND | Reuse SourceRefreshJob as run; add attempt history and schedule/missed-run metadata if needed. |
| Notification / OutboxEvent | KEEP + EXTEND | Reuse Event/Delivery/Outbox; add strict event contracts and organization-safe recipients. |

## Core ownership rule

`Organization -> Membership -> OrganizationPursuit -> private documents / analyses / evidence selections / people / tasks / proposal`. The optional `OrganizationPursuit.source_tender_id -> Tender -> TenderProject -> Project -> ProjectRoleAssignment` path is read-only for private work. A private upload must never write Tender, TenderDocument, Project, or ProjectRoleAssignment.
