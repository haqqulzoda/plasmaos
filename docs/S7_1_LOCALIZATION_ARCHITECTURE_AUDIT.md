# Sprint 7.1 — Product Localization Architecture & Locale Authority Foundation

Audit date: 2026-09-02  
Scope: repository audit and behavior-neutral foundation only  
Runtime baseline: Next.js 16.1.6, React 19.2.3, Auth.js 5 beta, FastAPI, SQLAlchemy, Alembic

## 1. Executive Summary

PlasmaOS currently has no product-localization runtime. Customer and admin copy is embedded in React components and TypeScript helpers, `<html lang="en">` is static, formatting is predominantly fixed to English, and neither `User` nor `CompanyProfile` has a locale field. Source, user, and AI content are already represented separately enough that localization can remain a presentation concern if Sprint 7 preserves the boundaries in this document.

Sprint 7.1 adds only a behavior-neutral typed contract in `frontend/i18n/locales.ts` and focused contract tests. It does not add dictionaries, install a runtime, alter rendering, add a selector, mutate data, add locale routes, implement analysis-language behavior, enable Arabic, or deploy anything.

Locked outcomes:

- UI locale authority is the individual authenticated `User`; it is never `CompanyProfile`.
- Canonical product identifiers are `en`, `uz`, `ru`, and reserved `ar`.
- English, Uzbek Latin, and Russian are enabled/customer-selectable. Arabic is known but disabled and not customer-selectable until Sprint 8 RTL acceptance.
- The product default is English. A saved user choice outranks every presentation hint.
- No suitable persistence column exists, so Sprint 7.2 needs one additive nullable `users.ui_locale` migration.
- Routes remain locale-neutral.
- Recommended runtime decision: **INTRODUCE next-intl IN 7.2**.

## 2. Current I18n State

Repository searches covered `i18n`, locale/language terms, dictionaries/messages/translations, all `Intl` and `toLocale*` calls, browser language and `Accept-Language`, cookies/storage, document language/direction, hard-coded copy, accessibility copy, enums, errors, exports, and RTL-sensitive layout.

| Concern | Current evidence | Result |
| --- | --- | --- |
| Product i18n dependency | `frontend/package.json` and lockfile | No `next-intl`, `react-i18next`, `i18next`, `next-i18next`, FormatJS, or Lingui dependency. Transitive `language-tags` is not an app runtime. |
| Dictionaries/messages | `frontend/app`, `frontend/components`, `frontend/lib` | None. Copy is in JSX, arrays/maps, and helper return values. |
| Document locale | `frontend/app/layout.tsx` | Static `<html lang="en">`; no runtime `lang` or `dir`. |
| Provider | `frontend/app/providers.tsx` | Auth.js `SessionProvider` only. |
| Rendering | route/component inventory | Root layout and redirect-only pages are server components; nearly all product pages and shared interactive components are client components. |
| Formatting | files in section 16 | Local `Intl`/`toLocale*` calls, mainly fixed `en-US`/`en`; no shared formatter. |
| Locale detection | complete frontend search | No `navigator.language`, `Accept-Language`, locale cookie, or locale resolver. |
| Preference | models, migrations, schemas, `/users/me`, Auth.js | No locale field or session value. |
| Plurals/interpolation | Explorer and refresh helpers | English manual singular suffixes and template strings. |
| RTL | app/components and Tailwind classes | No RTL runtime; many physical left/right assumptions. |

The only language-related backend matches are prose in AI extraction prompts and PostgreSQL `LANGUAGE plpgsql`. They are not UI preference fields or localization infrastructure.

## 3. Existing Language Fields

No model, schema, migration, API response, or Auth.js type contains `ui_locale`, `preferred_language`, `locale`, `source_language`, `document_language`, or `report_language`.

| Existing datum | Owner and meaning | Reuse for UI locale? | Required boundary |
| --- | --- | --- | --- |
| `User` identity/role fields in `backend/app/models/user.py` | Individual user identity, subscription, approval, and authorization | No suitable field exists | Add a dedicated `User.ui_locale`; never overload role/auth fields. |
| Legacy company-detail columns on `User` | Backward-compatible company details used by proposal export | No | Company content remains independent. |
| `CompanyProfile` fields | Company identity, targets, approval, readiness data | No | Two users in one company may choose different UI locales. |
| `target_regions`, `target_countries`, `country`, `region` | Company targeting or source procurement geography | No | Geography is not language or locale. |
| `currency`/`price_currency` | Economic denomination from Tender/Proposal data | No | Locale formats currency; it never chooses or converts it. |
| timezone-aware timestamps; explicit UTC project formatting | Domain time instants and a current display choice | No | Locale never determines timezone. |
| Tender title/description/buyer/contact/document text | Source-owned evidence and metadata | No | Preserve original content. There is no source-language field today. |
| Compliance/Recommendation/analysis text | AI-generated analysis under existing analysis semantics | No | Independent analysis-language authority belongs to Sprint 8. |
| Proposal/company notes/filenames | User-generated data | No | Preserve original content. |
| English/Russian/Uzbek labels in PDF templates | Static export-template copy, not a stored preference | No | Export/report language needs a separate later contract. |

Persistence audit result: **DOES NOT EXIST — ADD FIELD IN 7.2**.

## 4. Canonical UI Locale Authority

The sole durable authority is conceptually `User.ui_locale`. It is an optional presentation preference owned by the authenticated user. `CompanyProfile` is explicitly not an authority, and admins must not change it through account-lifecycle operations.

Changing UI locale must not increment `auth_version`, revoke or rotate credentials for locale reasons, require logout, alter access checks, or mutate Tender, TenderEngagement, Proposal, AnalysisVersion, Recommendation, evidence, reports, or source data.

The typed name is locked as `UI_LOCALE_PERSISTENCE_FIELD = "ui_locale"`. The backend migration/API is intentionally deferred to 7.2.

