#!/usr/bin/env python3
"""Disposable PostgreSQL proof matrix for Sprint 1.1 Project foundation."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Awaitable, Callable
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.all_models import TenderStatus
from app.services.projects import resolve_or_create_project
from app.services.tender_sources.base import NormalizedTender
from app.services.tender_sources.world_bank import WorldBankTenderSource
from scripts import bootstrap_database as bootstrap
from scripts import test_s0_5b4_baseline as support


BASELINE = "20260824_0002_s0_4c"
SPRINT_ZERO_HEAD = "20260825_0001_s0_5b3"
HEAD = "20260827_0001_s2_1_compliance_ownership"
MIGRATION_PATH = BACKEND_DIR / "alembic/versions/20260826_0001_s1_1_project_foundation.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("s1_1_live_migration", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def seed_existing_rows(database: str) -> dict[str, str]:
    user_id = uuid4()
    company_id = uuid4()
    tender_ids = [uuid4() for _ in range(6)]
    document_id = uuid4()
    proposal_id = uuid4()
    analysis_id = uuid4()
    recommendation_id = uuid4()
    rows = [
        (tender_ids[0], "WB-1", "world_bank", "P123456", "Liberia"),
        (tender_ids[1], "WB-2", "world_bank", "P123456", "Liberia"),
        (tender_ids[2], "WB-3", "world_bank", "  P654321  ", "Ghana"),
        (tender_ids[3], "WB-4", "world_bank", "123456", "Kenya"),
        (tender_ids[4], "WB-5", "world_bank", "   ", "Benin"),
        (tender_ids[5], "ADB-1", "adb", "P123456", "Georgia"),
    ]
    connection = await support.database_connection(database)
    try:
        await connection.execute(
            """
            INSERT INTO users (
                id, subscription_tier, is_admin, google_id, email, name,
                approval_status, platform_role
            ) VALUES ($1, 'SCOUT', false, $2, $3, 'S1.1 User', 'approved', 'pilot_user')
            """,
            user_id,
            f"google-{user_id}",
            f"{user_id}@example.test",
        )
        await connection.execute(
            """
            INSERT INTO company_profiles (
                id, user_id, company_name, pilot_status, approval_status
            ) VALUES ($1, $2, 'S1.1 Company', 'active_pilot', 'approved')
            """,
            company_id,
            user_id,
        )
        await connection.executemany(
            """
            INSERT INTO tenders (
                id, external_id, source_url, title, budget, currency,
                status, category, source_system, canonical_source_key,
                country, project_id, source_metadata_json, scrape_status
            ) VALUES (
                $1, $2::varchar, CONCAT('https://example.test/', $2::varchar),
                CONCAT('Preserved ', $2::varchar),
                1000, 'USD', 'OPEN', 'Other', $3::varchar,
                CONCAT($3::varchar, ':', $2::varchar),
                $5::varchar, $4::varchar,
                json_build_object('project_id', $4::varchar), 'success'
            )
            """,
            rows,
        )
        await connection.execute(
            """
            INSERT INTO tender_documents (
                id, tender_id, file_url, file_type, parsed_text,
                source_document_url, download_status
            ) VALUES ($1, $2, '/preserve.pdf', 'pdf', 'preserve text',
                      'https://example.test/preserve.pdf', 'available')
            """,
            document_id,
            tender_ids[0],
        )
        await connection.execute(
            """
            INSERT INTO proposals (
                id, user_id, tender_id, status, ai_confidence_score,
                structured_data, margin_percent, include_vat, currency
            ) VALUES ($1, $2, $3, 'DRAFT', 77, '{"preserve": true}'::json,
                      18.5, true, 'USD')
            """,
            proposal_id,
            user_id,
            tender_ids[0],
        )
        await connection.execute(
            """
            INSERT INTO tender_analyses (
                id, tender_id, tender_file_name, company_name,
                raw_extracted_text, analysis_json, content_hash
            ) VALUES ($1, $2, 'preserve.pdf', 'preserve-owner', 'preserve analysis',
                      '{"preserve": true}'::jsonb, $3)
            """,
            analysis_id,
            tender_ids[0],
            "a" * 64,
        )
        await connection.execute(
            """
            INSERT INTO tender_recommendations (
                id, tender_id, company_profile_id, match_score,
                strategic_rationale, is_dismissed
            ) VALUES ($1, $2, $3, 88, 'preserve rationale', false)
            """,
            recommendation_id,
            tender_ids[0],
            company_id,
        )
    finally:
        await connection.close()
    return {
        "user_id": str(user_id),
        "company_id": str(company_id),
        "primary_tender_id": str(tender_ids[0]),
        "document_id": str(document_id),
        "proposal_id": str(proposal_id),
        "analysis_id": str(analysis_id),
        "recommendation_id": str(recommendation_id),
    }


async def business_snapshot(database: str, ids: dict[str, str]) -> dict[str, Any]:
    connection = await support.database_connection(database)
    try:
        tender_rows = await connection.fetch(
            """
            SELECT id::text, external_id, source_url, title, budget, currency,
                   status::text, category, source_system, canonical_source_key,
                   country, project_id, source_metadata_json::text, scrape_status,
                   created_at
            FROM tenders ORDER BY external_id
            """
        )
        artifacts: dict[str, Any] = {}
        for table, row_id in (
            ("tender_documents", ids["document_id"]),
            ("proposals", ids["proposal_id"]),
            ("tender_analyses", ids["analysis_id"]),
            ("tender_recommendations", ids["recommendation_id"]),
        ):
            row = await connection.fetchrow(
                f"SELECT *, xmin::text AS row_version FROM {table} WHERE id = $1::uuid",
                row_id,
            )
            artifacts[table] = dict(row)
        return {
            "tenders": [tuple(row) for row in tender_rows],
            "artifacts": artifacts,
        }
    finally:
        await connection.close()


async def assert_schema_and_backfill(database: str) -> dict[str, Any]:
    connection = await support.database_connection(database)
    try:
        head = await bootstrap.current_revision(connection)
        assert head == HEAD
        tables = set(
            await connection.fetch(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                """
            )
        )
        del tables  # table existence is asserted directly below for clearer failures
        assert await connection.fetchval("SELECT to_regclass('public.projects')") == "projects"
        assert await connection.fetchval("SELECT to_regclass('public.tender_projects')") == "tender_projects"
        projects = await connection.fetch(
            """
            SELECT source_system, external_project_id, country
            FROM projects ORDER BY source_system, external_project_id
            """
        )
        links = await connection.fetch(
            """
            SELECT t.external_id, p.source_system, p.external_project_id,
                   tp.source_value, tp.linkage_method, tp.provenance
            FROM tender_projects tp
            JOIN tenders t ON t.id = tp.tender_id
            JOIN projects p ON p.id = tp.project_id
            ORDER BY t.external_id
            """
        )
        assert [tuple(row) for row in projects] == [
            ("world_bank", "P123456", "Liberia"),
            ("world_bank", "P654321", "Ghana"),
        ]
        assert [row[0] for row in links] == ["WB-1", "WB-2", "WB-3"]
        assert {row[2] for row in links} == {"P123456", "P654321"}
        assert all(row[4] == "SOURCE_PROJECT_ID" for row in links)
        whitespace_link = next(row for row in links if row[0] == "WB-3")
        whitespace_provenance = (
            json.loads(whitespace_link[5])
            if isinstance(whitespace_link[5], str)
            else whitespace_link[5]
        )
        assert whitespace_link[3] == "  P654321  "
        assert whitespace_provenance["normalized_value"] == "P654321"
        assert whitespace_provenance["normalization_changed"] is True
        assert not await connection.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM tender_projects tp JOIN tenders t ON t.id = tp.tender_id
                WHERE t.external_id IN ('WB-4', 'WB-5', 'ADB-1')
            )
            """
        )
        return {"projects": len(projects), "links": len(links), "head": head}
    finally:
        await connection.close()


async def rerun_backfill(database: str) -> dict[str, int]:
    migration = load_migration()
    engine = create_async_engine(support.target_url(database))
    try:
        async with engine.begin() as connection:
            return await connection.run_sync(migration._backfill_world_bank_projects)
    finally:
        await engine.dispose()


async def exercise_application_service(database: str) -> dict[str, Any]:
    engine = create_async_engine(support.target_url(database))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            adb_project, adb_created = await resolve_or_create_project(
                session,
                source_system="adb",
                external_project_id="P123456",
                authoritative_metadata={"country": "Georgia"},
            )
            assert adb_created
            await session.commit()
            assert adb_project.source_system == "adb"

        source = WorldBankTenderSource()
        normalized = NormalizedTender(
            source_system="world_bank",
            external_id="WB-NEW",
            source_url="https://example.test/WB-NEW",
            title="New deterministic notice",
            budget=5.0,
            currency="USD",
            country="Liberia",
            project_id="P777777",
            status=TenderStatus.OPEN,
            category="World Bank",
            source_metadata_json={"project_id": " P777777 "},
        )
        async with AsyncSession(engine, expire_on_commit=False) as session:
            tender, first_created = await source.upsert(session, normalized)
            await session.commit()
            tender_id = tender.id
            assert first_created
        sparse = NormalizedTender(
            **{
                **normalized.__dict__,
                "country": None,
            }
        )
        async with AsyncSession(engine, expire_on_commit=False) as session:
            tender, second_created = await source.upsert(session, sparse)
            await session.commit()
            assert not second_created
            assert tender.id == tender_id
    finally:
        await engine.dispose()

    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval(
            """
            SELECT COUNT(*) FROM projects
            WHERE external_project_id = 'P123456'
              AND source_system IN ('world_bank', 'adb')
            """
        ) == 2
        project_id = await connection.fetchval(
            """
            SELECT id FROM projects
            WHERE source_system = 'world_bank' AND external_project_id = 'P777777'
            """
        )
        assert project_id is not None
        assert await connection.fetchval(
            "SELECT country FROM projects WHERE id = $1", project_id
        ) == "Liberia"
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM tender_projects WHERE tender_id = $1", tender_id
        ) == 1
        await connection.execute("DELETE FROM projects WHERE id = $1", project_id)
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM tenders WHERE id = $1", tender_id
        ) == 1
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM tender_projects WHERE tender_id = $1", tender_id
        ) == 0
        return {
            "source_collision_separate": True,
            "connector_refresh_idempotent": True,
            "metadata_preserved": True,
            "project_delete_preserves_tender": True,
        }
    finally:
        await connection.close()


async def assert_alembic_check(database: str) -> None:
    result = await asyncio.to_thread(support.alembic, database, "check", success=False)
    diagnostic = result.stdout + result.stderr
    assert result.returncode == 0, diagnostic
    assert "No new upgrade operations detected" in diagnostic


async def fresh_scenario(database: str) -> dict[str, Any]:
    result = await asyncio.to_thread(support.run_bootstrap, database)
    assert result.returncode == 0, result.stderr or result.stdout
    connection = await support.database_connection(database)
    try:
        assert await bootstrap.current_revision(connection) == HEAD
        assert await connection.fetchval("SELECT COUNT(*) FROM projects") == 0
        assert await connection.fetchval("SELECT COUNT(*) FROM tender_projects") == 0
    finally:
        await connection.close()
    await assert_alembic_check(database)
    return {"head": HEAD, "schema": "clean", "alembic_check": "clean"}


async def existing_scenario(database: str) -> dict[str, Any]:
    await support.raw_baseline(database)
    await asyncio.to_thread(support.alembic, database, "upgrade", SPRINT_ZERO_HEAD)
    ids = await seed_existing_rows(database)
    before = await business_snapshot(database, ids)
    await asyncio.to_thread(support.alembic, database, "upgrade", "head")
    after = await business_snapshot(database, ids)
    assert before == after
    backfill = await assert_schema_and_backfill(database)
    rerun = await rerun_backfill(database)
    assert rerun == {
        "world_bank_tenders_with_project_id": 5,
        "valid_ids": 3,
        "invalid_skipped_ids": 2,
        "distinct_project_ids": 2,
        "normalization_changes": 1,
        "links_already_present": 3,
        "projects_created": 0,
        "projects_reused": 3,
        "tenderproject_links_created": 0,
        "errors": 0,
    }
    service = await exercise_application_service(database)
    await assert_alembic_check(database)
    return {
        "from": SPRINT_ZERO_HEAD,
        "to": HEAD,
        "business_rows_preserved": True,
        "initial_backfill": backfill,
        "rerun_backfill": rerun,
        **service,
        "alembic_check": "clean",
    }


async def with_database(
    label: str,
    scenario: Callable[[str], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    database = support.database_name(f"s11_{label}")
    await support.create_database(database)
    try:
        return {"scenario": label, "status": "passed", **await scenario(database)}
    finally:
        await support.drop_database(database)


async def main() -> int:
    results: list[dict[str, Any]] = []
    failures = 0
    for label, scenario in (("fresh", fresh_scenario), ("existing", existing_scenario)):
        try:
            results.append(await with_database(label, scenario))
        except Exception as exc:
            failures += 1
            results.append(
                {"scenario": label, "status": "failed", "error": repr(exc)}
            )
    leaked = await support.leaked_databases()
    if leaked:
        failures += 1
    print(
        json.dumps(
            {"results": results, "leaked_databases": leaked, "failures": failures},
            indent=2,
            default=str,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
