# Sprint 4.2 — My Tenders List Experience

## 1. Previous Customer Surface

| Surface | Current route | Current data source | Current label | Relation to My Tenders | Decision |
|---|---|---|---|---|---|
| Dashboard | `/dashboard` | Tender and analysis summary APIs | Dashboard | General landing page, not an engagement ledger | Keep; defer engagement cards |
| Tender Explorer | `/dashboard/tenders` | Tender APIs | Tenders | Discovery surface and route into Tender Details | Keep |
| Tender Details | `/dashboard/tenders/[tenderId]` | Tender, Project, document, and Compliance APIs | Tender Details | Smallest legitimate explicit save entry point | Modify only with Save to My Tenders |
| My Bids | `/dashboard/bids` | Proposal API (`/proposals`) | My Bids | Legacy Bid Preparation artifacts, not engagement authority | Keep unchanged through Sprint 4.3 |
| Proposal detail | `/dashboard/bids/[id]` | Proposal API | Proposal workspace | Bid Preparation artifact only | Keep; no engagement inference |
| Hunter | `/dashboard/hunter` | TenderRecommendation API | AI Hunter | Discovery/recommendation surface only | Keep separate |
| My Tenders | `/dashboard/my-tenders` | TenderEngagement API | My Tenders | Canonical customer pursuit list | Add |

The temporary navigation policy exposes both **My Tenders** and **My Bids**. Their distinct names and routes preserve the product boundary until the separately authorized Sprint 4.3 cleanup.

## 2. My Tenders Authority

`TenderEngagement` is the sole membership authority. A row appears if and only if the authenticated user's exact `(user_id, company_profile_id)` scope owns a canonical engagement for the Tender and the requested filters include it. Proposal, Compliance, TenderAnalysis, Recommendation, Hunter, Project linkage, PDF creation, deadline, and source status are never membership fallbacks.

## 3. List API

- `GET /api/v1/my-tenders` returns the bounded list, filtered total, owner-wide engagement status counts, and pagination metadata.
- `GET /api/v1/my-tenders/{engagement_id}` returns one owner-scoped engagement with its safe Tender summary; an unknown or foreign ID is `404`.
- `GET /api/v1/tenders/{tender_id}/engagement` answers whether the current owner already has an engagement without creating one.
- `POST /api/v1/tenders/{tender_id}/engagement` is the explicit Save command.

All four endpoints require the current authenticated account and the existing approved-pilot access dependency.

## 4. Ownership

Every list, Tender-scoped read/save, and direct-ID read uses both the authenticated `user_id` and the current `CompanyProfile.id`. Profile lookup is by `CompanyProfile.user_id`, never company display name, email, Proposal ownership, or an administrator-selected customer. Platform administrators receive no implicit customer-data backdoor.

The PostgreSQL proof used two companies with the same display name and showed isolated lists. A cross-tenant direct engagement UUID returned no row.

## 5. Response Contract

The customer-safe list item exposes:

- `engagement_id`, `tender_id`, `engagement_status`, `engagement_origin`, `engagement_created_at`, and `status_changed_at`;
- Tender title, buyer, source, source Tender status, deadline, value, currency, notice type, procurement method, country, and region;
- optional canonical Project external ID, name, source, and enrichment status.

It does not serialize an ORM object and does not expose another tenant's IDs, lock/version fields, storage paths, authentication versions, Proposal content, or Compliance evidence.

## 6. Engagement vs Tender Status

The API names the fields `engagement_status` and `tender_status`. The UI renders visibly labeled badges such as **Engagement: Preparing** and **Tender: Closed**. The two concepts never share a generic `status` property or an unlabeled color badge.

Tender status drift, deadline expiry, or cancellation does not mutate or remove the engagement.

## 7. Default Scope

The default `status=ACTIVE` scope contains `SAVED`, `EVALUATING`, `PREPARING`, `SUBMITTED`, `WON`, and `LOST`. It excludes but never deletes `DISMISSED`. `status=ALL` includes every canonical status; `status=DISMISSED` shows only dismissed rows. Owner-wide counts remain truthful regardless of the active list filter.

## 8. Filters

The API and UI support `ACTIVE`, `ALL`, and each of the seven canonical engagement statuses. Narrow optional Tender filters support canonical source and source-side Tender status. Filter state is stored in URL query parameters, including page, so reload and browser back/forward behavior is deterministic.

## 9. Search

`search` performs an escaped, case-insensitive database search over Tender title and buyer/procuring entity only. It does not search Proposal data, private documents, Compliance evidence, or recommendations.

## 10. Sorting

The default `recently_updated` order is `status_changed_at DESC, engagement_id DESC`. `recently_added` uses `engagement_created_at DESC, engagement_id DESC`. `deadline_soonest` uses Tender deadline ascending with null deadlines last and engagement ID as a stable tie-breaker. Sorting is performed by PostgreSQL, not by the current client page.

## 11. Pagination

The contract uses offset/limit pagination. The UI requests 25 rows. The API defaults to 25 and enforces `1 <= limit <= 100` and a non-negative offset. The 150-row fixture verified bounded, deterministic, non-overlapping pages.

## 12. Counts

Counts are derived only from `TenderEngagement`, grouped by canonical engagement status for the exact owner tuple. The response includes `all`, `active`, and each status. Search/source filters affect `total` for the current result set but do not make the owner-wide status tabs misleading. Proposal-only fixtures contribute zero.

## 13. Project Context

