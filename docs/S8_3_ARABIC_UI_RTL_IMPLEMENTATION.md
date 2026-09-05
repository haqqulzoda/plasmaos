# Sprint 8.3 — Arabic Customer UI and RTL Implementation

## 1. Previous Arabic State

Arabic (`ar`) was a known product locale but was disabled and not customer-selectable. The database constraint already allowed `User.ui_locale='ar'`; therefore no schema change was required. Arabic analysis was, and remains, a separate known-but-gated capability.

## 2. Arabic Activation Gate

Activation was delivered atomically: complete catalogs, request resolution, persistence, server `lang`/`dir`, logical customer CSS, bidi boundaries, formatter support, static guards, and browser acceptance were implemented together. No intermediate selector-only state is intended for release.

## 3. Arabic Catalog

`frontend/messages/ar` contains all 15 customer namespaces and 866 leaf messages, matching the current English contract (the Sprint 7 estimate was 850 before later additions). Arabic is loaded through its own dynamic namespace index.

## 4. Translation Quality

The catalog uses procurement-oriented Modern Standard Arabic. High-significance copy was reviewed for Tender Explorer, recommendation/match score, pursuit, bid preparation, requirements, evidence, Compliance, readiness, source refresh, project, submission, and outcome states. Awkward literal outcome and action phrases were corrected.

Canonical terminology:

| EN | UZ | RU | AR | Notes | Do not translate |
|---|---|---|---|---|---|
| Tender | Tender | Тендер | مناقصة | Procurement opportunity | — |
| Tender Explorer | Tenderlar katalogi | Каталог тендеров | مستكشف المناقصات | Discovery surface | — |
| My Tenders | Mening tenderlarim | Мои тендеры | مناقصاتي | Saved/pursued work | — |
| Bid Preparation | Taklif tayyorlash | Подготовка заявки | إعداد العطاء | Proposal-backed preparation | — |
| Compliance analysis | Muvofiqlik tahlili | Анализ соответствия | تحليل الامتثال | Advisory analysis, not certification | — |
| Readiness record | Tayyorgarlik hujjati | Документ готовности | سجل الجاهزية | Company-owned evidence | — |
| Recommendation | Tavsiya | Рекомендация | توصية | Advisory only | — |
| Match score | Moslik bali | Оценка соответствия | درجة المطابقة | Not win probability | — |
| Requirement | Talab | Требование | متطلب | — | — |
| Evidence | Dalil | Доказательство | دليل | Source/user content stays original | — |
| Risk | Xavf | Риск | مخاطر | — | — |
| Source refresh | Manbani yangilash | Обновление источника | تحديث المصدر | Bounded source capability | — |
| Pursuit | Kuzatuv | Сопровождение | المتابعة | Customer engagement state | — |
| Saved / Evaluating / Preparing / Submitted | Saqlangan / Baholanmoqda / Tayyorlanmoqda / Yuborilgan | Сохранено / Оценивается / Подготавливается / Подано | محفوظ / قيد التقييم / قيد الإعداد / تم التقديم | Canonical workflow labels | — |
| Won / Lost / Dismissed | Yutildi / Yutqazildi / Rad etildi | Выигран / Проигран / Отклонён | تم الفوز بها / لم يتم الفوز بها / تم التجاهل | Recorded customer outcome only | — |
| Brand/source names | — | — | — | Preserve canonical spelling | World Bank, ADB, GIZ, EBRD, UzEx, Plasma AI, Google |
| Technical formats | — | — | — | LTR isolated | PDF, DOCX, Word, SHA-256, UTF-8, URL, currency codes |

## 5. UI Locale Registry

The sole frontend registry now marks Arabic `enabled: true`, `customerSelectable: true`, and `direction: 'rtl'`. `CustomerSelectableLocale` covers all four canonical UI locales: EN, UZ, RU, AR.

## 6. Backend Persistence Activation

The existing own-user preferences endpoint now accepts `ui_locale=ar` through the shared locale gate. It still changes only supplied preference fields and does not bump `auth_version` or alter authorization state.

## 7. Locale Resolution

Primary-subtag normalization maps `ar`, `ar-SA`, `ar-EG`, `ar-AE`, underscore variants, and other well-formed Arabic variants to canonical `ar`. Resolution precedence remains persisted user, presentation cookie, weighted `Accept-Language`, then English.

## 8. Root Lang / Dir

The async root layout is the sole application direction authority: `<html lang={locale} dir={directionForLocale(locale)}>`. Arabic maps to RTL; EN, UZ, RU, and the dev-only `en-XA` pseudo-locale map to LTR.

