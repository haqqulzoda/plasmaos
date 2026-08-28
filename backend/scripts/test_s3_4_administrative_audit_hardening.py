#!/usr/bin/env python3
"""Disposable PostgreSQL transaction and concurrency proof for Sprint 3.4."""

from __future__ import annotations

import asyncio
import argparse
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import asyncpg
from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.endpoints.admin import _apply_user_lifecycle_action, get_admin_audit_events
from app.api.endpoints.auth import GoogleAuthRequest, google_auth_bridge
from app.cli.admin_management import promote_admin
from app.models.all_models import User
from scripts import test_s0_5b4_baseline as support


HEAD = "20260828_0002_s3_4_admin_audit_hardening"
S31 = "20260828_0001_s3_1_admin_account_lifecycle"


async def seed_user(
    connection: asyncpg.Connection,
    label: str,
    *,
    role: str = "admin",
    state: str = "approved",
    email: str | None = None,
    google_id: str | None = None,
) -> UUID:
    user_id = uuid4()
    await connection.execute(
        """
        INSERT INTO users (
            id, google_id, email, name, subscription_tier, is_admin,
            approval_status, platform_role, auth_version
        ) VALUES ($1,$2,$3,$4,'SCOUT',false,$5,$6,3)
        """,
        user_id,
        google_id or f"s34-google-{label}-{user_id}",
        email or f"{label}-{user_id}@s34.invalid",
        label,
        state,
        role,
    )
    return user_id


async def invoke(
    sessions,
    *,
    actor_id: UUID,
    target_id: UUID,
    action: str,
    gate: asyncio.Event | None = None,
) -> str:
    if gate is not None:
        await gate.wait()
    async with sessions() as session:
        actor = await session.get(User, actor_id)
        assert actor is not None
        try:
            await _apply_user_lifecycle_action(
                db=session,
                current_user=actor,
                user_id=target_id,
                action=action,  # type: ignore[arg-type]
                audit_reason=f"Sprint 3.4 {action} proof.",
            )
            return "SUCCESS"
        except HTTPException:
            return "DENIED"


