#!/usr/bin/env python3
"""Measure unchanged HTTP reads against an explicitly disposable local database.

Requires the repository bootstrap at head. Creates synthetic fixture data ONLY;
refuses normal database names, non-loopback hosts, and the usual service port.
Never runs workers, connectors, model generation, or external HTTP. Query text
is recorded without parameters. This is audit evidence, not a release test.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import time

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core.config import settings

if not (settings.POSTGRES_SERVER == '127.0.0.1'
        and settings.POSTGRES_DB == 'plasma_s05b4b_s91_audit'
        and settings.POSTGRES_PORT == 56591):
    raise SystemExit('Refusing database: requires dedicated S9.1 disposable localhost:56591 database')

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from app.core.security import create_access_token
from app.db.session import engine
from app.main import app
from scripts import test_s0_5b4_baseline as support
from scripts import verify_s5_2_tender_details_read_model as fixtures


async def main() -> None:
    connection = await support.database_connection(settings.POSTGRES_DB)
    rows = []
    statements: list[str] = []

    def record(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, 'before_cursor_execute', record)
    try:
        for size in (1, 30):
            user_id, profile_id = await fixtures.seed_user(connection, f's91-{size}', company_name='Synthetic audit company')
            admin_id, _ = await fixtures.seed_user(connection, f's91-admin-{size}', company_name=None, is_admin=True)
            assert profile_id
            tenders = []
            for index in range(size):
                tender_id = await fixtures.seed_tender(connection, f's91-{size}-{index}')
                tenders.append(tender_id)
                await fixtures.seed_private_context(connection, user_id=user_id, profile_id=profile_id,
                    tender_id=tender_id, engagement_status='SAVED', proposal_status='DRAFT',
                    compliance_status='COMPLETED', version_count=size if index == 0 else 1)
                await fixtures.add_document(connection, tender_id, index)
            await fixtures.seed_readiness(connection, profile_id=profile_id, extra_documents=size-1)
            tid = tenders[0]
            aid = await connection.fetchval('SELECT id FROM tender_analyses WHERE tender_id=$1 AND user_id=$2', tid, user_id)
            token = create_access_token({'sub': str(user_id), 'auth_version': 0})
            admin_token = create_access_token({'sub': str(admin_id), 'auth_version': 0})
            paths = [
                ('explorer', '/api/v1/explorer/tenders?limit=25'),
                ('explorer_available', '/api/v1/explorer/tenders?limit=25&document_status=documents_available'),
                ('details', f'/api/v1/tenders/{tid}/details'),
                ('my_tenders', '/api/v1/my-tenders?limit=25'),
                ('proposals', '/api/v1/proposals'),
                ('compliance_latest', f'/api/v1/tenders/{tid}/latest-analysis'),
                ('compliance_history', f'/api/v1/tenders/{tid}/analyses/{aid}/versions'),
                ('compliance_detail', f'/api/v1/tenders/{tid}/analyses/{aid}/versions/1'),
                ('vault', '/api/v1/vault'), ('readiness', '/api/v1/vault/readiness'),
                ('source_status', '/api/v1/tenders/sources/refresh-status'),
                ('source_activity', '/api/v1/tenders/sources/refresh-activity?limit=25'),
                ('source_catalog', '/api/v1/tenders/sources/catalog'),
                ('admin_accounts', '/api/v1/admin/accounts?limit=25'),
                ('admin_approvals', '/api/v1/admin/approval-queue'),
            ]
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://audit.invalid') as client:
                for label, path in paths:
                    statements.clear()
                    start = time.perf_counter()
                    response = await client.get(path, headers={'Authorization': 'Bearer ' + (admin_token if label.startswith('admin_') else token)})
                    payload = response.json()
                    rows.append({'fixture_size': size, 'label': label, 'path': path,
                        'status': response.status_code, 'query_count': len(statements),
                        'elapsed_ms': round((time.perf_counter()-start)*1000, 2),
                        'items': len(payload) if isinstance(payload, list) else len(payload.get('items', [])),
                        'write_statements': sum(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for s in statements),
                        'sql_without_parameters': list(statements)})
                    print(size, label, response.status_code, len(statements), flush=True)
    finally:
        event.remove(engine.sync_engine, 'before_cursor_execute', record)
        await connection.close()
        await engine.dispose()
        output = BACKEND.parent / 'docs/audits/s9_1_query_measurements.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({'method': 'HTTP ASGI; real JWT/account dependencies and PostgreSQL; synthetic 1/30 rows; cumulative shared corpus 1/31; source activity empty; warm process, no external I/O', 'measurements': rows}, indent=2) + '\n')


if __name__ == '__main__':
    asyncio.run(main())
