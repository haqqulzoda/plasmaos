# Sprint 5.1 — Canonical Tender Details Information Architecture Foundation

## 1. Current Tender-Centric Surfaces

Inventory was completed before changing route behavior. "Side effect" means a persisted or externally observable command, not local React state.

| Surface | Route | Dynamic identity | Primary authority | Purpose | Overlap | Side effects | Policy |
|---|---|---|---|---|---|---|---|
| Tender Explorer | `/dashboard/tenders` | Tender ID in outbound links | `Tender` | Search and browse source opportunities | Condensed opportunity facts and direct workflow actions | Explicit Save and Prepare Bid only; source refresh is a separate command | KEEP as Explorer |
| Tender Details | `/dashboard/tenders/{tender_id}` | Tender ID only | `Tender`, composed with adjacent domains | Canonical decision surface for one opportunity | Currently repeats source facts across overview cards and contains a hidden/commented Decision Snapshot | Passive GETs; explicit pursuit commands, GIZ document preparation, and document open/download | KEEP and consolidate in 5.3 |
| Compliance | `/dashboard/tenders/{tender_id}/compliance` | Tender ID only | `TenderAnalysis` plus canonical `AnalysisVersion` | Full requirements, evidence, verdict, overrides, history/export context | Repeats source text and documents because evidence inspection needs them | GET on open; explicit Analyze and Override POSTs; PDF GET is read-only | KEEP as full workflow |
| My Tenders | `/dashboard/my-tenders` | Engagement ID in backend detail API; Tender ID for Open Tender | `TenderEngagement` | Company pursuit portfolio | Compact source and Project summaries overlap Tender Details | Passive list; explicit engagement commands and Prepare Bid | KEEP as portfolio |
| My Tenders detail API | `GET /api/v1/my-tenders/{engagement_id}` | Engagement ID only | `TenderEngagement` | One owned list item/engagement view for API consumers | No frontend dynamic detail page exists | None | KEEP API; do not make it Tender Details |
| Tender pursuit panel | Embedded on Tender Details and Bid Preparation | Tender ID | `TenderEngagement`; owned Proposal ID is separate context | One engagement status and allowed actions | Shared deliberately between two surfaces | GET on mount; commands only from buttons | KEEP canonical shared component |
| Bid Preparation list | `/dashboard/bid-preparation` | Proposal ID in links | `Proposal` | List owned preparation artifacts | Includes Tender and engagement context | Passive Proposal list; explicit Continue for proposal-only artifacts | KEEP |
| Bid Preparation detail | `/dashboard/bid-preparation/{proposal_id}` | Proposal ID only | `Proposal` | Edit/generate/export one preparation artifact | Repeats Tender header, documents, readiness, and pursuit context | Opening can start non-GIZ document sync when no parsed documents exist; editing/drafting/export are explicit commands | KEEP; do not embed into Tender Details |
| Legacy My Bids list | `/dashboard/bids` | None | None; compatibility redirect | Old bookmark compatibility | Same destination as Bid Preparation | Server redirect only | REDIRECT; remove in 5.4 after compatibility review |
| Legacy My Bids detail | `/dashboard/bids/{proposal_id}` | Proposal ID only | `Proposal` ownership read | Validate old bookmark then redirect | Same artifact as Bid Preparation | Owned Proposal GET only; no Tender-ID fallback or creation | REDIRECT; remove in 5.4 after compatibility review |
| Legacy Proposals list | `/dashboard/proposals` | None | None; compatibility redirect | Old bookmark compatibility | Same destination as Bid Preparation | Server redirect only | REDIRECT; remove in 5.4 after compatibility review |
| Legacy upload workspace | `/dashboard/workspace` | None | None; compatibility redirect | Former archive-upload compliance surface | Dead `TenderWorkspace` and `StrategyPanel` code overlaps Compliance | Route redirects; dead components are not mounted | REDIRECT now; remove dead components in 5.4 |
| Project Context | Embedded on Tender Details | Tender ID resolves canonical Project | `Tender → TenderProject → Project → ProjectRoleAssignment` | Source Project metadata, freshness, and leadership | Small Project summary also appears in My Tenders | Read-only independent GET | KEEP canonical embedded context |
| Procurement contact/submission | Embedded on Tender Details | Tender ID | `Tender` normalized fields plus whitelisted source metadata/live source response | Buyer, procurement contact, submission facts | Buyer and deadline repeat Overview | Passive source read; no contact persistence | CONSOLIDATE under Contacts in 5.3 |
| Tender documents | Embedded on Tender Details, Compliance, Bid Preparation | Tender ID for list; document ID for open | `TenderDocument` | Source-document discovery and access | Three context-specific presentations | List is GET; Tender Details preparation is explicit; Bid Preparation currently has page-load document sync | KEEP canonical metadata on Tender Details; retain evidence/artifact-specific consumers |
| Requirements/evidence | Full Compliance surface | Tender ID, analysis/version IDs beneath it | `AnalysisVersion` snapshots | AI extraction, evidence, compliance decision support | Tender Details currently has no requirements section | GET on open; Analyze is explicit | SUMMARY on Tender Details; full detail remains Compliance |
| Company Readiness | `/dashboard/readiness-vault`, dashboard summary, Proposal context | readiness record ID where edited | `CompanyProfile`, credentials, `ReadinessDocument` | Company-wide readiness evidence and expiry state | Not currently tender-scoped on Tender Details | Vault CRUD is explicit; reads are passive | SUMMARY only in 5.2/5.3; keep Vault canonical |
| Hunter recommendation | `/dashboard/hunter` → Tender Details | Recommendation ID for dismiss; Tender ID for review | `TenderRecommendation` for recommendation state, `Tender` for opportunity | Recommended-opportunity feed | Review leads to canonical Tender Details | Explicit recommendation dismissal only | KEEP separate; do not merge with Explorer |
| Dashboard deep links | `/dashboard` → Tender Details/Compliance/Readiness | Tender ID for Tender/Compliance | Domain named by destination | Decision queue and recent activity | Summaries overlap destination surfaces | Passive reads | KEEP links canonical |
| Compliance PDF | `GET /api/v1/tenders/{tender_id}/compliance/export/pdf` | Tender ID, optional owned analysis/version selector | `AnalysisVersion` | Immutable compliance report export | Same evidence as Compliance | Response generation only; no persistence | KEEP with Compliance |
| Proposal PDF/DOCX | `POST /api/v1/proposals/{proposal_id}/generate-pdf`, `POST .../export/docx` | Proposal ID only | `Proposal` | Generate Bid Preparation artifacts | Proposal detail only | Explicit artifact generation; may set Proposal `COMPLETED`; never changes engagement | KEEP with Bid Preparation |

