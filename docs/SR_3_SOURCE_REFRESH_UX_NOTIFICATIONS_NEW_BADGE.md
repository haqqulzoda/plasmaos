# SR-3 — Source Refresh UX, Completion Notifications, and New Badge

## 1. Previous Refresh UX

The Sprint 6 Explorer owned a hard-coded five-source refresh menu, POSTed directly, kept only page-local pending state, and reported a request as “refresh requested.” Navigation or reload discarded that state. There was no catalog/status/activity client, notification infrastructure, rolling-new filter, or expiring New badge.

| File/component | Previous purpose | Backend API | State ownership | Decision |
|---|---|---|---|---|
| `dashboard/tenders/page.tsx` | Explorer plus source refresh menu | Explorer GET and refresh POST | Page-local | Retain Explorer; move refresh lifecycle out |
| `dashboard/layout.tsx` | Auth gate and dashboard shell | Access status | Layout | Reuse as provider boundary |
| `types/tender.ts` | Legacy known-source presentation helpers | None | Static helpers | Not refresh-menu authority |
| `lib/api.ts` | Authenticated Axios transport | All frontend APIs | Shared transport | Reuse |
| Global notification provider | None | None | None | Add lightweight implementation |

## 2. Source Catalog Consumption

The authenticated dashboard loads `/tenders/sources/catalog` once per provider mount. Explorer, My Tenders, dashboard source labels, and the refresh menu consume the returned ordering and display names. Catalog failure produces an unavailable/retry state and never falls back to a five-source runtime list; ordinary discovery remains functional.

## 3. Global Refresh State Owner

`SourceRefreshProvider` is mounted by the approved dashboard layout and remains above nested routes. Explorer, My Tenders, Tender Details, Bid Preparation, and settings therefore share one lifecycle owner and one poller. Blocked account routes do not mount it.

## 4. Status Initialization

On approved dashboard initialization the provider independently requests catalog and refresh status. Status supplies source-level active and terminal state. A status failure retains known state and announces unavailability rather than fabricating an idle result.

## 5. Activity Baseline

On a new browser session, the provider adopts the identical `activity_cursor` returned by status and does not request older activity. A session reload reuses the session-scoped last good cursor, so a completion during reload remains observable. An invalid cursor is recovered only by refetching status and adopting its race-safe baseline.

## 6. Polling State Machine

Polling is serialized. Each cycle reconciles status, drains activity in returned order, advances the exclusive cursor after each successful page, applies terminal job identity before status rendering, queues new events, and schedules the next cycle. Requests and timers are aborted on provider cleanup.

## 7. Poll Cadence

Active refreshes poll every 2.5 seconds. Two completion-grace cycles prevent loss when active state becomes terminal. Inactive state polls every 60 seconds. A successful explicit POST wakes the poller immediately. Repeated failures use exponential delay capped at 30 seconds. Hidden tabs pause timers and visible tabs reconcile immediately.

## 8. Cursor Management

The opaque cursor is never decoded or synthesized by the frontend. It advances only to backend `next_cursor`, survives reload in `sessionStorage`, and remains unchanged after transient activity failure. Up to ten 25-event pages are drained per cycle; remaining pages cause an immediate next cycle.

## 9. Event Deduplication

The exclusive cursor is primary. A bounded session set of 256 job IDs provides defensive deduplication without re-sorting events by timestamp or merging distinct same-source jobs.

## 10. Refresh Request UX

Only an explicit source button invokes `POST /tenders/sources/{source}/refresh`. The clicked source alone shows Requesting. Accepted queued/running responses say queued/started; reused jobs say already queued/running. POST acceptance is never called completion. Failure clears pending state and produces a safe error without inventing active state.

## 11. Global Active Indicator

The compact dashboard header identifies a single queued/running source by registry display name and summarizes multiple active sources by count. Its expandable detail contains customer-safe source and lifecycle state only.

## 12. Source Menu State

The menu renders catalog items in backend order. Each item independently shows Refresh, Queued, Refreshing, Requesting, or Unavailable. `can_refresh=false` disables POST while historical status remains available. No Refresh All control exists.

## 13. Completion Notifications

Authoritative completed events with created rows render “N new tenders from Source” and a View new tenders action. Zero-created completion still provides closure. Updated and unchanged counts are not promoted into verbose operational copy.

## 14. Zero-New Completion

Clean completion with `created_count=0` produces “Source refresh complete — no new tenders.” It does not force an Explorer refetch or move the current browsing position.

## 15. Partial/Failed/Unavailable UX

Partial completion states both the issue and authoritative new count. Failed and source-unavailable events use distinct generic safe messages. Degraded/fallback completion uses limited-coverage wording. No raw error, stack, HTTP, retry, task, or connector-special logic is exposed.

