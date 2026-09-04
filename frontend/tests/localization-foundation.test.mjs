import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createTranslator } from "next-intl";

import {
  CUSTOMER_SELECTABLE_LOCALES,
  DEFAULT_PRODUCT_LOCALE,
  LOCALE_REGISTRY,
  LOCALE_RESOLUTION_PRECEDENCE,
  LOCALIZATION_CONTENT_POLICY,
  MESSAGE_NAMESPACES,
  PRODUCT_LOCALE_CODES,
  UI_LOCALE_PERSISTENCE_FIELD,
  isCustomerSelectableLocale,
  resolveCustomerLocale,
  toCustomerSelectableLocale,
  toProductLocale,
} from "../i18n/locales.ts";
import {
  extractIcuPlaceholders,
  flattenMessageTree,
  validateMessageCatalogs,
} from "../i18n/messageValidation.ts";
import {
  parseAcceptLanguage,
  resolveRequestLocale,
} from "../i18n/requestLocale.ts";
import {
  INVALID_FORMAT_VALUE,
  formatCurrency,
  formatDate,
  formatDateTime,
  formatNumber,
  formatRelativeTime,
} from "../i18n/formatters.ts";
import { errorMessageKey, localizableErrorCode } from "../i18n/errors.ts";
import {
  tenderStatusMessageKey,
  translateTenderStatus,
} from "../i18n/enumLabels.ts";
import { commitUiLocaleChange } from "../i18n/localeAction.ts";

const readJson = (relative) =>
  JSON.parse(readFileSync(new URL(relative, import.meta.url), "utf8"));
const readText = (relative) =>
  readFileSync(new URL(relative, import.meta.url), "utf8");
const activeMessageNamespaces = [
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
    activeMessageNamespaces.map((namespace) => [
      namespace,
      readJson(`../messages/${locale}/${namespace}.json`),
    ]),
  );
const catalogs = { en: catalog("en"), uz: catalog("uz"), ru: catalog("ru") };

test("locale registry has one complete definition for every canonical product locale", () => {
  assert.deepEqual(PRODUCT_LOCALE_CODES, ["en", "uz", "ru", "ar"]);
  assert.deepEqual(Object.keys(LOCALE_REGISTRY), PRODUCT_LOCALE_CODES);
  for (const code of PRODUCT_LOCALE_CODES) {
    assert.equal(LOCALE_REGISTRY[code].code, code);
    assert.ok(LOCALE_REGISTRY[code].displayNameNative);
    assert.ok(LOCALE_REGISTRY[code].displayNameEnglish);
  }
});

test("English, Uzbek Latin, and Russian are selectable while Arabic remains gated", () => {
  assert.equal(DEFAULT_PRODUCT_LOCALE, "en");
  assert.deepEqual(CUSTOMER_SELECTABLE_LOCALES, ["en", "uz", "ru"]);
  assert.equal(LOCALE_REGISTRY.uz.displayNameNative, "O‘zbekcha");
  assert.equal(LOCALE_REGISTRY.ar.direction, "rtl");
  assert.equal(LOCALE_REGISTRY.ar.enabled, false);
  assert.equal(LOCALE_REGISTRY.ar.customerSelectable, false);
  assert.equal(isCustomerSelectableLocale("ar"), false);
  assert.equal(isCustomerSelectableLocale("ru"), true);
});

test("weighted Accept-Language parsing is robust and skips malformed entries", () => {
  assert.deepEqual(
    parseAcceptLanguage("de-DE, ru-RU;q=0.9, uz-Latn-UZ;q=0.8, en-US;q=0.2"),
    ["de-DE", "ru-RU", "uz-Latn-UZ", "en-US"],
  );
  assert.deepEqual(parseAcceptLanguage("ru;q=bogus, uz;q=0.7, *;q=1, en;q=0"), [
    "uz",
  ]);
  assert.equal(
    resolveRequestLocale({ acceptLanguage: "de,ru-RU;q=.oops,uz;q=0.5" }),
    "uz",
  );
});

test("request precedence is persisted user, cookie, request, then English", () => {
  assert.equal(
    resolveRequestLocale({
      persistedUserLocale: "ru",
      presentationCookie: "uz",
      acceptLanguage: "en-US",
    }),
    "ru",
  );
  assert.equal(
    resolveRequestLocale({ presentationCookie: "uz", acceptLanguage: "ru" }),
    "uz",
  );
  assert.equal(
    resolveRequestLocale({
      presentationCookie: "fr",
      acceptLanguage: "uz-Latn-UZ",
    }),
    "uz",
  );
  assert.equal(
    resolveRequestLocale({ presentationCookie: "ar", acceptLanguage: "de" }),
    "en",
  );
});

test("browser BCP-47 variants map to stable product identifiers", () => {
  assert.equal(toProductLocale("en-US"), "en");
  assert.equal(toProductLocale("uz-Latn-UZ"), "uz");
  assert.equal(toProductLocale("uz_Cyrl_UZ"), "uz");
  assert.equal(toProductLocale("RU-ru"), "ru");
  assert.equal(toProductLocale("ar-EG"), "ar");
  assert.equal(toProductLocale("de-DE"), null);
  assert.equal(toCustomerSelectableLocale("ar-EG"), null);
});

