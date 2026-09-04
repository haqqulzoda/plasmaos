# Sprint 7.3 — P0 Customer Localization

## 1. Previous State

Sprint 7.2 established request-scoped locale resolution, `User.ui_locale`, `PATCH /users/me/preferences`, the presentation cookie, locale-neutral URLs, root `lang`, dynamic per-locale catalog loading, and shared formatter/message-validation foundations. Sprint 7.3 reuses those authorities without a new API or migration.

## 2. Language Selector UX

One shared `LanguageSelector` presents exactly `English`, `O‘zbekcha`, and `Русский` as an accessible radio group. It is driven from the central locale registry, uses no flags, and cannot expose Arabic because Arabic remains disabled and non-customer-selectable.

## 3. Onboarding Integration

The selector appears immediately after the onboarding heading and before validation/errors and the company form. All onboarding headings, labels, helper text, validation, success/error states, actions, counts, regions, countries, and service presentation labels are localized. Submitted canonical geography and service values are unchanged.

## 4. Settings Integration

Settings exposes a separate top-level Interface language section before company-profile content. Company form labels, account statuses, targeting summaries, geography/service presentation labels, actions, loading/error/success states, and accessibility copy are localized.

## 5. Locale Save/Error Behavior

Selection is persist-first: the preference PATCH must succeed before the cookie is reconciled and `router.refresh()` runs. A failed preference write leaves the previous rendered locale and cookie active and shows a localized inline alert. The locale action does not push or replace the route.

## 6. Navigation Localization

The dashboard shell localizes navigation, logout, command-center, Admin Console, and accessible navigation labels. The authority terms are Tender Explorer / Tenderlar katalogi / Каталог тендеров; My Tenders / Mening tenderlarim / Мои тендеры; and Bid Preparation / Taklif tayyorlash / Подготовка заявки.

## 7. Auth/Access Localization

Public auth, pending-approval, and access-blocked customer journeys use EN/UZ/RU resources for headings, explanations, reasons, refresh/sign-out actions, errors, metadata, and accessible state announcements. Approval, disabled-account, stale-session, role, and tenant checks are unchanged.

## 8. Explorer Localization

Explorer headings, tabs, filters, known taxonomy display labels, lifecycle/document/status labels, sort options, result counts, pagination, new-only controls, empty/profile/error states, card metadata, and actions are localized. URL and backend values such as `view=recommended`, `status=open`, `new_only=true`, source keys, country/service values, and sort codes remain canonical.

## 9. Refresh UX Localization

The source menu, queued/running states, request outcomes, success/zero-new/partial/degraded/failure/unavailable completion notices, aggregation, live-region copy, dismissal, and View new tenders action are localized. The provider keeps its active poller, cursor, deduplication state, and timers while only replacing the translator reference. Source display names remain canonical.

## 10. Tender Details Localization

The P0 detail shell localizes navigation, lifecycle status, source classification labels, project and leadership labels, bounded requirement/document UI, Compliance/Readiness summary shell, pursuit, contacts, bid-preparation status/actions, loading/errors/empty states, and accessibility labels. Source title, description, project/contact data, filenames, requirements, and evidence stay original.

## 11. My Tenders Localization

My Tenders localizes filters, engagement and Tender status presentation, sort/search/pagination, cards, empty/error states, pursuit actions, confirmations, and accessibility copy. The engagement state machine and API action codes are unchanged and remain independent from Tender lifecycle status.

## 12. Bid Preparation Localization

The Proposal-backed list and workspace localize shell headings, artifact/Tender/pursuit statuses, actions, commercial labels, document states, safe failures, preview scaffolds, export controls, and accessible states. Proposal, user, source, and AI-authored body content remains byte-for-byte presentation content and is not passed through UI translation.

## 13. Enum Localization

Known Tender lifecycle, engagement, Proposal preparation, document, refresh, account, and section-state codes have exhaustive localized presentation mappings on P0 surfaces. Unknown values use localized safe fallbacks. Canonical request/query/payload codes are never translated.

## 14. Formatting Adoption

Touched P0 surfaces use the shared locale-aware date, date-time, number, currency, and relative-time formatters. Formatters preserve UTC/economic inputs and return a safe non-value marker rather than exposing `Invalid Date` or `NaN`. Counts and plurals use ICU messages.

## 15. Source Content Boundary

Tender/project/contact/document fields, source descriptions, evidence, URLs, IDs, filenames, currency codes, and canonical taxonomy values are preserved. Only surrounding UI and known presentation labels are localized.

## 16. User Content Boundary

Company/profile values, free-form onboarding/settings entries, Proposal edits, pricing inputs, and user-authored narrative remain original across locale changes, refreshes, reloads, and tabs.

## 17. AI/Compliance Boundary

Recommendation rationale, extracted requirement text, Compliance evidence, decision labels, and AI-generated Proposal narrative are not translated. Their labels and claim-safe explanatory shell are localized without implying eligibility, legal approval, certification, win probability, or guaranteed compliance.

## 18. Source Name Policy

