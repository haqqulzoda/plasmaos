import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const read = (path) => readFileSync(resolve(root, path), 'utf8');
const issues = [];
const checkAbsent = (label, pattern, paths) => {
  for (const path of paths) {
    const source = read(path);
    if (pattern.test(source)) issues.push({ label, path });
    pattern.lastIndex = 0;
  }
};

const customerClosure = [
  'app/page.tsx',
  'app/not-found.tsx',
  'app/dashboard/onboarding/page.tsx',
  'app/dashboard/pending-approval/page.tsx',
  'app/dashboard/access-blocked/page.tsx',
  'app/dashboard/bid-preparation/[proposalId]/page.tsx',
  'app/dashboard/bids/[id]/page.tsx',
];
const shellClosure = [
  'app/globals.css',
  'app/admin/layout.tsx',
  'components/shell/CustomerShell.tsx',
  'components/shell/AdminShell.tsx',
  'components/shell/shell.css',
];

checkAbsent('obsolete global visual helper', /(?:gradient-bg|glass-card|code-display|pulse-glow|btn-primary)/g, ['app/globals.css']);
checkAbsent('obsolete dark customer palette', /(?:bg-(?:gray|zinc|slate)-(?:8|9)|text-white|text-(?:gray|zinc)-(?:2|3|4))\b/g, customerClosure);
checkAbsent('retired shell feature flag', /(?:legacyContent|shell-legacy-content)/g, shellClosure);
checkAbsent('obsolete visual dependency', /framer-motion/g, ['package.json', 'package-lock.json']);

for (const asset of ['file.svg', 'globe.svg', 'next.svg', 'vercel.svg', 'window.svg']) {
  if (existsSync(resolve(root, 'public', asset))) issues.push({ label: 'unused starter asset', path: `public/${asset}` });
}

const topology = {
  customerTheme: /className="ds-theme app-shell"/.test(read('components/shell/CustomerShell.tsx')),
  adminTheme: /className="ds-theme ds-admin app-shell"/.test(read('components/shell/AdminShell.tsx')),
  sharedFoundation: /components\/ui\/foundation\.css/.test(read('app/globals.css')),
  canonicalLogo: /PlasmaLogo/.test(read('components/shell/CustomerShell.tsx')) && /PlasmaLogo/.test(read('components/shell/AdminShell.tsx')),
};
for (const [label, ok] of Object.entries(topology)) if (!ok) issues.push({ label: `topology:${label}`, path: null });

console.log(JSON.stringify({ ok: issues.length === 0, topology, auditedCustomerClosures: customerClosure, issues }, null, 2));
if (issues.length) process.exitCode = 1;
