# SR-1 — Source Refresh Execution & Efficiency Audit

Audit date: 2026-08-31. Repository state was inspected locally. The configured
PostgreSQL database was queried only inside an explicit read-only transaction;
all mutation/concurrency measurements used a uniquely named disposable database
that was dropped in `finally`. No production system, deployment, migration,
source inclusion rule, connector URL, ADB/EBRD recovery path, customer behavior,
notification, or New badge was changed.

## 1. SR-1 STATUS

**COMPLETE — WITH SR-2 CORRECTNESS BLOCKERS DOCUMENTED.** All five repository
source keys (`uzex`, `world_bank`, `giz`, `adb`, `ebrd`) were traced. The
mandatory connector gate and focused Sprint regressions pass. The current
Alembic revision and sole head are
`20260828_0003_s4_1_tender_engagement_foundation`.

The blockers are not SR-1 failures: identical payloads are classified and
written as updates; same-source concurrent inserts can report optimistic
creates that roll back; direct operator sync endpoints bypass durable job
dedupe; and ADB document/PDF work is coupled to metadata refresh. These must be
resolved before counts or completion notifications are customer-authoritative.

## 2. SOURCE REFRESH EXECUTIVE SUMMARY

Plasma has a useful source-agnostic outer lifecycle: an approved user creates a
`SourceRefreshJob`, a partial unique index coalesces one active generic job per
source, one Celery task dispatches by source key, and a status API exposes the
latest persisted run (`backend/app/api/endpoints/tenders.py:6988-7297`,
`backend/app/workers/source_refresh_tasks.py:45-200`,
`backend/app/models/all_models.py:482-553`). It is manual only; Celery Beat has
no source-refresh schedule (`backend/app/core/celery_app.py:60-78`).

The inner execution is not yet canonical. UzEx has a legacy result shape and
loop; World Bank, GIZ, and EBRD share one result type but duplicate orchestration
loops; ADB has a third result type. Four operator sync endpoints execute inline,
create no `SourceRefreshJob`, and can overlap the generic job. All connectors
use the shared identity/upsert helper, but it performs one or two row lookups and
rewrites every existing Tender, including `last_synced_at`, without a semantic
unchanged comparison (`backend/app/services/tender_sources/base.py:244-326`).

Measured shared-path behavior was linear: 10,000 first inserts executed 20,000
`SELECT` + 10,000 `INSERT` statements in 30.363 s; an identical repeat executed
10,000 `SELECT` + 10,000 `UPDATE` statements in 20.818 s and reported all 10,000
as updated. Domain fingerprints showed no unrelated Proposal, Recommendation,
Engagement, or Analysis creation in this DB-only path.

The future “New” timestamp should use immutable `Tender.created_at`; SR-2 does
**not** need `first_seen_at`. SR-2 does need conflict-safe CREATED detection,
semantic UPDATED/UNCHANGED classification, batch lookup/write behavior, a real
lease/heartbeat, one orchestrator authority for direct and generic routes, and
document work separation—especially for ADB.

## 3. REFRESH SURFACE INVENTORY

| Path / entry point | Function/task | Source(s) | Trigger / authorization | Execution / job | Side effects and downstream | Consumer / status |
|---|---|---|---|---|---|---|
| `POST /api/v1/tenders/refresh` | `refresh_tenders` | UzEx | Customer click; approved user; force operator/admin | Async; `SourceRefreshJob` | Queues source task | Explorer-compatible legacy alias; active |
| `POST /api/v1/tenders/sources/{source}/refresh` | `request_source_refresh` | All five | Customer click/API; approved user; force operator/admin | Async; persisted job | Queues `refresh_tender_source` on `celery` | Explorer refresh menu; active |
| `GET /api/v1/tenders/sources/refresh-status` | `get_source_refresh_status` | All five | Approved user | Sync read; latest job | Five serial latest-job queries; no mutation | No current frontend consumer; active |
| Celery `app.workers.source_refresh_tasks.refresh_tender_source` | `_execute_source_refresh` | All five | Generic refresh dispatch | Async worker; updates existing job | Runs connector orchestration and persists terminal state | `celery` worker; active |
| `POST .../sources/world-bank/sync` | `sync_world_bank_tenders` | World Bank | Operator/admin API | Synchronous request; **no job** | Tender/doc metadata, Project/link, enrichment dispatch | Operator/manual; active |
| `POST .../sources/giz/sync` | `sync_giz_tenders` | GIZ | Operator/admin API | Synchronous request; **no job** | Tender/doc metadata, quarantine; optional inline hydration | Operator/manual; active |
| `POST .../sources/adb/sync` | `sync_adb_tenders` | ADB | Operator/admin API | Synchronous request; **no job** | Tender/doc metadata, PDF contact extraction, lifecycle reconciliation | Operator/manual; active |
| `POST .../sources/ebrd/sync` | `sync_ebrd_tenders` | EBRD | Operator/admin API | Synchronous request; **no job** | Tender and access-required document metadata | Operator/manual; active |
| `POST .../sources/giz/hydrate` | `hydrate_giz_tenders` | GIZ docs | Approved pilot for one accessible Tender; operator for batch/force | Async `TenderSyncJob` | Downloads/parses documents on `heavy_dl_queue` | Explicit Tender Details action; active, not metadata refresh |
| `POST .../{tender_id}/sync-docs` | `sync_tender_documents` | UzEx docs only | Approved pilot with Tender access | Async `TenderSyncJob` | Discovers/downloads/parses docs; compiles Tender text | Explicit API; no passive frontend mount; active |
| Beat `run_hunter_sweep` | `_run_hunter_sweep_async` | Recent all-source Tenders; UzEx doc dispatch only | Every 30 minutes | Async; no refresh job | Creates Recommendations; may dispatch UzEx docs | Background Recommendation authority; active, not refresh owner |
| Beat World Bank auto-drain | `dispatch_world_bank_project_enrichment_backlog` | World Bank Projects | Every 60 s default | Async Project lease/state | Project enrichment jobs | Background Project authority; active, not refresh owner |
| `POST .../seed` / `backend/seed_tenders.py` | seed helpers | UzEx fixtures | Admin endpoint / offline script | Sync; no job | Creates/updates demo Tenders | Development/admin, not normal refresh |

Routes are registered under `/api/v1/tenders` at `backend/app/main.py:78`.
Authorization is at `backend/app/api/deps.py:118-187`. Direct source endpoints
are at `backend/app/api/endpoints/tenders.py:5260-6958`; generic lifecycle is at
`:6962-7297`; document commands are at `:6361-6601` and `:7524-7758`.

## 4. SOURCE MATRIX

Execution and network dimensions:

| Source | Current enablement | Refresh owner(s) / trigger | Schedule | Fetch / pagination | Incremental / cursor | Max/batch | HTTP concurrency / retries | Measured connector baseline | Main bottleneck | SR-2 change |
|---|---|---|---|---|---|---|---|---|---|---|
| UzEx enterprise (`uzex`) | Unconditionally registered and customer-visible | Generic job + `/refresh`; approved customer | None | `TradeList` API once, `From=1, To=50`; one `GetTrade` detail per returned row | Bounded latest window; none | 50 | Sequential detail calls; no fetch retry | 1 row, 2 calls/200, 0.492 s | N+1 network + row DB upsert; no fetched job count | Canonical result and batch upsert; explicit bounded-window capability |
| World Bank (`world_bank`) | Unconditionally registered/customer-visible | Generic job **and inline operator sync** | None | Official JSON; offset pages, 100/page, max 25; total/short/empty/repeat-page termination | Current-active bounded query; none | 2,500 | Sequential pages; one pooled client; 2 retries (3 attempts) | 1 row, 1 call/200, 0.729 s | Per-row Tender + Project/link DB work | One orchestrator; batch identity lookup; preserve Project auto-drain |
| GIZ (`giz`) | Unconditionally registered/customer-visible | Generic job **and inline operator sync** | None | Six country pages + six e-proc pages; sequential project/procedure/document detail | Full bounded surfaces; none | 6 + 6 listing pages; detail rows not item-capped | Sequential; one pooled client; 2 retries | 5 rows, 1 call/200, 0.606 s (one country page only) | Sequential multi-surface/detail network and full rescan | Capability-based bounded scan; separate document hydration |
| ADB (`adb`) | Unconditionally registered/customer-visible; no kill switch | Generic job **and inline operator sync** | None | Current HTML pages max 25/500, then existing RSS fallback; per-row node/PDF discovery | Bounded current scan/fallback; none | 500 / 25 pages | Sequential; retryable requests 2 retries; fresh clients per row stage | Primary 404 + fallback 200, 1 row, 2 calls, 0.949 s | Document redirect/PDF parsing on metadata critical path | Preserve restrictions; connector result contract; async document stage |
| EBRD (`ebrd`) | Unconditionally registered/customer-visible; metadata-only restrictions, but no runtime kill switch | Generic job **and inline operator sync** | None | One public listing; at most 50, sequential details for first 25; bundled fallback on listing failure | Bounded first items; none | 50 / 25 details | Sequential, shared client; 0 retries | 1 row, 1 call/200, 2.323 s | Full bounded rescan/detail calls; fallback can mask live failure as partial | Preserve metadata-only/security rules; generic result and explicit degraded state |

Persistence and lifecycle dimensions:

| Source | DB lookup / write | Transaction scope | Document coupling | Job persistence | Created / updated / unchanged | Partial failure | Concurrent protection | Current visibility |
|---|---|---|---|---|---|---|---|---|
| UzEx | 1–2 `SELECT`s/row; add or rewrite; no per-row flush | One data commit; generic request/start/end commits around it | Metadata/contact only; no refresh document discovery | Generic path yes; direct legacy alias uses generic | Created sequentially; every existing=updated; unchanged absent; fetched persists as 0 | Outer catch collapses all errors to source unavailable; unsafe pending-write ambiguity | Generic job index only; Tender unique indexes | Menu request notice only |
| World Bank | Tender lookup/write + conflict-safe Project/link inserts/select locks + doc lookup | One Tender transaction, then enrichment claim commit | Metadata + attachment discovery; async Project enrichment dispatch | Generic yes; direct operator no | Existing always updated; lifecycle closes inflate updated; unchanged absent | Row exceptions may be partial unless DB transaction is invalid; pagination fetch failure writes none | Generic job only; direct endpoint bypasses | Menu request notice; status API unused |
| GIZ | Tender lookup/write + doc lookup; quarantine scans | One transaction | Metadata + document discovery; downloads only if explicit flag/hydration | Generic yes; direct operator no | Existing always updated; quarantine not in updated count; unchanged absent | Healthy country surfaces can commit while others fail | Generic job only; direct endpoint bypasses | Menu request notice; targeted hydration has job UX/API |
| ADB | Tender lookup/write + doc lookup; lifecycle/legacy scans | One transaction | **Metadata + document redirect + PDF download/text extraction**; no stored file download | Generic yes; direct operator no | Existing always updated; lifecycle/legacy inflate updated; unchanged absent | Primary failure may degrade to RSS; row error partial subject to transaction caveat | Generic job only; direct endpoint bypasses | Menu request notice; health fields in API |
| EBRD | Tender lookup/write + access-doc lookup | One transaction | Metadata + access-required document descriptor; no restricted download | Generic yes; direct operator no | Existing always updated; unchanged absent | Listing failure may commit bundled fallback and mark partial; detail failures retain listing row | Generic job only; direct endpoint bypasses | Menu request notice |

## 5. UZEX EXECUTION TRACE

Approved user → `SourceRefreshJob(queued)` commit → Celery publish → worker marks
`running` and commits → `_sync_uzex_tenders` creates `UzExScraper` → one
`TradeList` POST with limit 50 → one sequential `GetTrade` GET per returned lot
for contacts → `UzExTenderSource.normalize` → shared canonical-key lookup, pair
fallback lookup, insert or full-field rewrite → one commit → no document
discovery/dispatch, Project linkage, or Recommendation generation → worker maps
`success` to `completed`, persists counts and completion, commits → frontend has
already stopped its spinner after POST acceptance. Evidence:
`backend/app/core/scraper.py:1972-2157`,
`backend/app/services/tender_sources/uzex.py:20-58`,
`backend/app/api/endpoints/tenders.py:5191-5262`.

The result has no fetched/failed/unchanged/duration fields, so generic job
`fetched_count` is 0 even when 50 records were fetched.

## 6. WORLD BANK EXECUTION TRACE

Generic job or uncoordinated operator endpoint → official `procnotices` JSON
client → deadline-current query, actionable notice types, offset pages sorted by
submission deadline → duplicate/page fingerprint protection → normalize → parse
attachment URLs from notice HTML → shared Tender upsert → flush → resolve/create
source-scoped Project with `ON CONFLICT DO NOTHING`, lock it, insert/resolve
`TenderProject`, update linkage provenance → upsert document metadata → after all
rows reconcile past deadlines → one data commit → bounded Project enrichment
claim commits and publishes per-Project jobs → response/job completion. Evidence:
`backend/app/services/tender_sources/world_bank.py:413-742`,
`backend/app/services/projects.py:106-261`,
`backend/app/api/endpoints/tenders.py:5265-5438`.

Project HTTP enrichment is not on the metadata critical path, but the bounded
claim/publish operation is called before refresh returns.

## 7. GIZ EXECUTION TRACE

Generic job or operator endpoint → one shared HTTP client → sequential configured
country pages plus exactly `max_pages` e-proc listing pages → e-proc rows are
sequentially enriched through project, procedure, and participation-document
pages → dedupe by external ID → pre-upsert quarantine scans → normalize and
discover canonical document descriptors → shared Tender upsert/flush → document
metadata upsert/flush → optional inline download/parse only when the direct
endpoint explicitly sets `download_documents=true` (generic default false) → one
commit → terminal result. Healthy country surfaces survive other country/e-proc
surface failures as partial. Evidence: `backend/app/services/tender_sources/giz.py:836-1254`,
`backend/app/api/endpoints/tenders.py:6101-6358`.

## 8. ADB EXECUTION TRACE

Generic job or operator endpoint → official current HTML listing pages → current
repository path presently receives non-retryable HTTP 404 → existing connector
uses its configured legacy RSS fallback (no bypass or recovery attempted) →
normalize each GUID → **for every row**, create a client and resolve node via HEAD
or ranged GET, then create another client to download up to 5 MiB of the notice
PDF and parse up to eight pages for contact metadata → shared Tender upsert/flush
→ metadata-only `TenderDocument` upsert → reconcile past deadlines and legacy
unresolved rows → one commit → health/coverage/fallback result → terminal job.
Evidence: `backend/app/services/tender_sources/adb.py:1055-1582`,
`backend/app/api/endpoints/tenders.py:6756-6958`.

