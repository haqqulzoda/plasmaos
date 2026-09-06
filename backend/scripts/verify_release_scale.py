#!/usr/bin/env python3
"""Synthetic PostgreSQL scale proof. Always creates and drops its own database."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from time import monotonic
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.release_test_target import assert_local_test_target


async def run():
    assert_local_test_target()
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.api.endpoints import tenders
    from app.services.explorer import ExplorerQuery, list_explorer_tenders
    from scripts import test_s0_5b4_baseline as support
    from scripts.verify_s6_2_unified_explorer_backend import seed_owner
    database = support.database_name("release_scale")
    await support.create_database(database)
    engine = None
    rows = []
    try:
        bootstrap = await asyncio.to_thread(support.run_bootstrap, database)
        if bootstrap.returncode:
            raise RuntimeError("Disposable bootstrap failed")
        connection = await support.database_connection(database)
        try:
            user_id, _ = await seed_owner(connection, "release-scale")
            engine = create_async_engine(support.target_url(database))
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            statements = []
            def record(conn, cursor, statement, parameters, context, executemany):
                assert not statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")), "Passive domain mutation"
                statements.append((statement, parameters))
            event.listen(engine.sync_engine, "before_cursor_execute", record)
            with tempfile.TemporaryDirectory(prefix="release-scale-") as directory:
                stored = Path(directory) / "stored.pdf"
                stored.write_bytes(b"%PDF-1.4 synthetic storage fixture")
                previous = 0
                for size in (1000, 10000, 100000):
                    await connection.execute("""
                        INSERT INTO tenders (id,external_id,source_system,canonical_source_key,source_url,title,description,budget,currency,status,country,category,compiled_master_text)
                        SELECT gen_random_uuid(), 'release-'||i, 'world_bank', 'world_bank:release:'||i,
                          'https://example.invalid/release/'||i, 'Synthetic scale tender '||i, 'Construction',1000,'USD','OPEN','Uzbekistan','Construction',repeat('x',1000)
                        FROM generate_series($1::int,$2::int) i
                    """, previous + 1, size)
                    await connection.execute("""
                        INSERT INTO tender_documents(id,tender_id,file_url,file_type,download_status,storage_path)
                        SELECT gen_random_uuid(),id,'https://example.invalid/file.pdf','pdf',
                          CASE WHEN substring(external_id from 9)::int % 2 = 0 THEN 'downloaded' ELSE 'metadata_only' END,
                          CASE WHEN substring(external_id from 9)::int % 2 = 0 THEN $3 ELSE NULL END
                        FROM tenders WHERE substring(external_id from 9)::int BETWEEN $1 AND $2
                    """, previous + 1, size, str(stored))
                    await connection.execute("ANALYZE tenders")
                    await connection.execute("ANALYZE tender_documents")
                    previous = size
                    for mode in ("documents_available", "metadata_only", "files_missing"):
                        statements.clear()
                        with patch.object(tenders, "storage_file_exists", wraps=tenders.storage_file_exists) as stat:
                            started = monotonic()
                            async with sessions() as db:
                                response = await list_explorer_tenders(db, user_id=user_id,
                                    query=ExplorerQuery(document_status=mode, limit=25, tender_status="all"))
                            elapsed = round((monotonic() - started) * 1000, 2)
                        assert len(response.items) <= 25
                        assert response.total == (0 if mode == "files_missing" else size // 2)
                        assert len(statements) <= 5
                        assert stat.call_count <= 25
                        plans = []
                        for statement, parameters in statements:
                            if "FROM tenders" in statement:
                                plan = await connection.fetchval("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, *parameters)
                                plans.append(json.loads(plan))
                        rows.append({"corpus":size,"filter":mode,"page_rows":len(response.items),"total":response.total,
                            "queries":len(statements),"filesystem_checks":stat.call_count,"elapsed_ms":elapsed,"plans":plans})
                        print(f"scale={size} filter={mode} queries={len(statements)} files={stat.call_count} ms={elapsed}", flush=True)
            return {"method":"Synthetic local PostgreSQL; one document per tender; 25-row page; no production latency claim", "rows":rows}
        finally:
            await connection.close()
    finally:
        if engine: await engine.dispose()
        await support.drop_database(database)


if __name__ == "__main__":
    result = asyncio.run(run())
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(result, indent=2))
