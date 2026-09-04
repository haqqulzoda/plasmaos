# Sprint 7.4 Final Localization QA

## 1. Executive Summary

Sprint 7.4 completes the approved Sprint 7 customer-localization scope. EN, UZ, and RU provide structurally complete P0 and P1 product chrome; source, user, Proposal, and AI/analysis content remains in its original language. The closure decision is **SPRINT 7 COMPLETE WITH NON-BLOCKING DOCUMENTED CAVEATS — READY FOR SPRINT 8**.

## 2. Sprint 7 Final Scope

Sprint 7 covers locale-neutral EN/UZ/RU customer UI, persisted `User.ui_locale`, next-intl messages, shared formatters, localized accessibility copy, and presentation-only enum labels. Arabic, RTL, analysis language, report language, and generated report-body language remain outside scope.

## 3. Final Surface Matrix

| Surface | Classification | Result |
|---|---|---|
| Auth, onboarding, Settings, navigation | P0 customer | EN/UZ/RU complete |
| Explorer, refresh, Tender Details, My Tenders, Bid Preparation | P0 customer | EN/UZ/RU complete |
| Dashboard secondary shell | P1 customer | EN/UZ/RU complete |
| Compliance workbench chrome | P1 customer | EN/UZ/RU complete; analysis/evidence preserved |
| Readiness Vault and Company Profile chrome | P1 customer | EN/UZ/RU complete; user values preserved |
| Document viewer and document states | P1 customer | EN/UZ/RU complete; document content preserved |
| Shared dialogs, pagination, empty/loading/error states, 404 | Shared customer | EN/UZ/RU complete |
| Dedicated Admin business screens | Dedicated Admin | Intentionally English-only |

## 4. P1 Compliance Localization

The workbench now localizes its headings, controls, loading/error states, verdict presentation, evidence chrome, PDF control, counts, audit labels, override dialog, and safe unknown-state presentation. Responsive behavior changes the split workbench to a stacked mobile layout without redesigning its domain model.

## 5. Readiness Localization

Readiness Vault headings, filters, form labels, confirmation/error states, table headers, dates, service presentation, document types, document statuses, expiry states, accessible names, and empty/loading states are localized. Canonical API values remain unchanged.

## 6. Secondary Customer Surfaces

Dashboard summaries, actions, activity, deadlines, coverage/readiness states, legacy Bid Preparation handoff, shared source-document viewer, authenticated not-found experience, Tender file-size presentation, and relevant secondary labels now use message resources.

## 7. Admin Boundary

Shared customer navigation may be localized around an operator link. Dedicated Admin approval, company, audit, and operational business screens remain intentionally English-only and are excluded from customer P1 coverage.

## 8. Final Message Catalog Structure

There are 15 JSON namespaces per locale: auth, bidPreparation, common, compliance, dashboard, documentViewer, errors, explorer, myTenders, navigation, onboarding, readiness, refresh, settings, and tenderDetails.

## 9. EN Coverage

English contains 850 of 850 expected scalar customer keys, zero missing, zero extra, zero ICU-placeholder mismatches, zero rich-placeholder mismatches, and zero browser fallback hits in covered flows. Reviewed.

## 10. UZ Coverage

Uzbek contains 850 of 850 expected scalar customer keys, zero missing, zero extra, zero ICU-placeholder mismatches, zero rich-placeholder mismatches, and zero browser fallback hits in covered flows. Reviewed.

## 11. RU Coverage

Russian contains 850 of 850 expected scalar customer keys, zero missing, zero extra, zero ICU-placeholder mismatches, zero rich-placeholder mismatches, and zero browser fallback hits in covered flows. Reviewed.

## 12. Placeholder / ICU Validation

The release validator compares flattened key shape, named ICU placeholders, and rich-message tag placeholders. The final automated validation passed with zero issues.

## 13. Terminology Review

Tender, Tender Explorer, My Tenders, Bid Preparation, Compliance, Readiness, Recommendation, Match score, Requirement, Evidence, Risk, Source, Refresh, Project, Documents, and pursuit-state terms were reviewed across all active catalogs. Canonical codes are never used as translated payload values.

## 14. Uzbek Quality Review

The Uzbek P1 pass removed literal English UI, normalized workflow terms, used natural action phrasing, distinguished missing/expired/unknown readiness states, and avoided eligibility or certification claims.

## 15. Russian Quality Review

The Russian P1 pass reviewed case agreement, procurement/workflow wording, plural ICU forms, readiness distinctions, and claim-sensitive Compliance text. No covered P1 English fallback remains.

## 16. Source/User/AI Content Boundary

Tender titles/descriptions, buyers, project/source narrative, requirement text, evidence quotes, document bodies, filenames, company/profile values, readiness notes, Proposal content, Recommendation rationale, Compliance status narrative, and AI explanations are rendered directly. They are not passed to `t()` or pseudo-transformed.

## 17. Enum Coverage

Known readiness document types, readiness statuses, expiry states, Compliance verdicts, requirement verdicts, Tender statuses, pursuit statuses, source-refresh statuses, and document presentation states have localized display mappings. Unknown readiness/Compliance values use safe generic localized labels without crashes or writes.

## 18. Formatter Consolidation

