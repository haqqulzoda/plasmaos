# Sprint 5.2 Tender Details Read Model

## 1. Read Model Purpose

`GET /api/v1/tenders/{tender_id}/details` is a secondary, read-only summary for
the canonical Tender Details route. It composes already-persisted domain truth;
it does not create a workspace aggregate or duplicate the source Tender payload.

## 2. Hybrid Architecture

`GET /api/v1/tenders/{tender_id}` remains the fast source-fact authority.
`GET /api/v1/tenders/{tender_id}/details` adds bounded Project, contact,
document, Compliance, readiness, pursuit, and Bid Preparation summaries.
Authoritative models and their existing full-detail APIs remain unchanged.

## 3. Endpoint Contract

The response root contains `tender_id` and nine explicit sections:
`project_context`, `project_leadership`, `procurement_contacts`, `requirements`,
`documents`, `compliance`, `company_readiness`, `pursuit`, and
`bid_preparation`. It contains no generic root `status` and no full Tender body.

The endpoint requires the existing approved-pilot dependency. It resolves the
Tender with the same customer-visible source condition and returns 404 when the
Tender is not visible or does not exist.

## 4. Section Envelope

Every optional domain uses:

- `state`: `AVAILABLE`, `EMPTY`, or `UNAVAILABLE`
- `data`: an explicit section-specific DTO or `null`
- `reason_code`: an optional, non-sensitive code

`EMPTY` means expected absence. `UNAVAILABLE` means known degraded canonical
state. Foreign private objects are represented as absent; their existence is
never disclosed by a special authorization state or reason.

## 5. Tenant Context

Private reads use the authenticated `user_id` and the `CompanyProfile.id`
selected by the canonical one-profile-per-user relationship. No company name,
email, title, or other display string participates in ownership. Operators and
admins can pass the product gate but receive no customer-private data without
an owned profile/object tuple; no impersonation behavior was added.

## 6. Project Context

Project context follows `Tender -> TenderProject -> Project`. The DTO whitelists
identity, source, compact geography/status/date fields, enrichment state, and
last enrichment time. `queued`/pending remains truthful and successful;
`failed` or `source_unavailable` produces an `UNAVAILABLE` project section while
retaining the safe canonical project identity. No read enqueues enrichment.

## 7. Project Leadership

Leadership comes only from `ProjectRoleAssignment`. It retains role ID, source,
native and canonical role, source URL, current/history signal, and observation
times. It is never relabeled as a Tender procurement contact. At most 12 roles
are returned, ordered current-first and then by most recent observation.

## 8. Procurement Contacts

This section reuses the local canonical Tender contact/source-metadata parser.
It never invokes source overrides or network fallbacks. Contact person, agency,
source-legitimate contact fields, submission details, and official Tender source
URL are kept separate from Project roles.

## 9. Requirements

The current database has no reliable source-native structured requirement row
with per-item provenance. The response therefore sets
`source_native_available=false`. When an owned latest `AnalysisVersion` contains
bounded structured requirements, they are labeled `ANALYSIS_DERIVED`; otherwise
the section is `EMPTY`. It never upgrades AI interpretation to source metadata.

## 10. Documents

The summary returns at most 25 conservatively classified
`PUBLIC_SOURCE_METADATA` rows. Safe fields are document ID, display name, type,
source system, coarse availability, size, MIME type, and creation time. It does
not expose a URL, storage location, parser text, hash, token, or credential.

## 11. Document Authorization

Document categories are reconciled as follows:

| Category | Details metadata | Download/open authority |
|---|---:|---|
| Public/source document metadata with explicit HTTP(S) source identity and type | Visible to an approved viewer of the Tender | Existing document endpoint; unchanged and potentially stricter |
| Tenant-private Proposal artifact | Not sourced from `TenderDocument`; omitted | Existing Proposal authorization |
| Tenant-private readiness document | Counts only in the owned readiness summary | Existing readiness authorization |
| Internal storage artifact | Never exposed as metadata or path | Existing document endpoint |
| Unknown/legacy TenderDocument | Omitted; aggregate omitted count only | Existing endpoint; no new grant |
| Foreign tenant private document/artifact | Omitted | Denied by existing owner checks |

