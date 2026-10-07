import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  addressedBy,
  builderErrors,
  downloadFilename,
  draftRequest,
  eoiRunId,
  experienceRows,
  initialBuilderState,
  partnerCoversUncovered,
  setPartnerRole,
  staleReasonKey,
  toggleOwn,
  togglePartner,
  togglePartnerReference,
  uncoveredByOwn,
  withoutLaterStage,
} from "../lib/eoiBuilder.ts";
import {
  bulkConfirmPlan,
  defaultBulkReason,
  gapsByRequirement,
  groupRequirements,
  pursuitDisplayTitle,
  referenceNames,
  runSequential,
} from "../lib/requirementsReview.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");
const LOCALES = ["en", "ru", "uz", "ar"];

// ---- contract mock (shape of GET /pursuits/{id}/eoi/suggestions) -----------------------------------

function reference(id, rank, matched, values = {}) {
  return {
    reference_id: id, project_name: `Project ${id}`, client_name: "Client", country: "Mongolia", sector: "Energy",
    service: "Design", role: "LEAD", contract_share_percent: null, contract_value: null, contract_currency: null,
    value_basis: "UNKNOWN", start_date: "2020-01-01", completion_date: "2022-01-01", completion_state: "COMPLETED",
    relevant_scope: "Substation design", evidence_state: "UNVERIFIED", evidence_basis: "METADATA_ONLY",
    matched_requirement_ids: matched, suggested: matched.length > 0, rank, ...values,
  };
}

const SUGGESTIONS = {
  analysis_run_id: "run-1", run_current: true,
  defaults: {
    assignment_title: "LOT-4 Detailed design", reference_no: "OP00468882", addressee_organization: "Ministry of Energy",
    addressee_name: "M. Purevsuren", addressee_email: "m@energy.gov.mn", firm_name: "Codex LLC", firm_country: "Uzbekistan",
  },
  criteria: [
    { requirement_id: "c1", statement: "Two contracts in substation design", original_quote: "q1",
      locator: { page_number: null, paragraph_number: 3 }, effective_coverage_state: "PARTIAL", matched_reference_ids: ["r1", "r2"] },
    { requirement_id: "c2", statement: "Experience in Mongolia", original_quote: "q2",
      locator: { page_number: 2, paragraph_number: null }, effective_coverage_state: "EVIDENCE_MISSING", matched_reference_ids: [] },
    { requirement_id: "c3", statement: "Valid licenses", original_quote: "q3",
      locator: { page_number: null, paragraph_number: null }, effective_coverage_state: "EVIDENCE_MISSING", matched_reference_ids: [] },
  ],
  notes: [{ requirement_id: "n1", note_kind: "SUBMISSION_INSTRUCTION", statement: "Deliver by e-mail", original_quote: "q4" }],
  own_references: [
    reference("r2", 2, ["c1"]),
    reference("r1", 1, ["c1"]),
    reference("r3", 3, []),
  ],
  partner_firms: [
    { firm_id: "p1", display_name: "Grid Partner", country: "Kazakhstan", covers_requirement_ids: ["c1", "c2"],
      references: [reference("pr1", 1, ["c1", "c2"]), reference("pr2", 2, [])] },
    { firm_id: "p2", display_name: "Water Partner", country: null, covers_requirement_ids: [], references: [] },
  ],
};

test("initial state pre-checks suggested references in rank order and prefills the letter", () => {
  const state = initialBuilderState(SUGGESTIONS, {
    profile: { director_name: " A. Director ", phone_contact: "+998 71", address: "Tashkent" }, email: "me@codex.uz", uiLocale: "ru",
  });
  assert.deepEqual(state.own, ["r1", "r2"]);
  assert.deepEqual(state.partners, {});
  assert.equal(state.language, "ru");
  assert.equal(state.includeNotes, true);
  assert.deepEqual(state.letter, {
    addressee_organization: "Ministry of Energy", addressee_name: "M. Purevsuren", signatory_name: "A. Director",
    signatory_title: "", contact_email: "me@codex.uz", contact_phone: "+998 71", contact_address: "Tashkent",
  });
  assert.equal(initialBuilderState(SUGGESTIONS, { uiLocale: "uz" }).language, "en");
});

