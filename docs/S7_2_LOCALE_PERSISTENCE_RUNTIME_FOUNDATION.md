# Sprint 7.2 — Locale Persistence and Runtime Foundation

Status: complete. This sprint adds durable per-user UI locale persistence and a request-scoped `next-intl` foundation. It intentionally does not add a visible locale selector, broad product translation, Arabic customer support, RTL, or analysis-language controls.

## 1. Previous State

Sprint 7.1 provided a behavior-neutral locale registry and message-validation prototype. The `User` ORM/schema, current-user bootstrap, Auth.js token/session, onboarding APIs, and company settings had no locale field. The root document was hardcoded to `lang="en"`, no translation provider was mounted, and no locale route segment existed.

## 2. User Locale Schema

`User.ui_locale` is a nullable `VARCHAR(8)`. It is the only durable customer UI-locale authority. `NULL` means the user has never explicitly selected a UI locale. `CompanyProfile` has no locale field and is not consulted for locale resolution.

## 3. Migration

One additive migration, revision `20260902_0001_s7_2_user_ui_locale`, extends parent `20260901_0001_sr2_3_connector_metrics`. It adds the nullable column and named check constraint `ck_users_ui_locale_allowed`; downgrade removes only that constraint and column.

## 4. Backend Validation

The database recognizes `NULL`, `en`, `uz`, `ru`, and future-known `ar`; unknown values fail the check constraint. The customer preference schema accepts exactly `en`, `uz`, or `ru`, rejects extra fields, and emits stable Pydantic validation type `unsupported_ui_locale` for Arabic and unknown inputs.

## 5. Own-User Preference API

`PATCH /api/v1/users/me/preferences` accepts `{ "ui_locale": "en|uz|ru" }` and returns the persisted locale. The route has no user identifier, uses the existing authenticated-user dependency, and can mutate only `current_user.ui_locale`. Pending/onboarding users may set presentation preferences; disabled, rejected, missing, and stale-auth users remain denied by the existing dependency.

## 6. Auth / Session Isolation

Locale is absent from backend JWT claims and Auth.js session authority. Saving locale neither increments `auth_version` nor rotates/revokes credentials. Tests fingerprinted `auth_version` and all non-locale user fields before and after mutation. No role, approval, tenant, CompanyProfile, Tender, document, recommendation, engagement, proposal, analysis, version, or refresh-job mutation was introduced.

## 7. Locale Registry

`frontend/i18n/locales.ts` remains the single frontend registry. Canonical known codes are `en`, `uz`, `ru`, and `ar`; customer-selectable codes are `en`, `uz`, and `ru`; default is `en`. Arabic remains known, disabled, non-selectable, and metadata-only with direction `rtl` reserved for future work.

## 8. Locale Normalization

The normalizer trims, lowercases, converts underscores to hyphens, and matches the primary BCP-47 subtag. Tests cover `en-US`, `uz-Latn-UZ`, `uz_Cyrl_UZ`, `ru-RU`, unsupported languages, Arabic gating, malformed values, and weighted request preferences.

## 9. next-intl Integration

`next-intl` is pinned to `4.14.2`, compatible with the existing Next.js `16.1.6` and React `19.2.3`; Next.js was not upgraded. The plugin uses `i18n/request.ts`, and type augmentation binds the app locale and English message shape.

## 10. Locale-Neutral Routing

No `[locale]`, `[lang]`, `/en`, `/uz`, or `/ru` route hierarchy was added. Existing URLs, deep links, query values, back/forward behavior, and canonical APIs are unchanged. Chromium verified locale switches retain `/dashboard/tenders?view=all&source=world_bank`.

## 11. Request Resolution

Resolution is: validated persisted-user header, valid presentation cookie, weighted supported `Accept-Language`, then English. Unsupported/malformed entries are skipped; `q=0` is excluded; equal weights preserve header order. Arabic cannot resolve through the customer runtime.

## 12. Authenticated Resolution

The existing protected-request middleware `/users/me` authority check reads `ui_locale` from the same response and forwards an allowlisted internal header into the request. Saved database locale therefore beats a stale cookie on the same server render. The middleware deletes any inbound spoofed copy before setting its validated value.

## 13. Pre-Auth Resolution

Public pages perform no user query for localization. A valid locale cookie wins, followed by supported `Accept-Language`, then English. Chromium proved Russian cookie rendering, Uzbek `Accept-Language` rendering, and unsupported-language English fallback.

## 14. Cookie Contract

`plasma_ui_locale` is a presentation/bootstrap cache, never durable authority. It is `SameSite=Lax`, `Secure` in production, path `/`, and bounded to one year. Authenticated middleware reconciles stale cookies to a saved user locale. `POST /api/ui-locale` accepts only exact customer-selectable codes and is protected by the existing API middleware.

## 15. SSR / Hydration

The server resolves one locale/message set and supplies the identical values to the client provider. Chromium captured Uzbek and Russian translated text in the SSR response and detected no hydration-language errors or English-to-localized flip. Suppressed hydration warnings were removed.

## 16. Provider Hierarchy

The root layout resolves locale/messages, sets `<html lang>`, and mounts one `NextIntlClientProvider` outside the existing `SessionProvider`. The dashboard continues to own one `SourceRefreshProvider`; pages are not individually wrapped and no locale key forces remounts.

## 17. SR-3 Provider Continuity

The locale action uses `router.refresh()` rather than a pathname change. Refresh translations are read through a mutable ref, so changing translator identity does not enter the polling effect dependency list. Chromium preserved the active job and session cursor, observed one poller/no overlap, retained dedupe state, and presented a later completion in the active Uzbek locale.

## 18. Message Resources

