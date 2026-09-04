import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  ACTIVE_REFRESH_POLL_MS,
  INACTIVE_REFRESH_POLL_MS,
  MAX_POLL_BACKOFF_MS,
  activityEventsWithoutDuplicates,
  nextPollDelay,
  notificationForEvents,
  sourceActivityHref,
} from "../lib/sourceRefreshPolicy.ts";
import {
  adjustedServerNow,
  createServerClockReference,
  nextBadgeTickDelay,
  shouldShowNewBadge,
} from "../lib/tenderNewness.ts";

const read = (path) =>
  readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const event = (overrides = {}) => ({
  job_id: "job-wb",
  source_system: "world_bank",
  source_display_name: "World Bank",
  status: "completed",
  completed_at: "2026-09-01T10:00:00Z",
  fetched_count: 20,
  created_count: 12,
  updated_count: 3,
  unchanged_count: 5,
  skipped_count: 0,
  failed_count: 0,
  documents_discovered_count: 2,
  documents_queued_count: 2,
  counts_authoritative: true,
  fallback_used: false,
  degraded: false,
  terminal_reason: "Refresh completed.",
  ...overrides,
});

test("polling cadence, grace policy, and bounded backoff are deterministic", () => {
  assert.equal(nextPollDelay(1, 0, 0), ACTIVE_REFRESH_POLL_MS);
  assert.equal(nextPollDelay(0, 1, 0), ACTIVE_REFRESH_POLL_MS);
  assert.equal(nextPollDelay(0, 0, 0), INACTIVE_REFRESH_POLL_MS);
  assert.equal(nextPollDelay(1, 0, 1), 5_000);
  assert.equal(nextPollDelay(1, 0, 99), MAX_POLL_BACKOFF_MS);
});

test("exclusive-cursor defense deduplicates job ids without timestamp sorting", () => {
  const seen = new Set(["old"]);
  const events = [
    event({ job_id: "b" }),
    event({ job_id: "a" }),
    event({ job_id: "b" }),
  ];
  assert.deepEqual(
    activityEventsWithoutDuplicates(events, seen).map((item) => item.job_id),
    ["b", "a"],
  );
});

test("single completion copy preserves exact count, source, zero, and terminal truth", () => {
  assert.equal(
    notificationForEvents([event()], "a").title,
    "12 new tenders from World Bank",
  );
  assert.match(
    notificationForEvents([event({ created_count: 0 })], "b").title,
    /no new tenders/,
  );
  assert.match(
    notificationForEvents([event({ status: "partial", created_count: 4 })], "c")
      .title,
    /with issues.*4 new tenders/,
  );
  assert.match(
    notificationForEvents([event({ status: "failed" })], "d").title,
    /refresh failed/,
  );
  assert.match(
    notificationForEvents([event({ status: "source_unavailable" })], "e").title,
    /could not be refreshed/,
  );
  assert.match(
    notificationForEvents([event({ degraded: true })], "f").title,
    /limited source coverage/,
  );
});

test("multiple events aggregate counts while retaining mixed issue detail", () => {
  const notice = notificationForEvents(
    [
      event(),
      event({
        job_id: "giz",
        source_system: "giz",
        source_display_name: "GIZ",
        created_count: 3,
        status: "partial",
      }),
      event({
        job_id: "uzex",
        source_system: "uzex",
        source_display_name: "UzEx",
        created_count: 2,
      }),
    ],
    "batch",
  );
  assert.equal(notice.title, "17 new tenders across 3 sources");
  assert.equal(notice.tone, "warning");
  assert.match(notice.detail, /World Bank.*GIZ.*UzEx.*issues/);
  assert.equal(notice.href, "/dashboard/tenders?view=all&new_only=true");
});

test("single-source action links to rolling source newness, never job membership", () => {
  const href = sourceActivityHref(event());
  assert.equal(
    href,
    "/dashboard/tenders?view=all&source=world_bank&new_only=true",
  );
  assert.doesNotMatch(href, /job/);
});

test("server reference defeats positive and negative browser wall-clock skew", () => {
  const clock = createServerClockReference("2026-09-01T10:00:00Z", 1_000);
  assert.ok(clock);
  assert.equal(
    adjustedServerNow(clock, 6_000),
    Date.parse("2026-09-01T10:00:05Z"),
  );
  assert.equal(
    shouldShowNewBadge(true, "2026-09-01T10:00:10Z", clock, 6_000),
    true,
  );
  const browserWallClockPlusTwoHours = Date.parse("2026-09-01T12:00:05Z");
  const browserWallClockMinusTwoHours = Date.parse("2026-09-01T08:00:05Z");
  assert.notEqual(
    browserWallClockPlusTwoHours,
    adjustedServerNow(clock, 6_000),
  );
  assert.notEqual(
    browserWallClockMinusTwoHours,
    adjustedServerNow(clock, 6_000),
  );
});