Tender visibility, engagement, or Proposal existence does not mint document
download authority. The existing `/documents` reader and download/open flows
were not weakened.

## 12. Compliance

Compliance is a small summary: parent analysis ID, immutable version number,
execution state, `compliance_completeness`, canonical decision label when
present, issue count, coverage signal, version origin, override-presence signal,
and version times. Full results and evidence remain in the Compliance workbench.

`FAILED` is `UNAVAILABLE` with decision label `FAILED`; it can never render as
compliant. Partial snapshots retain `PARTIAL`. `LEGACY_BACKFILL` remains visible
as the version origin. A zero-version owned parent is a safe
`COMPLIANCE_HISTORY_UNAVAILABLE` section and is logged without evidence content.

## 13. AnalysisVersion Authority

The canonical newest-owned-parent reader selects the parent, including its
existing multi-parent rule. The canonical version-aware reader selects the
highest authorized version. Customer results come only from
`AnalysisVersion.result_snapshot`; `TenderAnalysis.analysis_json` and parent
content hashes are not read as result authority. Risk override history is not
mutated; `override_applied` reports the existing parent seal only.

## 14. Company Readiness

One aggregate query returns supported evidence counts: certifications and
expiry, licenses and active state, canonical credentials and expiry, readiness
documents by persisted status, and financial-history years. It returns no score,
file URL, document name, banking/personal field, or raw content. A profile with
no evidence is available with zero counts; no owned profile is `EMPTY`.

## 15. Pursuit

Pursuit reads only the exact `(user_id, company_profile_id, tender_id)`
`TenderEngagement`. It returns engagement ID, `engagement_status`, origin,
status-change time, and backend-derived allowed actions. No engagement is
`EMPTY`; Proposal existence is never used to infer pursuit.

## 16. Bid Preparation

Bid Preparation reads only a Proposal owned by `(user_id, tender_id)`, the
existing model's authoritative owner tuple. It returns Proposal ID,
`proposal_status`, creation time, and the canonical Proposal route identifier.
It exposes no generated file, structured data, margin, evidence, or storage
field, and it does not create or repair a Proposal.

## 17. Proposal-Only Legacy Case

An owned Proposal with no TenderEngagement returns `pursuit=EMPTY` and
`bid_preparation=AVAILABLE`. Conversely, engagement-only returns an available
pursuit and empty Bid Preparation. Compliance-only returns available Compliance
without implying either other domain.

## 18. Failure Isolation

Expected domain absence maps to `EMPTY`; known project or Compliance degradation
maps to `UNAVAILABLE`; foreign private data maps to absence. Only the known
zero-version integrity exception is converted to a section result. SQL/database
errors are not broadly caught and therefore remain real server failures rather
than misleading empty sections.

## 19. Query Composition

Composition is sequential on one `AsyncSession`; unsafe concurrent operations on
the same session are not used. The representative all-domain path executes:

1. visible Tender
2. owned profile
3. linked Project
4. role count
5. bounded roles
6. document classification counts
7. bounded public document metadata
8. canonical owned Compliance parent
9. latest authorized AnalysisVersion
10. version document-snapshot select-in read
11. readiness aggregate
12. exact owned engagement
13. exact owned Proposal

No query is issued per child row.

## 20. Query Count / Performance

Disposable PostgreSQL 16 at Alembic head
`20260828_0003_s4_1_tender_engagement_foundation` measured exactly 13 SQL
statements. The count remained 13 after expansion from 1 to 25 public documents,
1 to 10 Project roles, and 1 to 21 owned readiness documents. The measured
expanded call was 37.155 ms in the local test environment. This is a proof of
bounded composition, not a production latency target.

## 21. Response Bounds