test("customer locale resolution is deterministic and saved preference wins", () => {
  assert.deepEqual(LOCALE_RESOLUTION_PRECEDENCE, [
    "persisted_user",
    "temporary_onboarding",
    "browser",
    "product_default",
  ]);
  assert.equal(
    resolveCustomerLocale({
      persistedUserLocale: "ru",
      temporaryOnboardingLocale: "uz",
      browserLocales: ["en-US"],
    }),
    "ru",
  );
  assert.equal(
    resolveCustomerLocale({
      persistedUserLocale: "unsupported",
      temporaryOnboardingLocale: "uz-UZ",
      browserLocales: ["ru-RU"],
    }),
    "uz",
  );
  assert.equal(
    resolveCustomerLocale({ browserLocales: ["ar-EG", "ru-RU"] }),
    "ru",
  );
  assert.equal(resolveCustomerLocale({ browserLocales: ["de-DE"] }), "en");
});

test("UI locale ownership and required message domains are explicit", () => {
  assert.equal(UI_LOCALE_PERSISTENCE_FIELD, "ui_locale");
  assert.deepEqual(MESSAGE_NAMESPACES, [
    "common",
    "navigation",
    "auth",
    "onboarding",
    "settings",
    "explorer",
    "tenderDetails",
    "myTenders",
    "bidPreparation",
    "dashboard",
    "compliance",
    "readiness",
    "documentViewer",
    "refresh",
    "errors",
  ]);
});

test("content policy translates presentation without mutating domain content", () => {
  assert.equal(LOCALIZATION_CONTENT_POLICY.product_ui, "translate");
  assert.equal(
    LOCALIZATION_CONTENT_POLICY.source_provided,
    "preserve_original",
  );
  assert.equal(LOCALIZATION_CONTENT_POLICY.user_generated, "preserve_original");
  assert.equal(
    LOCALIZATION_CONTENT_POLICY.ai_generated_analysis,
    "separate_sprint_8_language_authority",
  );
  assert.equal(
    LOCALIZATION_CONTENT_POLICY.enum_code,
    "preserve_code_translate_display_label",
  );
});

test("message validation prototype flattens semantic keys and understands ICU values", () => {
  const flattened = flattenMessageTree({
    refresh: {
      complete:
        "{count, plural, one {# new tender} other {# new tenders}} from {source}",
    },
  });
  assert.equal(
    flattened.get("refresh.complete"),
    "{count, plural, one {# new tender} other {# new tenders}} from {source}",
  );
  assert.deepEqual(extractIcuPlaceholders(flattened.get("refresh.complete")), [
    "count",
    "source",
  ]);
});

test("message validation detects missing, extra, and placeholder-mismatched keys", () => {
  const issues = validateMessageCatalogs(
    {
      common: { save: "Save" },
      refresh: { complete: "{count} new tenders from {source}" },
    },
    {
      uz: {
        common: { unexpected: "Ortiqcha" },
        refresh: { complete: "{count} ta yangi tender" },
      },
    },
  );

  assert.deepEqual(issues, [
    { locale: "uz", key: "common.save", kind: "missing_key" },
    {
      locale: "uz",
      key: "refresh.complete",
      kind: "placeholder_mismatch",
      expected: ["count", "source"],
      actual: ["count"],
    },
    { locale: "uz", key: "common.unexpected", kind: "extra_key" },
  ]);
});

test("committed English, Uzbek, and Russian catalogs have exact key and ICU parity", () => {
  assert.deepEqual(
    validateMessageCatalogs(catalogs.en, { uz: catalogs.uz, ru: catalogs.ru }),
    [],
  );
});

test("next-intl executes plural rules and named interpolation for all active locales", () => {
  const en = createTranslator({ locale: "en", messages: catalogs.en });
  const uz = createTranslator({ locale: "uz", messages: catalogs.uz });
  const ru = createTranslator({ locale: "ru", messages: catalogs.ru });

  assert.equal(en("common.tenderCount", { count: 1 }), "1 tender");
  assert.equal(en("common.tenderCount", { count: 2 }), "2 tenders");
  assert.equal(uz("common.tenderCount", { count: 2 }), "2 ta tender");
  assert.equal(ru("common.tenderCount", { count: 1 }), "1 тендер");
  assert.equal(ru("common.tenderCount", { count: 2 }), "2 тендера");
  assert.equal(ru("common.tenderCount", { count: 5 }), "5 тендеров");
  assert.equal(
    uz("common.newTendersFromSource", { count: 3, source: "World Bank" }),
    "World Bank: 3 ta yangi tender",
  );
  assert.equal(
    en("common.newTendersFromSource", { count: 3, source: "World Bank" }),
    "3 new tenders from World Bank",
  );
});

