#!/usr/bin/env python3
"""Disposable PostgreSQL correctness and performance proof for SR-2.1."""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import resource
import subprocess
import sys
from time import perf_counter
from typing import Any, Iterator
from uuid import uuid4

import asyncpg
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.models.all_models import Tender
from app.services.tender_sources.base import NormalizedTender, persist_tender_batch
from scripts import bootstrap_database as bootstrap


HEAD = "20260902_0001_s7_2_user_ui_locale"
PREFIX = "plasma_sr21_"
DEFAULT_BATCH_SIZE = 500
DOMAIN_TABLES = (
    "tender_engagements",
    "proposals",
    "tender_analyses",
    "analysis_versions",
    "tender_recommendations",
    "company_profiles",
)


@dataclass
class Measurement:
    rows: int
    batch_size: int
    created: int
    updated: int
    unchanged: int
    duplicate: int
    select: int
    insert: int
    update: int
    delete: int
    wall_seconds: float
    peak_mib: float


def _database_name() -> str:
    return f"{PREFIX}{uuid4().hex[:12]}"


def _assert_disposable(database: str) -> None:
    if not re.fullmatch(r"plasma_sr21_[a-f0-9]{12}", database):
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


def _alembic_environment(database: str) -> dict[str, str]:
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


def _alembic(database: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=_alembic_environment(database),
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
        env=_alembic_environment(database),
        text=True,
        capture_output=True,
        check=False,
    )


def _normalized(
    prefix: str,
    index: int,
    *,
    source: str = "uzex",
    changed: bool = False,
    reverse_metadata: bool = False,
) -> NormalizedTender:
    metadata_items = [
        {"kind": "notice", "value": index},
        {"kind": "tag", "value": index % 7},
    ]
    if reverse_metadata:
        metadata_items.reverse()
    return NormalizedTender(
        source_system=source,
        external_id=f"{prefix}-{index:06d}",
        source_url=f"https://example.test/{source}/{prefix}/{index}",
        title=f"{prefix} tender {index}" + (" changed" if changed else ""),
        description=f"Stable source description {index}",
        budget=float(index + 100),
        currency="USD",
        country="Uzbekistan",
        region="Tashkent",
        sector="Infrastructure",
        buyer="Benchmark Buyer",
        procurement_category="Works",
        procurement_method="Open",
        notice_type="Invitation",
        project_id=f"P{index:06d}",
        publication_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
        deadline=datetime(2026, 12, 1, tzinfo=timezone.utc),
        category="Other",
        source_metadata_json={"facts": metadata_items, "index": index},
        scrape_status="success",
    )


@contextmanager
def _statement_counter(engine: AsyncEngine) -> Iterator[Counter[str]]:
    counts: Counter[str] = Counter()

    def before_cursor_execute(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        lowered = statement.lstrip().lower()
        if "tenders" not in lowered:
            return
        for operation in ("select", "insert", "update", "delete"):
            if lowered.startswith(operation):
                counts[operation] += 1
                break

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield counts
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)


async def _measure(
    engine: AsyncEngine,
    payloads: list[NormalizedTender],
    *,
    batch_size: int,
) -> Measurement:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    started = perf_counter()
    with _statement_counter(engine) as statements:
        async with session_factory() as session:
            result = await persist_tender_batch(
                session,
                payloads,
                batch_size=batch_size,
            )
            await session.commit()
    wall_seconds = perf_counter() - started
    # Linux reports ru_maxrss in KiB. This is a low-overhead process high-water
    # estimate; tracemalloc materially distorts the 10k timing being measured.
    process_peak_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return Measurement(
        rows=len(payloads),
        batch_size=batch_size,
        created=result.created_count,
        updated=result.updated_count,
        unchanged=result.unchanged_count,
        duplicate=result.duplicate_count,
        select=statements["select"],
        insert=statements["insert"],
        update=statements["update"],
        delete=statements["delete"],
        wall_seconds=round(wall_seconds, 3),
        peak_mib=round(process_peak_mib, 2),
    )


