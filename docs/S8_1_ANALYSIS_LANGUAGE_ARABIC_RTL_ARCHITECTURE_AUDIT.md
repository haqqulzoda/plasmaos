# Sprint 8.1 — Independent Analysis-Language and Arabic/RTL Architecture Audit

## 1. Executive Summary

Sprint 8.1 is an audit and architecture contract only. No customer-visible analysis-language control, Arabic catalog, RTL behavior, multilingual generation, migration, deployment, or production mutation is introduced.

The existing architecture can support independent interface and analysis languages without replacing its ownership model. The durable unit is `AnalysisVersion`, while `TenderAnalysis` is the logical per-user/per-company/per-tender aggregate. Sprint 8.2 must persist the actual requested language on each new version, add it to cache identity, and persist a nullable per-user default. Sprint 8.3 must separately activate Arabic UI catalogs and root direction. Existing versions must remain language-unknown (`NULL`) rather than being guessed.

The current static RTL inventory contains 78 actionable physical-direction utility occurrences in 22 TSX files: 57 customer-facing and 21 admin-only. It also contains 21 directional arrow/chevron instances in 9 files: 16 customer-facing and 5 admin-only. A broad continuity scan finds 318 prefix matches in 28 files, but includes false positives and is not the implementation count.

## 2. Current Analysis Architecture

`POST /api/v1/tenders/{tender_id}/analyze` in `backend/app/api/endpoints/tenders.py` is the only runtime Compliance generation entry point. It:

1. authorizes approved-pilot access and ownership;
2. loads tender text, the selected company profile, credentials, taxonomy, and company vault;
3. builds a deterministic content hash;
4. returns the latest matching version unless `force=true`;
5. runs requirement and strategy extraction concurrently;
6. verifies quotations, classifies scope, and evaluates compliance;
7. resolves the logical aggregate;
8. appends an immutable version; and
9. updates the legacy `TenderAnalysis.analysis_json` compatibility mirror.

Generation is synchronous in the API process. Celery performs source-refresh work, not Compliance-version generation. Recommendation and Proposal generation are separate product domains and read Compliance output without owning its language.

## 3. AnalysisVersion Model

`backend/app/models/audit.py` defines the two-level model:

- `TenderAnalysis` owns the logical aggregate keyed in practice by `(user_id, company_profile_id, tender_id)`, plus legacy compatibility data.
- `AnalysisVersion` owns an immutable completed result beneath that aggregate.
- `AnalysisVersionDocument` owns immutable source-document snapshots for a version.

An `AnalysisVersion` currently records its aggregate ID, monotonically increasing `version_number`, predecessor, origin, status, schema and pipeline versions, model/prompt provenance, tender/company/result/evidence JSON snapshots, document snapshots, hashes, snapshot completeness, requester, and timestamps. It does not record analysis language.

Uniqueness on `(analysis_id, version_number)` and on `supersedes_version_id` preserves a linear history. Application validation protects snapshot and hash fields from mutation; Sprint 8.2 must add `analysis_language` to that protection and to new-version integrity hashing. Database checks constrain origin, status, and snapshot completeness; there is no database trigger making every column immutable.

## 4. Generation Entry Points

| Path | Creates Compliance version? | Language today | Result |
|---|---:|---|---|
| Customer `POST /tenders/{id}/analyze` | Yes | Not explicit | Sole production runtime path |
| Operator using the same endpoint | Only with an owned/authorized company profile | Not explicit | No separate privileged generator |
| Celery/source-refresh workers | No | N/A | Refresh sources only |
| Recommendation endpoints | No | N/A | Separate domain |
| Proposal/Bid Preparation endpoints | No Compliance version | Separate prompts/content | Separate domain |
| S2.2 Alembic backfill | Yes, one legacy v1 per prior aggregate | Unknown | Snapshot-only; no external/model call |
| Tests and maintenance scripts | May call append service directly | Not explicit | Non-customer scaffolding |

No automatic, scheduled, admin-wide, or hidden second Compliance generation route was found.

## 5. Current Language Behavior

Analysis language is currently implicit and not stored. The requirement-extractor prompt is English, accepts English/Uzbek/Russian/mixed tender text, requires verbatim evidence, and permits a concise English headline. The model can therefore return mixed/model-dependent narrative. Strategy extraction is also instructed from an English prompt while preserving original language when quoting.

