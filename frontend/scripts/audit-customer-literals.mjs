import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const ROOT = new URL('../', import.meta.url);

export const CUSTOMER_SURFACES = [
  'app/dashboard/page.tsx',
  'app/dashboard/readiness-vault/page.tsx',
  'app/dashboard/tenders/[tenderId]/compliance/page.tsx',
  'app/dashboard/bids/[id]/page.tsx',
  'app/not-found.tsx',
  'components/workspace/DocumentViewer.tsx',
];

const JSX_TEXT = />\s*([A-Za-z][^<>{}\n]*[A-Za-z.!?…])\s*</g;
const LITERAL_ATTRIBUTE = /\b(?:aria-label|placeholder|title)=["']([A-Za-z][^"']*)["']/g;

export function auditCustomerLiterals() {
  const candidates = [];
  for (const path of CUSTOMER_SURFACES) {
    const source = readFileSync(new URL(path, ROOT), 'utf8');
    for (const pattern of [JSX_TEXT, LITERAL_ATTRIBUTE]) {
      for (const match of source.matchAll(pattern)) {
        candidates.push({path, literal: match[1].trim(), index: match.index});
      }
    }
  }
  return candidates;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const candidates = auditCustomerLiterals();
  process.stdout.write(`${JSON.stringify({scope: CUSTOMER_SURFACES, candidates}, null, 2)}\n`);
  process.exitCode = candidates.length === 0 ? 0 : 1;
}
