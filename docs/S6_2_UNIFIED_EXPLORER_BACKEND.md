# Sprint 6.2 — Unified Explorer Backend

## 1. Unified Endpoint Purpose

`GET /api/v1/explorer/tenders` is the canonical bounded read model for global Tender discovery with an optional private Recommendation overlay. It does not replace `GET /api/v1/tenders` or the Hunter API in Sprint 6.2, and it performs no generation, ingestion, analysis, engagement, Proposal, Compliance, or Tender mutation.

## 2. View Modes

The `view` query parameter is the explicit `ExplorerView` enum: `all`, `recommended`, or `dismissed`. Unknown values fail FastAPI validation with 422. `all` starts from visible Tenders; `recommended` starts from owned active Recommendations; `dismissed` starts from owned dismissed Recommendations.

## 3. Tenant/Profile Resolution

Recommendation authority uses the schema-enforced canonical `CompanyProfile.user_id` relationship and UUID identity. Company name, email, Tender text, and Proposal state are never ownership inputs. An operator or administrator without its own profile receives no customer Recommendation overlay and has no mutation backdoor.

## 4. All Query

All mode starts from `Tender`, applies customer visibility and all Tender membership predicates, then left-joins at most one Recommendation for the current profile and at most one exact-owner TenderEngagement. Recommendation uniqueness `(tender_id, company_profile_id)` and engagement uniqueness `(user_id, company_profile_id, tender_id)` prove one Tender row cannot be duplicated. Both active and dismissed owned Recommendations are exposed as overlays; absence is `null`, never score zero.

## 5. Recommended Query

Recommended mode starts from `TenderRecommendation`, constrains `company_profile_id` and `is_dismissed=false`, joins a customer-visible Tender, applies the same Tender filters, counts, orders, and only then applies offset/limit. It never starts from a bounded Tender page.

## 6. Dismissed Query

Dismissed mode is identical in shape to Recommended except `is_dismissed=true`. Dismissal does not remove the Tender from All mode and does not modify Tender, engagement, Proposal, or Compliance state.

## 7. Filter Reuse

Legacy and unified Explorer both call `apply_explorer_tender_filters`. The shared contract covers source/source system, search, source lifecycle status, region/country, service, deadline status/range, price range, document status, and category. Search remains restricted to canonical Tender fields, including buyer through the Tender search predicate; rationale is not searched.

## 8. Document Filter Correction

The legacy post-page document filter was removed. Persisted document modes use correlated SQL `EXISTS`. `documents_available` and `files_missing` additionally depend on the established application-filesystem existence check, so their matching Tender UUIDs are resolved once before count/order/page and injected as a SQL `Tender.id IN (...)` membership predicate. A 10,000-Tender fixture returned total 80 and a full 25-row `files_missing` page with every response status matching; no bounded page is filtered afterward.

## 9. Search

Trimmed search applies SQL `ILIKE` predicates to title, description, buyer, project/external IDs, sector, category, procurement category/method, and notice type. It executes before counts and pagination. Recommendation rationale is deliberately excluded.

## 10. Sorting

All mode preserves `newest` as default and supports the existing Tender sorts: `deadline_soonest`, `highest_price`, `document_availability`, and `source`. Every Tender sort ends in `Tender.id ASC`. Recommended and Dismissed default to `match_score DESC, created_at DESC, recommendation_id ASC`; existing Tender sorts are also allowed. `best_match` in All returns 400 rather than inventing null-score semantics.

## 11. Counts

One count statement returns the request-filtered `all_tenders`, `active_recommendations`, and `dismissed_recommendations` universes. Recommendation counts use the exact current profile and visible filtered Tender join. `total` is exactly the count for the selected view.

## 12. Pagination

The API defaults to 25, caps limit at 100, and requires offset at least zero. PostgreSQL proof covered page sizes 1, 24, 25, 26, 99, and 100, an empty offset at 10,000, and a 10,000-row total. Equal-score/equal-time pages used Recommendation UUID ascending and produced no duplicate or missing IDs across adjacent 100-row pages.

## 13. Recommendation Overlay

The nullable overlay exposes only `recommendation_id`, `match_score`, bounded `rationale_summary`, `is_dismissed`, and creation time. All mode intentionally includes dismissed owned overlays so a later UI can distinguish “dismissed Recommendation” while the Tender remains discoverable.

## 14. Rationale Bounds

List rationale is sliced to at most 280 Unicode code points in the response representation. Stored `strategic_rationale` is never modified. The score is returned as persisted and validated against the existing 0–100 response domain; it is not clamped or recalculated.

## 15. Pursuit Overlay Decision

A small nullable pursuit summary is included to avoid future per-card engagement requests. It contains only `engagement_id`, engagement `status`, and `allowed_actions`. Proposal, Compliance, documents, and Tender Details are excluded. Pursuit never affects Recommendation membership, score, dismissal, sorting, or counts.

## 16. Dismiss Service

`dismiss_recommendation` resolves the exact owned Recommendation UUID through `CompanyProfile.user_id`, takes a narrow `FOR UPDATE` row lock, and idempotently sets only `is_dismissed=true`. Foreign or absent IDs use an anti-enumeration not-found result.

## 17. Restore Service