async def _domain_counts(engine: AsyncEngine) -> dict[str, int]:
    session_factory = async_sessionmaker(engine)
    async with session_factory() as session:
        return {
            table: int((await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())
            for table in DOMAIN_TABLES
        }


async def _correctness_matrix(engine: AsyncEngine) -> dict[str, Any]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    payload = _normalized("correctness", 1)
    async with session_factory() as session:
        first = await persist_tender_batch(session, [payload])
        await session.commit()
        tender_id = first.items[0].tender.id
        created_at = first.items[0].tender.created_at
        last_synced_at = first.items[0].tender.last_synced_at

    semantically_identical = _normalized(
        "correctness",
        1,
        reverse_metadata=True,
    )
    async with session_factory() as session:
        repeat = await persist_tender_batch(session, [semantically_identical])
        await session.commit()
        assert repeat.items[0].tender.id == tender_id
        assert repeat.items[0].tender.created_at == created_at
        assert repeat.items[0].tender.last_synced_at == last_synced_at

    async with session_factory() as session:
        changed = await persist_tender_batch(
            session,
            [_normalized("correctness", 1, changed=True)],
        )
        await session.commit()
        assert changed.items[0].tender.id == tender_id
        assert changed.items[0].tender.created_at == created_at

    duplicate_payloads = [
        _normalized("duplicate", 1),
        _normalized("duplicate", 1, changed=True),
    ]
    async with session_factory() as session:
        duplicate = await persist_tender_batch(session, duplicate_payloads)
        await session.commit()
        assert duplicate.created_count == 1
        assert duplicate.duplicate_count == 1
        assert duplicate.items[0].tender.title.endswith(" changed")

    async with session_factory() as session:
        cross_source = await persist_tender_batch(
            session,
            [
                _normalized("cross", 123, source="giz"),
                _normalized("cross", 123, source="adb"),
            ],
        )
        await session.commit()
        assert cross_source.created_count == 2
        assert len({item.tender.id for item in cross_source.items}) == 2

    legacy_external_id = "legacy-pair-1"
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO tenders "
                "(id, external_id, source_system, canonical_source_key, source_url, "
                "title, budget, currency, status, category) VALUES "
                "(:id, :external_id, 'uzex', :legacy_key, :source_url, :title, "
                "0, 'USD', 'OPEN', 'Other')"
            ),
            {
                "id": uuid4(),
                "external_id": legacy_external_id,
                "legacy_key": "uzex:legacy-pair-placeholder",
                "source_url": "https://example.test/legacy",
                "title": "Legacy",
            },
        )
        await session.commit()
    legacy_payload = NormalizedTender(
        source_system="uzex",
        external_id=legacy_external_id,
        source_url="https://example.test/legacy",
        title="Legacy normalized",
        currency="USD",
    )
    async with session_factory() as session:
        legacy = await persist_tender_batch(session, [legacy_payload])
        await session.commit()
        assert legacy.updated_count == 1
        assert legacy.items[0].tender.canonical_source_key == f"uzex:{legacy_external_id}"

    rollback_prefix = "forced-rollback"
    async with session_factory() as session:
        provisional = await persist_tender_batch(
            session,
            [_normalized(rollback_prefix, 1)],
        )
        assert provisional.created_count == 1
        await session.rollback()
    async with session_factory() as session:
        durable = int(
            (
                await session.execute(
                    select(func.count(Tender.id)).where(
                        Tender.canonical_source_key == f"uzex:{rollback_prefix}-000001"
                    )
                )
            ).scalar_one()
        )
        assert durable == 0

    try:
        NormalizedTender(
            source_system="uzex",
            external_id="",
            source_url="https://example.test/malformed",
            title="Malformed",
        ).canonical_source_key
    except ValueError:
        malformed_rejected = True
    else:
        raise AssertionError("malformed canonical identity was accepted")

    return {
        "same_source": [first.created_count, repeat.unchanged_count, changed.updated_count],
        "created_at_immutable": True,
        "last_synced_unchanged": True,
        "duplicate": {"created": duplicate.created_count, "duplicate": duplicate.duplicate_count},
        "cross_source_rows": cross_source.created_count,
        "legacy_pair_fallback": legacy.updated_count,
        "rollback_durable_rows": durable,
        "malformed_rejected": malformed_rejected,
    }


async def _concurrency_matrix(engine: AsyncEngine) -> dict[str, Any]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    payloads = [_normalized("concurrent", index) for index in range(100)]
    pids: list[int] = []
    pids_ready = asyncio.Event()
    pids_lock = asyncio.Lock()

    async def contender() -> tuple[int, int, int]:
        async with session_factory() as session:
            pid = int((await session.execute(text("SELECT pg_backend_pid()"))).scalar_one())
            async with pids_lock:
                pids.append(pid)
                if len(pids) == 2:
                    pids_ready.set()
            result = await persist_tender_batch(session, payloads, batch_size=100)
            await session.commit()
            return result.created_count, result.updated_count, result.unchanged_count

    # A SHARE table lock allows both initial identity SELECTs but blocks both
    # ROW EXCLUSIVE INSERT locks. Releasing it only after both contenders are
    # waiting guarantees a real absent-at-lookup insert race.
    async with session_factory() as gate_session:
        await gate_session.execute(text("LOCK TABLE tenders IN SHARE MODE"))
        tasks = [asyncio.create_task(contender()), asyncio.create_task(contender())]
        await asyncio.wait_for(pids_ready.wait(), timeout=5)
        for _attempt in range(100):
            waiting = int(
                (
                    await gate_session.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE pid = ANY(CAST(:pids AS integer[])) "
                            "AND wait_event_type = 'Lock'"
                        ),
                        {"pids": pids},
                    )
                ).scalar_one()
            )
            if waiting == 2:
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("both concurrent insert contenders did not reach lock wait")
        await gate_session.commit()
        results = await asyncio.gather(*tasks)
    async with session_factory() as session:
        durable_rows = int(
            (
                await session.execute(
                    select(func.count(Tender.id)).where(
                        Tender.canonical_source_key.like("uzex:concurrent-%")
                    )
                )
            ).scalar_one()
        )
    assert durable_rows == 100
    assert sum(result[0] for result in results) == 100
    return {
        "both_absent_insert_contenders_waited": True,
        "run_results": results,
        "durable_rows": durable_rows,
        "created_sum": sum(result[0] for result in results),
    }


