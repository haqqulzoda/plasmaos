# Sprint 14.3 — Tender Details UI/UX refinement

## Status

Sprint 14.3 UI and Sprint 14.3R competitor remediation are implemented. The preflight ledger below is historical; the appended Sprint 14.3R section records the current competitor authority and release closure.

## Preflight: mockup/report to current authority

| Mockup area | Existing route/component | Canonical authority | Action | Supported fields and states | Deliberate omissions |
| --- | --- | --- | --- | --- | --- |
| Header and utilities | `/dashboard/tenders/[tenderId]`; Explorer return state | `GET /tenders/{id}` | Back restores Explorer state; safe source link; Compliance route | Source, lifecycle, reference, title, buyer, deadline, budget/price display, geography; tender loading/404/denied/error | No invented facts or long source description |
| Pursuit | `TenderEngagementPanel` | `details.pursuit`; TenderEngagement | Explicit save/status changes and Prepare Bid | Saved state and allowed workflow actions; empty/error | Recommendation dismissal is unrelated; no automatic save/proposal |
| Compliance and readiness | Details composed projection | `details.compliance`, `details.company_readiness` | Open Compliance; Open Readiness Vault | Analysis state/completeness/issues/version and company document/credential counts; independent empty/unavailable | No derived percentages or critical-record classification |
| AI Recommendation | Details composed projection | `details.recommendation`; tender source classification | No mutation | Stored score/rationale and source category/method/notice type; empty | No generated score, rationale or method |
| Project Context | Details composed projection | `details.project_context`, canonical Project/TenderProject join | No mutation | Name, source project ID/status, geography, approval/closing dates; empty/preparing/unavailable | Objective and sector absent from DTO/model; no enrichment |
| Project Leadership | Details composed projection | `details.project_leadership`, stored ProjectRole | No mutation | Current/historical source-backed display names and source; empty/unavailable | No inferred role, title, employer or contact status |
| Tender Documents | Details composed projection | `details.documents`, Sprint 13 lifecycle | Explicit `POST /tenders/{id}/sync-docs`; READY per-row safe local download | Bounded metadata rows and remote/queued/downloading/processing/ready/partial/failed; separate failed/empty states | No per-file remote acquisition, eager download or auto-analysis |
| Competitor Intelligence | Details composed projection | `details.competitor_intelligence`, Sprint 12R stored evidence | Safe Open evidence link only | Winner/participant/similar actor, source, region, confidence; available/empty/unavailable | No live lookup, enrichment, current-tender participation inference |
| Procurement Contacts | Details composed projection | `details.procurement_contacts`, tender-source metadata | No mutation | Person, email, phone, address, submission method/deadlines, procedure; empty/unavailable | No leadership-to-contact inference |
| Bid Preparation | Details composed projection and existing PrepareBidButton | `details.bid_preparation`, Proposal | Explicit Prepare Bid or open existing Proposal | Existing proposal status/route; not started | No collaboration, tasking or progress-tracking claim |

The two existing initial requests are bounded local reads. The composed Details response supplies all secondary sections without frontend fan-out. Section-level `AVAILABLE`, `EMPTY`, and `UNAVAILABLE` states remain authoritative. User-visible section failures must not discard independent successful sections.

## Planned hierarchy and constraints

Back/utility, identity, decision row, Project Context, Project Leadership, Tender Documents, Competitor Intelligence, Procurement Contacts, Bid Preparation. The global shell is unchanged. No migrations, backend changes, production access or deployment are planned. Existing analysis-derived requirements remain available in a compact disclosure under documents so accepted evidence access is not lost.

## 1. Status

At the original Sprint 14.3 handoff, the UI and scoped regressions passed but full release acceptance was deferred for lack of an explicitly disposable PostgreSQL/Redis target. Sprint 14.3R closes that gap in the appended verification section. No production system was accessed and nothing was deployed.

## 2. Mockup/report mapping

The preflight table above is the field/action/state ledger. The approved 874 × 1799 mockup establishes decision-first hierarchy and the report establishes semantics. Mockup values are illustrative only; the browser proof uses deterministic, different fixture values. The actual page consumes the existing Tender and composed Tender Details responses, with no added backend projection.

## 3. Page hierarchy

