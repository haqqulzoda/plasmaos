#!/usr/bin/env python3
"""Disposable PostgreSQL proof for Sprint 8.2 analysis-language persistence."""

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
from scripts import test_s2_2_analysis_version_foundation as s22


HEAD = "20260904_0001_s8_2_analysis_language"
PARENT = "20260902_0001_s7_2_user_ui_locale"


async def revision(database: str) -> str | None:
    connection = await support.database_connection(database)
    try:
        return await connection.fetchval("SELECT version_num FROM alembic_version")
    finally:
        await connection.close()


async def insert_version(
    connection: asyncpg.Connection,
    analysis_id,
    number: int,
    language: str | None,
) -> None:
    await connection.execute(
        """
        INSERT INTO analysis_versions (
            id, analysis_id, version_number, origin, status,
            provenance_snapshot, tender_snapshot, company_snapshot,
            result_snapshot, evidence_snapshot, input_hash, output_hash,
            evidence_hash, document_set_hash, version_hash,
            snapshot_completeness, analysis_language
        ) VALUES (
            $1, $2, $3, 'RUNTIME_ANALYSIS', 'COMPLETED',
            '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
            $4, $5, $6, $7, $8, 'COMPLETE', $9
        )
        """,
        uuid4(), analysis_id, number, f"{number}" * 64, "a" * 64,
        "b" * 64, "c" * 64, "d" * 64, language,
    )


async def fresh_database_scenario() -> dict[str, Any]:
    database = support.database_name("s82_fresh")
    await support.create_database(database)
    try:
        bootstrap = await asyncio.to_thread(support.run_bootstrap, database)
        assert bootstrap.returncode == 0, bootstrap.stderr or bootstrap.stdout
        assert await revision(database) == HEAD
        fixture = await s22.seed_s2_1(database)
        connection = await support.database_connection(database)
        try:
            user_id = fixture["users"]["a"]
            for code in (None, "en", "uz", "ru", "ar"):
                await connection.execute(
                    "UPDATE users SET default_analysis_language = $1 WHERE id = $2",
                    code, user_id,
                )
                assert await connection.fetchval(
                    "SELECT default_analysis_language FROM users WHERE id = $1", user_id,
                ) == code
            analysis_id = fixture["analysis_ids"]["owned_a"]
            for number, code in enumerate((None, "en", "uz", "ru", "ar"), start=1):
                await insert_version(connection, analysis_id, number, code)
            assert await connection.fetch(
                "SELECT analysis_language FROM analysis_versions ORDER BY version_number"
            ) == [(None,), ("en",), ("uz",), ("ru",), ("ar",)]
            with_expected_violation = 0
            try:
                await connection.execute(
                    "UPDATE users SET default_analysis_language = 'fr' WHERE id = $1", user_id,
                )
            except asyncpg.CheckViolationError:
                with_expected_violation += 1
            try:
                await connection.execute(
                    "UPDATE analysis_versions SET analysis_language = 'en-US' WHERE analysis_id = $1",
                    analysis_id,
                )
            except asyncpg.CheckViolationError:
                with_expected_violation += 1
            assert with_expected_violation == 2
        finally:
            await connection.close()
        check = await asyncio.to_thread(support.alembic, database, "check")
        assert check.returncode == 0, check.stderr or check.stdout
        return {"head": HEAD, "canonical_values": "validated", "constraints": "validated", "alembic_check": "clean"}
    finally:
        await support.drop_database(database)


async def existing_database_scenario() -> dict[str, Any]:
    database = support.database_name("s82_existing")
    await support.create_database(database)
    try:
        await support.raw_baseline(database)
        upgrade = await asyncio.to_thread(support.alembic, database, "upgrade", PARENT)
        assert upgrade.returncode == 0, upgrade.stderr or upgrade.stdout
        fixture = await s22.seed_s2_1(database)
        connection = await support.database_connection(database)
        try:
            analysis_id = fixture["analysis_ids"]["owned_a"]
            await connection.execute(
                """
                INSERT INTO analysis_versions (
                    id, analysis_id, version_number, origin, status,
                    provenance_snapshot, tender_snapshot, company_snapshot,
                    result_snapshot, evidence_snapshot, input_hash, output_hash,
                    evidence_hash, document_set_hash, version_hash,
                    snapshot_completeness
                ) VALUES ($1, $2, 1, 'RUNTIME_ANALYSIS', 'COMPLETED', '{}'::jsonb,
                          '{}'::jsonb, '{}'::jsonb, '{"preserved": true}'::jsonb,
                          '{}'::jsonb, $3, $4, $5, $6, $7, 'COMPLETE')
                """,
                uuid4(), analysis_id, "1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64,
            )
            before = await connection.fetchrow(
                "SELECT result_snapshot, input_hash, version_hash FROM analysis_versions WHERE analysis_id = $1",
                analysis_id,
            )
            user_fingerprint = await connection.fetch(
                "SELECT id, auth_version, approval_status, ui_locale FROM users ORDER BY id"
            )
        finally:
            await connection.close()

        upgrade = await asyncio.to_thread(support.alembic, database, "upgrade", "head")
        assert upgrade.returncode == 0, upgrade.stderr or upgrade.stdout
        connection = await support.database_connection(database)
        try:
            after = await connection.fetchrow(
                "SELECT result_snapshot, input_hash, version_hash, analysis_language FROM analysis_versions WHERE analysis_id = $1",
                analysis_id,
            )
            assert after["analysis_language"] is None
            assert tuple(after.values())[:3] == tuple(before.values())
            assert await connection.fetchval("SELECT count(*) FROM users WHERE default_analysis_language IS NOT NULL") == 0
            assert await connection.fetch(
                "SELECT id, auth_version, approval_status, ui_locale FROM users ORDER BY id"
            ) == user_fingerprint
        finally:
            await connection.close()

        downgrade = await asyncio.to_thread(support.alembic, database, "downgrade", PARENT)
        assert downgrade.returncode == 0, downgrade.stderr or downgrade.stdout
        assert await revision(database) == PARENT
        upgrade = await asyncio.to_thread(support.alembic, database, "upgrade", "head")
        assert upgrade.returncode == 0, upgrade.stderr or upgrade.stdout
        assert await revision(database) == HEAD
        return {"historical_versions": "NULL", "historical_users": "NULL", "hashes": "preserved", "downgrade_reupgrade": "passed"}
    finally:
        await support.drop_database(database)


async def main() -> int:
    results: dict[str, Any] = {}
    failures = 0
    for label, scenario in (("fresh", fresh_database_scenario), ("existing", existing_database_scenario)):
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
