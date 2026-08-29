# Sprint 5.4 — Tender Details Final Cleanup

Status: complete. This closeout is limited to Sprint 5.4 customer-surface cleanup, passive-read hardening, and regression QA. It does not start Sprint 6 and does not include deployment.

## 1. Legacy Surface Inventory

| Path or component | Consumers before cleanup | Behavior / identifier | Side effect | Replacement | Disposition |
| --- | --- | --- | --- | --- | --- |
| `/dashboard/bids` | Historical bookmarks | Duplicate/legacy list | Previously a competing surface | Bid Preparation list | Permanent redirect |
| `/dashboard/bids/[id]` | Historical Proposal bookmarks | Owned Proposal ID only | One ownership-validating GET; no writes | Bid Preparation detail | Retained compatibility validator |
| `/dashboard/proposals` | Historical bookmarks | Duplicate/legacy list | None required | Bid Preparation list | Permanent redirect |
| `/dashboard/workspace` | Historical bookmarks | Obsolete workspace entry | None | Tender Explorer | Permanent redirect |
| `TenderWorkspace` | No runtime import or route | Legacy combined workbench | Contained old workspace behavior | Tender Details, Compliance, Bid Preparation | Deleted |
| `StrategyPanel` | `TenderWorkspace` only | Dead experimental strategy/audit UI | Included obsolete audit action | Canonical Sprint 5 surfaces | Deleted |
| `HighlightedText` | Deleted workspace only | Workspace presentation helper | None | Current Compliance presentation | Deleted |
| `SaveToMyTendersButton` | No runtime import | Duplicate save control | Explicit POST when clicked | `TenderEngagementPanel` | Deleted |
| `ProjectContextSection` | Tests only after Sprint 5.3 consolidation | Duplicate Tender Details section | Reads duplicated data | Consolidated Tender Details | Deleted |
| Decision Snapshot / competitor client contracts | No runtime consumer | Dead client types/helpers | No current request | Consolidated Tender Details | Deleted from client |
| Decision Snapshot / competitor backend APIs | Backend tests and compatibility contract | API compatibility | Explicit reads only | Existing backend API | Retained |
| Bid Preparation mount sync | Bid Preparation detail page | Proposal ID page triggered Tender document sync | Enqueued source/network work and could mutate document state | Persisted Tender document GET | Removed from page load |

Static import, route, navigation, and test searches were performed before deletion. Shared `DocumentViewer` remains because Compliance still consumes it.

## 2. Final Canonical Route Map

| Surface | Canonical route | Dynamic identifier |
| --- | --- | --- |
| Tender Explorer | `/dashboard/tenders` | None |
| Tender Details | `/dashboard/tenders/{tender_id}` | Tender ID |
| Compliance | `/dashboard/tenders/{tender_id}/compliance` | Tender ID |
| My Tenders | `/dashboard/my-tenders` | None; engagement IDs remain API-internal |
| Bid Preparation list | `/dashboard/bid-preparation` | None |
| Bid Preparation detail | `/dashboard/bid-preparation/{proposal_id}` | Proposal ID |

## 3. Legacy Bids Policy

`/dashboard/bids` is a framework-level permanent redirect to `/dashboard/bid-preparation`. It performs no fetch, Proposal creation, engagement creation, sync, or enqueue. `/dashboard/bids/[id]` remains only for safe bookmarks: it validates the ID with owned `GET /proposals/{proposal_id}` and redirects only after success. It never treats the value as a Tender ID and has no get-or-create fallback.

## 4. Legacy Proposals Policy

`/dashboard/proposals` is a permanent redirect to `/dashboard/bid-preparation`. No duplicate Proposal list implementation remains.

## 5. TenderWorkspace Finding

`TenderWorkspace` was unreachable from canonical navigation and had no runtime consumer. Its useful concepts are already owned by Tender Details, Compliance, Bid Preparation, and My Tenders. Its only imported strategy UI was experimental and its document viewer is independently retained for Compliance.

## 6. StrategyPanel Finding