World Bank, ADB, GIZ, EBRD, UzEx, Plasma AI, and runtime source-registry display names are treated as proper names. They are interpolated into localized messages but not translated or used as locale keys.

## 19. Terminology Glossary Finalization

Sprint 7.1 terminology remains authoritative. Final P0 copy consistently distinguishes Tender, Project, Recommendation, Match score, Pursuit, Compliance, Readiness, source status, document status, and Proposal/Bid Preparation concepts.

## 20. Uzbek Quality Review

Uzbek uses Latin script, glossary-approved product terms, contextual actions, natural count forms, and non-inflated Recommendation/Compliance/refresh claims. Catalog comparison found only intentional English-identical values: `IT`, punctuation-only document-count formatting, and the glossary-approved domain word `Tender` in two interpolated labels.

## 21. Russian Quality Review

Russian uses glossary-approved terms and ICU one/few/many forms where needed. Catalog comparison found only intentional English-identical values: `IT` and punctuation-only document-count formatting. No raw keys, broken interpolation, or stronger Recommendation/Compliance/refresh claims were observed.

## 22. Accessibility

Selectors use radio-group semantics, localized accessible names, `aria-checked`, keyboard-focusable buttons, focus-visible rings, localized live progress, and scoped alerts. P0 tabs, pagination, errors, refresh notices, New badge, confirmation dialogs, and section navigation retain semantic roles and localized accessible names. Root `html lang` follows the resolved locale.

## 23. Responsive Layout

Priority P0 layouts retain responsive grid/wrap/overflow behavior for longer Uzbek and Russian copy. Real Chromium checks at 390×844 found no document-level horizontal overflow in EN, UZ, or RU; desktop checks used 1360×900. Tablet behavior is covered by the same responsive breakpoints and static layout contracts.

## 24. State Preservation

`router.refresh()` preserves mounted onboarding/settings form state. Explorer URL/query values, Tender ID, refresh cursor/deduplication state, pursuit state, and Proposal content remain authoritative. Browser acceptance verified unsaved onboarding/company input continuity, unchanged Explorer queries, refresh-poller continuity, reload persistence, and new-tab persistence.

## 25. SR-3 Continuity

The dashboard retains a single refresh provider. Translator updates occur through a ref without locale-keyed remounts; active refresh, status polling, activity cursor, terminal-event deduplication, aggregated notices, and New-badge timing continue across locale changes. SR-3 unit/static and browser continuity tests pass.

## 26. Coverage Metrics

Automated flattening and ICU validation cover 11 active P0 namespaces.

| Locale | Expected keys | Present | Missing | Extra | Placeholder mismatch | Observed P0 fallback hits | Review status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| EN | 588 | 588 | 0 | 0 | 0 | 0 | Baseline/context reviewed |
| UZ | 588 | 588 | 0 | 0 | 0 | 0 | Glossary/context/plural review passed |
| RU | 588 | 588 | 0 | 0 | 0 | 0 | Glossary/context/plural review passed |

Resources contain no machine-placeholder markers. Independent stakeholder native-language sign-off is operational release governance, not a missing implementation key.

## 27. Remaining P1 Literals

Intentionally deferred scope is the full Compliance workbench, Readiness Vault secondary surfaces, dashboard-home secondary cards, document-viewer chrome outside the localized Bid Preparation preview scaffold, dedicated Admin pages, legacy/export templates, and non-P0 global literal elimination. Source/user/AI/export content is not a fallback defect.

## 28. Browser Acceptance

Real Chromium passed 32/32 Sprint 7.3 cases covering visible onboarding/settings controls, Arabic/flag absence, keyboard focus, successful and failed saves, route/form persistence, reload/new-tab persistence, EN/UZ/RU P0 shells, Explorer query/New/source boundaries, Tender Details evidence boundaries, My Tenders semantics, Bid Preparation Proposal boundaries, 390px layout, root `lang`, and passivity. The inherited locale-runtime matrix passed 50/50, including refresh continuity, formatter behavior, cross-user isolation, blocked access, and content boundaries.

## 29. Regression Results

TypeScript, ESLint, production build, 12 frontend test scripts, the focused backend/API suite (128 passed plus 54 subtests), and the connector regression gate (195 passed plus 4 subtests; one intentional skip) pass. Alembic reports the sole head/current revision `20260902_0001_s7_2_user_ui_locale` and no new upgrade operations. The only observed warnings are the pre-existing Pydantic v2 class-config deprecations in legacy Hunter compatibility schemas.

## 30. Deferred Sprint 7.4 Work

Sprint 7.4 owns full P1 Compliance shell localization, Readiness secondary surfaces, residual formatter migration outside P0, pseudo-locale tooling, remaining non-P0 product-copy elimination, dedicated Admin localization planning, a final multilingual layout sweep, and the broader non-P0 accessibility audit.

## 31. Sprint 8 Boundary

Sprint 8 owns Arabic customer support, Arabic resources, `dir=rtl`, logical-direction layout conversion, RTL icon/table/panel QA, and any explicit AI/analysis/export language authority. Sprint 7.3 does not expose Arabic, add RTL behavior, translate source/user/AI content, or infer document language from UI locale.
