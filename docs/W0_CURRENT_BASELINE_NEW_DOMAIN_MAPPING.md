# W0 — Current baseline and new-domain mapping

Audit date: 2026-09-25. Scope: local repository and configured local evidence only. This is an architecture decision record; no product implementation, migration, production access, deployment, or data deletion occurred. Detailed evidence: [working tree](audits/w0/current-working-tree.md), [domain map](audits/w0/domain-map.md), [routes](audits/w0/route-map.md), [migration risks](audits/w0/migration-risk-map.md), [AI pricing](audits/w0/ai-pricing-removal-manifest.md), [World Bank invariants](audits/w0/world-bank-project-invariants.md).

## 1. Status and authoritative baseline

W0 audit completed against `/mnt/d/projects/plasmaos`, branch `main`, HEAD `122e50b05760e3740845a744057cb6f2b4a11816`. The initial tracked working tree was clean: zero staged, unstaged, or untracked visible files. This does **not** mean HEAD contains all accepted work: the ignored `docs/` tree held 873 documentation/evidence files, including previous release and diagnostic records. The exact ignored-doc path manifest is in the working-tree appendix. W0 adds this report, six appendix files and narrow `.gitignore` exceptions so the audit is visible; it does not modify application code.

The accepted implementation at this path includes source registry/refresh, World Bank Project enrichment/Leadership, immutable AnalysisVersion, account/release security, communications outbox, passive competitor intelligence, on-demand source attachments, and Sprint 14 customer UI. Commit history alone was not used to infer release acceptance.

## 2. Deployment baseline

| Fact | Classification | Evidence and limit |
|---|---|---|
| Local checkout is the SHA above | CONFIRMED | `git rev-parse HEAD`. |
| Compose release script defaults `PLASMA_BUILD_SHA` to checkout HEAD; release metadata exposes build SHA/time and DB Alembic revision | CONFIRMED for configuration | `scripts/compose-release.sh`, `backend/app/core/release.py`; this does not establish an actual deployment. |
| Compose defines backend/frontend, PostgreSQL, Redis, general/AI worker, heavy download worker and Beat | CONFIRMED for configuration | `docker-compose.yml`. |
| Actual deployed commit/build, DB revision, flags, whether deployment differs from this checkout | UNKNOWN | No authorized production evidence was accessed. No live endpoint/container was queried. |
| A local `.env` exists, with an `ENVIRONMENT` key | CONFIRMED for local configuration only | Values and secrets were not copied into this report; local values do not prove production configuration. |

Release settings require HTTPS CORS and strong explicit secrets in production/release, and reject auto-table creation, OCR bypass and pseudo locale flags. Compose defaults `ENVIRONMENT` to production. The only explicit application feature switch inspected is pseudo locale; source availability/refresh capability comes from the source registry and request options, not a known deployment flag. General scheduled source refresh is **not** in the present Beat schedule; World Bank Project enrichment backlog is scheduled. Treat active runtime flags and release identity as unknown until an authorized deployment inventory is supplied.

## 3. Alembic and dependencies

`alembic heads` reports one repository head: `20260912_0001_s10_5_communications`. The graph is one linear chain from `20260227_0001_google_oauth_cutover` through multi-source Tender, source jobs, Project/Leadership, analysis ownership/versioning, Engagement, refresh leases/metrics, localization/language, and communications; full revision order is in the working-tree appendix. The **database** Alembic revision is unknown; W0 did not connect to a deployment DB.

Backend declares Python 3.12+ in `backend/requirements.txt`; this environment has Python 3.12.3. `backend/constraints.txt` pins the resolved package set and `requirements-test.txt` adds pytest. Frontend uses `frontend/package.json` and `package-lock.json`: Next 16.3.4, React 19.2.3, TypeScript 5.x, and NextAuth 5 beta. Node modules are present; native WSL `node` is absent, while the locally installed Windows Node is v22.15.0. Docker images are PostgreSQL 16 and Redis 7 Alpine.