The deterministic compliance layer emits several English explanation strings. No analysis code reads `User.ui_locale`, the locale cookie, `Accept-Language`, or `next-intl`. Current output is therefore not contractually tied to interface language, even when it happens to match it.

## 6. Source vs Generated Field Matrix

| Field family | Owner | Future language treatment |
|---|---|---|
| `source_filename`, source page, clause/reference | Source/parser | Preserve exactly; never translate |
| `exact_quote`, `raw_text_snippet`, tender source text | Source/parser | Preserve exactly; render with content-aware direction |
| Tender title/description/buyer/source URL | Source | Preserve source value |
| Document bytes, storage references, content hashes | Source/system | Never rewrite |
| Requirement `headline` | Model-generated normalization | Generate in selected analysis language |
| `validation_reason`, `eligibility_reason` | Backend deterministic narrative | Localize from an analysis-language message catalog |
| Per-match `reason`, `vault_missing_reason` | Backend deterministic narrative | Localize from the same catalog |
| Top-level `status_message`, customer-facing warning/error explanation | Backend/system narrative | Localize in selected analysis language |
| Category, scope, verdict, status, match method, origin | Canonical enum/system | Keep canonical machine values |
| IDs, versions, hashes, counts, booleans, confidence | System | Language-neutral |
| Credential names and profile/vault content | User/company | Preserve entered value |
| Override justification | User | Preserve entered value |
| Strategy intelligence | Separate model companion | Outside the Sprint 8.2 Compliance-language guarantee |

## 7. Evidence Immutability

Evidence is evidence because it retains the source form. `exact_quote`, snippets, filenames, page numbers, URLs, document bytes, and source metadata must never be translated or rewritten by an analysis-language change. Existing quote validation already compares normalized model output to parser-marked source content; translating a quote would break both evidentiary meaning and verification.

Language-localized explanation may sit next to evidence, but must remain a separate field. Evidence must retain its original direction and use `dir="auto"`/bidi isolation in the browser.

## 8. Requirement Ownership

Requirement records are mixed-ownership objects:

- source-owned: citation, exact quotation, raw snippet, and source location;
- model-owned: normalized headline;
- deterministic system-owned: category/scope/verdict/status and explanatory messages;
- user/company-owned: matched credential/vault values;
- provenance-owned: model, prompt, pipeline, schema, and hashes.

Sprint 8.2 may change only the generated explanation layer and its explicit provenance. It must not translate source or user/company material, and it must not localize canonical schema keys/enums.

## 9. Canonical Analysis Languages

The initial bounded analysis-language registry is:

| Code | Native label | Prompt display name | Analysis direction |
|---|---|---|---|
| `en` | English | English | LTR |
| `uz` | O‘zbekcha | Uzbek | LTR |
| `ru` | Русский | Russian | LTR |
| `ar` | العربية | Arabic | RTL |

Codes are stable persisted values, not free text, BCP-47 expansion, or aliases. Native labels appear in selectors. Trusted prompt names come only from the registry and never from user input. Adding a code later requires a reviewed registry, database constraint, prompt/test, UI, export, and quality-gate change.

## 10. UI / Analysis Independence

`ui_locale` controls application chrome, navigation, formatters, and root direction. `analysis_language` controls a specific analysis version's generated narrative. Neither derives the other after request submission.

Valid combinations include Arabic UI with English analysis and English UI with Arabic analysis. Changing UI locale must not relabel, regenerate, or mutate an existing version. Changing an analysis default must not change UI locale. The version's stored language, not the current browser locale, controls analysis-content direction and historical export defaults.

## 11. Default Analysis Language Authority

The default belongs to the authenticated `User`, not CompanyProfile, Tender, browser cookie, organization, or an analysis aggregate. Sprint 8.2 should add nullable `users.default_analysis_language`.

Resolution for an analysis request is performed once on the server:

1. explicit request value;
2. authenticated user's stored default;
3. `en` compatibility fallback.

The UI may preselect the current UI locale when no stored default exists and it is supported, but it must send that choice explicitly. Non-UI clients that omit the field resolve to the stored default or English. A stored default is preference, not provenance; only the resolved value stored on `AnalysisVersion` is authoritative for that result.

## 12. Per-Analysis Override

The Compliance execution control gets a per-run language selector adjacent to Run/Re-analyze. Selection is bounded to the canonical registry and is submitted with that operation. It does not persist the user's default and does not mutate UI locale.

