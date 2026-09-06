#!/usr/bin/env python3
"""Real PostgreSQL concurrency and rollback proof for Sprint 3.3."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.account_lifecycle import InvalidAccountLifecycleTransition
from app.models.all_models import User
from app.services.admin_survivability import (
    AdminActorAuthorityLost,
    AdminSurvivabilityViolation,
    apply_locked_user_lifecycle_mutation,
    count_effective_admins,
)
from scripts import test_s0_5b4_baseline as support


HEAD = "20260828_0003_s4_1_tender_engagement_foundation"


async def seed_user(connection, label: str, state: str, role: str, is_admin: bool) -> UUID:
    user_id = uuid4()
    await connection.execute(
        """
        INSERT INTO users (
            id, google_id, email, name, subscription_tier, is_admin,
            approval_status, platform_role, auth_version,
            pre_disabled_approval_status, disabled_at, rejected_at
        ) VALUES (
            $1, $2, $3, $4, 'SCOUT', $5, $6::varchar, $7::varchar, 10,
            CASE WHEN $6::varchar = 'disabled' THEN 'approved' ELSE NULL END,
            CASE WHEN $6::varchar = 'disabled' THEN now() ELSE NULL END,
            CASE WHEN $6::varchar = 'rejected' THEN now() ELSE NULL END
        )
        """,
        user_id,
        f"s33-google-{label}",
        f"{label}@s33.invalid",
        label,
        is_admin,
        state,
        role,
    )
    return user_id


async def set_effective_group(connection, user_ids: dict[str, UUID], labels: tuple[str, ...]) -> None:
    await connection.execute(
        """
        UPDATE users
        SET approval_status = 'pending', platform_role = 'pilot_user',
            is_admin = false, pre_disabled_approval_status = NULL,
            disabled_at = NULL, rejected_at = NULL
        WHERE email LIKE '%@s33.invalid'
        """
    )
    for label in labels:
        await connection.execute(
            """
            UPDATE users
            SET approval_status = 'approved', platform_role = 'admin', is_admin = false
            WHERE id = $1
            """,
            user_ids[label],
        )


async def mutate(sessions, actor: UUID, target: UUID, action: str, gate: asyncio.Event):
    await gate.wait()
    async with sessions() as session:
        try:
            mutation = await apply_locked_user_lifecycle_mutation(
                session,
                actor_user_id=actor,
                target_user_id=target,
                action=action,  # type: ignore[arg-type]
                reason="Sprint 3.3 concurrency proof",
            )
            await session.commit()
            return {"status": "committed", "target_state": mutation.target.approval_status}
        except (AdminActorAuthorityLost, AdminSurvivabilityViolation, InvalidAccountLifecycleTransition) as exc:
            await session.rollback()
            return {"status": "denied", "reason": type(exc).__name__}


async def effective_count(sessions) -> int:
    async with sessions() as session:
        return await count_effective_admins(session)


async def scenario(database: str) -> dict[str, object]:
    bootstrap = await asyncio.to_thread(support.run_bootstrap, database)
    assert bootstrap.returncode == 0, bootstrap.stderr or bootstrap.stdout
    connection = await support.database_connection(database)
    try:
        users: dict[str, UUID] = {}
        for label in ("a", "b", "c", "d"):
            users[label] = await seed_user(connection, label, "approved", "admin", False)
        users["disabled_admin"] = await seed_user(connection, "disabled-admin", "disabled", "admin", False)
        users["rejected_admin"] = await seed_user(connection, "rejected-admin", "rejected", "admin", False)
        users["pending_admin"] = await seed_user(connection, "pending-admin", "pending", "admin", False)
        users["legacy_admin"] = await seed_user(connection, "legacy-admin", "approved", "pilot_user", True)
        users["operator"] = await seed_user(connection, "operator", "approved", "operator", False)
        users["allowlisted"] = await seed_user(connection, "allowlisted", "approved", "pilot_user", False)
        users["ordinary"] = await seed_user(connection, "ordinary", "approved", "pilot_user", False)

        profile = uuid4()
        await connection.execute(
            "INSERT INTO company_profiles (id,user_id,company_name,approval_status,pilot_status) VALUES ($1,$2,'S33 Seed','approved','scoped_pilot')",
            profile,
            users["ordinary"],
        )
        await connection.execute(
            "INSERT INTO projects (id,source_system,external_project_id,name) VALUES ($1,'world_bank','S33-PROJECT','S33 Project')",
            uuid4(),
        )
        tender = uuid4()
        await connection.execute(
            """
            INSERT INTO tenders (
                id, external_id, source_system, canonical_source_key, source_url,
                title, budget, currency, status, category, project_id
            ) VALUES (
                $1,'S33-TENDER','world_bank','world_bank:S33-TENDER',
                'https://example.invalid/s33','S33 Tender',1,'USD','OPEN','Other','S33-PROJECT'
            )
            """,
            tender,
        )
        await connection.execute(
            "INSERT INTO proposals (id,user_id,tender_id,status,ai_confidence_score,margin_percent,include_vat,currency) VALUES ($1,$2,$3,'DRAFT',0,20,true,'USD')",
            uuid4(), users["ordinary"], tender,
        )
        analysis = uuid4()
        await connection.execute(
            """
            INSERT INTO tender_analyses (
                id,tender_id,tender_file_name,user_id,company_profile_id,
                ownership_state,company_name,raw_extracted_text,analysis_json
            ) VALUES ($1,$2,'s33.pdf',$3,$4,'OWNED','S33 Seed','seed','{}'::jsonb)
            """,
            analysis, tender, users["ordinary"], profile,
        )
        await connection.execute(
            """
            INSERT INTO analysis_versions (
                id,analysis_id,version_number,origin,status,provenance_snapshot,
                tender_snapshot,company_snapshot,result_snapshot,evidence_snapshot,
                snapshot_completeness,requested_by_user_id
            ) VALUES (
                $1,$2,1,'RUNTIME_ANALYSIS','COMPLETED','{}'::jsonb,'{}'::jsonb,
                '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'COMPLETE',$3
            )
            """,
            uuid4(), analysis, users["ordinary"],
        )
    finally:
        await connection.close()

    engine = create_async_engine(support.target_url(database), pool_size=8, max_overflow=4)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        setup = await support.database_connection(database)
        try:
            await set_effective_group(setup, users, ("a", "b"))
        finally:
            await setup.close()
        gate = asyncio.Event()
        tasks = (
            asyncio.create_task(mutate(sessions, users["a"], users["b"], "disable", gate)),
            asyncio.create_task(mutate(sessions, users["b"], users["a"], "reject", gate)),
        )
        gate.set()
        two_admin = await asyncio.gather(*tasks)
        assert await effective_count(sessions) == 1
        assert sum(item["status"] == "committed" for item in two_admin) == 1

        setup = await support.database_connection(database)
        try:
            await set_effective_group(setup, users, ("a", "b", "c"))
        finally:
            await setup.close()
        gate = asyncio.Event()
        tasks = (
            asyncio.create_task(mutate(sessions, users["a"], users["b"], "disable", gate)),
            asyncio.create_task(mutate(sessions, users["b"], users["c"], "reject", gate)),
            asyncio.create_task(mutate(sessions, users["c"], users["a"], "disable", gate)),
        )
        gate.set()
        three_admin = await asyncio.gather(*tasks)
        three_count = await effective_count(sessions)
        assert three_count >= 1

        setup = await support.database_connection(database)
        try:
            await set_effective_group(setup, users, ("a", "b", "c"))
            before_version = await setup.fetchval("SELECT auth_version FROM users WHERE id=$1", users["c"])
        finally:
            await setup.close()
        gate = asyncio.Event()
        tasks = (
            asyncio.create_task(mutate(sessions, users["a"], users["c"], "disable", gate)),
            asyncio.create_task(mutate(sessions, users["b"], users["c"], "disable", gate)),
        )
        gate.set()
        same_target = await asyncio.gather(*tasks)
        verify = await support.database_connection(database)
        try:
            target_row = await verify.fetchrow(
                "SELECT approval_status,pre_disabled_approval_status,auth_version FROM users WHERE id=$1",
                users["c"],
            )
        finally:
            await verify.close()
        assert sum(item["status"] == "committed" for item in same_target) == 1
        assert target_row["approval_status"] == "disabled"
        assert target_row["pre_disabled_approval_status"] == "approved"
        assert target_row["auth_version"] == before_version + 1

        setup = await support.database_connection(database)
        try:
            await set_effective_group(setup, users, ("a", "b"))
            rollback_before = await setup.fetchrow(
                "SELECT approval_status,pre_disabled_approval_status,auth_version FROM users WHERE id=$1",
                users["b"],
            )
        finally:
            await setup.close()
        async with sessions() as session:
            await apply_locked_user_lifecycle_mutation(
                session,
                actor_user_id=users["a"],
                target_user_id=users["b"],
                action="disable",
            )
            await session.rollback()
        verify = await support.database_connection(database)
        try:
            rollback_after = await verify.fetchrow(
                "SELECT approval_status,pre_disabled_approval_status,auth_version FROM users WHERE id=$1",
                users["b"],
            )
        finally:
            await verify.close()
        assert tuple(rollback_before.values()) == tuple(rollback_after.values())
        gate = asyncio.Event(); gate.set()
        retry = await mutate(sessions, users["a"], users["b"], "disable", gate)
        assert retry["status"] == "committed"

        async with sessions() as session:
            restored = await apply_locked_user_lifecycle_mutation(
                session,
                actor_user_id=users["a"],
                target_user_id=users["b"],
                action="restore",
            )
            await session.commit()
            assert restored.target.approval_status == "approved"

        setup = await support.database_connection(database)
        try:
            await setup.execute(
                "UPDATE users SET approval_status='disabled',platform_role='admin',is_admin=false,pre_disabled_approval_status=NULL,disabled_at=now() WHERE id=$1",
                users["d"],
            )
        finally:
            await setup.close()
        async with sessions() as session:
            unknown = await apply_locked_user_lifecycle_mutation(
                session,
                actor_user_id=users["a"],
                target_user_id=users["d"],
                action="restore",
            )
            await session.commit()
            assert unknown.target.approval_status == "pending"

        async with sessions() as session:
            self_before = await session.get(User, users["a"])
            assert self_before is not None
            version = self_before.auth_version
            try:
                await apply_locked_user_lifecycle_mutation(
                    session,
                    actor_user_id=users["a"],
                    target_user_id=users["a"],
                    action="reject",
                )
            except AdminSurvivabilityViolation:
                await session.rollback()
            else:
                raise AssertionError("self-reject unexpectedly succeeded")
        verify = await support.database_connection(database)
        try:
            assert await verify.fetchval("SELECT auth_version FROM users WHERE id=$1", users["a"]) == version
            head = await verify.fetchval("SELECT version_num FROM alembic_version")
            business_counts = {
                table: await verify.fetchval(f"SELECT COUNT(*) FROM {table}")
                for table in ("company_profiles", "projects", "tenders", "proposals", "tender_analyses", "analysis_versions")
            }
        finally:
            await verify.close()
        assert head == HEAD
        await asyncio.to_thread(support.alembic, database, "check")
        return {
            "head": head,
            "two_admin_race": two_admin,
            "three_admin_race": {"results": three_admin, "effective_admins": three_count},
            "same_target_race": {"results": same_target, "auth_version_increment": 1},
            "rollback_then_retry": True,
            "restore": "approved",
            "unknown_provenance_restore": "pending",
            "self_reject_denied": True,
            "business_counts": business_counts,
            "alembic_check": "clean",
        }
    finally:
        await engine.dispose()


async def main() -> int:
    database = support.database_name("s33_survivability")
    await support.create_database(database)
    try:
        result = await scenario(database)
        print(json.dumps({"status": "passed", **result}, indent=2, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": repr(exc)}, indent=2))
        return 1
    finally:
        await support.drop_database(database)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
