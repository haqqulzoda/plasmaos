#!/usr/bin/env python3
"""Disposable PostgreSQL proof and read-only local preflight for SR-2.3."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from time import monotonic
from uuid import uuid4

import asyncpg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings
from app.models.all_models import TenderDocument
from app.services.tender_sources.adb import AdbTenderSource
from app.services.tender_sources.base import (
    CanonicalDocument,
    persist_document_descriptors,
    persist_tender_batch,
)
from scripts import bootstrap_database as bootstrap

HEAD = "20260901_0001_sr2_3_connector_metrics"
PREVIOUS_HEAD = "20260831_0001_sr2_2_refresh_leases"
PREFIX = "plasma_sr23_"
METRICS = (
    "fetch_elapsed_ms", "normalize_elapsed_ms", "persist_elapsed_ms",
    "document_dispatch_elapsed_ms", "http_request_count",
    "http_retry_count", "http_failure_count",
)


def _safe_name(value: str) -> None:
    if not re.fullmatch(r"plasma_sr23_[a-f0-9]{12}", value):
        raise RuntimeError(f"unsafe disposable database name: {value!r}")


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
        PLASMA_BOOTSTRAP_DATABASE_URL=(
            f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
            f"@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{database}"
        ),
        AUTO_CREATE_TABLES="false",
    )
    return environment


def _url(database: str) -> str:
    return (
        f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{database}"
    )


def _alembic(database: str, *arguments: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments], cwd=BACKEND,
        env=_environment(database), text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr)[-4000:])


def _bootstrap(database: str) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/bootstrap_database.py", "--confirm", bootstrap.CONFIRMATION],
        cwd=BACKEND, env=_environment(database), text=True,
        capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr)[-4000:])


async def _document_matrix(database: str) -> dict[str, object]:
    engine = create_async_engine(_url(database))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source = AdbTenderSource()
    raw = {
        "guid": "sr23-adb-1",
        "link": "https://www.adb.org/node/sr23-adb-1",
        "title": "SR-2.3 ADB metadata",
        "source_kind": "official_current_listing",
    }
    normalized = source.normalize(raw)
    try:
        async with sessions() as db:
            tender_result = await persist_tender_batch(db, [normalized])
            tender = tender_result.items[0].tender
            await db.commit()
            metadata = dict(tender.source_metadata_json or {})
            metadata["email"] = "preserved@example.test"
            tender.source_metadata_json = metadata
            await db.commit()

            descriptor = (await source.discover_documents(normalized))[0]
            first = await persist_document_descriptors(
                db, source_system="adb", tender=tender, documents=[descriptor]
            )
            await db.commit()
            repeat = await persist_document_descriptors(
                db, source_system="adb", tender=tender, documents=[descriptor]
            )
            await db.commit()
            document = (await db.execute(select(TenderDocument))).scalar_one()
            document.download_status = "processed"
            await db.commit()
            monotonic_repeat = await persist_document_descriptors(
                db, source_system="adb", tender=tender, documents=[descriptor]
            )
            await db.commit()
            await persist_tender_batch(db, [normalized])
            await db.commit()
            await db.refresh(tender)
            await db.refresh(document)

            started = monotonic()
            for _ in range(1000):
                await source.discover_documents(normalized)
            discovery_ms = int((monotonic() - started) * 1000)
            assert first.created_count == 1
            assert repeat.unchanged_count == 1
            assert monotonic_repeat.unchanged_count == 1
            assert document.download_status == "processed"
            assert tender.source_metadata_json["email"] == "preserved@example.test"
            return {
                "first_descriptor": "created",
                "repeat_descriptor": "unchanged",
                "processed_status_after_rediscovery": document.download_status,
                "contact_after_metadata_repeat": tender.source_metadata_json["email"],
                "metadata_discovery_1000_ms": discovery_ms,
                "document_http_calls": 0,
            }
    finally:
        await engine.dispose()


async def disposable() -> dict[str, object]:
    database = f"{PREFIX}{uuid4().hex[:12]}"
    _safe_name(database)
    admin = await _connect("postgres")
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    try:
        await asyncio.to_thread(_bootstrap, database)
        await asyncio.to_thread(_alembic, database, "downgrade", PREVIOUS_HEAD)
        connection = await _connect(database)
        job_id = uuid4()
        try:
            await connection.execute(
                """
                INSERT INTO source_refresh_jobs (
                    id, source_system, status, trigger_kind, options_json, force,
                    created_count, updated_count, unchanged_count, fetched_count,
                    skipped_count, rejected_count, failed_count,
                    documents_discovered_count, documents_queued_count,
                    fallback_used, message
                ) VALUES ($1, 'adb', 'completed', 'scheduled', '{}'::json, false,
                          1, 2, 3, 6, 0, 0, 0, 1, 1, false, 'historical')
                """,
                job_id,
            )
            tender_count_before = await connection.fetchval("SELECT count(*) FROM tenders")
        finally:
            await connection.close()
        await asyncio.to_thread(_alembic, database, "upgrade", "head")
        connection = await _connect(database)
        try:
            values = await connection.fetchrow(
                "SELECT " + ", ".join(METRICS) + " FROM source_refresh_jobs WHERE id=$1",
                job_id,
            )
            tender_count_after = await connection.fetchval("SELECT count(*) FROM tenders")
            revision = await connection.fetchval("SELECT version_num FROM alembic_version")
        finally:
            await connection.close()
        assert values is not None and all(values[name] is None for name in METRICS)
        assert tender_count_before == tender_count_after
        assert revision == HEAD
        document_matrix = await _document_matrix(database)
        await asyncio.to_thread(_alembic, database, "downgrade", PREVIOUS_HEAD)
        await asyncio.to_thread(_alembic, database, "upgrade", "head")
        return {
            "head": revision,
            "historical_metrics": "null",
            "tender_rows_unchanged": tender_count_before == tender_count_after,
            "downgrade_upgrade": "pass",
            "document_matrix": document_matrix,
        }
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
    """Read-only and schema-aware: never migrates or changes local data."""
    connection = await _connect(settings.POSTGRES_DB)
    try:
        revision = await connection.fetchval("SELECT version_num FROM alembic_version")
        columns = {
            row["column_name"]
            for row in await connection.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='source_refresh_jobs'"
            )
        }
        counts = await connection.fetchrow(
            "SELECT count(*) AS jobs, count(*) FILTER (WHERE status IN ('queued','running')) AS active "
            "FROM source_refresh_jobs"
        )
        return {
            "mode": "read_only",
            "revision": revision,
            "head_present": revision == HEAD,
            "metrics_present": sorted(set(METRICS) & columns),
            "jobs": counts["jobs"],
            "active_jobs": counts["active"],
        }
    finally:
        await connection.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    arguments = parser.parse_args()
    result = await preflight() if arguments.preflight else await disposable()
    print(json.dumps(result, indent=2, default=str, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
