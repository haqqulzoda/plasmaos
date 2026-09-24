import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  classifyProjectContextFailure,
  projectFreshnessMessage,
  projectMetadataRows,
  projectRoleLabel,
} from "../types/project.ts";

const pageSource = readFileSync(
  new URL("../app/dashboard/tenders/[tenderId]/page.tsx", import.meta.url),
  "utf8",
);
const tenderDetailsMessages = JSON.parse(readFileSync(
  new URL("../messages/en/tenderDetails.json", import.meta.url),
  "utf8",
));

const project = (overrides = {}) => ({
  id: "internal-project-uuid",
  source_system: "world_bank",
  external_project_id: "P179267",
  name: "Regional Solar Project",
  country: "Liberia",
  region: "Western and Central Africa",
  status: "Active",
  approval_date: "2022-12-20",
  closing_date: "2027-06-30",
  borrower: "Republic of Liberia",
  implementing_agencies: ["Liberia Electricity Corporation"],
  source_url: "https://projects.worldbank.org/project/P179267",
  enrichment_status: "successful",
  last_successful_enrichment_at: "2026-08-26T12:00:00Z",
  source_freshness: "fresh",
  ...overrides,
});

const role = (canonicalRole, nativeRole = canonicalRole) => ({
  canonical_role: canonicalRole,
  native_role: nativeRole,
  source_system: "world_bank",
});

const projectSectionSource = pageSource
  .split('id="project-context"', 2)[1]
  .split('id="requirements-documents"', 1)[0];

test("no Project has an explicit consolidated empty state", () => {
  assert.match(
    projectSectionSource,
    /t\('projectLinkedEmpty'\)|t\("projectLinkedEmpty"\)/,
  );
});

test("linked not-enriched identity remains visible while details prepare", () => {
  assert.equal(
    projectFreshnessMessage("pending"),
    "Project details are being prepared.",
  );
  assert.match(projectSectionSource, /project\.name/);
  assert.match(
    projectSectionSource,
    /t\('projectPreparing'\)|t\("projectPreparing"\)/,
  );
});

test("enriched metadata renders only meaningful rows", () => {
  const rows = projectMetadataRows(project());
  assert.deepEqual(
    rows.map((row) => row.label),
    [
      "Country / Region",
      "Status",
      "Approval date",
      "Closing date",
      "Borrower",
      "Implementing Agency",
    ],
  );
});

test("Project Context uses the approved concise field labels", () => {
  assert.deepEqual(
    [
      tenderDetailsMessages.s143.projectName,
      tenderDetailsMessages.countryRegion,
      tenderDetailsMessages.s143.projectStatus,
      tenderDetailsMessages.projectApproval,
      tenderDetailsMessages.projectClosing,
    ],
    ["Name", "Country / Region", "Status", "Approval date", "Closing date"],
  );
});

test("missing metadata is omitted instead of rendered as placeholders", () => {
  assert.deepEqual(
    projectMetadataRows(
      project({
        country: null,
        region: null,
        status: null,
        approval_date: null,
        closing_date: null,
        borrower: null,
        implementing_agencies: null,
      }),
    ),
    [],
  );
  assert.doesNotMatch(
    projectSectionSource,
    /['"]N\/A['"]|['"]undefined['"]|['"]null['"]/,
  );
});

test("all source-backed leadership names use the scalable names-only list", () => {
  assert.match(projectSectionSource, /t\('leadership'\)|t\("leadership"\)/);
  assert.match(pageSource, /projectLeadership = leadership\?\.items \?\? \[\]/);
  assert.match(projectSectionSource, /items=\{projectLeadership\}/);
  assert.doesNotMatch(projectSectionSource, /leadershipRoleLabel|role\.native_role/);
});

test("leadership does not create a separate role or history treatment", () => {
  assert.doesNotMatch(pageSource, /previousLeadership|s143-leadership-previous|role\.is_current/);
});

