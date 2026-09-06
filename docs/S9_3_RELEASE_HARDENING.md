# Sprint 9.3 — Release Hardening

## 1. Executive Summary

**PASS — local Sprint 9.3 acceptance complete.** H01–H12 are addressed in the maintained application and release gates. This is local release-hardening evidence, not a production deployment certification. No deployment, production access, new procurement source, ADB/EBRD recovery, source schedule, or Sprint 9.4 work was performed. ADB/EBRD edits only replace unsafe exception logging.

The baseline is the accepted S9.2 working tree, including the accepted S9.1/S9.2 changes. It is not a clean checkout of HEAD. All subsequent evidence uses synthetic identities, owned disposable PostgreSQL databases, a loopback Redis instance, local HTTP fixtures, and controlled Chromium. See [evidence index](audits/s9_3/result-index.md) and [exact change manifest](audits/s9_3/changed-files.md).

## 2. Baseline

Branch `main`; HEAD `b121cda5b76911c59fdab5733d70aa6883908e9c`. The original tree was dirty with accepted S9.1/S9.2 work and 53 staged cache removals; those changes were preserved. [535 baseline hashes](audits/s9_3/baseline.json) define the comparison boundary; the local verification snapshot is `/tmp/plasma-s93-baseline`.

Baseline backend: **614 passed, 1 skipped, 100 subtests passed** ([log](audits/s9_3/baseline-backend.log)). Baseline frontend production build and seven page measurements are retained. Runtime: Python 3.12.3, Node v22.14.0, npm 10.9.2, PostgreSQL 16.15; FastAPI 0.141.1, Celery 5.6.3, Playwright 1.62.0; Chromium 151.0.7922.34. Next.js was 16.1.6 and is now 16.2.11. Pydantic was an inadvertently resolved 2.14.0b1 in the baseline environment and is now stable 2.13.5. [Final versions](audits/s9_3/runtime-versions.json).

## 3. H01 Google Bridge

Previous path: browser-supplied email/Google ID → `/auth/google` → account reconciliation → backend JWT. The backend accepted asserted identity without cryptographic proof.

Current path: Google OIDC → Auth.js verified initial Google callback → signed, short-lived server assertion → backend signature/claims/replay verification → existing account reconciliation and allowlists → backend JWT → canonical account/auth_version checks on protected requests. The callback uses verified `profile.email`, `profile.sub`/provider subject, and `email_verified === true`; it cannot mint a new bridge assertion from a later browser session-update payload.

## 4. Trust Model

Chosen model: a private Auth.js-to-backend service assertion, compatible with the existing Google provider and account lifecycle. `AUTH_BRIDGE_SECRET` is server-only and never `NEXT_PUBLIC`. HS256 is pinned; PyJWT verifies the MAC, issuer `plasma-authjs`, audience `plasma-backend`, required claims, expiry and issuance time. Assertions last at most 60 seconds. Subject, normalized email, name and avatar must match signed claims. UUID `jti` is atomically consumed with Redis SET NX and a 90-second TTL. Missing/invalid proof yields 401; unavailable secret/replay service yields a safe 503.

Both services require the same independently generated secret of at least 32 characters. Supply it through the deployment secret manager; do not copy fixture values. Rotate both services together; old assertions are invalidated. Redis AOF with `appendfsync always` preserves consumed assertions across normal restarts. After replay-store data loss, keep bridge issuance closed for at least the assertion validity window before reopening. These are deployment operating instructions; no secrets were rotated or deployed here.

## 5. Impersonation Tests

Maintained tests reject approved/admin/operator/arbitrary identity without proof, forged subject, changed email/name, unverified email, wrong issuer/audience, tampering, expiry, and excessive lifetime before account reads or writes. A valid ordinary assertion cannot inject an allowlisted identity. Existing pending, approved, restored, operator and administrator policies remain; conflicting Google/email account matches return 409 and do not create a second account. Disabled/rejected accounts remain blocked, and restored accounts cannot replay a previously consumed assertion. Real Redis concurrency accepted exactly one of twelve identical assertions. No raw assertion, OAuth token, backend JWT or secret is logged by the bridge.