`download_documents=false` prevents stored-document download, but does **not**
remove the redirect/PDF contact work above. No ADB path was repaired.

## 9. EBRD EXECUTION TRACE

Generic job or operator endpoint → one ECEPP public search request → filter
actionable rows, cap 50 → fetch details sequentially for first 25 using the same
client → if listing fails and fallback is enabled, use only bundled public
metadata and mark degraded/partial → normalize metadata → create an
`access_required` canonical document descriptor without logging in or fetching
restricted files → shared Tender upsert/flush → document metadata upsert → one
commit → terminal result. Evidence: `backend/app/services/tender_sources/ebrd.py:481-745`,
`backend/app/api/endpoints/tenders.py:6604-6753`.

The bounded probe reached the public listing successfully; no login, restricted
document access, scraping change, or fallback troubleshooting was attempted.

## 10. REFRESH OWNERSHIP RESULT

There is no scheduled owner. UzEx has one effective normal owner—the generic
job, exposed through two route aliases. World Bank, GIZ, ADB, and EBRD each have
**two uncoordinated normal-runtime owners**: the generic durable worker and a
synchronous operator endpoint. The direct endpoint neither creates nor checks a
`SourceRefreshJob`, so it can overlap the generic job and another direct call.
This is a P1 lifecycle/counter risk and must converge in SR-2.

## 11. SCHEDULE RESULT

| Source | Refresh cadence / Beat task / worker / queue | Overlap / missed jobs / disabled behavior |
|---|---|---|
| All five | **NONE** | No automatic refresh exists, so no interval overlap or missed refresh accumulation exists |

Beat owns only Recommendation generation every 30 minutes and World Bank Project
backlog dispatch every 60 seconds; neither fetches source Tender listings
(`backend/app/core/celery_app.py:60-78`). Source jobs use `celery`. Compose's
general worker consumes `celery,ai_fast_queue` with default Celery concurrency;
the document worker separately consumes `heavy_dl_queue` at concurrency 1
(`docker-compose.yml:109-151`). Horizontal/multi-process workers increase
different-source concurrency but do not change the DB active-job invariant.

## 12. ENABLEMENT / KILL-SWITCH RESULT

All five keys are allowed by the key registry and DB constraint, registered in
`SOURCE_REFRESH_SYSTEMS`, shown in Explorer, and callable by every approved
user (`backend/app/services/tender_sources/keys.py:3-21`,
`backend/app/models/all_models.py:255-276`,
`frontend/app/dashboard/tenders/page.tsx:20-28`). There is no per-source enabled
flag, environment gate, customer-visibility registry, or refresh kill switch.
ADB is degraded by connector behavior, not disabled. EBRD is metadata-only and
respects access restrictions, but is not pilot-only or kill-switched in the
refresh route/UI. Therefore a “disabled source does no work” invariant is not
representable today.

## 13. INCREMENTAL REFRESH RESULT

No connector persists a cursor, watermark, ETag, `modified-since`, or last-ID
checkpoint. UzEx repeats the latest 50 window; World Bank repeats the bounded
current-active result; GIZ repeats all configured surfaces; ADB repeats current
pages or fallback plus per-row document discovery; EBRD repeats its capped
listing/details. An immediate second refresh performs network work again and
rewrites every matched Tender because `last_synced_at` is regenerated. Document
descriptors are rediscovered; no refresh document tasks are published.

## 14. PAGINATION RESULT

| Source | Page size / cap | Termination and ordering | Duplicate protection | Mid-page failure / retry |
|---|---|---|---|---|
| UzEx | One `From=1, To=50` request | API order assumed “latest”; no pages | In-memory lot ID set | Whole list failure; detail failure is swallowed per lot; no fetch retry |
| World Bank | 100 default; 25 pages | empty/short page, API total, repeated fingerprint, or cap; deadline ascending | ID set + page fingerprint | A page exception aborts list and no rows are persisted; connector retry repeats that page, full task retry/redelivery restarts page 1 |
| GIZ | 6 country URLs + 6 e-proc page numbers | Country list is fixed; e-proc always requests all configured pages; row order later sorted for Central Asia/deadline | Final external-ID dict | Country failures retain healthy surfaces; e-proc listing failure drops accumulated e-proc rows; detail failure skips that row |
| ADB | Site-defined HTML; max 25 pages/500 items | explicit `has_next`, item/page cap | GUID set | Primary failure abandons primary rows and starts fallback; task redelivery restarts page 1 |
| EBRD | One listing; first 50 | no pagination | external-ID dict | Listing failure may use bundled fallback; detail failure retains listing row |

All pagination is bounded. GIZ's number of detail requests is not capped by a
separate item limit. No source commits a page independently.

## 15. CANONICAL IDENTITY RESULT

Logical identity is `(normalized source_system, stripped external_id)`, encoded
as `canonical_source_key = "{source}:{external_id}"`
(`backend/app/services/tender_sources/keys.py:6-21`). The upsert first selects by
canonical key, then falls back to the source/external pair. Both are unique DB
indexes (`backend/app/models/all_models.py:259-275`). Cross-source external IDs
can safely coincide. One source cannot durably create duplicate canonical rows.
Concurrent same-source contenders both initially believe they created a row,
but one transaction loses to uniqueness; the helper does not recover it as an
update. Logical uniqueness is enforced, while concurrent result semantics are
not.

## 16. CREATED / UPDATED / UNCHANGED RESULT

The current shared helper returns only `(Tender, created: bool)`. CREATED means
“no row was found before add,” not “this transaction ultimately inserted.”
Every found row is labeled UPDATED and receives full assignments plus a new
`last_synced_at`; there is no UNCHANGED result. SKIPPED/FAILED exist only in
source loops and have inconsistent coverage. World Bank and ADB add lifecycle
transitions to `updated_count`; ADB also adds legacy reconciliation. GIZ
quarantine changes are not included. Document created/updated counts returned by
adapters are discarded. Existing counters are therefore unsuitable for a
truthful future update count; sequential successful `created_count` is useful
but not concurrency/rollback-safe.

## 17. TRANSACTION RESULT

Generic lifecycle uses separate commits for request/job creation, worker start,
connector data, and terminal job state. Each connector holds one transaction
for all fetched Tender rows; World Bank then performs an additional committed
Project enrichment claim before returning. UzEx does not flush per row; the
other four flush each Tender, and GIZ also flushes documents per row.

There is no per-row savepoint. A normalization/value error can be counted and
other rows may commit. A database flush error invalidates the entire transaction;
subsequent row work fails and final commit rolls everything back. Commit-failure
responses retain pre-rollback created/updated counters, so they can overstate
writes. UzEx's broad catch does not explicitly roll back, creating an additional
risk that pending pre-error ORM writes are flushed with the terminal job commit.

## 18. SQL STATEMENT RESULT

The audit script instruments SQLAlchemy `before_cursor_execute` around the real
shared helper and mirrors the per-row flush used by World Bank/GIZ/ADB/EBRD
(`backend/scripts/audit_sr1_source_refresh.py:229-289`). First insert performs
two selects because neither key exists, then one insert. Repeat performs one
select and one update. Transaction commits are reported separately. Statement
counts exclude schema setup and fingerprint queries.

## 19. SYNTHETIC SCALE BENCHMARK