Evidence: `frontend/app/dashboard/**`, `frontend/components/tenders/**`, `frontend/components/bid-preparation/PrepareBidButton.tsx`, `backend/app/api/endpoints/{tenders,my_tenders,proposals}.py`, and the Sprint 1–4 architecture documents.

## 2. Tender Draft Findings

Repository-wide runtime and documentation search found no active **Tender Draft**, **Draft Tender**, `/draft/{id}`, or tender-draft route.

Every live "draft" occurrence means Proposal/Bid Preparation:

| Evidence | Classification | Finding |
|---|---|---|
| `backend/app/models/base.py`: `ProposalStatus.DRAFT` | B — Proposal/Bid Preparation | Artifact state, not Tender state |
| `backend/app/models/all_models.py`: Proposal defaults to `DRAFT` | B | Proposal persistence only |
| `frontend/types/bid-preparation.ts`: `DRAFT` → `Draft` | B | Preparation-status label |
| `frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx`: `Save Draft` | B | Saves Proposal structured data |
| Same page: `Generate Strategic Draft` | B | Explicit Proposal AI authoring command |
| `backend/app/api/endpoints/proposals.py`: create proposal draft / AI draft docstrings | B | Proposal endpoints only |
| `/dashboard/bids*`, `/dashboard/proposals` | D — legacy mixed naming, now corrected | Compatibility redirects/read validation; no Tender Draft meaning remains |
| `frontend/components/workspace/TenderWorkspace.tsx` | E — unused/dead | Not mounted; `/dashboard/workspace` redirects to Explorer |

Conclusion: there is no source-fact Tender Draft to preserve. "Draft" remains valid only as a subordinate Proposal artifact state/action. Legacy bid/proposal routes stay compatibility-only until 5.4.

## 3. Canonical Tender Details Purpose

Tender Details is the canonical customer decision surface for exactly one Tender. It composes source opportunity facts, canonical Project context, source documents/contacts, latest owned Compliance context, company readiness, the owned pursuit, and any owned Bid Preparation artifact. It answers what the opportunity is, what evidence exists, whether the company is ready, what the pursuit/artifact state is, and what explicit action is legitimate next.

It is not a Proposal editor, engagement portfolio, Compliance workbench, Project workspace, CRM record, collaboration workspace, or new persistence aggregate.

## 4. Domain Authorities