Back/utility → identity → Pursuit, Compliance/readiness and AI Recommendation → Project Context → Project Leadership → Tender Documents → Competitor Intelligence → Procurement Contacts → Bid Preparation. The long visible source description and seven-item sticky anchor bar are gone. The underlying source description remains canonical data, accessible from source/evidence workflows.

## 4. Header and utility actions

Explorer return state is restored from the existing validated session record. Header facts are source, lifecycle, reference, title, buyer, deadline, value and location, with existing truthful fallbacks. Open source notice validates the canonical URL with `safeSourceUrl`; unsupported schemes/credentialed URLs are omitted. Known source names have a display-only fallback if the catalog read is unavailable.

## 5. Pursuit

The page-specific decision-card variant of `TenderEngagementPanel` reuses the existing explicit Save, workflow actions and `PrepareBidButton`. No engagement or Proposal is created on page load. Pursuit state and Tender source lifecycle stay separate.

## 6. Compliance and company readiness

Compliance uses the latest composed immutable analysis summary and distinguishes failed, partial, legacy and available states. Company readiness uses its separate profile-derived available/total and missing-document counts. Open Compliance and Open Readiness Vault retain their existing routes. No score, percentage, critical-record class or analysis auto-start was added.

## 7. AI Recommendation

The card uses only the stored Recommendation score/rationale/dismissal flag and existing Tender classification, method and notice type. Missing Recommendation is explicit. No client-side scoring, AI call or recommendation mutation occurs.

## 8. Project Context

Only canonical Project/TenderProject name, status, geography and available approval/closing dates are shown. Preparing and unavailable states remain truthful. No page-load enrichment is triggered.

## 9. Project Leadership and provenance

Leadership is a separate names-only source-backed table, with section-level source provenance and an optional historical-name disclosure. Native/canonical role labels, inferred titles/employers and procurement-contact claims are not rendered. Truncation remains explicit.

## 10. Tender Documents and Sprint 13 preservation

The bounded composed document list is a table. Remote rows show metadata only; a single explicit bulk action invokes the existing `POST /tenders/{id}/sync-docs`. The bounded 150-attempt/2-second status poller starts only for an active job. Per-row binary access uses the existing safe local download route only when both availability is `AVAILABLE` and acquisition state is `READY`. Partial/failed states and retry remain visible. No per-row remote download, eager acquisition, auto-parse or auto-analysis was added. Bounded analysis-derived requirements remain accessible in a collapsed provenance-labelled disclosure.

## 11. Competitor Intelligence and Sprint 12R preservation

Only the stored composed competitor evidence is rendered, with historical outcome, source, geography and safe evidence URL. The explanatory copy explicitly disclaims current-tender participation. AVAILABLE/EMPTY/UNAVAILABLE states remain truthful. No live lookup, enrichment, source call or write was added.

## 12. Procurement Contacts

The separate section renders source-backed person, email, phone, address, submission method/deadlines and procedure. Missing facts use source-truthful fallbacks. Project Leadership is never mapped into a procurement contact.

## 13. Bid Preparation

The final compact strip opens an existing Proposal by its route identifier or invokes explicit Prepare Bid for an actionable Tender. Unsupported collaboration, task assignment and progress-tracking language from the mockup was replaced with existing product copy.

## 14. Loading and partial states

The Tender shell loads independently of the composed detail projection. Decision and evidence sections have local skeletons. An initial Details failure shows a retry action while retaining the Tender identity; a later refresh failure retains the last successful composed projection. Each composed section renders its own available, empty or unavailable truth. Remote/queued/downloading/processing/ready/partial/failed documents are distinct.

## 15. Passivity and request/query budgets

Initial page code has exactly two Tender-specific reads (`GET /tenders/{id}` and `GET /tenders/{id}/details`). A third GET is conditional bounded polling after an existing active document job. The page has one POST call site, guarded by explicit bulk acquisition click; pursuit/Proposal mutations remain guarded by their existing buttons. The focused browser proof observed zero Tender writes on passive load. Backend/domain code, SQL projections, caps and query budget were not changed; Sprint 12R and Sprint 13 focused backend regressions passed. A live PostgreSQL query-budget proof is deferred with the disposable-DB release gate.

## 16. Responsive, locales, RTL and accessibility

