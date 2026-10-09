import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  errorTrackingConfig,
  scrubBreadcrumb,
  scrubEvent,
  scrubText,
  sentryOptions,
} from "../lib/errorTracking.ts";

const DOCUMENT_TEXT =
  "The Consultant shall deliver the feasibility study for the Tashkent water network rehabilitation, including hydraulic modelling of zones 4-7.";
const EMAIL = "jane.doe@client-firm.example";
const JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEyMyJ9.c2lnbmF0dXJlLXZhbHVlLWZvci10ZXN0cw";
const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

test("without SENTRY_DSN_FRONTEND error tracking is off and the SDK is never loaded", () => {
  assert.equal(errorTrackingConfig({}), null);
  assert.equal(errorTrackingConfig({ SENTRY_DSN_FRONTEND: "  " }), null);
  const instrumentation = read("instrumentation.ts");
  const client = read("components/ErrorReporting.tsx");
  // Only dynamic imports, behind the configuration check: no static SDK import anywhere.
  for (const source of [instrumentation, client, read("app/layout.tsx"), read("lib/errorTracking.ts")]) {
    assert.doesNotMatch(source, /^import .*@sentry/m);
  }
  assert.match(instrumentation, /if \(!config\) return;\s*const Sentry = await import\('@sentry\/nextjs'\)/);
  assert.match(instrumentation, /if \(!enabled\) return;/);
  assert.match(client, /if \(!dsn \|\| !environment\) return;/);
  assert.match(read("app/layout.tsx"), /<ErrorReporting config=\{errorTrackingConfig\(\)\} \/>/);
});

test("release is the build SHA and environment is ENVIRONMENT", () => {
  const config = errorTrackingConfig({
    SENTRY_DSN_FRONTEND: "https://public@o1.ingest.sentry.io/2",
    PLASMA_BUILD_SHA: "4f09b8e1cf1be6a9c6c8ef5c63a6ef2b8af37c2d",
    ENVIRONMENT: "production",
  });
  assert.deepEqual(config, {
    dsn: "https://public@o1.ingest.sentry.io/2",
    release: "4f09b8e1cf1be6a9c6c8ef5c63a6ef2b8af37c2d",
    environment: "production",
  });
  assert.equal(errorTrackingConfig({ SENTRY_DSN_FRONTEND: "x", PLASMA_BUILD_SHA: "unknown" }).release, undefined);
  const options = sentryOptions(config);
  assert.equal(options.sendDefaultPii, false);
  assert.equal(options.tracesSampleRate, 0);
  assert.equal(options.beforeSendTransaction(), null);
});

test("scrubText redacts e-mail addresses, tokens and document text", () => {
  const scrubbed = scrubText(
    `upload failed for ${EMAIL}: Authorization: Bearer abcdefghijklmnop1234 token=${JWT} password='hunter22' ` +
      `https://user:secret@api.example/x '${DOCUMENT_TEXT}'`,
    10_000,
  );
  for (const secret of [EMAIL, "abcdefghijklmnop1234", JWT, "hunter22", "secret@", DOCUMENT_TEXT.slice(0, 30)]) {
    assert.ok(!scrubbed.includes(secret), secret);
  }
  assert.ok(!scrubText(DOCUMENT_TEXT).includes("hydraulic modelling"));
  assert.equal(scrubText("Tender 7f0c3a52-0d7c-4b61-9b8e-2b1d8c6b0a11 not found"), "Tender 7f0c3a52-0d7c-4b61-9b8e-2b1d8c6b0a11 not found");
  assert.ok(scrubText("ab1 ".repeat(2000)).endsWith("…[truncated]"));
});

test("scrubEvent drops bodies, cookies, auth headers, query strings, user and local variables", () => {
  const event = scrubEvent({
    request: {
      method: "POST",
      url: `https://app.example/dashboard/pursuits/7?email=${EMAIL}`,
      data: DOCUMENT_TEXT,
      cookies: { "authjs.session-token": JWT },
      headers: { Authorization: `Bearer ${JWT}`, Cookie: "a=b", "User-Agent": "node" },
    },
    user: { email: EMAIL, ip_address: "10.0.0.1" },
    exception: { values: [{ type: "TypeError", value: `cannot render '${DOCUMENT_TEXT}'`, stacktrace: { frames: [{ vars: { text: DOCUMENT_TEXT } }] } }] },
    breadcrumbs: [{ category: "fetch", message: `GET ${EMAIL}`, data: { url: "/api/v1/pursuits/7?token=abc", body: DOCUMENT_TEXT } }],
    extra: { notice_text: DOCUMENT_TEXT, pursuitId: "7" },
  });
  const dumped = JSON.stringify(event);
  for (const secret of [DOCUMENT_TEXT.slice(0, 30), EMAIL, JWT, "a=b", "10.0.0.1", "token=abc"]) {
    assert.ok(!dumped.includes(secret), secret);
  }
  assert.deepEqual(event.request, { method: "POST", url: "https://app.example/dashboard/pursuits/7", headers: { "User-Agent": "node" } });
  assert.equal(event.user, undefined);
  assert.equal(event.exception.values[0].type, "TypeError");
  assert.equal(event.exception.values[0].stacktrace.frames[0].vars, undefined);
  assert.deepEqual(event.extra, { notice_text: "[Filtered]", pursuitId: "7" });
  assert.equal(scrubBreadcrumb({ data: { url: "https://u:p@host/a?b=c" } }).data.url, "https://host/a");
});