Settings gets a distinct “Default analysis language” control. It must not be conflated with the existing “Interface language” selector. Saving either preference is an explicit action with independent validation and failure feedback.

## 13. Versioning Semantics

The aggregate identity remains `(user_id, company_profile_id, tender_id)`; language does not create a second logical analysis aggregate. Each completed run is an immutable version in that aggregate's linear history.

- Same inputs and same language with `force=false`: reuse the matching latest version.
- Same inputs and different language: append a distinct version.
- Same inputs and same language with `force=true`: append a distinct version.
- Changed source/company inputs: append a distinct version regardless of language.
- Changing a default alone: creates nothing and mutates no version.

Version lists and detail responses show the recorded language. Comparison across different recorded languages is allowed but must display an explicit language difference warning.

## 14. Cache / Idempotency

The current input hash covers extractor schema, tender text, credential/taxonomy identifiers, vault payload, and source coverage, but not language. Sprint 8.2 must add the resolved analysis-language code to input/cache identity before cache lookup and append. It must use a named/versioned hash envelope so future verification is unambiguous.

The full immutable version hash must also include the actual language for new versions. Legacy version hashes were computed without this field. Verification must remain schema/pipeline/hash-version aware and must not recompute a historical hash as if `NULL` language had originally participated.

## 15. Concurrency

`analysis_aggregates.py` uses a PostgreSQL transaction advisory lock to resolve one logical aggregate. `append_analysis_version()` locks the parent row and allocates the next number. Current LLM calls occur before the aggregate lock, so two simultaneous non-forced requests can both incur model cost even though the second matching request is collapsed before append.

Sprint 8.2 behavior:

- concurrent same-input/same-language non-forced requests may both execute but only one matching version survives the locked recheck;
- concurrent different-language requests never collapse because their input hashes differ;
- forced concurrent requests append distinct sequential versions;
- authorization remains user/profile/aggregate scoped, never language scoped.

## 16. Historical Compatibility

All existing versions have unknown analysis language. The migration must leave them `NULL`; no text detection or inference from UI locale, source language, user preference, prompt, or timestamp is acceptable.

Legacy reads, version history, detail, comparison, and export must accept `NULL` and display “Not recorded” (localized as UI chrome where appropriate). A legacy version must never be presented as English merely because English is the runtime compatibility fallback for a new omitted request.

## 17. Worker / Retry Contract

There is currently no Compliance Celery job payload: analysis runs synchronously in the API process. The selected language must be resolved once at request start and passed unchanged through requirement extraction and every Tenacity retry. A retry must not re-read a possibly changed default or current UI locale.

If Compliance later becomes asynchronous, the durable job must store the canonical language (or reference a durable request/version-intent record that does) before enqueueing. Workers must not consult cookies, headers, or the user's current preference. A completed immutable `AnalysisVersion` must not be overloaded as an in-progress job. Current process-crash durability remains a known limitation.

## 18. LLM Prompt Contract

The requirement extractor must receive a trusted registry value and add a clear instruction equivalent to: generate analysis explanation fields in the selected language; preserve source filenames, exact quotations, and source text verbatim; keep canonical keys and enums unchanged.

The language code/name cannot come from arbitrary prompt text. Retries use the same resolved enum. Prompt template version/hash and pipeline version must advance when the instruction changes. Strategy extraction remains outside the Compliance-language contract unless separately product-scoped.

## 19. Structured Schema Contract

Pydantic/LLM response keys remain canonical English implementation identifiers. Category values remain `DQ`, `NICE_TO_HAVE`, and `COMPLIANT`; scope, verdict, validation, origin, and status enums remain stable. Only designated free-text generated fields change language.

Validation remains language-neutral: schema shape, enum membership, exact-quote presence, source-page/filename matching, and deterministic compliance rules do not depend on translated labels. A selected language is a bounded enum. Failure to generate the requested language must not silently produce a successful differently labeled version.

## 20. Export / Report Language Boundary

Compliance PDF export already reads immutable version snapshots. Sprint 8.2 must expose version language in export metadata and default report chrome to the selected historical version's recorded language. Analysis narrative follows the version language; source evidence and user/company content remain original.

For legacy `NULL`, report chrome uses an explicitly documented compatibility locale while metadata states “Not recorded”; it must not mutate the version or claim its analysis was English. The current browser UI locale must not silently alter a historical export. Any future report-chrome override is a separate request option recorded in export provenance.

