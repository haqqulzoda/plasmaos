# Sprint 8.2 — Independent Analysis Language

## 1. Previous Analysis-Language State

Compliance generation had one production entry point, but its language was implicit, was not part of cache identity, and was absent from immutable version metadata. UI locale persistence existed independently.

## 2. Analysis Language Registry

`en`, `uz`, `ru`, and `ar` are canonical in a dedicated backend registry with native label, trusted prompt name, generation capability, customer selectability, and direction. English, Uzbek, and Russian are customer-selectable. Arabic generation exists technically but remains gated.

## 3. User Default Preference

`users.default_analysis_language` is nullable. `NULL` means no saved choice; it is not inferred from `ui_locale`. The Settings control writes only this preference.

## 4. AnalysisVersion Language

`analysis_versions.analysis_language` is nullable for history and mandatory by the Sprint 8.2 runtime append path. It is included in the ORM immutability guard.

## 5. Migration

Revision `20260904_0001_s8_2_analysis_language`, parent `20260902_0001_s7_2_user_ui_locale`, adds exactly the two nullable columns and their named check constraints. It creates no defaults, indexes, data updates, or unrelated schema.

## 6. Backward Compatibility

Existing analyze clients may omit the query field. Historical rows and users remain `NULL`. No source, company, tender, or historical hash is rewritten.

## 7. Resolution Precedence

At request start the runtime captures explicit request, otherwise the authenticated user's saved default, otherwise English. UI locale, cookies, `Accept-Language`, and document language are not consulted.

## 8. Per-Run Override

Compliance exposes a native select for EN/UZ/RU beside the primary run control. Its explicit query value wins for that run and never saves a user default.

## 9. Hash / Cache Identity

Resolved language is appended to the analysis input-hash envelope. Cache reuse and both pre-lock and post-lock checks require the stored version language to match. Source/document hashes remain unchanged.

## 10. Concurrency

The existing parent row lock and monotonic N+1 allocation remain authoritative. Same-language identical requests can reuse; different-language requests cannot collapse and append to the same ordered lineage.

## 11. Version Immutability

Language has no mutation endpoint and joins result, evidence, provenance, source, company, and hash fields in the persisted-history mutation validator.

## 12. Historical NULL Semantics

`NULL` means “Not recorded,” never English. A new explicit English request cannot reuse or relabel a legacy `NULL` version. Legacy version hash verification omits the absent language key.

## 13. Analyze API

`POST /tenders/{tender_id}/analyze` accepts optional bounded `analysis_language`. Invalid, gated, locale-shaped, empty, and free-form values receive a safe 422 before model execution.

## 14. Read APIs

Analyze, latest, aggregate/Tender Details, history, detail metadata, and safe provenance expose the stored nullable language. Analyze/latest additionally expose content direction; cached reads return the version value rather than recomputing a current default.

## 15. Prompt Language

The extractor receives only registry-owned prompt names: English, Uzbek (Latin script), Russian, or Arabic. The selected language is threaded unchanged through chunking and retry calls.

## 16. Structured Schema

JSON field names, Pydantic shapes, requirement categories, scope values, evidence statuses, verdicts, and matching enums remain canonical and language-neutral.

## 17. Generated Field Scope

Model-generated headlines and backend-owned validation, eligibility, match-reason, status, warning, and failure narratives follow the captured language. Identifiers and canonical machine fields do not.

## 18. Evidence Preservation

The prompt explicitly forbids translating or paraphrasing `source_filename` and `exact_quote`. Existing source-page evidence validation remains authoritative. UI evidence uses `dir="auto"`; report evidence uses the original snapshot.

## 19. Requirement Ownership

Category, quote, filename, page, source text, document metadata, tender/buyer narrative, and company/vault data retain their existing ownership. Language changes only analysis-owned explanation.

## 20. Failure / Fallback

Invalid language never calls the model. Language-adherence or extraction failure creates a safe failed result in the requested language. A requested-language failure is not replaced by any older result; prior versions remain separately available in history.

## 21. Language Adherence