## 4. Current domain architecture

The current authority graph is `User -> CompanyProfile -> readiness/credentials/recommendations`, with `User + CompanyProfile + Tender -> TenderEngagement`, and a separate `User + Tender -> Proposal`. `Tender` is shared source data; `Tender -> TenderProject -> Project -> ProjectRoleAssignment` is shared Project intelligence. `TenderAnalysis` is owned by user/profile (or quarantined legacy) and required Tender; immutable `AnalysisVersion` records execution snapshots and source document observations. Communications use per-user NotificationDelivery with a small transactional outbox. All current persistent authorities, API/UI consumers, and migration sensitivities are inventoried in the domain map.

There is no Organization, Membership, private tender workspace, partner Firm, Expert, CVVersion, Availability, Commitment, TeamScenario, Task, or versioned private document authority in the inspected ORM. Competitor/historical participant data is intelligence, not a person or candidate authority.

## 5. Tender → SourceOpportunity

**Decision: retain `Tender` as the shared SourceOpportunity authority and use a product/API alias.** Its source/external unique key, canonical source key, URL, dates/status, budget, source-specific JSON, shared documents, refresh updates, and Project link already establish a cross-tenant source entity. Renaming the table would threaten UUID foreign keys, APIs, tests, deep links and accepted source flows without adding semantics.

Additions required later: immutable `NoticeVersion`/amendment observation with source timestamps/content hash; explicit source freshness and change events; stable version selection for source documents; package/lot identity where a connector supplies it. `last_synced_at`, mutable metadata and document SHA-256 do not amount to a complete notice amendment history. Do not attach organization-private notes or uploads to Tender/TenderDocument. Retain `Tender.status` as source lifecycle, distinct from pursuit status.

## 6. TenderEngagement → OrganizationPursuit

**Decision: create an additive OrganizationPursuit root, backfill Engagements, and wrap old APIs for finite compatibility.** Engagement requires a user, that user's profile, and a Tender. Its uniqueness and My Tenders projection are tied to that tuple. It has no document collection, owner/deadline, participant team, or upload origin. In-place extension would change its ownership and required Tender constraints while breaking current reads. Keeping it as a permanent subordinate status record would create two lifecycle authorities. The three options and comparison are in the migration-risk map.

Target pursuit has organization FK, optional source Tender FK, explicit source/upload origin, internal owner/deadline/status, and private workspace relations. Backfill maps each existing Engagement UUID to one Pursuit UUID; preserve the old ID in a unique compatibility mapping. Existing Engagement status (`SAVED`, `EVALUATING`, `PREPARING`, `SUBMITTED`, `WON`, `LOST`, `DISMISSED`) is source of the initial pursuit state only. Normal transitions move saved/evaluating/preparing among preparation states, preparing to submitted, submitted to won/lost, and dismissed back to active; outcome corrections are separate explicit commands. No passive GET creates pursuit or proposal.

## 7. Organization and membership

`CompanyProfile.user_id` is unique and required. API ownership comes from authenticated user ID and profile lookup, not from company text; Engagement enforces the profile/user tuple with a composite FK. Platform user approval/disable/auth-version and company approval/pilot status are separate access gates. There is no shared team or membership model. User deletion currently cascades to profile and Proposal; some other records restrict or quarantine ownership, so account deletion cannot simply define future organization retention.

Safe migration: create one organization and owner membership per existing profile, preserving exact user/profile mapping; create a new organization for accounts without a profile only after an explicit onboarding decision. Do not merge accounts by email domain, similar name, INN, or profile text. Add explicit invitation/acceptance and membership revocation; retain platform and company approval rules as separate checks. Backfill owned rows only after organization mapping is verified. Choose policy for multiple organizations and account deletion before W2 writes.

## 8. Public/private document boundary