| Source/path | Size | First wall | Repeat wall | HTTP | First SQL S/I/U/D | Repeat SQL S/I/U/D | Created | Updated on repeat | Unchanged | Doc jobs | Errors | Notes |
|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|---|
| Shared `upsert_tender` + per-row flush | 100 | 0.526 s | 0.197 s | N/A | 200/100/0/0 | 100/0/100/0 | 100 | 100 | 0 | 0 | 0 | DB-only; one commit/run |
| Shared `upsert_tender` + per-row flush | 1,000 | 3.389 s | 1.887 s | N/A | 2,000/1,000/0/0 | 1,000/0/1,000/0 | 1,000 | 1,000 | 0 | 0 | 0 | DB-only; one commit/run |
| Shared `upsert_tender` + per-row flush | 10,000 | 30.363 s | 20.818 s | N/A | 20,000/10,000/0/0 | 10,000/0/10,000/0 | 10,000 | 10,000 | 0 | 0 | 0 | DB-only; one commit/run |

Host and cache state make wall time non-portable; statement counts and linear
shape are the primary evidence. The disposable database was bootstrapped through
the supported immutable baseline and migrated to head, then dropped.

## 20. FIRST VS REPEAT INGEST RESULT

The repeat fetched no external data in the DB-only benchmark, but used identical
normalized payloads through the production helper. Tender count and
`created_at` remained stable; `last_synced_at` changed for every row; every row
was reported updated; every row generated an SQL `UPDATE`. A real immediate
source repeat additionally repeats connector network and document discovery.

## 21. DB WRITE FINGERPRINT

For 100, 1,000, and 10,000 rows, first and repeat fingerprints were respectively
N and N Tenders, with zero `TenderDocument`, Project, TenderProject,
Recommendation, TenderEngagement, Proposal, TenderAnalysis, or AnalysisVersion
rows. Thus the shared helper alone does not create unrelated domain state.

Source-specific code adds expected coupling: World Bank may create Project and
TenderProject and rewrites link provenance observation time; GIZ/ADB/EBRD/World
Bank may create/update TenderDocument metadata. No source refresh directly
creates Recommendation, Engagement, Proposal, TenderAnalysis, or AnalysisVersion.

## 22. SAME-SOURCE CONCURRENCY RESULT

Disposable PostgreSQL test: two sessions selected the same absent GIZ identity;
both returned `created=True`; commits produced one success and one
`IntegrityError`; one Tender persisted. The same test for two queued GIZ
`SourceRefreshJob`s produced one success, one integrity error, and one active
job. Therefore DB uniqueness prevents duplicate rows/jobs, but the Tender helper
does not provide conflict-safe idempotent semantics or truthful losing-run
counters. Direct operator sync endpoints bypass the active-job protection and
both can fetch/write before uniqueness decides individual rows.

## 23. CROSS-SOURCE CONCURRENCY RESULT

The same external ID under GIZ and ADB committed twice with distinct IDs and two
rows. Concurrent queued GIZ and ADB jobs both committed. There is no global DB
lock or shared application transaction. They can execute independently when the
`celery` worker has capacity, but they share that queue and DB pool, so a single
available worker process/slot serializes them operationally. The dedicated heavy
document worker does not block the source queue.

## 24. LOCK / LEASE / IDEMPOTENCY RESULT

Present: partial unique active-job index per source, deterministic Celery task ID
equal to job ID, terminal redelivery short-circuit, Tender identity indexes,
TenderSyncJob active index, World Bank Project row locks/`SKIP LOCKED` leases.
Absent for source refresh: advisory/Redis lock, heartbeat, lease expiry field,
worker ownership token, direct-endpoint coalescing, checkpoint idempotency, and
conflict-safe Tender upsert. `updated_at` changes at worker start and finish only;
it is not a heartbeat. Celery late ack/reject-on-worker-loss can redeliver a
`running` job, which reruns the connector because only terminal states short
circuit (`backend/app/core/celery_app.py:48-50`,
`backend/app/workers/source_refresh_tasks.py:67-78`).

## 25. HTTP CLIENT RESULT

| Source | Client/session | Timeout | Retry/backoff | Redirects/pooling/rate limit |
|---|---|---|---|---|
| UzEx | `httpx.AsyncClient`; one list client, a second reused across details | 30 s scalar | None for listing/detail | Redirect default false; pooling within each phase; no source rate limit/delay |
| World Bank | One AsyncClient across pages | 30 s scalar | 2 retries after 0.5/1.0 s; catches all exceptions; no jitter | Redirect default false; pooled; 0.25 s inter-page delay |
| GIZ | One AsyncClient across all listing/detail requests | 30 s scalar | 2 classified retries; exponential 0.5..5 s + jitter/Retry-After | Follow redirects; pooled; 0.25 s sequential delay |
| ADB | One listing/fallback client; fresh clients for each node and PDF stage | 30 s scalar; max 5 redirects | 2 classified retries with same jitter/Retry-After | Follow redirects per request; sequential; no distributed rate limit |
| EBRD | One listing/detail client | 15 s scalar | Default 0 retries | Follow redirects; pooled; 0.25 s detail delay |

All clients inherit httpx compression behavior. Only named connectors set an
explicit connector User-Agent; UzEx listing uses httpx defaults and JSON/Referer
headers. Separate connect/read timeout budgets are not configured.

## 26. NETWORK BENCHMARK

Low-volume official-path probe; no writes, bypass, alternate URL, login, or
restricted download:

| Source/path | Records | Calls | HTTP success / other | Retries | Redirects | Mean / max request | Total connector wall | Note |
|---|---:|---:|---|---:|---:|---:|---:|---|
| UzEx limit 1 | 1 | 2 | 2×200 | 0 | 0 | 159.8 / 179.8 ms | 0.492 s | list + one contact detail; zero transport failures |
| World Bank 1×1 page | 1 | 1 | 1×200 | 0 | 0 | 700.6 / 700.6 ms | 0.729 s | official JSON; zero transport failures |
| GIZ one country page, no e-proc | 5 | 1 | 1×200 | 0 | 0 | 556.1 / 556.1 ms | 0.606 s | connector parsed five rows; zero transport failures |
| ADB max 1/page 1 | 1 | 2 | 1×404 + 1×200 | 0 | 0 | 464.1 / 604.7 ms | 0.949 s | current path failed once; existing RSS fallback used; zero transport failures |
| EBRD max 1/no details | 1 | 1 | 1×200 | 0 | 0 | 1,656.4 / 1,656.4 ms | 2.323 s | public listing; no restricted access; zero transport failures |

## 27. WALL-CLOCK BENCHMARK

Connector-only wall times are in section 26; DB/upsert wall times are in section
19. A full default refresh was not run because UzEx is hard-coded to 50 plus
details, GIZ/ADB perform additional per-row network work, and running those paths
against the configured DB would violate the read-only boundary. Current code
exposes only aggregate connector `elapsed_ms`; it does not separately time fetch,
normalization, DB, or document dispatch. No fabricated stage precision is given.

## 28. DOCUMENT COUPLING RESULT

| Source | Classification | Can metadata completion precede expensive processing today? |
|---|---|---|
| UzEx | Metadata/contact critical path; documents separate | Yes; refresh does not discover/queue docs |
| World Bank | Metadata + document-link discovery; no download/parse | Yes; actual file processing is separate, Project enrichment async |
| GIZ | Metadata + document discovery; optional direct inline hydration | Generic path yes; operator can deliberately couple download/parse |
| ADB | **Metadata + document redirect + PDF download + text parsing** | No for current contact/PDF discovery stage |
| EBRD | Metadata + access-required descriptor | Yes; restricted documents are not downloaded |

## 29. DOCUMENT REDISPATCH RESULT

