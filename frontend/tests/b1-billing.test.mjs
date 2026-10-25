import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { BILLING_ERROR_CODES, billingErrorCode, billingErrorKey, parseMarkdown, productFrom } from "../lib/billing.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");
const json = (path) => JSON.parse(read(path));

test("checkout accepts only the products sold in the app", () => {
  assert.deepEqual(["pilot", "pursuit_desk", "extra_pursuit"].map(productFrom), ["pilot", "pursuit_desk", "extra_pursuit"]);
  for (const value of ["agent", "enterprise", "", null, undefined, "pilot "]) assert.equal(productFrom(value), null);
});

test("billing errors map to explained codes, anything else to generic", () => {
  const error = (code) => ({ response: { data: { detail: { code, message: "x" } } } });
  assert.equal(billingErrorCode(error("terms_changed")), "terms_changed");
  assert.equal(billingErrorKey(billingErrorCode(error("terms_changed"))), "terms_changed");
  assert.equal(billingErrorKey(billingErrorCode(error("something_new"))), "generic");
  assert.equal(billingErrorKey(billingErrorCode({ response: { data: { detail: "plain" } } })), "generic");
});

test("the terms render as text blocks: headings, paragraphs, lists, bold; no HTML", () => {
  const blocks = parseMarkdown("# Title\n\nA **bold** and *soft* line\ncontinues.\n\n- one\n- two <b>x</b>\n\n## Part");
  assert.deepEqual(blocks.map((block) => block.kind), ["h1", "p", "ul", "h2"]);
  assert.deepEqual(blocks[1].inline, [{ text: "A " }, { text: "bold", strong: true }, { text: " and " }, { text: "soft", em: true },
    { text: " line continues." }]);
  assert.equal(blocks[2].items[1][0].text, "two <b>x</b>");
  const table = parseMarkdown(["| Plan | Price |", "|---|---|", "| **Pilot** | USD 900 |", "", "---", "", "After."].join(String.fromCharCode(10)));
  assert.deepEqual(table.map((block) => block.kind), ["table", "hr", "p"]);
  assert.deepEqual(table[0].header.map((cell) => cell[0].text), ["Plan", "Price"]);
  assert.deepEqual(table[0].rows[0][0], [{ text: "Pilot", strong: true }]);
  const terms = parseMarkdown(read("../docs/legal/PILOT_TERMS_v1.md"));
  assert.equal(terms[0].kind, "h1");
  assert.ok(terms.some((block) => block.kind === "ul"));
  // The owner-approved terms: the plan table (4 plans), the order form and the signature block.
  const tables = terms.filter((block) => block.kind === "table");
  assert.equal(tables.length, 3);
  assert.deepEqual(tables[0].rows.map((row) => row[0][0].text), ["Pilot", "Pursuit Desk", "Per-tender review", "Extra pursuit"]);
  assert.doesNotMatch(read("components/billing/BillingParts.tsx"), /dangerouslySetInnerHTML/);
});

test("every locale carries the billing strings with the same placeholders", () => {
  const en = json("messages/en/dashboard.json").billing;
  const flatten = (value, prefix = "") => Object.entries(value).flatMap(([key, item]) =>
    typeof item === "string" ? [[`${prefix}${key}`, item]] : flatten(item, `${prefix}${key}.`));
  const placeholders = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
  const english = new Map(flatten(en));
  for (const code of BILLING_ERROR_CODES) assert.ok(english.has(`start.errors.${code}`), code);
  for (const locale of ["ru", "uz", "ar"]) {
    const other = new Map(flatten(json(`messages/${locale}/dashboard.json`).billing));
    assert.deepEqual([...other.keys()].sort(), [...english.keys()].sort(), locale);
    for (const [key, text] of english) assert.deepEqual(placeholders(other.get(key)), placeholders(text), `${locale} ${key}`);
    assert.ok(json(`messages/${locale}/navigation.json`).billing, locale);
  }
});

test("checkout, notices, explore and admin are wired", () => {
  const start = read("app/dashboard/billing/start/page.tsx");
  assert.match(start, /api\.put\('\/billing\/customer'/);
  assert.match(start, /terms_version: terms\.version, terms_sha256: terms\.sha256, accept_terms: accepted/);
  assert.match(start, /window\.location\.assign\(response\.data\.checkout_url\)/);
  // No session refresh in the billing pages: it re-renders the layout and would unmount the confirmation.
  assert.doesNotMatch(start, /await update\(\)/);
  assert.doesNotMatch(read("app/dashboard/billing/success/page.tsx"), /useSession/);
  assert.match(read("app/dashboard/billing/success/page.tsx"), /api\.get<OrderStatus>\('\/billing\/orders', \{ params: \{ checkout_id: checkoutId \} \}\)/);
  assert.match(read("app/billing/start/page.tsx"), /redirect\(value \? `\/dashboard\/billing\/start\?plan=\$\{encodeURIComponent\(value\)\}`/);
  assert.match(read("app/dashboard/layout.tsx"), /const BILLING_PREFIX = '\/dashboard\/billing';/);
  assert.match(read("app/dashboard/layout.tsx"), /!pathname\.startsWith\(BILLING_PREFIX\)/);
  assert.match(read("app/dashboard/explore/page.tsx"), /href="\/dashboard\/billing\/start\?plan=pilot"/);
  assert.match(read("components/plans/PlanNotice.tsx"), /<BillingNotice summary=\{plan\.billing\} \/>/);
  const notice = read("components/billing/BillingParts.tsx");
  for (const kind of ["suspended", "awaiting_payment", "annual_offer"]) assert.match(notice, new RegExp(`data-billing-notice="${kind}"`));
  assert.match(read("components/shell/AdminShell.tsx"), /href: '\/admin\/billing'/);
  const admin = read("app/admin/billing/page.tsx");
  for (const path of ["/mark-paid", "/refund", "/override", "/onboarding/"]) assert.ok(admin.includes(path), path);
  assert.match(read("app/admin/audit/page.tsx"), /'BILLING_PLAN_ACTIVATED'/);
});
