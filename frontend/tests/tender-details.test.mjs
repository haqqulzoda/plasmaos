import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const page = read("../app/dashboard/tenders/[tenderId]/page.tsx");
const panel = read("../components/tenders/TenderEngagementPanel.tsx");
const dto = read("../types/tender-details.ts");
const css = read("../components/customer/pages.css");
const messages = Object.fromEntries(["en", "uz", "ru", "ar"].map((locale) => [
  locale, JSON.parse(read(`../messages/${locale}/tenderDetails.json`)),
]));

test("initial detail load is exactly two composed passive reads", () => {
  assert.match(page, /api\.get<Tender>\(`\/tenders\/\$\{tenderId\}`\)/);
  assert.match(page, /api\.get<TenderDetailsResponse>\(`\/tenders\/\$\{tenderId\}\/details`\)/);
  assert.equal((page.match(/api\.get</g) ?? []).length, 3); // third is bounded acquisition-status polling
  assert.match(page, /if \(!activeAcquisitionState\(acquisitionState\) \|\| !acquisitionJobId\) return/);
  assert.match(page, /attempts < 150/);
  assert.doesNotMatch(page, /decision-snapshot|`\/tenders\/\$\{tenderId\}\/competitors`|`\/tenders\/\$\{tenderId\}\/project`/);
});

test("decision-first hierarchy follows mockup without legacy tabs or description", () => {
  const order = [
    "decisionCard tenderId={tender.id}", 'id="s143-compliance-title"',
    'id="s143-recommendation-title"', 'id="project-context"',
    'id="project-leadership"', 'id="tender-documents"',
    'id="competitors"', 'id="contacts"', 'id="bid-preparation"',
  ];
  let cursor = -1;
  for (const marker of order) {
    const next = page.indexOf(marker);
    assert.ok(next > cursor, `${marker} must be present and ordered`);
    cursor = next;
  }
  assert.doesNotMatch(page, /details-anchors|tender\.description/);
});

test("Explorer return state and source URL stay safe", () => {
  assert.match(page, /readExplorerReturnState\(\)/);
  assert.match(page, /href=\{returnHref\}/);
  assert.match(page, /safeSourceUrl\(tender\.source_url\)/);
  assert.match(page, /rel="noopener noreferrer"/);
});

test("pursuit remains TenderEngagement with explicit actions", () => {
  assert.match(page, /engagementData=\{pursuit\}/);
  assert.match(page, /canStartNew=\{actionable\}/);
  assert.match(panel, /decisionCard/);
  assert.match(panel, /api\.post<SaveToMyTendersResponse>/);
  assert.match(panel, /EngagementWorkflowActions/);
  assert.match(dto, /allowed_actions: EngagementAction\[\]/);
});

test("Compliance and readiness use separate facts without invented percentages", () => {
  assert.match(page, /details\.compliance\.state/);
  assert.match(page, /details\.company_readiness\.state/);
  assert.match(page, /complianceFailed/);
  assert.match(page, /compliancePartial/);
  assert.match(page, /complianceLegacy/);
  assert.match(page, /readiness\.readiness_documents_missing/);
  assert.match(page, /\/dashboard\/readiness-vault/);
  assert.doesNotMatch(page, /readiness_score|readiness_percentage|critical records/i);
});

test("recommendation is stored-only and never generated on page load", () => {
  assert.match(page, /details\.recommendation\.match_score/);
  assert.match(page, /details\.recommendation\.rationale_summary/);
  assert.match(page, /copy\("noRecommendation"\)/);
  assert.doesNotMatch(page, /api\.post.*recommendation|generateRecommendation/);
});

test("Project Context exposes only canonical DTO fields", () => {
  assert.match(page, /project\.name/);
  assert.match(page, /project\.project_status/);
  assert.match(page, /project\.country/);
  assert.match(page, /project\.approval_date/);
  assert.doesNotMatch(page, /project\.objective|project\.sector|enrichProject/);
});

