import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");
const LOCALES = ["en", "ru", "uz", "ar"];

const finder = read("components/pursuits/PursuitPartnerFinder.tsx");
const team = read("components/pursuits/PursuitTeam.tsx");
const admin = read("app/admin/partner-requests/page.tsx");
const types = read("types/partnerFinder.ts");

test("every locale carries the partner finder and prospective-member strings", () => {
  const english = JSON.parse(read("messages/en/pursuits.json")).team;
  const keys = (value, prefix = "") => Object.entries(value).flatMap(([key, item]) =>
    typeof item === "string" ? [prefix + key] : keys(item, `${prefix}${key}.`));
  const expected = { finder: keys(english.partnerFinder), prospective: keys(english.scenarios.prospective) };
  for (const locale of LOCALES) {
    const catalog = JSON.parse(read(`messages/${locale}/pursuits.json`)).team;
    assert.deepEqual(keys(catalog.partnerFinder), expected.finder, locale);
    assert.deepEqual(keys(catalog.scenarios.prospective), expected.prospective, locale);
    assert.match(catalog.partnerFinder.notice, /\{id\}/, locale);
    assert.match(catalog.scenarios.prospective.closedBy, /\{names\}/, locale);
  }
  assert.equal(english.partnerFinder.sourceLabel, "From public award records, unverified");
  assert.match(english.partnerFinder.requestHelp, /Nothing is sent to the firm automatically/);
});

test("suggestions show public award facts with the unverified label and never contact fields", () => {
  for (const key of ["sourceLabel", "requestIntroduction", "askSourcing", "jvRuleCheck"]) {
    assert.match(finder, new RegExp(`t\\('${key}'\\)`), key);
  }
  assert.match(finder, /award\.notice_url/);
  assert.match(finder, /rel="noopener noreferrer"/);
  const partnerTypes = types;
  assert.ok(partnerTypes.includes("export type PartnerSuggestion = {"));
  assert.doesNotMatch(partnerTypes, /^\s*\w*(email|phone|contact|address|website)\w*\??:/im);
  assert.doesNotMatch(finder, /mailto:|tel:/);
});

test("the Team tab shows the finder and prospective JV members as not yet confirmed", () => {
  assert.match(team, /<PursuitPartnerFinder pursuitId=\{pursuitId\} headers=\{headers\} \/>/);
  assert.match(team, /t\('notConfirmed'\)/);
  assert.match(team, /prospective-members/);
  assert.match(team, /\['ACCEPTED', 'INTRODUCED'\]\.includes\(request\.status\)/);
});

test("the admin queue moves requests along the audited status path", () => {
  assert.match(read("components/shell/AdminShell.tsx"), /href: '\/admin\/partner-requests'/);
  assert.match(admin, /\/admin\/partner-requests\/\$\{editing\.item\.request_id\}\/status/);
  assert.match(admin, /item\.next_statuses\.map/);
  assert.match(read("app/admin/audit/page.tsx"), /'PARTNER_REQUEST_CREATED', 'PARTNER_REQUEST_STATUS_CHANGED'/);
});
