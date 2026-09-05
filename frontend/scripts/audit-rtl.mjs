import {readdirSync, readFileSync, statSync} from 'node:fs';
import {join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';

const FRONTEND = fileURLToPath(new URL('..', import.meta.url));
const CUSTOMER_ROOTS = ['app/dashboard', 'components'];
const SOURCE_EXTENSIONS = new Set(['.ts', '.tsx']);

function sourceFiles(root) {
  const files = [];
  for (const entry of readdirSync(root)) {
    const path = join(root, entry);
    if (statSync(path).isDirectory()) files.push(...sourceFiles(path));
    else if ([...SOURCE_EXTENSIONS].some((extension) => path.endsWith(extension))) files.push(path);
  }
  return files;
}

export const PHYSICAL_DIRECTION_PATTERN = /\b(?:text-(?:left|right)|[mp][lr]-[A-Za-z0-9.[\]/_-]+|border-[lr](?:-[A-Za-z0-9.[\]/_-]+)?|(?:left|right)-[A-Za-z0-9.[\]/_-]+|space-x-[A-Za-z0-9.[\]/_-]+|-?translate-x-[A-Za-z0-9.[\]/_-]+)\b/g;
export const DIRECTIONAL_ICON_PATTERN = /<(?:ArrowLeft|ArrowRight|ChevronLeft|ChevronRight|MoveLeft|MoveRight)\b[^>]*>/g;

function location(path, source, offset) {
  return `${relative(FRONTEND, path).replaceAll('\\', '/')}:${source.slice(0, offset).split('\n').length}`;
}

export function auditCustomerPhysicalDirection() {
  const issues = [];
  for (const root of CUSTOMER_ROOTS) {
    for (const path of sourceFiles(join(FRONTEND, root))) {
      const source = readFileSync(path, 'utf8');
      for (const match of source.matchAll(PHYSICAL_DIRECTION_PATTERN)) {
        issues.push(`${location(path, source, match.index)} ${match[0]}`);
      }
    }
  }
  return issues;
}

export function auditCustomerDirectionalIcons() {
  const issues = [];
  for (const root of CUSTOMER_ROOTS) {
    for (const path of sourceFiles(join(FRONTEND, root))) {
      const source = readFileSync(path, 'utf8');
      for (const match of source.matchAll(DIRECTIONAL_ICON_PATTERN)) {
        if (!match[0].includes('rtl-mirror')) {
          issues.push(`${location(path, source, match.index)} ${match[0]}`);
        }
      }
    }
  }
  return issues;
}

export function auditGlobalDirectionAuthority() {
  const files = [...sourceFiles(join(FRONTEND, 'app')), ...sourceFiles(join(FRONTEND, 'components'))];
  const combined = files.map((path) => readFileSync(path, 'utf8')).join('\n');
  const layout = readFileSync(join(FRONTEND, 'app/layout.tsx'), 'utf8');
  const adminLayout = readFileSync(join(FRONTEND, 'app/admin/layout.tsx'), 'utf8');
  const issues = [];
  if (!/<html\s+lang=\{locale\}\s+dir=\{directionForLocale\(locale\)\}>/.test(layout)) {
    issues.push('app/layout.tsx is not the server-authoritative lang/dir owner');
  }
  if (!/lang="en"\s+dir="ltr"\s+data-admin-ltr-island/.test(adminLayout)) {
    issues.push('app/admin/layout.tsx lacks its explicit English LTR content island');
  }
  if (/document\.documentElement\.(?:dir|lang)\s*=/.test(combined)) {
    issues.push('client code mutates the root lang/dir authority');
  }
  return issues;
}

export function runRtlAudit() {
  return {
    physical: auditCustomerPhysicalDirection(),
    icons: auditCustomerDirectionalIcons(),
    authority: auditGlobalDirectionAuthority(),
  };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const result = runRtlAudit();
  const count = Object.values(result).reduce((total, values) => total + values.length, 0);
  console.log(JSON.stringify({ok: count === 0, ...result}, null, 2));
  if (count) process.exitCode = 1;
}
