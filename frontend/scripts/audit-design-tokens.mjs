import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('..', import.meta.url));
const roots = ['components/ui', 'components/shell', 'components/brand', 'components/customer', 'components/admin', 'components/notifications', 'app/dashboard/page.tsx', 'app/dashboard/tenders/page.tsx', 'app/dashboard/tenders/[tenderId]/page.tsx', 'app/dashboard/my-tenders/page.tsx', 'app/dashboard/bid-preparation/page.tsx', 'app/dashboard/settings/page.tsx', 'app/dashboard/readiness-vault/page.tsx', 'app/dashboard/notifications/page.tsx', 'app/dashboard/tenders/[tenderId]/compliance/page.tsx', 'app/admin/approvals/page.tsx', 'app/admin/broadcasts/page.tsx'];
export function auditText(source, { tokens = false } = {}) {
  const rules = [
    [
      'physical direction utility',
      /\b(?:[mp][lr]-|(?:left|right)-|border-[lr]-|text-(?:left|right)\b)[\w[\]./-]*/g,
    ],
    [
      'arbitrary Tailwind value',
      /\b(?:p[xysetb]?|m[xysetb]?|gap|text|rounded|shadow|bg|z|w|h)-\[[^\]]+\]/g,
    ],
  ];
  if (!tokens) rules.push(['raw product color', /#[\da-f]{3,8}\b/gi]);
  return rules.flatMap(([rule, pattern]) =>
    [...source.matchAll(pattern)].map((m) => ({
      line: source.slice(0, m.index).split('\n').length,
      rule,
      value: m[0],
    })),
  );
}
export function auditDesignTokens() {
  const issues = [];
  function walk(dir) {
    if (statSync(dir).isFile()) {
      for (const issue of auditText(readFileSync(dir, 'utf8'))) issues.push({file: relative(root, dir), ...issue});
      return;
    }
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (/\.(tsx?|css)$/.test(entry.name)) {
        for (const issue of auditText(readFileSync(path, 'utf8'), {
          tokens: entry.name === 'tokens.css',
        }))
          issues.push({ file: relative(root, path), ...issue });
      }
    }
  }
  roots.forEach((dir) => walk(join(root, dir)));
  return issues;
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const issues = auditDesignTokens();
  console.log(
    JSON.stringify({ ok: !issues.length, scope: roots, issues }, null, 2),
  );
  if (issues.length) process.exitCode = 1;
}