## 5. Locale Codes

Stable product codes are independent of browser regional variants:

| Code | Product meaning | Browser examples mapped to it | Direction | Sprint 7 customer state |
| --- | --- | --- | --- | --- |
| `en` | English | `en`, `en-US`, `en-GB` | LTR | enabled/selectable |
| `uz` | Uzbek Latin | `uz`, `uz-UZ`, `uz-Latn-UZ` | LTR | enabled/selectable |
| `ru` | Russian | `ru`, `ru-RU` | LTR | enabled/selectable |
| `ar` | Arabic, reserved | `ar`, `ar-EG`, other `ar-*` | RTL metadata | disabled/not selectable |

The resolver performs case-insensitive primary-subtag mapping and tolerates underscore inputs defensively. `uz-Cyrl` maps to the one `uz` product locale but does not create or imply a Cyrillic UI resource; when selected in Sprint 7, that resource is Uzbek Latin. A distinct `uz-Cyrl` product locale requires a future explicit requirement.

## 6. Locale Registry

`frontend/i18n/locales.ts` is the single registry contract. Each `LocaleDefinition` contains:

- `code`
- `displayNameNative`
- `displayNameEnglish`
- `enabled`
- `customerSelectable`
- `direction`

The exact registry state is tested: `en`, `uz`, and `ru` are enabled/selectable/LTR; `ar` is disabled/not selectable/RTL. Native selector labels are `English`, `O‘zbekcha`, and `Русский`. Onboarding, settings, document setup, tests, and any future selector must import this registry rather than duplicate arrays.

Arabic gating is fail-closed: `toProductLocale("ar-EG")` recognizes metadata, while `toCustomerSelectableLocale("ar-EG")` and the customer resolver reject it. No current production module imports the registry to expose Arabic.

## 7. Default / Resolution Policy

`DEFAULT_PRODUCT_LOCALE` is `en`.

Authenticated request precedence:

1. valid persisted `User.ui_locale`;
2. valid temporary onboarding choice (the presentation cookie once 7.2 implements it), only while no persisted choice exists;
3. first supported customer-selectable browser/`Accept-Language` locale;
4. English product default.

Unauthenticated request precedence is valid presentation cookie, supported `Accept-Language`, then English. Unsupported, malformed, disabled, and reserved values are ignored. A stale cookie must never override a persisted user preference.

The pure `resolveCustomerLocale` prototype locks this order without reading browser, cookie, auth, or API state and without affecting current rendering.

Routes remain `/dashboard/...`, `/admin/...`, and `/`; no locale path segment, localized slug, redirect, or localized query value is introduced.

## 8. Persistence Decision

Sprint 7.2 must add exactly one additive field:

| Item | Contract |
| --- | --- |
| Column | `users.ui_locale` |
| Type | `VARCHAR(8)` / SQLAlchemy `String(8)` |
| Nullability/default | nullable, no server default; `NULL` means the user has never explicitly chosen a locale |
| Database validation | check constraint permits canonical known codes `en`, `uz`, `ru`, `ar`; customer API separately permits only registry-enabled/selectable values |
| Historical rows | remain `NULL`; resolve browser hint, then English. Do not backfill `en`, because that would falsely look like an explicit choice. |
| Read API | add nullable `ui_locale` to `/users/me` response (and the one bootstrap DTO used by the server resolver) |
| Write API | authenticated self-service `PATCH /users/me/preferences`; no arbitrary user ID |
| Write validation in Sprint 7 | `en`, `uz`, `ru` only; reject `ar` until Sprint 8 gate opens |
| Authorization | any authenticated user may update only their own preference, including during onboarding; not tied to company approval |
| Side effects | no `auth_version` change, no analysis/domain mutation |

Exact required outcome: **SPRINT 7.2 ADDITIVE USER LOCALE MIGRATION REQUIRED**.

No migration was created in Sprint 7.1. The sole repository Alembic head remains `20260901_0001_sr2_3_connector_metrics`.

## 9. Auth / Session Interaction

`frontend/auth.ts` currently exchanges Google identity for a backend JWT, refreshes backend authority on Auth.js callbacks, and copies authorization/onboarding claims into the JWT/session. Backend `auth.py` similarly embeds role, approval, company, and onboarding state. Locale is absent.

`ui_locale` is a preference, not an authorization claim. Do not put it in the signed backend access-token claim set and do not call `bump_auth_version` when it changes. Auth.js may hold request-local resolved presentation state only if needed by the runtime, but the authoritative saved value must come from the user bootstrap endpoint and be refreshable without reauthentication.

The 7.2 server request resolver should use the current Auth.js server session/access token to obtain `User.ui_locale` once with `cache: "no-store"`, combine it with request cookie/header hints, and pass one resolved locale/message set into the root provider. It must fail closed for authorization exactly as today; locale failure falls back to safe presentation behavior and never grants access.

## 10. SSR / Client Architecture

Current classification:

- Server: `frontend/app/layout.tsx`, API/document route handlers, and redirect-only legacy pages.
- Client: public auth page, dashboard/admin layouts, all substantive dashboard/admin pages, and all interactive shared components.
- Mixed request: the server root wraps client `Providers`, which currently contains only `SessionProvider`.

7.2 architecture:

1. A request-scoped server locale resolver reads authenticated `User.ui_locale` first; otherwise cookie/header/default.
2. The server loads only that locale's domain resources and renders `<html lang={locale}>`.
3. It wraps `SessionProvider` and the existing app in `NextIntlClientProvider` using the same locale/messages used for server output.
4. Server components use the server translator; client components use `useTranslations`; metadata uses server translations.
5. No client reads localStorage after an English SSR pass. The initial server and client locale is identical.
6. A successful settings change updates persistence and the presentation cookie, updates provider state, and calls `router.refresh()` where necessary. It does not remount/restart domain providers.