test("addressed-by numbers follow the backend row order and update with every selection", () => {
  let state = initialBuilderState(SUGGESTIONS);
  assert.deepEqual(experienceRows(SUGGESTIONS, state).map((row) => [row.no, row.reference.reference_id]), [[1, "r1"], [2, "r2"]]);
  assert.deepEqual(Object.fromEntries(addressedBy(SUGGESTIONS, state)), { c1: [1, 2], c2: [], c3: [] });
  state = toggleOwn(state, "r1", false);
  assert.deepEqual(Object.fromEntries(addressedBy(SUGGESTIONS, state)), { c1: [1], c2: [], c3: [] });
  assert.deepEqual(uncoveredByOwn(SUGGESTIONS, state).map((item) => item.requirement_id), ["c2", "c3"]);
  assert.deepEqual(partnerCoversUncovered(SUGGESTIONS, state, "p1"), ["c2"]);
  state = togglePartner(state, "p1", true);
  state = setPartnerRole(state, "p1", "SUBCONSULTANT");
  state = togglePartnerReference(state, "p1", "pr1", true);
  assert.deepEqual(experienceRows(SUGGESTIONS, state).map((row) => [row.no, row.reference.reference_id, row.firmId]),
    [[1, "r2", null], [2, "pr1", "p1"]]);
  assert.deepEqual(Object.fromEntries(addressedBy(SUGGESTIONS, state)), { c1: [1, 2], c2: [2], c3: [] });
  state = togglePartnerReference(state, "p1", "pr1", false);
  state = togglePartner(state, "p1", false);
  assert.deepEqual(state.partners, {});
});

test("the request matches the contract and the client checks the same limits", () => {
  let state = initialBuilderState(SUGGESTIONS, { email: "me@codex.uz" });
  assert.deepEqual(builderErrors(state).map((item) => `${item.field}:${item.code}`), [
    "signatory_name:required", "signatory_title:required",
  ]);
  state = { ...state, letter: { ...state.letter, signatory_name: "A. Signer", signatory_title: "Director", contact_phone: "  ", addressee_name: "" } };
  state = togglePartnerReference(setPartnerRole(togglePartner(state, "p1", true), "p1", "JV_MEMBER"), "p1", "pr2", true);
  assert.deepEqual(builderErrors(state), []);
  assert.deepEqual(draftRequest(SUGGESTIONS, state), {
    analysis_run_id: "run-1", language: "en", own_reference_ids: ["r1", "r2"],
    partners: [{ firm_id: "p1", role: "JV_MEMBER", reference_ids: ["pr2"] }],
    letter: {
      addressee_organization: "Ministry of Energy", addressee_name: null, signatory_name: "A. Signer",
      signatory_title: "Director", contact_email: "me@codex.uz", contact_phone: null, contact_address: null,
    },
    include_relevance_notes: true,
  });
  const empty = { ...state, own: [], letter: { ...state.letter, contact_email: "nope" } };
  assert.deepEqual(builderErrors(empty).map((item) => item.code), ["ownRequired", "email"]);
  const crowded = { ...state, own: Array.from({ length: 31 }, (_, i) => `x${i}`) };
  assert.ok(builderErrors(crowded).some((item) => item.code === "ownTooMany"));
});

test("the EOI uses the latest COMPLETED run; stale reasons map to known labels", () => {
  assert.equal(eoiRunId({ analysis_run_id: "a", status: "RUNNING" }, { analysis_run_id: "b", status: "COMPLETED" }), "b");
  assert.equal(eoiRunId(null, undefined), null);
  for (const reason of ["NEWER_ANALYSIS_RUN", "ANALYSIS_INPUTS_CHANGED", "REFERENCE_SUPERSEDED", "REFERENCE_ARCHIVED"]) {
    assert.equal(staleReasonKey(reason), reason);
  }
  assert.equal(staleReasonKey("SOMETHING_NEW"), "OTHER");
  for (const locale of LOCALES) {
    const eoi = JSON.parse(read(`messages/${locale}/pursuits.json`)).eoi;
    for (const key of ["NEWER_ANALYSIS_RUN", "ANALYSIS_INPUTS_CHANGED", "REFERENCE_SUPERSEDED", "REFERENCE_ARCHIVED", "OTHER"]) {
      assert.ok(eoi.staleReasons[key], `${locale} ${key}`);
    }
  }
});