| Current class/path | Classification | Boundary conclusion |
|---|---|---|
| `TenderDocument` source metadata, acquired bytes, parsed text, source URLs | SHARED SOURCE where source provenance is valid; ambiguous older rows are LEGACY / AMBIGUOUS | Details projection hides rows without trustworthy source URL/type. Approved-user download has Tender access check and normalized local storage path. It must never receive private RFP/CV/clarification. |
| `TenderSyncJob` | SYSTEM GENERATED job for shared-source acquisition | Requesting user is not the owner of acquired public bytes. |
| Proposal `/upload-tz` PDF and `structured_data.uploaded_tz_text/path` | USER PRIVATE legacy | Stored under local `backend/uploads/{user_id}`; no DocumentVersion or organization owner. A real preview mismatch exists: upload saves a random UUID filename/path, while preview reads `{proposal.id}.pdf`; new uploads can fail preview. |
| Readiness `optional_file_url`, certification/license/financial records | ORGANIZATION PRIVATE target; presently user-profile metadata | URL/title/status is not verified proof; no managed upload/hash/version on the readiness row. |
| AnalysisVersion snapshots/extracted text | SYSTEM GENERATED, private to owning user/profile | Preserve exact-version reads and hashes; do not expose storage references or extracted private text through shared Tender APIs. |
| Proposal PDF/DOCX/export and `final_pdf_url` | SYSTEM GENERATED, private to Proposal owner | Historical artifacts need authenticated pursuit/member access and provenance. |

Future invariant: `SourceOpportunity documents != OrganizationPursuit private documents`. Source-linked pursuits select official source document versions into an analysis pack; organization uploads remain separate immutable private versions. A private upload cannot update Tender, TenderDocument, Project, or source refresh state. Object storage and signed URL decisions are pending, but every preview/download/parse/export must recheck organization membership and document classification.

## 9. AnalysisVersion → AnalysisRun

`TenderAnalysis` is the logical parent; `AnalysisVersion` already supplies immutable numbered execution, supersedes link, input/output/evidence/document-set/version hashes, model/provider/prompt/schema/pipeline metadata, tender/company/result/evidence/provenance snapshots, analysis language, completeness and timestamps. `AnalysisVersionDocumentSnapshot` records source document identity, hash, storage reference/version and observation times. Exact version reads and exports are established behavior; legacy analyses without proven owner are quarantined. `RiskOverrideLog` is an append-only user/Tender/analysis liability action.

Reuse this versioning authority for source-linked historical runs through an AnalysisRun adapter. Add pursuit/organization scope, explicit private `DocumentVersion` input links, company/evidence version references, stable Requirement/Position IDs, reviewed Gap/Assertion records and run-level failure/attempt state. Historical version rows remain immutable; new versions must seal all selected source/private inputs and language. Overrides need actor, pursuit, exact analysis version, old/new review state and audit chain. Do not reinterpret old `TenderRequirement` taxonomy links as complete extracted requirements.

## 10. Readiness Vault → evidence service

Profile, certifications, licenses, financial history and readiness rows provide a useful metadata seed. Readiness rows keep ID on PUT but can be deleted; the `/vault` PUT deletes and recreates certification/license/financial child IDs, breaking stable references. `optional_file_url` is not hash-backed proof; statuses such as `available` can be user assertions. Migrate as `UNVERIFIED` claims unless a file, version, provenance and review prove them. Preserve legacy ID mapping and expiry/service/category metadata. Add EvidenceRecord → immutable EvidenceVersion → Assertion; replace destructive collection updates with versioned changes before analyses cite records. Company Profile and Vault can share one **organization-scoped evidence service** while retaining distinct presentation and provenance. Do not label a metadata title as verified evidence.

## 11. Proposal and Bid Preparation