All four locales have exact new-key and placeholder parity. English, Uzbek, Russian and Arabic were checked in Chromium at 320/390/768/1440 CSS viewports: 16 combinations, no page-level overflow, correct Arabic `dir=rtl`, and mobile decision/evidence order. Tables become labeled rows at narrow widths. Source/person/company text is verbatim and bidi-isolated; technical IDs, email and phone retain LTR isolation. Four representative EN/AR axe scans at 390/1440 reported zero serious/critical WCAG 2 A/AA/2.1 AA findings. Semantic headings, table headers, external-link semantics and keyboard buttons are retained.

## 17. Frontend, backend, browser and release totals

Historical Sprint 14.3 handoff snapshot; the appended Sprint 14.3R verification section supersedes these deferred release results.

| Gate | Result |
| --- | --- |
| Focused Tender Details frontend static | 16/16 pass |
| Full frontend static | 233/233 pass |
| TypeScript, full ESLint, production build | Pass |
| Literal, RTL, design-token, legacy-style audits | Pass |
| Focused S5.1/S5.2/S12/S12R/S13/analysis/readiness backend | 44/44 pass |
| Broad backend excluding unavailable-service/installed-pin tests | 758 pass, 1 skip, 2 deselected, 100 subtests pass |
| Sprint 14.3 Chromium browser | [35/35 pass](audits/s14_3/browser/results.json) |
| Maintained production-build release browser | [145/145 pass](audits/s14_3/release_browser/results.json), no external requests |
| Four representative EN/AR axe scans | Zero serious/critical findings |
| Alembic heads | `20260912_0001_s10_5_communications` (single head) |
| `npm audit --audit-level=high`; `pip check` | 0 npm vulnerabilities; no broken Python requirements |

The unfiltered full backend run ended at **756 passed, 1 skipped, 4 failed, 10 errors** before two obsolete static assertions were updated and passed separately (54/54). Of the remaining environment failures, ten S10.5 setup errors and the permanent release script require an explicitly named, disposable loopback PostgreSQL database; one test requires Redis; one checks an installed Python version against `constraints.txt` and found 1.18.4 versus 1.19.2. No local PostgreSQL/Redis server was present. Alembic `current`, `check`, schema/data preflight and the full permanent release gate therefore were not run. No guard was bypassed or database target invented.

## 18. Bundle impact

No dependency or backend addition. The Tender Details page source is 29,549 bytes versus 56,629 bytes in repository HEAD, but that is **not** a reliable baseline bundle delta because accepted Sprint 11–14.2 work is uncommitted. A production build passed; a like-for-like before/after client-chunk byte comparison was not available. New composition CSS uses existing design tokens.

## 19. Exact files changed for Sprint 14.3

- UI: `frontend/app/dashboard/tenders/[tenderId]/page.tsx`, `frontend/components/tenders/TenderEngagementPanel.tsx`, `frontend/components/customer/pages.css`.
- Locale: `frontend/messages/{en,uz,ru,ar}/tenderDetails.json`.
- Frontend tests: `frontend/tests/tender-details.test.mjs`, `project-context.test.mjs`, `s7-3-p0-localization.test.mjs`, `s8-3-arabic-rtl.test.mjs`, `tender-cleanup.test.mjs`, `tender-details-browser-acceptance.py`, `s14-3-browser-acceptance.py`, `s14-3-visual-compare.py`.
- Backend static assertions only: `backend/test_s0_5b1_unknown_actionability.py`, `backend/test_tender_document_status.py`.
- Evidence/report: this file, `design-qa.md`, `.gitignore` exceptions, `docs/audits/s14_3/design-comparison.png`, selected browser screenshots/results/axe JSON and release-browser results.

No backend application code, domain model, migration, Compliance Analysis UI or global shell was changed.

## 20. Deliberate mockup deviations

- Objective and sector are absent from the canonical Project Details DTO/model; project status and dates use available facts instead.
- Compliance/readiness percentages and “critical records” are unsupported; factual analysis state and company document counts replace them.
- “Download all documents” maps to the one explicit Sprint 13 remote-acquisition command and does not appear for already READY files because no safe ZIP/bulk binary route exists. READY rows use the existing safe individual download route.
- At the original Sprint 14.3 handoff, competitor confidence and long reasons were omitted from the compact table; Sprint 14.3R adds a concise “Why relevant” column while keeping confidence out of the UI.
- Source classification is folded into Recommendation; analysis-derived requirements move to a disclosure. Unsupported collaboration copy is omitted.
- Fixture titles, dates, counts and number of rows differ from mockup examples. The accepted shell is preserved.

