import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  formatCadence,
  formatLatency,
  formatTimestamp,
  runLabels,
  runQuery,
  shortId,
  sourceTone,
} from "../lib/adminPanels.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");

test("latency, cadence and timestamps read plainly", () => {
  assert.equal(formatLatency(null), "—");
  assert.equal(formatLatency(950), "950 ms");
  assert.equal(formatLatency(12_400), "12.4 s");
  assert.equal(formatLatency(185_000), "3 min 05 s");
  assert.equal(formatLatency(7_440_000), "2 h 04 min");
  assert.equal(formatCadence(null), "Not scheduled");
  assert.equal(formatCadence(86_400), "Every day");
  assert.equal(formatCadence(172_800), "Every 2 days");
  assert.equal(formatCadence(21_600), "Every 6 h");
  assert.equal(formatTimestamp("2026-10-08T03:00:00Z"), "2026-10-08 03:00 UTC");
  assert.equal(formatTimestamp("not a date"), "—");
  assert.equal(shortId("0123456789abcdef"), "01234567");
});

test("source tones and run labels flag what needs attention", () => {
  assert.equal(sourceTone({ status: "completed", stale: false, running: false }), "success");
  assert.equal(sourceTone({ status: "completed", stale: true, running: false }), "warning");
  assert.equal(sourceTone({ status: "failed", stale: false, running: false }), "danger");
  assert.equal(sourceTone({ status: "queued", stale: null, running: true }), "info");
  assert.equal(sourceTone({ status: "never_run", stale: null, running: false }), "neutral");
  assert.deepEqual(runLabels({ status: "FAILED", stuck: false, long: true }), ["Failed", "Long"]);
  assert.deepEqual(runLabels({ status: "RUNNING", stuck: true, long: true }), ["Stuck", "Long"]);
  assert.equal(runQuery(["long", "failed"]), "kind=failed&kind=long");
  assert.equal(runQuery([]), "kind=failed&kind=stuck&kind=long");
});

test("operators see the three panels; Run now and Retry use the existing explicit paths", () => {
  const shell = read("components/shell/AdminShell.tsx");
  for (const href of ["/admin/sources", "/admin/analysis-runs", "/admin/organizations"]) {
    const line = shell.split("\n").find((value) => value.includes(`'${href}'`));
    assert.ok(line && !line.includes("adminOnly"), href);
  }
  const sources = read("app/admin/sources/page.tsx");
  assert.match(sources, /api\.get<SourcePanelItem\[\]>\('\/admin\/panels\/sources'\)/);
  assert.match(sources, /\/tenders\/sources\/\$\{encodeURIComponent\(item\.source_system\)\}\/refresh/);
  assert.match(sources, /params: \{ force: true \}/);
  const runs = read("app/admin/analysis-runs/page.tsx");
  assert.match(runs, /\/admin\/panels\/analysis-runs\/\$\{encodeURIComponent\(item\.analysis_run_id\)\}\/retry/);
  assert.doesNotMatch(runs, /failure_reason|original_quote|document_text/);
  const organizations = read("app/admin/organizations/page.tsx");
  assert.match(organizations, /api\.get<OrganizationPanelItem\[\]>\('\/admin\/panels\/organizations'\)/);
  assert.doesNotMatch(organizations, /api\.(post|put|patch|delete)/);
  assert.match(read("app/admin/audit/page.tsx"), /'ANALYSIS_RUN_RETRIED'/);
});