test("Task Team Leader canonical label is exact", () => {
  assert.equal(
    projectRoleLabel(role("TASK_TEAM_LEADER", "Task Team Leader")),
    "Task Team Leader",
  );
});

test("Co-Task Team Leader canonical label is exact", () => {
  assert.equal(
    projectRoleLabel(role("CO_TASK_TEAM_LEADER", "Co-Task Team Leader")),
    "Co-Task Team Leader",
  );
});

test("Task Manager canonical label is exact and not TTL", () => {
  assert.equal(
    projectRoleLabel(role("PROJECT_TASK_MANAGER", "Task Manager")),
    "Task Manager",
  );
});

test("teamleadname never renders as TTL", () => {
  const label = projectRoleLabel(
    role("OTHER_PROJECT_ROLE", "teamleadname"),
    "World Bank",
  );
  assert.equal(label, "World Bank project team");
  assert.doesNotMatch(label, /Task Team Leader|\bTTL\b|Co-TTL/i);
});

test("no leadership email is inferred or replaced with a placeholder", () => {
  assert.doesNotMatch(projectSectionSource, /role\.email|mailto:|email format/);
});

test("procurement contact remains an explicitly separate Tender section", () => {
  assert.match(pageSource, /title=\{t\("contactsTitle"\)\}/);
  assert.match(pageSource, /id="contacts"/);
  assert.match(projectSectionSource, /s143\.leadershipSource/);
  assert.doesNotMatch(projectSectionSource, /role\.contact_person|role\.email/);
});

test("Project dates have explicit non-deadline labels", () => {
  const labels = projectMetadataRows(project()).map((row) => row.label);
  assert.ok(labels.includes("Approval date"));
  assert.ok(labels.includes("Closing date"));
  assert.ok(!labels.includes("Tender Deadline"));
});

test("Project status presentation does not use Tender actionability helpers", () => {
  assert.doesNotMatch(
    projectSectionSource,
    /isTenderActionable|tenderStatusLabel|TenderStatus/,
  );
});

test("stale and partial states use restrained truthful messages", () => {
  assert.equal(
    projectFreshnessMessage("stale"),
    "Project information may be outdated.",
  );
  assert.equal(
    projectFreshnessMessage("incomplete"),
    "Some project information is unavailable.",
  );
  assert.equal(
    projectFreshnessMessage("unavailable"),
    "Official project data is currently unavailable.",
  );
  assert.notEqual(
    projectFreshnessMessage("unavailable"),
    "Project details are temporarily unavailable.",
  );
  assert.equal(projectFreshnessMessage("fresh"), null);
});

test("Project API failure is isolated from the Tender load", () => {
  assert.match(pageSource, /const loadTender = useCallback/);
  assert.match(pageSource, /const loadDetails = useCallback/);
  assert.match(
    pageSource,
    /useEffect\(\(\) => \{\s*void loadTender\(\);\s*\}, \[loadTender\]\)/,
  );
  assert.match(
    pageSource,
    /useEffect\(\(\) => \{\s*void loadDetails\(\);\s*\}, \[loadDetails\]\)/,
  );
  assert.match(pageSource, /detailsError &&/);
  assert.match(pageSource, /t\(["']detailsFailed["']\)/);
});

test("Project HTTP outcomes remain semantically distinct", () => {
  assert.equal(classifyProjectContextFailure(404), "no_project");
  assert.equal(classifyProjectContextFailure(401), "authorization");
  assert.equal(classifyProjectContextFailure(403), "authorization");
  assert.equal(classifyProjectContextFailure(500), "endpoint_failure");
  assert.equal(classifyProjectContextFailure(undefined), "endpoint_failure");
});

test("source and status semantics are accessible and responsive", () => {
  assert.match(pageSource, /<Section id="project-context"/);
  assert.match(pageSource, /aria-labelledby=\{`\$\{id\}-title`\}/);
  assert.match(pageSource, /function StateMessage/);
  assert.match(readFileSync(new URL("../components/customer/pages.css", import.meta.url), "utf8"), /s143-project-grid/);
});