## 6. H02 Backend Guards

All 18 Tender GET handlers are inventoried in [tender-read-inventory.json](audits/s9_3/tender-read-inventory.json). Corpus, documents, versions and export use `require_approved_pilot_access`; source catalog/status/activity use `require_approved_user`. The legacy list and legacy detail now enforce the same backend authority. Resource ownership/visibility remains an additional check. Frontend middleware is not the authorization boundary.

## 7. Direct Backend Auth Matrix

The permanent direct-backend matrix covers legacy list/detail, canonical details, documents and decision snapshot. Anonymous/invalid bearer → 401; pending → 403; rejected/disabled/stale auth_version → canonical 401; approved/operator/admin → 200 for the synthetic list and 404 for an authorized lookup of the deliberately absent resource. Denied requests never query the Tender corpus. The browser executes these real HTTP route/dependency paths with a synthetic persistence fixture; PostgreSQL read tests separately exercise real persisted resources.

## 8. H03 Passive Reads

Customer reads use stored metadata, summaries, documents and immutable analyses. Legacy list/detail/decision no longer call live UzEx dates or WB/ADB/GIZ/UzEx contact retrieval. Missing information remains missing. Real PostgreSQL fingerprints cover 15 read routes: zero domain INSERT/UPDATE/DELETE and identical fingerprints before/after. History, latest Compliance, documents, Explorer, Proposals and Readiness are included. [Read proof](audits/s9_3/read-proof.json).

## 9. Source-I/O Boundary

Source HTTP, browser automation, external download, analysis generation and dispatch are guarded by deterministic spies in `test_release_reads.py`. The controlled browser additionally aborts and records every non-loopback browser request. No customer GET dispatches source or analysis work. Explicit source-refresh/operator/worker commands retain the existing SR boundary; no source recovery or new scheduling was implemented.

## 10. Document Hydration Boundary

The stored download handler serves a local `FileResponse`; a missing or metadata-only file returns a truthful 404. Both `/api/documents/[id]` and `/document-preview/[id]` use the same stored-download proxy. Preview cannot call Playwright or retrieve a remote replacement. Existing explicit `sync-docs`, targeted hydration and worker processing remain available under their prior guards. URL metadata alone never makes a document available.

## 11. H04 Explorer Bounding

The accepted resolver loaded every customer-visible Tender, summarized every document and inspected storage before applying pagination. Replaying the old resolver against 1k and 10k synthetic rows measured 3 SQL queries and respectively 500 and 5,000 file checks (half the corpus had stored files), regardless of the requested 25-row page. [Before evidence](audits/s9_3/scale-before.json).

The compatibility resolver now validates input only. Stored document state/path predicates determine membership in SQL before count/order/pagination; page summaries inspect only returned documents. Heavy `compiled_master_text` is deferred with raiseload. Filter/count authority is the state last persisted by ingestion/hydration. If someone deletes a file outside that boundary, its returned page summary/download truthfully reports missing while the stored filter/count can lag until explicit reconciliation. GET never silently repairs state or scans the corpus. Multiple documents on a page increase checks with page document count, not total Tender count.

## 12. H09 Pagination

Proposal, Readiness, Compliance history and approval queue default to 25, cap at 100, accept offset, and return additive `X-Has-More`, `X-Next-Offset`, and `X-Page-Limit` headers. Proposal/Readiness additionally expose `X-Total-Count`; the approval queue retains its envelope with additive pagination fields. Existing list payloads remain arrays.

Ordering: Proposal/approval queue created-descending plus ID; Readiness document type/name/ID; history version order. Readiness filters run in SQL before pagination. History uses a metadata-only column projection and raiseload for heavy snapshots/document relationships; detail/export retain full immutable snapshots. Fixtures verify 31 rows become 25 + 6 and max+1 is rejected. Customer URL state is preserved through `page` or `historyPage`; filter changes reset the relevant page. The existing admin accounts screen already uses its separate paginated accounts endpoint.

