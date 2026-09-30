import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { CUSTOMER_NAVIGATION, activeNavigationKey } from "../lib/customerNavigation.ts";
import {
  deadlineDaysLeft,
  deriveFactChips,
  matchesProfile,
  noticeKind,
} from "../lib/factChips.ts";
import {
  activeOrganizations,
  pursuitWorkspaceHref,
  resolveWorkspace,
} from "../lib/openWorkspace.ts";
import { analysisLanguageForLocale, initialPackSelection } from "../lib/packSelection.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");
const LOCALES = ["en", "ru", "uz", "ar"];
const messages = (locale, name) => JSON.parse(read(`messages/${locale}/${name}.json`));

function sources(directory) {
  const found = [];
  for (const entry of readdirSync(join(ROOT, directory))) {
    const path = `${directory}/${entry}`;
    if (statSync(join(ROOT, path)).isDirectory()) found.push(...sources(path));
    else if (/\.(tsx|ts)$/.test(entry)) found.push(path);
  }
  return found;
}

// ---- D1-06 one door: create-or-resolve on click only ----------------------------------------------

function fakeDeps(organizations) {
  const calls = [];
  return {
    calls,
    deps: {
      listOrganizations: async () => { calls.push(["GET", "/organizations"]); return organizations; },
      createOrResolveSourcePursuit: async (tenderId, organizationId) => {
        calls.push(["POST", "/pursuits/source", tenderId, organizationId]);
        return { pursuit_id: "pursuit-1" };
      },
    },
  };
}

test("a single ACTIVE membership resolves automatically and navigates to the workspace", async () => {
  const { calls, deps } = fakeDeps([
    { organization_id: "org-1", membership_state: "ACTIVE" },
    { organization_id: "org-revoked", membership_state: "REVOKED" },
  ]);
  const result = await resolveWorkspace("tender-1", deps);
  assert.deepEqual(result, {
    kind: "navigate",
    href: "/dashboard/pursuits/pursuit-1?organization_id=org-1",
    organizationId: "org-1",
    pursuitId: "pursuit-1",
  });
  assert.deepEqual(calls, [["GET", "/organizations"], ["POST", "/pursuits/source", "tender-1", "org-1"]]);
});

test("several ACTIVE memberships ask for a choice before anything is created", async () => {
  const { calls, deps } = fakeDeps([
    { organization_id: "org-1", membership_state: "ACTIVE" },
    { organization_id: "org-2", membership_state: "ACTIVE" },
  ]);
  const first = await resolveWorkspace("tender-1", deps);
  assert.equal(first.kind, "choose");
  assert.deepEqual(first.organizations.map((item) => item.organization_id), ["org-1", "org-2"]);
  assert.equal(calls.filter(([method]) => method === "POST").length, 0);
  const chosen = await resolveWorkspace("tender-1", deps, "org-2");
  assert.equal(chosen.href, "/dashboard/pursuits/pursuit-1?organization_id=org-2");
  assert.deepEqual(calls.at(-1), ["POST", "/pursuits/source", "tender-1", "org-2"]);
});

test("no ACTIVE membership creates nothing", async () => {
  const { calls, deps } = fakeDeps([{ organization_id: "org-1", membership_state: "INVITED" }]);
  assert.deepEqual(await resolveWorkspace("tender-1", deps), { kind: "no-organization" });
  assert.equal(calls.filter(([method]) => method === "POST").length, 0);
  assert.deepEqual(activeOrganizations([{ organization_id: "a" }]).map((item) => item.organization_id), ["a"]);
  assert.equal(pursuitWorkspaceHref("p 1", "o/1"), "/dashboard/pursuits/p%201?organization_id=o%2F1");
});