Proposal is one-per-user/Tender with DRAFT/GENERATING/COMPLETED/SUBMITTED status, mutable `structured_data`, margin/VAT/currency, optional PDF URL and user/Tender ownership. Explicit Prepare Bid transaction creates or resolves Proposal plus Engagement; Proposal remains an artifact, not pursuit lifecycle. Bid Preparation lists Proposal records and detail uses Proposal UUID. The technical-task upload path stores local private PDF/text; AI draft and PDF/DOCX paths read mutable JSON, including prices. No artifact version, collaboration, pursuit owner or evidence-pack binding exists.

Keep Proposal UUIDs and legacy exports. Add pursuit FK and artifact versions after exact owner/Tender mapping; source-linked historical proposals resolve through mapped Engagement/Pursuit. Handle proposals with no Engagement explicitly instead of inventing prior intent. Redirect verified legacy detail links to pursuit Proposal tab. Upload-origin proposal creation requires pursuit association without Tender. W1 must remove active AI-derived pricing before this workflow is reused.

## 12. AI pricing

Active generation exists in the analysis prompt's `estimated_cost_breakdown`, strategic draft prompt/parser, `ai-draft` response/fallback/persistence, and `upload-tz` 75%-cost/85%-bid heuristics; UI displays and persists the suggested value; export can reproduce it. Manual cost-plus-margin calculations are a separate user-input path. Historical analysis/Proposal snapshots and PDFs/DOCX may contain generated figures and must be classified without rewrite. The exact W1 path/test manifest is in the AI appendix.

## 13. World Bank Project Context and Leadership

Preservation is structurally possible through `OrganizationPursuit -> optional Tender -> TenderProject -> Project -> ProjectRoleAssignment`, with no copy into pursuit authority. The source connector, deterministic link, official Projects API normalization, provenance-backed role merge, current/historical status, freshness, failures, query caps, DTO and UI are traced in the World Bank appendix. The source field `teamleadname` is retained literally; it does not imply a Task Team Leader title. Procurement Contacts come from procurement notice fields and are separate from Project Leadership. Neither becomes Expert/CandidateMatch automatically. W2/W3 permanent regression tests are specified there.

## 14. Notifications and outbox

Reuse NotificationEvent's unique dedupe key, per-user NotificationDelivery/read state, committed NotificationOutbox, and Broadcast/frozen recipients. Existing template registry covers recommendation created, analysis completed, account approved, and document acquisition ready/partial/failed. It does **not** cover private upload completed/failed, analysis failed, refresh success with zero new, refresh partial/failure/recovery, missed schedules, document change, stale analysis, availability expiry, withdrawal, or proposal/task events. Add those with small ID-only payload contracts and explicit membership-scoped recipient selection. The outbox publishes after commit and Beat retries unpublished intents; broadcasts use a separate durable dispatch path. Current notification tenancy is per user, not organization.

## 15. Worker and queue map

Celery has `celery`, `ai_fast_queue`, and `heavy_dl_queue`. Compose's general worker consumes `celery,ai_fast_queue`; heavy worker consumes only heavy downloads with concurrency 1. Source refresh and World Bank Project enrichment run on `celery`; document acquisition/hydration/ADB enrichment run on heavy; Hunter runs on AI fast; communications default to general queue. Proposal AI draft and technical-task upload/parse/model operations execute in API requests, not a dedicated proposal queue. Therefore source I/O, communications and AI fast share one worker process pool, and proposal AI can occupy API capacity. Future pursuit analysis/upload needs its own bounded document/AI execution path; queue separation is justified before W3/W4, but no broad Celery refactor belongs in W0.

## 16. Routes and UI

The route appendix maps Dashboard, Explorer, Tender Details, My Tenders, Bid Preparation, Company Profile, Vault, Compliance, Notifications, Admin and legacy redirects. Opportunities can reuse Explorer and source Details; My Tenders becomes pursuit list; Company Profile/Vault become Company & Evidence; Compliance/Bid Preparation become pursuit tabs. Uploaded Tenders and Partners & Experts need new routes. Preserve source Tender, Engagement, Proposal and analysis deep links via explicit ID adapters. Navigation was not changed.

## 17. Security/privacy priorities

