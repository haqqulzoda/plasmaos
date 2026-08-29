# Sprint 5.3 Consolidated Tender Details UI

## 1. Previous Tender Details UI

The previous route assembled its page through fragmented passive calls for the
base Tender, a hidden Decision Snapshot, documents, competitors, Project, and a
separate engagement read inside the pursuit panel. Section failures and loading
states were coupled to a large page component, and the same customer decision
surface mixed multiple status meanings without a single explicit hierarchy.

## 2. Final Section Order

The route now presents: opportunity overview; Pursuit; Project Context and
Project Leadership; Requirements and Documents; Compliance and Company
Readiness; Procurement Contacts; and Bid Preparation. Stable anchors preserve
this order: `#pursuit`, `#project-context`, `#requirements-documents`,
`#compliance-readiness`, `#contacts`, and `#bid-preparation`.

## 3. Data Loading Model

Two independent passive reads power the page:

1. `GET /api/v1/tenders/{tender_id}` for source-authoritative opportunity facts.
2. `GET /api/v1/tenders/{tender_id}/details` for the nine bounded section envelopes.

The base Tender is the fatal page dependency. The consolidated details read is
secondary: it has its own loading state, failure message, and retry. The page
does not fan out to Project, documents, competitors, engagement, Proposal, or
Decision Snapshot summary routes.

## 4. Opportunity Overview

The header keeps the Tender title, description, source, external reference,
buyer, deadline, value, location, and Tender lifecycle status. These fields are
rendered only from the base Tender response. The official notice and Compliance
workbench remain explicit navigation actions.

## 5. Pursuit

Pursuit consumes the details response's exact engagement ID, engagement status,
status-change time, and backend-provided `allowed_actions`. The existing Sprint
4 mutation components remain the only command authority. The controlled pursuit
panel skips its legacy passive engagement GET and refreshes the consolidated
details response after a successful or stale command.

Tender lifecycle status and Pursuit status are shown with explicit labels and
separate copy. A cancelled Tender can truthfully coexist with a saved pursuit;
the UI does not infer lost/dismissed state from source status.

## 6. Project Context

Project identity, source system, external Project ID, source status, geography,
approval date, closing date, and enrichment state come from the Project Context
envelope. A linked Project remains visible while enrichment is queued or
running. Page load never triggers enrichment.

## 7. Project Leadership

Current Project roles and bounded history are rendered from the dedicated
Project Leadership envelope. Native/canonical role semantics remain explicit;
`teamleadname` is not upgraded to Task Team Leader. Project roles are never used
as procurement contacts.

## 8. Procurement Contacts

Tender procurement contacts and submission details have their own section.
Buyer agency, contact person, email, phone, submission method/deadlines,
procedure, and source-provided instructions remain Tender-source metadata and
are explicitly described as distinct from Project Leadership.

## 9. Requirements

Bounded structured requirements are marked `AI-extracted requirement` and show
available document/page/section provenance. The UI does not describe analysis-
derived requirements as source-native legal facts and does not infer additional
requirements in the browser.

## 10. Documents

The summary renders only the whitelisted public source-document metadata from
the details DTO: display name, type, source, coarse availability, size, and
creation metadata. `AVAILABLE`, `UNAVAILABLE`, and `METADATA_ONLY` receive
source-neutral labels. Document content is requested only after an explicit
Open document click.

## 11. Compliance

The summary uses the backend's latest immutable AnalysisVersion summary. It
shows execution/completeness semantics, version, issue count, creation time,
override presence, and an explicit route to the full Compliance workbench. The
workbench route always uses the Tender ID.

## 12. Company Readiness

The section shows owned evidence counts for certifications, licenses,
credentials, readiness files, missing evidence, and financial-history years.
It deliberately calculates no percentage, score, READY state, or eligibility
conclusion. The Readiness Vault remains the full-detail authority.

## 13. Bid Preparation

Bid Preparation is rendered only from the Proposal-backed envelope. Existing
artifacts display Proposal status and link with `detail_route_id` (the Proposal
ID). Prepare/Continue commands reuse the existing Sprint 4 endpoint and navigate
using the Proposal ID returned by the server.

## 14. Legacy Proposal-Only Presentation

An owned Proposal without an engagement shows `Not currently in My Tenders` in
Pursuit while Bid Preparation remains available. The UI does not infer a
PREPARING pursuit. Continue/Open Bid Preparation targets the Proposal ID.

## 15. Engagement-Only Presentation

An engagement without a Proposal shows the backend Pursuit state and actions,
while Bid Preparation truthfully reports `Not started`. Proposal absence does
not erase or alter pursuit state.

## 16. Empty/Partial States

Every section respects `AVAILABLE`, `EMPTY`, and `UNAVAILABLE`. Empty means that
the domain is absent; unavailable uses a restrained degraded-state message.
Compliance additionally distinguishes complete, `PARTIAL`, `FAILED`, and
`LEGACY_BACKFILL` results. Failed analysis never receives compliant styling.

