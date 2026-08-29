# Sprint 4.3 — Bid Preparation and Proposal Reconciliation

## 1. Previous My Bids Model

| Surface/path | Identifier | Read/write | Could create Proposal? | Ownership | Previous label/problem | Target behavior |
|---|---|---|---|---|---|---|
| `/dashboard/bids` | none | GET page/list | No | Proposal `user_id` | My Bids implied pursuit/submission | Legacy redirect to Bid Preparation |
| `/dashboard/bids/[id]` | Proposal ID or Tender ID | GET page followed by API POST fallback | Yes | Proposal `user_id` after lookup | Dual identity; navigation could create | Strict owned Proposal ID, then canonical redirect |
| `/dashboard/proposals` | none | referenced navigation | No implementation | none | Broken backlink | Legacy redirect to Bid Preparation |
| `GET /api/v1/proposals` | current user | read | No | `Proposal.user_id` | Proposal list | Safe Bid Preparation list authority |
| `GET /api/v1/proposals/{proposal_id}` | Proposal ID | read | No | `Proposal.user_id` | Proposal detail | Strict owned Proposal artifact read |
| `POST /api/v1/proposals` | Tender ID body | write | Yes | authenticated user | Compatibility artifact creation | Retained, artifact-only, concurrency-safe |
| Tender Explorer | Tender ID | navigation | Indirectly | deferred to legacy route | Draft | Explicit Prepare Bid command |
| Tender Details | Tender ID | read/actions | No | Tender access | Save only | Add explicit Prepare Bid |
| My Tenders | Tender engagement | read/actions | No | exact owner tuple | Open Tender only | Add explicit Prepare Bid |
| Hunter | Tender ID | navigation | Indirectly | recommendation scope | Review navigated into create fallback | Review opens Tender Details |
| Compliance | Tender ID, with Proposal-ID fallback | read with POST fallback | Yes | mixed | Passive compiled-text recovery created Proposal | Strict Tender ID and read-only loading |
| PDF/DOCX | Proposal ID | POST artifact generation | No new Proposal | Proposal `user_id` | Set Proposal COMPLETED | Preserve artifact-only completion |

## 2. Canonical Product Separation

`TenderEngagement` remains the company pursuit lifecycle. `Proposal` remains the Bid Preparation artifact. My Tenders is engagement-backed; Bid Preparation is Proposal-backed. Neither table replaces or derives historical truth from the other.

## 3. Bid Preparation Semantics

The customer label is **Bid Preparation**. A Proposal may exist without an engagement because legacy intent is unknown. An engagement may exist without a Proposal. Only the current explicit Prepare/Continue command connects them operationally.

## 4. Proposal Identity