| Concept | Canonical authority | Explicit non-authorities |
|---|---|---|
| Opportunity/source status | `Tender` and source-normalized metadata | Proposal, engagement, Compliance summary |
| Project context | `TenderProject → Project → ProjectRoleAssignment` | Title similarity, email, Proposal, Compliance |
| Procurement contacts/submission | Whitelisted Tender/source metadata with source evidence | Project leadership and inferred people |
| Project leadership | `ProjectRoleAssignment` with Project provenance | Tender contact/submission fields |
| Source documents | `TenderDocument` plus safe source/availability metadata | Analysis snapshot as a live document catalog |
| Source-native requirements | Explicit normalized/source metadata only when provenance exists | Unlabeled AI extraction |
| Extracted/interpreted requirements | Latest owned `AnalysisVersion` result/evidence snapshots | Mutable `TenderAnalysis.analysis_json` mirror |
| Compliance | Owned `TenderAnalysis` parent and immutable `AnalysisVersion` reads | Proposal, engagement, mutable parent mirror |
| Company readiness | Owned `CompanyProfile`, credentials, certifications/licenses/financial evidence, and `ReadinessDocument` | A new recommendation engine or Proposal content |
| Pursuit | Exact owned `TenderEngagement` tuple | Proposal, analysis, recommendation, source status |
| Bid Preparation | Exact owned `Proposal` | Engagement status or Compliance |
| Recommendation | `TenderRecommendation` | My Tenders membership |

No `CanonicalContact` or `CanonicalDocument` model exists in this repository. The operative models are source-derived contact DTOs and `TenderDocument`; Sprint 5 must describe the real architecture rather than invent names.

## 5. Route Identity

- Tender Details: `/dashboard/tenders/{tender_id}` — Tender ID only.
- Compliance: `/dashboard/tenders/{tender_id}/compliance` — Tender ID only.
- Bid Preparation: `/dashboard/bid-preparation/{proposal_id}` — Proposal ID only.
- My Tenders backend detail: `/api/v1/my-tenders/{engagement_id}` — Engagement ID only.

The canonical Tender route does not interpret Proposal, Analysis, or Engagement IDs and performs no get-or-create. Compliance no longer has Proposal-ID fallback. The legacy bid detail route validates an owned Proposal then redirects; it never treats the value as a Tender ID.

## 6. Information Architecture

Use one responsive, scrollable Tender Details page with a compact section navigator and these actual-capability sections:

1. **Opportunity Overview** — title, source, source status, buyer, source link/reference, deadline, value/currency, method, geography, publication/freshness, and restrained market context.
2. **Project Context** — canonical Project, freshness/provenance, current and historical Project Leadership.
3. **Requirements & Documents** — source document catalog first; requirement signals labelled source-native or AI-extracted.
4. **Compliance & Company Readiness** — latest truthful Compliance summary, company readiness evidence/gaps, and links to the full Compliance and Readiness Vault surfaces.
5. **Procurement Contacts** — procurement/submission contacts and instructions only. Project Leadership remains under Project Context.
6. **Pursuit** — one compact TenderEngagement-backed panel and allowed commands.
7. **Bid Preparation** — owned Proposal summary/open action or explicit Prepare Bid.

Do not create an empty section when its domain is absent. Opportunity Overview always renders. Existing Likely Competitors may remain a secondary/provenance-labelled part of Overview in 5.3; it is not a new authority.

## 7. Opportunity Authority

Opportunity Overview reads `Tender`: title, buyer, source/source URL, external reference, source status, deadline, budget/value, currency, procurement method/category, country/region, publication date, and source freshness when available. Proposal price, engagement status, or Compliance conclusions must never overwrite these facts.

The current API exposes most fields but not `last_synced_at`; the 5.2 summary contract should expose a safe `last_refreshed_at` when present. Live source fallbacks may affect only the response. Sprint 5.1 corrected live UzEx date enrichment so GET rendering no longer dirties and commits the ORM Tender row.

## 8. Project Context

Project identity is resolved only through `Tender → TenderProject → Project`. Leadership is `ProjectRoleAssignment`. The existing `GET /tenders/{tender_id}/project` query follows that join, returns `null` when absent, and independently degrades without blocking the Tender.

World Bank enrichment remains source-provenanced and asynchronous under Sprint 1 architecture. Tender Details access is not an enrichment creation authority. No standalone Project route currently exists; Tender Details remains the correct project context surface without foreclosing a later Project-level product.

## 9. Leadership vs Procurement Contacts

`Project Leadership != Procurement Contact` remains locked. `ProjectContextSection` labels `teamleadname` conservatively as World Bank project team and explicitly warns that leadership may differ from the Tender procurement contact. Contact & Submission derives separate whitelisted Tender/source fields.

Project names, implementing agencies, leadership emails, or borrower fields must not be promoted to submission/procurement contacts without source evidence of that role.

## 10. Requirements

The repository has three different requirement-like sources:

- source documents/compiled text: original evidence;
- `TenderRequirement`: taxonomy mappings associated with a Tender, but without enough per-item source provenance to present as source-native wording;
- `AnalysisVersion.result_snapshot` and `evidence_snapshot`: versioned AI extraction, validation, and interpretation.

