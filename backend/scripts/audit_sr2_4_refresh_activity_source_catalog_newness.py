#!/usr/bin/env python3
"""Disposable 100k activity/10k Explorer proof and read-only SR-2.4 preflight."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from time import monotonic
from uuid import uuid4

import asyncpg
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.dialects import postgresql

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings
from app.models.all_models import SourceRefreshJob, Tender
from app.schemas.explorer import ExplorerView
from app.services.explorer import ExplorerQuery, list_explorer_tenders
from app.services.source_refresh_activity import (
    _status_ranked_query,
    source_catalog,
    source_refresh_activity,
    source_refresh_status,
)
from app.services.source_registry import SOURCE_REGISTRY
from scripts import bootstrap_database as bootstrap


HEAD = "20260902_0001_s7_2_user_ui_locale"
PREFIX = "plasma_sr24_"


def _safe_database(database: str) -> None:
    if not re.fullmatch(r"plasma_sr24_[a-f0-9]{12}", database):
        raise RuntimeError(f"unsafe disposable database name: {database!r}")


def _url(database: str) -> str:
    return (
        f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{database}"
    )


async def _connect(database: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        user=settings.POSTGRES_USER, password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_SERVER, port=settings.POSTGRES_PORT,
        database=database,
    )


def _environment(database: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        POSTGRES_SERVER=settings.POSTGRES_SERVER,
        POSTGRES_PORT=str(settings.POSTGRES_PORT),
        POSTGRES_USER=settings.POSTGRES_USER,
        POSTGRES_PASSWORD=settings.POSTGRES_PASSWORD,
        POSTGRES_DB=database,
        PLASMA_BOOTSTRAP_DATABASE_URL=_url(database),
        AUTO_CREATE_TABLES="false",
    )
    return environment


def _bootstrap(database: str) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/bootstrap_database.py", "--confirm", bootstrap.CONFIRMATION],
        cwd=BACKEND, env=_environment(database), text=True,
        capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr)[-4000:])


async def _seed(database: str) -> None:
    connection = await _connect(database)
    try:
        await connection.execute(
            """
            INSERT INTO source_refresh_jobs (
                id, source_system, status, trigger_kind, options_json, force,
                created_count, updated_count, unchanged_count, fetched_count,
                skipped_count, rejected_count, failed_count,
                documents_discovered_count, documents_queued_count,
                fallback_used, created_at, completed_at, updated_at, message
            )
            SELECT md5('sr24-job-' || g::text)::uuid,
                   (ARRAY['uzex','world_bank','giz','adb','ebrd','internal_hidden'])[(g % 6)+1],
                   (ARRAY['completed','partial','failed','source_unavailable'])[(g % 4)+1],
                   'scheduled', '{}'::json, false,
                   g % 13, g % 17, g % 19, (g % 49)+1,
                   g % 3, g % 5, CASE WHEN g % 4 = 1 THEN 0 ELSE g % 3 END,
                   g % 7, g % 5, (g % 29 = 0),
                   timestamptz '2026-01-01 00:00:00+00' + ((g / 10) * interval '1 second'),
                   timestamptz '2026-01-01 00:00:00+00' + ((g / 10) * interval '1 second'),
                   timestamptz '2026-01-01 00:00:00+00' + ((g / 10) * interval '1 second'),
                   'seeded terminal event'
            FROM generate_series(1, 100000) AS g
            """
        )
        await connection.execute(
            """
            INSERT INTO source_refresh_jobs (
                id, source_system, status, trigger_kind, options_json, force,
                created_count, updated_count, unchanged_count, fetched_count,
                skipped_count, rejected_count, failed_count,
                documents_discovered_count, documents_queued_count,
                fallback_used, created_at, started_at, heartbeat_at, updated_at, message
            ) VALUES (
                $1, 'world_bank', 'running', 'customer', '{}'::json, false,
                0,0,0,0,0,0,0,0,0,false, now(), now(), now(), now(), 'Refreshing.'
            )
            """,
            uuid4(),
        )
        await connection.execute(
            """
            INSERT INTO tenders (
                id, external_id, source_system, canonical_source_key, source_url,
                title, budget, currency, status, category, publication_date, created_at
            )
            SELECT md5('sr24-tender-' || g::text)::uuid,
                   'sr24-' || g::text,
                   (ARRAY['uzex','world_bank','giz','adb','ebrd'])[(g % 5)+1],
                   (ARRAY['uzex','world_bank','giz','adb','ebrd'])[(g % 5)+1] || ':sr24-' || g::text,
                   'https://example.test/tender/' || g::text,
                   'SR-2.4 scale tender ' || g::text, 0, 'USD', 'OPEN', 'Other',
                   now() - interval '30 days',
                   now() - ((g % 72) * interval '1 hour')
            FROM generate_series(1, 10000) AS g
            """
        )
        await connection.execute("ANALYZE source_refresh_jobs")
        await connection.execute("ANALYZE tenders")
    finally:
        await connection.close()


def _plan_nodes(plan: dict[str, object]) -> list[str]:
    names = [str(plan.get("Node Type"))]
    if plan.get("Index Name"):
        names[-1] += f":{plan['Index Name']}"
    for child in plan.get("Plans", []) or []:
        names.extend(_plan_nodes(child))
    return names


async def _query_plans(database: str) -> dict[str, object]:
    visible = ("uzex", "world_bank", "giz", "adb", "ebrd")
    status_sql = str(
        _status_ranked_query(visible).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    activity_sql = """
        SELECT id FROM source_refresh_jobs
        WHERE source_system = ANY(ARRAY['uzex','world_bank','giz','adb','ebrd'])
          AND status = ANY(ARRAY['completed','partial','source_unavailable','failed'])
          AND completed_at IS NOT NULL AND trigger_kind IS NOT NULL
        ORDER BY completed_at ASC, id ASC LIMIT 26
    """
    connection = await _connect(database)
    try:
        results: dict[str, object] = {}
        for name, sql in (("status", status_sql), ("activity", activity_sql)):
            payload = await connection.fetchval(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql
            )
            if isinstance(payload, str):
                payload = json.loads(payload)
            root = payload[0]
            results[name] = {
                "planning_ms": round(float(root["Planning Time"]), 3),
                "execution_ms": round(float(root["Execution Time"]), 3),
                "nodes": _plan_nodes(root["Plan"]),
            }
        return results
    finally:
        await connection.close()


async def _fingerprint(db) -> dict[str, int]:
    tables = (
        "tenders", "tender_documents", "source_refresh_jobs",
        "tender_recommendations", "tender_engagements", "proposals",
        "tender_analyses", "analysis_versions",
    )
    return {
        table: int((await db.execute(text(f'SELECT count(*) FROM "{table}"'))).scalar_one())
        for table in tables
    }


async def _proof(database: str) -> dict[str, object]:
    engine = create_async_engine(_url(database), pool_size=5, max_overflow=5)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    statement_count = 0

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count(*_args) -> None:
        nonlocal statement_count
        statement_count += 1

    try:
        async with sessions() as db:
            before = await _fingerprint(db)

            catalog_started = monotonic()
            catalog = source_catalog()
            catalog_ms = int((monotonic() - catalog_started) * 1000)

            statement_count = 0
            status_started = monotonic()
            statuses = await source_refresh_status(db)
            status_ms = int((monotonic() - status_started) * 1000)
            status_queries = statement_count
            baseline = statuses[0].activity_cursor
            assert len(statuses) == 5 and len({item.activity_cursor for item in statuses}) == 1
            world_bank_status = next(item for item in statuses if item.source_system == "world_bank")
            assert world_bank_status.active_job is not None and world_bank_status.latest_terminal is not None

            statement_count = 0
            activity_started = monotonic()
            first = await source_refresh_activity(db, cursor=None, limit=5)
            second = await source_refresh_activity(db, cursor=first.next_cursor, limit=5)
            activity_ms = int((monotonic() - activity_started) * 1000)
            activity_queries = statement_count
            first_ids = [event.job_id for event in first.events]
            second_ids = [event.job_id for event in second.events]
            assert not set(first_ids) & set(second_ids)
            combined = [*first.events, *second.events]
            assert combined == sorted(combined, key=lambda item: (item.completed_at, item.job_id))
            assert all(item.source_system in SOURCE_REGISTRY for item in combined)

            test_registry = dict(SOURCE_REGISTRY)
            test_registry["ebrd"] = replace(SOURCE_REGISTRY["ebrd"], refresh_enabled=False)
            test_registry["internal_hidden"] = replace(
                SOURCE_REGISTRY["adb"], key="internal_hidden",
                display_name="Internal Hidden", customer_visible=False,
            )
            disabled_status = await source_refresh_status(db, test_registry)
            disabled_ebrd = next(item for item in disabled_status if item.source_system == "ebrd")
            assert not disabled_ebrd.can_refresh and disabled_ebrd.latest_terminal is not None
            hidden_activity = await source_refresh_activity(
                db, cursor=None, limit=100, registry=test_registry,
            )
            assert all(item.source_system != "internal_hidden" for item in hidden_activity.events)

            after_passive_reads = await _fingerprint(db)
            assert before == after_passive_reads

            new_job = await db.get(SourceRefreshJob, world_bank_status.active_job.job_id)
            assert new_job is not None
            new_job.status = "completed"
            new_job.created_count = 12
            new_job.fetched_count = 12
            new_job.completed_at = max(
                item.latest_terminal.completed_at for item in statuses if item.latest_terminal
            ) + __import__("datetime").timedelta(seconds=1)
            new_job.message = "Refresh completed."
            await db.commit()
            after_baseline = await source_refresh_activity(db, cursor=baseline, limit=25)
            assert [item.job_id for item in after_baseline.events] == [new_job.id]
            transitioned_statuses = await source_refresh_status(db)
            transitioned_wb = next(item for item in transitioned_statuses if item.source_system == "world_bank")
            assert transitioned_wb.active_job is None
            assert transitioned_wb.latest_terminal.job_id == new_job.id

            statement_count = 0
            ordinary_started = monotonic()
            ordinary = await list_explorer_tenders(
                db, user_id=uuid4(), query=ExplorerQuery(view=ExplorerView.ALL, limit=25)
            )
            ordinary_ms = int((monotonic() - ordinary_started) * 1000)
            ordinary_queries = statement_count

            statement_count = 0
            new_started = monotonic()
            recent = await list_explorer_tenders(
                db, user_id=uuid4(),
                query=ExplorerQuery(view=ExplorerView.ALL, source="world_bank", new_only=True, limit=25),
            )
            new_ms = int((monotonic() - new_started) * 1000)
            new_queries = statement_count
            assert all(item.tender.is_new and item.tender.source_system == "world_bank" for item in recent.items)
            assert all(item.tender.new_until > recent.server_time for item in recent.items)

            variants = {
                "search": ExplorerQuery(new_only=True, q="scale tender 1", limit=10),
                "document": ExplorerQuery(new_only=True, document_status="no_documents_found", limit=10),
                "recommended": ExplorerQuery(view=ExplorerView.RECOMMENDED, new_only=True, limit=10),
                "dismissed": ExplorerQuery(view=ExplorerView.DISMISSED, new_only=True, limit=10),
                "pagination": ExplorerQuery(new_only=True, limit=10, offset=10),
            }
            variant_totals = {}
            for name, variant in variants.items():
                response = await list_explorer_tenders(db, user_id=uuid4(), query=variant)
                variant_totals[name] = response.total
                assert all(item.tender.is_new for item in response.items)

            after = await _fingerprint(db)
            assert before["tenders"] == after["tenders"]
            assert before == after

            return {
                "history_rows": before["source_refresh_jobs"],
                "tender_rows": before["tenders"],
                "catalog": {"items": len(catalog), "queries": 0, "ms": catalog_ms},
                "status": {"items": len(statuses), "queries": status_queries, "ms": status_ms},
                "activity_two_pages": {
                    "events": len(combined), "queries": activity_queries,
                    "ms": activity_ms, "tie_overlap": 0,
                },
                "visibility": {
                    "hidden_history_exposed": False,
                    "disabled_visible_history": True,
                    "disabled_can_refresh": disabled_ebrd.can_refresh,
                },
                "bootstrap_race": {"events_after_baseline": 1, "created_count": after_baseline.events[0].created_count},
                "explorer_ordinary": {"total": ordinary.total, "queries": ordinary_queries, "ms": ordinary_ms},
                "explorer_new_source": {"total": recent.total, "queries": new_queries, "ms": new_ms},
                "explorer_new_variants": variant_totals,
                "passive_fingerprint": "all_counts_unchanged",
            }
    finally:
        await engine.dispose()


async def disposable() -> dict[str, object]:
    database = f"{PREFIX}{uuid4().hex[:12]}"
    _safe_database(database)
    admin = await _connect("postgres")
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    try:
        await asyncio.to_thread(_bootstrap, database)
        await _seed(database)
        plans = await _query_plans(database)
        proof = await _proof(database)
        connection = await _connect(database)
        try:
            head = await connection.fetchval("SELECT version_num FROM alembic_version")
        finally:
            await connection.close()
        assert head == HEAD
        return {"status": "passed", "head": head, "query_plans": plans, **proof}
    finally:
        admin = await _connect("postgres")
        try:
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=$1 AND pid<>pg_backend_pid()", database,
            )
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        finally:
            await admin.close()


async def preflight() -> dict[str, object]:
    connection = await _connect(settings.POSTGRES_DB)
    try:
        head = await connection.fetchval("SELECT version_num FROM alembic_version")
        jobs = await connection.fetchval("SELECT count(*) FROM source_refresh_jobs")
        active = await connection.fetchval(
            "SELECT count(*) FROM source_refresh_jobs WHERE status IN ('queued','running')"
        )
        recent = await connection.fetchval(
            "SELECT count(*) FROM tenders WHERE created_at <= now() AND created_at > now() - interval '24 hours'"
        )
        return {
            "mode": "read_only", "head": head, "expected_head": HEAD,
            "jobs": jobs, "active_jobs": active, "currently_new_tenders": recent,
        }
    finally:
        await connection.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(await (preflight() if arguments.preflight else disposable()), indent=2, default=str, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