The established repository contract is one Proposal per `(user_id, tender_id)`, enforced by `uq_proposals_user_tender`. Sprint 4.3 retains that identity. PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` makes both the compatibility artifact API and the Prepare command deterministic under concurrency.

No company-name, email, Tender-title, or timestamp reconciliation is used.

## 5. Route Identity

Canonical frontend routes are:

- `/dashboard/bid-preparation`
- `/dashboard/bid-preparation/{proposal_id}`

The dynamic identifier means Proposal ID only. The page performs exactly one owned `GET /proposals/{proposal_id}` lookup and never treats a failure as a Tender ID.

Backend route identifiers are also explicit: `/proposals/prepare` accepts a Tender ID in the POST body, while `/proposals/{proposal_id}/continue` accepts only a Proposal ID.

## 6. Legacy Route Compatibility

- `/dashboard/bids` redirects to `/dashboard/bid-preparation`.
- `/dashboard/bids/{id}` validates `id` strictly as an owned Proposal via a read, then redirects to the canonical detail route.
- An invalid, foreign, or Tender ID shows safe compatibility guidance. It creates nothing and does not guess by UUID shape.
- The previously referenced but absent `/dashboard/proposals` route is classified **BROKEN LEGACY** and now redirects to the canonical list.

## 7. Explicit Prepare Bid Command

`POST /api/v1/proposals/prepare` represents the user's current statement: “I am preparing a bid for this Tender.” The shared frontend `PrepareBidButton` is used from Tender Explorer, Tender Details, and My Tenders. It POSTs only from its click handler and navigates using the returned Proposal ID.

## 8. Engagement Integration

The command calls the canonical Sprint 4.1 engagement service with initial `PREPARING` and origin `BID_PREPARATION`. Existing engagement identity is reused. The Bid Preparation service never assigns engagement status directly.

Save remains separate: Save creates/reuses `SAVED` with `MANUAL_SAVE` and never creates a Proposal.

## 9. State Transition Behavior

| Initial engagement | Explicit Prepare result |
|---|---|
| none | new `PREPARING`, origin `BID_PREPARATION` |
| `SAVED` | same row → `PREPARING` |
| `EVALUATING` | same row → `PREPARING` |
| `DISMISSED` | same row → `PREPARING` |
| `PREPARING` | unchanged |
| `SUBMITTED` | unchanged |
| `WON` | unchanged |
| `LOST` | unchanged |

All seven inputs were proven against PostgreSQL.

## 10. Proposal Creation Transaction

Engagement resolution/transition and Proposal resolution occur in the same FastAPI database session and transaction. The service does not commit. The request dependency commits only after a successful response and rolls the complete transaction back on an exception.

Two concurrent commands from an empty state produced one engagement and one Proposal. Two concurrent commands from `SAVED` reused one engagement and one Proposal.

## 11. Legacy Proposal Policy

Legacy rows are preserved as artifacts. Listing or opening them does not create an engagement. Sprint 4.3 performs no migration, startup reconciliation, list-time inference, blanket backfill, deletion, or reassignment.

The 118-row representative PostgreSQL fixture remained 118 Proposals and received zero passive engagements after upgrade and reads.

## 12. Explicit Legacy Continue Action

Proposal rows without engagement context display **Continue Bid Preparation**. `POST /proposals/{proposal_id}/continue` verifies strict ownership, reuses that exact Proposal, and records current `PREPARING` intent. Concurrent Continue requests reused one Proposal and created one engagement.

This is a new user action, not historical reconstruction.

## 13. Proposal Ownership

Customer list/detail access requires the exact authenticated `Proposal.user_id`, a valid Tender join, and a current CompanyProfile. The optional engagement context joins on `(user_id, company_profile_id, tender_id)`. Incomplete owner/profile rows are preserved but excluded from normal customer reads. Administrators receive no customer-data backdoor.

Same-name tenant list, detail, and Continue attempts remained isolated. Foreign IDs return `404`/safe guidance.

## 14. Proposal Status Semantics

Proposal status describes artifact work only:

- `DRAFT`: draft preparation artifact;
- `GENERATING`: artifact generation state;
- `COMPLETED`: completed preparation artifact;
- `SUBMITTED`: preserved legacy artifact enum value.

It is never the canonical pursuit lifecycle. Customer copy uses “Preparation,” “Draft,” and “Completed preparation.”

## 15. Legacy SUBMITTED Policy

No current Proposal writer sets `ProposalStatus.SUBMITTED`. The enum value remains for historical compatibility and is labeled **Legacy submitted artifact**. Readers preserve it without setting `TenderEngagement.SUBMITTED`.

## 16. PDF/DOCX Non-Inference

PDF and DOCX generation may set the Proposal artifact to `COMPLETED`. Neither endpoint imports or calls an engagement submission command. Browser and static acceptance proved the engagement remains unchanged.

## 17. My Tenders Purity

My Tenders continues to query `TenderEngagement JOIN Tender` only. A Proposal-only Tender remains absent. After an explicit Continue, the reused Proposal gains a current `PREPARING` engagement and the Tender then appears. Other Proposal-only rows remain absent.

## 18. Tenant Security

All Proposal reads and commands use canonical IDs and current-user ownership. Prepare additionally requires the owned CompanyProfile. Pending, rejected, disabled, and stale accounts remain governed by Sprint 3 dependencies. A same-name foreign Proposal cannot be listed, opened, continued, or used to create an engagement.

## 19. Concurrency

Disposable PostgreSQL 16 proved:

- concurrent new Prepare: one Proposal and one engagement;
- concurrent Prepare from SAVED: same Proposal and same engagement, ending PREPARING;
- concurrent legacy Continue: same legacy Proposal and one engagement;
- no expected-race HTTP/server error path;
- forced Proposal insert failure rolled the newly inserted PREPARING engagement back;
- retry after removing the forced failure succeeded safely.

## 20. Preflight

The read-only preflight now reports total Proposals, valid owner/Tender/Profile relationships, incomplete ownership, missing owner, missing Tender, owner without Profile, status counts, duplicate logical keys, and Proposal-with/without-engagement counts when the engagement table exists.

Read-only local-development result:

- total Proposals: 118;
- valid owner/Tender/Profile: 110;
- incomplete ownership: 8, all owner-without-profile;
- missing owner: 0;
- missing Tender: 0;
- duplicates: 0;
- statuses: 109 DRAFT and 9 COMPLETED;
- engagement context unavailable because this intentionally untouched local DB is still at Sprint 3 head.

No content was dumped and no repair was attempted.

## 21. Browser Acceptance

Real Chromium acceptance passed **20/20**:

1. navigation renamed to Bid Preparation;
2. legacy list redirects;
3. owned Proposal bookmark redirects;
4. legacy Tender-ID bookmark creates nothing;
5. canonical detail creates nothing;
6. none → PREPARING plus Proposal;
7. SAVED → PREPARING;
8. EVALUATING → PREPARING;
9. DISMISSED → PREPARING;
10. PREPARING remains PREPARING;
11. SUBMITTED/WON/LOST are not downgraded;
12. repeated Prepare reuses both rows;
13. Proposal-only legacy Tender stays absent from My Tenders;
14. explicit Continue reuses it and creates PREPARING;
15. COMPLETED does not infer SUBMITTED;
16. PDF/DOCX do not infer SUBMITTED;
17. same-name tenant isolation;
18. invalid/foreign Proposal ID is safe;
19. My Tenders remains engagement-only after Continue;
20. stale/revoked credentials are denied.

## 22. Deprecated Surfaces

The customer-facing My Bids label is removed. `/dashboard/bids`, `/dashboard/bids/{proposal_id}`, and `/dashboard/proposals` remain compatibility-only frontend surfaces. Existing backend Proposal APIs remain available for consumers; direct `POST /proposals` is explicitly artifact-only and does not create an engagement. New customer UI uses the canonical Prepare command.

## 23. Deferred Sprint 4.4 Work

Sprint 4.4 retains full engagement workflow controls: Mark Evaluating, Submitted, Won, Lost, Dismiss, Resume, correction UI, and broader Tender Details/product QA. Sprint 4.3 adds only Prepare/Continue integration and route/terminology reconciliation.

No Sprint 4.4 work, migration, deployment, or production access was performed.