`restore_recommendation` uses the same authority and lock and idempotently sets only `is_dismissed=false` on the same row. It does not create a Recommendation or change score, rationale, or `created_at`.

## 18. Hunter Compatibility

The legacy Hunter list route remains operational. Its existing dismiss route now delegates to the canonical Recommendation service and preserves its response contract. No Hunter frontend, route, or navigation change was made.

## 19. Score/Rationale Semantics

`match_score` remains the stored 0–100 integer strategic-fit assessment and is not win probability, eligibility, Compliance, readiness, or award probability. Rationale remains stored LLM advisory text, not source or Compliance evidence. No freshness or staleness field is exposed.

## 20. Profile Absence

An approved account without a CompanyProfile may use global All discovery. Recommendation overlays are null, Recommendation counts are zero, and availability is `PROFILE_REQUIRED`. Recommended and Dismissed return 200 with empty items and total zero. Existing user/company approval and disabled-account checks remain enforced.

## 21. Empty States

`PROFILE_REQUIRED` is distinguishable from an available profile with zero Recommendations and from filters reducing a valid Recommendation universe to zero. No response claims generating, stale, failed generation, or refresh state because the current architecture cannot prove those conditions.

## 22. Failure Isolation

Expected Recommendation absence is represented by null or zero. Database/session/infrastructure errors are not swallowed as empty data. All mode remains usable without a profile, while Recommended and Dismissed truthfully depend on Recommendation queries when a profile exists.

## 23. Passive Read Guarantee

The unified GET dependency graph has no add/delete/flush/commit, queue dispatch, Gemini invocation, Recommendation generation, or domain writer. Fresh-database fingerprints over Tender, Recommendation, TenderEngagement, Proposal, TenderAnalysis, and AnalysisVersion were identical after all read modes, filters, pagination, and concurrent reads. The representative existing local database also retained identical fingerprints across all three views.

## 24. Same-Name Tenant Security

The PostgreSQL fixture used two profiles named “Acme Engineering” on the same 10,000 Tenders. Tenant A received only its score/rationale, Tenant B only its own; A’s dismiss/restore concurrency did not modify B. A foreign Recommendation UUID command returned not found.

## 25. Query Count

At 25 returned rows with Recommendation and pursuit overlays, All, Recommended, and Dismissed each executed exactly five SQL statements: profile, combined counts, page, compiled-text summaries, and document summaries. The filesystem-accurate `files_missing` mode executed eight because it resolves the full document membership universe first. Counts are fixed and independent of returned row count; no per-row query exists.

## 26. Scale Performance

Disposable PostgreSQL 16 contained 10,000 visible Tenders, 20,000 Recommendations across two profiles, 280 documents, and every engagement state. Observed end-to-end local times were All 147.95 ms, Recommended 64.13 ms, Dismissed 54.07 ms, and filesystem-accurate `files_missing` 1,070.35 ms. These are local compatibility measurements, not production SLOs. Search, source, status, deadline, document, service/category, geography, price, score ordering, and pagination passed.

## 27. Index Decision

No migration was added. `EXPLAIN ANALYZE` on 7,500 active target-profile rows completed the core Recommendation join/order/limit in 8.696 ms using a top-N sort and hash join. At the required 20,000-row fixture this is not material evidence for a new compound index. Existing profile, Tender, creation-time, primary-key, and unique identity indexes remain unchanged. Re-evaluate with production-safe telemetry only if real scale or latency justifies it.

## 28. Preflight

The count-only, read-only, rollback-only preflight remains intact. Local compatibility evidence remains 4,109 Recommendations: 4,107 active, 2 dismissed, zero duplicate logical keys/orphans/null scores, score 10–95, all with rationale, and zero with engagement. These are local facts only and are not hard-coded.

## 29. Worker Preservation

Recommendation generation code, Gemini prompt/model/temperature, score threshold, 30-minute Celery Beat ownership, existing-row exclusion, profile-change behavior, and separate UzEx document-ingestion dispatch were not changed. Explorer reads never dispatch worker work.

## 30. Regression Results

Focused Sprint 6.2/6.1/Sprint 5: 44 passed. Sprint 4: 64 passed plus 4 subtests. Sprint 3: 54 passed plus 54 subtests. Sprint 2: 52 passed. Sprint 1/WB: 67 passed. Migration/preflight focus: 18 passed plus 7 subtests. Connector gate: 195 passed plus 4 subtests, with the one approved storage-fixture skip. OpenAPI/startup, Celery import, compile, Alembic current/heads/check, and diff check passed. The only emitted notices were existing Pydantic class-config and Alembic configuration deprecations.

## 31. Sprint 6.3 Frontend Contract

Sprint 6.3 may consume `GET /api/v1/explorer/tenders` with URL-backed `view`, shared filters, counts, bounded pages, nullable Recommendation/pursuit overlays, and explicit availability. It may call canonical dismiss/restore routes and refresh the current page/counts. It must label score as strategic fit, creation time as generated/created time, and rationale as advisory—not probability, eligibility, evidence, freshness, or Compliance.

## 32. Deferred Sprint 6.4 Work

Hunter redirect, navigation retirement, old client/API compatibility removal, and dead component cleanup remain deferred. Sprint 6.2 did not redirect `/dashboard/hunter`, remove Hunter navigation, deploy, access production, backfill Recommendations, or begin final frontend convergence.