test("badge expires exactly at new_until and backend false never becomes true", () => {
  const clock = createServerClockReference("2026-09-01T10:00:00Z", 50);
  assert.equal(
    shouldShowNewBadge(true, "2026-09-01T10:00:10Z", clock, 10_049),
    true,
  );
  assert.equal(
    shouldShowNewBadge(true, "2026-09-01T10:00:10Z", clock, 10_050),
    false,
  );
  assert.equal(
    shouldShowNewBadge(false, "2027-09-01T10:00:10Z", clock, 50),
    false,
  );
  assert.equal(shouldShowNewBadge(true, "invalid", clock, 50), false);
  assert.equal(nextBadgeTickDelay(["2026-09-01T10:00:10Z"], clock, 50), 10_000);
});

test("one dashboard provider owns catalog, status, activity, session cursor, and cleanup", () => {
  const provider = read("components/source-refresh/SourceRefreshProvider.tsx");
  const client = read("lib/sourceRefresh.ts");
  const layout = read("app/dashboard/layout.tsx");
  assert.match(layout, /<SourceRefreshProvider enabled>/);
  assert.match(provider, /sessionStorage/);
  assert.doesNotMatch(provider, /localStorage/);
  assert.match(provider, /visibilitychange/);
  assert.match(provider, /requestController\?\.abort\(\)/);
  assert.match(provider, /ACTIVITY_DRAIN_PAGE_LIMIT/);
  assert.equal((client.match(/refresh-activity/g) ?? []).length, 1);
  assert.equal((client.match(/refresh-status/g) ?? []).length, 1);
  assert.equal((client.match(/sources\/catalog/g) ?? []).length, 1);
});

test("Explorer is catalog-driven and new_only is URL and backend authoritative", () => {
  const page = read("app/dashboard/tenders/page.tsx");
  const types = read("types/explorer.ts");
  assert.doesNotMatch(page, /const SOURCES|SOURCE_REFRESH/);
  assert.match(page, /catalog\.map/);
  assert.match(page, /params\.get\(["']new_only["']\) === ["']true["']/);
  assert.match(page, /params\.set\(["']new_only["'], ["']true["']\)/);
  assert.match(page, /new_only: query\.newOnly/);
  assert.match(types, /is_new: boolean/);
  assert.match(types, /new_until: string/);
  assert.match(types, /server_time: string/);
  assert.doesNotMatch(page, /created_at.*is_new|publication_date.*is_new/);
});

test("badge has one shared timer and no per-card interval", () => {
  const page = read("app/dashboard/tenders/page.tsx");
  const badge = read("components/tenders/NewTenderBadge.tsx");
  assert.equal((page.match(/window\.setTimeout/g) ?? []).length >= 2, true);
  assert.doesNotMatch(page, /setInterval/);
  assert.doesNotMatch(badge, /setTimeout|setInterval|Date\.now/);
  assert.match(badge, /t\(["']new["']\)/);
});

test("refresh POST remains explicit and is not owned by Explorer page effects", () => {
  const page = read("app/dashboard/tenders/page.tsx");
  const menu = read("components/source-refresh/SourceRefreshMenu.tsx");
  const provider = read("components/source-refresh/SourceRefreshProvider.tsx");
  assert.doesNotMatch(page, /api\.post|\/refresh`/);
  assert.match(menu, /onClick=\{\(\) => void requestRefresh/);
  assert.match(
    provider,
    /translateRefreshRef\.current\(["']queuedNotice["']|translateRefreshRef\.current\(["']startedNotice["']/,
  );
  assert.doesNotMatch(provider, /Started.*reused/);
});

test("SR-3 contract files use explicit types without broad any", () => {
  for (const path of [
    "types/source-refresh.ts",
    "lib/sourceRefresh.ts",
    "lib/sourceRefreshPolicy.ts",
    "lib/tenderNewness.ts",
    "components/source-refresh/SourceRefreshProvider.tsx",
    "components/source-refresh/SourceRefreshMenu.tsx",
    "components/tenders/NewTenderBadge.tsx",
  ])
    assert.doesNotMatch(read(path), /\bany\b/, path);
});