The migration-risk appendix classifies blockers. Before private upload: separate private document/version ownership, tenant-scoped storage/preview/download/parse/export, exact input-version binding, no private data through shared source records, and safe worker task authorization. Before external pilot: explicit membership/revocation, CV/PII/financial/partner sharing controls, cross-tenant enumeration tests, stable evidence history, and retention/deletion policy. Source refresh attempt/schedule observability can follow the pilot once basic correctness holds. Existing user/profile gates are valuable but are not organization authorization.

## 18. Migration and vertical slices

Use additive organization/membership mapping, pursuit root/backfill, private document versions, evidence versions, analysis extensions, proposal compatibility and redirects in that order. Backfills must be restartable and audited; temporary dual-read is acceptable, indefinite dual-write and table deletion are not. Dependency graph: W1 pricing/product truth and W2 organization/pursuit; W2 enables W3 uploads and W5 partner model; W3 enables full W4 analysis; W4 plus W6 participation enables W7 scenarios; W4/W7 enable W8 evidence pack. World Bank scheduled **source** refresh can be designed in parallel to private work while preserving shared facts; Project backlog scheduling already exists.

## 19. Reusable pieces and retirement candidates

Reuse Tender/source registry and refresh jobs, Project/Leadership, on-demand source document acquisition, immutable AnalysisVersion, readiness metadata, Proposal UUID/exports, account lifecycle/release security, notification/outbox, customer/admin design systems, and current passive intelligence. Retire the previous roadmap; later deprecate Engagement as canonical lifecycle, user-owned Proposal as workspace root, `upload-tz` as private tender intake, metadata-only “verified” wording, active AI price recommendation, and legacy bid/hunter route concepts after compatibility cutover. Do not delete their history in W0.

## 20. Known unknowns / founder decisions

- Whether an account can belong to multiple organizations and how ownership transfers when the sole owner leaves.
- Whether one source opportunity can have multiple pursuits per organization (e.g. lots/teams) and what counts as a unique pursuit.
- Private file storage/retention region, sharing/consent rules for CVs and partner notes, and deletion/export obligations.
- Manual commercial pricing policy after removal of AI bid-price generation.
- How to treat legacy Proposals without Engagement and ambiguous readiness file URLs.
- Production build SHA, schema revision and active feature flags; none were verified in W0.
- Source amendment versioning and scheduled refresh cadence/notification policy by connector.

These are explicit decisions, not reasons to infer organization membership or production state.

## 21. Recommended exact W1 scope

Remove active AI-derived bid pricing from prompt, service, fallback, upload-TZ, frontend suggestion and export auto-fill paths; distinguish source budget from user-entered commercial figures; preserve/label historical stored artifacts. Correct false verified-evidence language where metadata-only records are shown. Add focused negative tests for generated-price paths and truthful provenance, and write the W2 ownership/ID contract for approval. Do not start OrganizationPursuit migrations, Upload Tender, navigation changes, World Bank behavior changes, scheduled source refresh or deployment in W1 unless separately authorized.

## 22. Validation

- Repository Alembic head: one, as above. No DB revision was checked.
- Focused frontend Node tests: 42 passed (`project-context`, `my-tenders`, `bid-preparation`, Sprint 14.1 Dashboard); frontend TypeScript `tsc --noEmit` passed.
- Initial focused backend run: 54 passed, one parser failure and ten communications setup errors. Communications tests require an explicitly configured loopback PostgreSQL target and no disposable test DB was provided: **ENVIRONMENT**, not a proven product defect. The parser failure was caused by repository-root invocation; from `backend/`, the parser/upload suite passed 12/12 and the World Bank/AnalysisVersion/Engagement suites passed 43/43.
- The upload/preview filename mismatch described in section 8 is a **REAL CURRENT DEFECT** found by code trace. It was not repaired in this read-only audit.
- Full release gate was not run because an exact disposable release environment was not established. No unrelated failures were repaired.
