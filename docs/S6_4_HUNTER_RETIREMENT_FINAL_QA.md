# Sprint 6.4 — Hunter Route Retirement and Final QA

## 1. Hunter Surface Inventory

| File or route | Current consumer | Customer-facing | Runtime required | Canonical replacement | Decision |
|---|---|---:|---:|---|---|
| `/dashboard/hunter` | Historical bookmarks | Compatibility only | Yes | `/dashboard/tenders?view=recommended` | Redirect |
| Former Hunter page implementation | Retired route only | Yes | No | Unified Explorer | Delete |
| Former `frontend/types/hunter.ts` | Retired page only | No | No | `types/explorer.ts` | Delete |
| `GET /api/v1/hunter` | Possible versioned/external consumers | API compatibility | Temporarily | `GET /api/v1/explorer/tenders?view=recommended` | Retain legacy |
| `POST /api/v1/hunter/{id}/dismiss` | Possible versioned/external consumers | API compatibility | Temporarily | `POST /api/v1/recommendations/{id}/dismiss` | Retain legacy |
| Hunter worker, agent, and Beat names | Celery generation pipeline | No | Yes | Existing Recommendation generation | Retain internal |

## 2. Customer vs Backend Hunter Concepts

The customer product name and independent feed are retired. Backend compatibility routes and historical internal worker names are separate implementation layers and remain where removal would add risk.

## 3. Final Canonical Discovery Route

Tender Explorer at `/dashboard/tenders` is the sole discovery surface, with All, Recommended, and Dismissed URL modes.

## 4. Hunter Redirect

The compatibility route uses Next.js `redirect('/dashboard/tenders?view=recommended')`, producing the framework temporary redirect rather than asserting permanent retirement of bookmarks or API compatibility.

## 5. Redirect Passivity

The route is a server component containing no client hook, HTTP client, domain read, mutation, generation, or enqueue operation. The first domain read occurs on the destination Explorer.

## 6. Legacy Query Parameter Policy

The retired page consumed no query parameters. Unknown historical parameters are intentionally ignored; no unproven mapping is introduced into Explorer filters.

## 7. Dead Frontend Removal

The full Hunter feed implementation, score helpers, empty-state claims, legacy dismiss handler, and presentation code were removed from the route.

## 8. Legacy Frontend Client Decision

There was no separate shared Hunter client module. The only legacy calls lived inside the deleted page, so no Hunter list or dismiss frontend call remains.

## 9. Backend Hunter API Inventory

`GET /api/v1/hunter` and its slash alias remain approved-user, owned-profile, read-only compatibility endpoints. `POST /api/v1/hunter/{recommendation_id}/dismiss` remains an approved-user compatibility command.

## 10. Legacy List Decision

The legacy list remains temporarily because repository evidence cannot exclude external/versioned consumers. Canonical frontend code never calls it; replacement is unified Explorer Recommended mode.

## 11. Legacy Dismiss Decision

The legacy dismiss endpoint delegates to `app.services.recommendations.dismiss_recommendation`, preserving one mutation authority and the established anti-enumeration 404 behavior.

## 12. Generation Infrastructure Preservation

The scheduled sweep, `MIN_MATCH_SCORE`, Gemini model/prompt, existing-row exclusion, Recommendation insert, and UzEx document-processing side-dispatch are unchanged.

## 13. Internal Naming Decision

Historical names such as `hunter_tasks`, `_run_hunter_sweep_async`, and the agent module are internal, non-customer-facing identifiers. They remain to avoid risky task-name and worker-routing churn.

## 14. Unified Explorer Authority

Canonical passive discovery remains `GET /api/v1/explorer/tenders`; canonical mutations remain Recommendation dismiss and restore commands.

## 15. Navigation

Primary navigation contains Tenders, My Tenders, and Bid Preparation, with no Hunter or duplicate Recommendations entry.

## 16. Customer Terminology

Runtime discovery UI uses Tender Explorer and Recommended. The old Hunter Feed, AI-curated ranking, and scanning-market empty-state copy no longer render.

## 17. Recommendation/Pursuit Separation

Recommendation state remains independent of TenderEngagement, Proposal, Compliance, and Tender source truth. Cleanup introduced no cross-domain inference.

## 18. Same-Name Security

Both unified and compatibility endpoints resolve ownership by user/profile identity, never company name. Canonical and legacy mutations deny foreign Recommendation identifiers safely.

## 19. Profile Required

No-profile users may use All. Recommended and Dismissed show the canonical profile-required state, including when arriving through the Hunter bookmark redirect.

## 20. Browser Network Audit

The redirect performs navigation only. The destination issues the unified Explorer GET plus auth/session infrastructure, with no Hunter list request or per-card request fan-out.

## 21. DB Fingerprint Audit

Redirect and passive Explorer navigation leave Recommendation, TenderEngagement, Proposal, TenderAnalysis, AnalysisVersion, and Tender unchanged. Explicit dismiss/restore changes only Recommendation dismissal state.

## 22. Scale / Query Regression

The Sprint 6.2 PostgreSQL fixture covers 10,000 Tenders and 20,000 Recommendations. Normal modes retain five SQL statements; filesystem-accurate `files_missing` retains eight.

## 23. Worker Regression

Focused tests preserve duplicate exclusion, threshold behavior, generation ownership, document dispatch, and the absence of engagement/proposal/compliance writes.

## 24. Browser Acceptance

The final real-Chromium gate composes the 70-case unified Explorer suite with five Hunter retirement cases and requires `75/75 PASS`.

## 25. Broad Product Suite

The maintained backend product suite, frontend focused suites, connector gate, OpenAPI/startup checks, preflight contracts, and Alembic checks are reported separately. `backend/test_ai.py` remains an excluded Windows-path developer probe and is not called passed.

## 26. Remaining Compatibility Inventory

Only the passive customer redirect, legacy backend list/dismiss routes, and internal historical worker/agent names remain. There is no customer Hunter UI, frontend client, or frontend Hunter type.

## 27. Sprint 6 Release Considerations

Release review should preserve the temporary redirect and backend compatibility endpoints until an explicit API deprecation/removal policy exists. No database migration, backfill, production access, or deployment occurred.

## 28. Deferred Sprint 7 Work

Localization infrastructure, analysis-language changes, Arabic RTL, ADB recovery, Recommendation recomputation/freshness, automatic submission, and collaborative workspaces remain out of scope.