async def canonical_scenario(database: str) -> dict[str, object]:
    bootstrap = await asyncio.to_thread(support.run_bootstrap, database)
    assert bootstrap.returncode == 0, bootstrap.stderr or bootstrap.stdout
    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval("SELECT COUNT(*) FROM admin_activity_events") == 0
        actor = await seed_user(connection, "actor")
        peer = await seed_user(connection, "peer")
        target = await seed_user(connection, "target", role="pilot_user")
        race_a = await seed_user(connection, "race-a")
        race_b = await seed_user(connection, "race-b")
        same_a = await seed_user(connection, "same-a")
        same_b = await seed_user(connection, "same-b")
        same_target = await seed_user(connection, "same-target")
        allowlist_target = await seed_user(
            connection,
            "allowlist-target",
            role="pilot_user",
            state="pending",
            email="allowlist-admin@s34.invalid",
            google_id="s34-allowlist-google",
        )
        repair_target = await seed_user(
            connection,
            "repair-target",
            role="pilot_user",
            state="pending",
            email="repair-admin@s34.invalid",
            google_id="s34-repair-google",
        )
    finally:
        await connection.close()

    engine = create_async_engine(support.target_url(database), pool_size=10, max_overflow=4)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    import app.db.session as session_module

    original_factory = session_module.AsyncSessionLocal
    session_module.AsyncSessionLocal = sessions
    try:
        assert await invoke(
            sessions, actor_id=actor, target_id=target, action="disable"
        ) == "SUCCESS"
        verify = await support.database_connection(database)
        try:
            success = await verify.fetchrow(
                """
                SELECT action,outcome,source,actor_email_snapshot,
                       actor_role_snapshot,target_email,previous_state,new_state
                FROM admin_activity_events
                WHERE target_user_id=$1 ORDER BY created_at,id
                """,
                target,
            )
            assert success["action"] == "USER_DISABLED"
            assert success["outcome"] == "SUCCESS"
            assert success["source"] == "ADMIN_API"
            assert success["actor_email_snapshot"]
            assert success["actor_role_snapshot"] == "admin"
            assert "auth_version" not in success["previous_state"]
            assert "auth_version" not in success["new_state"]
        finally:
            await verify.close()

        with (
            patch.dict(
                os.environ,
                {"PLASMA_ADMIN_EMAILS": "allowlist-admin@s34.invalid"},
                clear=False,
            ),
            patch("app.api.endpoints.auth.create_access_token", return_value="test-token"),
        ):
            for _ in range(2):
                async with sessions() as session:
                    await google_auth_bridge(
                        GoogleAuthRequest(
                            google_id="s34-allowlist-google",
                            email="allowlist-admin@s34.invalid",
                            name="Allowlist Admin",
                        ),
                        Response(),
                        session,
                    )
        verify = await support.database_connection(database)
        try:
            assert await verify.fetchval(
                """
                SELECT COUNT(*) FROM admin_activity_events
                WHERE target_user_id=$1 AND action='ADMIN_GRANTED'
                  AND outcome='SUCCESS' AND source='GOOGLE_ALLOWLIST'
                  AND actor_type='SYSTEM' AND actor_user_id IS NULL
                """,
                allowlist_target,
            ) == 1
        finally:
            await verify.close()

        with (
            patch.dict(
                os.environ,
                {"PLASMA_ADMIN_EMAILS": "repair-admin@s34.invalid"},
                clear=False,
            ),
            patch("app.cli.admin_management._print_payload"),
        ):
            result = await promote_admin(
                argparse.Namespace(
                    email="repair-admin@s34.invalid",
                    google_id="s34-repair-google",
                    actor_email="claimed-human@s34.invalid",
                    actor_label=None,
                    reason="Controlled Sprint 3.4 repair fixture.",
                )
            )
            assert result == 0
        verify = await support.database_connection(database)
        try:
            repair = await verify.fetchrow(
                """
                SELECT action,outcome,source,actor_type,actor_user_id
                FROM admin_activity_events WHERE target_user_id=$1
                """,
                repair_target,
            )
            assert tuple(repair.values()) == (
                "ADMIN_REPAIR_PROMOTION",
                "SUCCESS",
                "ADMIN_REPAIR_COMMAND",
                "SERVER_COMMAND",
                None,
            )
        finally:
            await verify.close()

        assert await invoke(
            sessions, actor_id=actor, target_id=actor, action="disable"
        ) == "DENIED"
        verify = await support.database_connection(database)
        try:
            self_rows = await verify.fetch(
                """
                SELECT outcome,reason_code FROM admin_activity_events
                WHERE actor_user_id=$1 AND target_user_id=$1 AND action='USER_DISABLED'
                """,
                actor,
            )
            assert [(row["outcome"], row["reason_code"]) for row in self_rows] == [
                ("DENIED", "SELF_ACTION_PROHIBITED")
            ]
            assert await verify.fetchval(
                "SELECT approval_status FROM users WHERE id=$1", actor
            ) == "approved"
        finally:
            await verify.close()

        async with sessions() as session:
            loaded_actor = await session.get(User, actor)
            assert loaded_actor is not None
            # The canonical SUCCESS row is already added and flushed when this
            # deliberately injected commit failure occurs.
            session.commit = AsyncMock(side_effect=RuntimeError("forced commit failure"))
            try:
                await _apply_user_lifecycle_action(
                    db=session,
                    current_user=loaded_actor,
                    user_id=target,
                    action="restore",
                    audit_reason="forced rollback",
                )
            except RuntimeError:
                pass
            else:
                raise AssertionError("forced transaction failure unexpectedly committed")
        verify = await support.database_connection(database)
        try:
            assert await verify.fetchval(
                "SELECT approval_status FROM users WHERE id=$1", target
            ) == "disabled"
            assert await verify.fetchval(
                """
                SELECT COUNT(*) FROM admin_activity_events
                WHERE target_user_id=$1 AND action='USER_RESTORED'
                  AND outcome='FAILED' AND reason_code='TRANSACTION_FAILED'
                """,
                target,
            ) == 1
            assert await verify.fetchval(
                """
                SELECT COUNT(*) FROM admin_activity_events
                WHERE target_user_id=$1 AND action='USER_RESTORED'
                  AND outcome='SUCCESS'
                """,
                target,
            ) == 0
        finally:
            await verify.close()

        gate = asyncio.Event()
        tasks = (
            asyncio.create_task(
                invoke(sessions, actor_id=race_a, target_id=race_b, action="disable", gate=gate)
            ),
            asyncio.create_task(
                invoke(sessions, actor_id=race_b, target_id=race_a, action="reject", gate=gate)
            ),
        )
        gate.set()
        last_admin_race = await asyncio.gather(*tasks)
        assert sorted(last_admin_race) == ["DENIED", "SUCCESS"]
        verify = await support.database_connection(database)
        try:
            race_events = await verify.fetchval(
                """
                SELECT COUNT(*) FROM admin_activity_events
                WHERE actor_user_id IN ($1,$2) AND target_user_id IN ($1,$2)
                  AND outcome IN ('SUCCESS','DENIED')
                """,
                race_a,
                race_b,
            )
            assert race_events == 2
        finally:
            await verify.close()

        gate = asyncio.Event()
        tasks = (
            asyncio.create_task(
                invoke(sessions, actor_id=same_a, target_id=same_target, action="disable", gate=gate)
            ),
            asyncio.create_task(
                invoke(sessions, actor_id=same_b, target_id=same_target, action="disable", gate=gate)
            ),
        )
        gate.set()
        same_target_race = await asyncio.gather(*tasks)
        assert sorted(same_target_race) == ["DENIED", "SUCCESS"]
        verify = await support.database_connection(database)
        try:
            outcomes = await verify.fetch(
                """
                SELECT outcome,COUNT(*) AS rows FROM admin_activity_events
                WHERE target_user_id=$1 AND action='USER_DISABLED'
                GROUP BY outcome ORDER BY outcome
                """,
                same_target,
            )
            assert {row["outcome"]: row["rows"] for row in outcomes} == {
                "DENIED": 1,
                "SUCCESS": 1,
            }
            head = await verify.fetchval("SELECT version_num FROM alembic_version")
        finally:
            await verify.close()

        async with sessions() as session:
            current_admin = await session.get(User, actor)
            assert current_admin is not None
            page = await get_admin_audit_events(
                actor_user_id=actor,
                target_user_id=target,
                action="user_disabled",
                outcome="success",
                limit=10,
                offset=0,
                current_user=current_admin,
                db=session,
            )
            assert page.total == 1 and len(page.items) == 1
            assert page.items[0].target_user_id == target

        snapshot_before = page.items[0].target_email_snapshot
        verify = await support.database_connection(database)
        try:
            await verify.execute(
                "UPDATE users SET email='changed-target@s34.invalid' WHERE id=$1",
                target,
            )
            assert await verify.fetchval(
                """
                SELECT target_email FROM admin_activity_events
                WHERE target_user_id=$1 AND action='USER_DISABLED' AND outcome='SUCCESS'
                """,
                target,
            ) == snapshot_before
        finally:
            await verify.close()
        assert head == HEAD
        await asyncio.to_thread(support.alembic, database, "check")
        return {
            "head": head,
            "success_event": True,
            "self_denial": True,
            "failed_event_and_rollback": True,
            "allowlist_grant_exactly_once": True,
            "repair_actor_truthful": True,
            "last_admin_race": last_admin_race,
            "same_target_race": same_target_race,
            "filtered_read_and_snapshot": True,
            "alembic_check": "clean",
        }
    finally:
        session_module.AsyncSessionLocal = original_factory
        await engine.dispose()


