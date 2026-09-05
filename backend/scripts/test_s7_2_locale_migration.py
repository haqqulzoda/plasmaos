#!/usr/bin/env python3
"""Disposable PostgreSQL proof for Sprint 7.2 locale persistence."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

import asyncpg


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts import test_s0_5b4_baseline as support


HEAD = "20260904_0001_s8_2_analysis_language"
PARENT = "20260901_0001_sr2_3_connector_metrics"


async def revision(database: str) -> str | None:
    connection = await support.database_connection(database)
    try:
        return await connection.fetchval("SELECT version_num FROM alembic_version")
    finally:
        await connection.close()


async def insert_user(
    connection: asyncpg.Connection,
    label: str,
    *,
    locale: str | None = None,
) -> str:
    user_id = uuid4()
    await connection.execute(
        """
        INSERT INTO users (
            id, google_id, email, name, subscription_tier, is_admin,
            approval_status, platform_role, auth_version, ui_locale
        ) VALUES ($1, $2, $3, $4, 'SCOUT', false, 'approved', 'pilot_user', 23, $5)
        """,
        user_id,
        f"s72-{label}-{user_id}",
        f"{label}-{user_id}@s72.invalid",
        label,
        locale,
    )
    return str(user_id)


async def fresh_database_scenario() -> dict[str, Any]:
    database = support.database_name("s72_fresh")
    await support.create_database(database)
    try:
        bootstrap = await asyncio.to_thread(support.run_bootstrap, database)
        assert bootstrap.returncode == 0, bootstrap.stderr or bootstrap.stdout
        assert await revision(database) == HEAD
        connection = await support.database_connection(database)
        try:
            for locale in (None, "en", "uz", "ru"):
                await insert_user(connection, locale or "null", locale=locale)
            rows = await connection.fetch(
                "SELECT ui_locale, auth_version, approval_status FROM users ORDER BY email"
            )
            assert sorted(row["ui_locale"] or "NULL" for row in rows) == [
                "NULL", "en", "ru", "uz"
            ]
            assert all(row["auth_version"] == 23 for row in rows)
            assert all(row["approval_status"] == "approved" for row in rows)
            try:
                await insert_user(connection, "invalid", locale="fr")
            except asyncpg.CheckViolationError:
                pass
            else:
                raise AssertionError("database accepted an unknown UI locale")
        finally:
            await connection.close()
        check = await asyncio.to_thread(support.alembic, database, "check")
        assert check.returncode == 0, check.stderr or check.stdout
        return {
            "head": HEAD,
            "null_en_uz_ru": "validated",
            "unknown_locale": "check_constraint_rejected",
            "alembic_check": "clean",
        }
    finally:
        await support.drop_database(database)


async def existing_database_scenario() -> dict[str, Any]:
    database = support.database_name("s72_existing")
    await support.create_database(database)
    try:
        await support.raw_baseline(database)
        await asyncio.to_thread(support.alembic, database, "upgrade", PARENT)
        connection = await support.database_connection(database)
        try:
            ids = []
            for label, approval, version in (
                ("approved", "approved", 31),
                ("pending", "pending", 32),
            ):
                user_id = uuid4()
                ids.append(user_id)
                await connection.execute(
                    """
                    INSERT INTO users (
                        id, google_id, email, name, subscription_tier, is_admin,
                        approval_status, platform_role, auth_version
                    ) VALUES ($1, $2, $3, $4, 'SCOUT', false, $5, 'pilot_user', $6)
                    """,
                    user_id,
                    f"s72-existing-{user_id}",
                    f"{label}-{user_id}@s72.invalid",
                    label,
                    approval,
                    version,
                )
        finally:
            await connection.close()

        await asyncio.to_thread(support.alembic, database, "upgrade", "head")
        connection = await support.database_connection(database)
        try:
            rows = await connection.fetch(
                "SELECT id, ui_locale, auth_version, approval_status FROM users ORDER BY auth_version"
            )
            assert [row["auth_version"] for row in rows] == [31, 32]
            assert [row["approval_status"] for row in rows] == ["approved", "pending"]
            assert all(row["ui_locale"] is None for row in rows)
            before_unrelated = [(str(row["id"]), row["auth_version"], row["approval_status"]) for row in rows]
            await connection.execute("UPDATE users SET ui_locale = 'ru' WHERE id = $1", ids[0])
        finally:
            await connection.close()

        await asyncio.to_thread(support.alembic, database, "downgrade", PARENT)
        assert await revision(database) == PARENT
        connection = await support.database_connection(database)
        try:
            column_exists = await connection.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'users'
                      AND column_name = 'ui_locale'
                )
                """
            )
            assert not column_exists
            downgraded = await connection.fetch(
                "SELECT id, auth_version, approval_status FROM users ORDER BY auth_version"
            )
            assert [(str(row["id"]), row["auth_version"], row["approval_status"]) for row in downgraded] == before_unrelated
        finally:
            await connection.close()

        await asyncio.to_thread(support.alembic, database, "upgrade", "head")
        assert await revision(database) == HEAD
        connection = await support.database_connection(database)
        try:
            assert await connection.fetchval("SELECT count(*) FROM users") == 2
            assert await connection.fetchval("SELECT count(*) FROM users WHERE ui_locale IS NULL") == 2
        finally:
            await connection.close()
        return {
            "head": HEAD,
            "historical_users": 2,
            "historical_locale": "NULL",
            "auth_and_approval": "preserved",
            "downgrade_reupgrade": "passed",
        }
    finally:
        await support.drop_database(database)


async def main() -> int:
    results: dict[str, Any] = {}
    failures = 0
    for label, scenario in (
        ("fresh", fresh_database_scenario),
        ("existing", existing_database_scenario),
    ):
        try:
            results[label] = {"status": "passed", **await scenario()}
        except Exception as exc:
            failures += 1
            results[label] = {"status": "failed", "error": repr(exc)}
    leaked = await support.leaked_databases()
    if leaked:
        failures += 1
    print(json.dumps({"results": results, "leaked_databases": leaked, "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