## 9. SSR / Hydration

Request-scoped locale resolution supplies locale, messages, `lang`, and `dir` before server rendering. There is no client mutation of `document.documentElement.lang` or `.dir`, no suppression of hydration warnings, and no LTR-to-RTL correction flash.

## 10. Logical CSS Migration

All customer semantic `ml/mr`, `pl/pr`, `left/right` inset, physical border, and `text-left/right` utilities identified by the Sprint 8.1 baseline were converted to logical `ms/me`, `ps/pe`, `start/end`, `border-s/e`, and `text-start/end` equivalents. A direction-neutral vertical entry animation replaced the Bid Preparation horizontal slide.

## 11. Remaining Physical Exceptions

The post-migration strict scan finds zero customer occurrences. The 21 Admin occurrences remain inside its explicit English/LTR island. Two landing-page background blobs retain physical coordinates because they are non-semantic decorative geometry.

## 12. Directional Icon Strategy

`rtl-mirror` is the semantic geometry marker. A root-scoped CSS rule mirrors only marked back/forward/previous/next icons in RTL. The automated icon audit requires every customer `ArrowLeft`, `ArrowRight`, `ChevronLeft`, `ChevronRight`, `MoveLeft`, or `MoveRight` instance to carry the marker.

## 13. Bidi Isolation

`BidiText` renders a semantic `<bdi dir="auto">`; `TechnicalText` renders `<bdi dir="ltr">`. CSS applies `unicode-bidi: plaintext` to auto content and `unicode-bidi: isolate` to explicit islands. No ad-hoc Unicode control characters are used.

## 14. Source Content Direction

Tender titles/descriptions, buyer/project/source names, requirements, evidence, document names, and source lines remain byte-for-text original and render with auto direction at customer boundaries.

## 15. User Content Direction

Company names, industries, addresses, director names, notes, readiness document names/issuers, proposal summaries, delivery text, and search fields use auto direction without translation or mutation.

## 16. Analysis Content Direction

Generated Compliance content derives direction from the stored `AnalysisVersion.analysis_language`: EN/UZ/RU are LTR, future/gated AR is RTL, and legacy `NULL` is auto. UI locale is never consulted for analysis direction.

## 17. Identifier LTR Islands

Tender/project/document IDs, hashes, registration numbers, email addresses, URLs, phones, dates used by native form controls, and technical references are explicitly LTR/isolate. Mixed filenames use auto isolation instead.

## 18. Arabic Formatting

The centralized formatter registry maps Arabic to `Intl` locale `ar`. Number, currency, UTC date/date-time, relative time, and file-size functions preserve economic/timezone semantics and delegate grammar/digit presentation to the runtime; no manual digit substitution or FX conversion was added.

## 19. Navigation RTL

The dashboard sidebar uses a logical end border and logical active-start marker. Navigation/header flex order, labels, focus order, and compact/mobile layout inherit root direction without a second direction owner.

## 20. Explorer RTL

Search icons/insets, filter alignment, pagination, result cards, source names, tender IDs, mixed titles, locations, and semantic chevrons are RTL-safe. Query parsing/building retains canonical values and locale-neutral routes.

## 21. Refresh RTL

The source menu and indicator anchor to logical end. Source names and generated notice strings are isolated at render boundaries. The provider identity, cursor, dedupe sets, poll cadence, aggregation queue, and New state are not keyed to locale.

## 22. Tender Details RTL

Back actions mirror, section layout uses logical behavior, source and project values are auto-directed, technical references are LTR-isolated, contacts classify natural versus email/phone values, and document filenames are bidi-safe.

## 23. My Tenders RTL

Search insets, card content, source/buyer/location/project values, forward actions, state controls, and pagination work under RTL while all engagement and source status codes remain canonical.

## 24. Bid Preparation RTL

List/detail navigation arrows mirror, tables use start/end alignment, proposal/user content uses auto direction, numeric price input is LTR, and source document names remain original. No Proposal body translation was introduced.

## 25. Compliance RTL

The workbench shell uses logical spacing/positioning. Analysis narratives follow version-language direction, evidence and requirements use auto direction, IDs/hashes use LTR isolation, and Arabic remains absent from both analysis selectors.

## 26. Readiness RTL

Forms classify natural, identifier, date, URL, and note fields explicitly. Wide tables scroll internally, headings/actions use logical alignment, and cells isolate names, numbers, issuers, and references appropriately.

## 27. Settings / Onboarding RTL

Both surfaces expose the same registry-driven Interface language selector. Locale switching happens before presentation refresh and preserves mounted form state. Natural fields are auto-directed; registration number, URL, and phone fields are LTR.

