# SR-2.4 Refresh Activity, Source Catalog, and Tender Newness

## 1. SR-3 Backend Contract

SR-2.4 provides four passive customer reads: the source catalog, current/latest source status, terminal refresh activity, and Unified Explorer newness. Source definitions, lifecycle events, and Tender first-discovery newness remain separate concepts.

## 2. Customer-Safe Source Catalog

`GET /api/v1/tenders/sources/catalog` returns `source_system`, `display_name`, `refresh_enabled`, and `can_refresh` for customer-visible sources. It performs no SQL.

## 3. Registry Authority

The immutable `SourceDefinition` registry is the only catalog and display-label authority. Customer APIs contain no duplicate source-label map, runner path, options, queue, or concurrency data.

## 4. Source Visibility

Definitions with `customer_visible=false` are omitted from catalog, status, and activity without deleting history. A visible disabled definition remains visible with `can_refresh=false`; its safe historical status/activity remains readable.

## 5. Refresh Status

`GET /api/v1/tenders/sources/refresh-status` returns every visible definition with separate `active_job`, `latest_terminal`, recency summaries, and an activity baseline cursor. It uses one SQL statement independent of source count.

## 6. Active Job DTO

The active DTO contains only job ID, queued/running state, queued time, start time, and heartbeat time. It exposes no percentage, lease owner/expiry, requester, job options, worker, or delivery information.

## 7. Terminal Summary

Terminal summaries contain status, completion time, semantic counters, document counters, counter authority, fallback/degraded flags, and a generic bounded terminal reason. The same mapper supplies status and activity.

## 8. Counter Authority

`SourceRefreshJob.created_count` is the exact number of `CREATED` Tender outcomes committed by that refresh. Updated and unchanged counts retain the SR-2.1 semantic contract.

## 9. Historical Counter Boundary

SR-2.2 introduced explicit `trigger_kind`; preserved older jobs have `trigger_kind=NULL`. Therefore `counts_authoritative` is true exactly when `trigger_kind IS NOT NULL`. Historical terminal state may display, but activity excludes non-authoritative jobs.

## 10. Refresh Activity

`GET /api/v1/tenders/sources/refresh-activity` returns shared platform events for authoritative terminal jobs from visible sources. Running and queued jobs never appear.

## 11. Activity Eligibility

Eligible statuses are `completed`, `partial`, `source_unavailable`, and `failed`, with non-null completion time and trigger kind. Partial events retain committed created counts; unavailable/failed events return the lifecycle’s truthful zero counters.

## 12. Activity Cursor

The opaque URL-safe Base64 cursor encodes version, UTC `completed_at`, and `job_id`. Ordering is `completed_at ASC, job_id ASC`; continuation uses an exclusive tuple comparison. Default limit is 25 and maximum is 100.

## 13. Bootstrap Contract

Every status item returns the same `activity_cursor`, representing the latest authoritative terminal event visible to the status statement. SR-3 uses that cursor as its initial “notify only after this point” baseline.

## 14. Race Safety

Status state and high-water position are computed by one SQL statement under one PostgreSQL statement snapshot. A completion committed before the snapshot appears as terminal and is at/before the cursor; one committed after it is beyond the cursor and appears in activity. Activity pages advance only to their last returned event, so concurrent later commits remain available on the next poll.

## 15. Activity Security

Events expose shared source ingestion facts only. They omit requester/company identity, raw options, leases, worker/task information, raw errors, payloads, headers, document paths, and credentials.

## 16. Completion Semantics

Completed, partial, source-unavailable, and failed remain distinct. `degraded` is generic and derives from fallback, non-clean terminal status, or non-passing execution/coverage health.

## 17. New Tender Count

Activity `created_count` comes directly from the terminal SourceRefreshJob and is the authoritative count of Tenders first durably inserted by that refresh. It is never reconstructed from Tender queries.

## 18. Partial/Failure Semantics

A partial event may contain both created and failed counts. A clean zero-created event supports “No new tenders.” A failed/unavailable event does not invent created rows; committed partial work must have been classified partial by the lifecycle.

## 19. Source Labels

Catalog, status, activity, and refresh POST responses use `SourceDefinition.display_name`, preventing label drift such as `WorldBank`, `WB`, and `World Bank`.

## 20. Tender Newness

Explorer summaries expose immutable Tender `created_at`, derived `is_new`, and derived `new_until`. Newness is Tender-level and independent of Recommendation, pursuit, Proposal, Compliance, source lifecycle, deadline, and documents.

