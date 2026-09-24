# Sprint 14.1 — Dashboard UI/UX Refinement

## 1. Status

PASS. The customer Dashboard was rebuilt to the approved hierarchy without a
backend/domain change, migration, production access, or deployment. The
pre-existing shell, navigation, authentication, notification, and source
refresh owners remain authoritative.

## 2. Mockup/report mapping

- The page header now contains the Overview eyebrow, Dashboard title and
  supporting copy, authoritative last-update time, secondary Refresh control,
  and primary Tender Explorer action.
- Desktop uses the requested primary/secondary columns. Mobile and tablet use
  Header → Active opportunities → Company readiness → Needs attention →
  profile prompt → Recent compliance analyses.
- The KPI strip, recent-activity feed, decorative percentages, and long
  unbounded lists were removed.
- All visible values come from existing canonical reads; unsupported mockup
  content was omitted rather than synthesized.

## 3. Information architecture changes

The Dashboard is now a bounded decision surface. Active opportunities are the
primary panel; readiness is the desktop rail; action-required analyses and
recent analyses are separate; and the company-profile prompt is conditional.
Cards link to the existing Explorer, Tender Details, Compliance, Readiness
Vault, and Company Profile routes.

## 4. Active-opportunity eligibility and ranking

The shortlist is derived only from stored Explorer Recommendation records. A
Tender must have a Recommendation, canonical status `OPEN`, and either no
deadline or a valid deadline at/after the current instant. Closed, cancelled,
unknown, malformed-deadline, and expired rows are excluded. Rows are deduped by
`canonical_source_key`, falling back to source plus external ID. Ranking is
stored match score descending, known deadline ascending, then stable canonical
identity and Tender ID. The result is capped at three and never renders the
numeric score. A shared 60-second clock ages expired entries out without a
write.

## 5. Company readiness

Readiness uses `/vault/readiness` and the existing required-document taxonomy.
Available, missing, expired, and expiring-soon buckets are mutually exclusive.
Missing document types are listed with non-color labels, and the panel links to
the canonical Readiness Vault. No readiness percentage or inferred risk score
was introduced.

## 6. Needs attention and recent analyses

Needs attention contains only operational analysis states: failed, manual
review, or partial coverage. It is priority ordered and capped at three. Recent
analyses are separately date ordered and capped at three; each opens the
existing Compliance surface. Readiness deficiencies are not duplicated into
Needs attention.

## 7. Profile prompt

The prompt is absent for a complete profile. Its copy varies truthfully for a
missing profile/onboarding state, missing targeting data, missing company
details, or both. The action uses the existing Company Profile route.

## 8. Source-logo implementation

No approved official procurement-source logo assets exist in the repository.
The Dashboard therefore uses the required controlled neutral landmark fallback
and renders the canonical source name verbatim. It makes no runtime external
asset request. Official marks can replace the fallback only after approved,
licensed assets enter a controlled local registry.

## 9. Refresh and partial states

The header reuses `SourceRefreshMenu` and `SourceRefreshProvider`; only its
visible trigger label is specialized to “Refresh.” Last updated is the newest
`last_clean_completed.completed_at`, never browser time or a partial/failure
timestamp. Initial loading uses geometry-matched skeletons. Section reads are
settled independently, successful cached sections remain visible after a
partial refresh failure, and global failure has an explicit retry state.

## 10. Passivity and request budget

Initial render and background refresh perform GETs only. Save/unsave, source
refresh, and navigation remain explicit user actions through existing command
owners. Dashboard browser acceptance observed zero unsolicited writes, zero
external requests, and no more than 30 controlled fixture requests per
navigation. Analysis summaries are bounded to the first 12 canonical Tenders;
the shortlist read is bounded to 100 Explorer results.

## 11. Responsive, locales, RTL, and accessibility

- EN, UZ, RU, and AR have exact 1,071-key catalog and placeholder parity.
- The 320, 390, 768, and 1440 widths pass without page-level horizontal
  overflow; the shortlist remains capped at three.
- Arabic uses document-level RTL, logical CSS, mirrored directional icons, and
  explicit bidi boundaries for source names and identifiers.
- Semantic headings, keyboard-reachable controls, visible focus, explicit
  bookmark labels/state, non-color status text, reduced motion, and touch-safe
  controls are retained.
