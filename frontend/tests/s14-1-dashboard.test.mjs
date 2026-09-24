import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  DASHBOARD_OPPORTUNITY_LIMIT,
  activeOpportunityShortlist,
  isCurrentTender,
  lastAuthoritativeRefresh,
  profilePromptVariant,
} from "../lib/dashboard.ts";

const read = (path) =>
  readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const NOW = Date.parse("2026-09-17T10:00:00Z");

function item({
  id,
  canonical = id,
  status = "OPEN",
  deadline = "2026-10-20T10:00:00Z",
  score = 80,
  recommendation = true,
}) {
  return {
    tender: {
      id,
      external_id: `EXT-${id}`,
      source_system: "world_bank",
      canonical_source_key: canonical,
      source_url: null,
      title: `Tender ${id}`,
      buyer: null,
      budget: 0,
      currency: "USD",
      deadline,
      publication_date: null,
      country: "Uzbekistan",
      region: "Central Asia",
      sector: "Services",
      status,
      category: "Consulting",
      document_status: "metadata_only",
      document_count: 0,
      created_at: "2026-09-01T00:00:00Z",
      is_new: false,
      new_until: "2026-09-02T00:00:00Z",
    },
    recommendation: recommendation
      ? {
          recommendation_id: `rec-${id}`,
          match_score: score,
          rationale_summary: "Stored rationale",
          is_dismissed: false,
          created_at: "2026-09-01T00:00:00Z",
        }
      : null,
    pursuit: null,
  };
}

test("active shortlist enforces 0/1/3/4+ cardinality and the three-item cap", () => {
  assert.equal(DASHBOARD_OPPORTUNITY_LIMIT, 3);
  assert.deepEqual(activeOpportunityShortlist([], NOW), []);
  assert.equal(activeOpportunityShortlist([item({ id: "a" })], NOW).length, 1);
  assert.equal(
    activeOpportunityShortlist(
      ["a", "b", "c"].map((id) => item({ id })),
      NOW,
    ).length,
    3,
  );
  assert.deepEqual(
    activeOpportunityShortlist(
      ["a", "b", "c", "d"].map((id, index) =>
        item({ id, score: 90 - index }),
      ),
      NOW,
    ).map(({ tender }) => tender.id),
    ["a", "b", "c"],
  );
});

test("closed, cancelled, unknown, expired, invalid and un-recommended rows cannot leak", () => {
  const candidates = [
    item({ id: "open" }),
    item({ id: "closed", status: "CLOSED" }),
    item({ id: "cancelled", status: "CANCELLED" }),
    item({ id: "unknown", status: "UNKNOWN" }),
    item({ id: "expired", deadline: "2026-09-16T09:00:00Z" }),
    item({ id: "invalid", deadline: "not-a-date" }),
    item({ id: "unrecommended", recommendation: false }),
  ];
  assert.equal(isCurrentTender(candidates[0].tender, NOW), true);
  assert.deepEqual(
    activeOpportunityShortlist(candidates, NOW).map(({ tender }) => tender.id),
    ["open"],
  );
});

test("ranking uses stored relevance, then deadline urgency, then stable identity", () => {
  const selected = activeOpportunityShortlist(
    [
      item({ id: "later", canonical: "z", score: 90, deadline: "2026-11-01T00:00:00Z" }),
      item({ id: "lower", canonical: "a", score: 89, deadline: "2026-09-18T00:00:00Z" }),
      item({ id: "same-z", canonical: "c", score: 90, deadline: "2026-09-20T00:00:00Z" }),
      item({ id: "same-a", canonical: "b", score: 90, deadline: "2026-09-20T00:00:00Z" }),
    ],
    NOW,
  );
  assert.deepEqual(
    selected.map(({ tender }) => tender.id),
    ["same-a", "same-z", "later"],
  );
});

test("canonical source identity is deduplicated before the cap", () => {
  const selected = activeOpportunityShortlist(
    [
      item({ id: "old", canonical: "same", score: 70 }),
      item({ id: "best", canonical: "same", score: 95 }),
      item({ id: "other", canonical: "other", score: 80 }),
    ],
    NOW,
  );
  assert.deepEqual(
    selected.map(({ tender }) => tender.id),
    ["best", "other"],
  );
});

