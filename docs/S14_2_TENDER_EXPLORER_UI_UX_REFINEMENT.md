# Sprint 14.2 — Tender Explorer UI/UX refinement

## Preflight mapping (before implementation)

The supplied image establishes hierarchy and density; all counts, tenders, scores and actions must come from the existing Explorer read model, never from the illustrative pixels.

| Mockup element | Existing route/component | Canonical data/action | Support |
| --- | --- | --- | --- |
| Search | `/dashboard/tenders`, `SearchField` | `GET /explorer/tenders?q=` | Supported; current debounced, bounded query |
| Source, region/country, status, category, deadline filters | Explorer URL state and filters | Existing Explorer query parameters | Supported; retain country/service/document/value advanced filters |
| Match-quality filter | None | No canonical query parameter | Unsupported; omit |
| Active filter chips / Clear all | Explorer URL state | Parameter removal / documented defaults | Supported |
| Result count and sort | Explorer response / query | `total`, `offset`, `limit`, backend sort | Supported; `best_match` only in recommendation views |
| Match score | Explorer row | `Recommendation.match_score` | Supported only when recommendation exists |
| Bookmark | Explorer row; existing engagement action | TenderEngagement save, dismiss allowed only for SAVED | Supported; separate from Recommendation dismissal |
| View tender | Explorer row | `/dashboard/tenders/{id}` | Supported, including return state |
| Open source | Explorer row | `tender.source_url` | Supported only for safe authoritative HTTPS/HTTP URLs |
| Source identity | Explorer row / source catalog | Source system and display name; S14.1 approved local logos | Supported with neutral fallback |
| Pagination | Explorer response | Bounded `limit`/`offset` | Supported; 25 per page |
| All / Recommended / Dismissed / New | Explorer tabs and New control | Existing view, recommendation and SR-3 `new_only` | Supported |
| Short summary | Existing Tender.description, not in Explorer projection | Read-only bounded projection | Additive API projection retained; later follow-up removes the card display |
| Saved searches CTA/module | None | No ownership, persistence or API | Unsupported; omit and use full-width workspace |
| List / Compact toggle | List only | No canonical Compact mode/persistence | Unsupported; omit |
| Partial source failure | Source refresh provider | Authoritative source status metadata | Disclose only when a source reports a partial/failure; do not claim global completeness |

No migration, deployment, production access, source retrieval, recommendation generation or changes to Tender Details are in scope.

## Implementation

The accepted discovery hierarchy is now rendered in the unchanged customer shell: header and secondary source Refresh; a full-width search/filter workspace; All, Recommended and Dismissed tabs with the existing SR-3 New switch; removable active-filter chips; a distinct count/sort/page toolbar; then bounded result rows. The search remains URL-backed and debounced by 350 ms. Existing backend query parameters, sort contracts, tabs and 25-row pagination remain authoritative. The default status is explicitly Open in both the filter and chip; choosing All or another status exposes historical/unknown tenders.

Each result has four desktop zones: source identity, tender information, factual status/deadline and match/actions. Approved local source marks from Sprint 14.1 are used only for World Bank, ADB, GIZ, EBRD and UZEX; all other sources use the existing neutral fallback. Titles, source IDs and origin content stay verbatim, while metadata is isolated for RTL. The original result summary was a read-only, whitespace-normalized, 240-character projection of the already stored `Tender.description`; the later card-description follow-up below removes its visual display without changing that API projection. Up to four existing metadata values become neutral tags. Deadline text is derived from the authoritative timestamp and never overrides source lifecycle status. A Recommendation score appears only when a Recommendation exists. The primary View tender action, safe authoritative Open source link, independent Save/Unsave bookmark and Preview drawer are separately keyboard-accessible. The drawer retains Recommendation dismissal/restore and bid-preparation entry without adding page-load mutations.