This avoids normal-path English-to-Uzbek/Russian hydration replacement. Pre-auth browser detection is server-side through `Accept-Language`; the cookie preserves an explicit pre-auth/onboarding choice.

## 11. Translation Resource Design

Create domain-grouped JSON resources in 7.2, not 7.1:

```text
frontend/messages/
  en/{common,navigation,auth,onboarding,settings,explorer,tenderDetails,myTenders,bidPreparation,compliance,readiness,refresh,errors}.json
  uz/{same files}.json
  ru/{same files}.json
frontend/i18n/
  request.ts
  messages.ts
  formats.ts
  locales.ts
```

English is the schema/fallback authority. A typed loader merges namespaces for the requested locale and dynamically imports only that locale. `ar` has registry metadata but no customer message bundle requirement before Sprint 8. Avoid one monolithic file and avoid shipping all locales to every browser.

Required namespaces are already locked in `MESSAGE_NAMESPACES`: `common`, `navigation`, `auth`, `onboarding`, `settings`, `explorer`, `tenderDetails`, `myTenders`, `bidPreparation`, `compliance`, `readiness`, `refresh`, and `errors`. Admin gets a separate namespace only when its scope is scheduled.

## 12. Translation Key Strategy

Use semantic, domain-qualified keys such as `navigation.tenders`, `explorer.filters.source`, `refresh.notification.newTenders`, and `errors.companyProfile.loadFailed`; do not use raw English sentences as keys.

Rules:

- Keys express semantic intent, not layout or an English fragment.
- Keep canonical API enum values out of keys passed over the wire; map them at presentation boundaries (for example `common.status.tender.OPEN`).
- Full sentences own their punctuation and grammar. Do not concatenate translated fragments.
- Dynamic values use named ICU placeholders such as `{count}`, `{source}`, `{date}`, `{company}`, and `{status}`.
- Rich messages use `t.rich` with an allowlisted component map; never raw injected HTML.
- Accessibility keys live beside their component domain (`explorer.a11y.dismissNew`, not a forgotten parallel system).
- English, Uzbek, and Russian must have identical leaf keys and placeholder sets.
- CI reports missing, extra, and placeholder-mismatched keys; dead-key detection is advisory initially and becomes scheduled cleanup.

## 13. Product / Source / User / AI Content Boundaries

The behavior-neutral `LOCALIZATION_CONTENT_POLICY` is tested and locks five classes:

| Class | Examples | Policy |
| --- | --- | --- |
| Product UI | navigation, buttons, headings, form labels, helper/empty/error text, badges, a11y text | Translate. |
| Source-provided | Tender title/description, official requirements/quotes, buyer/contact text, project/source fields, source URLs, original filenames | Preserve original; do not silently machine-translate. |
| User-generated | Proposal copy, Company Profile values, notes, uploaded filenames | Preserve original. Translate only surrounding UI. |
| AI-generated analysis | Compliance explanations, evidence reasoning, Recommendation rationale, AnalysisVersion output | Preserve current analysis language; independent control is Sprint 8. |
| Enum | stored/API status/action/source codes | Preserve code; translate only the visible label. |

Changing UI locale is therefore presentation-only and cannot trigger analysis, Recommendation, refresh, source hydration, export regeneration, engagement transitions, proposal changes, or evidence rewriting.

Institution and brand identities—World Bank, ADB, GIZ, EBRD, UzEx, and Plasma AI—remain canonical unless a later reviewed product decision adopts an established localized institution name.

## 14. Enum Localization

Current enum presentation is spread across helpers and components:

| Domain | Canonical values/evidence | Current presentation site | 7.2/7.3 rule |
| --- | --- | --- | --- |
| Tender lifecycle | `OPEN`, `CLOSED`, `CANCELLED`, `UNKNOWN` in `frontend/types/tender.ts` | `tenderStatusLabel`, Explorer `STATUSES` | Keep URL/API codes; translate labels including truthful unknown actionability. |
| Tender documents | `documents_available`, `files_missing`, `metadata_only`, `access_required`, `no_documents_found`, `processing`, `partial`, `failed` | `documentStatusLabel`, Tender Details | Translate label; preserve availability/source semantics. |
| Pursuit | `SAVED`, `EVALUATING`, `PREPARING`, `SUBMITTED`, `WON`, `LOST`, `DISMISSED` | `frontend/types/engagement.ts`, action components | Keep persistence/API codes; translate label, description, action/confirmation. |
| Proposal artifact | `DRAFT`, `GENERATING`, `COMPLETED`, `SUBMITTED` | `frontend/types/bid-preparation.ts` | Translate display only; do not confuse artifact state with pursuit. |
| Compliance | `NOT_ELIGIBLE`, `NEEDS_REVIEW`, `ELIGIBLE_WITH_REVIEW`, `COMPLIANT`; match verdict/method and section states | Compliance page/types | Translate restrained shell labels only; do not strengthen into eligibility guarantee/legal certification. |
| Refresh | queued/running/completed/partial/failed/source_unavailable plus degraded/fallback | source refresh types/provider/policy | Translate from structured event at presentation time; do not persist translated notification text. |
| Readiness | document types/statuses and expiry state | `frontend/lib/readiness.ts` | Keep values, translate option/visible labels. |
| Account/admin | pending/approved/rejected/disabled, platform roles | `frontend/lib/adminOperations.ts`, settings/pending/admin | Shared customer access shell may translate; admin full copy deferred. |

Several current components create labels by splitting/replacing underscores (`settings/page.tsx`, Tender Details project enrichment, admin company detail). Replace these with exhaustive translation maps before those surfaces are declared covered. Unknown codes must render a safe localized fallback plus telemetry, never be written back as a translated value.

## 15. Error Localization Boundary