Current ReportLab/DejaVu output has no proven Arabic shaping/bidi contract, so Arabic PDF quality is gated for S8.4. Recommendation and Proposal exports remain separate domains.

## 21. Settings UX Contract

Settings presents separate labeled controls for Interface language and Default analysis language. Each explains its scope. The analysis selector uses native language names from the analysis registry and is available independently of current UI locale.

`PATCH /users/me/preferences` should be extended rather than creating a parallel endpoint. Both fields become optional, at least one is required, omitted fields remain unchanged, unknown codes are rejected, and the response includes both values. Existing `{ "ui_locale": ... }` clients remain valid. Saving the analysis default triggers no analysis, model call, locale switch, auth-version bump, or domain-side effect.

## 22. Compliance Execution UX Contract

The per-analysis selector sits next to Run/Re-analyze and clearly describes the generated narrative scope. The resolved language is captured when the request begins. Locale or default changes during execution do not affect that request.

After completion, the result header shows language and version. History rows show language, including “Not recorded” for legacy data. Failure to generate in the requested language is explicit and does not silently fall back; the previously displayed matching result may remain visible but must not be mislabeled as the requested new result.

## 23. Analysis Registry

Sprint 8.2 should introduce a dedicated semantic registry, separate from `frontend/i18n/locales.ts` customer selectability. It is shared conceptually across backend validation, frontend selectors, prompt names, direction helpers, and tests. Backend remains authoritative for accepted request/persistence codes.

The registry contains only code, native label, trusted prompt name, and content direction. UI-catalog readiness is a separate property. This prevents enabling Arabic UI merely because Arabic analysis is available, and prevents disabling Arabic analysis merely because Arabic UI is still gated.

## 24. Migration Decision

Sprint 8.2 requires one additive migration after `20260902_0001_s7_2_user_ui_locale`:

- `analysis_versions.analysis_language VARCHAR(8) NULL` with a named check allowing only `NULL`, `en`, `uz`, `ru`, `ar`;
- `users.default_analysis_language VARCHAR(8) NULL` with the same bounded-value check.

There is no server default, backfill, guessed language, or new index. No language column belongs on Tender, CompanyProfile, TenderAnalysis, SourceRefreshJob, Recommendation, or Proposal. Downgrade removes only the two checks and columns. Sprint 8.1 intentionally creates no migration.

## 25. Arabic Current State

Arabic is registered but deliberately disabled for customer UI:

- backend `UiLocale` and its database check know `ar`;
- `CUSTOMER_SELECTABLE_UI_LOCALES` excludes `ar`;
- frontend `ProductLocale` knows `ar`, while `CustomerSelectableLocale` excludes it;
- the Arabic registry entry is disabled/non-selectable and declares RTL;
- request resolution, middleware, preference validation, and `LanguageSelector` accept only customer-selectable locales;
- no `frontend/messages/ar` catalog or Arabic message loader exists;
- root layout sets dynamic `lang` but no `dir`.

This is a correct static gate. Arabic is neither advertised nor silently resolved today.

## 26. Arabic Activation Gate

Sprint 8.3 may enable Arabic UI only when all 15 message namespaces exist with the complete key contract, reviewed terminology, backend and frontend selectability change together, `directionForLocale` is installed at the root, customer surfaces pass RTL inspection, and browser/accessibility regressions pass.

Activation requires an atomic change. Merely adding a selector label, accepting `ui_locale=ar`, or adding `dir=rtl` alone is a release blocker. English, Uzbek, and Russian behavior must remain unchanged.

## 27. Root Direction Contract

The root locale runtime is the sole UI direction authority. `frontend/app/layout.tsx` should render both dynamic `lang` and `dir` from the same server-resolved locale:

- `ar` → `rtl`;
- `en`, `uz`, `ru`, and pseudo-locale `en-XA` → `ltr`.

Pages must not independently mutate `document.dir`. Server resolution must avoid hydration-direction flashes. Analysis/source/user content can override direction only on the smallest content container under the mixed-content rules below.

## 28. RTL CSS Risk Map

The precise TSX audit found 78 physical-direction utilities across 22 files:

| Category | Occurrences | Required disposition |
|---|---:|---|
| Physical margin/padding | 16 | Convert semantic spacing to `ms`/`me`/`ps`/`pe`; retain truly geometric cases with comment/test |
| `left`/`right` inset | 13 | Convert semantic anchoring to inline-start/end; keep centered/geometric positioning |
| Physical left/right border | 11 | Convert separators/selection bars to inline border utilities |
| Explicit `text-left`/`text-right` | 38 | Convert narrative/column semantics to start/end; keep numeric/LTR islands explicit |
| Physical rounded-side | 0 | No current migration item |
| `space-x-*` | 0 | No current migration item |
| `translate-x-*` | 0 | No current migration item |

Of the 78, 57 occur in customer surfaces and 21 in deferred admin surfaces. Highest customer concentrations are Compliance (13) and Bid Preparation detail (10). The broad historical prefix scan yields 318 occurrences in 28 files because it also matches non-directional classes such as `rounded-lg` and color borders; retain 318 only as a continuity sentinel, not a work estimate.

## 29. Bidi / Mixed Content Contract

Direction is layered:

- application chrome inherits root UI direction;
- generated analysis narrative uses the stored analysis-language direction;
- legacy unknown-language narrative uses `dir="auto"`;
- source evidence and user-entered text use `dir="auto"` plus isolation (`bdi` or CSS `unicode-bidi: isolate`) where embedded;
- email, URL, phone, hashes, IDs, codes, and filenames use explicit LTR isolated spans while remaining aligned to layout semantics;
- canonical enum display labels are UI chrome and follow UI locale/direction.

Do not apply `dir=rtl` to an entire document merely because UI or analysis is Arabic. Punctuation and numeric runs require browser QA with real mixed Arabic/Latin fixtures.

## 30. Directional Icon Matrix

The static icon audit found 21 ArrowLeft/ArrowRight/ChevronLeft/ChevronRight uses in 10 files: 16 customer and 5 admin.

| Icon meaning | RTL behavior |
|---|---|
| Back/forward navigation | Mirror or choose the semantic opposite glyph |
| Pagination previous/next | Swap/mirror while preserving accessible semantic labels |
| Breadcrumb/progress flow arrow | Mirror when it denotes inline progression |
| Search, refresh, download, upload, settings, document, plus, close, check, warning, shield/status | Do not mirror |
| Arrow inside source/document content | Preserve source direction |

Customer occurrences are in Bid Preparation list/detail, My Tenders, dashboard home, Explorer, Tender Details, and Compliance. Admin occurrences are in approvals, audit, and company detail. Use a shared semantic icon wrapper/RTL utility rather than scattered locale conditionals.

## 31. Surface-by-Surface RTL Matrix

| Surface | Current risk | Sprint 8.3 contract |
|---|---|---|
| Navigation/layout | Physical side border, sidebar order, arrows | Logical borders/spacing; validate collapsed/mobile order and focus traversal |
| Tender Explorer | Search/filter geometry, tabs, pagination chevrons | Logical spacing/alignment; semantic prev/next; horizontal-scroll QA |
| Tender Details | Back arrows, sticky tabs, metadata/source values | Mirror navigation only; isolate source values; preserve semantic tab order |
| My Tenders | Search/action alignment and forward arrows | Logical alignment; semantic arrows; card/table responsive QA |
| Bid Preparation | Back/forward arrows, text areas, numeric/table alignment, preview | Logical layout; content-aware editors; LTR identifiers; source preview unchanged |
| Compliance | Split-panel border/insets, back arrow, generated vs evidence direction | Logical split layout; analysis-language container; evidence auto-direction; mobile stacking QA |
| Readiness | Tables, dates, inputs/selects | Start/end semantics; numeric islands; native-control browser QA |
| Settings | Input padding/alignment and two language controls | Logical form layout; clearly separate UI/default-analysis selectors |
| Onboarding | Forms, credential/company free text | `dir=auto` for content fields; LTR semantic fields; step-flow QA |
| Refresh activity | End-anchored menu/toasts and status rows | Logical overlay anchoring; bidi-safe source/error text; active refresh continuity |
| Document viewer | Chrome controls versus document content | Chrome follows UI; source document/PDF is never mirrored |
| Admin | 21 physical tokens and 5 directional icons | Explicitly inventoried; activate only in admin RTL scope or track as deferred debt |

## 32. Third-Party RTL Readiness

The relevant frontend stack is Next.js/React, `next-intl`, Tailwind CSS 4, Lucide React, Framer Motion, native inputs/selects/tables, custom menus/dialogs/toasts, and an internal document viewer. No third-party date picker, table system, dialog/toast framework, or portal implementation was found; no `createPortal` use was found.

