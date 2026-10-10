import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  bidLabel,
  eventLabel,
  filenameFrom,
  formatCount,
  formatUsd,
  funnelShare,
  ledgerQuery,
  statusLabel,
  statusTone,
} from "../lib/adminAnalytics.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");

test("ledger filters become a stable query with empty values left out", () => {
  assert.equal(ledgerQuery({ q: "  idom ", status: "REJECTED", country: "" }), "status=REJECTED&q=idom");
  assert.equal(
    ledgerQuery({ procurement_group: "Consultant Services" }, { limit: 50, offset: 100 }),
    "procurement_group=Consultant+Services&limit=50&offset=100",
  );
  assert.equal(ledgerQuery({}), "");
});

test("statuses, joint ventures, counts, money and the funnel read plainly", () => {
  assert.equal(statusLabel("NOT_EVALUATED"), "Not evaluated");
  assert.equal(statusLabel("AWARDED"), "Awarded");
  assert.equal(statusTone("AWARDED"), "success");
  assert.equal(statusTone("REJECTED"), "danger");
  assert.equal(statusTone("EVALUATED"), "info");
  assert.equal(bidLabel({ bid_ordinal: 2, member_ordinal: 1, member_count: 3 }), "Bid 2 · JV member 1 of 3");
  assert.equal(bidLabel({ bid_ordinal: 4, member_ordinal: 1, member_count: 1 }), "Bid 4");
  assert.equal(formatCount(11351), "11,351");
  assert.equal(formatCount(null), "—");
  assert.equal(formatUsd(0.013125), "$0.0131");
  assert.equal(formatUsd(4.5), "$4.50");
  assert.equal(formatUsd(1234.5), "$1,234.50");
  assert.equal(formatUsd(null), "—");
  assert.equal(funnelShare(3, 4), "75%");
  assert.equal(funnelShare(0, 0), "—");
  assert.equal(eventLabel("analysis_completed"), "Analysis completed");
  assert.equal(filenameFrom('attachment; filename="award-ledger-20261010.csv"', "x.csv"), "award-ledger-20261010.csv");
  assert.equal(filenameFrom(undefined, "x.csv"), "x.csv");
});

test("operators see the award ledger; metrics and the outreach exports are admin-only", () => {
  const shell = read("components/shell/AdminShell.tsx");
  const line = (href) => shell.split("\n").find((value) => value.includes(`'${href}'`));
  assert.ok(line("/admin/award-ledger") && !line("/admin/award-ledger").includes("adminOnly"));
  assert.ok(line("/admin/metrics").includes("adminOnly: true"));
  const ledger = read("app/admin/award-ledger/page.tsx");
  for (const path of ["/admin/award-ledger/firms.csv", "/admin/award-ledger/market-sizing.csv", "/admin/award-ledger/market-sizing.md"]) {
    const index = ledger.indexOf(path);
    assert.ok(index > ledger.indexOf("{isAdmin && <>"), `${path} is behind the admin check`);
  }
  const metrics = read("app/admin/metrics/page.tsx");
  assert.ok(metrics.includes("/admin/metrics?"));
  assert.ok(!/dangerouslySetInnerHTML/.test(ledger + metrics));
});