The backend predominantly returns raw English `HTTPException.detail`; Pydantic 422 errors are framework structures containing field locations and English messages. Examples exist across `api/deps.py`, `auth.py`, `users.py`, `explorer.py`, `my_tenders.py`, `proposals.py`, `tenders.py`, `vault.py`, and source refresh services. Some endpoint details include exception strings and terminal/source reasons.

The frontend inconsistently handles them: many pages replace failures with local English copy; `PrepareBidButton`, `EngagementWorkflowActions`, Bid Preparation, and parts of Compliance can surface `response.data.detail`; refresh terminal reasons can be shown directly. `frontend/lib/sourceRefresh.ts` recognizes cursor-related 422 responses by HTTP status, not a stable error code.

Target boundary:

- Backend exposes stable machine-readable `code`, optional `field`, safe parameters, and a canonical diagnostic `detail` for compatibility/logging.
- Frontend translates known stable codes in `errors`; unknown failures use a localized safe generic message and are logged without leaking internals.
- Pydantic validation maps field locations/types to localized form messages; do not translate arbitrary framework prose as keys.
- Safe source terminal reasons and source/evidence content remain original and are visibly distinguished from translated shell copy.
- Never copy arbitrary exception strings into message resources.

Broad error-envelope refactoring is not part of 7.1. Inventory priority for 7.2/7.3 is auth/access, company preference save, Explorer, refresh, engagement, document access, Bid Preparation, and Compliance export errors.

## 16. Date / Number / Currency Formatting

Current customer-visible formatter inventory:

| File | Current behavior/gap |
| --- | --- |
| `frontend/types/project.ts:98` | project date fixed `en-US`, UTC |
| `frontend/components/tenders/RecommendationSummary.tsx:7` | date uses `toLocaleDateString` with explicit English options |
| `frontend/app/dashboard/page.tsx:108-127` | fixed `en-US` dates and bespoke English relative words (`Today`, days/count grammar) |
| `frontend/app/dashboard/tenders/page.tsx:114,126` | fixed `en-US` date and currency formatting; USD fallback |
| `frontend/app/dashboard/tenders/[tenderId]/page.tsx:56-78` | fixed `en-US` date/time and number plus currency-code concatenation |
| `frontend/app/dashboard/my-tenders/page.tsx:56-66` | fixed `en` date/number and currency-code concatenation |
| `frontend/app/dashboard/bid-preparation/page.tsx:38-50` | English `B`/`M` compact strings, fixed `en-US` date/number, concatenation |
| `frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx:81-82,179,209-216,691-705` | fixed `en-US` plus locale-default `toLocaleString()` calls |
| `frontend/app/admin/page.tsx:31` | fixed `en-US` number |
| `frontend/app/admin/audit/page.tsx:55` | environment-default `toLocaleString()` |

Create in 7.2 one formatter module (or thin wrappers around next-intl):

```ts
formatDate(value, {locale, timeZone, dateStyle})
formatDateTime(value, {locale, timeZone, dateStyle, timeStyle})
formatNumber(value, {locale, ...numberOptions})
formatCurrency(amount, currencyCode, {locale, ...numberOptions})
formatRelativeTime(value, now, {locale, timeZone})
```

The current `ui_locale` controls translation and presentation formatting in Sprint 7. `timeZone` remains explicit and independent; default it from the existing product/domain policy, not from locale. Dates remain stored instants/UTC semantics. Deadline calculations, `new_until`, server time, source parsing, and World Bank/project semantics do not change.

`formatCurrency` receives amount and ISO currency separately and performs no FX conversion. It may vary punctuation/symbol placement but must preserve the amount and denomination. API/persistence stays numeric/code-based.

## 17. Pluralization / Interpolation

Confirmed English grammar hazards include:

- `frontend/lib/sourceRefreshPolicy.ts`: `countCopy`, event lines, multi-source counts, and source/count template strings.
- `frontend/app/dashboard/tenders/page.tsx`: `{count} new tender{count === 1 ? "" : "s"}`, result ranges, item counts, and pagination.
- `frontend/app/dashboard/page.tsx`: deadline/relative-time phrases and counts.
- Tender Details: historical leadership counts and interpolated source/date/status sentences.
- Bid Preparation: compact budget suffixes, created/deadline copy, totals and currency concatenation.
- Recommendation: `Recommended on {date}`, score suffix, and claim-sensitive explanation.

Use ICU cardinal plural/select messages with named parameters; do not reproduce `count === 1` in each component. Word order belongs to each locale resource. Relative time uses locale-aware formatter rules rather than translated `ago/today/yesterday` fragments.

Rich copy uses `t.rich` with escaped React children and an allowlist for links/emphasis. Source/user values passed as interpolation remain text and are never `dangerouslySetInnerHTML`. Links, bold spans, inline actions, and icons stay structural; translators control complete surrounding phrases.

## 18. Onboarding Language Contract

`frontend/app/dashboard/onboarding/page.tsx` is a client form reached after Google creates the `User` and before `CompanyProfile` exists. It currently posts only company data to `/users/me/company/onboarding`, refreshes the Auth.js session for access state, and routes to pending approval.

In 7.3, place an `Interface language` choice at the top of the first onboarding view, before company copy, using the central registry and native language names. Because the `User` already exists, save through the self-preference endpoint independently of company submission. Do not attach locale to the company onboarding payload.

Selection flow: choose `English`, `O‘zbekcha`, or `Русский`; save preference; update presentation cookie/provider; set document `lang`; refresh server content if necessary; keep the route and form state. No flags. Arabic is absent.

Persistence failure policy is persist-first: keep the prior active locale, leave the new option uncommitted, show a localized error, and allow retry. Never show a saved state for an unpersisted choice.

## 19. Settings Language Contract

`frontend/app/dashboard/settings/page.tsx` is currently `Company profile`, backed only by `/users/me/company`. In 7.3, add a clearly separate `Interface language` account-preference section above or outside the Company form. It reads/writes `/users/me/preferences`, not `CompanyProfile`.

