import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { AUTH_ERROR_KINDS, authErrorKind } from "../lib/authError.ts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");

test("Auth.js error codes map to an explanation; anything else is the default", () => {
  assert.equal(authErrorKind("Configuration"), "configuration");
  assert.equal(authErrorKind("AccessDenied"), "accessDenied");
  assert.equal(authErrorKind("Verification"), "verification");
  for (const value of [null, undefined, "", "OAuthCallback", "<script>"]) assert.equal(authErrorKind(value), "default");
});

test("Auth.js sends sign-in errors to our page, outside the authenticated area", () => {
  assert.match(read("auth.ts"), /error: '\/auth\/error'/);
  assert.doesNotMatch(read("proxy.ts").match(/matcher: \[[^\]]*\]/)[0], /auth\/error/);
  const page = read("app/auth/error/page.tsx");
  assert.match(page, /authErrorKind\(code\)/);
  assert.match(page, /signIn\('google'/);
  assert.match(page, /href="\/"/);
});

test("every locale explains every error kind", () => {
  const keys = (value) => Object.entries(value).flatMap(([key, item]) =>
    item && typeof item === "object" ? Object.keys(item).map((leaf) => `${key}.${leaf}`) : [key]).sort();
  const en = JSON.parse(read("messages/en/auth.json")).authError;
  for (const kind of AUTH_ERROR_KINDS) for (const part of ["title", "body", "hint"]) assert.ok(en[kind][part], `${kind}.${part}`);
  for (const locale of ["ru", "uz", "ar"]) {
    assert.deepEqual(keys(JSON.parse(read(`messages/${locale}/auth.json`)).authError), keys(en), locale);
  }
  assert.doesNotMatch(en.configuration.body, /server configuration|server logs/i);
});
