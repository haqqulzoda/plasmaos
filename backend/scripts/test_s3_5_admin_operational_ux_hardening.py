#!/usr/bin/env python3
"""Disposable PostgreSQL API/data proof for Sprint 3.5."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.deps import require_admin
from app.api.endpoints.admin import get_admin_accounts, get_admin_audit_events
from app.models.all_models import User
from scripts import test_s0_5b4_baseline as support


HEAD = "20260828_0002_s3_4_admin_audit_hardening"


async def bootstrap(database: str) -> None:
    result = await asyncio.to_thread(support.run_bootstrap, database)
    assert result.returncode == 0, result.stderr or result.stdout


async def fresh_scenario(database: str) -> dict[str, object]:
    await bootstrap(database)
    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == HEAD
        assert await connection.fetchval("SELECT COUNT(*) FROM users") == 0
        assert await connection.fetchval("SELECT COUNT(*) FROM admin_activity_events") == 0
    finally:
        await connection.close()
    await asyncio.to_thread(support.alembic, database, "check")
    return {"head": HEAD, "empty_admin_reads": True, "alembic_check": "clean"}


async def seed_user(
    connection,
    label: str,
    *,
    status: str,
    role: str = "pilot_user",
    previous: str | None = None,
) -> UUID:
    user_id = uuid4()
    await connection.execute(
        """
        INSERT INTO users (
            id,google_id,email,name,subscription_tier,is_admin,
            approval_status,platform_role,pre_disabled_approval_status,auth_version
        ) VALUES ($1,$2,$3,$4,'SCOUT',false,$5,$6,$7,4)
        """,
        user_id,
        f"s35-google-{label}-{user_id}",
        f"{label}@s35.invalid",
        f"S3.5 {label}",
        status,
        role,
        previous,
    )
    return user_id


async def seed_existing(database: str) -> dict[str, UUID]:
    connection = await support.database_connection(database)
    try:
        ids = {
            "admin_a": await seed_user(connection, "admin-a", status="approved", role="admin"),
            "admin_b": await seed_user(connection, "admin-b", status="approved", role="admin"),
            "operator": await seed_user(connection, "operator", status="approved", role="operator"),
            "pending": await seed_user(connection, "pending", status="pending"),
            "approved": await seed_user(connection, "approved", status="approved"),
            "rejected": await seed_user(connection, "rejected", status="rejected"),
            "disabled_known": await seed_user(
                connection, "disabled-known", status="disabled", previous="approved"
            ),
            "disabled_unknown": await seed_user(
                connection, "disabled-unknown", status="disabled"
            ),
        }
        company_id, project_id, tender_id = uuid4(), uuid4(), uuid4()
        proposal_id, analysis_id, version_id = uuid4(), uuid4(), uuid4()
        ids.update(
            company=company_id,
            project=project_id,
            tender=tender_id,
            proposal=proposal_id,
            analysis=analysis_id,
            version=version_id,
        )
        await connection.execute(
            """
            INSERT INTO company_profiles (
                id,user_id,company_name,pilot_status,approval_status
            ) VALUES ($1,$2,'S3.5 preserved company','active_pilot','approved')
            """,
            company_id,
            ids["approved"],
        )
        await connection.execute(
            """
            INSERT INTO projects (
                id,source_system,external_project_id,name,country,raw_provenance
            ) VALUES ($1,'world_bank','S35-PROJECT','S3.5 preserved project',
                      'Uzbekistan','{"fixture":true}'::json)
            """,
            project_id,
        )
        await connection.execute(
            """
            INSERT INTO tenders (
                id,external_id,source_system,canonical_source_key,source_url,title,
                budget,currency,status,category,project_id,source_metadata_json
            ) VALUES ($1,'S35-TENDER','world_bank','world_bank:S35-TENDER',
                      'https://example.invalid/s35','S3.5 preserved tender',1000,
                      'USD','OPEN','World Bank','S35-PROJECT','{"fixture":true}'::json)
            """,
            tender_id,
        )
        await connection.execute(
            """
            INSERT INTO proposals (
                id,user_id,tender_id,status,ai_confidence_score,structured_data,
                margin_percent,include_vat,currency
            ) VALUES ($1,$2,$3,'DRAFT',80,'{"fixture":true}'::json,20,true,'USD')
            """,
            proposal_id,
            ids["approved"],
            tender_id,
        )
        await connection.execute(
            """
            INSERT INTO tender_analyses (
                id,tender_id,tender_file_name,user_id,company_profile_id,
                ownership_state,company_name,raw_extracted_text,analysis_json,
                content_hash
            ) VALUES ($1,$2,'s35.pdf',$3,$4,'OWNED','S3.5 preserved company',
                      'preserved text','{"fixture":true}'::jsonb,$5)
            """,
            analysis_id,
            tender_id,
            ids["approved"],
            company_id,
            "a" * 64,
        )
        await connection.execute(
            """
            INSERT INTO analysis_versions (
                id,analysis_id,version_number,origin,status,provenance_snapshot,
                tender_snapshot,company_snapshot,result_snapshot,evidence_snapshot,
                snapshot_completeness,requested_by_user_id
            ) VALUES ($1,$2,1,'RUNTIME_ANALYSIS','COMPLETED','{}'::jsonb,
                      '{}'::jsonb,'{}'::jsonb,'{"fixture":true}'::jsonb,
                      '{}'::jsonb,'COMPLETE',$3)
            """,
            version_id,
            analysis_id,
            ids["approved"],
        )
        legacy_id = uuid4()
        ids["legacy_event"] = legacy_id
        await connection.execute(
            """
            INSERT INTO admin_activity_events (
                id,action,actor_label,target_user_id,target_email,reason,metadata_json,
                created_at
            ) VALUES ($1,'user_approved','legacy',$2,'pending@s35.invalid',
                      'historical','{"legacy":true,"auth_version":9}'::jsonb,
                      NOW() - interval '3 hours')
            """,
            legacy_id,
            ids["pending"],
        )
        events = []
        outcomes = ("SUCCESS", "DENIED", "FAILED")
        actions = ("USER_APPROVED", "USER_REJECTED", "USER_DISABLED", "USER_RESTORED")
        for index in range(105):
            outcome = outcomes[index % len(outcomes)]
            events.append(
                (
                    uuid4(),
                    actions[index % len(actions)],
                    ids["admin_a"],
                    "admin-a@s35.invalid",
                    ids["pending"],
                    outcome,
                    json.dumps({"approval_status": "pending"})
                    if outcome == "SUCCESS"
                    else None,
                    json.dumps({"approval_status": "approved", "credentials_invalidated": True})
                    if outcome == "SUCCESS"
                    else None,
                    None if outcome == "SUCCESS" else "INVALID_LIFECYCLE_TRANSITION",
                    index,
                )
            )
        await connection.executemany(
            """
            INSERT INTO admin_activity_events (
                id,action,actor_user_id,actor_type,actor_email_snapshot,
                actor_role_snapshot,target_user_id,target_email,target_resource_type,
                target_resource_id,outcome,previous_state,new_state,reason_code,
                source,created_at
            ) VALUES ($1,$2,$3,'USER',$4,'admin',$5,'pending@s35.invalid',
                      'USER',$5::uuid::text,$6,$7::jsonb,$8::jsonb,$9,'ADMIN_API',
                      NOW() - ($10 * interval '1 second'))
            """,
            events,
        )
        return ids
    finally:
        await connection.close()


async def data_signature(database: str, ids: dict[str, UUID]) -> tuple[object, ...]:
    connection = await support.database_connection(database)
    try:
        return tuple(
            await connection.fetchrow(
                """
                SELECT
                  (SELECT COUNT(*) FROM users) AS users,
                  (SELECT COUNT(*) FROM company_profiles) AS companies,
                  (SELECT COUNT(*) FROM projects) AS projects,
                  (SELECT COUNT(*) FROM tenders) AS tenders,
                  (SELECT COUNT(*) FROM proposals) AS proposals,
                  (SELECT COUNT(*) FROM tender_analyses) AS analyses,
                  (SELECT COUNT(*) FROM analysis_versions) AS versions,
                  (SELECT approval_status FROM users WHERE id=$1) AS target_status,
                  (SELECT structured_data::text FROM proposals WHERE id=$2) AS proposal
                """,
                ids["pending"],
                ids["proposal"],
            )
        )
    finally:
        await connection.close()


async def expect_admin_denied(user: User) -> None:
    try:
        await require_admin(user)
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError(f"audit authorization unexpectedly allowed {user.email}")


async def existing_scenario(database: str) -> dict[str, object]:
    await bootstrap(database)
    ids = await seed_existing(database)
    before = await data_signature(database, ids)
    engine = create_async_engine(support.target_url(database))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            admin = await session.get(User, ids["admin_a"])
            operator = await session.get(User, ids["operator"])
            assert admin is not None and operator is not None

            page = await get_admin_accounts(
                approval_status=None,
                role=None,
                query=None,
                limit=100,
                offset=0,
                current_user=admin,
                db=session,
            )
            assert page.total == 8 and len(page.items) == 8
            by_email = {item.email: item for item in page.items}
            assert by_email["pending@s35.invalid"].allowed_actions == [
                "approve", "reject", "disable"
            ]
            assert by_email["approved@s35.invalid"].allowed_actions == ["reject", "disable"]
            assert by_email["rejected@s35.invalid"].allowed_actions == ["approve", "disable"]
            assert by_email["disabled-known@s35.invalid"].allowed_actions == ["restore"]
            assert by_email["disabled-known@s35.invalid"].restore_target_status == "approved"
            assert by_email["disabled-unknown@s35.invalid"].restore_target_status == "pending"
            assert by_email["admin-a@s35.invalid"].is_current_actor
            assert "reject" not in by_email["admin-a@s35.invalid"].allowed_actions
            assert "disable" not in by_email["admin-a@s35.invalid"].allowed_actions
            serialized = page.model_dump_json()
            for forbidden in ("auth_version", "google_id", "pre_disabled_approval_status"):
                assert forbidden not in serialized

            operator_page = await get_admin_accounts(
                approval_status="disabled",
                role=None,
                query=None,
                limit=25,
                offset=0,
                current_user=operator,
                db=session,
            )
            assert operator_page.total == 2
            assert all(not item.allowed_actions for item in operator_page.items)
            role_page = await get_admin_accounts(
                approval_status=None,
                role="admin",
                query=None,
                limit=25,
                offset=0,
                current_user=admin,
                db=session,
            )
            assert role_page.total == 2

            audit_one = await get_admin_audit_events(
                actor_user_id=None,
                target_user_id=None,
                action=None,
                outcome=None,
                limit=100,
                offset=0,
                current_user=admin,
                db=session,
            )
            audit_two = await get_admin_audit_events(
                actor_user_id=None,
                target_user_id=None,
                action=None,
                outcome=None,
                limit=100,
                offset=100,
                current_user=admin,
                db=session,
            )
            assert audit_one.total == audit_two.total == 106
            assert len(audit_one.items) == 100 and len(audit_two.items) == 6
            event_ids = [item.id for item in audit_one.items + audit_two.items]
            assert len(event_ids) == len(set(event_ids)) == 106
            legacy = next(item for item in audit_two.items if item.id == ids["legacy_event"])
            assert legacy.outcome is None and legacy.source is None
            assert legacy.previous_state is None and legacy.new_state is None
            assert legacy.metadata is None
            safe_payload = (audit_one.model_dump_json() + audit_two.model_dump_json()).casefold()
            for forbidden in ("auth_version", "access_token", "refresh_token", "google_id"):
                assert forbidden not in safe_payload

            success_page = await get_admin_audit_events(
                actor_user_id=ids["admin_a"],
                target_user_id=ids["pending"],
                action="user_approved",
                outcome="success",
                limit=100,
                offset=0,
                current_user=admin,
                db=session,
            )
            assert success_page.total > 0
            successful_actions = {
                item.action
                for item in audit_one.items + audit_two.items
                if item.outcome == "SUCCESS"
            }
            assert {
                "USER_APPROVED",
                "USER_REJECTED",
                "USER_DISABLED",
                "USER_RESTORED",
            } <= successful_actions

            await expect_admin_denied(operator)
            for key in ("approved", "pending", "rejected", "disabled_known"):
                denied = await session.get(User, ids[key])
                assert denied is not None
                await expect_admin_denied(denied)
    finally:
        await engine.dispose()

    after = await data_signature(database, ids)
    assert before == after
    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == HEAD
    finally:
        await connection.close()
    await asyncio.to_thread(support.alembic, database, "check")
    return {
        "head": HEAD,
        "representative_rows": True,
        "account_matrix_and_filters": True,
        "operator_read_only": True,
        "effective_admin_audit_authorization": True,
        "audit_events": 106,
        "stable_pages": [100, 6],
        "legacy_safe": True,
        "sensitive_payload_scan": "clean",
        "unrelated_data_unchanged": True,
        "alembic_check": "clean",
    }


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
    for label, scenario in (("s35_fresh", fresh_scenario), ("s35_existing", existing_scenario)):
        try:
            results.append(await run_database(label, scenario))
        except Exception as exc:
            failures += 1
            results.append({"scenario": label, "status": "failed", "error": repr(exc)})
    print(json.dumps({"results": results, "failures": failures}, indent=2, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