On successful save, update UI without logout, keep route and domain state, update `<html lang>`, and use `router.refresh()` only to synchronize server-rendered output. New tabs/page loads read persisted user locale. An optional `BroadcastChannel`/storage event may synchronize already-open tabs later; it is not a 7.3 blocker. Do not use localStorage as authority.

## 20. Admin Localization Decision

Decision: localize shared customer/auth/access shell strings that an admin also encounters, but keep dedicated `/admin` routes English-only during Sprint 7. This is option B from the audit.

Evidence: Admin has a separate client layout and multiple dense operational pages (`admin/page.tsx`, approvals, audit, company detail), with status tables, pagination, confirmation/reason text, and 54 observed direct JSX/a11y literal sites. Expanding full Admin localization would dilute the customer rollout and its approval/audit semantics need dedicated review. The admin document `lang` must still reflect the current UI context once the root runtime exists; untranslated Admin copy is an explicitly tracked English-only scope, not a claim of coverage.

## 21. Terminology Glossary

This is the Sprint 7 translation authority proposal. Uzbek is Latin script. A native procurement-language reviewer must approve Uzbek and Russian before release.

| Concept | English | Uzbek (Latin) | Russian | Do not translate? | Notes |
| --- | --- | --- | --- | --- | --- |
| Tender | Tender | Tender | Тендер | No | Keep procurement meaning; do not alternate casually with general competition terms. |
| Tender Explorer | Tender Explorer | Tenderlar katalogi | Каталог тендеров | No | Product surface name. |
| My Tenders | My Tenders | Mening tenderlarim | Мои тендеры | No | User-owned pursuit list. |
| Bid Preparation | Bid Preparation | Taklif tayyorlash | Подготовка заявки | No | Keep separate from submitted pursuit status. |
| Compliance | Compliance | Muvofiqlik tahlili | Анализ соответствия | No | Analysis, not legal certification. |
| Readiness | Readiness | Tayyorgarlik | Готовность | No | Company evidence readiness. |
| Readiness Vault | Readiness Vault | Tayyorgarlik hujjatlari | Документы готовности | No | Prefer meaning over literal “vault.” |
| Recommendation | Recommendation | Tavsiya | Рекомендация | No | Not a guarantee. |
| Match score | Match score | Moslik bali | Оценка соответствия | No | Never “win probability.” |
| Source | Source | Manba | Источник | No | Source identity itself remains canonical. |
| Refresh | Refresh | Yangilash | Обновить | No | UI action; does not alter connector semantics. |
| New | New | Yangi | Новое | No | Display badge; backend `is_new/new_until` remains authoritative. |
| Project | Project | Loyiha | Проект | No | Not Tender. |
| Project Context | Project Context | Loyiha ma’lumotlari | Контекст проекта | No | Source project data. |
| Procurement Contacts | Procurement Contacts | Xarid bo‘yicha kontaktlar | Контакты по закупке | No | Not project leadership. |
| Documents | Documents | Hujjatlar | Документы | No | Source/user document values remain original. |
| Requirements | Requirements | Talablar | Требования | No | Preserve source-derived vs analysis-derived provenance. |
| Pursuit status | Pursuit status | Ishtirok holati | Статус участия | No | Never substitute Tender lifecycle. |
| Company Profile | Company Profile | Kompaniya profili | Профиль компании | No | Not locale authority. |
| World Bank / ADB / GIZ / EBRD / UzEx / Plasma AI | same | same | same | Yes | Canonical proper names/source registry labels. |

Do not claim translation quality from key coverage alone. Terminology, procurement nuance, claim strength, grammar, and UI context require human review in both target languages.

## 22. UI Surface Coverage Matrix

The literal audit inspected every TS/TSX file under `frontend/app`, `frontend/components`, and copy-producing helpers under `frontend/lib`/`frontend/types`. Direct JSX text/a11y-attribute scan counts are a prioritization signal, not a key count; conditional strings, helper returns, and API content were separately inspected.

| Priority/surface | Exact implementation files | Current copy/risks | Sprint target |
| --- | --- | --- | --- |
| P0 public/auth | `app/page.tsx`, root `layout.tsx`, Auth.js errors | English marketing/sign-in/footer/metadata; static document language | 7.2 runtime, 7.3 EN/UZ/RU |
| P0 shell/navigation | `app/dashboard/layout.tsx`, `providers.tsx` | nav, logout, command center, admin link, loading a11y | 7.3 |
| P0 onboarding | `app/dashboard/onboarding/page.tsx` | form labels, targets, validation, success; 18 direct literal/a11y sites plus dynamic copy | 7.3 |
| P0 access states | pending/access-blocked pages | status labels, explanations, refresh/logout | 7.3 |
| P0 Explorer | `app/dashboard/tenders/page.tsx`, `lib/explorer.ts`, Tender helpers | filters, tabs, result ranges, pagination, errors, manual plural; 23 direct sites | 7.3 |
| P0 refresh UX | SourceRefresh provider/menu, `lib/sourceRefreshPolicy.ts`, New badge | interpolated toasts, status/live regions, terminal reasons; source names remain canonical | 7.3 |
| P0 Tender Details | Tender detail page plus Recommendation/Engagement/PrepareBid components and project types | dense shell/enum/a11y copy, source/AI boundaries; 43+ direct shared sites | 7.3 |
| P0 My Tenders | `app/dashboard/my-tenders/page.tsx`, engagement types/components | filters, statuses/actions, empty/error, dates/money; 21 direct sites | 7.3 |
| P0 Bid Preparation | list/detail pages and PrepareBid button | form/action/export copy, dates/numbers, proposal/source/user content; 27+ direct sites | 7.3 |
| P0 settings/company | settings page, geography/services metadata helpers | Company form, statuses, API-provided English labels; 11 direct sites; language section absent | 7.3 |
| P1 Compliance shell | compliance page and types/hooks | very large shell, 18 direct sites plus many helper strings; analysis/evidence must remain unchanged | staged 7.3, finish 7.4 |
| P1 Readiness | readiness page and `lib/readiness.ts` | form/table/status/expiry copy; 19 direct sites | 7.3/7.4 |
| P1 dashboard home | `app/dashboard/page.tsx`, Recommendation summary | dashboard cards, relative time, empty states | 7.3/7.4 |
| P1 document viewer | workspace viewer and document proxy errors | toolbar/a11y/errors; document content original | 7.4 |
| P2 Admin | admin layout/overview/approvals/audit/company detail and `lib/adminOperations.ts` | English-only operational copy; 76 direct sites | shared shell only; full Admin deferred |
| Technical/do not translate | route paths/query values, source keys/URLs, enum/API codes, IDs, emails, currency codes, file extensions, logs | protocol/domain identity | Never translate values |
| Source/do not translate | source-provided Tender/project/contact/document fields | evidence authority | Never auto-translate |