Native bidi support is helpful but not sufficient. Tailwind logical-property availability and compiled CSS must be verified. Lucide directional glyphs need semantic handling. Framer Motion animations must use semantic inline direction where motion implies navigation. Native controls need Chrome/Firefox/Safari checks. Future portals must receive `dir` on their portal root because DOM inheritance may be lost.

## 33. Arabic Catalog Plan

Add `frontend/messages/ar` with the same 15 namespaces and complete scalar-key parity as the approved English contract (currently 850 keys per existing locale). Update the explicit message loader only after all files are present. No fallback-based partial launch is allowed.

Translation uses the existing namespaces and placeholders, preserves ICU syntax and product/source names, and receives reviewer sign-off. Pseudo-locale remains a structural QA tool and stays LTR. Arabic catalogs localize UI chrome only; they do not translate stored analysis, source evidence, user-entered text, or immutable history.

## 34. Arabic Quality Gate

Required gates before Arabic UI activation:

1. exact namespace/key/placeholder parity and no English fallback;
2. reviewed glossary and native-language review;
3. root `lang=ar dir=rtl` SSR/hydration proof;
4. desktop/mobile visual checks across every Sprint 7 customer surface;
5. keyboard order, focus visibility, labels, and screen-reader semantics;
6. mixed Arabic/Latin evidence, names, URLs, phones, hashes, tables, dialogs, and toasts;
7. number/currency/date/relative-time behavior in supported runtimes;
8. English/Uzbek/Russian and active-refresh regression;
9. Arabic analysis combinations and PDF/export checks in Sprint 8.4.

## 35. UI / Analysis Language Matrix

Every combination is legal; examples apply equally across the 4×4 matrix:

| UI | Analysis | Chrome | Generated analysis | Evidence |
|---|---|---|---|---|
| English | English | English | English | Original |
| English | Arabic | English | Arabic | Original |
| Arabic | English | Arabic | English | Original |
| Arabic | Arabic | Arabic | Arabic | Original |
| Uzbek | Russian | Uzbek | Russian | Original |
| Russian | Uzbek | Russian | Uzbek | Original |

Tests must cover all sixteen `(ui_locale, analysis_language)` combinations at the contract level. UI switching never changes the stored analysis-language cell.

## 36. Direction Matrix

| Content | Direction authority | `dir` rule |
|---|---|---|
| UI chrome | Resolved `ui_locale` | Arabic RTL; other supported/pseudo locales LTR |
| Generated analysis narrative | `AnalysisVersion.analysis_language` | Arabic RTL; en/uz/ru LTR |
| Legacy generated narrative | Unknown | `auto` |
| Evidence/source/user text | Content itself | `auto` with isolation |
| Email/URL/phone/hash/ID/code | Semantic type | Explicit isolated LTR |
| PDF/document body | Document/version export contract | Never inherited from browser root |

Thus Arabic UI + English analysis is RTL chrome with an LTR analysis region; English UI + Arabic analysis is LTR chrome with an RTL analysis region.

## 37. Security / Authorization

Analysis language adds no authorization capability. The existing approved-pilot, tender, user, and company-profile ownership checks remain mandatory before cache lookup or generation. Only canonical enum codes are accepted, preventing prompt injection through language names.

The default-preference endpoint updates the authenticated user's row only. Operators do not obtain cross-user preference mutation. Logs may include language code, analysis/version IDs, pipeline outcome, and duration but not tender text, quotes, document content, company secrets, or user-entered evidence. Language changes do not bump `auth_version`.

## 38. Testing Strategy

Sprint 8.1 static tests/audits prove current boundaries: no UI locale input in analysis generation, explicit verbatim-evidence prompt rules, Arabic remains non-selectable with no catalog, root has no active RTL behavior, and all physical-direction/icon occurrences are inventoried.

Sprint 8.2 adds:

- migration fresh/upgrade/downgrade and invalid-code checks;
- legacy `NULL` and old-version-hash verification;
- API precedence tests for explicit/default/English fallback;
- same-input same/different-language cache and concurrency tests;
- immutable-version/read/list/export language tests;
- deterministic 4-language prompt/schema fixtures with language sentinels;
- evidence, user content, keys/enums, and identifiers byte-for-byte boundary tests;
- retry stability and no-silent-fallback tests;
- settings preference auth/backward-compatibility tests.