## 21. Remaining Tender Details issues

No observed P0/P1/P2 UI, responsive or accessibility defect in the supported design scope at the Sprint 14.3 handoff. Release certification was deferred then and is revisited in the Sprint 14.3R section below. The old stand-alone browser entry point now delegates to the Sprint 14.3 harness so it validates the current page rather than obsolete tabs.

## 22. Sprint 14.4 entry contract

First close the deferred local release/database checks against a disposable target, then start Sprint 14.4 only under its own explicit brief. Sprint 14.3 introduced no authority for further page redesign, migration, production access or deployment.

## Sprint 14.3R — Competitor Intelligence root-cause map (pre-remediation)

The current authority chain is source adapter → canonical Tender/source metadata → a bounded related-Tender scan plus optional source-specific live award/deal fetch → `_extract_public_competitor_records`/`_group_competitor_records` → a Plasma-owned metadata cache populated by source refresh → `/details` and `/competitors`. The chain has several independent failure modes:

| Source | Available public evidence in current connector | Current gap |
| --- | --- | --- |
| World Bank | Procurement notices, project identifiers, contract-award notice text; separate award endpoint parses named awarded/evaluated/rejected bidders | Latest 80 awards are selected by broad inferred service category, without a project/buyer/country-qualified target match before a single list is copied to every target in that category. Incoming active notices normally contain no bidder names. |
| UzEx | Tender/lot metadata and a separate deals list naming a provider and buyer | A category-wide deal list is copied to targets, even if the buyer/lot/market relationship is absent. The latest 80 deals cannot establish complete historical coverage. |
| GIZ | Public notice and document-discovery metadata; [GIZ says it publishes contract awards on its platform/TED](https://www.giz.de/en/partner/contractor) | The connector does not extract named award parties from those publications; document discovery is not competitor evidence. Source-refresh competitor enrichment skips GIZ. |
| ADB | Project-linked notices and awarded-contract RSS; [ADB project pages can identify contractors](https://www.adb.org/projects/41192-013/main) | RSS titles normally do not identify a winning company; the parser correctly refuses to invent one, but the connector does not extract the project-page contractor table. Category-wide results could previously be copied where a title names a winner. |
| EBRD | Public notice/project metadata; [ECEPP contract-award notices can name contracting parties](https://ecepp.ebrd.com/delta/viewNotice.html?displayNoticeId=41493497) | The current connector excludes award notices and has some detail-access restrictions; no verified bidder/award extraction or source-refresh competitor enrichment exists. Access restrictions must not be bypassed or reported as a negative competitor finding. |

Shared root causes: `_extract_public_competitor_records` accepts any whitelisted participant/winner field from a related Tender even when the match is merely a broad category; unknown category can fall back to buyer **or** sector **or** category; `similar_market_actor` can be promoted by repeated appearances without procurement evidence; `_group_competitor_records` dedupes only exact casefolded names within a service; source URLs are optional; and the cache carries records but no evaluated/unevaluated status. A missing cache and an evaluated source with no qualifying history both become an ambiguous empty section. `/details` is passive, but `/competitors` still defaults to live source calls. These are authority problems, not missing UI rows. The remediation below must qualify evidence before caching or display, preserve a specific relevance reason, and keep the customer read path network/write free.

### Remediation and qualification

- Public historical *winner* or *participant* evidence must have a validated HTTPS link on the official source domain, a source-local Tender relationship, and a safe company name. Bare `similar_market_actor` labels are rejected, even if repeated. No cross-source organization merge is attempted because there is no safe canonical identity key.
- `DIRECT`: same project and aligned service/buyer, or same buyer, service area and compatible country. `STRONG`: same inferred service, country, procurement category, sector or method, and evidence no older than five years. A country contradiction rejects the candidate. No title-only or opaque score can qualify it. The generated rationale names the historical procurement and *why it relates to this target*, never implying current participation.
- The existing v1 cache remains parseable for compatibility, but every cached record is requalified at read time; broad legacy entries therefore disappear. Source refresh now qualifies records **per target**, writes evaluated-empty metadata only after a successful source read, preserves prior qualified evidence on empty/transient source results, and skips unchanged records. An outage raises out of the strict enrichment fetch without committing a partial cache. Dry-run still bypasses enrichment. The source adapters and refresh retain up to 80 bounded historical candidates before per-target qualification, then cap the qualified response at 30; this prevents a relevant candidate in positions 31–80 from being dropped prematurely. World Bank, UzEx and ADB are supported by the existing bounded award/deal adapters; GIZ/EBRD remain `UNAVAILABLE` until a verified public award adapter is implemented.
- `AVAILABLE` means ≥1 qualified record; `INSUFFICIENT_EVIDENCE` means a successful evaluated cache or historical bidder/award fields were inspected but none qualified; `UNAVAILABLE` means no authority evaluation occurred. Thus missing enrichment is not presented as “no competitors.” GIZ and EBRD short-circuit to `UNAVAILABLE` even if an old cache marker exists, because their award authority is still unverified. `/details`, `/decision-snapshot`, and `/competitors` now default to stored-only competitor projection. The response remains bounded to 30 companies, related history to 250 visible Tenders, source rows to 80 per category, and refresh targets to 2,000. There is no per-competitor query or new migration.
- The accepted Sprint 14.3 table gains a compact “Why relevant” column. It still labels historical outcomes, retains source/region/evidence, and disclaims current participation. All four locales distinguish insufficient evidence from unavailable authority.

### Source-by-source fixture review and coverage

Official-source context: [World Bank's award form requires bidder details](https://thedocs.worldbank.org/en/doc/682671521470794188-0290022018/original/ProcurementClientConnectionsQuickRefAllNoticesv2Feb12.pdf); [UzEx's provider guide shows winner and participant information by lot](https://etender.uzex.uz/assets/file/etender-instruction_for_provider_compressed.pdf); [ADB publishes awarded contracts and shortlisted consulting firms](https://www.adb.org/business/project-procurement/services); [GIZ publishes contract awards](https://www.giz.de/en/partner/contractor); [EBRD ECEPP publishes named contract parties](https://ecepp.ebrd.com/delta/viewNotice.html?displayNoticeId=41493497). These sites establish that public evidence exists in some contexts; they do **not** prove the current Plasma connector has ingested it. Fixture evidence URLs are official-domain-shaped, not claims that the synthetic company appears at a live notice URL.

The reproducible `backend/scripts/audit_s14_3r_competitor_coverage.py` audit (`cd backend && python -m scripts.audit_s14_3r_competitor_coverage`) uses 15 deliberately constructed local Tenders (three per source). It is **not deployed or real-corpus coverage**. The diagnostic outputs 20.0% `AVAILABLE`, 20.0% `INSUFFICIENT_EVIDENCE`, 60.0% `UNAVAILABLE`, and 0.2 qualified companies per Tender. World Bank, UzEx and ADB each have one of each state (33.3% per state); GIZ and EBRD are 100% `UNAVAILABLE` under current connector authority. Of ten fixture historical candidates, three unrelated/generic records are rejected (30.0%) and four GIZ/EBRD records are withheld because their connector authority is unverified (40.0%). All three qualified fixture records have an allowed official-domain HTTPS URL and a historical-procurement-specific rationale (3/3 each). The existing `backend/seed_tenders.py` repository corpus has five UzEx mock Tenders without public bidder/award evidence or cache: 0% `AVAILABLE`, 0% `INSUFFICIENT_EVIDENCE`, 100% `UNAVAILABLE`. Neither sample measures the running app's Tender database; that existing database was not accessed, and the isolated release database is disposable. No arbitrary pass threshold is asserted.

The source-by-source test samples prove: World Bank/UzEx/ADB same-buyer historical award metadata can qualify; a different-country candidate cannot; a recent same-country/category/sector procurement can qualify as `STRONG`; GIZ document-discovery-like or unverified award metadata does not qualify; EBRD unverified metadata does not qualify despite official public award pages existing. Invalid schemes, credentialed links and wrong-domain links are rejected. Case/punctuation duplicates collapse without fuzzy cross-source merging. An empty cache, evaluated-empty cache, stale generic cache, outage, idempotent refresh, candidate position 31, legacy GIZ/EBRD cache markers, 250-related scan limit, and zero source calls from the stored Details builder have permanent tests.

### Verification and remaining limitations

The final-code, uninterrupted `bash scripts/run_release_gate.sh all` exited **0** in an isolated release environment: a Python environment installed from `backend/requirements.txt` under `backend/constraints.txt`, disposable PostgreSQL 16 at `127.0.0.1:15432` (`plasma_s143r_pg`), and disposable Redis 7 at `127.0.0.1:16379` (`plasma_s143r_redis`). The release guard was supplied the exact disposable database name and confirmation. The existing running app database and Redis were not used or modified.

| Final-code gate | Result |
| --- | --- |
| Focused competitor regression | 53/53 pass |
| Full backend | 794 passed, 1 skipped, 100 subtests passed |
| Security | 118 passed |
| Analysis | 50 passed, 12 subtests passed |
| Connectors | 198 passed, 1 skipped, 6 subtests passed |
| Sprint 12R and Sprint 13 regressions | Included in the passing full backend suite; targeted competitor/passivity suite also passed |
| Alembic | Single head `20260912_0001_s10_5_communications`; heads, current, check and schema preflight pass |
| Release read/performance | All nine 1k/10k/100k scale cases pass; no case exceeds five queries or 25 filesystem checks |
| Frontend | 233/233 static pass; typecheck, lint, RTL audit and production build pass |
| Tender Details Chromium | [35/35 pass](audits/s14_3/browser/results.json) |
| Maintained release Chromium | [145/145 pass](audits/s14_3r/release_browser/results.json), controlled local fixtures |
| Dependencies | `pip check` clean; `npm audit --audit-level=high` found zero vulnerabilities |

The 35-case Tender Details browser result was obtained after the UI change and before the final backend-only candidate-window safeguards; the frontend code did not change afterward. A repeat attempt of that narrower harness was inconclusive: one local dev-server navigation timeout was followed by a WSL-to-Windows process-bridge failure (`UtilAcceptVsock: accept4 failed 110`), also reproduced by a trivial `cmd.exe` command. It is not counted as a new pass. The uninterrupted permanent release wrapper's 145-case production-build Chromium run passed on the final code. No migration was added. No production access or deployment occurred. The release service containers are disposable and are stopped after verification.

Remaining authority gaps are material: the bounded latest-80 award/deal windows are not exhaustive historical coverage; ADB project-page contractor tables, [GIZ award publications](https://www.giz.de/en/partner/contractor) and [EBRD public award notices](https://ecepp.ebrd.com/delta/viewNotice.html?displayNoticeId=41493497) are not yet normalized into a safe canonical evidence stream; aliases/transliterations are not merged across sources; and the running app's real Tender corpus was deliberately not accessed, so its coverage is unknown. The isolated DB scale checks do not measure production timing. Sprint 14.4 requires a separate explicit brief and should not be started under Sprint 14.3R.

### Sprint 14.3R exact changed-file ledger

- Backend authority and projection: `backend/app/api/endpoints/tenders.py`, `backend/app/schemas/tender.py`, `backend/app/schemas/tender_details.py`, `backend/app/services/competitor_cache.py`, `backend/app/services/tender_details.py`.
- Backend verification: `backend/test_s14_3r_competitor_intelligence.py`, `backend/test_s4_2_competitor_intelligence.py`, `backend/test_s12_competitor_section_restoration.py`, `backend/test_s12r_competitor_passivity.py`, `backend/scripts/audit_s14_3r_competitor_coverage.py`, `backend/scripts/run_connector_regression_gate.sh`.
- Tender Details UI and validation: `frontend/app/dashboard/tenders/[tenderId]/page.tsx`, `frontend/types/tender-details.ts`, `frontend/messages/{en,uz,ru,ar}/tenderDetails.json`, `frontend/tests/tender-details.test.mjs`, `frontend/tests/tender-details-browser-acceptance.py`, `frontend/tests/s14-3-browser-acceptance.py`.
- Evidence/documentation: this document, `.gitignore` audit-result allowlist, and `docs/audits/s14_3r/release_browser/results.json`.

The acceptance decision is **PASS for Sprint 14.3R's bounded, truthfully labeled implementation and local release gate**. It is not a claim that every real Tender has identified competitors. GIZ/EBRD remain explicitly unavailable pending verified adapters, and live-corpus coverage remains unmeasured. No Compliance UI/Sprint 14.4 work was begun.