`StrategyPanel` was consumed only by the dead workspace. It combined obsolete strategy rendering with a non-canonical audit authorization action and demo identity. It represented neither the canonical Compliance workbench nor the canonical Proposal workflow, so it was deleted rather than relocated or redesigned.

## 7. Dead Component Removal

Deleted: `TenderWorkspace.tsx`, `StrategyPanel.tsx`, `HighlightedText.tsx`, `SaveToMyTendersButton.tsx`, and `ProjectContextSection.tsx`. Tests now assert the consolidated runtime owners. Static searches show no dangling runtime import, orphan navigation item, or orphan route link.

## 8. SaveToMyTendersButton Decision

The standalone component was unused and duplicated the explicit save behavior in `TenderEngagementPanel`. The canonical panel still performs `POST /tenders/{tender_id}/engagement` only from its Save button; its passive load performs only the engagement GET.

## 9. Decision Snapshot Client Cleanup

Unused client Decision Snapshot and competitor interfaces, labels, and presentation helpers were removed from `types/tender.ts`. Tender Details makes no Decision Snapshot or competitor request. Backend endpoints were retained because Sprint 5.4 is a customer-surface cleanup and API compatibility remains supported and tested.

## 10. Bid Preparation Document Sync Finding

The old Bid Preparation mount flow read sync status, called `POST /tenders/{tender_id}/sync-docs`, and polled the resulting job. The backend creates a `TenderSyncJob` and queues `process_tender_docs`; that worker may discover and fetch source documents, write `TenderDocument` state/files, and update compiled document text. Its purpose was source-document discovery plus legacy hydration, not Proposal rendering correctness. Repeated page visits could therefore enqueue or observe write-producing work.

## 11. Final Passive Bid Preparation Contract

Initial Bid Preparation rendering now reads the owned Proposal, Company Vault data, current engagement state, and already-persisted Tender documents. It never calls sync status or sync-docs, polls a job, fetches an external source, enqueues work, creates a Proposal/engagement/document, or changes domain timestamps. Generate Draft, Save Draft, Continue, Prepare, PDF, DOCX, document preview, and document download remain explicit click actions.

## 12. Document Sync Ownership

Source document discovery belongs to ingestion/connector infrastructure and its existing authorized backend job path. It is not owned by Bid Preparation page rendering. The compatibility API and worker remain available to supported infrastructure consumers; no new Refresh Documents button was invented merely to preserve the old mount behavior.

## 13. Passive Navigation Guarantee

Tender Details remains two domain reads: base Tender and details aggregate. Bid Preparation uses only persisted-state GETs on mount. Compliance retains its existing Tender, cached/latest analysis, evidence, document, readiness, and engagement reads; analysis creation and document preparation remain explicit. My Tenders is a portfolio GET. Redirect-only legacy routes perform no domain request, while legacy bid detail performs one ownership validation GET.

## 14. Route Identity

Tender Details and Compliance use Tender IDs. Bid Preparation uses Proposal IDs. My Tenders workflow APIs use engagement IDs internally while customer detail links use Tender IDs. Legacy bid detail is Proposal-ID-only compatibility. No dynamic route performs Proposal/Tender, Tender/engagement, or Analysis/Tender fallback interpretation.

## 15. Navigation

Canonical dashboard navigation exposes Tenders, My Tenders, and Bid Preparation. It does not expose My Bids, Tender Workspace, or Tender Draft. Removed surfaces have safe bookmark behavior where an unambiguous destination exists.

## 16. Terminology

Runtime copy audit found no canonical customer use of `My Bids`, `Tender Workspace`, `Tender Draft`, `Draft Tender`, `Submit Bid`, `Submit Tender`, `Fully compliant`, or `Ready %`. Proposal `DRAFT` remains a truthful artifact status where applicable.

## 17. Deep Links

Tender Details retains `#pursuit`, `#project-context`, `#requirements-documents`, `#compliance-readiness`, `#contacts`, and `#bid-preparation`. Real Chromium acceptance verifies the requirements/documents deep link after cleanup; static contracts cover all six anchors.