Sprint 8.3 adds catalog parity, root SSR direction, logical-style/static icon guards, 4×4 direction/content fixtures, surface browser tests, mixed-bidi fixtures, and EN/UZ/RU regression. Sprint 8.4 adds approved small live-model QA, Arabic export/font/shaping QA, browser/mobile/accessibility coverage, and full cross-language continuity. Live tests must be opt-in, non-production, bounded, and secret-safe.

Repository verification for this audit records frontend typecheck/lint/build and localization tests; focused backend localization/Compliance/version tests; Sprint 7 regression suites; the mandatory connector regression gate; and Alembic head/check. Exact outcomes are reported in the Sprint handoff rather than frozen into this architecture contract.

## 39. Sprint 8.2 Contract

Sprint 8.2 implements analysis language only:

- add the two nullable checked columns from section 24;
- add a dedicated analysis registry and nullable read schemas;
- accept optional `analysis_language` on create/re-run and resolve explicit → stored default → English once;
- store actual language on every new version and include it in immutable/hash provenance;
- add language to input/cache identity without changing aggregate identity;
- preserve language through synchronous retries and any future durable job payload;
- advance prompt/pipeline provenance and generate only designated narrative fields;
- keep evidence, user content, keys/enums, and strategy intelligence unchanged;
- expose language on analyze/latest/history/detail/export APIs;
- show language in version history/comparison and use it for analysis-content direction metadata;
- extend own-user preferences and add separate Settings/default and Compliance/per-run selectors;
- keep legacy versions `NULL`/“Not recorded” and verify legacy hashes with their original hash contract;
- fail explicitly rather than silently falling back to another generated language.

S8.2 does not enable Arabic UI or global RTL.

## 40. Sprint 8.3 Contract

Sprint 8.3 implements Arabic UI and RTL only after its atomic gate:

- add reviewed complete Arabic catalogs and loader;
- make `ui_locale=ar` selectable in backend and frontend together using the existing UI-locale schema;
- set server-rendered root `lang` and `dir` from one locale authority;
- replace semantic physical CSS with logical properties and classify exceptions;
- introduce semantic directional-icon handling;
- isolate source/user/identifier/mixed content and use version language for analysis containers;
- validate navigation, Explorer, Tender Details, My Tenders, Bid Preparation, Compliance, Readiness, Settings, onboarding, refresh UX, tables, forms, overlays, toasts, and document viewer;
- add Arabic Intl mapping and lock supported-runtime number/currency/date behavior;
- preserve active refresh, history, source names, and all EN/UZ/RU behavior.

S8.3 does not rewrite historical analysis content or document bodies.

## 41. Sprint 8.4 Contract

Sprint 8.4 is final integrated QA, not architectural invention. It validates all UI/analysis language pairs; LTR/RTL nesting; legacy unknown language; create/re-run/cache/concurrency/history persistence; source/evidence immutability; export and Arabic font/shaping; desktop/mobile/responsive behavior; keyboard/screen-reader/accessibility behavior; mixed-content punctuation, numbers, URLs, phones, IDs and tables; active refresh continuity; Compliance version continuity; EN/UZ/RU regression; and bounded live-model quality for the four analysis languages.

Release requires no fallback mislabeled as success, no untranslated Arabic UI gaps, no evidence mutation, no direction flash, and documented residual provider/browser limitations.

## 42. Remaining Risks

- Gemini language quality and exact requested-language adherence are unproven for the four-language contract until deterministic and approved live QA exist.
- ReportLab/DejaVu Arabic shaping, bidi ordering, line breaking, and mixed-script export require explicit validation and may need additional shaping/font work.
- Current synchronous generation cannot durably resume after API-process loss, and its pre-lock model calls can duplicate cost.
- Existing application-level immutability is narrower than full database-enforced row immutability; Sprint 8.2 must protect the new field and retain integrity tests.
- Legacy hashes require version-aware verification when the new language field enters the hash envelope.
- Arabic terminology and official institutional-name policy require native review; source/canonical names must remain unchanged until an approved official name exists.
- Browser-native Arabic digits/number formatting can vary by runtime; do not hand-convert stored values, and lock the supported-runtime expectation in QA.
- Admin RTL contains known physical styles/icons and must either be included in activation scope or explicitly tracked as deferred, non-customer debt.
- Future portals or third-party widgets can lose root direction inheritance and require local direction propagation.
- A complete RTL migration can regress LTR if physical-to-logical changes are not covered by EN/UZ/RU visual and interaction tests.
