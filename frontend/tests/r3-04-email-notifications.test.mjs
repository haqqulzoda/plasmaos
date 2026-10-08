import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { SYSTEM_TEMPLATE_KEYS, knownSystemTemplate, notificationDestination } from "../lib/communications.ts";
import { EMAIL_PREFERENCE_FIELDS, emailPreferenceChanges } from "../lib/emailPreferences.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");
const LOCALES = ["en", "ru", "uz", "ar"];
const ORG = "11111111-1111-4111-8111-111111111111";
const PURSUIT = "22222222-2222-4222-8222-222222222222";

const item = (event_type, payload) => ({
  id: "d", event_id: "e", category: "SYSTEM", event_type, template_key: null, payload, subject: null, body: null,
  message_type: null, content_format: "plain_text", is_test: false, created_at: "", read_at: null, is_read: false,
});

test("only changed switches are saved", () => {
  const saved = { email_channel_enabled: true, analysis_enabled: true, eoi_enabled: true, digest_enabled: true, digest_schedule: "08:00 Asia/Tashkent" };
  assert.deepEqual(emailPreferenceChanges(saved, { ...saved }), {});
  assert.deepEqual(emailPreferenceChanges(saved, { ...saved, digest_enabled: false }), { digest_enabled: false });
  assert.deepEqual(EMAIL_PREFERENCE_FIELDS.map((entry) => entry.field), ["analysis_enabled", "eoi_enabled", "digest_enabled"]);
});

test("analysis and EOI events open the pursuit on the right tab; unsafe payloads open nothing", () => {
  const payload = { organization_id: ORG, pursuit_id: PURSUIT, analysis_run_id: "33333333-3333-4333-8333-333333333333" };
  assert.equal(notificationDestination(item("PURSUIT_ANALYSIS_COMPLETED", payload)).href,
    `/dashboard/pursuits/${PURSUIT}?organization_id=${ORG}&tab=requirements`);
  assert.match(notificationDestination(item("PURSUIT_ANALYSIS_FAILED", payload)).href, /tab=requirements$/);
  assert.match(notificationDestination(item("EOI_DRAFT_READY", { ...payload, eoi_draft_id: PURSUIT, version_number: 2 })).href, /tab=eoi$/);
  assert.equal(notificationDestination(item("EOI_DRAFT_READY", { pursuit_id: "../admin", organization_id: ORG })), null);
  for (const key of ["notifications.pursuit_analysis_completed", "notifications.pursuit_analysis_failed", "notifications.eoi_draft_ready"]) {
    assert.ok(knownSystemTemplate(key), key);
  }
});

test("every in-app template and the e-mail settings are translated in all locales", () => {
  for (const locale of LOCALES) {
    const templates = JSON.parse(read(`messages/${locale}/notifications.json`)).templates;
    for (const name of Object.values(SYSTEM_TEMPLATE_KEYS)) {
      assert.ok(templates[name]?.title && templates[name]?.body, `${locale}.${name}`);
    }
    assert.match(templates.eoiDraftReady.body, /\{versionNumber\}/, locale);
    const email = JSON.parse(read(`messages/${locale}/settings.json`)).emailNotifications;
    assert.deepEqual(Object.keys(email).sort(), Object.keys(JSON.parse(read("messages/en/settings.json")).emailNotifications).sort(), locale);
    assert.match(email.digestHelp, /\{time\}/, locale);
  }
});

test("Settings shows the e-mail section, which reads passively and saves changes only", () => {
  assert.match(read("app/dashboard/settings/page.tsx"), /<EmailNotificationSettings \/>/);
  const section = read("components/settings/EmailNotificationSettings.tsx");
  assert.match(section, /api\.get<EmailPreferences>\('\/users\/me\/email-preferences'\)/);
  assert.match(section, /api\.put<EmailPreferences>\('\/users\/me\/email-preferences', changes\)/);
  assert.match(section, /id="email-notifications"/);
});