The initial result view uses geometric row skeletons. During filter/search fetches, the previous result set remains visible. Empty, error, retry and source-health partial-coverage states are explicit. Source health is reported only when the existing source-refresh provider reports a degraded source. Explorer return state still carries URL, page and scroll position into Tender Details and back. No infinite feed, new polling path or speculative source URL was added.

## Visual fidelity and deliberate deviations

The [comparison](audits/s14_2/design-comparison.png) and [first-row detail](audits/s14_2/design-comparison-first-row.png) show the light institutional surfaces, compact filter grid, active chips, toolbar separation, aligned row zones, restrained borders/blue actions and source provenance against the supplied mockup. The [design QA](../design-qa.md) records the responsive, RTL and accessibility review.

- Saved searches (both header CTA and side module) are omitted because the accepted product has no saved-search persistence, ownership or notification contract. The filter area uses the available width instead.
- Match-quality filtering is omitted because no canonical backend filter exists. Scores shown in rows come only from Recommendation data.
- Compact/List view switching is omitted because no canonical Compact mode or preference exists. A single polished List mode remains.
- Illustrative mockup counts, titles, logos and dates are not copied into runtime. The backend owns those values. Unsupported source logos use a neutral fallback. The original World Bank mark was softer at high zoom; the approved supplied replacement is documented in the follow-up below.
- The global shell is intentionally unchanged, even where the supplied composition depicts a slightly different shell width/profile label.

## Validation and outcome

| Gate | Result |
| --- | --- |
| Focused Explorer/browser acceptance, Chromium 145.0.7632.6 | **85/85 pass**; All/Recommended/Dismissed/New, search/chips/clear, sort/page, save/unsave/failure rollback, dismissal/restore, safe source URL, missing match/deadline/logo, loading/empty/partial/failure and passivity |
| Maintained release Chromium gate | [**145/145 pass**](audits/s14_2/release_browser/results.json), zero external requests |
| Frontend tests | **230/230 pass** |
| ESLint, TypeScript, production Next.js build | Pass; 26 app routes built |
| EN/UZ/RU/AR and 320/390/768/1440 | 16 browser combinations pass without horizontal overflow; Arabic RTL pass |
| EN/AR representative axe | Four runs at 390/1440, zero serious/critical violations |
| RTL, design-token, legacy-design and customer-literal audits | Pass |
| Focused backend/Explorer tests | 47 tests plus 5 subtests pass |
| Connector/source-refresh regression | 198 pass, 1 skipped, 6 subtests |
| Full backend release group on isolated disposable PostgreSQL/Redis | **770 passed, 1 skipped, 100 subtests passed** |
| Other permanent release groups | Security **118 passed**; analysis **50 passed + 12 subtests**; connectors **198 passed, 1 skipped + 6 subtests**; migrations and 100,000-tender performance proof passed |
| Alembic sole head, disposable current/check and schema preflight | `20260912_0001_s10_5_communications`; all pass on isolated loopback PostgreSQL |
| Dependency health | Temporary Python environment installed from `backend/requirements-test.txt` with exact constraints: pin-conformance **1 pass**, config/dependency group **24 passed**, `pip check` pass; `npm audit --audit-level=high` reported 0 vulnerabilities. The host Python installation remains out of sync with 52 pins, so it was not used for the permanent gate. No application requirement or lockfile was altered in Sprint 14.2. |
| Full permanent release wrapper | **PASS** (exit 0) against isolated disposable PostgreSQL/Redis and the temporary pinned Python environment; browser group **145/145 pass**, zero external requests |
| Diff hygiene | `git diff --check` pass (line-ending conversion warnings only) |