No custom `not-found.tsx`, `loading.tsx`, or global error boundary exists. Existing inline loading/error/empty states are included above; future framework-level states must join `common/errors` before coverage is complete.

Forms inventory includes labels, placeholders, helper text, validation, success/error state, buttons, select options, empty states, and confirmation dialogs across onboarding, settings, Explorer, Readiness, Bid Preparation, engagement actions, admin operations, and document access. Accessibility inventory includes `aria-label`, `aria-live`, `role=status/alert`, `sr-only`, `title`, and alt text; these are first-class keys.

## 23. Export / Report Boundary

Current exports:

| Export | Exact implementation | Current language | Decision |
| --- | --- | --- | --- |
| Compliance PDF | `backend/app/core/compliance_pdf.py`, called from Tender endpoints | English template labels plus existing analysis/evidence text | Do not bind to UI locale in Sprint 7. Report labels and analysis language need a deliberate Sprint 8/later contract; preserve evidence. |
| Commercial Proposal PDF | `backend/app/api/endpoints/proposals.py:976+` | Predominantly Uzbek labels with some English parentheticals; user/source/AI values | Preserve current behavior in Sprint 7. Do not infer export language from UI locale. |
| Commercial Proposal DOCX | `backend/app/api/endpoints/proposals.py:1310+` | Mirrors the Uzbek proposal template | Same boundary. |
| Quick proposal PDF | `backend/app/core/pdf_generator.py` | Russian/English mixed static template | Preserve; treat as legacy/export-specific language, not UI preference. |
| Source document preview/download | frontend route handlers and backend file endpoints | Original file | Never translate. |

No outbound email/invite/template delivery subsystem was found. Google OAuth email identity fields and source procurement “Invitation for Bids” values are not messaging features. Do not expand Sprint 7 into email localization.

## 24. Arabic / RTL Readiness Audit

Arabic is registry metadata only: `direction: "rtl"`, `enabled: false`, `customerSelectable: false`. Sprint 7.1 does not set `dir="rtl"`, create Arabic dictionaries, expose a selector entry, or claim Arabic support.

Physical-direction scan found 323 RTL-sensitive class/token occurrences across 26 TSX files. Highest-risk files are Compliance (47), Readiness (27), Explorer (26), Bid Preparation detail (25), admin approvals (24), Tender Details/admin audit (20 each), onboarding/settings/admin company detail (15 each), and My Tenders (14). Risks include:

- sidebar `border-r` and selected-item `border-l` in dashboard/admin layouts;
- search icons positioned `left-*` with `pl-*` inputs;
- refresh menus/toasts positioned `right-*` and `sm:right-*`;
- tables using `text-left`/`text-right`, numeric alignment, sticky/split panes, and Compliance `border-r`/absolute left-right geometry;
- margin-based inline spacing (`ml-*`, `mr-*`) and status-chip layout;
- back/forward arrows and previous/next chevrons.

Sprint 8 conversion map:

- physical margin/padding/inset → logical inline equivalents (`ms/me`, `ps/pe`, `start/end` or explicit logical CSS);
- semantic text alignment → `text-start`/`text-end`; retain intentional numeric alignment after RTL QA;
- sidebar/selected accent borders → inline-start/end;
- dropdown/toast anchoring → inline-end;
- split panes, sticky columns, Explorer cards/tables, Compliance workbench, Bid Preparation pricing tables, and Admin tables → explicit RTL layouts and keyboard/scroll QA.

Directional icons requiring mirroring/reordering were found in dashboard home, My Tenders, Explorer pagination, Tender Details back links, Bid Preparation list/detail, Compliance back links, and Admin pagination/company back. Non-directional icons (refresh, status, document, building, shield, close) do not mirror. Icon treatment must be semantic per action, not a blanket CSS transform.

Root layout owns future `<html lang={locale}>`; Sprint 8 adds `dir={registry[locale].direction}` only after Arabic surfaces pass. Nested components must not independently own document direction.

## 25. Third-Party Component Readiness

| Component area | Current implementation/dependency | Localization/RTL assessment |
| --- | --- | --- |
| Select/dropdown | native `<select>`, buttons/details; custom source refresh menu | Text is controllable; physical menu anchoring needs RTL work. No external locale API. |
| Date picker | none found | No blocker; formatting still centralized. |
| Dialog/toast | inline confirmations/errors; custom refresh notices/provider | Messages are controllable; toast position is physical-right and SR-3 event-to-copy boundary must be refactored. |
| Table | native tables/cards | Labels controllable; alignment/overflow/sticky/split geometry need RTL QA. |
| Tooltip | primarily native `title`/labels | Copy must become keys; document direction inherited. |
| File upload | native file input and document controls | Labels/errors controllable; original filenames remain untouched. |
| PDF preview | internal proxy/iframe-style document surface | UI chrome can localize; document bytes/direction remain original. |
| Icons | `lucide-react` | No locale API; explicit mirror/reorder list required for directional icons. |
| Motion | `framer-motion` on public page | No localization blocker; validate longer text/reduced motion/layout. |
| Styling | Tailwind CSS 4 plus global CSS | Logical utility migration and `dir` variant strategy required in Sprint 8. |