test("the EOI tab reads passively; generation is a click, never an effect", () => {
  const component = read("components/pursuits/PursuitEoi.tsx");
  assert.match(component, /api\.get<EoiSuggestions>\(`\$\{base\}\/eoi\/suggestions`, \{ headers, params: \{ analysis_run_id: runId \} \}\)/);
  assert.match(component, /api\.post<EoiDraft>\(`\$\{base\}\/eoi-drafts`, draftRequest\(suggestions, state\)/);
  // The only write is inside the Generate click handler.
  assert.equal((component.match(/api\.post/g) || []).length, 1);
  const generate = component.indexOf("const generate = async");
  assert.ok(generate > 0 && component.indexOf("api.post") > generate);
  assert.ok(component.indexOf("api.post") < component.indexOf("const download = async"));
  assert.match(component, /eoi-artifacts\/\$\{artifact\.artifact_id\}\/download/);
  assert.match(component, /staleReasons\.\$\{staleReasonKey\(reason\)\}/);
  assert.match(component, /href="\/dashboard\/partners-experts\?tab=own"/);
  const page = read("app/dashboard/pursuits/[pursuitId]/page.tsx");
  assert.match(page, /WORKSPACE_TABS = \['overview', 'requirements', 'eoi', 'team', 'documents', 'proposal'\]/);
  assert.match(page, /runId=\{eoiRunId\(analysis, lastReviewableAnalysis\)\}/);
});

// ---- Requirements screen ----------------------------------------------------------------------------

function requirement(id, state, values = {}) {
  return {
    requirement_id: id, pack_item_id: "p", original_quote: `quote ${id}`, source_context: null,
    normalized_requirement: id, effective_normalized_requirement: `statement ${id}`, category: "C", requirement_type: "T",
    stage_scope: "S", distinction: "MANDATORY", predicate: null, contribution_rule: null, coverage_state: state,
    effective_coverage_state: state, review_state: "PROVISIONAL", effective_review_state: "PROVISIONAL",
    source_locator: { paragraph_number: 1 }, generated_interpretation: null, ...values,
  };
}

test("one grouped list: every requirement once, notes from submission_and_notes", () => {
  const analysis = {
    requirements: [
      requirement("a", "EVIDENCE_MISSING"), requirement("b", "GAP"), requirement("c", "NEEDS_INTERPRETATION"),
      requirement("d", "PARTIAL", { matched_reference_ids: ["r1"] }), requirement("e", "LATER_STAGE_OBLIGATION"),
      requirement("f", "SUPPORTED"), requirement("n", "EVIDENCE_MISSING"),
    ],
    submission_and_notes: [{ ...requirement("n", "NOT_APPLICABLE"), note_kind: "SUBMISSION_INSTRUCTION" }],
  };
  const groups = groupRequirements(analysis);
  assert.deepEqual(Object.fromEntries(Object.entries(groups).map(([key, items]) => [key, items.map((item) => item.requirement_id)])), {
    attention: ["a", "b", "c"], partial: ["d"], notes: ["n"], later: ["e"], settled: ["f"],
  });
  const all = Object.values(groups).flat().map((item) => item.requirement_id);
  assert.equal(new Set(all).size, all.length);
  assert.deepEqual(groupRequirements(null).attention, []);
  assert.deepEqual(referenceNames(["r1", "old"], new Map([["r1", "Navoi substation"]])), { names: ["Navoi substation"], unresolved: 1 });
  const source = read("components/pursuits/PursuitRequirements.tsx");
  assert.doesNotMatch(source, /currentGaps|analysis-current-gaps/); // the second, repeated listing is gone
  assert.match(source, /<blockquote className="analysis-quote">/);
  assert.doesNotMatch(source, /<details[^>]*analysis-requirement-row/); // quote no longer behind a click
});

test("confirm all in a group: requirement and Gap, group reason with per-item override, sequential with a report", async () => {
  const items = [requirement("a", "EVIDENCE_MISSING"), requirement("b", "PARTIAL")];
  const gaps = gapsByRequirement([
    { gap_id: "g-a", requirement_id: "a", position_id: null, effective_coverage_state: "EVIDENCE_MISSING" },
    { gap_id: "g-x", requirement_id: null, position_id: "pos", effective_coverage_state: "EVIDENCE_MISSING" },
  ]);
  const reason = defaultBulkReason("Reviewed in bulk by {name}", "Aziza");
  assert.equal(reason, "Reviewed in bulk by Aziza");
  assert.equal(defaultBulkReason("Reviewed in bulk by {name}", null), "Reviewed in bulk by —");
  const plan = bulkConfirmPlan(items, gaps, reason, { b: "Checked against the certificate" });
  assert.deepEqual(plan.map((entry) => entry.posts.map((post) => [post.target_kind, post.target_id, post.new_coverage_state, post.reason])), [
    [["REQUIREMENT", "a", "EVIDENCE_MISSING", "Reviewed in bulk by Aziza"], ["GAP", "g-a", "EVIDENCE_MISSING", "Reviewed in bulk by Aziza"]],
    [["REQUIREMENT", "b", "PARTIAL", "Checked against the certificate"]],
  ]);
  assert.ok(plan.flatMap((entry) => entry.posts).every((post) => post.new_review_state === "CONFIRMED"));
  const order = [];
  const progress = [];
  const report = await runSequential(plan, (entry) => entry.requirementId, async (entry) => {
    order.push(entry.requirementId);
    if (entry.requirementId === "b") throw new Error("HTTP 404");
  }, (done, total) => progress.push(`${done}/${total}`));
  assert.deepEqual(order, ["a", "b"]);
  assert.deepEqual(progress, ["0/2", "1/2", "2/2"]);
  assert.deepEqual(report, { done: 2, failed: [{ id: "b", message: "HTTP 404" }] });
});

test("later-stage obligations never appear as EOI criteria, even if the backend returns them", () => {
  assert.equal(withoutLaterStage(SUGGESTIONS), SUGGESTIONS); // nothing to drop: unchanged
  const duty = { requirement_id: "c4", statement: "Prepare designs for 12 sub-projects", original_quote: "The Consultant shall prepare...",
    locator: { page_number: null, paragraph_number: 9 }, effective_coverage_state: "LATER_STAGE_OBLIGATION", matched_reference_ids: ["r3"] };
  const leaked = {
    ...SUGGESTIONS, criteria: [...SUGGESTIONS.criteria, duty],
    own_references: SUGGESTIONS.own_references.map((item) => item.reference_id === "r3" ? { ...item, matched_requirement_ids: ["c4"] } : item),
    partner_firms: SUGGESTIONS.partner_firms.map((firm) => firm.firm_id === "p1" ? { ...firm, covers_requirement_ids: ["c1", "c2", "c4"] } : firm),
  };
  const clean = withoutLaterStage(leaked);
  assert.deepEqual(clean.criteria.map((item) => item.requirement_id), ["c1", "c2", "c3"]);
  assert.deepEqual(clean.own_references.find((item) => item.reference_id === "r3").matched_requirement_ids, []);
  assert.deepEqual(clean.partner_firms[0].covers_requirement_ids, ["c1", "c2"]);
  const state = initialBuilderState(clean, { uiLocale: "en" });
  assert.equal(addressedBy(clean, state).has("c4"), false);
  const source = read("components/pursuits/PursuitEoi.tsx");
  assert.match(source, /withoutLaterStage\(suggested\.data\)/);
});

test("EOI downloads use the server's Content-Disposition filename, else the version pattern", () => {
  const fallback = "expression-of-interest-v2-ru.docx";
  assert.equal(downloadFilename('attachment; filename="eoi-OP00468882-v2-ru.docx"', fallback), "eoi-OP00468882-v2-ru.docx");
  assert.equal(downloadFilename("attachment; filename=eoi.pdf", fallback), "eoi.pdf");
  assert.equal(downloadFilename(`attachment; filename="eoi.docx"; filename*=utf-8''%D0%97%D0%B0%D1%8F%D0%B2%D0%BA%D0%B0.docx`, fallback), "Заявка.docx");
  assert.equal(downloadFilename(`attachment; filename*=UTF-8''%E0%A4%A`, fallback), fallback); // undecodable, no plain name
  assert.equal(downloadFilename('attachment; filename="../../etc/eoi.docx"', fallback), "eoi.docx"); // a name, never a path
  assert.equal(downloadFilename(undefined, fallback), fallback);
  assert.equal(downloadFilename("attachment", fallback), fallback);
  const source = read("components/pursuits/PursuitEoi.tsx");
  assert.match(source, /downloadFilename\(response\.headers\['content-disposition'\]/);
});

test("the workspace header shows the pursuit stage, never a processing state", () => {
  const page = read("app/dashboard/pursuits/[pursuitId]/page.tsx");
  const header = page.slice(page.indexOf("<PageHeader", page.indexOf("return <main className=\"customer-page pursuit-workspace")));
  const status = header.slice(header.indexOf("status={"), header.indexOf("metadata={"));
  assert.match(status, /stages\.\$\{pursuit\.stage\}/);
  assert.doesNotMatch(status, /processing/);
  assert.doesNotMatch(page, /customerProcessingState\(pursuit\.processing_state\)/);
  // Document processing states remain in Documents & Evidence.
  assert.match(page, /customerProcessingState\(document\.processing_state\)/);
  for (const locale of LOCALES) {
    const stages = JSON.parse(read(`messages/${locale}/pursuits.json`)).stages;
    for (const stage of ["SAVED", "EVALUATING", "PREPARING", "SUBMITTED", "WON", "LOST", "DISMISSED"]) assert.ok(stages[stage], `${locale} ${stage}`);
  }
});

test("live-run fixes: notice name localized, matches shown in every group, bulk panel closes, plural summary", async () => {
  const source = read("components/pursuits/PursuitRequirements.tsx");
  // The official notice is cited by its localized name, as in the EOI ("Notice, paragraph 17").
  assert.match(source, /item\.role === 'OFFICIAL_NOTICE' \? t\('documentRoles\.OFFICIAL_NOTICE'\) : item\.display_name/);
  // Matched experience is shown wherever the analysis recorded matches (also NEEDS_INTERPRETATION).
  assert.doesNotMatch(source, /group === 'partial' && \(matchedNames/);
  // After a run the group shows its report, not an empty "Confirm 0" panel.
  assert.match(source, /setOpen\(false\);\s*await onDone\(\);/);
  assert.match(source, /!open \? pending\.length > 0 && <Button/);
  const { default: IntlMessageFormat } = await import("intl-messageformat");
  const summary = JSON.parse(read("messages/en/pursuits.json")).eoi.versionSummary;
  const format = (references, partners) => new IntlMessageFormat(summary, "en").format({
    references, partners, addressed: 1, total: 5, notes: 2, dropped: 0 });
  assert.equal(format(1, 1), "1 own assignment · 1 partner · 1 of 5 criteria addressed · notes kept 2, dropped 0");
  assert.equal(format(3, 0), "3 own assignments · 0 partners · 1 of 5 criteria addressed · notes kept 2, dropped 0");
  for (const locale of LOCALES) {
    const messages = JSON.parse(read(`messages/${locale}/pursuits.json`)).requirements;
    assert.notEqual(messages.packHelp.replace(/\.$/, ""), messages.packTitle, locale); // help adds information
  }
});

test("pursuit titles are never 'Untitled'", () => {
  const fallback = (date) => `Uploaded tender · ${date.slice(0, 10)}`;
  assert.equal(pursuitDisplayTitle({ title: "LOT-4", tender_title: "x", created_at: "2026-09-01T00:00:00Z" }, fallback), "LOT-4");
  assert.equal(pursuitDisplayTitle({ title: " ", tender_title: null, first_document_name: "ToR.pdf", created_at: "2026-09-01T00:00:00Z" }, fallback), "ToR.pdf");
  assert.equal(pursuitDisplayTitle({ title: null, created_at: "2026-09-01T00:00:00Z" }, fallback), "Uploaded tender · 2026-09-01");
  for (const path of ["app/dashboard/page.tsx", "app/dashboard/uploaded-tenders/page.tsx", "app/dashboard/pursuits/[pursuitId]/page.tsx"]) {
    const source = read(path);
    assert.match(source, /pursuitDisplayTitle\(/, path);
    assert.doesNotMatch(source, /values\.untitled|pursuitUntitled/, path);
  }
  for (const locale of LOCALES) {
    assert.match(JSON.parse(read(`messages/${locale}/pursuits.json`)).values.uploadedOn, /\{date\}/, locale);
  }
});

test("every EOI and review string exists in all four locales", () => {
  const flatten = (node, prefix = "") => Object.entries(node).flatMap(([key, value]) =>
    typeof value === "object" ? flatten(value, `${prefix}${key}.`) : [`${prefix}${key}`]);
  const en = JSON.parse(read("messages/en/pursuits.json"));
  for (const locale of LOCALES) {
    const catalog = JSON.parse(read(`messages/${locale}/pursuits.json`));
    assert.deepEqual(flatten(catalog.eoi).sort(), flatten(en.eoi).sort(), locale);
    assert.deepEqual(flatten(catalog.requirements.review).sort(), flatten(en.requirements.review).sort(), locale);
    assert.ok(catalog.workspace.tabs.eoi, locale);
  }
  assert.equal(en.workspace.tabs.eoi, "EOI package");
  assert.equal(en.requirements.review.groups.attention, "Needs your attention");
  assert.equal(en.requirements.review.groups.partial, "Partly addressed by your experience");
});