Refresh itself publishes zero document jobs for all sources. Repeats rediscover
World Bank/GIZ/ADB/EBRD descriptors and execute per-document lookups. World Bank
and GIZ preserve an existing download status; EBRD reasserts `access_required`.
ADB re-downloads/parses contact PDFs and unconditionally sets an existing
document's status back to `metadata_only`, so a previously richer status can be
downgraded—documented only, not fixed (`backend/app/services/tender_sources/adb.py:1522-1582`).

UzEx's separate document worker avoids re-downloading a usable stored document
and reparses only missing text or explicit markerless requests. The scheduled
Hunter sweep can re-dispatch recent UzEx Tenders on later sweeps when they remain
Recommendation-pending; its in-memory dedupe lasts only one sweep
(`backend/app/workers/hunter_tasks.py:69-106`).

## 30. PROJECT ENRICHMENT INTERACTION

Only World Bank refresh creates/reuses canonical Project and TenderProject rows.
It commits Tender ingestion before calling the bounded enrichment dispatcher.
The dispatcher uses Project eligibility, row locks with `SKIP LOCKED`, bounded
claims, durable states, and async per-Project jobs. Beat independently drains
the backlog every 60 seconds, so refresh is not the sole recovery owner. Refresh
does not perform Project HTTP enrichment inline. This preserves Sprint 1
(`backend/app/services/project_enrichment.py:447-540`).

## 31. RECOMMENDATION INTERACTION

Source refresh never calls the Hunter agent and never inserts Recommendation.
The 30-minute Hunter task is the sole generation owner; it selects actionable
Tenders whose immutable `created_at` is within 24 hours, excludes existing
profile/Tender recommendations, evaluates in batches of 25, and commits once.
Newly inserted source Tenders become eligible indirectly. Hunter also dispatches
UzEx document work before evaluation. Explorer/Tender reads do not generate or
refresh Recommendations (`backend/app/workers/hunter_tasks.py:50-166`).

## 32. FAILURE SEMANTICS

- Listing/page failure: UzEx reports source unavailable; World Bank writes none;
  GIZ can retain healthy surfaces; ADB attempts existing fallback; EBRD may use
  bundled fallback.
- One normalization/document-discovery error: counted per row and loop continues
  when the DB transaction remains usable.
- One DB flush error: transaction becomes unusable; final commit rolls back all;
  pre-rollback counters can remain in the failure result.
- Document descriptor failure is a row failure. Actual async document worker
  failures are separate and cannot change source job status.
- Timeout status is classified via safe failure class/status/retryability. Raw
  errors are bounded to ten type-only entries in source results.
- One source job failure does not update another source job. Shared worker/queue
  exhaustion can delay another source but does not make it failed.

## 33. PARTIAL SUCCESS RESULT

`partial` exists and is persisted. It represents row failures, GIZ surface
failures, World Bank/ADB truncation/health degradation, or EBRD fallback. It does
not identify committed versus rolled-back row counts, page checkpoints, or
document-processing completion. There is no PARTIAL state for UzEx; all caught
failures are `source_unavailable`. Retry always starts from the beginning.

## 34. RETRY / BACKOFF RESULT

HTTP: World Bank 2 unclassified retries with fixed linear waits; GIZ/ADB 2
classified retries with bounded exponential jitter and numeric Retry-After;
EBRD 0; UzEx listing/details 0. Connector loops add no outer retry. The source
Celery task has no `autoretry_for`/`self.retry`; broker publication has up to
three retries, which retries message publication, not source HTTP. Late-ack
redelivery after worker loss can rerun the entire nonterminal job. World Bank
Project enrichment separately has at most three task retries; UzEx document
download helpers separately have four Tenacity attempts. Those are downstream,
not stacked with metadata refresh except ADB's inline PDF requests.

## 35. RETRY AMPLIFICATION

| Source | Per logical request max | Listing-cycle worst case in current refresh | Multiplication |
|---|---:|---:|---|
| UzEx | 1 | 1 list + up to 50 detail = 51 | No HTTP/task stack |
| World Bank | 3 | Up to 25 pages ×3 = 75 calls | No connector/Celery retry multiplier; worker-loss redelivery is unbounded by code |
| GIZ | 3 | Every listing/detail request up to ×3 | Sequential additive requests; no outer multiplier |
| ADB | 3 | Primary page up to 3 + fallback up to 3; per-row node/PDF each up to 3 | Additive fallback and per-row work, not 3×3×3 |
| EBRD | 1 | 1 listing + up to 25 details | No HTTP/task stack |

Publish retry can emit an uncertain duplicate only under broker acknowledgement
ambiguity; deterministic task ID plus active job helps, but is not broker-level
dedupe. Repeated worker loss can replay a running connector because no source
task retry cap/lease owner is persisted.

## 36. JOB PERSISTENCE RESULT

`SourceRefreshJob` fields: source, nullable requester user, status, force,
created/updated/fetched/skipped/rejected/failed counts, fallback/skip reasons,
failure class/stage/retryable, elapsed, source publication bounds, health fields,
safe message, created/started/completed/updated timestamps
(`backend/app/models/all_models.py:482-553`).

| Required question | Support |
|---|---|
| Which source is refreshing / start / finish / success / partial? | SUPPORTED for generic jobs |
| Fetched / failed? | SUPPORTED, but UzEx fetched is always 0 and source semantics differ |
| How many NEW? | PARTIALLY SUPPORTED; field exists, concurrency/rollback can lie |
| Updated? | PARTIALLY SUPPORTED; unchanged/lifecycle values inflate it |
| Unchanged? | NOT SUPPORTED |
| Initiating user/operator? | PARTIALLY SUPPORTED; user ID stored but not exposed |
| Scheduled versus manual? | NOT SUPPORTED; no scheduled refresh exists and no trigger field |
| Safe error? | SUPPORTED |
| Documents discovered/queued? | NOT SUPPORTED in job |
| Direct operator run? | NOT SUPPORTED; no job exists |

`TenderSyncJob` is a separate per-user/Tender document job with only status,
progress, error, and timestamps; it must not be reused as source-refresh history.

## 37. JOB STATE MACHINE

Actual source statuses: `queued → running → completed | partial |
source_unavailable | failed`. `fresh` is a synthetic response for cooldown reuse,
not a persisted state. Desired mapping: QUEUED=`queued`, RUNNING=`running`,
SUCCEEDED=`completed`, PARTIAL=`partial`, FAILED=`failed` plus a useful separate
`source_unavailable` terminal reason. There is no cancelled/expired state.
Direct operator runs have no state machine.

## 38. STALE JOB RECOVERY

No startup cleanup, Beat cleanup, timeout task, lease renewal, or periodic stale
recovery exists. A later generic request examines `updated_at`; after 1,800 s
default it marks the old active job failed and creates another. Therefore a job
can remain running forever if no one requests that source again. A legitimate
run longer than 30 minutes has no heartbeat and can be declared failed while
still executing, enabling overlap. Worker-loss redelivery may rerun; if broker
redelivery never arrives, persistence remains stale.

## 39. CUSTOMER REFRESH TRIGGER RESULT

Ordinary approved users can select any of five sources in Explorer and POST a
default refresh. They cannot force; operators/admins can use `force=true`.
Pending, rejected, disabled, and stale-auth-version users are denied. The generic
path has a five-minute completed cooldown and active-job dedupe but no IP/user
rate limiter. Source selection is customer-controlled. The response shows
queued/reused state, but the current frontend discards its structured fields.