## 13. Query / Scale Evidence

| Tenders | Filter | Queries | Page rows | File checks | ms |
|---:|---|---:|---:|---:|---:|
| 1,000 | documents_available | 5 | 25 | 25 | 114.51 |
| 1,000 | metadata_only | 5 | 25 | 0 | 60.07 |
| 1,000 | files_missing | 3 | 0 | 0 | 34.07 |
| 10,000 | documents_available | 5 | 25 | 25 | 83.74 |
| 10,000 | metadata_only | 5 | 25 | 0 | 102.52 |
| 10,000 | files_missing | 3 | 0 | 0 | 35.76 |
| 100,000 | documents_available | 5 | 25 | 25 | 204.57 |
| 100,000 | metadata_only | 5 | 25 | 0 | 1458.91 |
| 100,000 | files_missing | 3 | 0 | 0 | 110.2 |

| GET | Queries / budget |
|---|---:|
| legacy-list | 5 / 8 |
| legacy-detail | 5 / 8 |
| details | 12 / 13 |
| decision | 6 / 7 |
| documents | 5 / 6 |
| stored-download | 4 / 8 |
| missing-download | 4 / 8 |
| compiled-text | 4 / 10 |
| explorer | 7 / 8 |
| proposals | 5 / 5 |
| readiness | 5 / 6 |
| history | 6 / 7 |
| latest-analysis | 7 / 9 |
| approval-queue | 3 / 5 |
| source-status | 2 / 3 |

EXPLAIN ANALYZE BUFFERS JSON records both count and page-query plans in [scale.json](audits/s9_3/scale.json). SQL counts can still scan matching database rows; application materialization and filesystem work are bounded. These are single local synthetic runs with one document per Tender, not production p95 or a high-document-density claim. Metadata precedence uses several stored predicates and is slower than simple availability. The measured shape supports removing the application prepass; no speculative index or migration was justified.

## 14. H05 Upload Pipeline

Proposal import remains PDF-only. File maximum: **20 MiB**; request maximum: **21 MiB**, leaving multipart overhead. Content-Length is rejected before form parsing; streamed bodies are counted even without that header. Starlette closes partial spools on the multipart limit exception. A 64 KiB copy writes to a tenant-scoped random temporary file; filename never determines the storage path. `.pdf` suffix and `%PDF-` signature are required, followed by structural parsing.

A child process rejects encrypted/malformed PDFs and bounds documents to 200 pages and extracted text to one million characters; parser wall limit 60 seconds, CPU 50 seconds, address space 2 GiB. Model work runs in a separate child with 120-second wall limit, CPU 60 seconds and 2 GiB address space; company context is at most 64 KiB and response at most 1 MiB. Timeout/cancellation kills the process group before releasing capacity. Redis provides four shared processing slots, 240-second leases and one accepted attempt per user per 30 seconds. Rate/capacity failure returns 429; unavailable capacity service returns 503.

## 15. Upload Failure Semantics

Parse/empty-text failure blocks model execution. Model/provider failure returns a stable 502 without a success mutation. Existing Proposal state is copied, response-validated and changed only after successful parsing/model normalization; commit failure rolls back and removes the candidate retained file. Temporary files and UploadFile handles close on all paths. Successful imported source files are deliberately retained for the existing preview workflow.

Permanent tests cover valid/malformed PDFs, wrong extension/signature, oversize length and streamed multipart, path-like filenames, parser/model failure, commit failure, cleanup, timeout process termination, shared concurrency and rate bounds. Controlled Chromium sends actual multipart files and verifies status, no failed commit and cleanup. Parser/provider contents are synthetic; no paid/provider analysis was invoked. Intake remains subject to deployment request/time/concurrency controls; the shared four-slot bound covers processing, and a timed-out third-party upload may need provider-side retention cleanup.