Tender Details 5.2 may expose source-native requirement facts only when the normalized source contract includes traceable origin. Otherwise it may show an **AI-extracted requirements** count/key-gap summary from the latest owned usable AnalysisVersion, with coverage/completeness and a link to Compliance. It must not relabel extracted text as original source fact.

## 11. Documents

The current authority is `TenderDocument`. The Tender Details contract allowlist is:

- customer-safe display name;
- document/source type;
- institutional/source label and safe HTTP(S) source link when supported;
- availability/processing status;
- file size when useful;
- analysis-text availability;
- owned open/download action.

Do not expose `storage_path`, raw parser errors, credentials, raw internal URLs, hashes, or parser internals. The current DTO already hides `storage_path` and hash, but also exposes compatibility fields (`storage_filename`, parsed/archive filenames) that should not be copied into the 5.2 summary DTO unless product-relevant. The current document list access gate is Proposal/Compliance-history based and therefore fails for some Tender-only or engagement-only cases; 5.2 must align document metadata authorization with the canonical visible-Tender policy without weakening private file access.

## 12. Compliance

Compliance remains an owned `TenderAnalysis` aggregate whose canonical read payload is the selected `AnalysisVersion`. The Tender Details summary may show version number, execution timestamp, status/completeness, coverage signal, restrained verdict/readiness signal, and a link to `/dashboard/tenders/{tender_id}/compliance`.

Full requirements, evidence inspection, overrides, version history, rerun, and export remain in Compliance. The mutable parent mirror is compatibility-only and must never populate the summary.

## 13. Company Readiness

Readiness authority is the exact owned CompanyProfile scope, its certifications/licenses/financial inputs and credentials, plus readiness records in `ReadinessDocument`. Current global surfaces are `/dashboard/readiness-vault` and the dashboard; Tender Details has no current tender-scoped readiness summary.

Sprint 5.2 may compute a restrained evidence-backed summary against latest AnalysisVersion requirement signals. If no usable analysis exists, show company-wide evidence availability/expiry only and label it accordingly. Do not create a recommendation engine, infer readiness from Proposal content, or mutate the profile on read.

## 14. Pursuit

Pursuit reads only the exact `(user_id, company_profile_id, tender_id)` TenderEngagement. Backend-derived `allowed_actions` controls the UI. `GET /tenders/{tender_id}/engagement` may return no engagement and separately an owned `proposal_id`; Proposal presence never becomes pursuit state.

Tender Details controls one engagement only. My Tenders remains the list, filtering, counting, and bulk portfolio context.

## 15. Bid Preparation

Bid Preparation reads only an owned Proposal. When one exists, Tender Details shows its artifact status and opens `/dashboard/bid-preparation/{proposal_id}`. When absent, Prepare Bid is an explicit POST that atomically creates/reuses the engagement and Proposal according to Sprint 4.3. Page load never creates either.

Tender Details must not embed Proposal editing, AI drafting, pricing, line items, or PDF/DOCX generation.

## 16. Legacy and Partial Domain Combinations

| Combination | Truthful Tender Details behavior |
|---|---|
| Tender only | Render Opportunity Overview; optional sections omitted/unavailable; Save/Evaluate/Prepare actions according to existing commands |
| Tender + Project | Show Project Context; do not imply pursuit |
| Tender + Compliance only | Show owned Compliance context; say not in My Tenders; no Proposal |
| Tender + Engagement only | Show pursuit state; Bid Preparation "Not started" |
| Tender + Proposal only | Show Bid Preparation artifact; pursuit "Not recorded in My Tenders"; explicit Continue may establish PREPARING |
| Tender + Engagement + Proposal | Show independent pursuit and artifact states without reconciliation/inference |
| Tender + Compliance + Engagement | Show both; Bid Preparation "Not started" |
| All domains | Compose all summaries without one overwriting another |
| Project enrichment pending/unavailable | Show restrained pending/unavailable state when identity is known; other sections remain usable |
| Latest Compliance failed/partial/legacy | Show failed/incomplete/legacy warning; never show a synthetic compliant state |

Examples such as source `CLOSED` plus pursuit `SUBMITTED`, or source `CANCELLED` plus pursuit `PREPARING`, are valid and must display as separately labelled badges.

## 17. Action Hierarchy

Use the existing backend `allowed_actions`; do not duplicate transition rules in Tender Details.

