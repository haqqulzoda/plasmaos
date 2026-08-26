#!/usr/bin/env python3
"""Disposable PostgreSQL scenarios for the S0.5B.3 reconciliation migration.

The script never connects to production implicitly. It derives a local/admin
connection from the configured development database, creates uniquely named
disposable databases, and removes each database in ``finally`` blocks.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
import app.models.all_models  # noqa: F401  # Load circular model registry first.
from app.models.all_models import Base
from app.models.audit import TenderRecommendation


PREVIOUS_HEAD = "20260824_0002_s0_4c"
EXPECTED_HEAD = "20260826_0002_s1_2_wb_project_enrichment"
DATABASE_PREFIX = "plasma_s05b3_"
BOOTSTRAP_CONFIRMATION = "BOOTSTRAP_EMPTY_DATABASE"


def _database_name(label: str) -> str:
    safe_label = re.sub(r"[^a-z0-9_]", "_", label.casefold())
    return f"{DATABASE_PREFIX}{safe_label}_{uuid4().hex[:10]}"


def _assert_disposable_name(database: str) -> None:
    if not re.fullmatch(r"plasma_s05b3_[a-z0-9_]+", database):
        raise RuntimeError(f"refusing unsafe disposable database name: {database!r}")


async def _admin_connection() -> asyncpg.Connection:
    return await asyncpg.connect(
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        database="postgres",
    )


async def _database_connection(database: str) -> asyncpg.Connection:
    _assert_disposable_name(database)
    return await asyncpg.connect(
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        database=database,
    )


async def _create_database(database: str) -> None:
    _assert_disposable_name(database)
    connection = await _admin_connection()
    try:
        if await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            database,
        ):
            raise RuntimeError(f"refusing to overwrite existing database {database}")
        await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()


async def _drop_database(database: str) -> None:
    _assert_disposable_name(database)
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


def _alembic(database: str, *arguments: str, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
    _assert_disposable_name(database)
    environment = os.environ.copy()
    environment["POSTGRES_DB"] = database
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if expect_success and result.returncode != 0:
        diagnostic = "\n".join((result.stderr or result.stdout).splitlines()[-20:])
        raise RuntimeError(
            f"Alembic {' '.join(arguments)} failed for disposable database: {diagnostic}"
        )
    return result


def _bootstrap(database: str) -> subprocess.CompletedProcess[str]:
    """Run the supported immutable-baseline path for the literal fresh case."""
    _assert_disposable_name(database)
    environment = os.environ.copy()
    environment["PLASMA_BOOTSTRAP_DATABASE_URL"] = (
        f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{database}"
    )
    environment["AUTO_CREATE_TABLES"] = "false"
    return subprocess.run(
        [
            sys.executable,
            "scripts/bootstrap_database.py",
            "--confirm",
            BOOTSTRAP_CONFIRMATION,
        ],
        cwd=BACKEND_DIR,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


async def _create_parent_stubs(database: str) -> None:
    connection = await _database_connection(database)
    try:
        await connection.execute("CREATE TABLE tenders (id UUID PRIMARY KEY)")
        await connection.execute("CREATE TABLE company_profiles (id UUID PRIMARY KEY)")
    finally:
        await connection.close()


async def _create_recommendation_from_orm(database: str) -> None:
    database_uri = settings.SQLALCHEMY_DATABASE_URI.rsplit("/", 1)[0] + f"/{database}"
    engine = create_async_engine(database_uri)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(TenderRecommendation.__table__.create)
    finally:
        await engine.dispose()


async def _create_full_orm_schema(database: str) -> None:
    database_uri = settings.SQLALCHEMY_DATABASE_URI.rsplit("/", 1)[0] + f"/{database}"
    engine = create_async_engine(database_uri)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


async def _stamp_previous_head(database: str) -> None:
    await asyncio.to_thread(_alembic, database, "stamp", PREVIOUS_HEAD)


async def _schema_snapshot(connection: asyncpg.Connection) -> dict[str, Any]:
    columns = await connection.fetch(
        """
        SELECT column_name, data_type, udt_name, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'tender_recommendations'
        ORDER BY ordinal_position
        """
    )
    constraints = await connection.fetch(
        """
        SELECT conname, contype, pg_get_constraintdef(oid) AS definition
        FROM pg_constraint
        WHERE conrelid = 'tender_recommendations'::regclass
        ORDER BY conname
        """
    )
    indexes = await connection.fetch(
        """
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = current_schema() AND tablename = 'tender_recommendations'
        ORDER BY indexname
        """
    )
    return {
        "columns": [dict(row) for row in columns],
        "constraints": [dict(row) for row in constraints],
        "indexes": [dict(row) for row in indexes],
    }


def _assert_canonical_schema(snapshot: dict[str, Any]) -> None:
    columns = {column["column_name"]: column for column in snapshot["columns"]}
    expected_columns = {
        "id",
        "tender_id",
        "company_profile_id",
        "match_score",
        "strategic_rationale",
        "is_dismissed",
        "created_at",
    }
    if set(columns) != expected_columns:
        raise AssertionError(f"unexpected columns: {set(columns)}")
    if any(columns[name]["is_nullable"] != "NO" for name in expected_columns):
        raise AssertionError("canonical recommendation columns must be non-null")

    constraints = {
        constraint["conname"]: constraint["definition"]
        for constraint in snapshot["constraints"]
    }
    required_constraint_fragments = {
        "tender_recommendations_pkey": "PRIMARY KEY (id)",
        "tender_recommendations_tender_id_fkey": "FOREIGN KEY (tender_id)",
        "tender_recommendations_company_profile_id_fkey": "FOREIGN KEY (company_profile_id)",
        "uq_tender_recommendations_tender_profile": "UNIQUE (tender_id, company_profile_id)",
        "ck_tender_recommendations_match_score_range": "match_score >= 0",
    }
    for name, fragment in required_constraint_fragments.items():
        if fragment not in constraints.get(name, ""):
            raise AssertionError(f"missing or incompatible constraint {name}")
    for foreign_key in (
        "tender_recommendations_tender_id_fkey",
        "tender_recommendations_company_profile_id_fkey",
    ):
        if "ON DELETE CASCADE" not in constraints[foreign_key]:
            raise AssertionError(f"{foreign_key} must use ON DELETE CASCADE")

    indexes = {index["indexname"] for index in snapshot["indexes"]}
    required_indexes = {
        "ix_tender_recommendations_tender_id",
        "ix_tender_recommendations_company_profile_id",
        "ix_tender_recommendations_created_at",
    }
    if not required_indexes.issubset(indexes):
        raise AssertionError(f"missing canonical indexes: {required_indexes - indexes}")


async def _with_database(
    label: str,
    scenario: Callable[[str], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    database = _database_name(label)
    await _create_database(database)
    try:
        result = await scenario(database)
        return {"scenario": label, "status": "passed", **result}
    finally:
        await _drop_database(database)


async def _fresh_database_scenario(database: str) -> dict[str, Any]:
    result = await asyncio.to_thread(_bootstrap, database)
    if result.returncode != 0:
        diagnostic = "\n".join((result.stderr or result.stdout).splitlines()[-8:])
        raise AssertionError(
            "fresh immutable-baseline bootstrap failed before reconciliation migration: "
            f"{diagnostic}"
        )
    connection = await _database_connection(database)
    try:
        snapshot = await _schema_snapshot(connection)
        _assert_canonical_schema(snapshot)
    finally:
        await connection.close()
    return {"head": EXPECTED_HEAD}


async def _missing_table_scenario(database: str) -> dict[str, Any]:
    await _create_parent_stubs(database)
    await _stamp_previous_head(database)
    await asyncio.to_thread(_alembic, database, "upgrade", "head")
    connection = await _database_connection(database)
    try:
        snapshot = await _schema_snapshot(connection)
        _assert_canonical_schema(snapshot)
        head = await connection.fetchval("SELECT version_num FROM alembic_version")
    finally:
        await connection.close()
    if head != EXPECTED_HEAD:
        raise AssertionError(f"unexpected Alembic head {head}")
    return {"head": head, "rows": 0}


async def _existing_table_scenario(database: str) -> dict[str, Any]:
    await _create_parent_stubs(database)
    await _stamp_previous_head(database)
    await _create_recommendation_from_orm(database)

    tender_ids = [uuid4(), uuid4(), uuid4()]
    company_ids = [uuid4(), uuid4()]
    recommendation_rows = [
        (uuid4(), tender_ids[0], company_ids[0], 91, "active-alpha", False),
        (uuid4(), tender_ids[1], company_ids[0], 48, "dismissed-alpha", True),
        (uuid4(), tender_ids[0], company_ids[1], 77, "active-beta", False),
        (uuid4(), tender_ids[2], company_ids[1], 12, "low-score-beta", False),
    ]
    connection = await _database_connection(database)
    try:
        await connection.executemany(
            "INSERT INTO tenders (id) VALUES ($1)",
            [(value,) for value in tender_ids],
        )
        await connection.executemany(
            "INSERT INTO company_profiles (id) VALUES ($1)",
            [(value,) for value in company_ids],
        )
        await connection.executemany(
            """
            INSERT INTO tender_recommendations (
                id, tender_id, company_profile_id, match_score,
                strategic_rationale, is_dismissed
            ) VALUES ($1, $2, $3, $4, $5, $6)
            """,
            recommendation_rows,
        )
        before = await connection.fetch(
            """
            SELECT id, tender_id, company_profile_id, match_score,
                   strategic_rationale, is_dismissed, created_at
            FROM tender_recommendations ORDER BY id
            """
        )
    finally:
        await connection.close()

    await asyncio.to_thread(_alembic, database, "upgrade", "head")

    connection = await _database_connection(database)
    try:
        after = await connection.fetch(
            """
            SELECT id, tender_id, company_profile_id, match_score,
                   strategic_rationale, is_dismissed, created_at
            FROM tender_recommendations ORDER BY id
            """
        )
        snapshot = await _schema_snapshot(connection)
        _assert_canonical_schema(snapshot)
    finally:
        await connection.close()
    if [tuple(row) for row in before] != [tuple(row) for row in after]:
        raise AssertionError("recommendation rows changed during reconciliation")

    await asyncio.to_thread(_alembic, database, "downgrade", PREVIOUS_HEAD)
    connection = await _database_connection(database)
    try:
        after_downgrade = await connection.fetch(
            """
            SELECT id, tender_id, company_profile_id, match_score,
                   strategic_rationale, is_dismissed, created_at
            FROM tender_recommendations ORDER BY id
            """
        )
    finally:
        await connection.close()
    if [tuple(row) for row in after] != [tuple(row) for row in after_downgrade]:
        raise AssertionError("non-destructive downgrade changed recommendation rows")
    return {
        "rows_preserved": len(after),
        "dismissed_rows": sum(row[5] for row in after),
        "rows_preserved_after_downgrade": len(after_downgrade),
    }


async def _incompatible_table_scenario(database: str) -> dict[str, Any]:
    await _create_parent_stubs(database)
    await _stamp_previous_head(database)
    connection = await _database_connection(database)
    try:
        await connection.execute(
            """
            CREATE TABLE tender_recommendations (
                id UUID PRIMARY KEY,
                tender_id UUID NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
                match_score INTEGER NOT NULL
            )
            """
        )
    finally:
        await connection.close()

    result = await asyncio.to_thread(
        _alembic,
        database,
        "upgrade",
        "head",
        expect_success=False,
    )
    diagnostic = result.stderr or result.stdout
    if result.returncode == 0:
        raise AssertionError("incompatible table was silently accepted")
    if "Incompatible public.tender_recommendations schema" not in diagnostic:
        raise AssertionError(f"migration did not emit the expected safe failure: {diagnostic[-2000:]}")
    connection = await _database_connection(database)
    try:
        head = await connection.fetchval("SELECT version_num FROM alembic_version")
    finally:
        await connection.close()
    if head != PREVIOUS_HEAD:
        raise AssertionError("failed migration incorrectly advanced Alembic revision")
    return {"head_preserved": head, "failure": "explicit incompatibility"}


async def _orm_consistency_scenario(database: str) -> dict[str, Any]:
    # This is intentionally not the fresh Alembic-only scenario. It creates an
    # isolated full ORM schema solely to ask Alembic autogenerate whether the
    # reconciliation migration leaves TenderRecommendation-specific drift.
    await _create_full_orm_schema(database)
    await _stamp_previous_head(database)
    await asyncio.to_thread(_alembic, database, "upgrade", "head")
    result = await asyncio.to_thread(
        _alembic,
        database,
        "check",
        expect_success=False,
    )
    diagnostic = (result.stderr or result.stdout).strip()
    if "tender_recommendations" in diagnostic:
        raise AssertionError(
            "TenderRecommendation-specific Alembic drift remains: "
            f"{diagnostic[-3000:]}"
        )
    return {
        "alembic_check_returncode": result.returncode,
        "tender_recommendation_drift": False,
        "diagnostic": "\n".join(diagnostic.splitlines()[-6:]),
    }


async def main(selected_labels: set[str] | None = None) -> int:
    all_scenarios = (
        ("fresh", _fresh_database_scenario),
        ("missing", _missing_table_scenario),
        ("existing", _existing_table_scenario),
        ("incompatible", _incompatible_table_scenario),
        ("orm_check", _orm_consistency_scenario),
    )
    known_labels = {label for label, _scenario in all_scenarios}
    if selected_labels and not selected_labels.issubset(known_labels):
        raise ValueError(f"unknown scenario(s): {sorted(selected_labels - known_labels)}")
    scenarios = tuple(
        (label, scenario)
        for label, scenario in all_scenarios
        if not selected_labels or label in selected_labels
    )
    results: list[dict[str, Any]] = []
    failures = 0
    for label, scenario in scenarios:
        try:
            results.append(await _with_database(label, scenario))
        except Exception as exc:
            failures += 1
            results.append({"scenario": label, "status": "failed", "error": str(exc)})
    print(json.dumps({"results": results, "failures": failures}, indent=2, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    requested = set(sys.argv[1:]) or None
    raise SystemExit(asyncio.run(main(requested)))