No third-party date picker, headless UI localization layer, table framework, or toast library creates an unknown locale dependency.

## 26. Security / Tenant Isolation

Locale is untrusted presentation input. Canonicalize and allowlist it; never use an unchecked value to construct filesystem paths or arbitrary dynamic imports. The message loader maps registry codes to explicit imports.

The self-preference endpoint derives the user from `get_current_user`; it accepts no target user ID and performs no company mutation. Locale cookie is presentation-only, `Secure`, `SameSite=Lax`, path `/`, and never an authorization signal. A forged/stale/Arabic/unsupported cookie falls back safely and cannot bypass approval, disabled-account, admin, document, or tenant access checks.

Authorization and tenant-scoped data fetching execute exactly as now and never branch to broader access by locale. Localization cache keys cannot mix user-private HTML. Dynamic interpolation stays React/ICU escaped; source, user, error, and analysis values are never injected as raw HTML.

## 27. Performance / Bundle Strategy

Load one requested locale and only the namespaces required by the rendered app shell/route where practical. Do not ship complete EN+UZ+RU+AR dictionaries to every client. English fallback may be merged server-side or loaded at namespace granularity; measure before over-optimizing.

Request locale resolution is once per request/bootstrap, not one call per component. Client components consume provider context; server components consume request configuration. Domain API data stays locale-neutral and should not be refetched merely because UI locale changes. Localized derived caches/memoization include locale; raw Tender/source/engagement caches do not.

Current substantive pages are dynamic client components and no localized full-page cache exists. Any future server/static cache must include resolved locale and must not cache authenticated user HTML publicly. Use `cache: "no-store"` for private preference bootstrap; ensure a user's Uzbek output can never be served to an English user.

The localization provider should wrap the existing `SessionProvider` and dashboard `SourceRefreshProvider` without using locale as a React key that remounts the refresh provider. A locale change must retain active refresh jobs, cursor/sessionStorage, polling, newness clock, and dedupe state.

## 28. Testing Strategy

Sprint 7.1 adds six focused tests covering registry completeness, selectable locales, Arabic gating, BCP-47 normalization, deterministic precedence, namespaces, ownership naming, and content boundaries.

7.2 CI validation must recursively compare message leaf keys against English, compare ICU placeholder names/types, reject unsupported locale resources, validate registry/resource alignment, and report missing/extra keys. Development missing keys should log loudly/render an obvious diagnostic; production must fall back to English and never show `undefined` or raw keys. Dead-key analysis is advisory until extraction stabilizes.

Coverage metric excludes source/user/AI content:

```text
locale coverage % = translated, human-approved customer-runtime keys
                    / total English customer-runtime keys * 100
```

Report per locale and namespace: total keys, present keys, reviewed keys, missing keys, extra/dead candidates, placeholder mismatches, and fallback hits observed in tests. “Present” is not “approved.” Release requires 100% present/parity and native procurement review for P0 Uzbek/Russian copy.

Current frontend suites are largely copy-coupled static/source and Playwright tests; the inventory found copy/text/role/placeholder assertions in all 19 existing regression files (522 matching assertion/selector lines), with especially high coupling in Tender Details, refresh, engagement, Explorer, and project context. There are no snapshot suites. Preserve meaningful visible-copy assertions for English, but migrate navigation/action selection to roles plus stable accessible names in each locale or narrowly scoped test IDs. Do not weaken semantic/a11y verification.

Future critical locale matrix (`en`, `uz`, `ru`): auth/onboarding choice, settings switch, reload/new-tab persistence, navigation, Explorer and filters/query codes, refresh/New/toasts, Tender Details, My Tenders, Bid Preparation shell, Compliance shell boundary, date/number/currency, no source/user/AI translation, no hydration flash, mobile long labels, keyboard use, screen-reader names, and `<html lang>`. Arabic/RTL joins only in Sprint 8.

A development-only pseudo-locale is worthwhile in 7.4 for expansion, bracketed text, and missing layout capacity, but it is not a registry product locale, not persisted, and never customer-selectable.

Layout stress priority: collapsed/expanded navigation, filter rows, status/action chips, tables, pricing totals, mobile action bars, toast width, source refresh menu, and dense Compliance/Bid Preparation controls. Russian expansion and Uzbek phrase length need real viewport tests.

Sprint 7.1 verification results:

- localization foundation: 8/8 passed;
- existing frontend semantic suites: 95/95 passed across project context, Admin, My Tenders, Bid Preparation passivity, engagement workflow, Tender Details, cleanup, Explorer, SR-3 refresh, and Hunter retirement;
- TypeScript, ESLint, and optimized Next.js production build: passed (the build reports the existing Next.js middleware-to-proxy deprecation warning);
- focused backend auth/onboarding/access/schema set: 35 passed plus 17 subtests passed;
- mandatory connector regression gate: 195 passed, 1 skipped, 4 subtests passed;
- Alembic: one head, `20260901_0001_sr2_3_connector_metrics`.

## 29. Migration Decision

**SPRINT 7.2 ADDITIVE USER LOCALE MIGRATION REQUIRED**

Reason: exhaustive model/migration/schema/API/session search proves no semantically suitable durable user-level field. Add only nullable `users.ui_locale VARCHAR(8)` with a canonical-code check, expose it through current-user bootstrap, and add an authenticated self-preference PATCH as specified in section 8. Leave existing rows `NULL` to preserve the difference between “never selected” and explicit English.

