import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { leadershipListPresentation } from "../lib/projectLeadership.ts";

const names = (count) => Array.from({ length: count }, (_, index) => `Person ${index + 1}`);
const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("one to three leadership names use one compact column", () => {
  for (const count of [1, 2, 3]) {
    const result = leadershipListPresentation(names(count), false);
    assert.equal(result.columns, "one");
    assert.equal(result.visibleItems.length, count);
    assert.equal(result.hasToggle, false);
  }
});

test("four to six leadership names use equal two-column presentation", () => {
  for (const count of [4, 5, 6]) {
    const result = leadershipListPresentation(names(count), false);
    assert.equal(result.columns, "two");
    assert.equal(result.visibleItems.length, count);
    assert.equal(result.hasToggle, false);
  }
});

test("seven or more names are capped at six until expanded", () => {
  const collapsed = leadershipListPresentation(names(9), false);
  assert.equal(collapsed.columns, "two");
  assert.deepEqual(collapsed.visibleItems, names(6));
  assert.equal(collapsed.hasToggle, true);

  const expanded = leadershipListPresentation(names(9), true);
  assert.deepEqual(expanded.visibleItems, names(9));
});

test("project cards balance one to six names and preserve names-only overflow", () => {
  const page = read("../app/dashboard/tenders/[tenderId]/page.tsx");
  const css = read("../components/customer/pages.css");
  const messages = JSON.parse(read("../messages/en/tenderDetails.json"));
  assert.match(page, /className="s143-leadership-list"/);
  assert.match(page, /leadershipViewAll/);
  assert.doesNotMatch(page, /s143-name-table/);
  assert.doesNotMatch(page, /role\.native_role|role\.canonical_role/);
  assert.match(css, /grid-template-columns: minmax\(0, 1\.22fr\) minmax\(0, 1fr\)/);
  assert.match(css, /\.s143-project-grid[^}]*align-items: start/);
  assert.match(page, /data-balanced=\{projectLeadership\.length <= 6 \? "true" : "false"\}/);
  assert.match(css, /\.s143-project-grid\[data-balanced="true"\][^{]*\{[^}]*align-items: stretch/);
  assert.match(css, /\.s143-project-grid\[data-balanced="true"\] > \.s143-section[^}]*\{[^}]*align-self: stretch/);
  assert.match(css, /\.s143-leadership-list\[data-columns="two"\][^{]*\{[^}]*repeat\(2, minmax\(0, 1fr\)\)/);
  assert.equal(
    messages.s143.leadershipSource,
    "Individuals mentioned in the World Bank source. Not procurement contacts.",
  );
});
