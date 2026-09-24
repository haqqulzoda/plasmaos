import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const page = readFileSync(
  new URL("../app/dashboard/tenders/[tenderId]/compliance/page.tsx", import.meta.url),
  "utf8",
);
const css = readFileSync(new URL("../components/customer/pages.css", import.meta.url), "utf8");
const report = readFileSync(
  new URL("../../docs/S14_4_COMPLIANCE_ANALYSIS_UI_UX_REFINEMENT.md", import.meta.url),
  "utf8",
);
const locales = ["en", "uz", "ru", "ar"];
const catalogs = Object.fromEntries(
  locales.map((locale) => [
    locale,
    JSON.parse(
      readFileSync(new URL(`../messages/${locale}/compliance.json`, import.meta.url), "utf8"),
    ),
  ]),
);

test("the pre-implementation ledger separates canonical, supported, and omitted concepts", () => {
  assert.match(report, /\| Related requirements \|[^\n]+\| UNSUPPORTED \|/);
  assert.match(report, /\| Notes \|[^\n]+\| UNSUPPORTED \|/);
  assert.match(report, /Current AnalysisVersion[\s\S]*SUPPORTED/);
  assert.match(report, /does not alter the Compliance engine/);
});

test("the workspace groups canonical engine arrays without inventing a severity score", () => {
  for (const field of [
    "failed_dealbreakers",
    "manual_reviews_required",
    "satisfied_requirements",
    "recorded_obligations",
  ]) {
    assert.match(page, new RegExp(`hybridCompliance\\.${field}`));
  }
  assert.doesNotMatch(page, /riskScore|compliancePercentage|severityScore/);
});

test("search, status, category, and source filters operate on loaded requirement data", () => {
  assert.match(page, /const \[searchQuery, setSearchQuery\]/);
  assert.match(page, /const \[statusFilter, setStatusFilter\]/);
  assert.match(page, /const \[categoryFilter, setCategoryFilter\]/);
  assert.match(page, /const \[documentFilter, setDocumentFilter\]/);
  assert.match(page, /group\.items\.filter\(\(detail\)/);
  assert.match(page, /resetFilters/);
});

test("source evidence is rendered before generated analysis and source bytes require an explicit action", () => {
  const inspector = page.slice(page.indexOf("function EvidenceInspector"), page.indexOf("function verdictTone"));
  assert.ok(inspector.indexOf("compliance-evidence-block") < inspector.indexOf("compliance-analysis-block"));
  assert.match(inspector, /href=\{documentUrl\}/);
  assert.doesNotMatch(inspector, /fetch\(documentUrl/);
});

test("desktop inspector and narrow drawer are both present with logical responsive CSS", () => {
  assert.match(page, /className="compliance-context"/);
  assert.match(page, /<Drawer[\s\S]*?open=\{contextOpen\}/);
  assert.match(css, /@media \(min-width: 1200px\)[\s\S]*?\.compliance-context[\s\S]*?position: sticky/);
  assert.match(css, /border-inline-start|padding-inline|margin-inline/);
});

test("immutable version, language, export, and audited override paths remain wired", () => {
  assert.match(page, /analyses\/\$\{analysisId\}\/versions/);
  assert.match(page, /selectedAnalysisLanguage/);
  assert.match(page, /exportQuery\.set\("analysis_id", analysisId\)/);
  assert.match(page, /exportQuery\.set\("version_number"/);
  assert.match(page, /\/tenders\/\$\{tenderId\}\/override/);
});

test("unsupported notes and related-link persistence are not introduced", () => {
  assert.doesNotMatch(page, /localStorage|sessionStorage/);
  assert.doesNotMatch(page, /relatedRequirements|saveNote|linkReadinessRecord/);
  assert.match(page, /href="\/dashboard\/readiness-vault"/);
});

test("the redesigned workspace message contract is complete in all four locales", () => {
  const englishKeys = Object.keys(catalogs.en.workspace).sort();
  assert.ok(englishKeys.length >= 30);
  for (const locale of locales) {
    assert.deepEqual(Object.keys(catalogs[locale].workspace).sort(), englishKeys);
    assert.ok(catalogs[locale].workspace.beta);
    assert.ok(catalogs[locale].workspace.sourceEvidenceLabel);
    assert.ok(catalogs[locale].workspace.plasmaAnalysisLabel);
  }
});