## 16. H06 Error Contract

The hardened HTTP boundary returns generic validation 422 and internal 500 payloads with stable `code`, `detail`, and generated UUID `request_id`; it never serializes Pydantic `input`/`ctx`. Upload, bridge, source probe, download and diagnostics use safe fixed messages and existing status semantics. Known domain 4xx messages remain useful; the application does not translate arbitrary internal exceptions into customer text. Historical extraction errors and operator technical warnings are redacted on read without rewriting immutable versions.

## 17. Logging / Redaction

Touched request/provider/parser/connector/worker exception logs record a static event identifier and exception class, not exception arguments or traceback text. Requirement extraction failure metadata retains safe diagnostic categories. Frontend catch handlers no longer emit response/error objects to the browser console. Synthetic `SECRET_SENTINEL`, `AUTH_TOKEN_SENTINEL`, and `CUSTOMER_TEXT_SENTINEL` checks cover response/log boundaries and historic error reads. The UUID correlation ID is generated server-side, not copied from an untrusted header. Third-party access logging and infrastructure log retention remain deployment configuration responsibilities.

## 18. H07 Configuration

Compose requires PostgreSQL, Auth.js and bridge secrets through environment configuration; old literal administrative credentials and password fallbacks are removed. PostgreSQL publishes no host port. pgAdmin is behind the explicit `development` profile, binds only loopback and requires supplied credentials/master-password behavior. Backend/frontend remain loopback-published behind the intended TLS edge. `.env.example` contains empty secret placeholders and safe flags.

