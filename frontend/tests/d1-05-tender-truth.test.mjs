import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  daysLeft,
  deadlineBasisLabel,
  effectiveDeadlineMs,
  formatBudget,
  formatPublishedDeadline,
  isBudgetPublished,
  isClosedByDeadline,
  isDeadlinePassed,
  isTenderOpen,
  TENDER_SOURCE_UNAVAILABLE_DETAIL,
} from "../lib/tenderTruth.ts";
import { isTenderActionable } from "../types/tender.ts";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const labels = {
  notPublished: "Not published",
  localTimeAsPublished: "local time (as published)",
  zoneTimeAsPublished: (zone) => `${zone} time (as published)`,
  dateAsPublished: "date as published",
  closedDeadlinePassed: "Closed (deadline passed)",
};

// ---- D1-05 honest budgets -------------------------------------------------------------

test("null, zero, negative and non-finite budgets are 'Not published', never an amount", () => {
  for (const value of [null, undefined, 0, -5, Number.NaN, Number.POSITIVE_INFINITY, "", "0"]) {
    assert.equal(isBudgetPublished(value), false, String(value));
    assert.equal(formatBudget(value, "USD", "en", labels.notPublished), "Not published", String(value));
  }
  assert.equal(formatBudget(1500, "USD", "en", labels.notPublished), "$1,500");
  assert.match(formatBudget(2500000, "UZS", "ru", "Не опубликован"), /2\s500\s000/);
  assert.equal(formatBudget(100, "not-a-code", "en", labels.notPublished), "Not published");
});