- axe produced zero serious/critical violations for representative EN and AR at
  390 and 1440 pixels.

## 12. Frontend, backend, browser, and release totals

- Dashboard focused static tests: **7/7**.
- Dashboard production-browser acceptance: **32/32** (16 locale/viewport
  renders, 4 axe runs, shortlist/state/interaction/passivity checks).
- Complete frontend static suite: **227/227**.
- Relevant backend regressions: **56/56**.
- Maintained Chromium release-hardening gate: **145/145**, zero external
  requests.
- Permanent frontend release-gate wrapper: PASS (`npm ci`, typecheck, ESLint,
  227 tests, RTL audit, and 26-route production build).
- Locale parity, RTL, design-token, legacy-design, and customer-literal audits:
  PASS.
- Alembic `heads`, `current`, `check`, and disposable read-only schema
  preflight: **4/4 PASS**. Sole head/current remains
  `20260912_0001_s10_5_communications`.
- Dependency audit: **0 vulnerabilities** at the high threshold.

## 13. Bundle impact

No dependency was added. The release build emits a 30,559-byte uncompressed
Dashboard route-specific client chunk; the full shared static output is
1,413,436 bytes uncompressed. The 26-route production build succeeds. No
before/after bundle claim is made because the supplied worktree already
contained unrelated uncommitted changes.

## 14. Exact Sprint 14.1 files changed

- `.gitignore` (tracks this required Sprint report)
- `frontend/app/dashboard/page.tsx`
- `frontend/lib/dashboard.ts`
- `frontend/components/customer/DashboardBookmarkButton.tsx`
- `frontend/components/customer/pages.css`
- `frontend/components/source-refresh/SourceRefreshMenu.tsx`
- `frontend/messages/en/dashboard.json`
- `frontend/messages/uz/dashboard.json`
- `frontend/messages/ru/dashboard.json`
- `frontend/messages/ar/dashboard.json`
- `frontend/package.json`
- `frontend/tests/s14-1-dashboard.test.mjs`
- `frontend/tests/s14-1-dashboard-browser-acceptance.py`
- `frontend/tests/s8-3-arabic-rtl.test.mjs`
- `frontend/tests/release-hardening-browser.py`
- `docs/S14_1_DASHBOARD_UI_UX_REFINEMENT.md`
- `docs/audits/s14_1/browser/` (Dashboard screenshots, axe JSON, logs, results)
- `docs/audits/s9_3/browser/` (regenerated maintained-Chromium evidence)

`pages.css`, the Arabic contract test, the release-hardening gate, and the
maintained-browser evidence already had reviewed worktree changes from earlier
sprints; Sprint 14.1 preserved them and changed only the necessary sections.
No backend application file was changed for Sprint 14.1.

## 15. Deliberate mockup deviations

- Neutral source marks are used because controlled official logo assets were
  not supplied.
- Recent analyses has no unsupported aggregate “View all” destination; the
  three canonical item links remain available.
- The profile action targets the existing `/dashboard/settings` Company
  Profile surface.
- Fixture-specific titles and counts in screenshots intentionally differ from
  the illustrative mockup; production renders canonical data.

## 16. Remaining Dashboard issues

- Official source marks still require licensed, approved local assets and a
  controlled registry.
- Ranking is exact within the existing bounded 100-result recommended Explorer
  read. A larger cross-page shortlist would require a narrowly scoped canonical
  read projection rather than browser-side retrieval expansion.
- Recent analysis collection uses bounded per-Tender summary reads because no
  canonical aggregate analysis-history endpoint currently exists.

These are recorded limitations, not blockers for the approved Sprint 14.1
scope.

## 17. Sprint 14.2 entry contract

Sprint 14.2 may begin only with Sprint 14.1 gates still green and a separately
approved scope. It must preserve canonical Recommendation/readiness/refresh
ownership, Dashboard passivity, the three-item active shortlist, four-locale
and RTL parity, and current request budgets. Any source logo work requires
approved local assets and usage rights. Any new aggregation must be additive,
read-only, canonically sourced, and justified against the existing bounded
reads. No Sprint 14.2 work, migration, production access, or deployment was
started here.
