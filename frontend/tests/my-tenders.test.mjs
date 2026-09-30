import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  engagementStatusClasses,
  engagementStatusLabel,
} from "../types/engagement.ts";

const page = readFileSync(
  new URL("../app/dashboard/my-tenders/page.tsx", import.meta.url),
  "utf8",
);
const pursuitPanel = readFileSync(
  new URL("../components/tenders/TenderEngagementPanel.tsx", import.meta.url),
  "utf8",
);
const layout = readFileSync(
  new URL("../components/shell/CustomerShell.tsx", import.meta.url),
  "utf8",
);

test("all canonical statuses use customer language and visible text", () => {
  const expected = {
    SAVED: "Saved",
    EVALUATING: "Evaluating",
    PREPARING: "Preparing",
    SUBMITTED: "Submitted",
    WON: "Won",
    LOST: "Lost",
    DISMISSED: "Dismissed",
  };
  for (const [status, label] of Object.entries(expected)) {
    assert.equal(engagementStatusLabel(status), label);
    assert.ok(engagementStatusClasses(status).includes("text-"));
  }
  assert.notEqual(engagementStatusLabel("PREPARING"), "Draft");
});

test("My Tenders is engagement-only, bounded, and URL-driven", () => {
  assert.match(
    page,
    /\.get<MyTendersListResponse>\(\s*["']\/my-tenders["']/,
  );
  assert.match(page, /PAGE_SIZE = 25/);
  assert.match(page, /useSearchParams/);
  assert.match(page, /status/);
  assert.match(page, /search/);
  assert.match(page, /sort/);
  assert.match(page, /page/);
  assert.doesNotMatch(
    page,
    /\/proposals|Proposal|compliance|Hunter|Recommendation/,
  );
});

test("engagement and source status are separately labeled and accessible", () => {
  assert.match(page, /t\("engagement", \{\s*status: engagementLabel/);
  assert.match(page, /t\("tender", \{ status: tenderLabel \}\)/);
  assert.match(page, /aria-label=\{t\("statusesLabel"\)\}/);
  assert.match(page, /<Tabs/);
  assert.match(readFileSync(new URL("../components/ui/foundation.css", import.meta.url), "utf8"), /focus-visible/);
  assert.match(page, /role="status"/);
  assert.match(page, /<Alert\s+tone="danger"/);
});

test("empty state is truthful and never imports legacy bids", () => {
  assert.match(page, /t\("emptyTitle"\)/);
  assert.match(page, /t\("explore"\)/);
  assert.doesNotMatch(page, /no bids|legacy proposals/i);
});

test("save happens only in explicit click handler and represents re-engagement", () => {
  const effect = pursuitPanel
    .split("useEffect(() =>", 2)[1]
    .split("const save =", 1)[0];
  assert.doesNotMatch(effect, /api\.post/);
  assert.match(pursuitPanel, /const save = async/);
  assert.match(pursuitPanel, /api\.post<SaveToMyTendersResponse>/);
  assert.match(pursuitPanel, /onClick=\{save\}/);
  assert.match(pursuitPanel, /t\("panel\.save"\)/);
});

test("navigation exposes Pursuits; Bid Preparation is a route, not a menu item (D1-07)", () => {
  const navigationSource = readFileSync(
    new URL("../lib/customerNavigation.ts", import.meta.url),
    "utf8",
  );
  assert.match(layout, /CUSTOMER_NAVIGATION/);
  assert.match(navigationSource, /nameKey: 'pursuits',\s+href: '\/dashboard\/my-tenders'/);
  assert.doesNotMatch(navigationSource, /nameKey: 'bidPreparation'/);
  const english = readFileSync(
    new URL("../messages/en/navigation.json", import.meta.url),
    "utf8",
  );
  assert.match(english, /"pursuits": "Pursuits"/);
  assert.match(english, /"bidPreparation": "Bid Preparation"/);
  assert.doesNotMatch(english, /My Bids/);
});