A bounded script guard covers compliance headlines and strategy narratives: it rejects Cyrillic/Arabic generated text for EN/UZ, requires Cyrillic for RU, and requires Arabic script for AR. This is a deterministic safety check, not a substitute for human linguistic QA.

## 22. Settings UX

Interface language and Default analysis language are separate labeled sections. The default selector uses native names, is keyboard-native, preserves the previous value on save failure, and makes the Arabic gate explicit.

## 23. Compliance Selector UX

The per-run selector is localized through EN/UZ/RU UI catalogs while option names remain canonical native names. Re-analysis keeps the selector visible, sends `force=true`, and captures the selected code.

## 24. Version History UX

Results show stored language and version. History shows every version in existing order, labels legacy `NULL` as Not recorded, and warns when displayed versions use different analysis languages. No language filter was added.

## 25. Content Direction

Analysis narrative islands derive direction from stored language: EN/UZ/RU LTR, AR RTL, legacy unknown auto. Evidence is auto/original. Application chrome/root, navigation, layout, and directional icons remain LTR in Sprint 8.2.

## 26. Export / Report Language

PDF export resolves an exact immutable version and uses that version's language, never current UI/default state. English, Uzbek, and Russian report chrome is localized; legacy `NULL` exports with English compatibility chrome and a `not-recorded` response header. Version number and language are returned as headers.

## 27. Arabic Analysis Quality Gate

Arabic is registered as generation-supported and RTL but not customer-selectable. Default and per-run APIs reject it. PDF export returns 409 because tested Arabic shaping/bidi support is absent. Arabic UI remains unavailable.

## 28. Model QA Results

The configured `gemini-3.1-pro-preview` sample was blocked by its zero-request provider quota. A bounded synthetic fallback sample on `gemini-2.5-flash` produced two requirements in each of EN/UZ/RU/AR; all four passed schema, canonical-enum, post-extraction verbatim-evidence, and requested-script checks. EN/UZ/RU are enabled. Arabic remains gated because customer selection and PDF shaping/bidi acceptance are not complete. No production or customer data was used.

## 29. Observability

Version creation logs analysis aggregate ID, version number, language, status, and already-approved model identifier. Logs exclude prompts, evidence, document contents, credentials, and customer secrets.

## 30. Security / Authorization

Preferences remain authenticated own-user only. Analysis/version reads and appends retain current user/company ownership enforcement. Language never widens tenant scope or admin localization.

## 31. DB Fingerprints

Default changes touch only the current User preference and ordinary ORM timestamps if present; they do not bump `auth_version` or create domain records. Analysis additions remain inside existing Compliance/TenderAnalysis domains. UI-locale writes do not touch analysis defaults or versions.

## 32. Browser Acceptance

`frontend/tests/s8-2-analysis-language-browser-acceptance.py` defines exactly 60 real-Chromium checks covering settings, defaults, per-run behavior, history, legacy metadata, reuse/force, evidence, direction, export, failures, reload, and isolation, with Arabic-specific cases testing the gate.

## 33. Regression Results

The Sprint 8.2 backend suite passed 12/12, frontend unit suite 7/7, real Chromium matrix 60/60, connector gate 195 passed plus four subtests with one approved skip, TypeScript, ESLint, all directly invoked frontend cross-sprint suites, and the production build. The full root backend diagnostic recorded 595 passes, one approved skip, and 93 subtests; ten unrelated legacy static tests remain stale against already-delivered localization/Explorer changes. The three migration-topology expectations affected by this sprint were updated and pass 30/30. Disposable fresh/existing PostgreSQL matrices, downgrade/re-upgrade, local upgrade, single-head, and clean autogenerate checks pass. No production access occurred.

## 34. Sprint 8.3 Boundary

Sprint 8.2 does not enable `ui_locale=ar`, Arabic UI catalogs, an Arabic Interface-language choice, root RTL, logical-CSS migration, RTL sidebar/navigation, or RTL conversion of product surfaces.

## 35. Remaining Risks

Arabic model quality and PDF shaping/bidi remain gated. Live model quality is provider/model-specific and must be rerun when quota is available and whenever the configured model changes. Linguistic acceptance still benefits from native-speaker review even after deterministic adherence checks pass.
