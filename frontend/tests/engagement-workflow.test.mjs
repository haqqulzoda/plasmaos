import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  engagementStatusDescription,
  engagementStatusLabel,
} from "../types/engagement.ts";

const read = (path) =>
  readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const actions = read("components/tenders/EngagementWorkflowActions.tsx");
const panel = read("components/tenders/TenderEngagementPanel.tsx");
const myTenders = read("app/dashboard/my-tenders/page.tsx");
const tenderDetail = read("app/dashboard/tenders/[tenderId]/page.tsx");
const preparation = read("app/dashboard/bid-preparation/[proposalId]/page.tsx");

test("every canonical status has concise non-color meaning", () => {
  for (const status of [
    "SAVED",
    "EVALUATING",
    "PREPARING",
    "SUBMITTED",
    "WON",
    "LOST",
    "DISMISSED",
  ]) {
    assert.ok(engagementStatusLabel(status));
    assert.match(engagementStatusDescription(status), /\.$/);
  }
});

test("high-significance actions use confirmation and exact semantics", () => {
  assert.match(actions, /role="dialog"/);
  assert.match(actions, /aria-modal="true"/);
  assert.match(actions, /t\("markSubmitted"\)/);
  assert.match(actions, /t\("submittedConfirm"\)/);
  assert.match(actions, /t\("recordWon"\)/);
  assert.match(actions, /t\("recordLost"\)/);
  assert.match(actions, /t\("correctPreparing"\)/);
  assert.doesNotMatch(actions, /Submit Bid|Submit Tender/);
});

test("commands send expected state and refresh authoritative backend truth", () => {
  assert.match(actions, /expected_status: engagement\.engagement_status/);
  assert.match(actions, /t\("statusChanged"\)/);
  assert.match(actions, /await onRefresh\?\.\(\)/);
  assert.match(myTenders, /setRefreshVersion/);
});

test("Tender Details and Bid Preparation share the compact pursuit panel", () => {
  assert.match(
    tenderDetail,
    /<TenderEngagementPanel[\s\S]{0,120}tenderId=\{tender\.id\}/,
  );
  assert.match(
    preparation,
    /<TenderEngagementPanel[\s\S]{0,120}tenderId=\{proposal\.tender_id\}[\s\S]{0,80}proposalContext/,
  );
  assert.match(panel, /t\("panel\.openMy"\)/);
  assert.match(panel, /t\("panel\.openBid"\)/);
});

test("legacy proposal is continued only by explicit click", () => {
  const effect = panel.split("useEffect", 2)[1].split("const save", 1)[0];
  assert.doesNotMatch(effect, /api\.post/);
  assert.match(panel, /proposalId=\{proposalId\}/);
});

test("source and engagement semantics remain independent", () => {
  assert.match(myTenders, /t\("engagement", \{\s*status: engagementLabel/);
  assert.match(myTenders, /t\("tender", \{ status: tenderLabel \}\)/);
  assert.doesNotMatch(
    actions,
    /tender_status|deadline|ProposalArtifactStatus|compliance/i,
  );
});
