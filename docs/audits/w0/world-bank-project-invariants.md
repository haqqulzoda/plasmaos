# W0 World Bank Project Context and Leadership invariants

## Current end-to-end path

1. `backend/app/services/tender_sources/world_bank.py` reads official procurement notices (`/api/v2/procnotices`), normalizes a shared Tender with `source_system=world_bank`, external notice ID, source URL and raw metadata. The connector calls `link_tender_to_project` from its persistence path when a valid source project ID is present.
2. `backend/app/services/projects.py` validates and normalizes the source-native project ID, upserts `Project` under unique `(source_system, external_project_id)`, and records a one-per-Tender `TenderProject` link with method, source field/value, URL and observed timestamp. Invalid/ambiguous IDs yield no link; no fuzzy match.
3. `backend/app/services/world_bank_projects.py` fetches one known ID from the official Projects API (`https://search.worldbank.org/api/v2/projects`, `rows=1`), verifies response identity, and normalizes project name, country, region, status, approval/closing dates, borrower, implementing agencies, source URL, source update time and raw record. Project detail URL is retained or formed from the official project-detail route.
4. `backend/app/services/project_enrichment.py` conservatively merges nonempty facts into `Project`, stores fields obtained/missing and raw source provenance, and reconciles `ProjectRoleAssignment` under source/person/native-role hash. Existing current roles end only when the source roster is complete. An incomplete roster sets `partial` and preserves unobserved current roles; source failure only updates status/failure class and retains prior facts.
5. `backend/app/workers/project_enrichment_tasks.py` runs bounded per-Project enrichment with a 7-day freshness window and 30-minute active lease. Task rate limit is 30/minute, three retries for classified transient errors, 60/90-second soft/hard limit. Beat dispatches eligible backlog every configured 60 seconds; default batch 25, capped at 30 (and internal maximum 50), on the `celery` queue. The client performs one request per Project, 20-second default timeout clamped to 60 seconds. General source refresh is not in Beat’s schedule.
6. `/api/v1/tenders/{tender_id}/project` returns Project plus current and historical roles. `/api/v1/tenders/{tender_id}/details` uses a separate Project query and bounded Leadership query (12 returned, total/truncated count) and distinct Procurement Contacts section. `frontend/app/dashboard/tenders/[tenderId]/page.tsx` renders Project Context and source-backed Leadership; `frontend/lib/projectLeadership.ts` controls labels without turning `teamleadname` into an invented Task Team Leader title.

World Bank notice pagination defaults to 100 rows × 25 pages with 0.25-second request spacing, 30-second timeout and two retries (`WorldBankSyncConfig`). These are connector defaults, not proof of actual production settings. Project facts include source freshness status/history, while general notice amendment history is not a first-class immutable NoticeVersion.

## Leadership boundary

The current official Projects API source field is `teamleadname`. Its native role is stored literally as `teamleadname`; exact role mapping only recognizes explicit “task team leader”, “co-task team leader”, and “task manager” terms. Thus `teamleadname` maps to `OTHER_PROJECT_ROLE`, preserving the name and source field without inventing a title. Source person ID, email, phone and document ID remain null when absent. Role provenance includes endpoint, source URL, project ID, field, raw value, observed name and retrieval time. Procurement Contacts are extracted separately from procurement notice contact fields, stored in source metadata, and projected as `TENDER_SOURCE`. They are not ProjectRoleAssignment records. Neither class is an Expert candidate.

## Target preservation proof

`OrganizationPursuit.source_tender_id (nullable) -> Tender.id -> TenderProject.project_id -> Project.id -> ProjectRoleAssignment.project_id`. Project Context and Leadership reads continue through this source path for source-linked pursuits. Uploaded pursuits have no source path unless a user explicitly links a verified source Tender; private upload does not create or edit shared Project facts. Do not copy project fields or roles into private pursuit columns as the authority. Optional display snapshots must carry source identity, provenance and freshness, and never overwrite shared records.

Permanent tests required for W2/W3 and future source refresh:

- A source-linked World Bank pursuit preserves exact Tender→Project link and Project Context fields/provenance after organization migration.
- Current and historical Leadership remain available, with native `teamleadname` and no invented role/title, email or person identity.
- Procurement Contacts remain a separate Tender section and never populate Project Leadership; Leadership never auto-populates Expert or CandidateMatch.
- Uploading private RFP/CV/clarification to a pursuit leaves Tender, TenderDocument, Project, TenderProject and ProjectRoleAssignment unchanged.
- Partial/incomplete roster and fetch failure retain valid prior metadata and roles, expose truthful freshness/failure state, and do not silently mark roles ended.
- Query caps and total/truncated metadata survive the new route; source-only and private-only authorization cases are tested.

Evidence: [notice connector](../../../backend/app/services/tender_sources/world_bank.py), [project link service](../../../backend/app/services/projects.py), [Projects API client](../../../backend/app/services/world_bank_projects.py), [merge](../../../backend/app/services/project_enrichment.py), [worker](../../../backend/app/workers/project_enrichment_tasks.py), [Details projection](../../../backend/app/services/tender_details.py), [DTO](../../../backend/app/schemas/tender_details.py), [UI](../../../frontend/app/dashboard/tenders/[tenderId]/page.tsx).