## 28. Dialog / Overlay RTL

Customer dialogs, confirmations, menus, toasts, and overlays inherit root direction. Their semantic positioning uses logical start/end and localized accessible names; source-bearing toast text is bidi-isolated.

## 29. Document Viewer RTL

Viewer chrome follows the Arabic shell, while source-document geometry and line numbering remain an explicit LTR document canvas. Each original source line is independently auto-directed, and the gutter uses a logical end border.

## 30. Admin Boundary

Dedicated `/admin` content is explicitly `<div lang="en" dir="ltr" data-admin-ltr-island>`. Its existing 21 physical utilities and five direction icons are intentional inside that island; the shared application root can remain Arabic/RTL without mirroring Admin tables and forms.

## 31. Responsive QA

The formal browser suite covers Arabic Explorer, Tender Details, My Tenders, Bid Preparation, Readiness, Settings, and Compliance at 390, 768, and 1440 CSS pixels, plus representative all-locale desktop checks. Wide data surfaces use internal scrolling rather than page overflow.

## 32. Accessibility QA

Arabic `html[lang][dir]`, localized accessible names, radiogroup/radio state, analysis selectors, filters, live regions, semantic status text, keyboard focus, and direction icon meaning are preserved. Mirrored icons are decorative geometry only. Existing reduced-motion behavior is retained.

## 33. State Continuity

Locale changes persist first, reconcile the presentation cookie second, then call `router.refresh()` on the same locale-neutral route. They do not use `push`, `replace`, pathname prefixes, or locale-keyed refresh providers.

## 34. Analysis-Language Independence

Valid combinations include Arabic UI with English, Uzbek, or Russian analysis. Chrome remains RTL, those analysis regions remain LTR, evidence remains auto, and export/report authority follows the selected immutable version.

## 35. Arabic Analysis Gate Preservation

Arabic is not in either customer analysis selector. Hand-crafted `default_analysis_language=ar` and per-run `analysis_language=ar` remain rejected. The endpoint still returns the Arabic PDF gate for an Arabic AnalysisVersion. Sprint 8.3 did not alter hashes, cache selection, version semantics, or PDF shaping.

## 36. Network / Bundle

Messages remain active-locale dynamic imports. Arabic directly loads only its complete catalog (no English merge/fallback request); UZ/RU retain the established compatibility merge. There are no per-component translation requests, locale-keyed pollers, or duplicate direction bootstrap requests. The 15 Arabic JSON namespaces add 56,377 raw bytes (13,583 bytes when concatenated and gzip-compressed); the optimized Next.js production build passes.

## 37. Static RTL Guards

`npm run audit:rtl` rejects customer physical direction utilities, unmarked semantic direction icons, client root direction mutations, a missing server root authority, or a missing Admin LTR island. `npm run test:s8-3-arabic-rtl` also checks catalogs, gates, bidi boundaries, formatting, payload stability, and content ownership.

## 38. Browser Acceptance

The formal suite is `frontend/tests/s8-3-arabic-rtl-browser-acceptance.py`. It uses real Chromium and covers activation, all four locales, P0/P1 surfaces, bidi, analysis islands and gates, responsive behavior, accessibility semantics, cross-user SSR isolation, passive rendering, and the Admin boundary. The final run passed 160/160 explicit checks.

## 39. Regression Results

All release gates executed before handoff passed: S8.3 frontend 18/18; localization foundation 19/19; Sprint 7.3 10/10; Sprint 7.4 10/10 plus its 120/120 Chromium regression; S8.2 frontend 7/7; all broader frontend product suites; ESLint; TypeScript; production build; 144 targeted/backend domain tests plus 55 subtests; connector gate 195 passed, 1 skipped, plus 4 subtests; S8.3 Chromium 160/160; and Alembic single-head/drift checks.

## 40. Sprint 8.4 Entry Contract

Sprint 8.4 must perform final release QA across all four UI locales and EN/UZ/RU analysis, keep Arabic analysis gated, exercise the complete UI/analysis independence matrix, repeat all-surface Arabic RTL and mixed-content checks, cover exports/mobile/accessibility, re-run EN/UZ/RU/refresh/Compliance regressions, and make the release decision. This Sprint does not perform or pre-empt that closure.

## 41. Remaining Risks

Arabic copy has automated parity/literal/claim-safety coverage and a focused procurement-language review, but final release governance should still include a named native Arabic procurement reviewer. Arabic analysis and Arabic PDF shaping remain intentionally unaccepted and gated for Sprint 8.4 or later. No deployment or production access was performed.
