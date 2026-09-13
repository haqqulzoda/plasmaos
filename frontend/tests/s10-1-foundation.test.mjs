import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  auditDesignTokens,
  auditText,
} from '../scripts/audit-design-tokens.mjs';
const read = (p) => readFileSync(new URL('../' + p, import.meta.url), 'utf8');
test('new foundations obey the semantic token and direction contract', () =>
  assert.deepEqual(auditDesignTokens(), []));
test('audit catches violations and allows only the token color authority', () => {
  assert.equal(auditText('bg-[#abcdef] ml-4 rounded-[9px]').length, 4);
  assert.equal(auditText('--color: #abcdef', { tokens: true }).length, 0);
});
test('logo has no executable or external content and retains supplied vector paths', () => {
  const svg = read('public/brand/plasma-mark.svg');
  assert.equal((svg.match(/<path /g) || []).length, 187);
  assert.doesNotMatch(svg, /<script|<image|onload|href=|<foreignObject/i);
  assert.match(svg, /viewBox="290 235 1420 1530"/);
});
test('shell presentation is passive with no domain ownership', () => {
  for (const p of ['CustomerShell', 'AdminShell'])
    assert.doesNotMatch(
      read(`components/shell/${p}.tsx`),
      /\bapi\.|\bfetch\(|useSession|SourceRefreshProvider|setInterval/,
    );
});
test('admin is code split and refresh ownership stays in customer layout', () => {
  assert.doesNotMatch(
    read('components/shell/CustomerShell.tsx'),
    /import.*AdminShell/,
  );
  assert.equal(
    (
      read('app/dashboard/layout.tsx').match(
        /<SourceRefreshProvider enabled>/g,
      ) || []
    ).length,
    1,
  );
});
test('logo red is independent of interactive token palette', () => {
  assert.match(read('components/ui/tokens.css'), /--ds-accent: #3159c9/);
  assert.doesNotMatch(
    read('components/brand/PlasmaLogo.tsx'),
    /filter|invert|fill=/,
  );
});
test('token foreground pairs exceed AA normal text contrast', () => {
  const css = read('components/ui/tokens.css');
  const blocks = [
    css.slice(css.indexOf(':root'), css.indexOf('.ds-admin')),
    css.slice(css.indexOf('.ds-admin'), css.indexOf('@theme')),
  ];
  const lum = (hex) => {
    const rgb = hex
      .match(/\w\w/g)
      .map((x) => parseInt(x, 16) / 255)
      .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
  };
  for (const block of blocks) {
    const tokens = Object.fromEntries(
      [...block.matchAll(/--ds-([\w-]+): #([\da-f]{6});/g)].map((m) => [
        m[1],
        m[2],
      ]),
    );
    for (const [fg, bg] of [
      ['text', 'surface'],
      ['text-secondary', 'surface'],
      ['text-tertiary', 'surface'],
      ['text-disabled', 'background-subtle'],
      ['on-accent', 'accent'],
      ...['success', 'warning', 'danger', 'info'].map((t) => [
        t,
        t + '-subtle',
      ]),
    ]) {
      const l = [lum(tokens[fg]), lum(tokens[bg])].sort((a, b) => b - a);
      assert.ok((l[0] + 0.05) / (l[1] + 0.05) >= 4.5, `${fg}/${bg} contrast`);
    }
  }
});
