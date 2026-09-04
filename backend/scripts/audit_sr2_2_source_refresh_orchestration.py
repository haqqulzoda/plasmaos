#!/usr/bin/env python3
"""Disposable PostgreSQL proof and read-only local preflight for SR-2.2."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import asyncpg
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.models.all_models import SourceRefreshJob, User
from app.services.source_refresh_jobs import (
    SourceRefreshClaimStatus,
    claim_source_refresh_job,
    complete_source_refresh_job,
    renew_source_refresh_lease,
)
from scripts import bootstrap_database as bootstrap

HEAD = "20260902_0001_s7_2_user_ui_locale"
PREVIOUS_HEAD = "20260828_0003_s4_1_tender_engagement_foundation"
PREFIX = "plasma_sr22_"


def _database_name() -> str:
    return f"{PREFIX}{uuid4().hex[:12]}"


def _assert_disposable(database: str) -> None:
    if not re.fullmatch(r"plasma_sr22_[a-f0-9]{12}", database):
        raise RuntimeError(f"unsafe disposable database name: {database!r}")


async def _admin_connection() -> asyncpg.Connection:
    return await asyncpg.connect(
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        database="postgres",
    )


async def _create_database(database: str) -> None:
    _assert_disposable(database)
    connection = await _admin_connection()
    try:
        await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()


async def _drop_database(database: str) -> None:
    _assert_disposable(database)
    connection = await _admin_connection()
    try:
        await connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database,
        )
        await connection.execute(f'DROP DATABASE IF EXISTS "{database}"')
    finally:
        await connection.close()


def _url(database: str) -> str:
    _assert_disposable(database)
    return (
        f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{database}"
    )


def _environment(database: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "POSTGRES_SERVER": settings.POSTGRES_SERVER,
            "POSTGRES_PORT": str(settings.POSTGRES_PORT),
            "POSTGRES_USER": settings.POSTGRES_USER,
            "POSTGRES_PASSWORD": settings.POSTGRES_PASSWORD,
            "POSTGRES_DB": database,
            "PLASMA_BOOTSTRAP_DATABASE_URL": _url(database),
            "AUTO_CREATE_TABLES": "false",
        }
    )
    return environment


def _command(database: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=_environment(database),
        text=True,
        capture_output=True,
        check=False,
    )


def _bootstrap(database: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/bootstrap_database.py",
            "--confirm",
            bootstrap.CONFIRMATION,
        ],
        cwd=BACKEND_DIR,
        env=_environment(database),
        text=True,
        capture_output=True,
        check=False,
    )


async def _existing_database_matrix(database: str) -> dict[str, Any]:
    downgrade = await asyncio.to_thread(_command, database, "downgrade", PREVIOUS_HEAD)
    assert downgrade.returncode == 0, (downgrade.stdout + downgrade.stderr)[-4000:]
    connection = await asyncpg.connect(
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        database=database,
    )
    historical_id = uuid4()
    try:
        tender_count_before = await connection.fetchval("SELECT count(*) FROM tenders")
        await connection.execute(
            """
            INSERT INTO source_refresh_jobs (
                id, source_system, status, force, created_count, updated_count,
                fetched_count, skipped_count, rejected_count, failed_count,
                fallback_used, message
            ) VALUES ($1, 'giz', 'completed', false, 1, 2, 3, 0, 0, 0,
                      false, 'historical job')
            """,
            historical_id,
        )
    finally:
        await connection.close()

    upgrade = await asyncio.to_thread(_command, database, "upgrade", "head")
    assert upgrade.returncode == 0, (upgrade.stdout + upgrade.stderr)[-4000:]
    connection = await asyncpg.connect(
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        database=database,
    )
    try:
        historical = await connection.fetchrow(
            """
            SELECT trigger_kind, options_json, unchanged_count,
                   documents_discovered_count, documents_queued_count,
                   lease_owner, lease_expires_at, heartbeat_at
            FROM source_refresh_jobs WHERE id = $1
            """,
            historical_id,
        )
        tender_count_after = await connection.fetchval("SELECT count(*) FROM tenders")
    finally:
        await connection.close()
    assert historical is not None
    assert historical["trigger_kind"] is None
    historical_options = historical["options_json"]
    if isinstance(historical_options, str):
        historical_options = json.loads(historical_options)
    assert historical_options == {}
    assert all(
        historical[name] == 0
        for name in (
            "unchanged_count",
            "documents_discovered_count",
            "documents_queued_count",
        )
    )
    assert tender_count_before == tender_count_after
    return {
        "historical_trigger": None,
        "historical_defaults": "readable",
        "tender_rows_before": tender_count_before,
        "tender_rows_after": tender_count_after,
    }


async def _lease_matrix(database: str) -> dict[str, Any]:
    engine = create_async_engine(_url(database), pool_size=5, max_overflow=5)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    timestamp = datetime.now(timezone.utc)
    job_id = uuid4()
    owner_a, owner_b = uuid4(), uuid4()
    try:
        async with sessions() as db:
            db.add(
                SourceRefreshJob(
                    id=job_id,
                    source_system="world_bank",
                    requested_by_user_id=None,
                    trigger_kind="scheduled",
                    options_json={"max_pages": 2},
                    status="queued",
                    force=False,
                    message="Refresh queued.",
                )
            )
            await db.commit()
        async with sessions() as db:
            claim_a = await claim_source_refresh_job(
                db,
                job_id=job_id,
                source_system="world_bank",
                lease_owner=owner_a,
                now=timestamp,
            )
        async with sessions() as db:
            claim_b_live = await claim_source_refresh_job(
                db,
                job_id=job_id,
                source_system="world_bank",
                lease_owner=owner_b,
                now=timestamp + timedelta(seconds=1),
            )
        async with sessions() as db:
            heartbeat_a = await renew_source_refresh_lease(
                db,
                job_id=job_id,
                lease_owner=owner_a,
                now=timestamp + timedelta(seconds=30),
            )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE source_refresh_jobs SET created_count = 9, "
                    "unchanged_count = 8, lease_expires_at = :expired WHERE id = :id"
                ),
                {"expired": timestamp - timedelta(seconds=1), "id": job_id},
            )
        async with sessions() as db:
            takeover_b = await claim_source_refresh_job(
                db,
                job_id=job_id,
                source_system="world_bank",
                lease_owner=owner_b,
                now=timestamp + timedelta(seconds=31),
            )
        async with sessions() as db:
            old_heartbeat = await renew_source_refresh_lease(
                db,
                job_id=job_id,
                lease_owner=owner_a,
                now=timestamp + timedelta(seconds=32),
            )
        async with sessions() as db:
            old_terminal = await complete_source_refresh_job(
                db,
                job_id=job_id,
                lease_owner=owner_a,
                terminal_status="failed",
                result_values={"message": "stale owner"},
                now=timestamp + timedelta(seconds=32),
            )
        async with sessions() as db:
            terminal_b = await complete_source_refresh_job(
                db,
                job_id=job_id,
                lease_owner=owner_b,
                terminal_status="completed",
                result_values={
                    "fetched_count": 10,
                    "created_count": 2,
                    "updated_count": 3,
                    "unchanged_count": 5,
                    "documents_discovered_count": 4,
                    "documents_queued_count": 0,
                    "message": "Refresh completed.",
                },
                now=timestamp + timedelta(seconds=33),
            )
        async with sessions() as db:
            terminal_redelivery = await claim_source_refresh_job(
                db,
                job_id=job_id,
                source_system="world_bank",
                lease_owner=uuid4(),
                now=timestamp + timedelta(seconds=34),
            )
            record = await db.get(SourceRefreshJob, job_id)
        assert claim_a.status == SourceRefreshClaimStatus.CLAIMED
        assert claim_b_live.status == SourceRefreshClaimStatus.BUSY
        assert heartbeat_a
        assert takeover_b.status == SourceRefreshClaimStatus.CLAIMED
        assert not old_heartbeat and not old_terminal and terminal_b
        assert terminal_redelivery.status == SourceRefreshClaimStatus.TERMINAL
        assert record is not None
        assert (record.created_count, record.updated_count, record.unchanged_count) == (
            2,
            3,
            5,
        )
        assert record.documents_discovered_count == 4
        assert record.documents_queued_count == 0
        return {
            "first_claim": claim_a.status.value,
            "duplicate_live_claim": claim_b_live.status.value,
            "heartbeat": heartbeat_a,
            "expired_takeover": takeover_b.status.value,
            "old_owner_heartbeat": old_heartbeat,
            "old_owner_terminal": old_terminal,
            "new_owner_terminal": terminal_b,
            "terminal_redelivery": terminal_redelivery.status.value,
            "semantic_counts": [
                record.created_count,
                record.updated_count,
                record.unchanged_count,
            ],
        }
    finally:
        await engine.dispose()


async def _request_and_status_matrix(database: str) -> dict[str, Any]:
    from app.api.endpoints.tenders import (
        _request_source_refresh,
        get_source_refresh_status,
    )

    engine = create_async_engine(_url(database), pool_size=10, max_overflow=20)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    requester = User(
        google_id=f"sr22-{uuid4().hex}",
        email=f"sr22-{uuid4().hex}@example.test",
        name="SR-2.2 Audit Operator",
        approval_status="approved",
        platform_role="admin",
        is_admin=True,
    )
    try:
        async with sessions() as db:
            db.add(requester)
            await db.commit()

        async def request_once():
            async with sessions() as db:
                return await _request_source_refresh(
                    source_system="uzex",
                    force=False,
                    current_user=requester,
                    db=db,
                )

        with patch(
            "app.api.endpoints.tenders.refresh_tender_source.apply_async",
            return_value=SimpleNamespace(id="audit-delivery"),
        ) as publish:
            responses = await asyncio.gather(*(request_once() for _ in range(20)))
        job_ids = {response.job_id for response in responses}
        assert len(job_ids) == 1
        assert publish.call_count == 1
        async with sessions() as db:
            active_uzex = await db.scalar(
                select(func.count(SourceRefreshJob.id)).where(
                    SourceRefreshJob.source_system == "uzex",
                    SourceRefreshJob.status.in_(("queued", "running")),
                )
            )
        assert active_uzex == 1

        async def request_operator(source_system: str):
            async with sessions() as db:
                return await _request_source_refresh(
                    source_system=source_system,
                    force=True,
                    current_user=requester,
                    db=db,
                    trigger_kind="operator",
                    options={},
                )

        with patch(
            "app.api.endpoints.tenders.refresh_tender_source.apply_async",
            return_value=SimpleNamespace(id="cross-source-delivery"),
        ) as cross_source_publish:
            cross_source_responses = await asyncio.gather(
                request_operator("giz"),
                request_operator("adb"),
            )
        assert len({response.job_id for response in cross_source_responses}) == 2
        assert cross_source_publish.call_count == 2

        with patch(
            "app.api.endpoints.tenders.refresh_tender_source.apply_async",
            return_value=SimpleNamespace(id="unexpected-force-delivery"),
        ) as forced_publish:
            async with sessions() as db:
                forced_active = await _request_source_refresh(
                    source_system="uzex",
                    force=True,
                    current_user=requester,
                    db=db,
                    trigger_kind="operator",
                    options={},
                )
        assert forced_active.job_id in job_ids
        assert forced_active.reused
        assert forced_publish.call_count == 0

        select_count = 0

        def count_selects(
            _connection: Any,
            _cursor: Any,
            statement: str,
            _parameters: Any,
            _context: Any,
            _executemany: bool,
        ) -> None:
            nonlocal select_count
            if statement.lstrip().casefold().startswith("select"):
                select_count += 1

        event.listen(engine.sync_engine, "before_cursor_execute", count_selects)
        try:
            async with sessions() as db:
                statuses = await get_source_refresh_status(
                    _current_user=requester,
                    db=db,
                )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count_selects)
        assert select_count == 1
        assert {item.source_system for item in statuses} == {
            "uzex",
            "world_bank",
            "adb",
            "giz",
            "ebrd",
        }
        safe_fields = set(statuses[0].model_dump())
        assert not {
            "lease_owner",
            "options_json",
            "requested_by_user_id",
        } & safe_fields
        return {
            "concurrent_same_source_requests": len(responses),
            "durable_job_ids": len(job_ids),
            "broker_publications": publish.call_count,
            "active_uzex_jobs": active_uzex,
            "cross_source_independent_jobs": len(cross_source_responses),
            "cross_source_publications": cross_source_publish.call_count,
            "force_reused_active_job": forced_active.reused,
            "force_active_publications": forced_publish.call_count,
            "status_sources": len(statuses),
            "status_select_queries": select_count,
            "private_status_fields": [],
        }
    finally:
        await engine.dispose()


async def _schema_result(database: str) -> dict[str, str]:
    current = await asyncio.to_thread(_command, database, "current")
    heads = await asyncio.to_thread(_command, database, "heads")
    check = await asyncio.to_thread(_command, database, "check")
    diagnostic = current.stdout + heads.stdout + check.stdout + check.stderr
    assert current.returncode == heads.returncode == check.returncode == 0, diagnostic[-4000:]
    assert HEAD in current.stdout and HEAD in heads.stdout
    assert "No new upgrade operations detected" in diagnostic
    return {"head": HEAD, "alembic_check": "clean"}


async def _local_preflight() -> int:
    connection = await asyncpg.connect(
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
    )
    try:
        columns = {
            row["column_name"]
            for row in await connection.fetch(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'source_refresh_jobs'
                """
            )
        }
        by_source_status = [
            dict(row)
            for row in await connection.fetch(
                """
                SELECT source_system, status, count(*) AS jobs
                FROM source_refresh_jobs GROUP BY source_system, status
                ORDER BY source_system, status
                """
            )
        ]
        active_jobs = await connection.fetchval(
            "SELECT count(*) FROM source_refresh_jobs "
            "WHERE status IN ('queued', 'running')"
        )
        latest = [
            dict(row)
            for row in await connection.fetch(
                """
                SELECT source_system, max(completed_at) AS latest_completion
                FROM source_refresh_jobs GROUP BY source_system ORDER BY source_system
                """
            )
        ]
        expired = (
            await connection.fetchval(
                "SELECT count(*) FROM source_refresh_jobs "
                "WHERE status = 'running' AND lease_expires_at <= now()"
            )
            if "lease_expires_at" in columns
            else None
        )
        missing_trigger = (
            await connection.fetchval(
                "SELECT count(*) FROM source_refresh_jobs WHERE trigger_kind IS NULL"
            )
            if "trigger_kind" in columns
            else None
        )
        legacy_running = await connection.fetchval(
            "SELECT count(*) FROM source_refresh_jobs WHERE status = 'running' "
            + (
                "AND lease_owner IS NULL AND updated_at < now() - interval '180 seconds'"
                if "lease_owner" in columns
                else "AND updated_at < now() - interval '180 seconds'"
            )
        )
        counter_columns = [
            name
            for name in (
                "created_count",
                "updated_count",
                "unchanged_count",
                "fetched_count",
                "skipped_count",
                "rejected_count",
                "failed_count",
                "documents_discovered_count",
                "documents_queued_count",
            )
            if name in columns
        ]
        anomaly_predicate = " OR ".join(f"{name} < 0" for name in counter_columns)
        anomalies = await connection.fetchval(
            f"SELECT count(*) FROM source_refresh_jobs WHERE {anomaly_predicate}"
        )
        print(
            json.dumps(
                {
                    "mode": "read_only_local_preflight",
                    "schema_has_sr2_2_fields": "lease_owner" in columns,
                    "jobs_by_source_status": by_source_status,
                    "active_jobs": active_jobs,
                    "expired_leases": expired,
                    "jobs_missing_historical_trigger": missing_trigger,
                    "latest_completion_by_source": latest,
                    "stale_legacy_running_jobs": legacy_running,
                    "negative_counter_anomalies": anomalies,
                },
                indent=2,
                default=str,
            )
        )
        return 0
    finally:
        await connection.close()


async def _disposable_audit() -> int:
    database = _database_name()
    await _create_database(database)
    try:
        bootstrapped = await asyncio.to_thread(_bootstrap, database)
        if bootstrapped.returncode:
            raise RuntimeError((bootstrapped.stderr or bootstrapped.stdout)[-5000:])
        existing = await _existing_database_matrix(database)
        lease = await _lease_matrix(database)
        request_and_status = await _request_and_status_matrix(database)
        schema = await _schema_result(database)
        print(
            json.dumps(
                {
                    "status": "passed",
                    "schema": schema,
                    "existing_database": existing,
                    "fresh_database_lease_matrix": lease,
                    "request_and_status_matrix": request_and_status,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    finally:
        await _drop_database(database)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    arguments = parser.parse_args()
    return await (_local_preflight() if arguments.preflight else _disposable_audit())


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
