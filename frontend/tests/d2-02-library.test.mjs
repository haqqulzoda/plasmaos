import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { analysisCardState, sourcePursuitFor } from "../lib/analysisCard.ts";
import {
  COMPLETION_STATES,
  CSV_COLUMNS,
  IMPORT_ROW_LIMIT,
  REFERENCE_ROLES,
  VALUE_BASES,
  csvTemplate,
  cvErrors,
  cvPayload,
  emptyCvDraft,
  emptyReferenceDraft,
  ensureSelfFirm,
  expertPayload,
  isNotFound,
  libraryTab,
  listValue,
  newestFirst,
  parseCsv,
  partnerFirmPayload,
  prepareImport,
  referenceChanges,
  referenceErrors,
  referencePayload,
  runImport,
} from "../lib/library.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");
const LOCALES = ["en", "ru", "uz", "ar"];
const library = (locale) => JSON.parse(read(`messages/${locale}/pursuits.json`)).library;
const codes = (errors) => errors.map((error) => `${error.field}:${error.code}`).sort();
const draft = (values = {}) => ({ ...emptyReferenceDraft(), project_name: "Substation design", ...values });

// ---- tabs -------------------------------------------------------------------------------------------

test("tab routing: ?tab= selects a tab and anything else opens Our experience", () => {
  assert.equal(libraryTab("own"), "own");
  assert.equal(libraryTab("partners"), "partners");
  assert.equal(libraryTab("experts"), "experts");
  for (const value of [null, undefined, "", "PARTNERS", "firms"]) assert.equal(libraryTab(value), "own");
  const page = read("app/dashboard/partners-experts/page.tsx");
  assert.match(page, /libraryTab\(searchParams\.get\('tab'\)\)/);
  assert.match(page, /router\.replace\(`\$\{pathname\}\?\$\{next\.toString\(\)\}`/);
  assert.match(page, /value: 'own', label: t\('tabs\.own'\)/);
  assert.match(page, /value: 'partners', label: t\('tabs\.partners'\)/);
  assert.match(page, /value: 'experts', label: t\('tabs\.experts'\)/);
  // Rendering only reads: the library and the (404-tolerant) own firm.
  assert.match(page, /Promise\.all\(\[getLibrary\(organizationId\), getSelfFirm\(organizationId\)\]\)/);
  assert.doesNotMatch(page, /api\.(post|put|patch|delete)|saveSelfFirm|createReference/);
});

// ---- reference form validation ----------------------------------------------------------------------

test("reference validation mirrors ProjectReferenceCreateRequest", () => {
  assert.deepEqual(referenceErrors(draft()), []);
  assert.deepEqual(codes(referenceErrors(draft({ project_name: "" }))), ["project_name:required"]);
  assert.deepEqual(codes(referenceErrors(draft({ project_name: "A" }))), ["project_name:tooShort"]);
  // value and currency together; a value needs its basis
  assert.deepEqual(codes(referenceErrors(draft({ contract_value: "1000" }))),
    ["contract_currency:valueNeedsCurrency", "value_basis:valueNeedsBasis"]);
  assert.deepEqual(codes(referenceErrors(draft({ contract_currency: "USD" }))), ["contract_value:currencyNeedsValue"]);
  assert.deepEqual(codes(referenceErrors(draft({ contract_value: "1000", contract_currency: "usd", value_basis: "FIRM_SHARE" }))), []);
  assert.deepEqual(codes(referenceErrors(draft({ contract_value: "1,000,000.50", contract_currency: "USD", value_basis: "CONTRACT_TOTAL" }))), []);
  assert.deepEqual(codes(referenceErrors(draft({ contract_value: "1e5", contract_currency: "US", value_basis: "CONTRACT_TOTAL" }))),
    ["contract_currency:currencyFormat", "contract_value:number"]);
  // dates are real and ordered
  assert.deepEqual(codes(referenceErrors(draft({ start_date: "2022-05-01", completion_date: "2021-01-01" }))), ["completion_date:datesOrder"]);
  assert.deepEqual(codes(referenceErrors(draft({ start_date: "2022-02-30" }))), ["start_date:date"]);
  assert.deepEqual(codes(referenceErrors(draft({ contract_share_percent: "101" }))), ["contract_share_percent:share"]);
  assert.deepEqual(codes(referenceErrors(draft({ role: "PARTNER" }))), ["role:invalid"]);
});

test("reference payloads are normalized and edits send only what changed", () => {
  const payload = referencePayload(draft({
    client_name: "  ", contract_value: "250 000", contract_currency: "usd", value_basis: "contract total",
    role: "jv member", completion_state: "completed", evidence_state: "UNVERIFIED",
  }));
  assert.deepEqual(payload, {
    project_name: "Substation design", client_name: null, country: null, sector: null, service: null,
    role: "JV_MEMBER", contract_share_percent: null, contract_value: "250000", contract_currency: "USD",
    value_basis: "CONTRACT_TOTAL", start_date: null, completion_date: null, completion_state: "COMPLETED",
    relevant_scope: null, evidence_state: "UNVERIFIED",
  });
  const stored = { ...payload, contract_value: "250000.00" };
  assert.deepEqual(referenceChanges(stored, draft({
    contract_value: "250000", contract_currency: "USD", value_basis: "CONTRACT_TOTAL", role: "JV_MEMBER",
  })), {});
  assert.deepEqual(referenceChanges(stored, draft({
    contract_value: "250000", contract_currency: "USD", value_basis: "CONTRACT_TOTAL", role: "JV_MEMBER",
    client_name: "Grid company",
  })), { client_name: "Grid company" });
});

test("partner firms and experts created here are private; experts need no consent record", () => {
  const firm = partnerFirmPayload({
    display_name: " Grid  Partner ", legal_name: "", country: "Kazakhstan", services: "Design; design, Supervision",
    sectors: "Energy", capabilities: "", regions: "",
  });
  assert.equal(firm.scope, "ORGANIZATION_PRIVATE");
  assert.equal(firm.display_name, "Grid Partner");
  assert.equal(firm.canonical_name, "Grid Partner");
  assert.deepEqual(firm.services, ["Design", "Supervision"]);
  assert.equal(firm.evidence_state, "UNVERIFIED");
  const expert = expertPayload({ display_name: "A. Expert", qualifications: "", languages: "English; Russian", specializations: "" });
  assert.equal(expert.scope, "ORGANIZATION_PRIVATE");
  assert.equal(expert.consent_state, "NOT_REQUIRED_PRIVATE");
  assert.deepEqual(expert.languages, ["English", "Russian"]);
  assert.deepEqual(listValue("a;;b\nc, a"), ["a", "b", "c"]);
});

test("CV versions: structured rows, empty rows dropped, errors per row, history newest first", () => {
  assert.deepEqual(codes(cvErrors(emptyCvDraft())), ["cv:emptyCv"]);
  const cv = emptyCvDraft();
  cv.assignments = [
    { role: "Team Leader", client: "Utility", country: "Uzbekistan", sector: "Energy", start: "2021-03", end: "2020-01", description: "" },
    { role: "", client: "Other", country: "", sector: "", start: "", end: "", description: "" },
  ];
  cv.education = [{ degree: "MSc", institution: "TSTU", year: "20a1" }];
  assert.deepEqual(codes(cvErrors(cv)), ["assignments.0.end:datesOrder", "assignments.1.role:required", "education.0.year:year"]);
  cv.assignments = [{ role: "Team Leader", client: "Utility", country: "", sector: "", start: "2020-01", end: "2021-03", description: "" }];
  cv.education = [{ degree: "MSc", institution: "", year: "2010" }];
  assert.deepEqual(cvErrors(cv), []);
  const payload = cvPayload(cv);
  assert.deepEqual(payload.assignments, [{ role: "Team Leader", client: "Utility", start: "2020-01", end: "2021-03" }]);
  assert.deepEqual(payload.languages, []); // the blank default row is dropped
  assert.equal(payload.evidence_state, "UNVERIFIED");
  assert.deepEqual(newestFirst([{ version_number: 1 }, { version_number: 3 }, { version_number: 2 }]).map((v) => v.version_number), [3, 2, 1]);
});

// ---- CSV ---------------------------------------------------------------------------------------------

test("CSV parser handles quotes, escaped quotes, embedded commas and line breaks, CRLF and a BOM", () => {
  const rows = parseCsv('﻿a,b,c\r\n"x, y","he said ""hi""","line1\nline2"\r\n\r\n,,\n1,2,3');
  assert.deepEqual(rows, [["a", "b", "c"], ["x, y", 'he said "hi"', "line1\nline2"], ["1", "2", "3"]]);
  assert.deepEqual(parseCsv(""), []);
  assert.deepEqual(parseCsv("only\n"), [["only"]]);
});

test("templates parse back into one valid example row", () => {
  const references = prepareImport("references", csvTemplate("references"));
  assert.deepEqual(references.errors, []);
  assert.equal(references.rows.length, 1);
  assert.deepEqual(references.rows[0].errors, []);
  assert.equal(references.rows[0].payload.value_basis, "CONTRACT_TOTAL");
  const experts = prepareImport("experts", csvTemplate("experts"));
  assert.deepEqual(experts.rows[0].errors, []);
  assert.deepEqual(experts.rows[0].payload.languages, ["English", "Russian", "Uzbek"]);
  assert.deepEqual(parseCsv(csvTemplate("references"))[0], [...CSV_COLUMNS.references]);
});

test("CSV preview reports file errors and per-row errors with line numbers", () => {
  const header = CSV_COLUMNS.references.join(",");
  assert.deepEqual(codes(prepareImport("references", "").errors), ["file:emptyFile"]);
  assert.deepEqual(codes(prepareImport("references", "project_name,rating\n").errors),
    ["completion_state:missingColumn", "file:noRows", "rating:unknownColumn", "role:missingColumn"]);
  const many = [header, ...Array.from({ length: IMPORT_ROW_LIMIT + 1 }, (_, i) => `P${i} name,,,,,LEAD,,,,,,,COMPLETED,,`)].join("\n");
  assert.deepEqual(codes(prepareImport("references", many).errors), ["file:tooManyRows"]);
  const preview = prepareImport("references", [
    header,
    "Good project,,Uzbekistan,,,LEAD,,,,,2020-01-01,2021-01-01,COMPLETED,,",
    "Value without currency,,,,,LEAD,,5000,,,,,COMPLETED,,",
    "Reviewed claim,,,,,LEAD,,,,,,,COMPLETED,,REVIEWED",
    "X,,,,,BOSS,,,,,,,DONE,,",
    "Extra cells,,,,,LEAD,,,,,,,COMPLETED,,,surplus",
  ].join("\r\n"));
  assert.deepEqual(preview.errors, []);
  assert.deepEqual(preview.rows.map((row) => row.line), [2, 3, 4, 5, 6]);
  assert.deepEqual(preview.rows.map((row) => row.payload !== null), [true, false, false, false, false]);
  assert.deepEqual(codes(preview.rows[1].errors), ["contract_currency:valueNeedsCurrency", "value_basis:valueNeedsBasis"]);
  assert.deepEqual(codes(preview.rows[2].errors), ["evidence_state:reviewNotImportable"]);
  assert.deepEqual(codes(preview.rows[3].errors), ["completion_state:invalid", "project_name:tooShort", "role:invalid"]);
  assert.deepEqual(codes(preview.rows[4].errors), ["row:extraCells"]);
  assert.deepEqual(codes(prepareImport("experts", "display_name,languages\nA,English\n,Russian").rows[1].errors), ["display_name:required"]);
});

test("import posts valid rows in order, counts progress and reports every row not created", async () => {
  const preview = prepareImport("references", [
    CSV_COLUMNS.references.join(","),
    "First,,,,,LEAD,,,,,,,COMPLETED,,",
    "Invalid,,,,,LEAD,,1,,,,,COMPLETED,,",
    "Second,,,,,LEAD,,,,,,,COMPLETED,,",
    "Third,,,,,LEAD,,,,,,,COMPLETED,,",
  ].join("\n"));
  const posted = [];
  const progress = [];
  const report = await runImport(preview.rows, async (payload) => {
    posted.push(payload.project_name);
    if (payload.project_name === "Second") throw new Error("HTTP 409");
  }, (done, total) => progress.push(`${done}/${total}`));
  assert.deepEqual(posted, ["First", "Second", "Third"]);
  assert.deepEqual(progress, ["0/3", "1/3", "2/3", "3/3"]);
  assert.deepEqual(report, {
    created: 2, skipped: 1,
    failed: [{ line: 4, label: "Second", message: "HTTP 409" }],
  });
});

// ---- own firm: 404-tolerant --------------------------------------------------------------------------

test("the own firm: 404 reads as not set up; the first save creates it once, from an action only", async () => {
  assert.equal(isNotFound({ response: { status: 404 } }), true);
  assert.equal(isNotFound({ response: { status: 500 } }), false);
  assert.equal(isNotFound(new Error("network")), false);
  const calls = [];
  const deps = {
    getSelfFirm: async () => { calls.push("GET"); return null; },
    createSelfFirm: async () => { calls.push("PUT"); return { firm_id: "own-1" }; },
  };
  assert.deepEqual(await ensureSelfFirm(null, deps), { firm_id: "own-1" });
  assert.deepEqual(calls, ["GET", "PUT"]);
  calls.length = 0;
  assert.deepEqual(await ensureSelfFirm({ firm_id: "known" }, deps), { firm_id: "known" });
  assert.deepEqual(calls, []);
  const existing = { getSelfFirm: async () => { calls.push("GET"); return { firm_id: "raced" }; }, createSelfFirm: deps.createSelfFirm };
  assert.deepEqual(await ensureSelfFirm(null, existing), { firm_id: "raced" });
  assert.deepEqual(calls, ["GET"]);
  const api = read("lib/libraryApi.ts");
  assert.match(api, /if \(isNotFound\(error\)\) return null;/);
  assert.match(api, /api\.put<CandidateFirm>\('\/candidates\/self-firm'/);
  assert.match(api, /project-references\/\$\{encodeURIComponent\(referenceId\)\}\/archive/);
  assert.match(api, /api\.patch<CandidateProjectReference>/);
  const tabs = read("components/library/LibraryTabs.tsx");
  assert.match(tabs, /createSelfFirm: \(\) => saveSelfFirm\(organizationId, \{\}\)/);
});

test("Mark as reviewed confirms that it is the organization's own assertion", () => {
  const parts = read("components/library/LibraryParts.tsx");
  assert.match(parts, /t\('review\.explanation'\)/);
  assert.match(parts, /t\('review\.notVerification'\)/);
  const tabs = read("components/library/LibraryTabs.tsx");
  for (const call of [
    /saveSelfFirm\(organizationId, \{ evidence_state: 'REVIEWED' \}\)/,
    /updateFirm\(organizationId, firm\.firm_id, \{ evidence_state: 'REVIEWED' \}\)/,
    /updateExpert\(organizationId, expert\.expert_id, \{ evidence_state: 'REVIEWED' \}\)/,
    /updateReference\(organizationId, firmId, reference\.reference_id, \{ evidence_state: 'REVIEWED' \}\)/,
  ]) assert.match(tabs, call);
  for (const locale of LOCALES) {
    assert.ok(library(locale).review.notVerification.length > 40, locale);
  }
  assert.match(library("en").review.notVerification, /Plasma has not verified/);
});

test("every library message exists in all four locales, including enum and error labels", () => {
  const flatten = (node, prefix = "") => Object.entries(node).flatMap(([key, value]) =>
    typeof value === "object" ? flatten(value, `${prefix}${key}.`) : [`${prefix}${key}`]);
  const keys = flatten(library("en")).sort();
  for (const locale of LOCALES) assert.deepEqual(flatten(library(locale)).sort(), keys, locale);
  const errorCodes = [...read("lib/library.ts").matchAll(/code: '([A-Za-z]+)'/g)].map((match) => match[1]);
  for (const locale of LOCALES) {
    const messages = library(locale);
    for (const role of REFERENCE_ROLES) assert.ok(messages.roles[role], `${locale} role ${role}`);
    for (const basis of VALUE_BASES) assert.ok(messages.valueBases[basis], `${locale} basis ${basis}`);
    for (const state of COMPLETION_STATES) assert.ok(messages.completion[state], `${locale} completion ${state}`);
    for (const code of new Set(errorCodes)) assert.ok(messages.errors[code], `${locale} error ${code}`);
    for (const column of [...CSV_COLUMNS.references, ...CSV_COLUMNS.experts, "file", "row"]) {
      assert.ok(messages.fields[column], `${locale} field ${column}`);
    }
  }
  assert.equal(library("en").tabs.own, "Our experience");
  assert.equal(library("en").tabs.partners, "Partner firms");
  assert.equal(library("en").tabs.experts, "Experts");
});

// ---- demo polish -------------------------------------------------------------------------------------

test("dashboard: legacy widgets gone, Your pursuits added, Browse opportunities, Company & Experience", () => {
  const page = read("app/dashboard/page.tsx");
  assert.doesNotMatch(page, /actionTitle|analysesTitle|latest-analysis|dashboard-attention|dashboard-analyses/);
  assert.match(page, /t\("pursuitsTitle"\)/);
  assert.doesNotMatch(page, /readiness-vault/);
  assert.match(page, /href="\/dashboard\/settings"/);
  for (const locale of LOCALES) {
    const dashboard = JSON.parse(read(`messages/${locale}/dashboard.json`));
    assert.ok(dashboard.pursuitsTitle && dashboard.pursuitsEmpty && dashboard.openWorkspace, locale);
  }
  const en = JSON.parse(read("messages/en/dashboard.json"));
  assert.equal(en.openExplorer, "Browse opportunities");
  assert.equal(en.readinessTitle, "Company & Experience");
  assert.equal(JSON.parse(read("messages/en/explorer.json")).title, "Opportunities");
  assert.doesNotMatch(JSON.parse(read("messages/ru/myTenders.json")).sort, /Моих тендеров/);
});

test("Tender Details: Analysis card, no Bid Preparation strip, no Readiness Vault link", () => {
  const page = read("app/dashboard/tenders/[tenderId]/page.tsx");
  assert.doesNotMatch(page, /id="bid-preparation"|openReadiness|readiness-vault|complianceTitle/);
  assert.match(page, /<PursuitAnalysisCard tenderId=\{tender\.id\}/);
  assert.equal(analysisCardState(null).kind, "none");
  assert.equal(analysisCardState({ status: "RUNNING" }).kind, "running");
  assert.equal(analysisCardState({ status: "FAILED" }).kind, "failed");
  assert.deepEqual(analysisCardState({
    status: "COMPLETED", completed_at: "2026-09-30T10:00:00Z",
    requirements: [{ effective_coverage_state: "EVIDENCE_MISSING" }, { effective_coverage_state: "PARTIAL" }],
    positions: [{}], gaps: [{}, {}], submission_and_notes: [{}],
  }), {
    kind: "ready", requirements: 2, positions: 1, gaps: 2, evidenceMissing: 1, notes: 1,
    completedAt: "2026-09-30T10:00:00Z",
  });
  const pursuits = [
    { pursuit_id: "u", origin: "UPLOAD", source_tender_id: null },
    { pursuit_id: "s", origin: "SOURCE", source_tender_id: "t-1" },
  ];
  assert.equal(sourcePursuitFor(pursuits, "t-1")?.pursuit_id, "s");
  assert.equal(sourcePursuitFor(pursuits, "t-2"), null);
});

test("shell has no duplicate Settings link; workspace keeps admission detail in technical details", () => {
  const shell = read("components/shell/CustomerShell.tsx");
  assert.equal((shell.match(/href="\/dashboard\/settings"/g) || []).length, 1);
  const requirements = read("components/pursuits/PursuitRequirements.tsx");
  assert.match(requirements, /<summary>\{t\('technicalDetails'\)\}<\/summary>[^\n]*analysis\.limit_disclosure/);
  assert.doesNotMatch(requirements, /<h3>\{t\('summary'\)\}<\/h3><p>\{analysis\.limit_disclosure\}/);
  assert.equal(JSON.parse(read("messages/en/pursuits.json")).workspace.reviewRequirementsGaps, "Review requirements");
});