test("the button requests nothing on render: the POST lives in the click path only", () => {
  const button = read("components/pursuits/OpenWorkspaceButton.tsx");
  assert.doesNotMatch(button, /useEffect|useLayoutEffect/);
  assert.equal((button.match(/resolveWorkspace\(/g) || []).length, 1);
  assert.match(button, /const open = useCallback\(\s*async[\s\S]*?resolveWorkspace\(tenderId, deps, chosenOrganizationId\)/);
  assert.match(button, /onClick=\{\(\) => void open\(/);
  assert.match(button, /api\.post<\{ pursuit_id: string \}>\(\s*"\/pursuits\/source"/);
  assert.match(button, /\{choosing && \([\s\S]*?<OrganizationContextPicker/); // the picker (a GET) mounts after a click
  const logic = read("lib/openWorkspace.ts");
  assert.doesNotMatch(logic, /from ['"](react|next|@\/lib\/api)/);
});

test("Open workspace is the CTA on every surface and the legacy CTAs are gone", () => {
  const details = read("app/dashboard/tenders/[tenderId]/page.tsx");
  // D2-02: one primary "Open workspace" in the header; the Analysis card offers a secondary one.
  assert.equal((details.match(/<OpenWorkspaceButton /g) || []).length, 1);
  assert.match(details, /<PursuitAnalysisCard tenderId=\{tender\.id\}/);
  assert.match(read("components/tenders/PursuitAnalysisCard.tsx"), /<OpenWorkspaceButton tenderId=\{tenderId\} variant="secondary"/);
  assert.match(details, /<TenderEngagementPanel[\s\S]*?secondaryStageActions/);
  assert.doesNotMatch(details, /openCompliance|PrepareBidButton|\/compliance`/);
  const panel = read("components/tenders/TenderEngagementPanel.tsx");
  assert.equal((panel.match(/workspaceEntry && <OpenWorkspaceButton/g) || []).length, 3);
  assert.doesNotMatch(panel, /<PrepareBidButton (foundation )?tenderId/);
  const workflow = read("components/tenders/EngagementWorkflowActions.tsx");
  assert.doesNotMatch(workflow, /PrepareBidButton|bid-preparation|openBid/);
  assert.match(workflow, /DISMISS:/); // stage actions stay
  const dashboard = read("app/dashboard/page.tsx");
  assert.match(dashboard, /<OpenWorkspaceButton tenderId=\{tender\.id\} \/>/);
  assert.doesNotMatch(dashboard, /\/compliance/);
  const myTenders = read("app/dashboard/my-tenders/page.tsx");
  assert.match(myTenders, /<OpenWorkspaceButton tenderId=\{item\.tender_id\} \/>/);
  const explorer = read("app/dashboard/tenders/page.tsx");
  assert.match(explorer, /<OpenWorkspaceButton tenderId=\{tender\.id\} variant="secondary"/); // secondary on Explorer cards
  assert.doesNotMatch(explorer, /PrepareBidButton/);
  // The old routes still exist.
  for (const route of ["app/dashboard/tenders/[tenderId]/compliance/page.tsx", "app/dashboard/bid-preparation/page.tsx", "app/dashboard/bid-preparation/[proposalId]/page.tsx"]) {
    assert.ok(existsSync(join(ROOT, route)), route);
  }
});

test("a SOURCE pursuit pre-selects its official notice; language follows the UI locale", () => {
  const candidate = {
    pursuit_origin: "SOURCE",
    source_documents: [
      { tender_document_id: "attachment", role: "OFFICIAL_SOURCE", parse_ready: true },
      { tender_document_id: "notice", role: "OFFICIAL_NOTICE", parse_ready: true },
    ],
    private_versions: [
      { document_version_id: "mine", parse_ready: true },
      { document_version_id: "pending", parse_ready: false },
    ],
  };
  assert.deepEqual(initialPackSelection(candidate), { source: ["notice"], private: ["mine"] });
  const unreadyNotice = { ...candidate, source_documents: [candidate.source_documents[0], { ...candidate.source_documents[1], parse_ready: false }] };
  assert.deepEqual(initialPackSelection(unreadyNotice).source, ["attachment"]);
  assert.deepEqual(initialPackSelection({ ...candidate, pursuit_origin: "UPLOAD" }).source, ["attachment", "notice"]);
  assert.deepEqual(["en", "ru", "uz", "ar", "ru-RU", "xx", null].map(analysisLanguageForLocale), ["en", "ru", "uz", "en", "ru", "en", "en"]);
  const requirements = read("components/pursuits/PursuitRequirements.tsx");
  assert.match(requirements, /initialPackSelection\(candidateResponse\.data\)/);
  assert.match(requirements, /useState<AnalysisLanguage>\(\(\) => analysisLanguageForLocale\(locale\)\)/);
  assert.match(requirements, /onClick=\{\(\) => void start\(\)\}/); // analysis still starts on the explicit click only
});

// ---- D1-07 navigation ---------------------------------------------------------------------------

test("the customer menu is one product with six destinations, localized in four languages", () => {
  assert.deepEqual(
    CUSTOMER_NAVIGATION.map(({ nameKey, href }) => [nameKey, href]),
    [
      ["dashboard", "/dashboard"],
      ["opportunities", "/dashboard/tenders"],
      ["pursuits", "/dashboard/my-tenders"],
      ["partnersExperts", "/dashboard/partners-experts"],
      ["companyExperience", "/dashboard/settings"],
      ["notifications", "/dashboard/notifications"],
    ],
  );
  for (const locale of LOCALES) {
    const navigation = messages(locale, "navigation");
    const labels = CUSTOMER_NAVIGATION.map(({ nameKey }) => navigation[nameKey]);
    assert.ok(labels.every((label) => typeof label === "string" && label.trim()), locale);
    assert.equal(new Set(labels).size, labels.length, locale);
    assert.ok(navigation.uploadTender, locale);
    const segments = messages(locale, "pursuits").segments;
    assert.ok(segments.fromSources && segments.uploaded && segments.label, locale);
    assert.equal(messages(locale, "myTenders").title, navigation.pursuits, locale);
  }
  assert.equal(messages("en", "navigation").opportunities, "Opportunities");
  assert.equal(messages("en", "navigation").companyExperience, "Company & Experience");
  const shell = read("components/shell/CustomerShell.tsx");
  assert.match(shell, /CUSTOMER_NAVIGATION\.map/);
  assert.doesNotMatch(shell, /bidPreparation|readinessVault|uploadedTenders/);
  assert.match(shell, /href="\/dashboard\/uploaded-tenders\/upload"/); // persistent Upload Tender
  assert.match(shell, /href="\/admin"/); // admin shell link unchanged
  assert.equal((shell.match(/\{nav\}/g) || []).length, 2); // desktop sidebar and mobile drawer share one nav
});

test("every route maps to the destination it belongs to", () => {
  const cases = {
    "/dashboard": "dashboard",
    "/dashboard/": "dashboard",
    "/dashboard/tenders": "opportunities",
    "/dashboard/tenders/abc": "opportunities",
    "/dashboard/tenders/abc/compliance": "opportunities",
    "/dashboard/my-tenders": "pursuits",
    "/dashboard/pursuits/p1?organization_id=o1": "pursuits",
    "/dashboard/uploaded-tenders": "pursuits",
    "/dashboard/uploaded-tenders/upload": "pursuits",
    "/dashboard/bid-preparation/x": "pursuits",
    "/dashboard/partners-experts": "partnersExperts",
    "/dashboard/settings": "companyExperience",
    "/dashboard/readiness-vault": "companyExperience",
    "/dashboard/notifications": "notifications",
    "/dashboard/tendersX": null,
    "/dashboard/onboarding": null,
  };
  for (const [path, expected] of Object.entries(cases)) assert.equal(activeNavigationKey(path), expected, path);
});

test("Pursuits has the From sources | Uploaded control; Company links to Readiness; Partners is honest", () => {
  assert.match(read("app/dashboard/my-tenders/page.tsx"), /<PursuitSegments active="sources" \/>/);
  assert.match(read("app/dashboard/uploaded-tenders/page.tsx"), /<PursuitSegments active="uploaded" \/>/);
  const segments = read("components/pursuits/PursuitSegments.tsx");
  assert.match(segments, /href="\/dashboard\/my-tenders"/);
  assert.match(segments, /href="\/dashboard\/uploaded-tenders"/);
  const company = read("app/dashboard/settings/page.tsx");
  assert.match(company, /href="\/dashboard\/readiness-vault"[\s\S]*?t\("readinessLink"\)/);
  assert.equal(messages("en", "pursuits").library.empty, "Add your first partner or expert");
  assert.equal(messages("en", "pursuits").library.emptyHelp, "Record them here or import a CSV file.");
  for (const locale of LOCALES) {
    assert.ok(messages(locale, "settings").readinessLink, locale);
    assert.ok(messages(locale, "pursuits").library.empty && messages(locale, "pursuits").library.emptyHelp, locale);
    assert.ok(messages(locale, "pursuits").oneDoor.openWorkspace, locale);
  }
});

// ---- D1-08 no score -------------------------------------------------------------------------------

test("no customer surface renders the numeric score or the generated rationale", () => {
  const forbidden = /match_score|rationale_summary|strategic_rationale|matchScore|RecommendationSummary\b|\/100/;
  for (const path of [...sources("app/dashboard"), ...sources("components"), "lib/dashboard.ts", "lib/factChips.ts"]) {
    const source = read(path);
    const hit = source.match(forbidden);
    assert.equal(hit, null, `${path}: ${hit?.[0]}`);
  }
  assert.equal(existsSync(join(ROOT, "components/tenders/RecommendationSummary.tsx")), false);
  const explorer = read("app/dashboard/tenders/page.tsx");
  assert.match(explorer, /t\("matches\.tab"\)/);
  assert.doesNotMatch(explorer, /views\.dismissed|best_match|dismissRecommendation/);
  for (const locale of LOCALES) {
    const facts = messages(locale, "explorer").facts;
    assert.match(facts.countryMatch, /\{country\}/, locale);
    assert.match(facts.serviceMatch, /\{service\}/, locale);
    assert.match(facts.daysLeft, /\{count, plural,/, locale);
    assert.deepEqual(Object.keys(facts.noticeType).sort(), ["eoi", "ifb", "prequalification"], locale);
    assert.ok(messages(locale, "explorer").matches.tab, locale);
    for (const text of [facts.countryMatch, facts.serviceMatch, messages(locale, "explorer").matches.tab]) {
      assert.doesNotMatch(text, /AI|score|балл|ball|%/i, locale);
    }
  }
  assert.equal(messages("en", "explorer").matches.tab, "Matches your profile");
  // The score copy is gone from the customer catalogs, not just unreferenced.
  for (const locale of LOCALES) {
    for (const name of ["dashboard", "explorer", "myTenders", "tenderDetails"]) {
      const catalog = read(`messages/${locale}/${name}.json`);
      assert.doesNotMatch(catalog, /\{score\}|"matchScore"|\/100/, `${locale}/${name}`);
    }
  }
  for (const name of ["dashboard", "explorer", "myTenders", "tenderDetails"]) {
    assert.doesNotMatch(read(`messages/en/${name}.json`), /match score|AI score/i, name);
  }
});

test("fact chips are deterministic facts from existing data", () => {
  const now = Date.parse("2026-10-01T00:00:00Z");
  const tender = { deadline: "2026-10-04T12:00:00Z", notice_type: "Request for Expression of Interest", status: "OPEN" };
  assert.deepEqual(deriveFactChips(tender, { country: "Uzbekistan", services: ["consulting", "IT"] }, now), [
    { kind: "country", country: "Uzbekistan" },
    { kind: "service", service: "consulting" },
    { kind: "service", service: "IT" },
    { kind: "noticeType", type: "eoi" },
    { kind: "daysLeft", days: 4 },
  ]);
  assert.deepEqual(deriveFactChips({ deadline: null, notice_type: "General Procurement Notice" }, null, now), []);
  assert.deepEqual(deriveFactChips({ deadline: "2026-09-30T00:00:00Z", notice_type: null }, { country: null, services: [] }, now), []);
  assert.equal(noticeKind("Invitation for Bids"), "ifb");
  assert.equal(noticeKind("Request for Bids"), "ifb");
  assert.equal(noticeKind("Invitation for Prequalification"), "prequalification");
  assert.equal(noticeKind("REOI"), "eoi");
  assert.equal(noticeKind("Contract Award"), null);
  assert.equal(deadlineDaysLeft("2026-10-01T00:00:00Z", now), 0);
  assert.equal(deadlineDaysLeft("2026-10-01T00:00:01Z", now), 1);
  assert.equal(deadlineDaysLeft("not-a-date", now), null);
  assert.equal(matchesProfile({ country: "Uzbekistan", services: [] }), true);
  assert.equal(matchesProfile({ country: null, services: ["IT"] }), true);
  assert.equal(matchesProfile({ country: " ", services: [] }), false);
  assert.equal(matchesProfile(null), false);
});