test("rich messages keep dynamic source values as escaped text", () => {
  const translate = createTranslator({ locale: "en", messages: catalogs.en });
  const markup = renderToStaticMarkup(
    createElement(
      "p",
      null,
      translate.rich("common.richReview", {
        source: "<img src=x onerror=alert(1)>",
        strong: (chunks) => createElement("strong", null, chunks),
      }),
    ),
  );
  assert.match(markup, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(markup, /<img/);
});

test("formatters localize representation while preserving UTC and economic inputs", () => {
  const timestamp = "2026-09-02T12:34:00Z";
  const dates = ["en", "uz", "ru"].map((locale) =>
    formatDate(timestamp, locale),
  );
  assert.equal(new Set(dates).size >= 2, true);
  assert.match(formatDateTime(timestamp, "en"), /12:34/);
  assert.notEqual(formatNumber(12345.67, "en"), formatNumber(12345.67, "ru"));
  assert.equal(formatNumber(0, "uz").includes("0"), true);
  assert.equal(formatNumber(-1000, "ru").includes("1"), true);

  for (const currency of ["USD", "UZS", "EUR"]) {
    const formatted = ["en", "uz", "ru"].map((locale) =>
      formatCurrency(1234.5, currency, locale),
    );
    assert.ok(formatted.every((value) => value.includes("1")));
  }
  assert.match(
    formatRelativeTime("2026-09-02T12:29:00Z", timestamp, "en"),
    /5 minutes ago/,
  );
  assert.match(
    formatRelativeTime("2026-09-02T12:29:00Z", timestamp, "ru"),
    /5 минут назад/,
  );
});

test("formatters never expose Invalid Date or NaN", () => {
  for (const result of [
    formatDate(null, "en"),
    formatDate("not-a-date", "uz"),
    formatNumber(Number.NaN, "ru"),
    formatCurrency(10, "invalid", "en"),
    formatRelativeTime("invalid", new Date(), "en"),
  ])
    assert.equal(result, INVALID_FORMAT_VALUE);
});

test("enum display and stable error-code foundations preserve canonical payloads", () => {
  assert.equal(tenderStatusMessageKey("OPEN"), "tenderStatus.open");
  assert.equal(tenderStatusMessageKey("FUTURE_CODE"), "tenderStatus.unknown");
  assert.equal(
    translateTenderStatus("CLOSED", (key) => `label:${key}`),
    "label:tenderStatus.closed",
  );
  assert.equal(
    localizableErrorCode("unsupported_ui_locale"),
    "unsupported_ui_locale",
  );
  assert.equal(localizableErrorCode("backend English prose"), null);
  assert.equal(errorMessageKey("unknown"), "generic");
});

test("runtime integration is locale-neutral, request-scoped, and bundle-conscious", () => {
  const layout = readText("../app/layout.tsx");
  const middleware = readText("../middleware.ts");
  const loader = readText("../i18n/messages.ts");
  const request = readText("../i18n/request.ts");
  const localeAction = readText("../i18n/userLocale.ts");
  const refreshProvider = readText(
    "../components/source-refresh/SourceRefreshProvider.tsx",
  );

  assert.match(layout, /<html lang=\{locale\}>/);
  assert.doesNotMatch(layout, /suppressHydrationWarning/);
  assert.match(
    layout,
    /NextIntlClientProvider locale=\{locale\} messages=\{messages\}/,
  );
  assert.match(middleware, /cache: 'no-store'/);
  assert.match(middleware, /PERSISTED_UI_LOCALE_HEADER/);
  assert.match(
    request,
    /persistedUserLocale.*presentationCookie.*acceptLanguage/s,
  );
  assert.equal((loader.match(/import\('\.\.\/messages\//g) ?? []).length, 3);
  assert.doesNotMatch(localeAction, /localStorage|window\.location/);
  assert.match(localeAction, /router\.refresh\(\)/);
  assert.match(
    refreshProvider,
    /translateRefreshRef\.current = translateRefresh/,
  );
  assert.doesNotMatch(refreshProvider, /key=\{.*locale/);
});

test("successful locale action persists, reconciles cookie, then refreshes in order", async () => {
  const calls = [];
  const result = await commitUiLocaleChange(
    "uz",
    { refresh: () => calls.push("refresh") },
    async (locale) => {
      calls.push(`persist:${locale}`);
      return { ui_locale: locale };
    },
    async (locale) => {
      calls.push(`cookie:${locale}`);
    },
  );
  assert.deepEqual(result, { ui_locale: "uz" });
  assert.deepEqual(calls, ["persist:uz", "cookie:uz", "refresh"]);
});

test("failed locale save leaves cookie and rendered locale untouched", async () => {
  const calls = [];
  await assert.rejects(
    commitUiLocaleChange(
      "ru",
      { refresh: () => calls.push("refresh") },
      async () => {
        throw new Error("save failed");
      },
      async () => {
        calls.push("cookie");
      },
    ),
    /save failed/,
  );
  assert.deepEqual(calls, []);
});