The Explorer page-specific production JS chunk is **61,277 bytes uncompressed / approximately 17.3 KB gzip** in the final `.next-release-test` build. This is a measured size, not a before/after delta: there is no clean pre-S14.2 production artifact in this shared, already-modified worktree. Result pagination and passive request budgets remain bounded; the 100,000-tender synthetic proof used at most five read queries and 25 file checks for a 25-row page. The browser gate observed no external requests. The existing Docker app stack and database were not modified, restarted or used for testing. Separate `plasma_s142_disposable_pg` and `plasma_s142_disposable_redis` containers on loopback ports 6544 and 16380 were used only for validation and removed afterward. No production access, deployment or migration of the existing application database occurred.

### Sprint 14.2-owned files

| Area | Files |
| --- | --- |
| Explorer UI | `frontend/app/dashboard/tenders/page.tsx`, `frontend/components/customer/pages.css`, `frontend/components/customer/DashboardBookmarkButton.tsx`, `frontend/lib/sourceUrl.ts`, `frontend/types/explorer.ts` |
| Locales | `frontend/messages/en/explorer.json`, `frontend/messages/uz/explorer.json`, `frontend/messages/ru/explorer.json`, `frontend/messages/ar/explorer.json` |
| Read-only summary projection | `backend/app/schemas/explorer.py`, `backend/app/services/explorer.py` |
| Regression/acceptance | `backend/test_s6_2_unified_explorer_backend.py`, `frontend/tests/s14-2-explorer.test.mjs`, `frontend/tests/s14-2-browser-acceptance.py`, `frontend/tests/s14-2-visual-compare.py`, `frontend/tests/s8-3-arabic-rtl.test.mjs`, `frontend/tests/s10-1-foundation.test.mjs` |
| Documentation/evidence | `.gitignore`, `docs/S14_2_TENDER_EXPLORER_UI_UX_REFINEMENT.md`, `design-qa.md`, `docs/audits/s14_2/design-comparison.png`, `docs/audits/s14_2/design-comparison-first-row.png`, `docs/audits/s14_2/browser/explorer-en-1440.png`, `docs/audits/s14_2/browser/explorer-ar-390.png`, `docs/audits/s14_2/browser/results.json`, `docs/audits/s14_2/release_browser/results.json` |

The repository contains unrelated, pre-existing Sprint 11–14.1/S13 changes; they were preserved. The two existing frontend tests above were updated only to reflect added locale keys/RTL icon behavior and the accepted S14.1 warning-token contrast contract.

### Remaining issues and Sprint 14.3 entry contract

**Sprint 14.2 outcome: PASS.** There is no unresolved P0/P1/P2 Explorer design, browser or release-gate defect. The World Bank asset-quality follow-up is now resolved below. A developer rerunning the permanent gate must recreate the exact pinned Python environment and use explicitly disposable loopback PostgreSQL/Redis; the host Python installation is not release-gate compliant. Sprint 14.3 may begin only after Sprint 14.2 is accepted; it must not reinterpret Saved searches, Compact mode, match scores or source lifecycle without new canonical product contracts. Sprint 14.3 and Sprint 15 were not started.

## Follow-up — supplied World Bank mark and tender-card budget

The user supplied `/mnt/c/Users/acer/Desktop/World_Bank-Logo.wine.png` (3000 × 2000, transparent) and the new 1312 × 1199 Explorer mockup at `/mnt/d/Downloads/ChatGPT Image Sep 19, 2026, 07_59_46 PM.png`. The former was copied byte-for-byte to `frontend/public/brand/sources/world-bank-supplied.png`, then displayed as the globe portion within the existing source-identity block. The World Bank text label was initially retained; the later EBRD/logo-only follow-up below removes visible source captions on logo cards. The Dashboard asset was not changed.

Each Explorer result now presents **Budget** beside **Deadline** on desktop and after Deadline on narrow screens. The value comes from the row's existing `budget` and `currency` fields; a positive finite amount with a valid currency is locale-formatted. Missing, zero or invalid values use the existing localized “Value not disclosed” fallback rather than an invented amount or currency. The label is localized in English, Uzbek, Russian and Arabic, and the amount uses bidi isolation for RTL. There is no new API field, database migration, or source-ingestion change.

