import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { PLAN_CODES, planErrorCode, planTabs } from "../lib/plans.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");
const TABS = ["overview", "requirements", "eoi", "team", "documents", "proposal"];
const plan = (code, features) => ({ plan: code, features: { tender_check: true, ...features } });

test("tabs follow the plan: Explore checks requirements only", () => {
  assert.deepEqual(planTabs(TABS, null), TABS);
  assert.deepEqual(planTabs(TABS, plan("explore", { eoi: false, own_evidence: false })), ["overview", "requirements"]);
  assert.deepEqual(planTabs(TABS, plan("pilot", { eoi: true, own_evidence: true })), TABS);
  assert.deepEqual(PLAN_CODES, ["explore", "pilot", "pursuit_desk", "agent", "enterprise", "per_tender"]);
});

test("plan errors are read from the API detail code", () => {
  const error = (detail) => ({ response: { data: { detail } } });
  assert.equal(planErrorCode(error({ code: "PLAN_PURSUIT_LIMIT", message: "x", plan: "pilot" })), "PLAN_PURSUIT_LIMIT");
  assert.equal(planErrorCode(error({ code: "EMAIL_MISMATCH" })), null);
  assert.equal(planErrorCode(error("Pursuit not found")), null);
  assert.equal(planErrorCode(new Error("network")), null);
});

test("every locale carries the plan notice, limit and explore check strings", () => {
  const keys = (value, prefix = "") => Object.entries(value).flatMap(([key, item]) =>
    typeof item === "string" ? [prefix + key] : keys(item, `${prefix}${key}.`));
  const english = JSON.parse(read("messages/en/dashboard.json")).plan;
  for (const locale of ["en", "ru", "uz", "ar"]) {
    const dashboard = JSON.parse(read(`messages/${locale}/dashboard.json`)).plan;
    assert.deepEqual(keys(dashboard), keys(english), locale);
    for (const key of ["nearTitle", "reachedTitle"]) {
      for (const placeholder of ["{used}", "{limit}", "{period}"].filter((p) => english[key].includes(p))) {
        assert.ok(dashboard[key].includes(placeholder), `${locale} ${key} ${placeholder}`);
      }
    }
    const pursuits = JSON.parse(read(`messages/${locale}/pursuits.json`));
    assert.ok(pursuits.requirements.planLimit && pursuits.requirements.planExploreLimit, locale);
    assert.match(pursuits.team.partnerFinder.introductionsUsed, /\{used\}.*\{limit\}|\{limit\}.*\{used\}/, locale);
    assert.match(JSON.parse(read(`messages/${locale}/auth.json`)).explore.checkUsed, /\{date\}/, locale);
  }
});

test("the notice, the explore check and the gates are wired", () => {
  const notice = read("components/plans/PlanNotice.tsx");
  assert.match(notice, /api\.get<PlanStatus>\('\/organizations\/plan'/);
  assert.match(notice, /request: explore \? 'pilot' : 'upgrade'/);
  assert.match(read("app/dashboard/page.tsx"), /<PlanNotice \/>/);
  const workspace = read("app/dashboard/pursuits/[pursuitId]/page.tsx");
  assert.match(workspace, /<PlanNotice headers=\{headers\} onPlan=\{setPlan\} \/>/);
  assert.match(workspace, /visibleTabs\.map\(\(tab\)/);
  const explore = read("app/dashboard/explore/page.tsx");
  assert.match(explore, /api\.post<\{ pursuit_id: string \}>\('\/pursuits\/source', \{ tender_id: tenderId \}\)/);
  assert.match(read("app/dashboard/layout.tsx"), /access\.organization_access_state === 'explore' && pathname\.startsWith\(EXPLORE_CHECK_PREFIX\)/);
  assert.match(read("components/pursuits/PursuitRequirements.tsx"), /planErrorCode\(failure\) === 'PLAN_PURSUIT_LIMIT'/);
  assert.match(read("components/pursuits/PursuitPartnerFinder.tsx"), /'PLAN_INTRODUCTION_LIMIT'/);
  assert.match(read("app/admin/audit/page.tsx"), /'ORGANIZATION_PLAN_GRANTED'/);
});