| State | Primary | Secondary |
|---|---|---|
| No engagement/no Proposal | Prepare Bid | Save to My Tenders |
| No engagement/Proposal exists | Continue/Open Bid Preparation | Save to My Tenders |
| SAVED | Evaluate or Prepare Bid | Dismiss |
| EVALUATING | Prepare Bid | Dismiss |
| PREPARING | Open Bid Preparation when present; otherwise Prepare to create it | Mark as Submitted, Dismiss |
| SUBMITTED | Record Won / Record Lost | Correct to Preparing |
| WON / LOST | View recorded outcome | Correction actions |
| DISMISSED | Resume via Save/Evaluate/Prepare | None promoted |

Compliance Analyze, source-document preparation, and source opening are context actions, not pursuit transitions.

## 18. Action Side-Effect Matrix

| Action | Allowed persistence/external effect | Must not affect |
|---|---|---|
| Passive Tender Details open | None | Every persistence domain |
| Open source notice | Browser navigation to source | Plasma persistence |
| Open/download source document | Read/proxy bytes only | Tender, engagement, Proposal, analysis |
| Prepare GIZ documents | Explicit source-document hydration/sync | Engagement, Proposal, Compliance, company profile |
| Save to My Tenders | TenderEngagement only | Proposal, Compliance, Project, Tender source facts |
| Evaluate / Dismiss / Resume | TenderEngagement only | Proposal and source facts |
| Prepare Bid | TenderEngagement + Proposal atomically | Compliance, Project, source facts |
| Continue legacy Proposal | Reuse Proposal + establish/reuse PREPARING engagement | New Proposal, Compliance, source facts |
| Mark Submitted / Won / Lost / correct | TenderEngagement only | Proposal status, source status |
| Run Compliance | TenderAnalysis/AnalysisVersion and its audit/evidence records only | Engagement, Proposal, Project, source facts |
| Apply Compliance override | Risk override overlay only | Base AnalysisVersion, engagement, Proposal |
| Generate Compliance PDF | Response artifact only | Persisted analysis and pursuit |
| Save Proposal draft | Proposal structured data only | Engagement status and Compliance |
| Generate Proposal PDF/DOCX | Proposal artifact; current implementation may mark Proposal `COMPLETED` | TenderEngagement submission/outcome, Compliance |
| Dismiss Hunter recommendation | TenderRecommendation only | TenderEngagement and Proposal |

## 19. Tab vs Section Decision

Choose a **hybrid single-page section model**, not nested routed tabs. Current information density is significant but the complex workflows already have dedicated routes. A scrollable Tender Details page with a compact section navigator, collapsible secondary content, and links out to full Compliance/Bid Preparation is simpler, preserves context, and avoids route explosion. 5.3 owns the visual implementation.

## 20. Deep-Link Strategy

Use stable fragment anchors on the canonical route:

- `/dashboard/tenders/{id}#overview`
- `#project-context`
- `#requirements-documents`
- `#compliance-readiness`
- `#procurement-contacts`
- `#pursuit`
- `#bid-preparation`

Fragments do not change identity, require no nested route, and preserve existing `/dashboard/tenders/{id}` bookmarks. Full Compliance and Bid Preparation keep their existing routes. 5.3 should focus/scroll after progressively loaded sections mount and leave unknown fragments harmless.

## 21. Legacy Route Policy

| Route/surface | 5.1 policy | 5.4 target |
|---|---|---|
| `/dashboard/bids` | KEEP redirect | Remove after usage/bookmark validation or retain thin redirect if inexpensive |
| `/dashboard/bids/{proposal_id}` | KEEP safe owned-read redirect | Same; never regain dual ID semantics |
| `/dashboard/proposals` | KEEP redirect | Remove or retain thin compatibility redirect |
| `/dashboard/workspace` | KEEP redirect | Remove dead upload-workspace components after import/acceptance proof |
| Tender Draft route | None exists | No route to clean up |
| `SaveToMyTendersButton` | Unused duplicate; do not remove in 5.1 | Consolidate/remove after component acceptance |
| Commented Decision Snapshot block and active hidden fetch | Duplicate/dead presentation | Remove or intentionally revive as part of 5.3, then delete duplicate code in 5.4 |

No route is removed in 5.1.

## 22. Compliance and Project Route Policy

Tender Details shows latest Compliance summary and links to the full Tender-ID Compliance route. Do not delete or embed the full workbench. Project Context remains embedded on Tender Details because no standalone Project product route exists. This does not prevent a legitimate future source Project route; such a route would use Project identity, not replace Tender Details.

## 23. Composite Read-Model Decision

Choose **hybrid composition** for Sprint 5.2:

1. Keep `GET /tenders/{tender_id}` as the fast critical source-fact response.
2. Add one approved, tenant-scoped `GET /tenders/{tender_id}/details` secondary summary endpoint composed through domain services.
3. Keep full domain endpoints for detailed workflows and all commands.

Why:

