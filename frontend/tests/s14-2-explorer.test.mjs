import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { safeSourceUrl } from "../lib/sourceUrl.ts";

const page = readFileSync(new URL("../app/dashboard/tenders/page.tsx", import.meta.url), "utf8");

test("source navigation uses only valid authoritative web URLs", () => {
  assert.equal(safeSourceUrl("https://official.example/tender/7"), "https://official.example/tender/7");
  for (const unsafe of [null, "javascript:alert(1)", "data:text/html,hi", "//evil.example/path", "/relative", "https://user:pass@evil.example/path"])
    assert.equal(safeSourceUrl(unsafe), null);
  assert.match(page, /safeSourceUrl\(tender\.source_url\)/);
  assert.match(page, /rel="noopener noreferrer external"/);
});

test("unsupported mockup controls are omitted and recommendation state stays distinct", () => {
  assert.doesNotMatch(page, /Saved searches|Create saved search|Compact mode/);
  assert.match(page, /recommendation\.match_score/);
  assert.match(page, /DashboardBookmarkButton/);
  assert.match(page, /dismissRecommendation/);
  assert.match(page, /new_only: query\.newOnly/);
});

test("Explorer cards use the supplied World Bank mark and canonical budget", () => {
  assert.match(page, /world-bank-supplied\.png/);
  // D1-05: one shared helper; null/zero budgets render the localized "Not published".
  assert.match(page, /formatBudget\(tender\.budget, tender\.currency, locale, truthLabels\.notPublished\)/);
  assert.doesNotMatch(page, /tender\.budget > 0/);
  assert.match(page, /className="explorer-card-budget"/);
});

test("Explorer cards use the supplied EBRD artwork without duplicate source captions", () => {
  assert.match(page, /ebrd-supplied\.png/);
  assert.match(page, /<Image src=\{logo\} alt=\{name\}/);
  assert.match(page, /data-source-logo="fallback"[\s\S]*?explorer-source-name/);
  assert.doesNotMatch(page, /<BidiText className="explorer-source-name">\{name\}<\/BidiText>\s*<\/div>/);
});

test("Explorer result cards omit description snippets", () => {
  assert.doesNotMatch(page, /explorer-card-summary|tender\.summary/);
  assert.match(page, /className="explorer-card-tags"/);
});