`production`/`release` rejects schema auto-create, OCR demo bypass, pseudo-locale flags, short/missing signing secrets, and wildcard/non-HTTPS origins. Defaults preserve local development separately. Docker manifests align Python/Playwright to 1.62.0 Noble and Node to the tested 22.14.0 family; no Docker daemon was available to build/run containers locally. The official [Playwright container contract](https://playwright.dev/python/docs/docker) documents matching package/image versions. Browser scraping is still an explicit worker/operator operation; no production container was launched.

## 19. Security Headers / Origin / CORS

Backend responses include no-store, nosniff, same-origin referrer policy, a frame-ancestor policy and request ID; HSTS is emitted when the trusted request scheme is HTTPS. Frontend config adds frame-ancestor/object/base/form restrictions and safe headers. Cookies remain HttpOnly/Secure where applicable and SameSite=Lax. The production TLS edge must supply HSTS on its public origin and correctly overwrite forwarded headers.

Unsafe cookie-authenticated backend requests require an allowed Origin; Bearer API requests retain their existing contract. Auth.js owns OAuth/CSRF handling. CORS has explicit credentialed origins and exposes only needed pagination/correlation headers. Tests reject unsafe configuration/origins and verify HTTPS headers. HTTP loopback browser fixtures necessarily exercise secure cookies through Chromium's localhost allowance, not a public TLS deployment.

## 20. SSRF Review

Existing administrator-only probes accept HTTPS on exactly `etender.uzex.uz` or `apietender.uzex.uz`, default/443 port, no credentials/control characters/backslashes. DNS answers must all be public. Browser redirects and subresources are revalidated; probe HTTPX fallback requests validate their destination and do not follow redirects. Probe file paths must stay under the allowed `/files/` form without traversal. Ordinary worker connector behavior is unchanged.

Negative tests include loopback, metadata IP, file URLs, hostname confusion, untrusted host/port, private DNS and redirected/subresource destinations. This application allowlist is not an egress firewall: DNS rebinding of the two trusted hostnames or compromised source infrastructure still calls for network-level private-address denial in deployment. No arbitrary-host proxy remains.

## 21. H08 Dependency Triage

Baseline npm audit: **18 advisories: 2 critical, 12 high, 3 moderate, 1 low**. Final locked audit: **0 vulnerabilities**. [Before](audits/s9_3/npm-audit-before.json), [after](audits/s9_3/npm-audit-after.json), [advisory inventory](audits/s9_3/dependency-triage.json), [exact lock changes](audits/s9_3/dependency-lock-changes.json).

Bounded updates: Next/eslint-config-next 16.2.11, Auth.js beta.32 / core 0.41.3, Axios 1.18.0, PostCSS 8.5.28 and Sharp 0.35.0, plus affected transitive lock entries. No feature library was introduced. Next middleware exposure was runtime-relevant; Auth.js provider-confusion exposure is narrower with one Google provider but was patched; image/native and build-tool advisories were resolved rather than ignored. Primary advisories: [Next](https://github.com/advisories/GHSA-6gpp-xcg3-4w24), [Auth.js](https://github.com/advisories/GHSA-x445-f3h2-j279), [Sharp](https://github.com/advisories/GHSA-f88m-g3jw-g9cj).

Manifest licenses remain MIT/ISC/Apache-2.0 for the touched direct packages; native redistributable obligations remain applicable. Lock entries changed from 500 to 504; lock bytes 251553 → 256277. Platform-specific framework/image binaries account for many changed lock entries. Auth.js remains on the pre-existing v5 beta line, now pinned. npm audit is an advisory snapshot, not a container/OS or provider security attestation.

## 22. Backend Reproducibility

`backend/constraints.txt` pins every resolved runtime/test dependency to an exact stable version. `requirements-test.txt` includes constraints, runtime requirements and test dependencies; Docker explicitly installs runtime requirements with the constraints. Pydantic's accidental prerelease resolution was removed. `pip check` passes and the gate verifies exact installed versions/non-prerelease constraints. Reproduction target is Python 3.12 on Linux; no claim is made for untested Python/platform combinations.

Use `python -m pip install -r backend/requirements-test.txt` for verification or `python -m pip install -c backend/constraints.txt -r backend/requirements.txt` for runtime. The baseline Google GenAI API version and connector semantics were not broadly redesigned.

## 23. H10 Request Amplification

The prior Next middleware performed another `/users/me` for each protected API request even though the backend repeated canonical authorization. That redundant API middleware call is removed; protected SSR/navigation still fetches current authority and every backend request still resolves current account/auth_version. Dashboard navigation prefetch is disabled where it caused avoidable fetches. No cross-request authorization cache or TTL was introduced.

The browser gate caps each tested hard page load at 30 backend requests, 8 `/users/me`, 4 access-status and 6 auth-refresh calls, while asserting zero source I/O. Residual Auth.js and component checks remain; H10 is bounded with measured evidence, not claimed to be one request per page. Locale headers are stripped before trusted propagation, and two-user locale isolation is exercised.

## 24. Production Request Counts

| Navigation / page | Total before → after | `/users/me` before → after |
|---|---:|---:|
| passivity / explorer | 31 → 16 | 21 → 5 |
| passivity / details | 35 → 19 | 23 → 7 |
| passivity / my-tenders | 31 → 14 | 20 → 3 |
| passivity / bid-preparation | 33 → 16 | 22 → 5 |
| passivity / compliance | 41 → 20 | 27 → 6 |
| passivity / readiness | 33 → 15 | 21 → 3 |
| passivity / settings | 37 → 17 | 24 → 4 |
| client-navigation / explorer | 5 → 7 | 4 → 4 |
| client-navigation / my-tenders | 5 → 3 | 3 → 1 |
| client-navigation / bid-preparation | 5 → 5 | 3 → 3 |
| client-navigation / settings | 1 → 1 | 1 → 1 |

Measured using real production Next builds, the same controlled HTTP fixture family, English and 390px viewport, network-idle settling, hard loads and client navigation. The unchanged accepted build was retained separately from the patched build. Counts include required Auth.js refresh and source-status/activity reads; synthetic polling state and warmup can affect individual counts. This is a deterministic release fixture comparison, not production telemetry. [Raw comparison](audits/s9_3/request-comparison.json).

## 25. H11 Session Recovery

Canonical sign-in is `/`; unauthorized Axios recovery no longer targets absent `/login`. Missing/expired session and account revocation return to the real sign-in page. A transient authority/network failure preserves credentials without granting authority: SSR returns a localized 503 interstitial with retry on the same URL, and mounted access checks show localized unavailable/retry rather than labeling an approved account pending. Retry preserves the route/query. Backend revocation checks remain mandatory on every protected request.

## 26. H12 Mobile Fixes

Bid Preparation headers/badges wrap with nonshrinking icons and bounded text. My Tenders search/filter forms stack and allow inputs/selects to shrink within their grid; pagination wraps. Explorer tabs wrap so all are visible, filters use zero-minimum grid tracks, pagination wraps, and the source menu stays within narrow viewports. Existing keyboard focus, ARIA labels, logical start/end positioning and RTL icon behavior are retained.

Chromium checks EN/UZ/RU/AR at 320, 390, 768 and 1440 pixels for Explorer, My Tenders, Bid Preparation and outage/retry. It tests visible control bounds, badge overlap, source menu bounds, focus, document direction and console errors; screenshots support the narrow checks. Native select text may truncate inside a bounded select while the control remains usable.

## 27. Readiness / Queue Diagnostics

`/health` remains liveness; `/health/ready` concurrently probes DB and Redis with two-second bounds and returns 200/503 with dependency booleans only. Admin-only `/api/v1/admin/operations` has a five-second bound, fixed 100-job recent sample, oldest queued source-job age, failed/retryable counts, three Redis queue lengths and WB enrichment status counts. It neither dispatches work nor returns job options, messages, URLs, credentials or customer text. Diagnostic failures yield safe 503; readiness outage and failure redaction are tested. An actual local DB/Redis probe returned both healthy, and a controlled unavailable Redis endpoint returned database=true/redis=false; see [runtime proof](audits/s9_3/readiness-runtime.json). These are queue/dependency observations, not a guarantee that every worker is healthy.

## 28. Permanent Release Gate

`bash scripts/run_release_gate.sh GROUP` supports `backend`, `security`, `analysis`, `connectors`, `migrations`, `performance`, `frontend`, `browser`, `config-dependencies`, or `all`. These are maintained commands, not historical one-off audit invocations. Configure an explicitly disposable loopback PostgreSQL instance and loopback Redis before running; the guard executes before database imports.

```bash
export ENVIRONMENT=test
export POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=5432
export POSTGRES_DB=plasma_s05b4b_release_fixture
export PLASMA_RELEASE_TEST_CONFIRM=DISPOSABLE_LOCAL_ONLY
# Supply disposable-only DB credentials and synthetic test signing keys.
export AUTH_REPLAY_REDIS_URL=redis://127.0.0.1:6379/0
python -m pip install -r backend/requirements-test.txt
python -m playwright install --with-deps chromium
bash scripts/run_release_gate.sh all
```

The browser build uses `NEXT_DIST_DIR=.next-release-test`, port 3114 and fixture API 8114, plus backend security fixture 8124. `PLASMA_FRONTEND_TEST_ROOT` optionally selects an isolated Linux frontend copy. `PLASMA_BROWSER_CASE_FILTER` is debugging only: fewer than 100 cases cannot yield a passing gate. Performance and migration scripts create/drop only their own disposable DBs.

## 29. CI Contract

`.github/workflows/release-gate.yml` runs the maintained `all` gate on pull requests/manual dispatch with Python 3.12, Node 22.14.0, local PostgreSQL 16 and Redis 7 services, synthetic keys, Chromium installation and artifact upload. It has read-only repository permissions. Production/release environment, non-loopback DB host, wrong DB prefix or missing disposable confirmation are rejected before gate imports. No production credential/target is configured.

Local groups were executed; the remote GitHub job was not triggered or observed. Docker image builds and production OAuth/TLS routing are outside this controlled acceptance. CI is a tracked, reviewable integration contract, not an invented remote green run.

## 30. Security Regression

The maintained security group includes proof/impersonation/lifecycle, canonical route guards, upload failures/limits, config/SSRF, shared Redis processing/replay, safe diagnostics/headers and real PostgreSQL read fingerprints. Broad backend: **732 passed, 1 existing skipped, 100 subtests passed**. The single skip is the pre-existing known-481480 local storage fixture test; that fixture is absent. The separately maintained analysis gate passed 50 tests/12 subtests, and the connector gate passed 196 tests/6 subtests with its existing single skip. No unexpected failures. Deprecation warnings remain for existing Pydantic class config, Alembic path configuration and test-client APIs.

## 31. Passivity Regression

[Read proof](audits/s9_3/read-proof.json) covers 15 real PostgreSQL GETs, with zero domain writes and unchanged table fingerprints for users, company profiles, Tenders/documents, Proposals, analyses/versions, Readiness, Recommendations and engagements. Source metadata helpers, HTTP, Playwright, analysis and task dispatch are instrumented to fail on unexpected calls. Existing Recommendation/engagement architecture tests remain in the broad gate. Browser page loads and document proxy reads add a separate external-network check.

## 32. Performance Regression

Permanent assertions cap page size, query count and fixture file checks; history SQL must omit result/evidence/document snapshots and client output cannot contain its large synthetic snapshot. Scale fixtures cover 1k, 10k and 100k; each run performs stored available/metadata/missing filters and retains count/page EXPLAIN plans when an output filename is supplied. Query budgets and frontend request budgets are executable assertions, not timing-only claims. No index was added.

## 33. Browser Acceptance

Current recorded result: **145 passed, 0 failed**. Final acceptance requires all explicit cases and at least 100 passes. [Results](audits/s9_3/browser/results.json), [run log](audits/s9_3/browser-final.log), and locale/mobile screenshots are retained.

The suite combines real production UI navigation, actual browser multipart uploads, real backend HTTP guards with synthetic persistence, proof attacks and replay, two-user locale isolation, outage/retry, pagination, mobile/RTL and request budgets. Authentication provider verification is represented by controlled trusted assertions; the Google network itself is not exercised. Parser/model failures are deterministic fixtures; real PDF structure parsing is verified separately. Intermediate failures are retained as audit history and are not acceptance results.

## 34. Alembic / Migration

No migration or index was added. Expected and observed sole head: `20260904_0001_s8_2_analysis_language`. Fresh disposable bootstrap, `alembic heads`, `current`, `check` and read-only schema/data preflight passed. [Migration log](audits/s9_3/migrations.log). The original accepted migration tree is unchanged.

## 35. Remaining Risks

No unresolved locally demonstrated critical/high finding is accepted as closed without evidence. Scope limitations: real Google/provider services and production infrastructure were not exercised; GitHub CI and Docker builds were not run remotely; DNS rebinding defense ultimately needs private-network egress restrictions; public TLS/HSTS and secret provisioning are deployment prerequisites. Auth.js remains a pinned beta and npm advisory coverage is time-specific. Synthetic scale uses one document per Tender; page-local document density and stored-state drift from out-of-band deletion require operational monitoring. Processing limits do not replace edge request/concurrency limits. Existing test skips/deprecations are visible in logs. These limits are not claims of completed production acceptance.

## 36. Sprint 9.4 Entry Contract

Hand off the verified H01–H12 changes, exact manifest, before/after fingerprints and production request counts, dependency locks/audits, safe configuration, bounded APIs/uploads, session/mobile fixes, and maintained local/CI gates. Before a later release, supply real secrets and validate the actual container/TLS/Google integration in an authorized staging environment. Do not infer production release authorization from this report.

Recommended next task: review this Sprint 9.3 evidence and use it as the input contract for a separately authorized Sprint 9.4. Sprint 9.4 has not been started; no ADB/EBRD recovery or deployment is included.
