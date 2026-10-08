import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  CV_DRAFT_PENDING,
  cvConfirmPayload,
  cvDraftConfirmable,
  cvDraftPending,
  cvErrors,
  emptyCvDraft,
  reviewDraftErrors,
  reviewDraftFromProposal,
} from "../lib/library.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");
const LOCALES = ["en", "ru", "uz", "ar"];
const STATES = ["PROCESSING_DOCUMENT", "QUEUED", "EXTRACTING", "READY", "FAILED", "CONFIRMED"];
const flatten = (value, prefix = "") =>
  Object.entries(value).flatMap(([key, item]) =>
    item && typeof item === "object" ? flatten(item, `${prefix}${key}.`) : [`${prefix}${key}`],
  );

const PROPOSAL = {
  full_name: { value: "Dilnoza Karimova", quote: "Dilnoza Karimova" },
  education: [{ degree: "MSc Electrical Engineering", institution: "TSTU", year: "2009", quote: "MSc Electrical Engineering, TSTU, 2009" }],
  assignments: [{ role: "Team Leader", client: "National Grid", country: "Uzbekistan", sector: "Energy", start: "2019", end: "2023", description: "", quote: "2019-2023 Team Leader" }],
  languages: [],
  certifications: [{ name: "PMP", issuer: "PMI", year: "", quote: "PMP, PMI", extra: "ignored" }],
};

test("the proposal becomes editable rows that keep their quotes", () => {
  const draft = reviewDraftFromProposal(PROPOSAL);
  assert.equal(draft.assignments[0].quote, "2019-2023 Team Leader");
  assert.equal(draft.assignments[0].role, "Team Leader");
  assert.deepEqual(Object.keys(draft.certifications[0]).sort(), ["issuer", "name", "quote", "year"]);
  // Nothing proposed: one empty row to type into (the manual form after a provider failure).
  assert.equal(draft.languages.length, 1);
  assert.equal(draft.languages[0].quote, undefined);
  const manual = reviewDraftFromProposal(null);
  assert.deepEqual(manual.assignments, emptyCvDraft().assignments);
});

test("review validation matches the manual CV rules and needs a name for a new expert", () => {
  const draft = reviewDraftFromProposal(PROPOSAL);
  // CVs state periods in years: YYYY is accepted as well as YYYY-MM.
  assert.deepEqual(reviewDraftErrors(draft, "Dilnoza Karimova"), []);
  assert.deepEqual(reviewDraftErrors(draft, null), []);
  assert.deepEqual(reviewDraftErrors(draft, " "), [{ field: "expert_name", code: "required" }]);
  draft.assignments[0].end = "2018";
  assert.deepEqual(reviewDraftErrors(draft, null), [{ field: "assignments.0.end", code: "datesOrder" }]);
  draft.assignments[0].end = "23";
  assert.deepEqual(reviewDraftErrors(draft, null), [{ field: "assignments.0.end", code: "month" }]);
  assert.deepEqual(cvErrors(emptyCvDraft()), [{ field: "cv", code: "emptyCv" }]);
});

test("the confirm payload drops empty rows and keeps quotes for server-side verification", () => {
  const draft = reviewDraftFromProposal(PROPOSAL);
  draft.assignments.push({ role: "", client: "", country: "", sector: "", start: "", end: "", description: "" });
  draft.languages[0] = { language: "Russian", level: "fluent" };
  const payload = cvConfirmPayload(draft, "  Dilnoza   Karimova ");
  assert.equal(payload.new_expert_name, "Dilnoza Karimova");
  assert.equal(payload.assignments.length, 1);
  assert.deepEqual(payload.assignments[0], {
    role: "Team Leader", client: "National Grid", country: "Uzbekistan", sector: "Energy", start: "2019", end: "2023",
    quote: "2019-2023 Team Leader",
  });
  assert.deepEqual(payload.languages, [{ language: "Russian", level: "fluent" }]);
  // An existing expert sends no name.
  assert.equal("new_expert_name" in cvConfirmPayload(draft, null), false);
});

test("drafts poll while being read and are confirmable unless rejected or saved", () => {
  assert.deepEqual([...CV_DRAFT_PENDING], ["PROCESSING_DOCUMENT", "QUEUED", "EXTRACTING"]);
  assert.deepEqual(STATES.map(cvDraftPending), [true, true, true, false, false, false]);
  assert.equal(cvDraftConfirmable("READY"), true);
  assert.equal(cvDraftConfirmable("FAILED", "PROVIDER_ERROR"), true);  // manual form after a provider failure
  assert.equal(cvDraftConfirmable("FAILED", "DOCUMENT_REJECTED"), false);
  assert.equal(cvDraftConfirmable("PROCESSING_DOCUMENT"), false);
  assert.equal(cvDraftConfirmable("CONFIRMED"), false);
});

test("CV upload and review copy exists with the same keys in every locale", () => {
  const library = (locale) => JSON.parse(read(`messages/${locale}/pursuits.json`)).library;
  const keys = (locale) => flatten({
    cvUpload: library(locale).cvUpload, cvDrafts: library(locale).cvDrafts, cvReview: library(locale).cvReview,
    expert: library(locale).expert,
  }).sort();
  for (const locale of LOCALES) {
    assert.deepEqual(keys(locale), keys("en"), locale);
    assert.deepEqual(Object.keys(library(locale).cvDrafts.states).sort(), [...STATES].sort(), locale);
  }
});

test("Experts offers Upload CV for new and existing experts; the review never saves by itself", () => {
  const tabs = read("components/library/LibraryTabs.tsx");
  assert.match(tabs, /setUploadFor\(\{ expert: null \}\)/);
  assert.match(tabs, /setUploadFor\(\{ expert \}\)/);
  assert.match(tabs, /<PendingCvDrafts /);
  const page = read("app/dashboard/partners-experts/cv/[draftId]/page.tsx");
  assert.equal((page.match(/confirmCvDraft\(/g) || []).length, 1);
  assert.match(page, /const submit = async/);
  assert.match(page, /setInterval\(\(\) => void load\(\), 3_000\)/);
  assert.match(page, /cv-review-layout/);
  const api = read("lib/libraryApi.ts");
  assert.match(api, /'\/candidates\/cv-uploads'/);
});