No schema/data change belongs to Sprint 7.1.

## 30. Library Decision

**INTRODUCE next-intl IN 7.2**

Why this repository fit is stronger than an internal dictionary layer:

- the app uses Next.js App Router with both server and client components;
- next-intl supplies server translators and `NextIntlClientProvider` for client components;
- ICU messages cover named interpolation, plural/select grammar, and rich messages;
- its formatter APIs cover dates, numbers, currency, and relative time consistently;
- message keys can be TypeScript-augmented and resource parity checked in CI;
- requested-locale resources can be dynamically loaded without shipping all languages;
- locale routing is optional to Plasma's presentation architecture—do not adopt locale-prefixed routes.

Official next-intl documentation states that it supports App Router/server components, client providers, ICU message syntax, formatting, and typed messages: <https://next-intl.dev/> and <https://learn.next-intl.dev/chapters/03-translations/02-server-client-components>.

Do not install it until 7.2, when request resolution, persistence, message loading, and hydration behavior can land together. Adding only the dependency in 7.1 would have no runtime value.

## 31. Sprint 7.2 Contract

Atomic infrastructure/persistence scope:

1. Add the single nullable `users.ui_locale` migration/model/check and focused migration tests.
2. Add nullable locale to `/users/me` bootstrap and an authenticated-own-user preferences PATCH; validate `en|uz|ru`, leave `ar` gated.
3. Install/configure next-intl without locale-prefixed routing.
4. Implement server request resolution in the locked precedence, a secure presentation cookie, root `<html lang>`, and identical server/client provider state.
5. Add domain-grouped English skeleton plus Uzbek/Russian resources sufficient for infrastructure tests, English fallback, typed message schema, and dynamic current-locale loading.
6. Add shared formatter APIs with explicit timezone/currency separation.
7. Add CI validation for keys/placeholders/registry/resources and missing-key telemetry.
8. Prove auth/access/tenant isolation, SSR hydration, Arabic rejection, and no domain side effects.

Do not perform the broad customer-copy conversion or add selectors in 7.2 unless the task is explicitly expanded.

## 32. Sprint 7.3 Contract

Customer rollout scope:

1. Add the registry-driven onboarding selector at the first onboarding view and a separate account preference section in settings.
2. Implement persist-first instant switch, error/retry behavior, cookie synchronization, document `lang`, and same-route refresh without logout.
3. Translate/human-review P0 EN/UZ/RU resources: public/auth, access states, shell/navigation, onboarding, settings, Explorer, refresh/New/toasts, Tender Details shell, My Tenders, Bid Preparation shell/actions.
4. Replace manual enum labels, plural/concatenated strings, and scattered P0 formatters with message/formatter APIs while preserving API/query codes.
5. Preserve source, user, institution, AI analysis, evidence, export, scoring, engagement, proposal, and refresh semantics.
6. Keep Arabic absent and dedicated Admin English-only except shared shell.

## 33. Sprint 7.4 Contract

Coverage/quality completion scope:

1. Finish P1 Compliance shell, Readiness, dashboard home, document viewer, framework empty/loading/error metadata, and any missed customer copy.
2. Reach 100% EN/UZ/RU customer-runtime key/placeholder parity and native-reviewed P0/P1 translation quality.
3. Consolidate remaining date/number/currency/relative-time sites and verify timezone/domain invariants.
4. Run the three-locale browser matrix across reload/new tab, mobile expansion, keyboard/screen reader, accessibility names, source/AI boundaries, and hydration flash.
5. Add development pseudo-locale/layout stress checks and dead-key reporting.
6. Confirm all existing regression suites, connector gate, and Alembic topology remain green.

Full dedicated Admin localization and report/email language platforms remain separately scoped.

## 34. Sprint 8 Boundary

Sprint 8 exclusively owns independent Compliance/analysis/report-language product decisions and Arabic first-class release. It may add `analysis_language` to the appropriate immutable analysis/version contract, explicit rerun semantics, report-language decisions, Arabic dictionaries, runtime `dir="rtl"`, logical CSS conversion, mirrored directional navigation, third-party/table/split-pane RTL fixes, typography/font validation, and full Arabic browser/a11y acceptance.

Sprint 7.1 introduces no `analysis_language`, `report_language` mutation, AnalysisVersion language control, LLM prompt language setting, Arabic selector, Arabic customer dictionary, RTL layout conversion, or `dir="rtl"` behavior.

## 35. Remaining Risks

- The user preference does not exist until 7.2; current runtime stays English by design.
- Authenticated SSR preference lookup must be implemented without creating duplicate page-level requests or weakening fail-closed access behavior.
- A nullable field is important; an automatic English backfill would erase the distinction between default and explicit preference.
- Backend errors lack stable codes and some exception/source terminal text reaches users. Full error-envelope modernization may outgrow Sprint 7 and should be staged by customer risk.
- API-delivered geography/service labels currently mix canonical values and English display labels; 7.3 must localize presentation without translating submitted values.
- Copy-heavy tests will need careful locale-aware selectors while retaining exact semantic/claim assertions.
- Compliance and Bid Preparation are dense and claim-sensitive; native terminology review is mandatory.
- Export templates are already English/Uzbek/Russian mixed and must not accidentally follow UI locale.
- The RTL scan is static; Sprint 8 requires actual Arabic content, font, browser, mobile, table, split-pane, and assistive-technology testing.
- No global not-found/loading/error surfaces exist, so framework failure coverage must be explicitly added or documented in 7.4.
- Library compatibility must be pinned and proven against the exact Next.js 16 version during 7.2 implementation.
- Dedicated Admin remains English-only and must be visibly tracked rather than counted as localized coverage.

Recommended next task: execute Sprint 7.2 exactly as section 31, beginning with the nullable user preference migration/API and request-scoped resolver tests before installing/wiring the runtime.
