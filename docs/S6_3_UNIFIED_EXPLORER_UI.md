# Sprint 6.3 — Unified Tender Explorer UI

## 1. Previous Explorer UI

`/dashboard/tenders` previously read the legacy `/tenders` collection, accumulated pages with Load more, and had no owned Recommendation or pursuit overlay.

## 2. Previous Hunter UI

`/dashboard/hunter` remains the Sprint 6.1 compatibility surface backed by `/hunter/`. It is operational but is no longer a primary navigation destination.

## 3. Unified Explorer Architecture

One client-side surface renders All, Recommended, and Dismissed modes from one response model and one reusable Recommendation summary.

## 4. Data Authority

`GET /api/v1/explorer/tenders` is the sole passive domain authority. The UI neither composes legacy Tender and Hunter responses nor infers membership.

## 5. URL Contract

Canonical mode is `view=all|recommended|dismissed`. Canonical filters are `status`, `source`, `region`, `countries`, `services`, `deadline_status`, `document_status`, `category`, `price_min`, `price_max`, `q`, `sort`, and `page`. Invalid values normalize safely.

## 6. All Mode

All is ordinary Tender discovery. A nullable owned Recommendation augments a row; its absence produces no score or negative-match claim.

## 7. Recommended Mode

Recommended displays only backend-provided active owned Recommendations and defaults to deterministic `best_match` ordering.

## 8. Dismissed Mode

Dismissed displays backend-provided dismissed Recommendations and offers Restore recommendation without labeling the Tender itself dismissed.

## 9. Counts

All three mode counts come from `response.counts`, which uses the same backend filter universe. No page-row counting occurs.

## 10. Filters

Lifecycle, source, geography, country, service, deadline, document, category, and price filters are URL-backed and sent to the unified endpoint. Membership is never filtered in the browser.

## 11. Search

Search uses `q`, a 350 ms debounce, first-page reset, request cancellation, and server-authoritative results.

## 12. Sorting

All exposes Tender sorts and rejects/normalizes Best match. Recommended and Dismissed expose Best match plus supported Tender sorts.

## 13. Pagination

Pagination uses backend `total`, `limit`, and `offset` with 25-row pages. Out-of-range pages recover to the nearest valid page.

## 14. Recommendation Overlay

`RecommendationSummary` is shared by every mode and remains compact: score, bounded rationale, creation date, and one explicit mutation control.

## 15. Match Score

The score is labeled Match score and shown on a 0–100 advisory scale. It is not a probability, eligibility, compliance, or readiness result.

## 16. Rationale

The UI renders `rationale_summary` under “Why this may match.” It does not generate, expand, or fabricate rationale.

## 17. Creation Time Semantics

`created_at` is labeled “Recommended on.” No refreshed, updated, fresh, or stale claim is made.

## 18. Pursuit Overlay

Pursuit is a separate badge using canonical Sprint 4 labels and shared status styling. Every pursuit state coexists independently with either Recommendation state.

## 19. Dismiss

Dismiss recommendation calls only `POST /recommendations/{id}/dismiss`, disables that Recommendation’s button while pending, and never dismisses a pursuit.

## 20. Restore

Restore recommendation calls only `POST /recommendations/{id}/restore`. It restores the same owned Recommendation without regeneration.

## 21. Mutation Refresh

After success, the UI refetches the unified response. Counts, membership, and pagination are not optimistically invented.

## 22. Empty States

All says “No tenders match these filters.” Recommended uses neutral Recommendation wording, including “No active recommendations” for the all-dismissed condition. Dismissed says “No dismissed recommendations.”

## 23. Profile Required

All remains available when `PROFILE_REQUIRED`. Recommendation modes truthfully request profile completion and link to Company Profile without claiming background generation.

## 24. Failure Handling

List failure has an announced error and retry. Recommendation mutations distinguish authorization, missing/stale identity, and operational failure without exposing raw exceptions or removing rows prematurely.

## 25. Loading

One announced Explorer loading state represents the unified list. Recommendation and pursuit rows cause no passive secondary loading trees.

## 26. Request Collapse

Initial rendering and each mode/filter/page change create one unified domain GET, plus normal auth/session infrastructure. Static filter taxonomies prevent metadata fan-out.

## 27. Navigation

Primary navigation retains Tenders, My Tenders, and Bid Preparation. Hunter is removed as a duplicate primary discovery entry.

## 28. Hunter Compatibility

The Hunter page, client, API, and route remain physically operational and unredirected for Sprint 6.4 compatibility cleanup.

## 29. Accessibility

Modes use tab semantics, actions are buttons, score and statuses have text labels, loading/errors are announced, focus is visible, and pagination has a navigation label.

## 30. Responsive Layout

Controls wrap or scroll at narrow widths; cards use single-column mobile layout and denser multi-column laptop/desktop layout without a fixed page width.

## 31. Tenant Security

The UI receives only backend-owned overlays, has no foreign Recommendation lookup, and turns forged/stale mutation identity into a safe error.

## 32. Passive Read Guarantee

Opening modes, filtering, sorting, paging, and history navigation do not create Recommendations, engagements, proposals, compliance analyses, or source mutations. Source refresh remains an explicit menu action.

## 33. Browser Acceptance

`frontend/tests/unified-explorer-browser-acceptance.py` runs the actual Next.js page in real Chromium against a controlled API and reports all required 70 cases: `70/70 PASS`.

## 34. Sprint 6.4 Cleanup Contract

Sprint 6.3 does not redirect or delete `/dashboard/hunter`, its component/client, or legacy backend routes. Sprint 6.4 exclusively owns final compatibility-route retirement.
