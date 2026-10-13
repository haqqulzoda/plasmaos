import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const messages = (locale) => JSON.parse(read(`messages/${locale}/explorer.json`));
const LOCALES = ["en", "ru", "uz", "ar"];

test("S1 coverage strip sits on Opportunities under the page header", () => {
  const page = read("app/dashboard/tenders/page.tsx");
  assert.match(page, /import \{ CoverageStrip \} from "@\/components\/source-refresh\/CoverageStrip";/);
  assert.match(page, /<PageHeader[\s\S]*?\/>\s*<CoverageStrip \/>\s*<div className="explorer-workspace">/);
});

test("the strip reads sources and last successful refresh from the registry, not literals", () => {
  const strip = read("components/source-refresh/CoverageStrip.tsx");
  assert.match(strip, /useSourceRefresh\(\)/);
  assert.match(strip, /catalog\.map\(/); // customer-visible sources only (ADB is not in the catalog)
  assert.match(strip, /status\?\.last_success_at/);
  assert.match(strip, /status\?\.stale/);
  assert.match(strip, /status\?\.last_success_partial/);
  assert.match(strip, /t\("adbConsulting"\)[\s\S]*t\("coming"\)/);
  assert.match(strip, /new Intl\.DateTimeFormat\(locale/);
  assert.match(strip, /<BidiText>\{source\.display_name\}<\/BidiText>/);
  assert.doesNotMatch(strip, /World Bank|EBRD|UzEx|"ADB/); // names come from the catalog and messages
  assert.match(strip, /if \(catalogLoading \|\| catalogError \|\| catalog\.length === 0\) return null;/);
});

test("coverage messages exist with the same keys in every locale", () => {
  const keys = (value, prefix = "") =>
    Object.entries(value).flatMap(([key, item]) => (typeof item === "object" ? keys(item, `${prefix}${key}.`) : [`${prefix}${key}`]));
  const english = keys(messages("en").coverage).sort();
  assert.deepEqual(english, [
    "adbConsulting", "coming", "lastRefresh", "noRefreshYet", "title",
    "types.ebrd", "types.giz", "types.uzex", "types.world_bank",
  ]);
  for (const locale of LOCALES) {
    const coverage = messages(locale).coverage;
    assert.deepEqual(keys(coverage).sort(), english, locale);
    assert.match(coverage.lastRefresh, /\{time\}/, locale);
  }
  assert.match(messages("en").coverage.types.world_bank, /Expression of Interest/);
});

test("coverage strip styles use tokens and logical properties", () => {
  const css = read("components/customer/pages.css");
  const block = css.slice(css.indexOf(".coverage-strip {"), css.indexOf(".coverage-strip-coming strong"));
  assert.ok(block.length > 0);
  assert.doesNotMatch(block, /#[0-9a-f]{3,6}\b|margin-left|margin-right|padding-left|padding-right|\bleft:|\bright:/i);
  assert.match(block, /var\(--ds-border\)/);
});

test("S1 legacy URLs land on Pursuits or Company & Experience", () => {
  for (const route of ["bids", "proposals", "bid-preparation", "workspace"]) {
    const source = read(`app/dashboard/${route}/page.tsx`);
    assert.match(source, /permanentRedirect\('\/dashboard\/my-tenders'\)/, route);
    assert.doesNotMatch(source, /api\.|post\(|"use client"/, route);
  }
  const vault = read("app/dashboard/readiness-vault/page.tsx");
  assert.match(vault, /permanentRedirect\('\/dashboard\/settings\/readiness'\)/);
  // The vault itself moved under Company & Experience; every link points there.
  assert.ok(existsSync(new URL("../app/dashboard/settings/readiness/page.tsx", import.meta.url)));
  for (const path of ["app/dashboard/settings/page.tsx", "app/dashboard/tenders/[tenderId]/compliance/page.tsx"]) {
    assert.match(read(path), /href="\/dashboard\/settings\/readiness"/, path);
    assert.doesNotMatch(read(path), /\/dashboard\/readiness-vault/, path);
  }
  // Proposal pages still open (legacy links from Pursuits), and return to Pursuits.
  assert.ok(existsSync(new URL("../app/dashboard/bid-preparation/[proposalId]/page.tsx", import.meta.url)));
  const config = read("next.config.ts");
  for (const [from, to] of [["/bids", "/dashboard/my-tenders"], ["/proposals", "/dashboard/my-tenders"],
    ["/bid-preparation", "/dashboard/my-tenders"], ["/workspace", "/dashboard/my-tenders"],
    ["/readiness-vault", "/dashboard/settings/readiness"]]) {
    assert.match(config, new RegExp(`\\{source: '${from}', destination: '${to}', permanent: true\\}`), from);
  }
});

test("navigation keeps the moved pages under the right destination", async () => {
  const { activeNavigationKey } = await import("../lib/customerNavigation.ts");
  assert.equal(activeNavigationKey("/dashboard/settings/readiness"), "companyExperience");
  assert.equal(activeNavigationKey("/dashboard/bid-preparation/123"), "pursuits");
});

test("S1-6: a preview EOI draft shows 'Draft — not reviewed by your team' in every locale", () => {
  const panel = read("components/pursuits/PursuitEoi.tsx");
  assert.match(panel, /draft\.draft_status === 'NOT_REVIEWED_BY_TEAM' && <StatusBadge tone="warning"[^>]*>\{t\('notReviewedByTeam'\)\}/);
  assert.match(read("types/eoi.ts"), /draft_status\?: string \| null;/);
  const labels = Object.fromEntries(["en", "ru", "uz", "ar"].map((locale) =>
    [locale, JSON.parse(read(`messages/${locale}/pursuits.json`)).eoi.notReviewedByTeam]));
  assert.equal(labels.en, "Draft — not reviewed by your team");
  assert.ok(Object.values(labels).every((value) => typeof value === "string" && value.length > 5), JSON.stringify(labels));
});