| Concern | Decision |
|---|---|
| Authorization | One secondary orchestrator consistently resolves exact current user/profile for private domains; source facts retain current visibility policy |
| Query count/latency | Avoid today's many independent round trips and duplicate competitor/source requests; batch summaries and use bounded query counts |
| Failure isolation | Field envelopes permit partial success; the critical Tender response is independent |
| Domain ownership | Orchestrator calls domain readers/DTO builders; it does not query and reinterpret mutable mirrors |
| Cache behavior | Source Tender/project/document summaries can use source freshness; tenant-private summaries are private/no shared cache |
| Frontend complexity | One critical and one secondary request, followed by existing full-workflow routes |

No `/details` endpoint is implemented in 5.1.

### Sprint 5.2 response contract

The secondary response should contain:

```text
tender_id
project: Section<ProjectSummary>
contacts: Section<ProcurementContactsSummary>
documents: Section<DocumentSummary[]>
requirements: Section<RequirementSignalsSummary>
compliance: Section<LatestComplianceSummary>
readiness: Section<CompanyReadinessSummary>
pursuit: Section<TenderEngagementSummary | null>
bid_preparation: Section<ProposalSummary | null>
allowed_actions: backend-derived command descriptors
```

Each `Section<T>` has `state = available | empty | unavailable | unauthorized`, optional `data`, a stable safe reason code, and `as_of`/freshness where relevant. A section never includes another tenant's IDs or data.

## 24. Failure Isolation, Loading, and Errors

Critical source facts load first and determine Tender missing/not-visible behavior. Secondary sections load together through the summary endpoint but resolve independently.

| Failure | Customer behavior |
|---|---|
| Tender missing/not visible | Canonical not-found state; no secondary calls/actions |
| Customer access rejected/disabled/stale | Existing access-blocked/session handling; public source visibility does not bypass dashboard access |
| Project unavailable | Project-only warning/omission; Tender and private summaries remain |
| Documents unavailable | Document-only safe reason; other sections remain |
| Compliance unavailable/integrity anomaly | Compliance-only unavailable/409-derived safe state; never fall back to parent mirror |
| Readiness unavailable | Readiness-only warning and Vault link when authorized |
| Engagement unavailable | Pursuit-only warning; never infer from Proposal |
| Proposal unavailable | Bid Preparation-only warning; never infer from engagement |

Do not add streaming architecture. Use ordinary progressive loading and existing React request patterns in 5.3.

## 25. Tenant Security

Source Tender/Project/document metadata follows the current customer-visible source policy. Private summaries require exact current scope:

- TenderEngagement: `(user_id, company_profile_id, tender_id)`;
- Proposal: `Proposal.user_id` plus current owned profile context;
- Compliance: owned parent `(user_id, company_profile_id, tender_id)` then AnalysisVersion;
- readiness: current user's owned CompanyProfile and readiness records.

Same-name company display values are never authorization. Platform admin/operator roles do not receive a customer Proposal, engagement, Compliance summary, or readiness summary through this endpoint. Existing explicit administrative review endpoints remain separate and must not be reused as Tender Details composition.

Pending, rejected, disabled, or stale credentials remain denied by Sprint 3 dependencies/layout access checks. The secondary endpoint must require approved pilot access even though source Tender facts may have broader API visibility.

## 26. Same-Name Tenant Matrix

For the same Tender and two profiles both named "Acme Engineering":

| Context | User A | User B |
|---|---|---|
| Source Tender/Project/doc metadata | Same visible source facts | Same visible source facts |
| Pursuit | PREPARING | SAVED |
| Bid Preparation | Proposal A | None |
| Compliance | Analysis/Version A | Analysis/Version B |
| Readiness | Profile A evidence | Profile B evidence |

No field may be selected by company name. IDs from the other tuple return null/not found rather than cross-contaminating the response.

## 27. Provenance and Freshness Contract

Show provenance only where it changes interpretation:

- Tender source badge plus official notice link;
- Project source/freshness and official Project source;
- Project role institutional source and observation/history dates;
- source document origin/availability;
- AI-extracted requirement evidence/source and analysis version/completeness.

Do not label every scalar. Preserve original evidence text; translation or AI explanation must be visually and structurally separate.

Freshness uses safe existing facts: Tender source status and proposed `last_refreshed_at` from `last_synced_at`; Project `source_freshness` and `last_successful_enrichment_at`; Compliance version `created_at/completed_at`; readiness expiry/status. Never imply source data is current when freshness is absent.

## 28. Static Passive-Read Audit

Tender Details mount currently invokes:

- `GET /tenders/{id}`;
- `GET /tenders/{id}/decision-snapshot` even though its UI is commented out;
- `GET /tenders/{id}/documents`;
- `GET /tenders/{id}/competitors`;
- `GET /tenders/{id}/project`;
- `GET /tenders/{id}/engagement` through `TenderEngagementPanel`.