test("Project Leadership is names-only and separate from contacts", () => {
  assert.match(page, /s143\.leadershipSource/);
  assert.match(page, /role\.display_name/);
  assert.match(page, /id="project-leadership"/);
  assert.match(page, /id="contacts"/);
  assert.doesNotMatch(page, /leadershipRoleLabel|role\.native_role|role\.canonical_role/);
});

test("documents retain one explicit bulk acquisition command and bounded poller", () => {
  assert.match(page, /api\.post<DocumentSyncAccepted>\(`\/tenders\/\$\{tenderId\}\/sync-docs`\)/);
  assert.match(page, /onClick=\{\(\) => void acquireDocuments\(\)\}/);
  assert.match(page, /attempts < 150/);
  assert.equal((page.match(/api\.post</g) ?? []).length, 1);
  assert.doesNotMatch(page, /api\.(put|patch|delete)/);
});

test("per-row binary download is available only for READY local files", () => {
  assert.match(page, /item\.availability !== "AVAILABLE" \|\| item\.acquisition_state !== "READY"/);
  assert.match(page, /item\.availability === "AVAILABLE" && item\.acquisition_state === "READY"/);
  assert.match(page, /`\/tenders\/documents\/\$\{item\.document_id\}\/download`/);
  assert.match(page, /onClick=\{\(\) => void openDocument\(item\)\}/);
  assert.doesNotMatch(page, /useEffect\([\s\S]{0,250}openDocument/);
});

test("requirements retain bounded analysis-derived provenance in disclosure", () => {
  assert.match(page, /<details className="s143-disclosure">/);
  assert.match(page, /t\("aiRequirement"\)/);
  assert.match(page, /requirements\?\.truncated/);
  assert.match(page, /item\.document_name/);
});

test("competitors use the stored composed DTO and safe evidence links", () => {
  assert.match(dto, /competitor_intelligence: DetailsSection<TenderDetailsCompetitorIntelligence>/);
  assert.match(page, /competitor_intelligence\.data\?\.groups\.flatMap/);
  assert.match(page, /item\.participation_type/);
  assert.match(page, /t\("s143\.whyRelevant"\)/);
  assert.match(page, /<BidiText>\{item\.reason\}<\/BidiText>/);
  assert.match(dto, /INSUFFICIENT_EVIDENCE/);
  assert.match(page, /safeSourceUrl\(item\.evidence_source\)/);
  assert.match(page, /details\.competitor_intelligence\.state/);
  assert.match(page, /competitorsEmpty/);
  assert.match(page, /competitorsUnavailable/);
  assert.doesNotMatch(page, /current bidder|confirmed competitor|market share/i);
});

test("contacts are source-backed and Proposal action remains explicit", () => {
  assert.match(page, /contacts\.contact_person/);
  assert.match(page, /contacts\.address/);
  assert.match(page, /contacts\.submission_method/);
  assert.match(page, /`\/dashboard\/bid-preparation\/\$\{bidPreparation\.detail_route_id\}`/);
  assert.match(page, /<PrepareBidButton foundation tenderId=\{tender\.id\}/);
});

test("section-level loading, failures and previous successful data are retained", () => {
  assert.match(page, /<SectionPlaceholder/);
  assert.match(page, /setDetailsError\("detailsFailed"\)/);
  assert.match(page, /Retain a previously successful composed projection/);
  assert.match(page, /role="alert"/);
  assert.match(page, /<StateMessage/);
});

test("responsive tables degrade to stacked rows without page overflow", () => {
  assert.match(css, /\.s143-table-wrap[^}]*overflow-x: auto/);
  assert.match(css, /@media \(max-width: 559px\)/);
  assert.match(css, /\.s143-document-table td::before/);
  assert.match(css, /\.s143-project-grid/);
});

test("EN, UZ, RU and AR have exact Sprint 14.3 copy parity", () => {
  const keys = Object.keys(messages.en.s143).sort();
  for (const locale of ["en", "uz", "ru", "ar"]) {
    assert.deepEqual(Object.keys(messages[locale].s143).sort(), keys);
    assert.ok(messages[locale].competitorsHelp);
    assert.ok(messages[locale].competitorParticipation.winner);
  }
  assert.notEqual(messages.ar.s143.leadershipSource, messages.en.s143.leadershipSource);
});