async def _benchmark_matrix(engine: AsyncEngine) -> dict[str, Any]:
    sizes: dict[str, dict[str, Any]] = {}
    for size in (100, 1_000, 10_000):
        payloads = [_normalized(f"size-{size}", index) for index in range(size)]
        first = await _measure(engine, payloads, batch_size=DEFAULT_BATCH_SIZE)
        repeat = await _measure(
            engine,
            [
                _normalized(f"size-{size}", index, reverse_metadata=True)
                for index in range(size)
            ],
            batch_size=DEFAULT_BATCH_SIZE,
        )
        assert (first.created, first.updated, first.unchanged) == (size, 0, 0)
        assert (repeat.created, repeat.updated, repeat.unchanged) == (0, 0, size)
        assert repeat.insert == repeat.update == repeat.delete == 0
        sizes[str(size)] = {"first": asdict(first), "repeat": asdict(repeat)}

    batch_sizes: dict[str, Any] = {}
    ten_thousand_repeat = [
        _normalized("size-10000", index, reverse_metadata=True)
        for index in range(10_000)
    ]
    for batch_size in (100, 250, 500, 1_000):
        measurement = await _measure(
            engine,
            ten_thousand_repeat,
            batch_size=batch_size,
        )
        assert measurement.unchanged == 10_000
        assert measurement.update == 0
        batch_sizes[str(batch_size)] = asdict(measurement)

    mixed_seed = [_normalized("mixed", index) for index in range(6_000)]
    await _measure(engine, mixed_seed, batch_size=DEFAULT_BATCH_SIZE)
    mixed_payloads = [
        _normalized("mixed", index, changed=4_000 <= index < 6_000)
        for index in range(10_000)
    ]
    mixed = await _measure(engine, mixed_payloads, batch_size=DEFAULT_BATCH_SIZE)
    assert (mixed.created, mixed.updated, mixed.unchanged) == (4_000, 2_000, 4_000)

    sr1_first_seconds = 30.363
    sr1_repeat_seconds = 20.818
    first_10k = sizes["10000"]["first"]["wall_seconds"]
    repeat_10k = sizes["10000"]["repeat"]["wall_seconds"]
    improvement = {
        "first_percent": round((sr1_first_seconds - first_10k) / sr1_first_seconds * 100, 2),
        "repeat_percent": round((sr1_repeat_seconds - repeat_10k) / sr1_repeat_seconds * 100, 2),
    }
    return {
        "sizes": sizes,
        "batch_sizes": batch_sizes,
        "selected_default": DEFAULT_BATCH_SIZE,
        "mixed": asdict(mixed),
        "versus_sr1_percent_improvement": improvement,
    }


async def _schema_result(database: str) -> dict[str, Any]:
    current = await asyncio.to_thread(_alembic, database, "current")
    heads = await asyncio.to_thread(_alembic, database, "heads")
    check = await asyncio.to_thread(_alembic, database, "check")
    diagnostic = check.stdout + check.stderr
    assert current.returncode == heads.returncode == check.returncode == 0, diagnostic[-4000:]
    assert HEAD in current.stdout and HEAD in heads.stdout
    assert "No new upgrade operations detected" in diagnostic
    return {"head": HEAD, "alembic_check": "clean"}


async def main() -> int:
    database = _database_name()
    await _create_database(database)
    engine: AsyncEngine | None = None
    try:
        bootstrap_result = await asyncio.to_thread(_bootstrap, database)
        if bootstrap_result.returncode:
            raise RuntimeError(
                (bootstrap_result.stderr or bootstrap_result.stdout)[-5000:]
            )
        schema = await _schema_result(database)
        engine = create_async_engine(_url(database), pool_size=5, max_overflow=5)
        before_domains = await _domain_counts(engine)
        correctness = await _correctness_matrix(engine)
        concurrency = await _concurrency_matrix(engine)
        benchmarks = await _benchmark_matrix(engine)
        after_domains = await _domain_counts(engine)
        assert before_domains == after_domains
        print(
            json.dumps(
                {
                    "status": "passed",
                    "schema": schema,
                    "correctness": correctness,
                    "concurrency": concurrency,
                    "benchmarks": benchmarks,
                    "domain_write_fingerprint": {
                        "before": before_domains,
                        "after": after_domains,
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(database)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
