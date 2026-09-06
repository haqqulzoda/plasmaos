#!/usr/bin/env python3
"""Render reviewed S9.1 source inventories; no app imports or external access."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/audits'


def main() -> None:
    data = json.loads((OUT / 's9_1_inventory.json').read_text())
    runtime = json.loads((OUT / 's9_1_openapi.json').read_text())
    lines = ['# S9.1 inventory appendix', '', f"Baseline `{data['sha']}`.", '',
             'This is a source-reference inventory, not an automatic deletion allowlist. '
             'Framework entrypoints, same-module references, dynamic names and external clients matter. '
             'See the main audit for reviewed boundaries, risk and deletion conditions.', '',
             '[Main report](../S9_1_CROSS_PRODUCT_ARCHITECTURE_LEGACY_AUDIT.md) · '
             '[Raw inventory](s9_1_inventory.json) · [OpenAPI](s9_1_openapi.json)', '']

    def cell(value):
        if isinstance(value, list):
            value = '<br>'.join(str(v) for v in value) or '—'
        return str(value).replace('|', '\\|').replace('\n', ' ')

    def table(title, headers, rows):
        lines.extend(['## ' + title, '', '| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join('---' for _ in headers) + ' |'])
        lines.extend('| ' + ' | '.join(cell(c) for c in row) + ' |' for row in rows)
        lines.append('')

    def normalized(path):
        path = re.sub(r'^\$\{[^}]+\}', '', path)
        path = re.sub(r'\$\{[^}]+\}|\{[^}]+\}', '{}', path.split('?', 1)[0])
        return path.removeprefix('/api/v1').rstrip('/')

    purpose = {
        '/': 'Google sign-in entry', '/dashboard': 'Customer overview',
        '/dashboard/tenders': 'Explorer; all/recommended/dismissed',
        '/dashboard/tenders/[tenderId]': 'Tender Details',
        '/dashboard/tenders/[tenderId]/compliance': 'Versioned Compliance',
        '/dashboard/my-tenders': 'Engagement-backed pursuit list',
        '/dashboard/bid-preparation': 'Proposal artifact list',
        '/dashboard/bid-preparation/[proposalId]': 'Proposal artifact editing/export',
        '/dashboard/settings': 'Company profile and preferences',
        '/dashboard/readiness-vault': 'Readiness records',
        '/dashboard/onboarding': 'Pending-user company onboarding',
        '/dashboard/pending-approval': 'Approval waiting/recovery',
        '/dashboard/access-blocked': 'Disabled/rejected account messaging',
        '/admin': 'Account operations and corpus overview',
        '/admin/approvals': 'User/company approval queue',
        '/admin/audit': 'Administrative audit event log',
        '/admin/companies/[companyProfileId]': 'Company profile/readiness inspection',
        '/api/auth/[...nextauth]': 'Auth.js authentication/session handlers',
        '/api/build': 'Public frontend release metadata',
        '/api/documents/[id]': 'Authenticated document proxy',
        '/document-preview/[id]': 'Document preview proxy alias',
        '/api/ui-locale': 'Validated locale-cookie write',
    }
    table('Frontend routes', ['Route / source', 'Purpose', 'Canonical / legacy',
          'Redirect or guard navigation', 'Customer reachable', 'Backend dependencies', 'Decision'], (
        [r['route'] + '<br>' + r['location'], purpose.get(r['route'], 'Legacy alias' if r['legacy'] else 'Admin / infrastructure'),
         'Legacy' if r['legacy'] else 'Canonical', r['redirects'],
         'Operator/admin only' if r['route'].startswith(('/admin', '/dashboard/admin')) else
         'Public; handler-specific validation' if r['route'] in {'/', '/api/build', '/api/ui-locale', '/api/auth/[...nextauth]'} else 'Authenticated',
         r['backend_dependencies'], 'KEEP compatibility' if r['legacy'] else 'KEEP; hardening findings apply'] for r in data['routes']))
    lines.extend(['Parent middleware/layout auth, locale and refresh dependencies are additional. '
                  'A guard navigation destination is not itself a legacy redirect.', ''])

    backend_rows = []
    for e in data['endpoints']:
        r = next((r for r in runtime['routes'] if r['path'] == e['path'] and e['method'] in r['methods']), None)
        guards = [d for d in r['dependencies'] if d.startswith(('require_', 'get_current', '_resolve_current'))] if r else e['dependencies']
        callers = [c['location'] for c in data['api_clients'] if normalized(c['endpoint']) == normalized(e['path'])
                   and c['method'] in {e['method'], 'FETCH'}]
        decision = 'KEEP current contract' if callers else 'INVESTIGATE external/operator/internal use; no removal proof'
        if e['path'] in {'/api/v1/tenders', '/api/v1/tenders/{tender_id}'} and e['method'] == 'GET':
            decision = 'H02: add backend guard in 9.3; live callers remain'
        backend_rows.append([e['method'] + ' ' + e['path'], e['function'] + '<br>' + e['location'],
                             e['classification'], guards or 'PUBLIC / no account guard', callers, decision])
    table('Backend endpoints', ['Method / path', 'Handler / source', 'Classification', 'Effective account guards',
          'Matching frontend callsites', 'Decision'], backend_rows)
    lines.extend(['Template matching is conservative; unmatched wrappers/props and external clients require manual review. '
                  'Public metadata/health and the login bridge must not be confused with accidentally unguarded customer APIs.', ''])

    table('Frontend API clients', ['Function hint / callsite', 'Method / endpoint', 'Module importers', 'Contract', 'Duplicate / removal'], (
        [c['function_hint'] + '<br>' + c['location'], c['method'] + ' ' + c['endpoint'], c['module_callers'],
         'Shared Axios or server fetch; see matching endpoint',
         ('Repeated endpoint callsites; ' if sum(normalized(x['endpoint']) == normalized(c['endpoint']) and x['method'] == c['method'] for x in data['api_clients']) > 1 else 'Single observed callsite; ') + 'KEEP until caller migration']
        for c in data['api_clients']))
    lines.extend(['Function hints are nearest lexical declaration names; source location is authoritative. '
                  'Repeated calls across pages are not necessarily duplicate wrappers. Only one Axios instance is defined.', ''])

    table('ORM models', ['Model / table', 'Source', 'Classification', 'Runtime reference files'], (
        [m['name'] + ' / ' + m['table'], m['location'],
         'Canonical domain' if m['name'] in {'Tender', 'TenderEngagement', 'Proposal', 'TenderAnalysis', 'AnalysisVersion', 'User', 'CompanyProfile', 'TenderRecommendation', 'SourceRefreshJob'} else 'Active support; no table deletion proof',
         m['runtime_references']] for m in data['models']))
    table('Schemas and types', ['Name / bases', 'Source', 'Classification', 'Same-module lines', 'Runtime refs', 'Tests/tool refs'], (
        [s['name'] + ' (' + ', '.join(s['bases']) + ')', s['location'], s['classification'], s.get('same_module_uses', []),
         s['runtime_references'], s['test_tool_references']] for s in data['schemas']))
    lines.extend(['ProjectResponse is test-only/API-ready historical schema; ProjectContext responses are the live Tender Details contract. '
                  'Keep until the enrichment test expectation is deliberately transferred. Source runner DTOs are live internal contracts.', ''])
    table('Services', ['Module', 'Classification', 'Runtime importers', 'Tests/tools'], (
        [s['path'], s['classification'], s['runtime_importers'], s['test_tool_importers']] for s in data['services']))
    table('Components', ['Module', 'Classification', 'Callers'], (
        [c['path'], c['classification'], c['callers']] for c in data['components']))
    table('Hooks', ['Hook / source', 'Classification', 'Runtime references'], (
        [h['name'] + '<br>' + h['location'], 'Active', h['runtime_references']] for h in data['hooks']))

    defaults = {
        'AUTO_CREATE_TABLES': 'false', 'PLASMA_ENABLE_PSEUDO_LOCALE': 'off; nonproduction only',
        'DEMO_OCR_BYPASS': 'off', 'TENDER_OCR_DISABLED': 'off', 'POSTGRES_PORT': '6543 (app); 5432 (Compose)',
        'SOURCE_REFRESH_COOLDOWN_SECONDS': '300', 'SOURCE_REFRESH_LEASE_SECONDS': '180',
        'SOURCE_REFRESH_HEARTBEAT_SECONDS': '30', 'SOURCE_REFRESH_QUEUED_REPUBLISH_SECONDS': '60',
        'TENDER_OCR_PAGE_TIMEOUT_SECONDS': '12', 'TENDER_OCR_MAX_PAGES': '2', 'TENDER_OCR_RENDER_DPI': '150',
        'TENDER_OCR_SKIP_AFTER_TEXT_CHARS': '5000', 'GEMINI_REQUIREMENT_MAX_PAYLOAD_CHARS': '120000',
        'GEMINI_REQUIREMENT_CHUNK_OVERLAP_CHARS': '1000', 'GEMINI_REQUIREMENT_CHUNK_CONCURRENCY': '3',
        'WORLD_BANK_AUTODRAIN_BATCH_SIZE': '25', 'WORLD_BANK_AUTODRAIN_INTERVAL_SECONDS': '60 minimum',
        'WORLD_BANK_ENRICHMENT_RETRY_BACKOFF_SECONDS': '900', 'CELERY_WORKER_MAX_TASKS_PER_CHILD': '10',
        'GIZ_MAX_ARCHIVE_COMPRESSED_BYTES': '100 MiB', 'GIZ_MAX_ARCHIVE_EXTRACTED_BYTES': '250 MiB',
        'GIZ_MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES': '50 MiB', 'GIZ_MAX_ARCHIVE_FILE_COUNT': '200',
        'GIZ_MAX_ARCHIVE_NESTING_DEPTH': '1', 'NEXT_DIST_DIR': '.next', 'DOCKER_BIN': 'docker',
        'PLASMA_ADMIN_EMAILS': 'empty allowlist', 'PLASMA_OPERATOR_EMAILS': 'empty allowlist',
    }
    table('Environment and flags', ['Name', 'Classification / owner', 'Default / requirement', 'Keep / risk', 'References'], (
        [e['name'], 'Shell special variable (not configuration)' if e['name'] == 'BASH_SOURCE' else e['classification'],
         'Value withheld; secret' if e['classification'] == 'secret' else defaults.get(e['name'], 'See source default; optional unless required by selected service'),
         'REVIEW; production must disable' if e['name'] in {'AUTO_CREATE_TABLES', 'DEMO_OCR_BYPASS'} else 'KEEP or explicit config compatibility review', e['locations']]
        for e in data['environment']))
    lines.extend(['Configured `.env` names are stored separately in JSON; values are not retained. '
                  'Compose/script inputs are operational even when the conservative source scan labels them test/tool-only. '
                  '`NEXT_PUBLIC_API_URL` and `ACCESS_TOKEN_EXPIRE_MINUTES` are stale configured inputs discussed in the main report.', ''])

    table('Celery tasks', ['Function / location', 'Task registration', 'Queue / lifecycle', 'Call references'], (
        [t['function'] + '<br>' + t['location'], t['decorator'],
         'ai_fast_queue; Beat every 30m' if 'hunter' in t['location'] else
         'heavy_dl_queue; explicit document work' if 'tender_tasks' in t['location'] else
         'celery; Beat autodrain' if t['function'].startswith('dispatch_') else 'celery; dispatched worker',
         t['runtime_references']] for t in data['tasks']))
    table('Duplicate test basenames', ['Existing pair', 'Exact proposed script rename', 'Condition'], (
        [ps, next(p for p in ps if '/scripts/' in p).replace('/test_', '/verify_'),
         'Update every scripts import/reference; keep root test name; run both domain and migration proof']
        for ps in data['duplicate_test_basenames'].values()))
    table('Test topology', ['File', 'Classification'], (
        [p, 'Import-time developer probe; move/guard' if Path(p).name in {'test_ai.py', 'test_tender_api.py', 'test_uzbek_nlp.py'} else
         'Browser harness/fixture; platform constraints apply' if '/frontend/tests/' in '/' + p and p.endswith('.py') else
         'PostgreSQL proof / developer script; inspect main before invocation' if '/scripts/' in p else 'Domain regression / frontend static or fixture'] for p in data['tests']))
    table('Documentation', ['File', 'Classification', 'Decision'], (
        [d['path'], d['classification'], 'PRESERVE historical evidence; label baseline/SHA' if 'historical' in d['classification'] else 'UPDATE canonical setup guidance / preserve connector research'] for d in data['docs']))
    table('Scripts', ['File', 'Classification'], (
        [p, 'Release operational wrapper; not executed' if 'compose-release' in p else
         'Connector release gate' if 'connector_regression_gate' in p else
         'Migration proof/bootstrap; preserve' if any(x in p for x in ['migration', 'baseline', 'bootstrap', 'drift']) else
         'Audit/report tooling' if any(x in p for x in ['audit', 'report', 'preflight']) else
         'Historical proof / developer probe; preserve until explicit caller review'] for p in data['scripts']))
    tracked = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
    utilities = [p for p in tracked if len(Path(p).parts) == 2 and p.startswith('backend/') and p.endswith('.py') and not Path(p).name.startswith('test_')]
    table('Root developer utilities', ['File', 'Classification / decision'], (
        [p, 'Legacy schema/data mutation; do not use as release bootstrap' if any(x in p for x in ['add_', 'init_db', 'reset_db', 'seed_']) else 'Developer probe; not product coverage; make explicit and portable'] for p in utilities))
    table('Package scripts', ['Name', 'Command', 'Classification'], (
        [k, v, 'Platform-bound browser acceptance' if 'browser' in k else 'Build/dev' if k in {'dev', 'start', 'build'} else 'Existing static/domain gate'] for k, v in data['package_scripts'].items()))
    migrations = []
    for path in sorted((ROOT / 'backend/alembic/versions').glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        values = {}
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {'revision', 'down_revision'}:
                        values[target.id] = ast.literal_eval(node.value)
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                   and node.module and node.module.startswith('app.')]
        migrations.append([str(path.relative_to(ROOT)), values.get('revision'), values.get('down_revision'),
                           imports or 'None', 'KEEP immutable history; do not squash'])
    table('Migration graph', ['File', 'Revision', 'Parent', 'Runtime imports', 'Decision'], migrations)
    table('Localization keys', ['Namespace/key', 'Classification'], ([k['key'], k['classification']] for k in data['localization_keys']))

    tree = ast.parse((ROOT / 'backend/app/api/endpoints/tenders.py').read_text())
    candidates = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and 5710 <= n.lineno <= 6356]
    table('GIZ duplicate closure candidates', ['Exact endpoint-module function', 'Line', 'Disposition'], (
        [n.name, n.lineno, 'Candidate closed helper set; delete endpoint copies only after import/dynamic/test proof; KEEP active service names'] for n in candidates))
    lines.extend(['The 22 functions above have no incoming same-module function-reference edge from outside the set at the audited SHA. '
                  'Identically named functions in `services/giz_document_hydration.py` are separate live definitions, not callers of these copies. '
                  'Line numbers identify evidence, not a range to blindly delete. Preserve constants until their own callers are checked.', '',
                  '## Evidence limitations', '',
                  'Search-evidence arrays and mutation candidates in JSON retain locations without raw secret/log content. '
                  'All original regression outcomes were observed before the session environment restarted; temporary full logs and disposable tools '
                  'were lost on that restart. Persisted JSON/screenshots and the execution record distinguish retained evidence from observed tool output. '
                  'No test rerun is asserted after restart.', ''])
    (OUT / 's9_1_inventory.md').write_text('\n'.join(lines) + '\n')
    print(f'Rendered {len(lines)} lines from {data["sha"]}')


if __name__ == '__main__':
    main()