## 40. CURRENT REFRESH UX

Explorer shows a source-specific dropdown, disables all source buttons during
the POST only, shows a spinner for the selected source while awaiting acceptance,
then displays “{source} refresh requested” and immediately refetches Explorer
(`frontend/app/dashboard/tenders/page.tsx:216-240`). It does not call
refresh-status, poll, retain queued/running state, show progress/completion,
distinguish partial/failure after acceptance, show counts/source timestamps, or
show activity history. There is no global multi-source refresh. A POST enqueue
failure gets only “could not be requested.”

## 41. NOTIFICATION INFRASTRUCTURE RESULT

No toast/notification provider or source-completion notification exists.
Current reusable primitives are local inline `role="status"` and `role="alert"`
messages. They are page-scoped and not backed by durable events. Admin pages have
similar local banners, not a general notification system. SR-3 should consume
authoritative backend completion records rather than reuse Explorer list-length
changes.

## 42. TENDER TIMESTAMP AUDIT

Tender has `created_at` (server default now), `publication_date`, and
`last_synced_at`; it has **no `updated_at` column**
(`backend/app/models/all_models.py:160-276`). Shared upsert never assigns
`created_at`, always preserves it on update, and rewrites `last_synced_at`.
Lifecycle/GIZ quarantine/document compilation writers do not touch
`created_at`. The multi-source migration backfills identity only and does not
rewrite creation time (`backend/alembic/versions/20260610_0001_multi_source_tender_foundation.py:57-249`).

Runtime admin seed uses the shared helper; the offline seed uses `NOW()`. Tests
can explicitly construct timestamps, but are not runtime writers. No migration
or backfill assigns source publication time to Tender `created_at`. Old Tenders
retain original creation time after updates. Concurrent losing inserts do not
alter the winner's timestamp.

## 43. NEW BADGE TIMESTAMP DECISION

**USE `TENDER.CREATED_AT`.** Repository evidence proves it is the immutable
first durable insertion timestamp under normal runtime and migration paths.
`publication_date` is source time; `last_synced_at` is rewritten on every
refresh; no Tender update timestamp exists. Recommended future display window:
24 hours. SR-2 should expose backend-computed `is_new`/`new_until` or the
authoritative `created_at` plus server time; it must not use publication,
analysis, recommendation, or last-sync time.

## 44. NEW-TENDER COUNT CORRECTNESS

Sequential first insert=1 created; identical repeat=0 created/all updated;
changed metadata=0 created; same external ID in another source=another created;
concurrent same-source insertion=one durable row but both pre-commit helpers say
created; partial/commit failure can return created counts for rolled-back rows.
Thus the logical invariant “one durable canonical insert in this refresh = one
NEW” is enforced by DB uniqueness but **not yet truthfully counted by the
application result**. SR-2 must count only committed insert winners, ideally
from `INSERT ... ON CONFLICT ... RETURNING` or an equivalent batch result.

## 45. CURRENT REFRESH RESULT CONTRACTS

- `RefreshResponse` (UzEx): status, `new_count`, `updated_count`, message only.
- `SourceSyncResponse` (World Bank/GIZ/EBRD): fetched/created/updated/skipped/
  rejected/failed, attachment/download counts, diagnostics, errors, duration.
- `AdbSyncResponse`: similar data but names `fetched/created/updated/skipped/
  failed` and `attachments_discovered`.
- `SourceRefreshResponse`: normalized persisted job shape, but no unchanged or
  document counters and no trigger/initiator exposure.

Schemas are at `backend/app/api/endpoints/tenders.py:234-329`. The shared outer
response/job is worth extending; source-specific direct DTOs and duplicated loops
should not remain lifecycle authorities.

## 46. SOURCE-AGNOSTIC ARCHITECTURE RESULT

| Branch/location | Classification |
|---|---|
| Connector parsers, URLs, normalization, document adapters | VALID CONNECTOR-SPECIFIC |
| ADB health/fallback and EBRD access-required restrictions | VALID CAPABILITY DIFFERENCE |
| `_run_source_refresh` `if source == ...` and four duplicated sync loops | ORCHESTRATION LEAK |
| Direct source sync routes with independent lifecycle | ORCHESTRATION LEAK |
| Explorer hard-coded refresh source list/labels | UI LEAK |
| GIZ targeted hydration and UzEx-only document sync | VALID CAPABILITY DIFFERENCE, provided metadata lifecycle remains generic |

The existing `NormalizedTender`, `CanonicalDocument`, connector protocol,
canonical key helper, `SourceRefreshJob`, and worker task are the correct reuse
points (`backend/app/services/tender_sources/base.py:23-203`).

## 47. ADB FUTURE-COMPATIBILITY RESULT

ADB can plug into a future orchestrator if it implements the same generic
capability/result interface: stable source key and GUID identity; bounded fetch
result with fetched/deduped/skipped/truncated/fallback metrics; optional
checkpoint capability declared unsupported until proven; normalized Tender and
document descriptors; committed CREATED/UPDATED/UNCHANGED outcomes; structured
partial/source-unavailable failure; separate document/contact acquisition stage;
and stage timings. The current HTTP 404/fallback and freshness health must remain
visible, not normalized to success. No Cloudflare bypass, URL change, restricted
access, or repair is proposed.

## 48. EBRD FUTURE-COMPATIBILITY RESULT

EBRD needs the same interface, declaring metadata-only/access-required document
capability, one-page bounded fetch, optional public-detail enrichment, no current
checkpoint, and explicit live-versus-bootstrap provenance. Security restrictions
must remain in the connector; orchestration/UI should render generic source,
partial/failure, and counts without EBRD-specific branches. No login automation,
restricted document download, URL change, or recovery is proposed.

## 49. PERFORMANCE BOTTLENECK RANKING

| Priority | Evidence | Bottleneck |
|---|---|---|
| P0 | MEASURED | Per-row lookup/flush: first 3N SQL statements; repeat 2N statements |
| P0 | MEASURED/CODE-PROVEN | Identical input rewrites every Tender and reports every row updated; no unchanged semantics |
| P0 | MEASURED/CODE-PROVEN | Concurrent insert/rollback counters can be false even though uniqueness preserves rows |
| P1 | CODE-PROVEN | Direct operator endpoints bypass job dedupe and observability |
| P1 | CODE-PROVEN + bounded probe | ADB current listing degrades to fallback and per-item PDF work sits on metadata path |
| P1 | CODE-PROVEN | All sources repeat bounded scans; no checkpoint/cursor |
| P1 | CODE-PROVEN | World Bank unchanged rows repeat Tender + Project/link conflict/lock work and link provenance changes |
| P1 | CODE-PROVEN | No source heartbeat; long/live or abandoned jobs can overlap/remain running |
| P1 | CODE-PROVEN | GIZ/EBRD/ADB detail work is sequential; GIZ detail item count lacks separate cap |
| P2 | CODE-PROVEN | Status API executes one latest-job query per source |
| P2 | CODE-PROVEN | Result DTO/name duplication and hard-coded orchestration/UI source branches |
| P2 | CODE-PROVEN | Frontend has no completion/status consumption |

No hypothetical production throughput or source volume was labeled measured.

## 50. SCALE MODEL

Shared standard-connector DB shape: first ingest `SELECT≈2N`, `INSERT≈N`;
repeat `SELECT≈N`, `UPDATE≈N`; memory≈O(N) for fetched rows/dedupe; one data
transaction. Naively extending the measured local slope—not an SLA—gives:

| N | First SQL / repeat SQL | Local linear wall illustration |
|---:|---:|---:|
| 1,000 | 3,000 / 2,000 | 3.4 s / 1.9 s measured |
| 10,000 | 30,000 / 20,000 | 30.4 s / 20.8 s measured |
| 100,000 | 300,000 / 200,000 | ~5.1 min / ~3.5 min if slope held; high uncertainty |

Network shape: UzEx≈`1+N`; World Bank≈O(pages), ≤25; GIZ≈12 listing calls +
O(e-proc rows) detail/document calls; ADB≈O(pages)+O(N) node/PDF calls; EBRD≈1
+ min(N,25). World Bank adds approximately four conflict/lock statements per
valid Project-linked Tender before possible updates, plus document lookup.

## 51. OBSERVABILITY GAP MATRIX

| Metric | Availability | Evidence/gap |
|---|---|---|
| Per-source duration | AVAILABLE NOW | `elapsed_ms`, except UzEx result has none |
| HTTP calls/failures/retries | MISSING | Logs do not aggregate into job fields |
| Items fetched | PARTIALLY AVAILABLE | Persisted field; UzEx 0, source semantics inconsistent |
| New | PARTIALLY AVAILABLE | Field exists; not conflict/rollback-safe |
| Updated | PARTIALLY AVAILABLE | Includes unchanged/lifecycle |
| Unchanged | MISSING | No classification/field |
| Failed/skipped | PARTIALLY AVAILABLE | Fields exist; coverage differs by source |
| DB/upsert duration | MISSING | Only whole-source elapsed |
| Documents discovered/queued | DERIVABLE only in direct result / MISSING in job | Adapter counts discarded; queue count absent |
| Last successful/failed refresh | DERIVABLE | Query job history; current status API returns latest only |
| Active source/start/finish | AVAILABLE NOW | Generic jobs only |
| Queue wait/heartbeat/worker | MISSING | No enqueued timestamp distinction/heartbeat/worker ID |

## 52. AUTHORIZATION RESULT

Generic refresh/status requires `require_approved_user`; force requires
operator/admin. Direct source sync requires operator/admin. Disabled is checked
before role bypass; pending/rejected are not approved; platform admin/operator
must themselves be approved/enabled. JWT resolution compares token
`auth_version` to the current User row and rejects stale credentials
(`backend/app/core/security.py:108-131`). Ordinary approved customers can run
non-force refresh for every source. Authorization was not changed.

## 53. PASSIVE READ RESULT

Explorer initial load calls only the Explorer GET; source POST exists solely in
the click handler. Tender Details initial render uses its two approved passive
reads. Bid Preparation mount document synchronization was previously removed.
Dashboard layout does not call source refresh. No customer read triggers source
fetch, Tender mutation, Project enrichment creation, or Recommendation
generation. Static and frontend regression tests explicitly assert absence of
refresh-status/sync mount calls.

## 54. LOCAL PREFLIGHT

Count-only configured-development data; **not production truth**:

| Source | Tenders | Min/max created_at | Min/max last_synced_at | Documents | Job statuses |
|---|---:|---|---|---:|---|
| ADB | 35 | 2026-06-10 / 2026-06-10 | 2026-08-24 / 2026-08-24 | 42 | 3 completed, 2 partial |
| EBRD | 89 | 2026-07-04 / 2026-08-30 | 2026-07-04 / 2026-08-30 | 25 | 2 completed, 1 partial |
| GIZ | 188 | 2026-07-02 / 2026-08-30 | 2026-07-02 / 2026-08-30 | 933 | 5 completed |
| UzEx | 435 | 2026-02-21 / 2026-08-30 | 2026-06-09 / 2026-08-30 | 1,762 | 2 completed |
| World Bank | 1,134 | 2026-06-09 / 2026-08-30 | 2026-08-24 / 2026-08-30 | 0 | 3 completed |

Totals: 1,881 Tenders; 2,762 TenderDocuments; 462 Projects; 1,134
TenderProjects; 4,109 Recommendations; 3 Engagements; 120 Proposals; 127
TenderAnalyses; 127 AnalysisVersions. Missing canonical identities=0;
duplicate source/external groups=0; duplicate canonical-key groups=0; stale
active jobs=0; successful jobs in last seven days=15; failed/source-unavailable
jobs in last seven days=0. The transaction was rolled back. Reproducible query:
`python3 backend/scripts/audit_sr1_source_refresh.py preflight`.

## 55. STATIC WRITER AUDIT

| Writer | Classification | Tender/TenderDocument effect |
|---|---|---|
| `upsert_tender` via five connectors | SOURCE INGEST / SOURCE UPDATE | Sole normal Tender creation; metadata/full rewrite |
| lifecycle reconciliation / GIZ quarantine | SOURCE UPDATE | Status, metadata, scrape status, last sync; no creation time |
| connector `upsert_documents` | SOURCE INGEST | Document metadata create/update |
| UzEx/GIZ document workers and GIZ inline hydration | DOCUMENT PROCESSING | Document/file/text/status writes; Tender compiled text |
| World Bank project/link helper | PROJECT ENRICHMENT adjacency | Project/TenderProject only; no Tender creation |
| admin `/seed` | ADMIN / MANUAL | Uses canonical upsert |
| `backend/seed_tenders.py` | SEED / TEST | Direct inserts with `NOW()` |
| purge/reset/diagnostic scripts | ADMIN / MANUAL / TEST | Offline explicit operations; not imported runtime owners |
| migrations | MIGRATION / BACKFILL | Identity/schema backfill; no creation-time rewrite |

No unexplained normal-runtime Tender creator was found. TenderDocument creators
are connector adapters, document workers/hydration service, and an inline GIZ
helper (`rg` evidence at `backend/app/services/tender_sources/*`,
`backend/app/workers/tender_tasks.py:397,952`,
`backend/app/services/giz_document_hydration.py:259`).

## 56. REFRESH SIDE-EFFECT MATRIX

Legend: `W` direct write, `D` async downstream eligibility/dispatch, `—` none.

| Event | Tender | TenderDocument | Project | TenderProject | Recommendation | Engagement / Proposal | Compliance / AnalysisVersion |
|---|---|---|---|---|---|---|---|
| Passive Explorer open | — | — | — | — | — | — | — |
| Manual source refresh | W | W metadata except UzEx | W World Bank | W World Bank | D later Hunter eligibility only | — | — |
| Scheduled source refresh | — (none exists) | — | — | — | — | — | — |
| Repeated unchanged refresh | W `last_synced_at` | rediscover/look up; possible W | World Bank lookup | W provenance | — direct | — | — |
| Refresh with new Tender | W insert | W metadata | W World Bank | W World Bank | D later Hunter | — | — |
| Refresh with updated Tender | W | possible W | World Bank lookup | possible W | — direct | — | — |
| Failed source refresh | — after fetch failure; partial caveats | —/partial caveats | —/partial WB | —/partial WB | — | — | — |
| Partial refresh | W committed successful rows | W successful rows | W World Bank rows | W World Bank rows | D later only | — | — |
| Document ingestion | W compiled text only | W download/parse/status | — | — | — direct | — | — |
| Project enrichment | — | — | W + roles | — | — | — | — |

## 57. CONNECTOR GATE

Mandatory command executed exactly:
`bash backend/scripts/run_connector_regression_gate.sh`.
Result: **195 passed, 1 approved skip, 4 subtests passed** in 13.37 s; zero
unexpected failures. The skip is the existing approved storage fixture skip.