test("similar EBRD titles remain distinct when their canonical notices differ", () => {
  const selected = activeOpportunityShortlist(
    [
      item({ id: "ebrd-a", canonical: "ebrd:46012817", score: 90 }),
      item({ id: "ebrd-b", canonical: "ebrd:46255706", score: 89 }),
    ].map((entry) => ({
      ...entry,
      tender: {
        ...entry.tender,
        source_system: "ebrd",
        title: "Construction supervision services",
      },
    })),
    NOW,
  );
  assert.deepEqual(
    selected.map(({ tender }) => tender.id),
    ["ebrd-a", "ebrd-b"],
  );
});

test("profile prompt is conditional on supported matching and company fields", () => {
  const complete = {
    company_profile_id: "profile",
    onboarding_required: false,
    company_name: "Plasma",
    director_name: "Director",
    phone_contact: "+998",
    inn: "123",
    industry: "IT",
    target_regions: ["Central Asia"],
    target_countries: [],
    target_services: ["it"],
  };
  assert.equal(profilePromptVariant(null), "all");
  assert.equal(profilePromptVariant(complete), null);
  assert.equal(
    profilePromptVariant({ ...complete, target_services: [] }),
    "targeting",
  );
  assert.equal(profilePromptVariant({ ...complete, inn: null }), "details");
});

test("header freshness uses only authoritative clean refresh metadata", () => {
  const terminal = (completed_at) => ({ completed_at });
  const rows = [
    { last_clean_completed: terminal("2026-09-16T08:00:00Z") },
    { last_clean_completed: terminal("2026-09-17T09:00:00Z") },
    { last_clean_completed: null },
  ];
  assert.equal(lastAuthoritativeRefresh(rows), "2026-09-17T09:00:00Z");
  assert.equal(lastAuthoritativeRefresh([]), null);
});

test("Dashboard source preserves the accepted IA, passivity and controlled fallback", () => {
  const page = read("app/dashboard/page.tsx");
  const bookmark = read("components/customer/DashboardBookmarkButton.tsx");
  const css = read("components/customer/pages.css");
  const shell = read("components/shell/CustomerShell.tsx");
  const shellCss = read("components/shell/shell.css");
  const primaryOrder = ["dashboard-active", "dashboard-attention", "dashboard-analyses"]
    .map((marker) => page.lastIndexOf(marker));
  const supportOrder = ["dashboard-readiness", "dashboard-profile"]
    .map((marker) => page.lastIndexOf(marker));
  assert.ok(primaryOrder.every((position) => position >= 0), primaryOrder);
  assert.ok(supportOrder.every((position) => position >= 0), supportOrder);
  assert.ok(primaryOrder.every((position, index) => !index || position > primaryOrder[index - 1]));
  assert.ok(supportOrder[1] > supportOrder[0]);
  assert.match(page, /dashboard-column dashboard-primary-column/);
  assert.match(page, /dashboard-column dashboard-support-column/);
  assert.match(page, /view: "recommended"/);
  assert.match(page, /status: "OPEN"/);
  assert.match(page, /limit: 100/);
  assert.match(page, /data-source-logo="official"/);
  assert.match(page, /data-source-logo="fallback"/);
  assert.match(page, /state\.analyses\.slice\(0, 2\)/);
  assert.match(page, /viewAllAnalyses/);
  assert.match(page, /deadline\.unavailable/);
  assert.match(page, /profilePrompt\.all/);
  assert.match(page, /lastAuthoritativeRefresh\(statusItems\)/);
  assert.doesNotMatch(page, /activityTitle|recentActivity|Match score|redesign\.match/);
  assert.doesNotMatch(page, /api\.(?:post|put|patch|delete)/);
  assert.match(bookmark, /aria-pressed=\{isSaved\}/);
  assert.match(bookmark, /actions\/dismiss/);
  assert.match(bookmark, /expected_status: pursuit\.status/);
  assert.match(css, /\.dashboard-column\s*\{[\s\S]*?align-content: start/);
  assert.doesNotMatch(css, /"analyses profile"|grid-template-areas/);
  assert.doesNotMatch(css, /\.dashboard[^\{]*\{[^\}]*--[\w-]+\s*:/);
  assert.match(shell, /path !== '\/dashboard'/);
  assert.match(shellCss, /\.shell-nav-link\[aria-current='page'\][\s\S]*background: var\(--ds-accent-subtle\)/);
});
