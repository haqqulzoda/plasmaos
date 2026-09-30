// Integration fix 3a: lenient open/closed truth (COUNTRY_INFERRED, "Closing — verify on source").
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { deriveFactChips } from "../lib/factChips.ts";
import {
  closingDeadlineMs,
  deadlineBasisLabel,
  isClosedByDeadline,
  isCountdownOver,
  isDeadlinePassed,
  isDeadlineUncertain,
  isTenderOpen,
} from "../lib/tenderTruth.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");
const labels = {
  notPublished: "Not published",
  localTimeAsPublished: "local time (as published)",
  zoneTimeAsPublished: (zone) => `${zone} time (as published)`,
  zoneInferredFromCountry: (zone) => `${zone} time (inferred from country)`,
  dateAsPublished: "date as published",
  closedDeadlinePassed: "Closed (deadline passed)",
  closingVerifyOnSource: "Closing — verify on source",
};

// Published 17:00, zone unknown: countdown to 03:00Z (UTC+14), status closes 05:00Z next day (UTC-12).
const unknownZone = {
  status: "OPEN",
  deadline: "2026-10-16T17:00:00Z",
  deadline_time_basis: "SOURCE_LOCAL_UNSPECIFIED",
  deadline_effective_at: "2026-10-16T03:00:00Z",
  deadline_closes_at: "2026-10-17T05:00:00Z",
};

test("unknown zone: countdown ends early, the tender stays open until the latest instant", () => {
  const before = Date.parse("2026-10-16T02:00:00Z");
  const window = Date.parse("2026-10-16T12:00:00Z");
  const after = Date.parse("2026-10-17T06:00:00Z");
  assert.equal(closingDeadlineMs(unknownZone), Date.parse("2026-10-17T05:00:00Z"));
  assert.deepEqual(
    [before, window, after].map((now) => [isCountdownOver(unknownZone, now), isDeadlineUncertain(unknownZone, now), isDeadlinePassed(unknownZone, now), isTenderOpen(unknownZone, now), isClosedByDeadline(unknownZone, now)]),
    [
      [false, false, false, true, false],
      [true, true, false, true, false],
      [true, false, true, false, true],
    ],
  );
  // The server's reason alone also marks the window.
  assert.equal(isDeadlineUncertain({ ...unknownZone, status_reason: "DEADLINE_VERIFY_ON_SOURCE" }, before), true);
  // No "days left" chip once the countdown is over, even though the tender is open.
  assert.deepEqual(deriveFactChips(unknownZone, null, window), []);
});

test("country-inferred zone: one instant, labelled with the zone", () => {
  const inferred = {
    status: "OPEN", deadline: "2026-10-16T17:00:00Z", deadline_time_basis: "COUNTRY_INFERRED",
    deadline_timezone: "Asia/Ulaanbaatar", deadline_effective_at: "2026-10-16T09:00:00Z", deadline_closes_at: "2026-10-16T09:00:00Z",
  };
  assert.equal(deadlineBasisLabel(inferred, labels), "Asia/Ulaanbaatar time (inferred from country)");
  const now = Date.parse("2026-10-16T10:00:00Z");
  assert.equal(isDeadlineUncertain(inferred, now), false);
  assert.equal(isClosedByDeadline(inferred, now), true);
});

test("responses without deadline_closes_at keep the strict behaviour", () => {
  const legacy = { status: "OPEN", deadline: "2026-10-16T17:00:00Z", deadline_effective_at: "2026-10-16T03:00:00Z" };
  const now = Date.parse("2026-10-16T12:00:00Z");
  assert.equal(isDeadlinePassed(legacy, now), true);
  assert.equal(isDeadlineUncertain(legacy, now), false);
});

test("every status surface shows the verify-on-source label, localized in en/ru/uz/ar", () => {
  for (const locale of ["en", "ru", "uz", "ar"]) {
    const common = JSON.parse(read(`messages/${locale}/common.json`));
    assert.ok(common.tenderTruth.closingVerifyOnSource, locale);
    assert.match(common.tenderTruth.zoneInferredFromCountry, /\{zone\}/, locale);
    assert.ok(JSON.parse(read(`messages/${locale}/dashboard.json`)).deadline.verifyOnSource, locale);
  }
  assert.match(read("app/dashboard/tenders/page.tsx"), /isDeadlineUncertain\(tender\)\s*\?\s*truthLabels\.closingVerifyOnSource/);
  assert.match(read("app/dashboard/tenders/[tenderId]/page.tsx"), /isDeadlineUncertain\(tender\) \? truthLabels\.closingVerifyOnSource/);
  assert.match(read("app/dashboard/my-tenders/page.tsx"), /isDeadlineUncertain\(truth\)\s*\?\s*truthLabels\.closingVerifyOnSource/);
  assert.match(read("app/dashboard/page.tsx"), /isCountdownOver\(truth, now\)\) return t\("deadline\.verifyOnSource"\)/);
  assert.match(read("app/dashboard/pursuits/[pursuitId]/page.tsx"), /deadline_closes_at: pursuit\.source_deadline_closes_at/);
  assert.match(read("lib/useTenderTruthLabels.ts"), /closingVerifyOnSource: t\("closingVerifyOnSource"\)/);
});
