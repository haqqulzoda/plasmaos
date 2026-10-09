import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { organizationHeader, pageOrganization, validSelection } from "../lib/organizationSelection.ts";
import { defaultBulkReason } from "../lib/requirementsReview.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");
const A = { organization_id: "org-a", membership_state: "ACTIVE" };
const B = { organization_id: "org-b", membership_state: "ACTIVE" };
const REVOKED = { organization_id: "org-r", membership_state: "REVOKED" };

test("the stored organization counts only while the membership is active", () => {
  assert.equal(validSelection([A, B], "org-b"), "org-b");
  assert.equal(validSelection([A, B], "org-x"), null);
  assert.equal(validSelection([A, REVOKED], "org-r"), null);
  assert.equal(validSelection([A], null), null);
});

test("pages use the stored organization, else the only one, else ask", () => {
  assert.equal(pageOrganization([A, B], "org-b"), "org-b");
  assert.equal(pageOrganization([A], null), "org-a");
  assert.equal(pageOrganization([A], "org-x"), "org-a");
  assert.equal(pageOrganization([A, B], null), null);
  assert.equal(pageOrganization([A, REVOKED], null), "org-a");
});

test("a request that names its organization keeps it; otherwise the selection is sent", () => {
  assert.equal(organizationHeader("org-a", "org-b"), null);
  assert.equal(organizationHeader(null, "org-b"), "org-b");
  assert.equal(organizationHeader(undefined, null), null);
});

test("the API client sends the selection and forgets a revoked one", () => {
  const api = read("lib/api.ts");
  assert.match(api, /organizationHeader\(existing \? String\(existing\) : null, readSelectedOrganization\(\)\)/);
  assert.match(api, /detail === 'Organization not found'/);
  assert.match(api, /writeSelectedOrganization\(null\)/);
  assert.match(api, /!config\.plasmaRetried/);
});

test("multi-organization users switch from the shell; pages default to the selection", () => {
  assert.match(read("components/shell/CustomerShell.tsx"), /<OrganizationSwitcher \/>/);
  const switcher = read("components/shell/OrganizationSwitcher.tsx");
  assert.match(switcher, /if \(organizations\.length < 2\) return null;/);
  assert.match(switcher, /writeSelectedOrganization\(event\.target\.value\)/);
  assert.match(read("components/pursuits/OrganizationContextPicker.tsx"), /pageOrganization\(response\.data, readSelectedOrganization\(\)\)/);
  assert.match(read("app/dashboard/page.tsx"), /pageOrganization\(organizations, readSelectedOrganization\(\)\)/);
  for (const locale of ["en", "ru", "uz", "ar"]) {
    assert.ok(JSON.parse(read(`messages/${locale}/navigation.json`)).organization, locale);
  }
});

test("the bulk-review placeholder always receives its {name} value", () => {
  const requirements = read("components/pursuits/PursuitRequirements.tsx");
  assert.match(requirements, /t\('review\.bulkDefaultReason', \{ name: '\{name\}' \}\)/);
  assert.equal(defaultBulkReason("Reviewed in bulk by {name}", "Aziza"), "Reviewed in bulk by Aziza");
});