## 58. SOURCE REGRESSION RESULT

Connector gate covered cross-source identity, source refresh API/worker, World
Bank, UzEx scraper/document behavior, ADB, EBRD, GIZ, hydration, access, status,
parser, and worker failure handling. Focused backend cross-sprint command passed
**120 tests and 10 subtests** with three deprecation warnings. No external ADB or
EBRD behavior was changed to obtain green results.

## 59. SPRINT 6 REGRESSION

Backend Sprint 6.1/6.2/6.4 tests were included in the 120-pass focused run.
Frontend unified Explorer (9), Hunter retirement (6), Tender Details (13), and
Tender cleanup/passivity (9) tests all passed; TypeScript `tsc --noEmit` passed.
Recommendation generation ownership and source non-inference remain unchanged.

## 60. SPRINT 1 / WB REGRESSION

Sprint 1.1 Project foundation, Sprint 1.2 World Bank enrichment, Sprint 1.3
Project context/runtime recovery, and World Bank auto-drain tests were included
in the 120-pass focused run. Canonical Project/TenderProject and backlog
auto-drain behavior remain intact.

## 61. ALEMBIC CHECK / HEAD

Configured DB `current`: `20260828_0003_s4_1_tender_engagement_foundation
(head)`. Repository `heads`: the same single head. `python3 -m alembic check`:
`No new upgrade operations detected.` No migration was created.

## 62. EXACT FILES CHANGED

1. `backend/scripts/audit_sr1_source_refresh.py` — audit-only read-only preflight,
   disposable SQL/fingerprint/scale/concurrency benchmark.
2. `docs/SR_1_SOURCE_REFRESH_EXECUTION_EFFICIENCY_AUDIT.md` — this report.

No runtime, model, schema, connector, frontend, deployment, or test behavior was
changed.

## 63. DOCUMENT CREATED

`docs/SR_1_SOURCE_REFRESH_EXECUTION_EFFICIENCY_AUDIT.md`.

## 64. REMAINING RISKS

- New/update counters are not transaction/concurrency truthful.
- No unchanged classification; repeat work is O(N) writes.
- Direct operator routes bypass jobs, cooldown, status, and active-source dedupe.
- No source enablement/kill-switch registry despite all sources in customer UI.
- No heartbeat; stale/long jobs and worker-loss replay are ambiguous.
- ADB current listing is degraded and ADB PDF/contact work is refresh-critical;
  this audit deliberately did not repair it.
- EBRD fallback can preserve availability while customers receive bundled rather
  than live metadata; current health is only a partial result, not enablement.
- Source HTTP/DB/document stage metrics are absent.
- World Bank unchanged refresh repeats Project/link work.
- One DB row failure can roll back a whole transaction while counters retain
  optimistic values.
- Frontend reports request acceptance as the only observable result.

## 65. SR-2 IMPLEMENTATION CONTRACT

SR-2 minimum architecture, based on the evidence above:

1. **Extend `SourceRefreshJob`; do not create a competing lifecycle aggregate.**
   It is already the per-source run. Add immutable trigger kind
   (`customer/operator/scheduled`), lease owner/expiry/heartbeat, truthful
   `unchanged_count`, committed document discovered/queued counts, stage timing
   fields, and safe structured terminal reason. Preserve requester FK; expose
   only safe initiator kind to customers.
2. **One orchestration authority.** Generic and operator routes must call the
   same service; operator tuning becomes validated connector options on that
   service. No inline endpoint may bypass active-job/lease rules.
3. **Conflict-safe, semantic upsert.** Batch-fetch existing canonical keys;
   compare a defined source-metadata fingerprint excluding observation time;
   return CREATED/UPDATED/UNCHANGED/SKIPPED/FAILED. Count CREATED only from a
   committed insert winner. Do not let `last_synced_at` alone classify UPDATED.
4. **Bounded transaction truth.** Use bounded batches/savepoints or another
   explicit partial-commit policy. Persist counters only after their batch
   commits; rolled-back rows count failed, never created/updated. Advance any
   checkpoint only after durable persistence.
5. **Lease/idempotency.** Retain the active-source unique index, add heartbeat
   and expiry/owner comparison, make redelivery claim the same job safely, and
   prevent a live task from being timed out solely because it exceeds 30 minutes.
6. **No `first_seen_at`.** Use immutable Tender `created_at`; expose 24-hour New
   semantics from the backend.
7. **Connector capability/result contract.** Each connector returns source key,
   fetch counts, duplicates/skips, truncation/fallback, normalized records,
   document descriptors, optional checkpoint in/out, structured failures, and
   stage timings. ADB/EBRD can implement it without UI branches.
8. **Incremental policy.** No connector currently proves a stable cursor, so
   SR-2 must not invent one. Declare current modes explicitly: UzEx latest-50,
   World Bank current-active bounded, GIZ bounded surfaces, ADB current bounded,
   EBRD capped list. Add checkpoint persistence only when a connector proves a
   stable source cursor; reserve optional contract fields now.
9. **Separate document processing.** Metadata completion means normalized
   Tender plus document descriptors are durable. Download/archive/PDF parsing
   occurs after commit on the document queue. Move ADB redirect/PDF contact work
   out of metadata critical path; preserve GIZ/EBRD access rules and UzEx worker
   behavior.
10. **Preserve World Bank Sprint 1.** Canonical Project/TenderProject linkage may
    remain in metadata persistence, but enrichment stays auto-drained and async.
    Avoid changing link provenance/writes when evidence is semantically equal.
11. **Partial semantics.** `partial` means at least one committed record plus a
    bounded failed/skipped/truncated portion. `failed` means no successful
    committed refresh unit. `source_unavailable` remains a terminal reason.
12. **Per-source runs, not mandatory child aggregate.** Each current job is
    already a child-sized unit. If a future “refresh all” command is added, it
    creates independent per-source jobs; a parent summary is optional and must
    never serialize/fail them as one unit.

## 66. SR-3 UX DATA CONTRACT

SR-2 must expose, authoritatively and without list-length inference:

- Per source: `source_system`, stable display label, enablement/customer
  visibility, job ID, persisted status, queued/started/heartbeat/completed time,
  safe terminal reason, partial flag, and last successful/failed refresh.
- Per completed job: committed `fetched`, `created`, `updated`, `unchanged`,
  `skipped`, `failed`, `documents_discovered`, `documents_queued`, fallback/
  truncation, and duration/stage timing fields.
- A bounded completion feed or `completed_after` contract ordered by
  `(completed_at, job_id)`, allowing SR-3 to render “World Bank refresh complete,”
  “12 new tenders from World Bank,” and aggregate “17 new tenders available”
  exactly once per observed job. The frontend must not compare Explorer arrays.
- Tender DTO: authoritative `created_at` and preferably backend-derived
  `is_new` plus `new_until = created_at + 24h`, based on server time.
- POST response: accepted/reused job with source and state; GET list/status must
  return all enabled/visible sources even when no historical job exists.

Polling/SSE/WebSocket and notification presentation remain SR-3 choices; SR-2's
durable fields/feed must support any of them.

## 67. RECOMMENDED NEXT TASK

Proceed to **SR-2 — Source-Agnostic Refresh Orchestration, Truthful Upsert Results,
Leases, and Document Decoupling** using section 65 as the locked implementation
contract. Do not start localization/Sprint 7 or SR-3 UX until SR-2 proves
committed created/updated/unchanged counters and independent per-source terminal
states under concurrency and retry.
