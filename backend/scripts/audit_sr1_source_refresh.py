#!/usr/bin/env python3
"""SR-1 count-only preflight and disposable PostgreSQL ingest benchmark.

This script does not call external procurement sources. ``preflight`` opens the
configured database in a read-only transaction. ``benchmark`` creates a uniquely
named disposable database, migrates it to the repository head, exercises the
real shared Tender upsert helper, and removes the database in ``finally``.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import monotonic
from typing import Any

from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models  # noqa: E402,F401 - load the complete ORM registry
from app.core.config import settings  # noqa: E402
from app.models.all_models import SourceRefreshJob, Tender, TenderStatus  # noqa: E402
from app.services.tender_sources.base import NormalizedTender, upsert_tender  # noqa: E402
from scripts import test_s0_5b4_baseline as disposable  # noqa: E402


DOMAIN_TABLES = (
    "tenders",
    "tender_documents",
    "projects",
    "tender_projects",
    "tender_recommendations",
    "tender_engagements",
    "proposals",
    "tender_analyses",
    "analysis_versions",
)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


async def _table_counts(connection: Any) -> dict[str, int]:
    existing = {
        row[0]
        for row in (
            await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        ).all()
    }
    counts: dict[str, int] = {}
    for table_name in DOMAIN_TABLES:
        counts[table_name] = (
            int(
                (
                    await connection.execute(
                        text(f'SELECT count(*) FROM "{table_name}"')
                    )
                ).scalar_one()
            )
            if table_name in existing
            else 0
        )
    return counts


async def configured_preflight() -> dict[str, Any]:
    engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                sources = [
                    dict(row._mapping)
                    for row in (
                        await connection.execute(
                            text(
                                """
                                SELECT source_system, count(*) AS tender_count,
                                       min(created_at) AS min_created_at,
                                       max(created_at) AS max_created_at,
                                       min(last_synced_at) AS min_last_synced_at,
                                       max(last_synced_at) AS max_last_synced_at
                                FROM tenders
                                GROUP BY source_system
                                ORDER BY source_system
                                """
                            )
                        )
                    ).all()
                ]
                documents = [
                    dict(row._mapping)
                    for row in (
                        await connection.execute(
                            text(
                                """
                                SELECT t.source_system, count(d.id) AS document_count
                                FROM tenders t
                                LEFT JOIN tender_documents d ON d.tender_id = t.id
                                GROUP BY t.source_system
                                ORDER BY t.source_system
                                """
                            )
                        )
                    ).all()
                ]
                jobs = [
                    dict(row._mapping)
                    for row in (
                        await connection.execute(
                            text(
                                """
                                SELECT source_system, status, count(*) AS job_count
                                FROM source_refresh_jobs
                                GROUP BY source_system, status
                                ORDER BY source_system, status
                                """
                            )
                        )
                    ).all()
                ]
                scalar_queries = {
                    "missing_canonical_identity": """
                        SELECT count(*) FROM tenders
                        WHERE source_system IS NULL OR btrim(source_system) = ''
                           OR external_id IS NULL OR btrim(external_id) = ''
                           OR canonical_source_key IS NULL OR btrim(canonical_source_key) = ''
                    """,
                    "duplicate_source_external_groups": """
                        SELECT count(*) FROM (
                          SELECT 1 FROM tenders GROUP BY source_system, external_id
                          HAVING count(*) > 1
                        ) duplicates
                    """,
                    "duplicate_canonical_key_groups": """
                        SELECT count(*) FROM (
                          SELECT 1 FROM tenders GROUP BY canonical_source_key
                          HAVING count(*) > 1
                        ) duplicates
                    """,
                    "stale_active_refresh_jobs_30m": """
                        SELECT count(*) FROM source_refresh_jobs
                        WHERE status IN ('queued', 'running')
                          AND updated_at < now() - interval '30 minutes'
                    """,
                    "successful_refresh_jobs_7d": """
                        SELECT count(*) FROM source_refresh_jobs
                        WHERE status = 'completed'
                          AND completed_at >= now() - interval '7 days'
                    """,
                    "failed_refresh_jobs_7d": """
                        SELECT count(*) FROM source_refresh_jobs
                        WHERE status IN ('failed', 'source_unavailable')
                          AND completed_at >= now() - interval '7 days'
                    """,
                }
                scalar_counts = {
                    name: int((await connection.execute(text(sql))).scalar_one())
                    for name, sql in scalar_queries.items()
                }
                revision = (
                    await connection.execute(text("SELECT version_num FROM alembic_version"))
                ).scalar_one_or_none()
                return {
                    "mode": "configured_read_only",
                    "database": settings.POSTGRES_DB,
                    "tenders_by_source": sources,
                    "documents_by_source": documents,
                    "refresh_jobs_by_source_status": jobs,
                    **scalar_counts,
                    "domain_counts": await _table_counts(connection),
                    "alembic_revision": revision,
                    "transaction_rolled_back": True,
                }
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


def _normalized(source: str, index: int) -> NormalizedTender:
    external_id = f"sr1-{index:08d}"
    return NormalizedTender(
        source_system=source,
        external_id=external_id,
        source_url=f"https://example.invalid/{source}/{external_id}",
        title=f"SR-1 synthetic tender {index}",
        description="Stable synthetic metadata for the SR-1 DB-only benchmark.",
        budget=1000.0 + index,
        currency="USD",
        country="Uzbekistan",
        region="Central Asia",
        sector="Consulting services",
        buyer="SR-1 synthetic buyer",
        procurement_category="Consulting",
        procurement_method="Open competition",
        notice_type="Invitation for bids",
        project_id=None,
        publication_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
        deadline=datetime(2026, 12, 1, tzinfo=timezone.utc),
        status=TenderStatus.OPEN,
        category="Other",
        source_metadata_json={"fixture": "sr1", "version": 1},
        scrape_status="success",
    )


class SqlCounter:
    def __init__(self, sync_engine: Any) -> None:
        self.counts: Counter[str] = Counter()

        @event.listens_for(sync_engine, "before_cursor_execute")
        def count_statement(
            _connection: Any,
            _cursor: Any,
            statement: str,
            _parameters: Any,
            _context: Any,
            _executemany: bool,
        ) -> None:
            token = statement.lstrip().split(None, 1)[0].upper()
            self.counts[token if token in {"SELECT", "INSERT", "UPDATE", "DELETE"} else "OTHER"] += 1

    def reset(self) -> None:
        self.counts.clear()

    def snapshot(self) -> dict[str, int]:
        return {
            "select": self.counts["SELECT"],
            "insert": self.counts["INSERT"],
            "update": self.counts["UPDATE"],
            "delete": self.counts["DELETE"],
            "other": self.counts["OTHER"],
        }


async def _ingest(
    session_factory: Any,
    *,
    source: str,
    size: int,
) -> dict[str, Any]:
    started = monotonic()
    created = 0
    updated = 0
    async with session_factory() as session:
        for index in range(size):
            _tender, was_created = await upsert_tender(
                session,
                _normalized(source, index),
            )
            # Mirrors the World Bank/GIZ/ADB/EBRD endpoint path.
            await session.flush()
            created += int(was_created)
            updated += int(not was_created)
        await session.commit()
    return {
        "wall_seconds": round(monotonic() - started, 6),
        "rows_created": created,
        "rows_updated": updated,
        "rows_unchanged": 0,
        "transaction_commits": 1,
    }


async def _timestamps(session_factory: Any) -> dict[str, Any]:
    async with session_factory() as session:
        row = (
            await session.execute(
                select(
                    func.count(Tender.id),
                    func.min(Tender.created_at),
                    func.max(Tender.created_at),
                    func.min(Tender.last_synced_at),
                    func.max(Tender.last_synced_at),
                )
            )
        ).one()
        return {
            "tender_count": int(row[0]),
            "min_created_at": row[1],
            "max_created_at": row[2],
            "min_last_synced_at": row[3],
            "max_last_synced_at": row[4],
        }


async def _domain_counts(session_factory: Any) -> dict[str, int]:
    async with session_factory() as session:
        return await _table_counts(session)


async def _truncate(session_factory: Any) -> None:
    async with session_factory() as session:
        await session.execute(text("TRUNCATE TABLE tenders CASCADE"))
        await session.execute(text("TRUNCATE TABLE source_refresh_jobs CASCADE"))
        await session.commit()


async def _commit_result(session: Any) -> str:
    try:
        await session.commit()
        return "committed"
    except IntegrityError:
        await session.rollback()
        return "integrity_error"


async def _tender_concurrency(session_factory: Any, *, same_source: bool) -> dict[str, Any]:
    first = session_factory()
    second = session_factory()
    try:
        source_a = "giz"
        source_b = "giz" if same_source else "adb"
        first_row, first_created = await upsert_tender(first, _normalized(source_a, 999_999))
        second_row, second_created = await upsert_tender(second, _normalized(source_b, 999_999))
        outcomes = await asyncio.gather(_commit_result(first), _commit_result(second))
        async with session_factory() as verifier:
            count = int(
                (
                    await verifier.execute(
                        select(func.count(Tender.id)).where(
                            Tender.external_id == "sr1-00999999"
                        )
                    )
                ).scalar_one()
            )
        return {
            "optimistic_created_flags": [first_created, second_created],
            "commit_outcomes": sorted(outcomes),
            "persisted_tenders": count,
            "first_ids_differ": first_row.id != second_row.id,
        }
    finally:
        await first.close()
        await second.close()


async def _job_concurrency(session_factory: Any, *, same_source: bool) -> dict[str, Any]:
    first = session_factory()
    second = session_factory()
    try:
        first.add(SourceRefreshJob(source_system="giz", status="queued", force=False))
        second.add(
            SourceRefreshJob(
                source_system="giz" if same_source else "adb",
                status="queued",
                force=False,
            )
        )
        outcomes = await asyncio.gather(_commit_result(first), _commit_result(second))
        async with session_factory() as verifier:
            count = int(
                (
                    await verifier.execute(
                        select(func.count(SourceRefreshJob.id)).where(
                            SourceRefreshJob.status == "queued"
                        )
                    )
                ).scalar_one()
            )
        return {"commit_outcomes": sorted(outcomes), "persisted_active_jobs": count}
    finally:
        await first.close()
        await second.close()


async def disposable_benchmark() -> dict[str, Any]:
    database = disposable.database_name("sr1_refresh_audit")
    await disposable.create_database(database)
    try:
        # Plasma's supported empty-database path is the immutable S0.4c
        # baseline plus its verified forward migrations, not ``alembic upgrade
        # head`` from an object-free database.
        migration = await asyncio.to_thread(disposable.run_bootstrap, database)
        if migration.returncode:
            raise RuntimeError((migration.stderr or migration.stdout)[-4000:])
        engine = create_async_engine(disposable.target_url(database), poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        sql_counter = SqlCounter(engine.sync_engine)
        matrix: list[dict[str, Any]] = []
        try:
            for size in (100, 1_000, 10_000):
                await _truncate(session_factory)
                sql_counter.reset()
                first = await _ingest(session_factory, source="giz", size=size)
                first_sql = sql_counter.snapshot()
                first_fingerprint = await _domain_counts(session_factory)
                first_timestamps = await _timestamps(session_factory)

                sql_counter.reset()
                repeat = await _ingest(session_factory, source="giz", size=size)
                repeat_sql = sql_counter.snapshot()
                repeat_fingerprint = await _domain_counts(session_factory)
                repeat_timestamps = await _timestamps(session_factory)
                matrix.append(
                    {
                        "source_path": "shared upsert_tender + per-row flush",
                        "dataset_size": size,
                        "first_ingest": {**first, "sql": first_sql},
                        "identical_reingest": {**repeat, "sql": repeat_sql},
                        "first_fingerprint": first_fingerprint,
                        "repeat_fingerprint": repeat_fingerprint,
                        "created_at_preserved": (
                            first_timestamps["min_created_at"] == repeat_timestamps["min_created_at"]
                            and first_timestamps["max_created_at"] == repeat_timestamps["max_created_at"]
                        ),
                        "last_synced_at_rewritten": (
                            first_timestamps["max_last_synced_at"]
                            != repeat_timestamps["max_last_synced_at"]
                        ),
                        "document_jobs_dispatched": 0,
                        "errors": 0,
                    }
                )

            await _truncate(session_factory)
            same_tender = await _tender_concurrency(session_factory, same_source=True)
            await _truncate(session_factory)
            cross_tender = await _tender_concurrency(session_factory, same_source=False)
            await _truncate(session_factory)
            same_job = await _job_concurrency(session_factory, same_source=True)
            await _truncate(session_factory)
            cross_job = await _job_concurrency(session_factory, same_source=False)
        finally:
            await engine.dispose()
        return {
            "mode": "disposable_postgresql",
            "database_prefix": "plasma_s05b4b_sr1_refresh_audit_",
            "schema_bootstrap_returncode": migration.returncode,
            "matrix": matrix,
            "concurrency": {
                "same_source_same_tender": same_tender,
                "different_source_same_external_id": cross_tender,
                "same_source_active_jobs": same_job,
                "different_source_active_jobs": cross_job,
            },
            "database_dropped": True,
        }
    finally:
        await disposable.drop_database(database)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "benchmark", "all"))
    arguments = parser.parse_args()
    result: dict[str, Any] = {}
    if arguments.mode in {"preflight", "all"}:
        result["preflight"] = await configured_preflight()
    if arguments.mode in {"benchmark", "all"}:
        result["benchmark"] = await disposable_benchmark()
    print(json.dumps(result, indent=2, default=_json_default, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
