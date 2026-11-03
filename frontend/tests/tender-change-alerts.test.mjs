import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { SYSTEM_TEMPLATE_KEYS, knownSystemTemplate, notificationDestination } from "../lib/communications.ts";
import { TENDER_CHANGE_KINDS, tenderChangeKinds } from "../lib/tenderChanged.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");
const LOCALES = ["en", "ru", "uz", "ar"];
const ORG = "11111111-1111-4111-8111-111111111111";
const PURSUIT = "22222222-2222-4222-8222-222222222222";

const item = (payload) => ({
  id: "d", event_id: "e", category: "TENDER_ALERT", event_type: "TENDER_CHANGED", template_key: "notifications.tender_changed",
  payload, subject: null, body: null, message_type: null, content_format: "plain_text", is_test: false,
  created_at: "", read_at: null, is_read: false,
});

test("a tender-change notice opens the pursuit's analysis; unsafe payloads open nothing", () => {
  const payload = { organization_id: ORG, pursuit_id: PURSUIT, tender_id: PURSUIT, tender_change_id: ORG, change_kinds: ["DEADLINE"] };
  assert.deepEqual(notificationDestination(item(payload)), {
    href: `/dashboard/pursuits/${PURSUIT}?organization_id=${ORG}&tab=requirements`, labelKey: "openWorkspace",
  });
  assert.equal(notificationDestination(item({ ...payload, pursuit_id: "../admin" })), null);
  assert.ok(knownSystemTemplate("notifications.tender_changed"));
  assert.equal(SYSTEM_TEMPLATE_KEYS["notifications.tender_changed"], "tenderChanged");
});

test("change kinds keep a stable order and drop unknown codes", () => {
  assert.deepEqual(tenderChangeKinds(["DOCUMENT", "NEW_THING", "DEADLINE"]), ["DEADLINE", "DOCUMENT"]);
  assert.deepEqual(tenderChangeKinds(undefined), []);
});

test("the notice and the out-of-date banner are translated in every locale", () => {
  for (const locale of LOCALES) {
    const notice = JSON.parse(read(`messages/${locale}/notifications.json`)).templates.tenderChanged;
    assert.ok(notice?.title && notice?.body, locale);
    const requirements = JSON.parse(read(`messages/${locale}/pursuits.json`)).requirements;
    assert.ok(requirements.tenderChangedTitle, locale);
    assert.match(requirements.tenderChangedHelp, /\{changes\}/, locale);
    assert.deepEqual(Object.keys(requirements.tenderChangeKinds).sort(), [...TENDER_CHANGE_KINDS].sort(), locale);
  }
});

test("the Requirements screen shows the banner only for a completed analysis the tender change made stale", () => {
  const requirements = read("components/pursuits/PursuitRequirements.tsx");
  assert.match(requirements, /analysis\.status === 'COMPLETED' && analysis\.tender_changed && <div className="analysis-stale"/);
  assert.match(requirements, /tenderChangeKinds\(analysis\.tender_change_kinds\)/);
});
