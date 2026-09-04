import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createTranslator } from "next-intl";

import {
  CUSTOMER_SELECTABLE_LOCALES,
  LOCALE_REGISTRY,
} from "../i18n/locales.ts";
import {
  flattenMessageTree,
  validateMessageCatalogs,
} from "../i18n/messageValidation.ts";

const read = (path) =>
  readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const readJson = (path) => JSON.parse(read(path));
const namespaces = [
  "auth",
  "bidPreparation",
  "common",
  "errors",
  "explorer",
  "myTenders",
  "navigation",
  "onboarding",
  "refresh",
  "settings",
  "tenderDetails",
];
const catalog = (locale) =>
  Object.fromEntries(
    namespaces.map((namespace) => [
      namespace,
      readJson(`messages/${locale}/${namespace}.json`),
    ]),
  );
const catalogs = Object.fromEntries(
  CUSTOMER_SELECTABLE_LOCALES.map((locale) => [locale, catalog(locale)]),
);

test("P0 catalogs have complete EN/UZ/RU key and placeholder coverage", () => {
  assert.deepEqual(
    validateMessageCatalogs(catalogs.en, {
      uz: catalogs.uz,
      ru: catalogs.ru,
    }),
    [],
  );
  const expected = flattenMessageTree(catalogs.en).size;
  assert.ok(expected > 250);
  for (const locale of CUSTOMER_SELECTABLE_LOCALES) {
    assert.equal(flattenMessageTree(catalogs[locale]).size, expected);
  }
});

test("the only customer selector is registry-driven, accessible, and Arabic-gated", () => {
  const selector = read("components/i18n/LanguageSelector.tsx");
  assert.deepEqual(CUSTOMER_SELECTABLE_LOCALES, ["en", "uz", "ru"]);
  assert.deepEqual(
    CUSTOMER_SELECTABLE_LOCALES.map(
      (locale) => LOCALE_REGISTRY[locale].displayNameNative,
    ),
    ["English", "O‘zbekcha", "Русский"],
  );
  assert.equal(LOCALE_REGISTRY.ar.customerSelectable, false);
  assert.match(selector, /CUSTOMER_SELECTABLE_LOCALES\.map/);
  assert.match(selector, /role="radiogroup"/);
  assert.match(selector, /role="radio"/);
  assert.match(selector, /aria-checked=\{selected\}/);
  assert.doesNotMatch(selector, /flag|emoji|العربية|LOCALE_REGISTRY\.ar/i);
});

test("onboarding and settings expose one selector before editable form content", () => {
  for (const [path, surface] of [
    ["app/dashboard/onboarding/page.tsx", "onboarding"],
    ["app/dashboard/settings/page.tsx", "settings"],
  ]) {
    const source = read(path);
    const selector = `<LanguageSelector surface="${surface}" />`;
    assert.equal(source.split(selector).length - 1, 1);
    assert.ok(source.indexOf(selector) < source.indexOf("<form"));
  }
});

test("locale changes are persist-first and preserve route and mounted state", () => {
  const selector = read("components/i18n/LanguageSelector.tsx");
  const action = read("i18n/localeAction.ts");
  assert.match(selector, /await applyUiLocale\(locale, router\)/);
  assert.match(selector, /catch \(requestError\)/);
  assert.match(action, /const preference = await persist\(locale\)/);
  assert.ok(
    action.indexOf("await persist(locale)") <
      action.indexOf("router.refresh()"),
  );
  assert.doesNotMatch(
    `${selector}\n${action}`,
    /router\.(push|replace)|location\.href|localStorage/,
  );
});

