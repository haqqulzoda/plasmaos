#!/usr/bin/env python3
"""Offline, read-only source inventory. Never imports the app or emits .env values.

Run from any directory with Python 3.12+. Output is an audit artifact, not a
dead-code verdict: textual references include comments; dynamic imports and
external clients require separate compatibility review.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    paths = sorted(p for p in tracked if p and (ROOT / p).is_file())
    code = {p: (ROOT / p).read_text(encoding='utf-8-sig', errors='replace') for p in paths
            if Path(p).suffix in {'.py', '.ts', '.tsx', '.mjs', '.sh'} and '.env' not in p}
    runtime = {p: s for p, s in code.items() if p.startswith(('backend/app/', 'backend/bot/'))
               or p.startswith('frontend/') and not p.startswith(('frontend/tests/', 'frontend/scripts/'))}
    trees = {p: ast.parse(s) for p, s in code.items() if p.endswith('.py')}
    def refs(symbol: str, exclude: str = '') -> dict:
        pattern = re.compile(r'\b' + re.escape(symbol) + r'\b')
        found = [f'{p}:{s[:m.start()].count(chr(10))+1}' for p, s in code.items()
                 if p != exclude for m in list(pattern.finditer(s))[:1]]
        return {'runtime_references': [x for x in found if x.rsplit(':', 1)[0] in runtime],
                'test_tool_references': [x for x in found if x.rsplit(':', 1)[0] not in runtime]}
    def loc(p, node):
        return f'{p}:{node.lineno}'
    prefixes = defaultdict(list)
    for n in ast.walk(trees['backend/app/main.py']):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'include_router':
            prefixes[ast.unparse(n.args[0])].append(next(ast.literal_eval(k.value) for k in n.keywords if k.arg == 'prefix'))
    endpoints, schemas, models, tasks, writes, guards = [], [], [], [], [], []
    for p, tree in trees.items():
        if not p.startswith('backend/app/'):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef):
                bases = [ast.unparse(b) for b in n.bases]
                table = next((ast.literal_eval(a.value) for a in n.body if isinstance(a, ast.Assign)
                              and any(isinstance(t, ast.Name) and t.id == '__tablename__' for t in a.targets)), None)
                if table:
                    models.append({'name': n.name, 'table': table, 'location': loc(p, n),
                                   'classification': 'active canonical/support; review matrix', **refs(n.name, p)})
                elif any('BaseModel' in b or b.endswith(('Response', 'Base', 'Request')) for b in bases) or p.startswith('backend/app/schemas/'):
                    usage = refs(n.name, p)
                    local_uses = [item.lineno for item in ast.walk(tree) if isinstance(item, ast.Name)
                                  and item.id == n.name and isinstance(item.ctx, ast.Load)]
                    schemas.append({'name': n.name, 'bases': bases, 'location': loc(p, n), **usage,
                                    'same_module_uses': local_uses,
                                    'classification': 'active referenced' if usage['runtime_references'] or local_uses else 'test-only/unreferenced candidate; review dynamic use'})
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls = sorted({ast.unparse(c.func) for c in ast.walk(n) if isinstance(c, ast.Call)})
                deps = sorted({ast.unparse(c) for c in ast.walk(n.args) if isinstance(c, ast.Call)
                               and ast.unparse(c.func) == 'Depends'})
                if deps:
                    guards.append({'function': n.name, 'location': loc(p, n), 'dependencies': deps})
                for d in n.decorator_list:
                    if not isinstance(d, ast.Call) or not isinstance(d.func, ast.Attribute):
                        continue
                    if d.func.attr == 'task':
                        tasks.append({'function': n.name, 'location': loc(p, n), 'decorator': ast.unparse(d), **refs(n.name, p)})
                    if d.func.attr not in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options'}:
                        continue
                    if not d.args or not isinstance(d.args[0], ast.Constant):
                        continue
                    module = Path(p).stem
                    for prefix in prefixes.get(module + '.router', ['']):
                        path = prefix + d.args[0].value
                        classification = ('canonical operator' if '/admin' in path else
                                          'legacy compatibility' if '/hunter' in path or path.startswith('/audit/') or path.endswith('/sync') or path == '/api/v1/tenders/refresh' else
                                          'dangerous operator probe' if any(x in path for x in ['/seed', '/test-scrape', '/proxy-download', '/upgrade-me']) else
                                          'customer/support')
                        endpoints.append({'method': d.func.attr.upper(), 'path': path, 'function': n.name,
                                          'location': loc(p, n), 'dependencies': deps,
                                          'decorator': ast.unparse(d), 'classification': classification,
                                          'calls': calls, 'router_guards': [ast.unparse(x.value) for x in tree.body if isinstance(x, ast.Assign) and isinstance(x.value, ast.Call) and ast.unparse(x.value.func) == 'APIRouter']})
                mutation = []
                for c in ast.walk(n):
                    if isinstance(c, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                        targets = c.targets if isinstance(c, ast.Assign) else [c.target]
                        for t in targets:
                            if isinstance(t, ast.Attribute) and re.search(r'tender|doc|analysis|version|proposal|engagement|profile|user|job|rec', ast.unparse(t), re.I):
                                mutation.append({'target': ast.unparse(t), 'line': c.lineno})
                    elif isinstance(c, ast.Call) and (ast.unparse(c.func) in {'Tender', 'TenderDocument', 'CanonicalDocument', 'Proposal', 'TenderEngagement', 'TenderAnalysis', 'AnalysisVersion', 'SourceRefreshJob'} or ast.unparse(c.func).endswith(('.add', '.execute', '.commit', '.flush', '.delete'))):
                        mutation.append({'call': ast.unparse(c.func), 'line': c.lineno})
                if mutation:
                    writes.append({'function': n.name, 'location': loc(p, n), 'candidates': mutation})
    frontend = {p: s for p, s in runtime.items() if p.startswith('frontend/')}
    edges = defaultdict(list)
    for p, s in frontend.items():
        for spec in re.findall(r'(?:from\s*|import\s*\(\s*|import\s*)[\'\"]([^\'\"]+)[\'\"]', s):
            target = ROOT / 'frontend' / spec[2:] if spec.startswith('@/') else (ROOT / p).parent / spec
            for candidate in [target, *(Path(str(target) + x) for x in ['.ts', '.tsx']), target / 'index.ts', target / 'index.tsx']:
                relative = str(candidate.resolve().relative_to(ROOT)) if candidate.resolve().is_relative_to(ROOT) else ''
                if relative in frontend:
                    edges[p].append(relative)
                    break
    incoming = defaultdict(list)
    for p, targets in edges.items():
        for target in targets:
            incoming[target].append(p)
    roots = [p for p in frontend if p.startswith('frontend/app/') and Path(p).stem in {'page', 'route', 'layout', 'not-found', 'error', 'loading'}] + ['frontend/middleware.ts', 'frontend/auth.ts']
    reachable = set()
    def walk(p):
        if p in reachable:
            return
        reachable.add(p)
        for target in edges[p]:
            walk(target)
    for p in roots:
        walk(p)
    api_calls = []
    api_pattern = re.compile(r'\b(api\.(get|post|put|patch|delete)(?:<[^;]*?>)?\s*\(\s*([\'\"`])(.+?)\3|fetch\(\s*([\'\"`])(.+?)\5)', re.S)
    for p, s in frontend.items():
        for m in api_pattern.finditer(s):
            before = s[:m.start()]
            names = list(re.finditer(r'(?:function\s+(\w+)|(?:const|let)\s+(\w+)\s*=)', before))
            name = next((g for g in names[-1].groups() if g), 'module') if names else 'module'
            api_calls.append({'location': f'{p}:{before.count(chr(10))+1}', 'function_hint': name,
                              'method': (m.group(2) or 'FETCH').upper(), 'endpoint': m.group(4) or m.group(6),
                              'module_callers': incoming[p], 'canonical': 'review endpoint matrix',
                              'safe_remove': False})
    routes = []
    for p in roots:
        if not p.startswith('frontend/app/') or Path(p).stem not in {'page', 'route'}:
            continue
        s = frontend[p]
        url = '/' + '/'.join(Path(p).parts[2:-1])
        redirect = re.findall(r'(?:permanentRedirect|redirect|router\.replace)\([\'\"`]([^\'\"`]+)', s)
        alias = '/dashboard/' in url and any(x in url for x in ['/hunter', '/workspace', '/bids', '/proposals', '/admin'])
        deps = set()
        seen = set()
        def gather(target):
            if target in seen:
                return
            seen.add(target)
            deps.update(c['endpoint'] for c in api_calls if c['location'].rsplit(':', 1)[0] == target)
            for child in edges[target]:
                gather(child)
        gather(p)
        routes.append({'route': url, 'location': p, 'purpose': Path(p).parent.name,
                       'canonical': not alias, 'legacy': alias, 'redirects': redirect,
                       'customer_reachable': not url.startswith('/admin'),
                       'backend_dependencies': sorted(deps), 'action': 'KEEP compatibility' if alias else 'KEEP'})
    components = [{'path': p, 'callers': incoming[p], 'reachable': p in reachable,
                   'classification': 'active' if p in reachable else 'investigate zero static imports'}
                  for p in frontend if p.startswith('frontend/components/')]
    hooks = [{'name': m.group(1), 'location': f'{p}:{s[:m.start()].count(chr(10))+1}', **refs(m.group(1), p)}
             for p, s in frontend.items() for m in re.finditer(r'(?:function\s+|(?:const|let)\s+)(use[A-Z]\w+)', s)]
    services = []
    imported_modules = {}
    for p, tree in trees.items():
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
                imports.update(node.module + '.' + alias.name for alias in node.names)
        imported_modules[p] = imports
    for p in trees:
        if not p.startswith('backend/app/services/'):
            continue
        module = p.removeprefix('backend/').removesuffix('.py').replace('/', '.')
        if module.endswith('.__init__'):
            module = module.removesuffix('.__init__')
        callers = [q for q, imports in imported_modules.items() if q != p
                   and any(value == module or value.startswith(module + '.') for value in imports)]
        services.append({'path': p, 'runtime_importers': [q for q in callers if q in runtime],
                         'test_tool_importers': [q for q in callers if q not in runtime],
                         'classification': 'active/support' if any(q in runtime for q in callers) else 'investigate; exports/dynamic imports may apply'})
    env = defaultdict(list)
    for p, s in code.items():
        for m in re.finditer(r'(?:getenv\(|environ\.get\(|environ\[|process\.env\.?\[?|environment\.)\s*[\'\"]?([A-Z][A-Z0-9_]+)', s):
            env[m.group(1)].append(f'{p}:{s[:m.start()].count(chr(10))+1}')
    for n in ast.walk(trees['backend/app/core/config.py']):
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id.isupper():
            env[n.target.id].append(loc('backend/app/core/config.py', n))
    # Include indirect settings readers (_env_int, _seconds, allowlists, etc.).
    for p, tree in trees.items():
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and re.search(r'env|setting|seconds|allowlist', ast.unparse(n.func), re.I):
                for value in n.args:
                    if isinstance(value, ast.Constant) and isinstance(value.value, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{3,}', value.value):
                        env[value.value].append(loc(p, n))
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id.endswith('_ENV') for t in n.targets):
                if isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                    env[n.value.value].append(loc(p, n))
    for p in paths:
        if p.endswith(('.sh', 'Dockerfile')) or p == 'docker-compose.yml':
            for i, line in enumerate((ROOT / p).read_text().splitlines(), 1):
                for key in re.findall(r'\$\{([A-Z][A-Z0-9_]*)', line):
                    env[key].append(f'{p}:{i}')
    configured_env_names = {}
    # Read names only; never retain, emit, or compare secret values.
    for p in [ROOT / '.env', ROOT / 'frontend/.env.local']:
        if p.exists():
            configured_env_names[str(p.relative_to(ROOT))] = sorted(set(
                m.group(1) for line in p.read_text().splitlines()
                if (m := re.match(r'^\s*([A-Z][A-Z0-9_]*)\s*=', line))))
    environments = [{'name': k, 'locations': sorted(set(v)), 'classification':
                     'secret' if re.search('SECRET|PASSWORD|TOKEN|API_KEY', k) else
                     'public' if k.startswith('NEXT_PUBLIC') else
                     'test-only' if all(x.rsplit(':', 1)[0] not in runtime for x in v) else 'runtime; required/optional in review matrix'} for k, v in sorted(env.items())]
    tests = [p for p in paths if '/tests/' in p or Path(p).name.startswith('test_')]
    basenames = defaultdict(list)
    for p in tests:
        if p.endswith('.py'):
            basenames[Path(p).name].append(p)
    search_patterns = {'hunter': r'\bhunter\b|Hunter', 'old_product': r'My Bids|Bid Workspace|Tender Workspace|proposal.as.pursuit',
                       'platform': r'[CDcd]:\\|/mnt/[cd]/|cmd\.exe',
                       'source_labels': r'UzEx|World Bank|\bADB\b|\bGIZ\b|\bEBRD\b',
                       'locale': r'localStorage.*locale|Accept-Language|\[.en., .uz., .ru.',
                       'logging': r'logger\.|logging\.|console\.(?:log|error|warn)|\bprint\(',
                       'errors': r'HTTPException|detail=f|str\(exc\)|str\(e\)',
                       'timezone': r'datetime\.utcnow|datetime\.now\(\)|DateTime\(|timezone=True',
                       'constraints': r'UniqueConstraint|unique=True|Index\(|ondelete=|cascade='}
    findings = {name: [{'location': f'{p}:{i}', 'category': 'runtime' if p in runtime else 'test/tool',
                         'matched_symbol': m.group(0)} for p, s in code.items() for i, line in enumerate(s.splitlines(), 1)
                        if (m := re.search(pattern, line))] for name, pattern in search_patterns.items()}
    catalog_keys = []
    def flatten(data, prefix=''):
        for k, v in data.items():
            key = prefix + k
            if isinstance(v, dict):
                yield from flatten(v, key + '.')
            else:
                yield key
    combined = '\n'.join(frontend.values())
    for p in paths:
        if p.startswith('frontend/messages/en/') and p.endswith('.json'):
            namespace = Path(p).stem
            for key in flatten(json.loads((ROOT / p).read_text())):
                literal = bool(re.search(r'[\'\"]' + re.escape(key) + r'[\'\"]', combined))
                catalog_keys.append({'key': namespace + '.' + key,
                                     'classification': 'literal reference candidate' if literal else 'dynamic/unreferenced candidate; no deletion proof'})
    package = json.loads((ROOT / 'frontend/package.json').read_text())
    result = {'method': 'tracked source AST + conservative textual references + resolved TS import graph; no app imports, environment values, network or database',
              'sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'routes': routes, 'endpoints': endpoints, 'api_clients': api_calls, 'models': models,
              'schemas': schemas, 'services': services, 'components': components, 'hooks': hooks,
              'tasks': tasks, 'write_candidates': writes, 'auth_dependencies': guards,
              'environment': environments, 'configured_env_names_only': configured_env_names, 'tests': tests,
              'duplicate_test_basenames': {k: v for k, v in basenames.items() if len(v) > 1},
              'docs': [{'path': p, 'classification': 'historical sprint evidence' if re.match(r'docs/(S\d|SR_|WB_)', p) else 'review setup/connector reference'} for p in paths if p.startswith('docs/') or '/docs/' in p or Path(p).name.lower().startswith('readme')],
              'scripts': [p for p in paths if '/scripts/' in p or p.startswith('scripts/')],
              'package_scripts': package['scripts'], 'packages': package['dependencies'],
              'search_evidence': findings, 'localization_keys': catalog_keys,
              'frontend_import_graph': dict(edges), 'ci_files': [p for p in paths if p.startswith('.github/') or re.search(r'gitlab-ci|Jenkinsfile|azure-pipelines', p)]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: len(v) for k, v in result.items() if isinstance(v, (list, dict))}, sort_keys=True))


if __name__ == '__main__':
    main()
