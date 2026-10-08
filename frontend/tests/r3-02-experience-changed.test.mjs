import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { EVIDENCE_SECTIONS, evidenceSections, rerunRequest } from "../lib/experienceChanged.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");
const LOCALES = ["en", "ru", "uz", "ar"];

const candidate = {
  candidate_sha256: "c".repeat(64),
  source_documents: [
    { tender_document_id: "notice", parse_ready: true },
    { tender_document_id: "tor", parse_ready: false },
  ],
  private_versions: [{ document_version_id: "v2", parse_ready: true }],
};

test("a re-run repeats the run's documents that are still present and ready", () => {
  const run = {
    analysis_language: "ru",
    pack_items: [
      { tender_document_id: "notice", document_version_id: null },
      { tender_document_id: "tor", document_version_id: null },
      { tender_document_id: null, document_version_id: "v2" },
      { tender_document_id: null, document_version_id: "v1-replaced" },
    ],
  };
  assert.deepEqual(rerunRequest(run, candidate), {
    candidate_sha256: "c".repeat(64), analysis_language: "ru",
    source_document_ids: ["notice"], private_version_ids: ["v2"],
  });
  // Nothing left to analyze: the customer chooses documents on the Requirements tab.
  assert.equal(rerunRequest({ analysis_language: "en", pack_items: [{ tender_document_id: "gone" }] }, candidate), null);
  // A run read from a backend before R3 has no selection ids.
  assert.equal(rerunRequest({ analysis_language: "en", pack_items: [{}] }, candidate), null);
});

test("sections keep a stable order and drop unknown codes", () => {
  assert.deepEqual(evidenceSections(["READINESS_RECORDS", "NEW_THING", "OWN_EXPERIENCE"]), ["OWN_EXPERIENCE", "READINESS_RECORDS"]);
  assert.deepEqual(evidenceSections(undefined), []);
});

test("banner copy exists in every locale with the exact English wording", () => {
  const banner = (locale) => JSON.parse(read(`messages/${locale}/pursuits.json`)).experienceChanged;
  assert.equal(banner("en").title, "Your experience records changed since this analysis — re-run to update matches.");
  for (const locale of LOCALES) {
    const messages = banner(locale);
    for (const key of ["title", "help", "changed", "rerun", "rerunFailed", "noDocuments"]) assert.ok(messages[key], `${locale}.${key}`);
    assert.deepEqual(Object.keys(messages.sections).sort(), [...EVIDENCE_SECTIONS].sort(), locale);
    assert.match(messages.changed, /\{sections\}/, locale);
  }
});

test("the Requirements screen and the EOI tab show the banner and re-run through the explicit POST", () => {
  const requirements = read("components/pursuits/PursuitRequirements.tsx");
  assert.match(requirements, /analysis\.company_evidence_changed && <ExperienceChangedBanner/);
  const eoi = read("components/pursuits/PursuitEoi.tsx");
  assert.match(eoi, /suggestions\.company_evidence_changed && <ExperienceChangedBanner/);
  const banner = read("components/pursuits/ExperienceChangedBanner.tsx");
  assert.match(banner, /api\.post\(`\$\{base\}\/analysis-runs`, body/);
  // Showing the banner is passive: posting happens only from the button.
  assert.equal((banner.match(/api\.post/g) || []).length, 1);
  assert.match(banner, /onClick=\{\(\) => void rerun\(\)\}/);
});