test("P0 pages use translations and shared locale formatters", () => {
  const files = [
    "app/dashboard/tenders/page.tsx",
    "app/dashboard/tenders/[tenderId]/page.tsx",
    "app/dashboard/my-tenders/page.tsx",
    "app/dashboard/bid-preparation/page.tsx",
    "app/dashboard/bid-preparation/[proposalId]/page.tsx",
  ];
  for (const path of files) {
    const source = read(path);
    assert.match(source, /useTranslations\(/, path);
    assert.match(
      source,
      /format(Date|DateTime|Number|Currency|RelativeTime)/,
      path,
    );
  }
});

test("canonical query, enum, and action codes remain untranslated", () => {
  const explorer = read("app/dashboard/tenders/page.tsx");
  const myTenders = read("app/dashboard/my-tenders/page.tsx");
  const actions = read("components/tenders/EngagementWorkflowActions.tsx");
  for (const code of ["all", "recommended", "dismissed", "new_only"])
    assert.match(explorer, new RegExp(`[\"']${code}[\"']`));
  for (const code of [
    "SAVED",
    "EVALUATING",
    "PREPARING",
    "SUBMITTED",
    "WON",
    "LOST",
    "DISMISSED",
  ])
    assert.match(`${myTenders}\n${actions}`, new RegExp(`[\"']${code}[\"']`));
  assert.match(actions, /expected_status: engagement\.engagement_status/);
});

test("source, user, Proposal, and AI narrative fields remain original", () => {
  const explorer = read("app/dashboard/tenders/page.tsx");
  const details = read("app/dashboard/tenders/[tenderId]/page.tsx");
  const recommendation = read("components/tenders/RecommendationSummary.tsx");
  const workspace = read("app/dashboard/bid-preparation/[proposalId]/page.tsx");
  assert.match(explorer, /\{tender\.title\}/);
  assert.match(details, /tender\.description \|\| t\("descriptionMissing"\)/);
  assert.match(details, /\{item\.label\}/);
  assert.match(recommendation, /\{recommendation\.rationale_summary\}/);
  assert.match(workspace, /value=\{strategicSummary\}/);
  assert.doesNotMatch(
    `${explorer}\n${details}\n${recommendation}\n${workspace}`,
    /(?:^|[^A-Za-z])t\((tender\.title|tender\.description|item\.label|recommendation\.rationale_summary|strategicSummary)/,
  );
});

test("refresh copy is translated without resetting the active poller or source names", () => {
  const provider = read("components/source-refresh/SourceRefreshProvider.tsx");
  const menu = read("components/source-refresh/SourceRefreshMenu.tsx");
  const policy = read("lib/sourceRefreshPolicy.ts");
  assert.match(provider, /translateRefreshRef\.current = translateRefresh/);
  assert.match(
    provider,
    /translateRefreshRef\.current\("(queuedNotice|startedNotice)"/,
  );
  assert.doesNotMatch(provider, /key=\{.*locale/);
  assert.match(menu, /useTranslations\("refresh"\)/);
  assert.match(policy, /RefreshPresentationTranslator/);
  assert.match(provider, /source\.display_name|data\.display_name/);
});

test("new badge and high-significance actions have localized accessible copy", () => {
  const badge = read("components/tenders/NewTenderBadge.tsx");
  const actions = read("components/tenders/EngagementWorkflowActions.tsx");
  assert.match(badge, /useTranslations\("explorer"\)/);
  assert.match(badge, /title=\{t\("newRecent"\)\}/);
  assert.match(actions, /aria-labelledby="engagement-confirm-title"/);
  for (const key of ["submittedConfirm", "wonConfirm", "lostConfirm"])
    assert.match(actions, new RegExp(`t\\(\"${key}\"\\)`));
});

test("claim-safe terminology renders natively in all P0 locales", () => {
  const expected = {
    en: ["Tender Explorer", "Match score", "Compliance"],
    uz: ["Tenderlar katalogi", "Moslik bali", "Muvofiqlik tahlili"],
    ru: ["Каталог тендеров", "Оценка соответствия", "Анализ соответствия"],
  };
  for (const locale of CUSTOMER_SELECTABLE_LOCALES) {
    const t = createTranslator({ locale, messages: catalogs[locale] });
    assert.equal(t("explorer.title"), expected[locale][0]);
    assert.equal(t("explorer.recommendation.matchScore"), expected[locale][1]);
    assert.ok(t("tenderDetails.compliance").includes(expected[locale][2]));
    assert.doesNotMatch(
      [
        t("explorer.recommendation.matchScore"),
        t("explorer.recommendation.why"),
        t("refresh.partial", { source: "World Bank", count: 2 }),
      ].join(" "),
      /guaranteed|win probability|approved|fully live/i,
    );
  }
});
