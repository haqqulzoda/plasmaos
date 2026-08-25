#!/usr/bin/env python3
"""Disposable PostgreSQL proof matrix for the immutable S0.5B.4B baseline."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Awaitable, Callable
from uuid import uuid4

import asyncpg

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from scripts import bootstrap_database as bootstrap


PREFIX = "plasma_s05b4b_"
BASELINE = "20260824_0002_s0_4c"
HEAD = "20260825_0001_s0_5b3"
OLDER = "a8f3d1c2e5b4"
BUSINESS_TABLES = (
    "users",
    "tenders",
    "proposals",
    "tender_analyses",
    "tender_recommendations",
)


def database_name(label: str) -> str:
    label = re.sub(r"[^a-z0-9_]", "_", label.casefold())
    return f"{PREFIX}{label}_{uuid4().hex[:8]}"


def assert_disposable(database: str) -> None:
    if not re.fullmatch(r"plasma_s05b4b_[a-z0-9_]+", database):
        raise RuntimeError(f"unsafe disposable database name: {database!r}")


async def admin_connection() -> asyncpg.Connection:
    return await asyncpg.connect(
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        database="postgres",
    )


async def database_connection(database: str) -> asyncpg.Connection:
    assert_disposable(database)
    return await asyncpg.connect(
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        database=database,
    )


async def create_database(database: str) -> None:
    assert_disposable(database)
    connection = await admin_connection()
    try:
        if await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", database):
            raise RuntimeError(f"refusing to overwrite disposable database {database}")
        await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()


async def drop_database(database: str) -> None:
    assert_disposable(database)
    connection = await admin_connection()
    try:
        await connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database,
        )
        await connection.execute(f'DROP DATABASE IF EXISTS "{database}"')
    finally:
        await connection.close()


def target_url(database: str) -> str:
    assert_disposable(database)
    return (
        f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{database}"
    )


def environment(database: str) -> dict[str, str]:
    result = os.environ.copy()
    result.update(
        {
            "POSTGRES_SERVER": settings.POSTGRES_SERVER,
            "POSTGRES_PORT": str(settings.POSTGRES_PORT),
            "POSTGRES_USER": settings.POSTGRES_USER,
            "POSTGRES_PASSWORD": settings.POSTGRES_PASSWORD,
            "POSTGRES_DB": database,
            "PLASMA_BOOTSTRAP_DATABASE_URL": target_url(database),
            "AUTO_CREATE_TABLES": "false",
        }
    )
    return result


def run_bootstrap(database: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/bootstrap_database.py",
            "--confirm",
            bootstrap.CONFIRMATION,
        ],
        cwd=BACKEND_DIR,
        env=environment(database),
        text=True,
        capture_output=True,
        check=False,
    )


def alembic(database: str, *arguments: str, success: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment(database),
        text=True,
        capture_output=True,
        check=False,
    )
    if success and result.returncode:
        raise AssertionError((result.stderr or result.stdout)[-4000:])
    return result


async def raw_baseline(database: str, revision: str = BASELINE) -> None:
    manifest = bootstrap.load_manifest()
    sql = bootstrap.snapshot_path(manifest).read_text(encoding="utf-8")
    connection = await database_connection(database)
    try:
        await bootstrap.require_genuinely_empty(connection)
        await bootstrap.apply_baseline_transaction(connection, sql, manifest)
    finally:
        await connection.close()
    await asyncio.to_thread(alembic, database, "stamp", revision)


async def catalog_signature(database: str) -> str:
    connection = await database_connection(database)
    try:
        rows = await connection.fetch(
            """
            SELECT 'column' AS kind,
                   table_name || '.' || column_name || ':' || data_type || ':' || is_nullable AS value
            FROM information_schema.columns
            WHERE table_schema = 'public'
            UNION ALL
            SELECT 'constraint', conname || ':' || pg_get_constraintdef(c.oid)
            FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
            WHERE n.nspname = 'public'
            UNION ALL
            SELECT 'index', indexname || ':' || indexdef
            FROM pg_indexes WHERE schemaname = 'public'
            UNION ALL
            SELECT 'view', table_name || ':' || view_definition
            FROM information_schema.views WHERE table_schema = 'public'
            ORDER BY kind, value
            """
        )
        revision = await bootstrap.current_revision(connection)
        payload = json.dumps(
            {"revision": revision, "catalog": [(row["kind"], row["value"]) for row in rows]},
            sort_keys=True,
        ).encode()
        return hashlib.sha256(payload).hexdigest()
    finally:
        await connection.close()


async def verify_recommendation_contract(database: str) -> dict[str, Any]:
    connection = await database_connection(database)
    try:
        columns = await connection.fetch(
            """
            SELECT column_name, is_nullable, data_type, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'tender_recommendations'
            ORDER BY ordinal_position
            """
        )
        constraints = {
            row["conname"]: row["definition"]
            for row in await connection.fetch(
                """
                SELECT conname, pg_get_constraintdef(oid) AS definition
                FROM pg_constraint
                WHERE conrelid = 'public.tender_recommendations'::regclass
                """
            )
        }
        indexes = {
            row["indexname"]
            for row in await connection.fetch(
                """
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = 'tender_recommendations'
                """
            )
        }
        expected_columns = {
            "id",
            "tender_id",
            "company_profile_id",
            "match_score",
            "strategic_rationale",
            "is_dismissed",
            "created_at",
        }
        by_name = {row["column_name"]: row for row in columns}
        assert set(by_name) == expected_columns
        assert all(row["is_nullable"] == "NO" for row in columns)
        assert by_name["is_dismissed"]["column_default"] == "false"
        assert "now()" in by_name["created_at"]["column_default"]
        assert "PRIMARY KEY (id)" in constraints["tender_recommendations_pkey"]
        assert "ON DELETE CASCADE" in constraints["tender_recommendations_tender_id_fkey"]
        assert "ON DELETE CASCADE" in constraints[
            "tender_recommendations_company_profile_id_fkey"
        ]
        assert "match_score >= 0" in constraints[
            "ck_tender_recommendations_match_score_range"
        ]
        assert "UNIQUE (tender_id, company_profile_id)" in constraints[
            "uq_tender_recommendations_tender_profile"
        ]
        required_indexes = {
            "ix_tender_recommendations_tender_id",
            "ix_tender_recommendations_company_profile_id",
            "ix_tender_recommendations_created_at",
        }
        assert required_indexes <= indexes
        rows = await connection.fetchval("SELECT count(*) FROM tender_recommendations")
        assert rows == 0
        return {"columns": len(columns), "constraints": len(constraints), "indexes": len(indexes)}
    finally:
        await connection.close()


async def fresh_scenario(database: str) -> dict[str, Any]:
    result = await asyncio.to_thread(run_bootstrap, database)
    if result.returncode:
        raise AssertionError((result.stderr or result.stdout)[-5000:])
    assert settings.POSTGRES_PASSWORD not in result.stdout
    assert settings.POSTGRES_PASSWORD not in result.stderr

    manifest = bootstrap.load_manifest()
    connection = await database_connection(database)
    try:
        await bootstrap.validate_schema(connection, manifest, expected_revision=HEAD)
        await bootstrap.assert_zero_business_rows(connection, manifest["tables"])
        revision = await bootstrap.current_revision(connection)
    finally:
        await connection.close()

    current = await asyncio.to_thread(alembic, database, "current")
    heads = await asyncio.to_thread(alembic, database, "heads")
    assert HEAD in current.stdout
    assert HEAD in heads.stdout

    check = await asyncio.to_thread(alembic, database, "check", success=False)
    diagnostic = check.stdout + check.stderr
    assert check.returncode == 0, diagnostic
    assert "No new upgrade operations detected" in diagnostic
    assert "uq_proposals_user_tender" not in diagnostic
    assert "override_seal" not in diagnostic
    assert "tender_recommendations" not in diagnostic
    recommendation = await verify_recommendation_contract(database)
    return {
        "revision": revision,
        "recommendation": recommendation,
        "alembic_check": "clean",
    }


async def rejection_scenario(
    database: str,
    setup: Callable[[str], Awaitable[None]],
) -> dict[str, Any]:
    await setup(database)
    before = await catalog_signature(database)
    result = await asyncio.to_thread(run_bootstrap, database)
    after = await catalog_signature(database)
    assert result.returncode != 0
    assert "not genuinely empty" in result.stderr
    assert before == after
    return {"refused": True, "catalog_unchanged": True}


async def create_alembic_only(database: str) -> None:
    connection = await database_connection(database)
    try:
        await connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(128) PRIMARY KEY)")
    finally:
        await connection.close()


async def create_users_only(database: str) -> None:
    connection = await database_connection(database)
    try:
        await connection.execute("CREATE TABLE users (id UUID PRIMARY KEY)")
    finally:
        await connection.close()


async def create_partial_plasma(database: str) -> None:
    connection = await database_connection(database)
    try:
        await connection.execute("CREATE TABLE tenders (id UUID PRIMARY KEY)")
    finally:
        await connection.close()


async def create_unrelated(database: str) -> None:
    connection = await database_connection(database)
    try:
        await connection.execute("CREATE TABLE unrelated_application_state (id BIGINT PRIMARY KEY)")
    finally:
        await connection.close()


async def setup_0_4c(database: str) -> None:
    await raw_baseline(database)


async def setup_head(database: str) -> None:
    await raw_baseline(database)
    await asyncio.to_thread(alembic, database, "upgrade", "head")


async def setup_older(database: str) -> None:
    await raw_baseline(database)
    await asyncio.to_thread(alembic, database, "downgrade", OLDER)


async def existing_upgrade_scenario(
    database: str,
    setup: Callable[[str], Awaitable[None]],
    expected_before: str,
) -> dict[str, Any]:
    await setup(database)
    signature = await catalog_signature(database)
    refusal = await asyncio.to_thread(run_bootstrap, database)
    assert refusal.returncode != 0
    assert signature == await catalog_signature(database)
    connection = await database_connection(database)
    try:
        assert await bootstrap.current_revision(connection) == expected_before
    finally:
        await connection.close()
    await asyncio.to_thread(alembic, database, "upgrade", "head")
    connection = await database_connection(database)
    try:
        assert await bootstrap.current_revision(connection) == HEAD
    finally:
        await connection.close()
    return {"baseline_refused": True, "before": expected_before, "after": HEAD}


async def failed_apply_scenario(database: str) -> dict[str, Any]:
    manifest = bootstrap.load_manifest()
    sql = bootstrap.snapshot_path(manifest).read_text(encoding="utf-8")
    connection = await database_connection(database)
    try:
        try:
            await bootstrap.apply_baseline_transaction(
                connection,
                sql + "\nSELECT definitely_missing_s0_5b4b_function();\n",
                manifest,
            )
        except asyncpg.PostgresError:
            pass
        else:
            raise AssertionError("deliberately broken baseline unexpectedly succeeded")
        assert await bootstrap.discover_user_objects(connection) == []
        assert await bootstrap.current_revision(connection) is None
    finally:
        await connection.close()
    return {"rolled_back": True, "stamped": False}


async def with_database(
    label: str,
    scenario: Callable[[str], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    database = database_name(label)
    await create_database(database)
    try:
        return {"scenario": label, "status": "passed", **await scenario(database)}
    finally:
        await drop_database(database)


async def leaked_databases() -> list[str]:
    connection = await admin_connection()
    try:
        rows = await connection.fetch(
            "SELECT datname FROM pg_database WHERE datname LIKE $1 ORDER BY datname",
            f"{PREFIX}%",
        )
        return [row["datname"] for row in rows]
    finally:
        await connection.close()


async def main() -> int:
    scenarios: list[tuple[str, Callable[[str], Awaitable[dict[str, Any]]]]] = [
        ("fresh", fresh_scenario),
        ("guard_alembic", lambda db: rejection_scenario(db, create_alembic_only)),
        ("guard_users", lambda db: rejection_scenario(db, create_users_only)),
        ("guard_partial", lambda db: rejection_scenario(db, create_partial_plasma)),
        ("guard_unrelated", lambda db: rejection_scenario(db, create_unrelated)),
        (
            "existing_0_4c",
            lambda db: existing_upgrade_scenario(db, setup_0_4c, BASELINE),
        ),
        (
            "existing_head",
            lambda db: existing_upgrade_scenario(db, setup_head, HEAD),
        ),
        (
            "existing_older",
            lambda db: existing_upgrade_scenario(db, setup_older, OLDER),
        ),
        ("failed_apply", failed_apply_scenario),
    ]
    results: list[dict[str, Any]] = []
    failures = 0
    for label, scenario in scenarios:
        try:
            results.append(await with_database(label, scenario))
        except Exception as exc:
            failures += 1
            results.append({"scenario": label, "status": "failed", "error": str(exc)})
    leaks = await leaked_databases()
    if leaks:
        failures += 1
    print(json.dumps({"results": results, "leaked_databases": leaks, "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
