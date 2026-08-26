#!/usr/bin/env python3
"""Disposable PostgreSQL proof matrix for Sprint 1.2 Project enrichment."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.all_models import Project, ProjectRoleAssignment, Tender
from app.services.project_enrichment import (
    apply_world_bank_project_snapshot,
    claim_world_bank_projects_for_enrichment,
)
from app.services.world_bank_projects import (
    WorldBankProjectIdentityMismatch,
    normalize_world_bank_project_record,
)
from scripts import bootstrap_database as bootstrap
from scripts import test_s0_5b4_baseline as support


S1_1_HEAD = "20260826_0001_s1_1_project_foundation"
HEAD = "20260826_0002_s1_2_wb_project_enrichment"


def fixture(project_id: str = "P179267", **overrides: Any) -> dict[str, Any]:
    record = {
        "id": project_id,
        "project_name": "Authoritative Project Name",
        "countryshortname": "Liberia",
        "regionname": "Western and Central Africa",
        "projectstatusdisplay": "Active",
        "boardapprovaldate": "2022-12-20T00:00:00Z",
        "closingdate": "6/30/2027 12:00:00 AM",
        "borrower": "Republic of Liberia",
        "impagency": "Liberia Electricity Corporation (LEC)",
        "teamleadname": "Leader One,Leader Two",
        "p2a_updated_date": "2022-12-21 00:00:00.0",
        "url": (
            "https://projects.worldbank.org/en/projects-operations/project-detail/"
            f"{project_id}"
        ),
    }
    record.update(overrides)
    return record


async def seed_s1_1_rows(database: str) -> dict[str, str]:
    user_id = uuid4()
    company_id = uuid4()
    project_id = uuid4()
    tender_ids = [uuid4(), uuid4()]
    link_ids = [uuid4(), uuid4()]
    document_id = uuid4()
    proposal_id = uuid4()
    analysis_id = uuid4()
    recommendation_id = uuid4()
    connection = await support.database_connection(database)
    try:
        await connection.execute(
            """
            INSERT INTO users (
                id, subscription_tier, is_admin, google_id, email, name,
                approval_status, platform_role
            ) VALUES ($1, 'SCOUT', false, $2, $3, 'S1.2 User', 'approved', 'pilot_user')
            """,
            user_id,
            f"google-{user_id}",
            f"{user_id}@example.test",
        )
        await connection.execute(
            """
            INSERT INTO company_profiles (
                id, user_id, company_name, pilot_status, approval_status
            ) VALUES ($1, $2, 'S1.2 Company', 'active_pilot', 'approved')
            """,
            company_id,
            user_id,
        )
        await connection.execute(
            """
            INSERT INTO projects (
                id, source_system, external_project_id, name, country,
                source_url, raw_provenance, created_at, updated_at
            ) VALUES ($1, 'world_bank', 'P179267', 'Tender-derived name', 'Liberia',
                      NULL, '{"sprint": "1.1"}'::json, NOW(), NOW())
            """,
            project_id,
        )
        for index, tender_id in enumerate(tender_ids, start=1):
            await connection.execute(
                """
                INSERT INTO tenders (
                    id, external_id, source_url, title, budget, currency,
                    status, category, source_system, canonical_source_key,
                    country, project_id, source_metadata_json, scrape_status
                ) VALUES ($1, $2::varchar, $3, $4, 1000, 'USD', 'OPEN', 'World Bank',
                          'world_bank', CONCAT('world_bank:', $2::varchar),
                          'Liberia', 'P179267', $5::json,
                          'success')
                """,
                tender_id,
                f"WB-S12-{index}",
                f"https://example.test/WB-S12-{index}",
                f"Preserved Tender {index}",
                json.dumps(
                    {
                        "project_id": "P179267",
                        "contact_name": "Leader One",
                        "contact_email": "procurement@example.test",
                    }
                ),
            )
            await connection.execute(
                """
                INSERT INTO tender_projects (
                    id, tender_id, project_id, linkage_method,
                    source_value, provenance, created_at
                ) VALUES ($1, $2, $3, 'SOURCE_PROJECT_ID', 'P179267',
                          '{"source_field": "tenders.project_id"}'::json, NOW())
                """,
                link_ids[index - 1],
                tender_id,
                project_id,
            )
        await connection.execute(
            """
            INSERT INTO tender_documents (id, tender_id, file_url, file_type, parsed_text)
            VALUES ($1, $2, '/preserved.pdf', 'pdf', 'preserved text')
            """,
            document_id,
            tender_ids[0],
        )
        await connection.execute(
            """
            INSERT INTO proposals (
                id, user_id, tender_id, status, ai_confidence_score,
                structured_data, margin_percent, include_vat, currency
            ) VALUES ($1, $2, $3, 'DRAFT', 70, '{"preserved": true}'::json,
                      20, true, 'USD')
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
            ) VALUES ($1, $2, 'preserved.pdf', 'preserved-owner', 'preserved',
                      '{"preserved": true}'::jsonb, $3)
            """,
            analysis_id,
            tender_ids[0],
            "b" * 64,
        )
        await connection.execute(
            """
            INSERT INTO tender_recommendations (
                id, tender_id, company_profile_id, match_score,
                strategic_rationale, is_dismissed
            ) VALUES ($1, $2, $3, 90, 'preserved', false)
            """,
            recommendation_id,
            tender_ids[0],
            company_id,
        )
    finally:
        await connection.close()
    return {
        "project_id": str(project_id),
        "tender_ids": ",".join(str(value) for value in tender_ids),
        "link_ids": ",".join(str(value) for value in link_ids),
        "document_id": str(document_id),
        "proposal_id": str(proposal_id),
        "analysis_id": str(analysis_id),
        "recommendation_id": str(recommendation_id),
    }


async def preservation_snapshot(database: str, ids: dict[str, str]) -> dict[str, Any]:
    connection = await support.database_connection(database)
    try:
        project = await connection.fetchrow(
            """
            SELECT id::text, source_system, external_project_id, name, country,
                   source_url, raw_provenance::text, created_at, updated_at
            FROM projects WHERE id = $1::uuid
            """,
            ids["project_id"],
        )
        tender_ids = [UUID(value) for value in ids["tender_ids"].split(",")]
        links = await connection.fetch(
            """
            SELECT id::text, tender_id::text, project_id::text, linkage_method,
                   source_value, provenance::text, created_at
            FROM tender_projects WHERE tender_id = ANY($1::uuid[]) ORDER BY id
            """,
            tender_ids,
        )
        tenders = await connection.fetch(
            """
            SELECT id::text, external_id, status::text, project_id,
                   source_metadata_json::text, created_at
            FROM tenders WHERE id = ANY($1::uuid[]) ORDER BY id
            """,
            tender_ids,
        )
        artifacts = {}
        for table, key in (
            ("tender_documents", "document_id"),
            ("proposals", "proposal_id"),
            ("tender_analyses", "analysis_id"),
            ("tender_recommendations", "recommendation_id"),
        ):
            row = await connection.fetchrow(
                f"SELECT *, xmin::text AS row_version FROM {table} WHERE id = $1::uuid",
                ids[key],
            )
            artifacts[table] = dict(row)
        return {
            "project": tuple(project),
            "links": [tuple(row) for row in links],
            "tenders": [tuple(row) for row in tenders],
            "artifacts": artifacts,
        }
    finally:
        await connection.close()


async def exercise_enrichment_matrix(database: str, project_id: UUID) -> dict[str, Any]:
    engine = create_async_engine(support.target_url(database))
    first_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    second_at = first_at + timedelta(hours=1)
    changed_at = second_at + timedelta(hours=1)
    partial_at = changed_at + timedelta(hours=1)
    second_project_id = uuid4()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            first = normalize_world_bank_project_record(
                "P179267", fixture(), retrieved_at=first_at
            )
            result = await apply_world_bank_project_snapshot(
                db, project_id=project_id, snapshot=first
            )
            assert (result.roles_created, result.roles_updated, result.roles_ended) == (
                2,
                0,
                0,
            )
            await db.commit()

        async with AsyncSession(engine, expire_on_commit=False) as db:
            repeated = normalize_world_bank_project_record(
                "P179267", fixture(), retrieved_at=second_at
            )
            result = await apply_world_bank_project_snapshot(
                db, project_id=project_id, snapshot=repeated
            )
            assert (result.roles_created, result.roles_updated, result.roles_ended) == (
                0,
                2,
                0,
            )
            await db.commit()

        async with AsyncSession(engine, expire_on_commit=False) as db:
            changed = normalize_world_bank_project_record(
                "P179267",
                fixture(teamleadname="New Leader"),
                retrieved_at=changed_at,
            )
            result = await apply_world_bank_project_snapshot(
                db, project_id=project_id, snapshot=changed
            )
            assert (result.roles_created, result.roles_ended) == (1, 2)
            await db.commit()

        async with AsyncSession(engine, expire_on_commit=False) as db:
            partial_record = fixture(projectstatusdisplay="Closed")
            del partial_record["teamleadname"]
            partial = normalize_world_bank_project_record(
                "P179267", partial_record, retrieved_at=partial_at
            )
            result = await apply_world_bank_project_snapshot(
                db, project_id=project_id, snapshot=partial
            )
            assert result.status == "partial"
            assert result.roles_ended == 0
            await db.commit()

        try:
            normalize_world_bank_project_record(
                "P179267",
                fixture(project_id="P123456", id="P123456"),
                retrieved_at=partial_at,
            )
        except WorldBankProjectIdentityMismatch:
            pass
        else:
            raise AssertionError("wrong World Bank project identity was accepted")

        async with AsyncSession(engine, expire_on_commit=False) as db:
            db.add(
                Project(
                    id=second_project_id,
                    source_system="world_bank",
                    external_project_id="P123456",
                    name=None,
                    country=None,
                    source_url=None,
                    enrichment_status="never_attempted",
                )
            )
            await db.commit()
        async with AsyncSession(engine, expire_on_commit=False) as db:
            same_name = normalize_world_bank_project_record(
                "P123456",
                fixture("P123456", teamleadname="New Leader"),
                retrieved_at=partial_at,
            )
            await apply_world_bank_project_snapshot(
                db, project_id=second_project_id, snapshot=same_name
            )
            await db.commit()

        async with AsyncSession(engine, expire_on_commit=False) as db:
            project = await db.get(Project, project_id)
            project.enrichment_status = "never_attempted"
            project.last_enriched_at = None
            project.enrichment_last_attempted_at = None
            claimed = await claim_world_bank_projects_for_enrichment(
                db, now=partial_at + timedelta(hours=1)
            )
            assert claimed == [project_id]
            await db.rollback()
    finally:
        await engine.dispose()

    connection = await support.database_connection(database)
    try:
        project = await connection.fetchrow(
            """
            SELECT name, country, region, project_status, approval_date,
                   closing_date, borrower, implementing_agencies,
                   enrichment_status
            FROM projects WHERE id = $1
            """,
            project_id,
        )
        assert project[0] == "Authoritative Project Name"
        assert project[2] == "Western and Central Africa"
        assert project[3] == "Closed"
        assert project[8] == "partial"
        assignments = await connection.fetch(
            """
            SELECT project_id, display_name, native_role, canonical_role,
                   email, phone, provenance, is_current, ended_at,
                   first_observed_at, last_observed_at
            FROM project_role_assignments ORDER BY project_id, display_name
            """
        )
        first_project_roles = [row for row in assignments if row[0] == project_id]
        assert len(first_project_roles) == 3
        assert sum(bool(row[7]) for row in first_project_roles) == 1
        assert next(row for row in first_project_roles if row[1] == "New Leader")[7]
        assert all(row[4] is None and row[5] is None for row in assignments)
        assert all(row[6] for row in assignments)
        assert sum(1 for row in assignments if row[1] == "New Leader") == 2
        tender_contact = await connection.fetchval(
            """
            SELECT source_metadata_json->>'contact_email' FROM tenders
            WHERE external_id = 'WB-S12-1'
            """
        )
        assert tender_contact == "procurement@example.test"
        assert not any(row[4] == tender_contact for row in assignments)
        return {
            "metadata_enriched": True,
            "role_rows": len(assignments),
            "first_project_history_rows": len(first_project_roles),
            "current_first_project_roles": 1,
            "partial_preserved_current_role": True,
            "wrong_identity_rejected": True,
            "emails_inferred": 0,
            "same_name_cross_project_rows": 2,
            "multiple_tenders_one_enrichment_claim": True,
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
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM project_role_assignments"
        ) == 0
    finally:
        await connection.close()
    await assert_alembic_check(database)
    return {"head": HEAD, "role_rows": 0, "alembic_check": "clean"}


async def existing_scenario(database: str) -> dict[str, Any]:
    await support.raw_baseline(database)
    await asyncio.to_thread(support.alembic, database, "upgrade", S1_1_HEAD)
    ids = await seed_s1_1_rows(database)
    before = await preservation_snapshot(database, ids)
    await asyncio.to_thread(support.alembic, database, "upgrade", "head")
    after = await preservation_snapshot(database, ids)
    assert before == after
    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval(
            "SELECT enrichment_status FROM projects WHERE id = $1::uuid",
            ids["project_id"],
        ) == "never_attempted"
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM project_role_assignments"
        ) == 0
    finally:
        await connection.close()
    matrix = await exercise_enrichment_matrix(database, UUID(ids["project_id"]))
    await assert_alembic_check(database)
    return {
        "from": S1_1_HEAD,
        "to": HEAD,
        "existing_rows_preserved": True,
        "migration_fabricated_roles": 0,
        **matrix,
        "alembic_check": "clean",
    }


async def with_database(
    label: str,
    scenario: Callable[[str], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    database = support.database_name(f"s12_{label}")
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
            results.append({"scenario": label, "status": "failed", "error": repr(exc)})
    leaked = await support.leaked_databases()
    if leaked:
        failures += 1
    print(json.dumps({"results": results, "leaked_databases": leaked, "failures": failures}, indent=2, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