## 18. Compatibility Redirects

List/workspace compatibility uses permanent redirects: bids and proposals to Bid Preparation, workspace to Tender Explorer. The ambiguous bid-detail route does not guess: owned Proposal succeeds; Tender ID, invalid ID, and foreign Proposal all produce the same safe compatibility outcome without exposing private data or mutating state. No separate strategy route exists, so no ambiguous redirect was added.

## 19. Browser Network Audit

The Chromium harness records method/path traffic and a mutation counter. Tender Details retained its collapsed two-read contract. Bid Preparation emitted no sync-docs or sync-status request on initial or repeated loads. Redirect-only routes emitted no write, legacy bid detail emitted only ownership validation, and explicit Continue/Prepare/export actions were isolated to their test cases.

## 20. Database Fingerprint Audit

Disposable PostgreSQL verification ran on fresh and representative existing fixtures at the current head. The Tender Details read-model matrix reported `read_only_repeatability: true`, constant 13-query bounds before/after fixture expansion, tenant isolation, preserved parent mirrors, and no auto-repair. The Bid Preparation reconciliation matrix reported `passive_engagement_backfill: 0`, preserved 118 legacy Proposals, no submitted-state inference, and clean same-name tenant isolation. Frontend passive-request tests prove the removed document writer is unreachable from page mount; the browser mutation fingerprint remains unchanged across repeated passive loads.

## 21. Final Browser Acceptance

All 40 Sprint 5.3 Chromium scenarios pass. All 20 Sprint 5.4 cleanup scenarios pass: redirects, owned/invalid/foreign Proposal bookmarks, Tender-ID non-creation, workspace compatibility, passive and repeated Bid loads, Proposal-only behavior, explicit Continue/Prepare, non-submission exports, canonical navigation and return IDs, My Tenders link, deep link, tenant isolation, and stale credential denial. Final result: 60/60.

## 22. Remaining Legacy Inventory

Retained intentionally: `/dashboard/bids`, `/dashboard/proposals`, and `/dashboard/workspace` as passive permanent bookmark redirects; `/dashboard/bids/[id]` as Proposal-ID-only ownership-validating compatibility; backend Proposal, Decision Snapshot, competitor, and document-sync APIs for compatibility/infrastructure; legacy Proposal statuses and rows as historical business data; dashboard Admin redirects unrelated to Sprint 5. No legacy customer implementation competes with a canonical Sprint 5 surface.

## 23. Regression Results

- Frontend focused contracts: 66 passed across cleanup, Tender Details, Bid Preparation, project context, My Tenders, engagement workflow, and Admin suites.
- Backend Sprint 5: 19 passed.
- Backend Sprint 4: 64 passed and 4 subtests passed.
- Backend Sprint 3: 54 passed and 54 subtests passed.
- Backend Sprint 2: 52 passed.
- Backend Sprint 1 / World Bank: 79 passed.
- Connector gate: 195 passed, 1 approved storage-fixture skip, 4 subtests passed.
- ESLint: zero errors and zero warnings. TypeScript: pass. Production build: pass (framework middleware deprecation notice only).
- FastAPI startup/OpenAPI: pass; 77 paths generated with Tender Details, Proposal, and document routes present.
- Alembic: current=head=`20260828_0003_s4_1_tender_engagement_foundation`; check reports no upgrade operations.

## 24. Sprint 5 Release Considerations

Release review should treat the redirects as permanent compatibility, monitor legacy bookmark traffic before any later removal, and preserve the single-ID contracts. The page-load sync removal means Bid Preparation displays persisted document state; connector/ingestion health, rather than page visits, owns freshness. No migration or business-row repair is required. This work was not deployed.

## 25. Deferred Sprint 6 Work

Hunter/Explorer convergence, localization and RTL, analysis-language changes, ADB recovery, automatic submission, collaborative workspaces, and Proposal-generation expansion remain deferred. Sprint 5.4 stops without implementing any of them.