test("every customer budget display site uses the shared helper", () => {
  const sites = {
    "app/dashboard/tenders/page.tsx": 2, // Explorer card + preview drawer
    "app/dashboard/tenders/[tenderId]/page.tsx": 1,
    "app/dashboard/my-tenders/page.tsx": 1,
    "app/dashboard/bid-preparation/page.tsx": 1,
    "app/dashboard/bid-preparation/[proposalId]/page.tsx": 1,
  };
  for (const [path, count] of Object.entries(sites)) {
    const source = read(path);
    assert.equal((source.match(/formatBudget\(/g) || []).length, count, path);
    assert.doesNotMatch(source, /budget > 0|estimated_value === null/, path);
  }
  // Dashboard and pursuit overview render no budget at all.
  for (const path of ["app/dashboard/page.tsx", "app/dashboard/pursuits/[pursuitId]/page.tsx"]) {
    assert.doesNotMatch(read(path), /\bbudget\b.*formatCurrency|formatCurrency\([^)]*budget/, path);
  }
  for (const locale of ["en", "ru", "uz", "ar"]) {
    const common = JSON.parse(read(`messages/${locale}/common.json`));
    assert.ok(common.tenderTruth.notPublished, locale);
    assert.ok(common.tenderTruth.localTimeAsPublished, locale);
    assert.ok(common.tenderTruth.closedDeadlinePassed, locale);
    assert.match(common.tenderTruth.zoneTimeAsPublished, /\{zone\}/, locale);
  }
});

// ---- D1-05b deadline time truth ------------------------------------------------------------

const worldBank = {
  status: "OPEN",
  deadline: "2026-10-16T17:00:00Z", // borrower local 17:00, zone unknown
  deadline_time_basis: "SOURCE_LOCAL_UNSPECIFIED",
  deadline_published_local: "2026-10-16T17:00",
  deadline_effective_at: "2026-10-16T03:00:00Z", // 17:00 at UTC+14
};

test("an unspecified-zone deadline is shown as published, unconverted and labelled", () => {
  const text = formatPublishedDeadline(worldBank, "en", labels);
  assert.match(text, /Oct 16, 2026/);
  assert.match(text, /05:00 PM|17:00/);
  assert.match(text, /\(local time \(as published\)\)$/);
  assert.equal(deadlineBasisLabel(worldBank, labels), "local time (as published)");
});

test("explicit-zone and date-only deadlines carry their own label and no invented time", () => {
  const uzex = { ...worldBank, deadline_time_basis: "EXPLICIT_TZ", deadline_timezone: "Asia/Tashkent" };
  assert.match(formatPublishedDeadline(uzex, "en", labels), /Asia\/Tashkent time \(as published\)/);
  const giz = { status: "OPEN", deadline: "2026-10-01T00:00:00Z", deadline_time_basis: "DATE_ONLY" };
  const text = formatPublishedDeadline(giz, "en", labels);
  assert.match(text, /Oct 1, 2026 \(date as published\)/);
  assert.doesNotMatch(text, /12:00|00:00/);
});

test("countdown and 'passed' use the conservative effective instant, never the wall time", () => {
  assert.equal(effectiveDeadlineMs(worldBank), Date.parse("2026-10-16T03:00:00Z"));
  const beforeEffective = Date.parse("2026-10-16T02:00:00Z");
  const betweenEffectiveAndWall = Date.parse("2026-10-16T10:00:00Z");
  assert.equal(isDeadlinePassed(worldBank, beforeEffective), false);
  assert.equal(isDeadlinePassed(worldBank, betweenEffectiveAndWall), true); // wall time would still say open
  assert.equal(daysLeft(worldBank, Date.parse("2026-10-14T03:00:00Z")), 2);
  assert.equal(isTenderOpen(worldBank, betweenEffectiveAndWall), false);
});

test("the effective instant falls back to the stored deadline for older API payloads", () => {
  const legacy = { status: "OPEN", deadline: "2026-10-16T17:00:00Z" };
  assert.equal(effectiveDeadlineMs(legacy), Date.parse("2026-10-16T17:00:00Z"));
});

// ---- D1-05c open status truth -----------------------------------------------------------------

test("a passed deadline reads 'Closed (deadline passed)' and is never actionable", () => {
  const closed = { ...worldBank, status: "CLOSED", status_reason: "DEADLINE_PASSED" };
  assert.equal(isClosedByDeadline(closed), true);
  assert.equal(isTenderOpen(closed), false);
  assert.equal(isTenderActionable(closed), false);
  const stillOpenInCache = { ...worldBank, status: "OPEN" };
  assert.equal(isClosedByDeadline(stillOpenInCache, Date.parse("2026-10-17T00:00:00Z")), true);
  assert.equal(isTenderActionable("OPEN"), true); // a bare status carries no deadline
});

test("each customer surface derives open/closed from the shared helper", () => {
  const explorer = read("app/dashboard/tenders/page.tsx");
  assert.match(explorer, /isClosedByDeadline\(tender\)[\s\S]*?truthLabels\.closedDeadlinePassed/);
  assert.match(explorer, /isExpiredDeadline = \(truth: TenderTruth\) => isDeadlinePassed\(truth\)/);
  const details = read("app/dashboard/tenders/[tenderId]/page.tsx");
  assert.match(details, /isClosedByDeadline\(tender\) \? truthLabels\.closedDeadlinePassed/);
  const myTenders = read("app/dashboard/my-tenders/page.tsx");
  assert.match(myTenders, /isClosedByDeadline\(truth\)[\s\S]*?truthLabels\.closedDeadlinePassed/);
  const dashboard = read("app/dashboard/page.tsx");
  assert.match(dashboard, /return isTenderOpen\(tender\)/);
  assert.match(dashboard, /deadlineState\(tender, now, t\)/);
  assert.match(read("lib/dashboard.ts"), /return isTenderOpen\(tender, now\)/);
  const pursuit = read("app/dashboard/pursuits/[pursuitId]/page.tsx");
  assert.match(pursuit, /isDeadlinePassed\(sourceTruth\)/);
});

// ---- D1-04b hidden source deep links -----------------------------------------------------------

test("a deep link to a hidden-source tender shows 'source temporarily unavailable'", () => {
  const details = read("app/dashboard/tenders/[tenderId]/page.tsx");
  assert.equal(TENDER_SOURCE_UNAVAILABLE_DETAIL, "Tender source temporarily unavailable");
  assert.match(details, /detail === TENDER_SOURCE_UNAVAILABLE_DETAIL \? "sourceUnavailable"/);
  assert.match(details, /tTruth\("sourceUnavailableTitle"\)/);
  for (const locale of ["en", "ru", "uz", "ar"]) {
    const common = JSON.parse(read(`messages/${locale}/common.json`));
    assert.ok(common.tenderTruth.sourceUnavailableTitle && common.tenderTruth.sourceUnavailableBody, locale);
    assert.ok(common.tenderTruth.sourceStale, locale);
  }
  assert.equal((read("components/source-refresh/SourceRefreshMenu.tsx").match(/data-source-stale/g) || []).length, 2);
});