The new [full comparison](audits/s14_2/budget-logo-comparison.png), [focused first-row comparison](audits/s14_2/budget-logo-first-row.png) and [final desktop render](audits/s14_2/browser/explorer-en-1440.png) document the design check. The first visual pass found an over-wide Open status pill; it was constrained. The second pass found the globe slightly large; the final crop is 48 × 48 on desktop. Both corrections were recaptured. The [follow-up QA entry](../design-qa.md) records responsive and accessibility evidence.

Validation for this follow-up: focused frontend tests **231/231 pass**, TypeScript and ESLint pass, production build pass, Explorer browser acceptance **87/87 pass** and the [maintained release browser gate](audits/s14_2/release_browser/results.json) **145/145 pass** on Chromium 145. Design-token, legacy-design, customer-literal and RTL audits pass. The Explorer run covers 16 locale-width combinations (EN/UZ/RU/AR × 320/390/768/1440), canonical budget/missing-value and supplied-art checks, four axe scans with zero serious/critical findings, and no external network requests. The historical Sprint 14.2 validation table above describes the original sprint run; this follow-up did not deploy or restart the existing Docker app.

Follow-up-owned additions are `frontend/public/brand/sources/world-bank-supplied.png`, `frontend/tests/s14-2-budget-visual-compare.py`, and the two budget/logo comparison images. The Explorer page, CSS, locale catalogs, acceptance tests and documentation were updated in place. The existing unrelated worktree changes were preserved.

## Follow-up — supplied EBRD art and logo-only source identity

The user supplied `/mnt/c/Users/acer/Desktop/european-bank-transparent-smaller.png` (1140 × 1141 RGBA). The exact bytes, verified by SHA-256, were copied to `frontend/public/brand/sources/ebrd-supplied.png` and used for EBRD Explorer cards. The old dark square treatment was removed so the transparent artwork appears on the light card surface. The existing `ebrd.svg` is retained but no longer used on these cards.

Cards with an available logo now show only that logo, not a duplicate source-name caption underneath. The image's accessible alternative text retains the source name for assistive technology. Unknown sources and failed image loads still show the neutral placeholder **and** a visible source name, because an icon alone cannot identify them. Source filters, detail provenance and backend data are unchanged.

The [desktop capture](audits/s14_2/browser/explorer-en-1440.png) and [mobile capture](audits/s14_2/browser/explorer-en-390.png) show the updated source column. The EBRD art renders at 84 × 84px on desktop and 72 × 72px on narrow screens without cropping. Focused Explorer browser acceptance **89/89 pass** across the existing 16 locale-width combinations, including supplied EBRD loading, absence of duplicate captions, the visible fallback name, and four EN/AR axe scans with zero serious/critical findings. Frontend tests **232/232 pass**, production build and ESLint pass, and the [maintained release browser gate](audits/s14_2/release_browser/results.json) **145/145 pass**. No application deployment, Docker restart, backend change or migration occurred.

## Follow-up — remove descriptions from Explorer result cards

The short description snippet is no longer rendered in Tender Explorer result cards; its unused card-specific CSS was removed. Titles, source identity, location/reference, tags, deadline, budget and actions remain in place. The existing read-only `summary` API projection is retained to avoid an unrelated backend contract change, and the full description remains on Tender Details. The Preview drawer was already a key-facts view and was not changed.

The [updated desktop](audits/s14_2/browser/explorer-en-1440.png) and [mobile](audits/s14_2/browser/explorer-en-390.png) captures show the shorter cards. Frontend tests **233/233 pass**; TypeScript, ESLint and the production build pass. Focused Explorer browser acceptance **90/90 pass** across the same 16 locale-width combinations, including an explicit absence check for the fixture description; four EN/AR axe scans report zero serious/critical findings. No backend, migration, Docker or deployment action was taken.
