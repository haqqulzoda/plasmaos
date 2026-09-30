import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const read = (path) =>
  readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const bidDetail = read("app/dashboard/bid-preparation/[proposalId]/page.tsx");
const tenderDetail = read("app/dashboard/tenders/[tenderId]/page.tsx");
const compliance = read("app/dashboard/tenders/[tenderId]/compliance/page.tsx");
const myTenders = read("app/dashboard/my-tenders/page.tsx");
const layout = read("app/dashboard/layout.tsx") + read("components/shell/CustomerShell.tsx") + read("lib/customerNavigation.ts");
const legacyBidList = read("app/dashboard/bids/page.tsx");
const legacyBidDetail = read("app/dashboard/bids/[id]/page.tsx");
const legacyProposals = read("app/dashboard/proposals/page.tsx");
const legacyWorkspace = read("app/dashboard/workspace/page.tsx");
const tenderTypes = read("types/tender.ts");

test("dead workspace and duplicate Tender components are removed", () => {
  for (const path of [
    "../components/workspace/TenderWorkspace.tsx",
    "../components/workspace/StrategyPanel.tsx",
    "../components/workspace/HighlightedText.tsx",
    "../components/tenders/SaveToMyTendersButton.tsx",
    "../components/tenders/ProjectContextSection.tsx",
  ]) {
    assert.equal(
      existsSync(new URL(path, import.meta.url)),
      false,
      `${path} should be absent`,
    );
  }
});

test("legacy lists and workspace are permanent read-only redirects", () => {
  assert.match(
    legacyBidList,
    /permanentRedirect\('\/dashboard\/bid-preparation'\)/,
  );
  assert.match(
    legacyProposals,
    /permanentRedirect\('\/dashboard\/bid-preparation'\)/,
  );
  assert.match(legacyWorkspace, /permanentRedirect\('\/dashboard\/tenders'\)/);
  assert.doesNotMatch(
    `${legacyBidList}\n${legacyProposals}\n${legacyWorkspace}`,
    /api\.|fetch\(|post\(|put\(|patch\(|delete\(/i,
  );
});

test("legacy bid detail validates only an owned Proposal ID", () => {
  assert.match(legacyBidDetail, /api\.get\(`\/proposals\/\$\{id\}`\)/);
  assert.match(
    legacyBidDetail,
    /router\.replace\(`\/dashboard\/bid-preparation\/\$\{id\}`\)/,
  );
  assert.doesNotMatch(
    legacyBidDetail,
    /\/tenders\/|tender_id|api\.post|api\.put|api\.patch|api\.delete/,
  );
});

test("Bid Preparation passive effects read persisted state and never synchronize", () => {
  assert.match(
    bidDetail,
    /api\.get<Proposal>\(\s*`\/proposals\/\$\{resolvedParams\.proposalId\}`,?\s*\)/,
  );
  assert.match(bidDetail, /api\.get\(["']\/vault["']\)/);
  assert.match(
    bidDetail,
    /api\.get<TenderDocument\[\]>\(\s*`\/tenders\/\$\{tenderId\}\/documents`,?\s*\)/,
  );
  assert.doesNotMatch(
    bidDetail,
    /sync-docs|sync-status|pollTenderDocumentSync|TenderDocsSyncResponse|TenderSyncStatusResponse/,
  );
});

test("Bid Preparation mutations remain explicit event handlers", () => {
  for (const handler of [
    "handleGenerateStrategicProposal",
    "handleSave",
    "handleGeneratePdf",
    "handleGenerateDocx",
  ]) {
    assert.match(bidDetail, new RegExp(`const ${handler} = async`));
  }
  assert.doesNotMatch(
    bidDetail,
    /useEffect\([\s\S]{0,500}api\.(post|put|patch|delete)/,
  );
});

test("canonical cross-surface links use the correct identifiers", () => {
  assert.match(bidDetail, /`\/dashboard\/tenders\/\$\{proposal\.tender_id\}`/);
  // D1-06: Tender Details leads to the pursuit workspace, not to Bid Preparation or compliance.
  assert.doesNotMatch(tenderDetail, /\/dashboard\/bid-preparation\/|\/compliance`/);
  assert.match(tenderDetail, /<OpenWorkspaceButton tenderId=\{tender\.id\}/);
  assert.match(compliance, /`\/dashboard\/tenders\/\$\{tenderId\}`/);
  assert.match(myTenders, /`\/dashboard\/tenders\/\$\{item\.tender_id\}`/);
});

test("canonical navigation and runtime copy omit obsolete product terminology", () => {
  const navigation = read("messages/en/navigation.json");
  const runtime = `${layout}\n${navigation}\n${bidDetail}\n${tenderDetail}\n${compliance}\n${myTenders}`;
  assert.match(layout, /nameKey: 'opportunities'/);
  assert.match(layout, /nameKey: 'pursuits'/);
  assert.doesNotMatch(layout, /nameKey: 'bidPreparation'/);
  assert.match(navigation, /"opportunities": "Opportunities"/);
  assert.match(navigation, /"pursuits": "Pursuits"/);
  assert.doesNotMatch(
    runtime,
    /My Bids|Tender Workspace|Tender Draft|Draft Tender|Submit Bid|Submit Tender|Fully compliant|Ready %/,
  );
});

test("dead Decision Snapshot contracts stay removed while competitors use the details DTO", () => {
  assert.doesNotMatch(
    tenderTypes,
    /TenderDecisionSnapshot|TenderCompetitor|competitorStatusLabel|competitorConfidence|competitorParticipation/,
  );
  assert.doesNotMatch(tenderDetail, /decision-snapshot|\/competitors/);
  assert.match(tenderDetail, /details\.competitor_intelligence/);
});

test("Tender Details exposes the new decision-and-evidence sections without redundant anchor tabs", () => {
  for (const id of ["project-context", "project-leadership", "tender-documents", "competitors", "contacts", "bid-preparation"]) {
    assert.match(tenderDetail, new RegExp(`id="${id}"`));
  }
  assert.match(tenderDetail, /decisionCard tenderId=\{tender\.id\}/);
  assert.doesNotMatch(tenderDetail, /details-anchors/);
});