async def legacy_scenario(database: str) -> dict[str, object]:
    await support.raw_baseline(database)
    await asyncio.to_thread(support.alembic, database, "upgrade", S31)
    connection = await support.database_connection(database)
    try:
        actor = await seed_user(connection, "legacy-actor")
        target = await seed_user(connection, "legacy-target", role="pilot_user")
        event_id = uuid4()
        await connection.execute(
            """
            INSERT INTO admin_activity_events (
                id,action,actor_user_id,actor_label,target_user_id,target_email,
                reason,metadata_json
            ) VALUES ($1,'user_approved',$2,'legacy',$3,'legacy-target@s34.invalid',
                      'historical','{"legacy":true}'::jsonb)
            """,
            event_id,
            actor,
            target,
        )
    finally:
        await connection.close()
    await asyncio.to_thread(support.alembic, database, "upgrade", "head")
    connection = await support.database_connection(database)
    try:
        row = await connection.fetchrow(
            """
            SELECT action,outcome,source,previous_state,new_state,metadata_json
            FROM admin_activity_events WHERE id=$1
            """,
            event_id,
        )
        assert row["action"] == "user_approved"
        assert row["outcome"] is None and row["source"] is None
        assert row["previous_state"] is None and row["new_state"] is None
        legacy_metadata = row["metadata_json"]
        if isinstance(legacy_metadata, str):
            legacy_metadata = json.loads(legacy_metadata)
        assert legacy_metadata == {"legacy": True}
        for statement in (
            "UPDATE admin_activity_events SET reason='tampered' WHERE id=$1",
            "DELETE FROM admin_activity_events WHERE id=$1",
        ):
            try:
                await connection.execute(statement, event_id)
            except asyncpg.PostgresError as exc:
                assert "append-only" in str(exc)
            else:
                raise AssertionError("append-only trigger allowed mutation")
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM admin_activity_events WHERE id=$1", event_id
        ) == 1
    finally:
        await connection.close()
    await asyncio.to_thread(support.alembic, database, "downgrade", S31)
    await asyncio.to_thread(support.alembic, database, "upgrade", "head")
    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM admin_activity_events WHERE id=$1", event_id
        ) == 1
    finally:
        await connection.close()
    return {"legacy_preserved": True, "append_only": True, "round_trip": True}


async def run_database(label: str, scenario) -> dict[str, object]:
    database = support.database_name(label)
    await support.create_database(database)
    try:
        return {"scenario": label, "status": "passed", **await scenario(database)}
    finally:
        await support.drop_database(database)


async def main() -> int:
    results: list[dict[str, object]] = []
    failures = 0
    for label, scenario in (
        ("s34_canonical", canonical_scenario),
        ("s34_legacy", legacy_scenario),
    ):
        try:
            results.append(await run_database(label, scenario))
        except Exception as exc:
            failures += 1
            results.append({"scenario": label, "status": "failed", "error": repr(exc)})
    print(json.dumps({"results": results, "failures": failures}, indent=2, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