Matching English, Uzbek Latin, and Russian resources exist for `auth`, `common`, `errors`, `navigation`, and `refresh`. These are the deliberately narrow namespaces used by the 7.2 runtime. No Arabic production message set exists.

## 19. Message Loading

The loader has explicit dynamic imports per active locale. English loads alone for English; Uzbek/Russian load the selected catalog plus English fallback. It never imports all active catalogs into every request/client bundle.

## 20. Fallback

English is merged recursively as fallback authority before messages reach the provider. Runtime fallback renders `Translation unavailable`, not `undefined`, `[object Object]`, or a raw key. Diagnostics log only next-intl error codes, never interpolated customer/source values.

## 21. Key Validation

The promoted catalog validator flattens nested message trees and reports missing or extra leaves. The committed English/Uzbek/Russian catalogs pass with zero key/shape issues.

## 22. ICU Placeholder Validation

The validator extracts named and plural placeholders and requires target catalogs to match English. Committed catalogs pass exact `{count}`/`{source}` parity; a negative fixture proves missing, extra, and placeholder mismatch detection.

## 23. Pluralization

Actual `next-intl` translators prove English singular/plural, Uzbek count forms, and Russian one/few/many behavior. Named interpolation proves locale-specific ordering: English places count before source while Uzbek places source before count. A React server-rendered rich-message test proves dynamic markup-like source text is escaped.

## 24. Formatter APIs

Central helpers provide `formatDate`, `formatDateTime`, `formatNumber`, `formatCurrency`, and `formatRelativeTime`. They accept canonical values, apply `en-US`, `uz-Latn-UZ`, or `ru-RU` presentation, preserve the explicit/default UTC timezone policy, perform no FX conversion, and return an em dash for null/invalid dates, non-finite numbers, or invalid currencies.

## 25. Enum Display Pattern

`tenderStatusMessageKey` maps canonical Tender status codes to typed presentation keys with an unknown fallback; `translateTenderStatus` translates only the label. API/domain codes such as `OPEN` remain unchanged.

## 26. Error Localization Foundation

Only stable known codes `unsupported_ui_locale` and `locale_save_failed` are mapped. Unknown codes or backend prose resolve to a generic localized key; arbitrary English backend messages are never treated as translation keys.

## 27. Source/User/AI Content Boundaries

Source system display names, source-provided Tender text, user-authored content, and AI analysis/rationale remain original data. Locale changes translate presentation chrome only. Browser comparisons confirmed byte-for-byte-equivalent content payloads across Uzbek and Russian users.

## 28. Document Language

The root layout alone sets dynamic `<html lang="en|uz|ru">`. Customer paths remain LTR and do not set `dir=rtl`; Arabic cannot be selected or resolved.

## 29. Performance / Bundle Impact

Authenticated locale bootstrap adds zero API/DB requests: it reuses the existing no-store `/users/me` authority response. Request configuration reads headers/cookies locally; client navigation introduces no locale endpoint per page. Protected API requests retain their existing authority checks. Dynamic catalog imports bound message loading to English plus, only when needed, the active non-English catalog.

## 30. Security

The server allowlists every persisted/header/cookie/request locale before use, strips spoofed internal locale headers, rejects customer Arabic/unknown updates, forbids extra preference fields, preserves all existing account/session checks, and keeps locale outside authorization claims and domain content. Rich interpolation relies on React escaping. No localStorage locale authority, production access, deployment, or production mutation occurred.

## 31. Migration Evidence

`python3 scripts/test_s7_2_locale_migration.py` passed against disposable PostgreSQL databases. Fresh bootstrap reached `20260902_0001_s7_2_user_ui_locale`, accepted `NULL/en/uz/ru`, rejected unknown values, and returned clean `alembic check`. Existing-db upgrade preserved two users, `auth_version` values 31/32, approved/pending states, and produced `NULL` locale. Downgrade/re-upgrade preserved unrelated fields and rows. No disposable database leaked. `alembic heads` reports exactly one head: `20260902_0001_s7_2_user_ui_locale`.

## 32. Browser Acceptance

`python3 tests/s7-2-localization-browser-acceptance.py` completed the specified real Chromium matrix with `50/50 PASS`. It used isolated user contexts, a mocked backend authority, actual Next.js SSR/client hydration, cookie/session behavior, locale-neutral deep links, refresh polling/activity state, and exact domain payload comparisons.

## 33. Regression Results

Frontend localization tests: 19/19. All directly invoked frontend project-context/admin/My Tenders/Bid Preparation/engagement/Tender Details/cleanup/Explorer/SR-3/Hunter suites are green (114 tests total). Focused backend locale/auth and Sprint 3/5/6/SR-2.x suites are green; FastAPI startup and OpenAPI route generation pass. Connector gate: 195 passed, 1 expected skip, 4 subtests passed. The repository-wide recursive pytest collector is independently unhealthy because `test_ai.py` hardcodes a Windows `chdir` under WSL and `backend/scripts/test_*.py` collide with root test module names; the required suites were therefore invoked explicitly.

## 34. Deferred 7.3 Work

Sprint 7.3 owns visible onboarding/settings selectors, complete P0 customer-surface translation, full Explorer/Tender Details/My Tenders/Bid Preparation copy extraction, and full refresh UX translation. It must consume the existing registry, preference client, action ordering, request resolver, provider, catalogs, and formatter contracts without introducing locale routes or localStorage authority.

## 35. Sprint 8 Boundary

Sprint 8 owns `analysis_language`, report-language controls, Arabic customer enablement/translations, RTL layout/icon behavior, and analysis regeneration language. UI locale remains presentation-only and must not silently alter source, user, AI, document, currency, timezone, authorization, or analysis semantics.