Customer P0/P1 surfaces use the Sprint 7 formatter layer for dates, date-times, numbers, currency, relative time, and file sizes. The file-size helper localizes only the number and preserves B/KB/MB/GB technical units. Currency performs no conversion and timezone remains UTC.

## 19. Remaining Formatter Exceptions

Direct Intl usage is approved inside `i18n/formatters.ts`; dedicated Admin remains deferred. `types/project.ts` contains a legacy test-only compatibility formatter with no runtime customer caller. Browser test fixtures intentionally invoke Intl to verify reference behavior. No unexplained customer-component direct formatter remains.

## 20. Pseudo-Locale Design

`en-XA` is a deterministic LTR stress locale that accents and expands static message copy, including ICU branch text, while preserving ICU syntax, placeholder names, rich tags, and dynamic values. It is enabled only when `NODE_ENV` is not production, `PLASMA_ENABLE_PSEUDO_LOCALE=1`, and the explicit `x-plasma-pseudo-locale: 1` request header is present.

## 21. Pseudo-Locale Layout Findings

Pseudo runs covered dashboard navigation, Explorer, Tender Details, Bid Preparation, Readiness, and Compliance at mobile width. Generic Compliance header/split-panel/modal constraints were made responsive. No critical page-level clipping or overflow remained.

## 22. Responsive QA

The formal matrix exercised 390px mobile, 768px tablet, and 1440px desktop for EN/UZ/RU Explorer, Readiness, Compliance, and Settings. Intentional inner table/document scrolling remains allowed; page-level overflow was zero.

## 23. Accessibility QA

`html lang` matched en/uz/ru and pseudo test context, selectors remained a named three-radio group, active state remained announced, radios retained keyboard focus, navigation had an accessible name, icon-only actions received localized labels, dialogs received dialog semantics, and loading states used status semantics. All active customer locales remain LTR.

## 24. Locale State Continuity

Locale switching retains canonical routes, Explorer query codes, current Tender identity, mounted form/workflow state, pursuit/Proposal state, and Readiness/Compliance domain data. P1 loading effects use translation refs so a message-function change does not create a locale-driven data reload.

## 25. SR-3 Refresh Continuity

The inherited 50-case runtime suite reconfirmed one refresh job, poller, and cursor; no duplicate completion; preserved New semantics; and a final notification in the active locale. The P1 work did not change refresh architecture.

## 26. Security / Authorization

Locale changes do not affect approval, role, tenant, authentication, or authorization state. Arabic and pseudo locale are not accepted preference values. No backend feature or schema change was introduced.

## 27. Passive Behavior

Localized reads did not create domain writes. Compliance analysis still starts only from its explicit button; opening pages does not generate Recommendations, hydrate documents, run Compliance, or start source refresh.

## 28. Bundle / Network Audit

The production build passed. Active customer catalogs remain server-loaded through explicit locale loaders; non-English requests merge English fallback with only the active locale. Pseudo loads English only and is non-production. No per-component message request, preference GET, duplicate `/users/me`, or extra refresh poller was introduced.

## 29. SSR / Cache Safety

The inherited multi-user browser matrix reconfirmed independent first-render locales and no cross-user authenticated HTML leak. Locale resolution remains request-scoped and middleware authority remains the current authenticated user.

## 30. Remaining English Literal Inventory

The P1 detector reported zero unexplained JSX/accessibility literals across its exact customer scope. Remaining English is classified as source/user/AI content, canonical brand/institution names (World Bank, ADB, GIZ, EBRD, UzEx, Plasma AI), dedicated Admin, technical/dev/test text, legacy compatibility helpers, Sprint 8 analysis/RTL boundary, or approved technical terms such as PDF, SHA-256, UTF-8, KB, and API codes.

## 31. Browser Acceptance

The formal Sprint 7.4 real-Chromium suite passed 120/120 cases. It includes EN/UZ/RU P0/P1 routes, content boundaries, accessible language controls, LTR proof, route/query continuity, three responsive widths, passive behavior, and pseudo P0/P1 stress.

## 32. Regression Results

All 13 frontend static test scripts passed. TypeScript, ESLint, literal audit, and production build passed. Sprint 7.2 browser regression passed 50/50; Sprint 7.3 passed 32/32. Focused backend coverage passed 137 tests plus 28 subtests. Connector gate passed 195 tests plus 4 subtests with one intentional skip.

## 33. Alembic / Migration Result

No Sprint 7.4 migration was created. The sole repository and database head remains `20260902_0001_s7_2_user_ui_locale`; `alembic check` reports no new upgrade operations.

## 34. Remaining Caveats

Dedicated Admin remains English-only by contract. The legacy Hunter Pydantic class-config warnings, Alembic path-separator warning, and Next.js middleware deprecation warning predate this task and are non-blocking.

## 35. Sprint 7 Closure Decision

**SPRINT 7 COMPLETE WITH NON-BLOCKING DOCUMENTED CAVEATS — READY FOR SPRINT 8**

## 36. Sprint 8 Entry Contract

Sprint 8 receives stable `User.ui_locale`, complete EN/UZ/RU customer UI, gated registry-only Arabic, next-intl request runtime, locale-neutral URLs, message and formatter infrastructure, source/user/AI content boundaries, the dedicated Admin boundary, and the Sprint 7.1 RTL risk map. Sprint 8 may add independent analysis/report language ownership, Arabic customer support, RTL, and directional behavior without redesigning Sprint 7 architecture.
