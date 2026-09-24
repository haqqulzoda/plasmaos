# Sprint 11 — Framework Deprecation & Runtime Maintenance

## 1. Status

**PASS — Sprint 11 complete.** The accepted framework deprecations were removed without a product feature, route-semantic, domain-architecture, or schema change. Validation was local and isolated; no deployment, production access, ADB/EBRD recovery, or Sprint 12 work was performed.

Validation date: 2026-09-14 (Asia/Tashkent).

## 2. Repository / Alembic

- Repository baseline: branch `main`, commit `b38feb5`.
- Sole Alembic head remains `20260912_0001_s10_5_communications`.
- Fresh disposable PostgreSQL 16 bootstrap, `alembic heads`, `alembic current`, `alembic check`, and schema/data preflight all passed.
- `alembic check` reported no new upgrade operations. Sprint 11 adds no migration and rewrites no historical migration.
- Database validation used the existing destructive-test guard with `PLASMA_RELEASE_TEST_CONFIRM=DISPOSABLE_LOCAL_ONLY` and an isolated local database. No production configuration or data was used.

## 3. Next middleware-to-proxy migration

`frontend/middleware.ts` was renamed to `frontend/proxy.ts`, and the exported entry point was renamed from `middleware` to `proxy`, matching the supported Next.js convention. The matcher, auth request, locale request, cookie forwarding, redirect construction, response headers, and failure behavior are otherwise unchanged.

The optimized Next.js build passed with 26 application pages and registered `Proxy (Middleware)` without the former middleware-convention deprecation notice. No duplicate auth check or second routing owner was introduced.

## 4. Auth / locale routing regression

The 254-case Sprint browser suite and 145-case maintained Chromium suite passed. Together with the frontend static suite, they cover:

- authenticated, anonymous, expired, revoked, pending, blocked, Admin, and customer routing;
- locale persistence and isolation for EN/UZ/RU/AR;
- Arabic document RTL and LTR isolation for directional domain content;
- redirects, public/static assets, API pass-through, and session recovery;
- account lifecycle, Notifications, Broadcasts, source refresh, passivity, ownership, and authorization boundaries.

The maintained run recorded zero external requests. No route-semantic or product behavior regression was found.

## 5. Starlette warnings

Application-owned uses of `HTTP_422_UNPROCESSABLE_ENTITY` were replaced by `HTTP_422_UNPROCESSABLE_CONTENT`; the numeric response contract remains 422. Three repository tests that imported the deprecated FastAPI/Starlette synchronous `TestClient` bridge now use the installed current `httpx.AsyncClient` with `ASGITransport`. Their assertions still cover authorization, safe exception handling, origin/cookie hardening, and upload-size rejection.

The final full backend suite passes with warnings promoted to errors, so no Starlette warning remains. FastAPI middleware ordering, request IDs, origin/CORS handling, exception behavior, readiness, and liveness remain covered by the regression suites.

## 6. Pydantic warnings

The two application-owned Hunter response models migrated from deprecated class-based `Config` with `orm_mode` to `ConfigDict(from_attributes=True)`. Field definitions, validation, aliases, serialization, and API/OpenAPI shape were not changed. No Pydantic warning remains in the final warning-as-error run.

## 7. Alembic warnings

`backend/alembic.ini` now declares `path_separator = os`, removing Alembic's deprecated path-splitting fallback. The sole head, migration history, disposable-database guard, fresh bootstrap, current/check, and preflight contracts all pass unchanged.

## 8. Remaining upstream warnings

None in the constrained Sprint 11 environment. The fresh audit initially observed two dependency-internal Starlette/AnyIO warnings when application tests entered the deprecated synchronous `TestClient` bridge. Removing those three application-owned imports provided a safe local resolution without patching dependencies. The final 747-test backend run completed under `-W error` with zero warning emissions.

The complete observed maintenance inventory was:

| Category | Observed source | Ownership / resolution |
| --- | --- | --- |
| Next.js | Deprecated `middleware` file convention | Application-owned; renamed to `proxy` |
| Pydantic | Two class-based model configs | Application-owned; migrated to `ConfigDict` |
| Alembic | Missing explicit path separator, emitted during multiple Alembic invocations | Application-owned configuration; set to `os` |
| Starlette | Deprecated 422 constant in three endpoint responses | Application-owned; current constant used with the same numeric status |
| PyMuPDF | Deprecated `fitz` compatibility import in three runtime modules and one test | Application-owned imports; changed to `import pymupdf as fitz` |
| Starlette / AnyIO | Dependency-internal warnings entered through three synchronous test-client imports | Locally avoidable; tests moved to `httpx.AsyncClient`/`ASGITransport` |

No global warning filter, blanket suppression, vendored dependency patch, or broad framework modernization was added.

## 9. Dependency changes

