// Integration fix 3b: a partial refresh that saved tenders is fresh data with a visible note.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(ROOT, path), "utf8");

test("the source refresh menu shows a localized partial note next to the stale note", () => {
  const menu = read("components/source-refresh/SourceRefreshMenu.tsx");
  // Both menu variants: only when no job is running, from last_success_partial.
  assert.equal((menu.match(/last_success_partial === true/g) || []).length, 2);
  assert.equal((menu.match(/data-source-partial="true"/g) || []).length, 2);
  assert.equal((menu.match(/tTruth\("sourcePartial"\)/g) || []).length, 2);
  assert.match(read("types/source-refresh.ts"), /last_success_partial\?: boolean;/);
  for (const locale of ["en", "ru", "uz", "ar"]) {
    const truth = JSON.parse(read(`messages/${locale}/common.json`)).tenderTruth;
    assert.ok(truth.sourcePartial && truth.sourcePartial !== truth.sourceStale, locale);
  }
});
