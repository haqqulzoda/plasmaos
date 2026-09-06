#!/usr/bin/env python3
"""Disposable PostgreSQL 16 proof for Sprint 4.1 tender engagements."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.base import TenderEngagementOrigin, TenderEngagementStatus
from app.services.tender_engagements import (
    TenderEngagementOwnershipError,
    TenderEngagementTenderNotFoundError,
    TenderEngagementTransitionError,
    correct_tender_engagement_status,
    dismiss,
    get_or_create_tender_engagement,
    get_tender_engagement,
    mark_lost,
    mark_submitted,
    mark_won,
    prepare,
)
from scripts import test_s0_5b4_baseline as support


HEAD = "20260828_0003_s4_1_tender_engagement_foundation"
PREVIOUS_HEAD = "20260828_0002_s3_4_admin_audit_hardening"
PRESERVED_TABLES = (
    "users",
    "company_profiles",
    "tenders",
    "proposals",
    "tender_analyses",
    "analysis_versions",
    "projects",
    "admin_activity_events",
)


async def seed_owner(
    connection: asyncpg.Connection,
    label: str,
    *,
    company_name: str,
) -> tuple[UUID, UUID]:
    user_id = uuid4()
    profile_id = uuid4()
    await connection.execute(
        """
        INSERT INTO users (
            id, google_id, email, name, subscription_tier, is_admin,
            approval_status, platform_role, auth_version
        ) VALUES ($1, $2, $3, $4, 'SCOUT', false, 'approved', 'pilot_user', 0)
        """,
        user_id,
        f"s41-google-{label}-{user_id}",
        f"{label}-{user_id}@s41.invalid",
        label,
    )
    await connection.execute(
        """
        INSERT INTO company_profiles (
            id, user_id, company_name, pilot_status, approval_status
        ) VALUES ($1, $2, $3, 'active_pilot', 'approved')
        """,
        profile_id,
        user_id,
        company_name,
    )
    return user_id, profile_id


async def seed_tender(connection: asyncpg.Connection, label: str) -> UUID:
    tender_id = uuid4()
    await connection.execute(
        """
        INSERT INTO tenders (
            id, external_id, source_system, canonical_source_key, source_url,
            title, budget, currency, status, category
        ) VALUES ($1, $2, 'uzex', $3, $4, $5, 1000, 'UZS', 'OPEN', 'Other')
        """,
        tender_id,
        f"S41-{label}-{tender_id}",
        f"uzex:s41:{label}:{tender_id}",
        "https://example.invalid/s41",
        f"S4.1 {label}",
    )
    return tender_id


async def engagement_count(connection: asyncpg.Connection) -> int:
    return int(await connection.fetchval("SELECT COUNT(*) FROM tender_engagements"))


async def fresh_and_concurrency_scenario(database: str) -> dict[str, Any]:
    bootstrap = await asyncio.to_thread(support.run_bootstrap, database)
    assert bootstrap.returncode == 0, bootstrap.stderr or bootstrap.stdout
    connection = await support.database_connection(database)
    try:
        assert int(await connection.fetchval("SHOW server_version_num")) // 10000 == 16
        assert await engagement_count(connection) == 0
        user_a, profile_a = await seed_owner(
            connection, "owner-a", company_name="Acme Engineering"
        )
        user_b, profile_b = await seed_owner(
            connection, "owner-b", company_name="Acme Engineering"
        )
        tender_id = await seed_tender(connection, "shared")
    finally:
        await connection.close()

    engine = create_async_engine(support.target_url(database), pool_size=6)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    scope_a = {
        "user_id": user_a,
        "company_profile_id": profile_a,
        "tender_id": tender_id,
    }
    scope_b = {
        "user_id": user_b,
        "company_profile_id": profile_b,
        "tender_id": tender_id,
    }

    async def concurrent_create():
        async with sessions() as session:
            async with session.begin():
                return await get_or_create_tender_engagement(
                    session,
                    status=TenderEngagementStatus.PREPARING,
                    origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
                    **scope_a,
                )

    first, second = await asyncio.gather(concurrent_create(), concurrent_create())
    assert sorted((first.created, second.created)) == [False, True]
    assert first.engagement.id == second.engagement.id
    engagement_a_id = first.engagement.id

    async with sessions() as session:
        async with session.begin():
            owner_b = await get_or_create_tender_engagement(
                session,
                status=TenderEngagementStatus.SAVED,
                origin=TenderEngagementOrigin.MANUAL_SAVE,
                **scope_b,
            )
            assert owner_b.created
            assert owner_b.engagement.id != engagement_a_id

    async with sessions() as session:
        async with session.begin():
            try:
                await get_or_create_tender_engagement(
                    session,
                    user_id=user_a,
                    company_profile_id=profile_b,
                    tender_id=tender_id,
                    status=TenderEngagementStatus.SAVED,
                    origin=TenderEngagementOrigin.MANUAL_SAVE,
                )
            except TenderEngagementOwnershipError:
                pass
            else:
                raise AssertionError("invalid user/profile pairing was accepted")
            try:
                await get_or_create_tender_engagement(
                    session,
                    user_id=user_a,
                    company_profile_id=profile_a,
                    tender_id=uuid4(),
                    status=TenderEngagementStatus.SAVED,
                    origin=TenderEngagementOrigin.MANUAL_SAVE,
                )
            except TenderEngagementTenderNotFoundError:
                pass
            else:
                raise AssertionError("missing tender was accepted")

    # Existing business artifacts are independent and survive dismissal.
    connection = await support.database_connection(database)
    try:
        proposal_id = uuid4()
        analysis_id = uuid4()
        version_id = uuid4()
        project_id = uuid4()
        admin_event_id = uuid4()
        await connection.execute(
            """
            INSERT INTO proposals (
                id, user_id, tender_id, status, ai_confidence_score,
                structured_data, margin_percent, include_vat, currency
            ) VALUES ($1,$2,$3,'COMPLETED',80,'{}'::json,20,true,'UZS')
            """,
            proposal_id,
            user_a,
            tender_id,
        )
        await connection.execute(
            """
            INSERT INTO tender_analyses (
                id, tender_id, tender_file_name, user_id, company_profile_id,
                ownership_state, company_name, raw_extracted_text,
                analysis_json, content_hash
            ) VALUES ($1,$2,'s41.pdf',$3,$4,'OWNED',$5,'text','{}'::jsonb,$6)
            """,
            analysis_id,
            tender_id,
            user_a,
            profile_a,
            "display snapshot only",
            "a" * 64,
        )
        await connection.execute(
            """
            INSERT INTO analysis_versions (
                id, analysis_id, version_number, origin, status,
                provenance_snapshot, tender_snapshot, company_snapshot,
                result_snapshot, evidence_snapshot, snapshot_completeness,
                requested_by_user_id
            ) VALUES (
                $1,$2,1,'RUNTIME_ANALYSIS','COMPLETED','{}'::jsonb,'{}'::jsonb,
                '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'PARTIAL',$3
            )
            """,
            version_id,
            analysis_id,
            user_a,
        )
        await connection.execute(
            """
            INSERT INTO projects (id, source_system, external_project_id)
            VALUES ($1,'world_bank',$2)
            """,
            project_id,
            f"P{str(project_id.int)[-6:]}",
        )
        await connection.execute(
            """
            INSERT INTO admin_activity_events (
                id, action, actor_user_id, target_user_id, target_email,
                actor_type, outcome, source
            ) VALUES ($1,'USER_APPROVED',$2,$2,$3,'USER','SUCCESS','ADMIN_API')
            """,
            admin_event_id,
            user_a,
            f"owner-a-{user_a}@s41.invalid",
        )
        artifact_counts = {
            table: int(await connection.fetchval(f"SELECT COUNT(*) FROM {table}"))
            for table in (
                "proposals",
                "tender_analyses",
                "analysis_versions",
                "projects",
                "admin_activity_events",
                "tenders",
            )
        }
    finally:
        await connection.close()

    async with sessions() as session:
        async with session.begin():
            dismissed = await dismiss(session, **scope_a)
            assert dismissed.id == engagement_a_id
            assert dismissed.status == TenderEngagementStatus.DISMISSED
    async with sessions() as session:
        async with session.begin():
            resumed = await prepare(session, **scope_a)
            assert resumed.id == engagement_a_id
            assert resumed.status == TenderEngagementStatus.PREPARING
    async with sessions() as session:
        async with session.begin():
            submitted = await mark_submitted(session, **scope_a)
            submitted_changed_at = submitted.status_changed_at
            assert submitted.status == TenderEngagementStatus.SUBMITTED

    connection = await support.database_connection(database)
    try:
        await connection.execute(
            "UPDATE tenders SET status='CLOSED' WHERE id=$1", tender_id
        )
        current_status = await connection.fetchval(
            "SELECT status::text FROM tender_engagements WHERE id=$1",
            engagement_a_id,
        )
        assert current_status == "SUBMITTED"
        after_counts = {
            table: int(await connection.fetchval(f"SELECT COUNT(*) FROM {table}"))
            for table in artifact_counts
        }
        assert after_counts == artifact_counts
    finally:
        await connection.close()

    async with sessions() as session:
        async with session.begin():
            corrected = await correct_tender_engagement_status(
                session,
                status=TenderEngagementStatus.PREPARING,
                **scope_a,
            )
            assert corrected.status_changed_at >= submitted_changed_at

    async def competing_status(command):
        async with sessions() as session:
            try:
                async with session.begin():
                    engagement = await command(session, **scope_a)
                    return ("ok", engagement.status.value)
            except TenderEngagementTransitionError:
                return ("conflict", None)

    status_results = await asyncio.gather(
        competing_status(mark_submitted),
        competing_status(dismiss),
    )
    assert sorted(result[0] for result in status_results) == ["conflict", "ok"]
    async with sessions() as session:
        final = await get_tender_engagement(session, **scope_a)
        assert final is not None
        assert final.status.value == next(
            result[1] for result in status_results if result[0] == "ok"
        )

    # Move deterministically to an outcome, then prove source changes cannot
    # infer a different outcome and only the explicit correction can do so.
    async with sessions() as session:
        async with session.begin():
            current = await get_tender_engagement(session, **scope_a)
            assert current is not None
            if current.status == TenderEngagementStatus.DISMISSED:
                await prepare(session, **scope_a)
            else:
                await correct_tender_engagement_status(
                    session,
                    status=TenderEngagementStatus.PREPARING,
                    **scope_a,
                )
    async with sessions() as session:
        async with session.begin():
            await mark_submitted(session, **scope_a)
            await mark_won(session, **scope_a)
    connection = await support.database_connection(database)
    try:
        await connection.execute(
            "UPDATE tenders SET status='CANCELLED' WHERE id=$1", tender_id
        )
        assert await connection.fetchval(
            "SELECT status::text FROM tender_engagements WHERE id=$1",
            engagement_a_id,
        ) == "WON"
    finally:
        await connection.close()
    async with sessions() as session:
        async with session.begin():
            corrected = await correct_tender_engagement_status(
                session,
                status=TenderEngagementStatus.LOST,
                **scope_a,
            )
            assert corrected.status == TenderEngagementStatus.LOST

    # A quarantined analysis for a third scope does not create engagement.
    connection = await support.database_connection(database)
    try:
        before = await engagement_count(connection)
        other_tender = await seed_tender(connection, "analysis-only")
        await connection.execute(
            """
            INSERT INTO tender_analyses (
                id, tender_id, tender_file_name, ownership_state, company_name,
                raw_extracted_text, analysis_json
            ) VALUES ($1,$2,'legacy.pdf','QUARANTINED_LEGACY','legacy','text','{}'::jsonb)
            """,
            uuid4(),
            other_tender,
        )
        assert await engagement_count(connection) == before
        assert await connection.fetchval(
            """
            SELECT COUNT(*) FROM tender_engagements
            WHERE user_id=$1 AND company_profile_id=$2 AND tender_id=$3
            """,
            user_a,
            profile_a,
            tender_id,
        ) == 1
        assert await connection.fetchval(
            """
            SELECT COUNT(*) FROM tender_engagements
            WHERE tender_id=$1
            """,
            tender_id,
        ) == 2
    finally:
        await connection.close()

    check = await asyncio.to_thread(
        support.alembic, database, "check", success=False
    )
    assert check.returncode == 0, check.stderr or check.stdout
    await engine.dispose()
    return {
        "postgres_major": 16,
        "concurrent_create_rows": 1,
        "same_name_tenant_rows": 2,
        "concurrent_status_results": status_results,
        "dismissal_preserved_artifact_counts": True,
        "source_status_separation": True,
        "alembic_check": "clean",
    }


async def existing_upgrade_scenario(database: str) -> dict[str, Any]:
    await support.raw_baseline(database)
    await asyncio.to_thread(support.alembic, database, "upgrade", PREVIOUS_HEAD)
    connection = await support.database_connection(database)
    try:
        user_a, profile_a = await seed_owner(
            connection, "legacy-a", company_name="Acme Engineering"
        )
        user_b, _profile_b = await seed_owner(
            connection, "legacy-b", company_name="Acme Engineering"
        )
        tender_id = await seed_tender(connection, "legacy")
        for user_id in (user_a, user_b):
            await connection.execute(
                """
                INSERT INTO proposals (
                    id, user_id, tender_id, status, ai_confidence_score,
                    structured_data, margin_percent, include_vat, currency
                ) VALUES ($1,$2,$3,'DRAFT',0,'{}'::json,20,true,'UZS')
                """,
                uuid4(),
                user_id,
                tender_id,
            )
        analysis_id = uuid4()
        await connection.execute(
            """
            INSERT INTO tender_analyses (
                id, tender_id, tender_file_name, user_id, company_profile_id,
                ownership_state, company_name, raw_extracted_text,
                analysis_json, content_hash
            ) VALUES ($1,$2,'legacy.pdf',$3,$4,'OWNED','snapshot','text','{}'::jsonb,$5)
            """,
            analysis_id,
            tender_id,
            user_a,
            profile_a,
            "b" * 64,
        )
        await connection.execute(
            """
            INSERT INTO analysis_versions (
                id, analysis_id, version_number, origin, status,
                provenance_snapshot, tender_snapshot, company_snapshot,
                result_snapshot, evidence_snapshot, snapshot_completeness
            ) VALUES (
                $1,$2,1,'RUNTIME_ANALYSIS','COMPLETED','{}'::jsonb,'{}'::jsonb,
                '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'PARTIAL'
            )
            """,
            uuid4(),
            analysis_id,
        )
        await connection.execute(
            """
            INSERT INTO projects (id, source_system, external_project_id)
            VALUES ($1,'world_bank',$2)
            """,
            uuid4(),
            f"P{str(uuid4().int)[-6:]}",
        )
        await connection.execute(
            """
            INSERT INTO admin_activity_events (
                id, action, actor_user_id, target_user_id, target_email,
                actor_type, outcome, source
            ) VALUES ($1,'USER_APPROVED',$2,$2,$3,'USER','SUCCESS','ADMIN_API')
            """,
            uuid4(),
            user_a,
            f"legacy-a-{user_a}@s41.invalid",
        )
        before = {
            table: int(await connection.fetchval(f"SELECT COUNT(*) FROM {table}"))
            for table in PRESERVED_TABLES
        }
        duplicate_proposals_supported = bool(
            await connection.fetchval(
                """
                SELECT NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conrelid='proposals'::regclass
                      AND conname='uq_proposals_user_tender'
                )
                """
            )
        )
    finally:
        await connection.close()

    await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
    connection = await support.database_connection(database)
    try:
        after = {
            table: int(await connection.fetchval(f"SELECT COUNT(*) FROM {table}"))
            for table in PRESERVED_TABLES
        }
        assert after == before
        assert await engagement_count(connection) == 0
        revision = await connection.fetchval("SELECT version_num FROM alembic_version")
        assert revision == HEAD
    finally:
        await connection.close()

    preflight = subprocess.run(
        [
            sys.executable,
            "scripts/run_s0_3_schema_data_preflight.py",
            "--compact",
        ],
        cwd=BACKEND_DIR,
        env=support.environment(database),
        text=True,
        capture_output=True,
        check=False,
    )
    assert preflight.returncode == 0, preflight.stderr or preflight.stdout
    report = json.loads(preflight.stdout.splitlines()[-1])
    engagement_report = report["tender_engagements"]["data"]
    assert engagement_report["total_tender_engagements"] == 0
    assert engagement_report["legacy_proposal_candidates"]["total_proposals"] == 2
    assert (
        engagement_report["legacy_proposal_candidates"][
            "created_by_explicit_user_action"
        ]
        is None
    )
    return {
        "revision": HEAD,
        "business_counts_preserved": before == after,
        "engagement_backfill_rows": 0,
        "legacy_proposals": 2,
        "duplicate_proposals_supported_by_current_schema": (
            duplicate_proposals_supported
        ),
        "preflight": "clean",
    }


async def main() -> int:
    databases = {
        "fresh": support.database_name("s41_fresh"),
        "existing": support.database_name("s41_existing"),
    }
    for database in databases.values():
        await support.create_database(database)
    try:
        result = {
            "fresh": await fresh_and_concurrency_scenario(databases["fresh"]),
            "existing": await existing_upgrade_scenario(databases["existing"]),
        }
        print(json.dumps({"status": "ok", **result}, sort_keys=True))
        return 0
    finally:
        for database in databases.values():
            await support.drop_database(database)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