None. Python requirement files and frontend package/lock data are unchanged. The exact isolated Python environment was installed from `backend/requirements-test.txt`; representative resolved versions were FastAPI 0.141.1, Starlette 1.6.0, Pydantic 2.13.5, Alembic 1.19.2, SQLAlchemy 2.0.52, and pytest 9.1.1. `pip check` reported no broken requirements, and `npm audit` reported zero vulnerabilities.

## 10. Request-budget result

Before/after request dictionaries were identical for every maintained production-page sample. Counts include all captured requests; the second value is the exact `/api/v1/users/me` count.

| Page | Before | After | Result |
| --- | ---: | ---: | --- |
| Explorer | 12 / 1 | 12 / 1 | unchanged |
| My Tenders | 13 / 1 | 13 / 1 | unchanged |
| Bid Preparation | 13 / 1 | 13 / 1 | unchanged |
| Tender Details | 14 / 1 | 14 / 1 | unchanged |
| Compliance | 17 / 2 | 17 / 2 | unchanged |
| Readiness | 14 / 1 | 14 / 1 | unchanged |
| Settings | 16 / 2 | 16 / 2 | unchanged |

There is no request amplification. The existing two `/users/me` requests on Compliance and Settings are unchanged application behavior, not proxy duplication.

## 11. Backend / frontend / browser totals

- Backend full suite under `-W error`: **747 passed, 1 skipped, 100 subtests passed**.
- Frontend: typecheck PASS; lint PASS; static/unit **214/214**; RTL, design-token, and legacy-design audits PASS; optimized production build PASS with 26 pages.
- Maintained Chromium: **145/145**, with zero external requests.
- Sprint browser acceptance: **254/254**.
- Permanent groups: security **118 passed**; analysis **50 passed plus 12 subtests**; connectors **196 passed, 1 skipped, plus 6 subtests**.
- Release-scale PostgreSQL checks passed at 1k, 10k, and 100k rows.

The Windows-mounted workspace can raise `ENOMEM` during recursive Python/Alembic discovery and cannot directly supply the Linux browser libraries. Backend and frontend release validation therefore used source-equivalent `/tmp` snapshots, an exact isolated Python virtual environment, a disposable PostgreSQL container, a Linux Node runtime, and locally extracted browser libraries. No system package or repository dependency was changed for these execution-environment accommodations.

## 12. Release-gate result

**PASS.** Every permanent gate group passed: backend, security, analysis, connectors, migrations, performance, frontend, browser, and configuration/dependencies. The final warning-as-error backend sweep and the post-modernization 118-test security group also passed. Locale/RTL, auth/account lifecycle, Notifications/Broadcasts, source-refresh/passivity, request-budget, and maintained-Chromium coverage are included in those results.

## 13. Exact files changed

Application/configuration changes:

- `backend/alembic.ini`
- `backend/app/api/endpoints/hunter.py`
- `backend/app/api/endpoints/tenders.py`
- `backend/app/core/parser.py`
- `backend/app/core/upload_parser.py`
- `backend/app/services/tender_sources/adb.py`
- `frontend/middleware.ts` → `frontend/proxy.ts`

Test/audit maintenance:

- `backend/scripts/audit_s9_1_architecture.py`
- `backend/test_giz_hydration_worker.py`
- `backend/test_p0_2a_release_admin_repair.py`
- `backend/test_release_runtime.py`
- `backend/test_release_security.py`
- `backend/test_release_uploads.py`
- `backend/test_s1_admin_approval_queue.py`
- `backend/test_s3_2_session_revocation_restore_security.py`
- `backend/test_s7_2_locale_foundation.py`
- `frontend/tests/localization-foundation.test.mjs`

Documentation:

- `docs/S11_FRAMEWORK_DEPRECATION_MAINTENANCE.md`

No generated build, browser, database, audit, or dependency artifact is included in the repository delta.

## 14. Remaining risks

- Validation used deterministic local fixtures and a disposable database; staging/production identity providers, TLS termination, and real external services were not exercised because production access and deployment were out of scope.
- The Next.js proxy executes in its supported Node.js runtime. Future framework changes still require the normal release gate before adoption.
- The constrained dependency set is warning-free today; future dependency updates can introduce new deprecations and must be audited rather than suppressed.

These are non-blocking operational boundaries, not failed Sprint 11 acceptance criteria.

## 15. Sprint 12 entry contract

Sprint 12 may start only from this accepted Sprint 11 baseline:

- branch/commit baseline `main` / `b38feb5`, with the reviewed Sprint 11 delta applied;
- one Alembic head: `20260912_0001_s10_5_communications`;
- no Sprint 11 dependency or schema migration;
- backend 747 passed, 1 skipped, 100 subtests, zero warnings under `-W error`;
- frontend 214/214 plus typecheck, lint, audits, and build;
- browser 254/254 Sprint plus 145/145 maintained;
- all permanent release groups passing and request counts unchanged;
- no production access or deployment performed.

Sprint 11 stops here.