The list left-joins the canonical TenderProject/Project association in the page query. When available, it displays a small Project signal. Project enrichment may be pending or Project context may be absent; either case leaves the Tender row usable and never becomes a blocking page state. The World Bank pending-enrichment browser case passed.

## 14. Explicit Save

Tender Details renders **Save to My Tenders**. On mount, the component only performs the narrow read. It sends the save `POST` solely from the button click handler. Passive Explorer, Tender Details, Proposal, Compliance, and recommendation reads cannot invoke creation.

New rows use `SAVED` with origin `MANUAL_SAVE`.

## 15. Idempotency

Save delegates to the Sprint 4.1 canonical uniqueness tuple and PostgreSQL conflict-safe creation. Concurrent saves for one owner/Tender produced one row, returned no server error, and kept deterministic `SAVED` / `MANUAL_SAVE` state. Re-saving `SAVED`, `EVALUATING`, `PREPARING`, `SUBMITTED`, `WON`, or `LOST` returns the existing row without a downgrade.

## 16. Dismissed Re-engagement

An explicit Save of a `DISMISSED` row transitions the same canonical row to `SAVED` through the Sprint 4.1 lifecycle service. It does not insert a second row. The concurrency-safe reread accepts another request that completed the same re-engagement first.

## 17. Proposal Separation

The My Tenders route calls only `/my-tenders`; it never loads `/proposals`, merges Proposal data, or falls back to My Bids. Backend list joins start at `TenderEngagement` and `Tender`, with optional Project context only.

Static tests and source scans found no Proposal, TenderAnalysis, Recommendation, or Hunter fallback in the My Tenders list path.

## 18. Legacy Proposal Behavior

A Proposal-only Tender is absent from My Tenders and remains available in legacy My Bids. In the mixed fixture—Proposal-only A, engagement-only B, and Proposal-plus-engagement C—My Tenders returned B and C exactly once and omitted A. Sprint 4.2 performs no Proposal reconciliation or backfill.

## 19. Security

Approved accounts receive normal owner-scoped access. Pending, rejected, disabled, and stale/revoked sessions remain denied through the Sprint 3 access dependencies and session checks. Direct foreign engagement IDs use the repository anti-enumeration convention (`404`). Safe response schemas exclude private/internal data. The browser stale-session case and focused Sprint 3 security regressions passed.

## 20. Query Performance

The representative PostgreSQL 16 fixture contained 150 engagements across all statuses, sources, deadlines (including nulls), and Project states. One list request issued exactly three fixed SQL statements: page data, filtered total, and owner-wide counts. Tender and Project context use joins, so query count does not grow with a 25-row page.

Measured result on the disposable acceptance database: **140.332 ms**, **3 SQL queries**, query plan root **Limit**, **no N+1**. The existing unique index on `(user_id, company_profile_id, tender_id)` provides an owner-prefix path and enforces Tender uniqueness; existing status and foreign-key indexes were sufficient at this measured scale. No new index or Sprint 4.2 migration was justified.

## 21. Browser Acceptance

Real Chromium acceptance passed **15/15**:

1. truthful empty My Tenders;
2. explicit Save creates a row;
3. duplicate Save creates no duplicate;
4. PREPARING plus Save does not downgrade;
5. DISMISSED plus Save re-engages as SAVED;
6. status filtering;
7. dismissed default/filter behavior;
8. title/buyer search;
9. pagination;
10. Tender OPEN to CLOSED without engagement mutation;
11. Proposal-only Tender absent;
12. mixed legacy/new fixture;
13. same-name tenant isolation;
14. World Bank pending Project context renders;
15. expired/stale session denial.

The acceptance run used the actual Next.js route, Auth.js session/middleware behavior, and Chromium against a deterministic mock API boundary. Backend semantics, SQL, concurrency, and tenant isolation were separately proven against disposable PostgreSQL 16.

Quality/regression evidence:

- Sprint 4.2 + Sprint 4.1 focused static/contract suite: 20 passed.
- Sprint 4.2 PostgreSQL acceptance: clean; 150 rows; all list, security, legacy-separation, and save/concurrency assertions passed.
- Sprint 4.1 PostgreSQL regression: fresh and representative existing-database paths clean; zero engagement backfill; business counts preserved.
- Sprint 3 focused: 54 tests and 54 subtests passed.
- Sprint 2 focused: 52 passed.
- Sprint 1/World Bank focused: 51 passed (one existing Alembic deprecation warning).
- Connector gate: 195 passed, one approved fixture skip, four subtests passed.
- Frontend: TypeScript passed; six focused tests passed; production build passed; ESLint had zero errors and zero new warnings (15 pre-existing warnings remain).
- Alembic repository head/check: `20260828_0003_s4_1_tender_engagement_foundation`, clean on disposable fresh and existing upgrade paths.

The configured local development database was inspected read-only and remains at Sprint 3 head `20260828_0002_s3_4_admin_audit_hardening`; it was intentionally not migrated or mutated. The disposable existing-database upgrade proof reached Sprint 4.1 head cleanly and preserved its business rows.

## 22. Deferred Sprint 4.3 / 4.4 Work

Sprint 4.3 retains ownership of Proposal integration and naming/route cleanup: My Bids replacement/removal, legacy Proposal reconciliation, Proposal route changes, comprehensive Bid Preparation naming, dual Proposal/Tender route semantics, and explicit Proposal creation-to-PREPARING integration.

Sprint 4.4 retains ownership of the full engagement workflow UX: preparing/submitted/won/lost/dismiss/correction controls, workflow actions across Tender Details, and broader polish.

No Sprint 4.3/4.4 work, deployment, or production access was performed.
