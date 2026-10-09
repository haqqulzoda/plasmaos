import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  invitationErrorKey,
  invitationLink,
  invitationTone,
  memberTone,
  pendingInvitations,
  sortMembers,
} from "../lib/team.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");
const LOCALES = ["en", "ru", "uz", "ar"];

const flatten = (value, prefix = "") =>
  Object.entries(value).flatMap(([key, item]) =>
    item && typeof item === "object" ? flatten(item, `${prefix}${key}.`) : [`${prefix}${key}`],
  );

const invitation = (status, values = {}) => ({
  invitation_id: `i-${status}`, organization_id: "o", email: `${status.toLowerCase()}@example.org`, role: "MEMBER",
  status, expires_at: "2026-10-22T00:00:00Z", created_at: "2026-10-08T00:00:00Z",
  last_sent_at: "2026-10-08T00:00:00Z", send_count: 1, ...values,
});

test("the copied link prefers the configured URL and falls back to this origin", () => {
  assert.equal(invitationLink({ invite_url: "https://app.example/invite/abc", invite_path: "/invite/abc" }, "http://x"), "https://app.example/invite/abc");
  assert.equal(invitationLink({ invite_url: null, invite_path: "/invite/abc" }, "http://localhost:3100/"), "http://localhost:3100/invite/abc");
  // A listed invitation never carries a link: copying requires a fresh one.
  assert.equal(invitationLink({ invite_url: null, invite_path: null }, "http://x"), null);
});

test("pending invitations are open or expired; accepted and revoked are history", () => {
  const all = ["OPEN", "EXPIRED", "ACCEPTED", "REVOKED"].map((status) => invitation(status));
  assert.deepEqual(pendingInvitations(all).map((item) => item.status), ["OPEN", "EXPIRED"]);
  assert.deepEqual(["OPEN", "EXPIRED", "ACCEPTED", "REVOKED"].map(invitationTone), ["success", "warning", "neutral", "danger"]);
  assert.deepEqual(["ACTIVE", "INVITED", "REVOKED"].map(memberTone), ["success", "warning", "neutral"]);
});

test("members sort active first, owners before members, then by name", () => {
  const member = (id, state, role, name) => ({ membership_id: id, organization_id: "o", user_id: id, state, role, created_at: "", user_name: name });
  const sorted = sortMembers([
    member("1", "REVOKED", "OWNER", "Zed"), member("2", "ACTIVE", "MEMBER", "Bea"),
    member("3", "ACTIVE", "OWNER", "Cy"), member("4", "INVITED", "MEMBER", "Al"), member("5", "ACTIVE", "MEMBER", "Ann"),
  ]);
  assert.deepEqual(sorted.map((item) => item.membership_id), ["3", "5", "2", "4", "1"]);
});

test("backend refusals map to translated messages", () => {
  const failure = (status, detail) => ({ response: { status, data: { detail } } });
  assert.equal(invitationErrorKey(failure(409, { code: "ALREADY_MEMBER" })), "alreadyMember");
  assert.equal(invitationErrorKey(failure(409, { code: "ALREADY_INVITED" })), "alreadyInvited");
  assert.equal(invitationErrorKey(failure(409, { code: "TOO_MANY_OPEN" })), "tooMany");
  assert.equal(invitationErrorKey(failure(403, { code: "EMAIL_MISMATCH" })), "emailMismatch");
  assert.equal(invitationErrorKey(failure(422, "a valid e-mail address is required")), "invalidEmail");
  assert.equal(invitationErrorKey(failure(403, "OWNER membership required")), "ownerOnly");
  assert.equal(invitationErrorKey(failure(409, "final active OWNER cannot be revoked")), "lastOwner");
  assert.equal(invitationErrorKey(new Error("network")), "failed");
});

test("team and invite messages exist with the same keys in every locale", () => {
  const team = (locale) => JSON.parse(read(`messages/${locale}/settings.json`)).team;
  const invite = (locale) => JSON.parse(read(`messages/${locale}/auth.json`)).invite;
  const teamKeys = flatten(team("en")).sort();
  const inviteKeys = flatten(invite("en")).sort();
  for (const locale of LOCALES) {
    assert.deepEqual(flatten(team(locale)).sort(), teamKeys, locale);
    assert.deepEqual(flatten(invite(locale)).sort(), inviteKeys, locale);
  }
  const source = read("components/team/TeamSection.tsx");
  for (const key of teamKeys.filter((key) => !/\.(OWNER|MEMBER|ACTIVE|INVITED|REVOKED|OPEN|EXPIRED|ACCEPTED)$/.test(key) && !key.startsWith("errors."))) {
    const leaf = key.split(".").pop();
    assert.ok(source.includes(`'${key}'`) || source.includes(`'${leaf}'`) || source.includes(key), `unused team key ${key}`);
  }
});

test("the Team section sits on Company & Experience and the preview is the only public invitation API", () => {
  assert.match(read("app/dashboard/settings/page.tsx"), /<TeamSection \/>/);
  const proxy = read("proxy.ts");
  assert.match(proxy, /'\/api\/v1\/invitations\/preview'/);
  assert.doesNotMatch(proxy, /'\/api\/v1\/invitations\/accept'/);
  // /invite/* is outside the proxy matcher: the landing page loads before sign-in.
  assert.doesNotMatch(proxy, /'\/invite/);
  const page = read("app/invite/[token]/page.tsx");
  assert.match(page, /callbackUrl: returnUrl/);
  assert.match(page, /acceptInvitation\(token\)/);
});