## 21. 24-Hour Window

The single `TENDER_NEWNESS_WINDOW` is exactly 24 hours. The predicate is `created_at <= server_time < created_at + 24h`; exactly 24 hours is not new and a future timestamp is not new.

## 22. Server Time

Each Explorer response contains one timezone-aware UTC `server_time`. SQL filtering and every row’s `is_new`/`new_until` derive from that same reference, avoiding row-to-row drift and browser clock assumptions.

## 23. New-Only Filter

`GET /api/v1/explorer/tenders?new_only=true` applies `created_at <= server_time` and `created_at > server_time - 24h` before counts, view membership, sorting, offset, and limit. It composes with source, search, document, all/recommended/dismissed, and existing filters without changing sort.

## 24. Job Count vs Recent-New Distinction

Activity `created_count` is exact for one refresh job. Explorer `new_only` is the current rolling 24-hour Tender universe and has no job membership linkage; multiple refreshes in the window can make these values differ.

## 25. API Passivity

Catalog, status, activity, and Explorer new-only paths create no jobs, renew no leases, invoke no connector, enqueue no task, and mutate no Tender/customer domain. The disposable fingerprint remained unchanged across reads.

## 26. Query Performance

Catalog uses zero SQL; status uses one statement; each activity page uses one statement; ordinary and new-only Explorer both used five statements, preserving the existing fixed-count architecture.

## 27. Large-History Benchmark

On 100,001 disposable refresh jobs, status returned five sources in 204 ms and activity returned two stable five-event pages in 88 ms. PostgreSQL plans completed status in 194 ms and activity in 27 ms; the broad terminal predicate correctly favored a sequential scan at this distribution.

## 28. Explorer Scale Regression

On 10,000 Tenders, ordinary Explorer returned a total of 8,000 visible rows in 62 ms; `new_only+source=world_bank` returned 667 in 19 ms. Both used five SQL statements and no N+1 query; search, document, recommendation modes, and pagination variants also completed correctly.

## 29. Security/Data Minimization

Customer schemas exclude `requested_by_user_id`, `options_json`, lease fields, task IDs, raw failures, HTTP internals, runner names, source payloads, and storage paths. Unknown historical source keys are omitted rather than labeled dynamically.

## 30. OpenAPI

OpenAPI defines explicit catalog, active, terminal, status, activity event/response, Explorer `new_only`, `created_at`, `is_new`, `new_until`, and response `server_time` types. Created-count and rolling-newness semantics are documented separately.

## 31. Regression Results

The disposable 100k/10k audit, cursor tie and race tests, newness boundary tests, passive/static security checks, connector gate, SR-2.x audits, Sprint suites, FastAPI startup, and OpenAPI generation results are recorded in the final implementation handoff.

## 32. Exact SR-3 Frontend Contract

SR-3 must implement the following sequence without hard-coded sources:

A. Load `/tenders/sources/catalog` and render only returned items; `can_refresh` controls refresh affordances.

B. Load `/tenders/sources/refresh-status` after the catalog and whenever terminal activity is received.

C. Identify queued/running sources only through each status item’s explicit `active_job`; use `latest_terminal` only for recency.

D. Save any status item’s identical `activity_cursor` as the initial baseline. Do not request initial notifications without this baseline.

E. While any source has an `active_job`, poll `/tenders/sources/refresh-activity?cursor=<cursor>&limit=25`; process events in order, dedupe defensively by `job_id`, replace the cursor with `next_cursor`, and continue immediately while `has_more=true`.

F. Treat each newly returned activity event as exactly one newly completed job.

G. Render its registry-derived `source_display_name` and authoritative `created_count`, with zero meaning “No new tenders.”

H. Distinguish clean completed, partial/completed-with-issues, failed, and source-unavailable through `status`, `degraded`, and `fallback_used`—never by parsing `terminal_reason`.

I. Aggregate multiple newly returned events by summing their authoritative `created_count` values while retaining per-source event detail.

J. Refresh status after terminal events; when no source has an `active_job`, stop or substantially reduce activity polling.

K. Display `New` only when the server returns `is_new=true`; expire it at `new_until` relative to response `server_time`, then confirm on the next response without writing state.

L. Link recent discovery views to `/explorer/tenders?new_only=true`, optionally with `source=<key>` and existing view/filter parameters.

M. Never claim Explorer rows are the exact members of an activity event: event `created_count` is exact per job, while Explorer `new_only` is a rolling 24-hour source/filter universe.

No SR-3 frontend implementation is included in SR-2.4.