## 17. Failure Isolation

A details endpoint failure leaves the complete source opportunity header and
source actions usable, hides stale secondary data, and offers `Retry details`.
Project-level unavailable state does not block other details sections. A base
Tender failure remains a page-level failure with its own retry.

## 18. Section Navigation

A sticky, horizontally scrollable navigation strip exposes the six stable
anchors in information-hierarchy order. Links are native anchors, focusable by
keyboard, and do not introduce router or client-state authority.

## 19. Deep Links

Chromium acceptance opened `#project-context`, `#compliance-readiness`, and
`#bid-preparation` directly. The fragment is retained while the details request
loads, then the route scrolls to the asynchronously rendered target.

## 20. Loading/Error UX

Base loading uses a page-level status. Secondary loading uses an independent
polite live region and restrained skeleton. Details, base, and explicit document
errors are separate. Retry buttons invoke only their corresponding reads.

## 21. Accessibility

Sections have stable IDs and labelled headings; status and error states use
`role=status`, `role=alert`, and `aria-live` where appropriate. Controls have
visible focus rings, native button/link semantics, and non-color status text.
The compact mobile dashboard navigation retains explicit accessible names.

## 22. Responsive Behavior

Cards collapse to one column before expanding at `sm`/`lg` breakpoints. The
section navigator scrolls horizontally without widening the document. The
dashboard sidebar becomes a labelled, icon-width rail on narrow screens, and
content/header padding contracts. Chromium at 390x844 verified no page-level
horizontal overflow and preserved usable opportunity/actions/content.

## 23. Passive Read Guarantee

Static audit and repeated Chromium loads show no passive POST, PUT, PATCH, or
DELETE. The controlled pursuit panel does not issue its fallback engagement GET.
Document content is click-only. Browser state counts and the Sprint 5.2
PostgreSQL fingerprints show zero Proposal or engagement creation and zero
domain writes across repeated loads, refreshes, and anchor navigation.

## 24. Network Request Audit

| Request | Classification | Trigger |
|---|---|---|
| `GET /tenders/{id}` | Required | Passive page load |
| `GET /tenders/{id}/details` | Required | Passive page load |
| Auth/session/access-status infrastructure | Existing required infrastructure | Layout/session |
| `GET /tenders/documents/{document_id}/download` | Required explicit action | Open document click |
| Pursuit/Prepare mutations | Existing explicit commands | User click only |

There is no passive Decision Snapshot, Project, competitor, document-list,
engagement, Proposal, or Compliance-summary fan-out. No duplicate base/details
request was observed per initial render.

## 25. Tenant Isolation

The UI renders only the backend response and stores no private section data in
local/session storage. Browser acceptance verified that foreign same-name tenant
contact data was absent and that a private document route remained 403. Sprint
5.2's PostgreSQL matrix independently proves ownership by immutable IDs and
omission of foreign Compliance, readiness, pursuit, and Proposal context.

## 26. Browser Acceptance

Real Chromium passed 40/40 required cases: Tender-only; Project available,
pending, and unavailable; leadership/contact separation; requirements and safe
documents; unauthorized document denial; Compliance complete/partial/failed/
legacy; readiness without score; all pursuit/Proposal combinations; route ID
correctness; cancelled source status coexistence; details failure; stale 409
refresh; same-name isolation; three deep links; repeated zero-write loads; no
Decision Snapshot; and no GET-side Proposal/engagement creation.

Frontend gates passed: 13 focused Tender Details tests, 42 preserved focused UI
tests, TypeScript, production build, and ESLint with zero errors. ESLint retains
one pre-existing deferred unused-import warning in `TenderWorkspace.tsx`.

Regression results: Sprint 5.1/5.2 focused tests 10/10 plus the disposable S5.2
PostgreSQL matrix; Sprint 4 64 tests and four subtests plus four PostgreSQL
scripts; Sprint 3 54 tests and 54 subtests plus three PostgreSQL scripts; Sprint
2 52 tests plus four PostgreSQL scripts; Sprint 1/WB 69 tests plus three
PostgreSQL scripts. The connector gate passed 195 tests and four subtests with
its one approved skip. Alembic check is clean at
`20260828_0003_s4_1_tender_engagement_foundation`.

## 27. Deferred Sprint 5.4 Cleanup

Sprint 5.3 does not remove legacy bids/proposals/workspace redirects, the dead
TenderWorkspace/StrategyPanel flow, unused SaveToMyTendersButton, compatibility
copy/routes, legacy duplicate overview components, or Bid Preparation page-load
document synchronization. The pre-existing TenderWorkspace lint warning remains
documented. Those reconciliations belong to Sprint 5.4; no deployment was
performed.