## 16. Event Aggregation

Events observed within 500 ms are grouped for presentation. Counts are summed only from authoritative job events, per-source details remain visible, and any partial/failure/unavailable/degraded member makes the aggregate warning-toned. Aggregation never merges persisted events or changes cursor semantics.

## 17. Notification Infrastructure

The lightweight dashboard notification region is `aria-live=polite`; failure notices use alert semantics. Notices support keyboard-focusable action and dismiss controls, respect reduced motion, and retain only the newest four visible items.

## 18. Reload/Navigation Behavior

Lifecycle state lives above route pages. Navigation does not issue another refresh or create another poller. Session cursor and job dedupe survive reload; logout clears them. Separate tabs may independently notify, which is the documented minimum behavior without cross-tab coordination.

## 19. New Tender Badge

Explorer displays a compact textual New badge only when backend `is_new=true` and the validated `new_until` has not elapsed. Publication date, updates, documents, Recommendations, pursuit, and source lifecycle do not control membership.

## 20. Server Clock Reconciliation

Each Explorer response creates a reference from backend `server_time` and browser monotonic elapsed time. Badge timing therefore tolerates wall-clock skew. A later response replaces the reference. Backend false can transition to neither inferred nor locally computed true.

## 21. Badge Expiry

One shared Explorer timeout schedules the nearest expiry, capped at a 60-second cadence. Cards create no timers. At adjusted server-now equal to `new_until`, the badge disappears locally without API write, page reload, Tender mutation, or Explorer refetch.

## 22. New-Only Filter

`new_only=true` is parsed from and written to the canonical Explorer URL. The compact “New in last 24h” control resets pagination to page one and passes the flag to the unified backend request. Search, source, lifecycle, geography, service, deadline, value, document, view, and sort remain composable.

## 23. View New Tenders Navigation

A single-source event links to `/dashboard/tenders?view=all&source=<key>&new_only=true`. An aggregate links to `/dashboard/tenders?view=all&new_only=true`. Explorer activity also offers a Show banner without auto-prepending or re-sorting rows.

## 24. Job Count vs Rolling-New Distinction

Activity `created_count` is exact for one job. Explorer `new_only` is the rolling 24-hour discovery universe and may contain rows from several jobs. The UI says “View new tenders,” never “View these exact N” or “Showing the N from this refresh.”

## 25. Accessibility

Refresh status changes and errors use live regions, notifications are textual and dismissible, buttons are keyboard operable with visible focus, New is not color-only, spinners have accompanying text, and motion uses reduced-motion-aware utilities.

## 26. Responsive UX

Chromium verified the dashboard indicator, source menu, toast stack, filter, and badge at 390 px and desktop widths. Menus are viewport-bounded, navigation remains usable, and notification placement does not replace critical controls.

## 27. Network Request Audit

Dashboard initialization makes one catalog and one status request. The dashboard tree owns one serialized status/activity poller. Explorer makes only unified Explorer reads; cards make no lifecycle calls. Explicit source clicks are the only refresh POST source. Inactive and hidden states do not sustain 2-second traffic.

## 28. Browser Acceptance

The dedicated real Chromium harness passes 95/95 required SR-3 cases. The Sprint 6.3 Explorer harness passes 70/70. Coverage includes bootstrap/no-history, reload/navigation, multipage cursor draining, failure recovery, mixed aggregation, exact local expiry, ±2-hour skew, URL history, responsive/accessibility, request collapse, visibility, logout, and blocked polling.

## 29. Regression Results

SR-3 focused Node tests pass 12/12 and the complete frontend static/unit set passes 93/93. TypeScript, ESLint, and the optimized production build pass. The dedicated SR-3 Chromium matrix passes 95/95, the Sprint 6.3 Explorer Chromium suite passes 70/70, and the Hunter redirect matrix passes 5/5. The maintained root backend sweep passes 587 tests with one approved fixture skip and 80 subtests; focused SR-2.4 through SR-2.1 and Sprint 6 regressions pass 71 tests with five subtests; the connector gate passes 195 tests with one approved fixture skip and four subtests. Alembic current/head is `20260901_0001_sr2_3_connector_metrics`, and `alembic check` reports no new upgrade operations. The repository's intentionally unsupported recursive collector still includes duplicate script module names and live-server developer probes, so backend release evidence uses the documented maintained root-module selection.

## 30. Deferred Future Refresh Work

Automatic schedules, Refresh All, email/push, backend notification acknowledgement, exact job-to-Tender membership, cross-tab notification suppression, connector recovery, incremental connector cursors, and an advanced source administration console remain deferred. SR-3 adds no backend migration, connector changes, deployment, production access, or Sprint 7 work.