Limits are 25 documents, 12 Project roles, and 12 derived requirements. Each
bounded collection reports total/returned counts and truncation. The measured
representative 25-document response was 15,265 bytes. No full Project history,
document content, Compliance snapshots/evidence, readiness files, or Proposal
body is included.

## 22. Passive Read Guarantee

The endpoint graph contains no add, flush, commit, insert, update, delete,
enqueue, source fetch, LLM, Project enrichment, document sync, or Decision
Snapshot call. PostgreSQL fingerprints and SQLAlchemy new/dirty/deleted sets were
checked before and after repeated and concurrent calls. Counts, Tender dates,
and engagement timestamps remained unchanged. The Sprint 5.1 UzEx response-only
date override code is not called by this secondary endpoint.

## 23. Tenant Security

Source/project/contact/public metadata follows visible Tender access. Compliance,
readiness, pursuit, and Bid Preparation independently enforce their canonical
owner IDs. A foreign viewer sees no foreign private IDs, states, counts, or
timestamps. Admin/operator product access does not create a customer-data
backdoor.

## 24. Same-Name Tenant Proof

Two PostgreSQL tenants named `Acme Engineering` were seeded for the same Tender.
Tenant A received PREPARING, its COMPLETED Proposal, latest v2 Compliance, and A's
readiness. Tenant B received SAVED, no Proposal, FAILED/PARTIAL LEGACY_BACKFILL
Compliance, and B's readiness. No display-name matching or cross-contamination
occurred.

## 25. Representative Matrix

The endpoint proof covers Tender-only, Project-only, Compliance-only,
engagement-only, Proposal-only, all domains, pending Project, terminal Project
failure, failed/partial/legacy Compliance, zero-version anomaly, same-name
tenants, foreign viewer, and platform admin. It also verifies Project Leader A
and Procurement Contact B remain separate.

## 26. Preflight

The read-only preflight now reports count-only Tender Details metrics: total
Tenders; with/without Project; with engagement, Proposal, and Compliance;
Proposal-only, engagement-only, Compliance-only, engagement+Proposal, and all
private domains; broken Project/Proposal/engagement Tender references; and
zero-version analysis parents. It uses `SELECT` in the existing explicit
read-only transaction, treats optional absence as normal, and performs no repair.

## 27. Regression Results

Focused S5.2/S5.1 tests passed 10/10. The combined Sprint 5/Sprint 4 gate passed
83 tests and four subtests; Sprint 3 passed 54 tests and 54 subtests; Sprint 2
passed 52 tests; the applicable Sprint 1/World Bank gate passed 59 tests. The
connector gate passed 195 tests and four subtests with its one approved storage
fixture skip. All Sprint 4, Sprint 3, Sprint 2, and Sprint 1 disposable
PostgreSQL matrices passed. The dedicated S5.2 PostgreSQL matrix, local-existing
repeatability check, OpenAPI/startup check, preflight, and static audits passed.
No migration was created; `alembic check` is clean at the expected head.

One older all-Sprint-1 batch test still asserts the pre-Sprint-3.5 label and
unbounded approval-queue UI that Sprint 3.5 intentionally replaced with the
Accounts surface. It is not part of the Project/World Bank regression gate and
the newer frontend was not reverted for S5.2.

## 28. Sprint 5.3 Frontend Contract

Sprint 5.3 may fetch base Tender facts and this secondary summary independently.
The UI can render each envelope directly, use explicit status fields, use
backend-provided engagement actions, link Proposal by `detail_route_id`, and
route full Compliance/document operations to their existing APIs. The UI must
not infer pursuit from Proposal or treat project leadership as procurement
contacts.

## 29. Deferred Sprint 5.4 Risks

The existing Bid Preparation page-load document synchronization policy remains
deferred because the new endpoint neither invokes nor depends on it. Legacy
compatibility routes, hidden/redundant frontend Decision Snapshot loading,
workspace cleanup, redirect reconciliation, and dead component cleanup also
remain outside Sprint 5.2.