Result by path:

| Path | Classification | Finding |
|---|---|---|
| Tender, Project, documents, competitors, engagement GETs | READ ONLY | No customer-domain creation |
| Live source contact/date/competitor fallback | READ ONLY external source lookup | No persistence; date override fix in 5.1 prevents ORM dirty-write commit |
| Save/Evaluate/workflow buttons | EXPLICIT COMMAND | Handlers only |
| Prepare Bid | EXPLICIT COMMAND | Handler only; atomic engagement + Proposal |
| GIZ Prepare documents | EXPLICIT COMMAND | Handler only |
| Project enrichment workers | BACKGROUND SOURCE ENRICHMENT | Independent of page access |
| Former live UzEx date assignment during GET | BLOCKER, RESOLVED | Now response-only override, covered by `test_s5_1_tender_details_foundation.py` |

No passive Tender Details page load creates or updates TenderEngagement, Proposal, TenderAnalysis, AnalysisVersion, Recommendation, Project, CompanyProfile, or Tender source rows after the fix.

Separate audit note: Bid Preparation detail currently starts eligible non-GIZ document sync on page open. It is not called by Tender Details and does not infer engagement state, but 5.4 browser cleanup should decide whether this background document behavior remains intentional.

## 29. Static Route Identity Audit

- `frontend/app/dashboard/tenders/[tenderId]/page.tsx` reads `/tenders/${tenderId}` and links Compliance with the same Tender ID.
- Compliance sets `resolvedId = tenderId`; no Proposal lookup/fallback exists.
- Bid Preparation reads exactly `/proposals/${resolvedParams.proposalId}`.
- legacy `/dashboard/bids/[id]` performs only owned Proposal GET then redirects.
- My Tenders rows link with `item.tender_id`; backend detail uses `engagement_id`.
- Prepare accepts Tender ID in a POST body; Continue accepts Proposal ID in its route.

Result: no dual-ID interpretation.

## 30. Duplicate and Dead Components

| Component/concept | Classification | Decision |
|---|---|---|
| Tender Details source header + Source Identity/Buyer/Timing/Classification cards | DUPLICATE presentation | Consolidate into Opportunity Overview in 5.3 |
| Commented Decision Snapshot markup, helpers, state, and active request | DUPLICATE/DEAD UI | Defer removal/reconciliation to 5.4 after 5.3 layout decision |
| `SaveToMyTendersButton` | LEGACY duplicate | Unused at runtime; shared panel owns current behavior; defer removal 5.4 |
| `TenderEngagementPanel` | CANONICAL shared | Keep |
| `ProjectContextSection` | CANONICAL | Keep and place under Project Context |
| Tender Details Documents | CANONICAL catalog | Keep |
| Compliance/Bid Preparation document views | CONTEXTUAL consumers | Keep evidence/artifact needs; share DTO/render primitives later where useful |
| `TenderWorkspace`, `StrategyPanel`, workspace `DocumentViewer` upload flow | DEAD legacy surface, except `DocumentViewer` reused by Compliance | Remove only unused workspace/strategy pieces in 5.4; retain reused viewer |
| Legacy bids/proposals route files | LEGACY compatibility | Retain through 5.4 policy review |

## 31. Terminology

Canonical customer terms are **Tender Details**, **My Tenders**, **Bid Preparation**, **Compliance**, **Company Readiness**, **Project Context**, **Procurement Contact**, and **Project Leadership**.

Occurrence classifications:

- **Draft** is allowed only for Proposal artifact state/content actions such as Save Draft or Generate Strategic Draft.
- **Bid** is allowed in explicit actions/outcome sentences (Prepare Bid, mark bid submitted), not as a portfolio/surface synonym.
- **Proposal** is primarily the backend/domain name; customer navigation remains Bid Preparation.
- **Readiness Vault** remains the evidence-management surface; its Tender Details summary label is Company Readiness.
- **Contact & Submission** should become Procurement Contacts in 5.3; it must not absorb Project Leadership.
- **My Bids** has no customer runtime label; legacy routes are compatibility-only.

No global word replacement is appropriate.

## 32. Migration Decision

No migration and no new aggregate entity. Tender Details is composition. Do not create `TenderWorkspace`, `TenderDetail`, `TenderCase`, `BidWorkspace`, or equivalent persistence. Repository Alembic head remains `20260828_0003_s4_1_tender_engagement_foundation`.

## 33. Read-Only Preflight and Consistency Plan

Sprint 5.2/5.4 should add count-only, tenant-safe metrics:

- Tenders with/without TenderProject;
- Tenders with/without engagement, Proposal, and owned Compliance;
- Proposal-only, engagement-only, Compliance-only, pairwise, and all-three counts;
- broken TenderProject, Proposal→Tender, engagement→Tender, and analysis→Tender references;
- duplicate logical owner keys and owned analysis parents without versions;
- private rows whose user/profile ownership tuple is inconsistent.

Optional absence is not a defect. Output only counts/status classes; do not dump customer content and do not repair.

## 34. Representative Data Matrix

| Fixture | Expected proof | Existing/new coverage |
|---|---|---|
| A Tender only | Overview useful, zero private inference | S4.2/S4.3 passive and non-inference fixtures |
| B Tender + Project | Canonical Project, no pursuit | S1.1–S1.3 Project tests |
| C Tender + Compliance | Compliance shown, no engagement/Proposal inference | S2.1–S2.3 plus S4 non-inference tests |
| D Tender + Engagement | pursuit shown, Proposal absent | S4.1/S4.4 no-Proposal workflow |
| E Tender + Proposal only | artifact shown, not My Tenders until Continue | S4.3 legacy Proposal fixture |
| F Tender + Engagement + Proposal | independent statuses | S4.3/S4.4 workflows |
| G Tender + Compliance + Engagement | independent decision/pursuit | S4.4 Compliance independence |
| H All domains | every section composes without inference | Cross-Sprint focused regression composition |
| I Project enrichment pending | non-blocking fallback identity | S1.3 frontend/runtime recovery tests |
| J Compliance partial/legacy | truthful completeness and failure semantics | S2.2/S2.3 version tests |
| K same-name tenants | distinct private summaries | S2/S4 same-name ownership tests |
| L live UzEx date fallback | response fresh, persisted Tender unchanged | New S5.1 passive-read test |

Sprint 5.2 must turn this into one endpoint-level response matrix, including per-section unavailable states and bounded query counts. Sprint 5.1 reuses the established domain fixtures rather than implementing the deferred endpoint.

## 35. Sprint 5.2 Implementation Contract

Sprint 5.2 is limited to:

1. Define presentation-safe summary DTOs and `Section<T>` failure envelopes.
2. Implement the approved tenant-scoped secondary `/tenders/{tender_id}/details` read endpoint through existing domain services.
3. Resolve Tender ID once; never accept alternate identities.
4. Enforce exact user/profile ownership independently for engagement, Proposal, Compliance, and readiness.
5. Read Compliance only from canonical AnalysisVersion services and preserve failed/partial/legacy completeness.
6. Return Proposal and engagement independently, including proposal-only and engagement-only truth.
7. Align safe document metadata access with visible Tender policy while preserving file authorization.
8. Provide source-vs-AI requirement labels and safe provenance/freshness.
9. Batch queries, establish a bounded query-count test, and avoid per-row/N+1 loads.
10. Return partial secondary success when Project/readiness/Compliance/document domains fail.
11. Add the full A–L endpoint test matrix, same-name tenant isolation, rejected/disabled/stale access, and passive-read transaction proofs.
12. Add count-only consistency preflight metrics.

It must not implement the 5.3 layout, 5.4 route/component cleanup, a migration, localization, automatic submission, collaboration/CRM, or deployment.

## 36. Deferred Sprint 5.3 and 5.4 Work

Sprint 5.3 owns the scrollable consolidated UI, section navigation/anchors, action hierarchy, progressive loading, differentiated error states, responsive behavior, and accessibility.

Sprint 5.4 owns compatibility decisions/removal, dead and duplicate component cleanup, legacy route/deep-link reconciliation, final full-browser acceptance, and the decision on Bid Preparation page-load document sync.

## 37. Verification Record

The implementation changes in Sprint 5.1 are limited to the response-only live UzEx date fix, its passive-read tests, and this architecture document.

- S5.1/passive/source-detail focus: 36 passed, 4 subtests passed.
- Sprint 4 focus: 40 passed; four disposable PostgreSQL scripts passed with clean Alembic checks.
- Sprint 3 access/admin focus: 72 passed, 64 subtests passed; three disposable PostgreSQL scripts passed.
- Sprint 2 Compliance/version/readiness focus: 42 passed; four disposable PostgreSQL scripts passed.
- Sprint 1/World Bank focus: 69 passed with one pre-existing Alembic deprecation warning; three disposable Project/enrichment scripts passed.
- Connector regression gate: 195 passed, one approved storage-fixture skip, 4 subtests passed.
- Focused frontend domain regressions: 42 passed. TypeScript, production build, and ESLint were not mandatory because no frontend file changed.
- Repository and configured development database current revision: `20260828_0003_s4_1_tender_engagement_foundation`; direct `alembic check` reported no new upgrade operations.

No frontend file, migration, route, composite endpoint, production resource, localization, ADB/World Bank architecture, Admin architecture, or deployment is changed.
