"""Permanent W2 migration, tenancy, lifecycle, and compatibility proofs."""

from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import require_approved_user
from app.models.audit import TenderAnalysis
from app.models.base import MembershipRole, MembershipState, TenderEngagementOrigin, TenderEngagementStatus
from app.models.tenancy import Membership, Organization, OrganizationPursuit, PursuitLifecycleEvent
from app.services.analysis_aggregates import get_owned_analysis_parent_for_tender
from app.services.memberships import LastOwnerError, MembershipError, MembershipPermissionError, activate_invitation, change_membership_role, invite_member, revoke_membership
from app.services.organization_context import OrganizationAccessDeniedError, OrganizationContextRequiredError, resolve_organization_context
from app.services.pursuits import PursuitOwnershipError, PursuitTransitionError, assign_pursuit_owner, get_or_create_source_pursuit, get_owned_pursuit, get_owned_pursuit_by_legacy_id, reopen_pursuit, transition_pursuit
from app.services.tender_engagements import get_tender_engagement
from scripts import test_s0_5b4_baseline as support


W1_HEAD = "20260912_0001_s10_5_communications"
W2_HEAD = "20260925_0002_w2_organization_pursuit"
CURRENT_HEAD = "20261005_0001_d2_05_eoi_drafts"


def deterministic_uuid(label: str) -> UUID:
    return UUID(bytes=hashlib.md5(label.encode(), usedforsecurity=False).digest())


async def _digest(connection, table: str, row_id: UUID) -> str:
    return await connection.fetchval(
        f"SELECT md5(to_jsonb(t)::text) FROM {table} t WHERE id=$1", row_id
    )


async def _seed_w1(database: str) -> dict[str, UUID]:
    ids = {name: uuid4() for name in (
        "user_a", "user_b", "member", "member_two", "multi", "profile_a", "profile_b",
        "tender", "project", "tender_project", "current_leader", "historical_leader",
        "engagement", "proposal", "analysis", "analysis_version",
    )}
    connection = await support.database_connection(database)
    try:
        for name in ("user_a", "user_b", "member", "member_two", "multi"):
            await connection.execute(
                """
                INSERT INTO users(
                    id,google_id,email,name,subscription_tier,is_admin,
                    approval_status,platform_role,auth_version
                ) VALUES ($1,$2,$3,$4,'SCOUT',false,'approved','pilot_user',0)
                """,
                ids[name], f"w2-{name}-{ids[name]}", f"{name}@same-domain.invalid", name,
            )
        for user_key, profile_key in (("user_a", "profile_a"), ("user_b", "profile_b")):
            await connection.execute(
                """
                INSERT INTO company_profiles(
                    id,user_id,company_name,inn,pilot_status,approval_status
                ) VALUES ($1,$2,'Same Name Company','SAME-TEXT','active_pilot','approved')
                """,
                ids[profile_key], ids[user_key],
            )
        await connection.execute(
            """
            INSERT INTO projects(
                id,source_system,external_project_id,name,country,source_url,
                raw_provenance,project_status,enrichment_status
            ) VALUES (
                $1,'world_bank','P-W2-FOUNDATION','W2 Preserved Project','Uzbekistan',
                'https://projects.worldbank.org/P-W2-FOUNDATION',
                '{"source":"world_bank","native_teamleadname":"Literal Leader"}'::json,
                'active','successful'
            )
            """,
            ids["project"],
        )
        await connection.execute(
            """
            INSERT INTO tenders(
                id,external_id,source_system,canonical_source_key,source_url,title,
                description,budget,currency,deadline,status,category,project_id,
                source_metadata_json
            ) VALUES (
                $1,'WB-W2-1','world_bank','world_bank:WB-W2-1',
                'https://example.invalid/w2-source','W2 Source Tender','source truth',
                125000,'USD','2026-12-31T00:00:00Z','OPEN','Services','P-W2-FOUNDATION',
                '{"contact_name":"Procurement Contact","teamleadname":"Literal Leader"}'::json
            )
            """,
            ids["tender"],
        )
        await connection.execute(
            """
            INSERT INTO tender_projects(
                id,tender_id,project_id,linkage_method,source_value,provenance
            ) VALUES ($1,$2,$3,'SOURCE_PROJECT_ID','P-W2-FOUNDATION','{"source_field":"project_id"}'::json)
            """,
            ids["tender_project"], ids["tender"], ids["project"],
        )
        await connection.execute(
            """
            INSERT INTO project_role_assignments(
                id,project_id,source_system,assignment_key,display_name,native_role,
                canonical_role,source_url,provenance,is_current,first_observed_at,last_observed_at
            ) VALUES (
                $1,$2,'world_bank','current-leader','Literal Leader','Team Leader',
                'TASK_TEAM_LEADER','https://example.invalid/project/current',
                '{"native_field":"teamleadname"}'::json,true,
                '2026-01-01T00:00:00Z','2026-09-01T00:00:00Z'
            )
            """,
            ids["current_leader"], ids["project"],
        )
        await connection.execute(
            """
            INSERT INTO project_role_assignments(
                id,project_id,source_system,assignment_key,display_name,native_role,
                canonical_role,source_url,provenance,is_current,first_observed_at,
                last_observed_at,ended_at
            ) VALUES (
                $1,$2,'world_bank','historical-leader','Historical Leader','Task Team Leader',
                'TASK_TEAM_LEADER','https://example.invalid/project/history',
                '{"native_field":"teamleadname"}'::json,false,
                '2025-01-01T00:00:00Z','2025-12-31T00:00:00Z','2025-12-31T00:00:00Z'
            )
            """,
            ids["historical_leader"], ids["project"],
        )
        await connection.execute(
            """
            INSERT INTO tender_engagements(
                id,user_id,company_profile_id,tender_id,status,origin,
                created_at,updated_at,status_changed_at
            ) VALUES (
                $1,$2,$3,$4,'PREPARING','BID_PREPARATION',
                '2026-08-01T00:00:00Z','2026-08-02T00:00:00Z','2026-08-03T00:00:00Z'
            )
            """,
            ids["engagement"], ids["user_a"], ids["profile_a"], ids["tender"],
        )
        await connection.execute(
            """
            INSERT INTO proposals(
                id,user_id,tender_id,status,ai_confidence_score,structured_data,
                margin_percent,include_vat,currency
            ) VALUES ($1,$2,$3,'DRAFT',77,'{"manual_price":null}'::json,18.5,true,'USD')
            """,
            ids["proposal"], ids["user_a"], ids["tender"],
        )
        await connection.execute(
            """
            INSERT INTO tender_analyses(
                id,tender_id,tender_file_name,user_id,company_profile_id,ownership_state,
                company_name,raw_extracted_text,analysis_json,content_hash
            ) VALUES (
                $1,$2,'w2-source.pdf',$3,$4,'OWNED','Same Name Company',
                'immutable source snapshot','{"preserved":true}'::jsonb,$5
            )
            """,
            ids["analysis"], ids["tender"], ids["user_a"], ids["profile_a"], "a" * 64,
        )
        await connection.execute(
            """
            INSERT INTO analysis_versions(
                id,analysis_id,version_number,origin,status,analysis_language,
                provenance_snapshot,tender_snapshot,company_snapshot,result_snapshot,
                evidence_snapshot,snapshot_completeness,requested_by_user_id
            ) VALUES (
                $1,$2,1,'RUNTIME_ANALYSIS','COMPLETED','en','{}'::jsonb,
                '{"source":"world_bank"}'::jsonb,'{"company":"snapshot"}'::jsonb,
                '{"result":"preserved"}'::jsonb,'{"evidence":"preserved"}'::jsonb,
                'COMPLETE',$3
            )
            """,
            ids["analysis_version"], ids["analysis"], ids["user_a"],
        )
    finally:
        await connection.close()
    return ids


async def _scenario(database: str) -> None:
    await support.raw_baseline(database)
    await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
    ids = await _seed_w1(database)

    preserved_tables = {
        "tenders": ids["tender"],
        "projects": ids["project"],
        "tender_projects": ids["tender_project"],
        "project_role_assignments/current": ids["current_leader"],
        "project_role_assignments/history": ids["historical_leader"],
        "tender_engagements": ids["engagement"],
        "proposals": ids["proposal"],
        "tender_analyses": ids["analysis"],
        "analysis_versions": ids["analysis_version"],
    }

    async def snapshots() -> dict[str, str]:
        connection = await support.database_connection(database)
        try:
            return {
                label: await _digest(connection, label.split("/", 1)[0], row_id)
                for label, row_id in preserved_tables.items()
            }
        finally:
            await connection.close()

    before = await snapshots()
    await asyncio.to_thread(support.alembic, database, "upgrade", "head")
    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == CURRENT_HEAD
        organizations = await connection.fetch(
            "SELECT id,legacy_company_profile_id,display_name FROM organizations ORDER BY legacy_company_profile_id"
        )
        assert len(organizations) == 2
        assert len({row["id"] for row in organizations}) == 2
        for row in organizations:
            assert row["id"] == deterministic_uuid(
                f"plasma:w2:organization:{row['legacy_company_profile_id']}"
            )
        assert await connection.fetchval(
            "SELECT count(*) FROM memberships WHERE role='OWNER' AND state='ACTIVE'"
        ) == 2
        pursuit = await connection.fetchrow(
            "SELECT * FROM organization_pursuits WHERE legacy_engagement_id=$1",
            ids["engagement"],
        )
        assert pursuit is not None
        assert pursuit["id"] == deterministic_uuid(f"plasma:w2:pursuit:{ids['engagement']}")
        assert pursuit["id"] != ids["engagement"]
        assert pursuit["stage"] == "PREPARING"
        assert pursuit["created_at"].isoformat().startswith("2026-08-01")
        assert pursuit["updated_at"].isoformat().startswith("2026-08-02")
        assert pursuit["stage_changed_at"].isoformat().startswith("2026-08-03")
        assert await connection.fetchval("SELECT count(*) FROM tenancy_backfill_exceptions") == 0
        assert await connection.fetchval(
            "SELECT count(*) FROM pursuit_lifecycle_events WHERE pursuit_id=$1 AND action='LEGACY_BACKFILL'",
            pursuit["id"],
        ) == 1
        first_pursuit_id = pursuit["id"]
    finally:
        await connection.close()
    assert await snapshots() == before

    await asyncio.to_thread(support.alembic, database, "downgrade", W1_HEAD)
    assert await snapshots() == before
    await asyncio.to_thread(support.alembic, database, "upgrade", "head")
    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval(
            "SELECT id FROM organization_pursuits WHERE legacy_engagement_id=$1", ids["engagement"]
        ) == first_pursuit_id
        organization_a = await connection.fetchval(
            "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"]
        )
        organization_b = await connection.fetchval(
            "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_b"]
        )
        owner_a = await connection.fetchval(
            "SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2",
            organization_a, ids["user_a"],
        )
        owner_b = await connection.fetchval(
            "SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2",
            organization_b, ids["user_b"],
        )
        second_tender = uuid4()
        await connection.execute(
            """
            INSERT INTO tenders(
                id,external_id,source_system,canonical_source_key,source_url,title,
                budget,currency,status,category
            ) VALUES ($1,$2,'world_bank',$3,'https://example.invalid/w2-second',
                      'Second source tender',1000,'USD','OPEN','Services')
            """,
            second_tender, f"WB-W2-{second_tender}", f"world_bank:w2:{second_tender}",
        )
    finally:
        await connection.close()

    engine = create_async_engine(support.target_url(database), pool_size=12)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session, session.begin():
            invited = await invite_member(
                session, organization_id=organization_a,
                actor_membership_id=owner_a, user_id=ids["member"],
            )
            invited_id = invited.id
            assert invited.state == MembershipState.INVITED
        async with sessions() as session, session.begin():
            active_member = await activate_invitation(
                session, membership_id=invited_id, user_id=ids["member"]
            )
            assert active_member.id == invited_id
            assert active_member.state == MembershipState.ACTIVE
        async with sessions() as session:
            with pytest.raises(MembershipPermissionError):
                async with session.begin():
                    await invite_member(
                        session, organization_id=organization_a,
                        actor_membership_id=invited_id, user_id=ids["member_two"],
                    )
        async with sessions() as session, session.begin():
            await change_membership_role(
                session, organization_id=organization_a,
                actor_membership_id=owner_a, membership_id=invited_id,
                role=MembershipRole.OWNER,
            )

        async def demote(actor: UUID, target: UUID):
            async with sessions() as session, session.begin():
                return await change_membership_role(
                    session, organization_id=organization_a,
                    actor_membership_id=actor, membership_id=target,
                    role=MembershipRole.MEMBER,
                )

        outcomes = await asyncio.gather(
            demote(owner_a, invited_id), demote(invited_id, owner_a),
            return_exceptions=True,
        )
        assert sum(isinstance(value, Membership) for value in outcomes) == 1
        assert sum(isinstance(value, MembershipError) for value in outcomes) == 1
        async with sessions() as session:
            active_owner_ids = list((await session.execute(
                select(Membership.id).where(
                    Membership.organization_id == organization_a,
                    Membership.state == MembershipState.ACTIVE,
                    Membership.role == MembershipRole.OWNER,
                )
            )).scalars())
            assert len(active_owner_ids) == 1
        current_owner = active_owner_ids[0]
        demoted_owner = invited_id if current_owner == owner_a else owner_a
        async with sessions() as session, session.begin():
            await change_membership_role(
                session, organization_id=organization_a,
                actor_membership_id=current_owner, membership_id=demoted_owner,
                role=MembershipRole.OWNER,
            )

        async def create_same_source():
            async with sessions() as session, session.begin():
                return await get_or_create_source_pursuit(
                    session, organization_id=organization_a,
                    actor_user_id=ids["user_a"], actor_membership_id=owner_a,
                    tender_id=second_tender, stage=TenderEngagementStatus.SAVED,
                    legacy_origin=TenderEngagementOrigin.MANUAL_SAVE,
                )

        created = await asyncio.gather(create_same_source(), create_same_source())
        assert sorted(result.created for result in created) == [False, True]
        assert len({result.pursuit.id for result in created}) == 1
        runtime_pursuit_id = created[0].pursuit.id
        runtime_legacy_id = created[0].pursuit.legacy_engagement_id
        assert runtime_legacy_id is not None and runtime_legacy_id != runtime_pursuit_id

        async def transition(expected, destination):
            async with sessions() as session, session.begin():
                return await transition_pursuit(
                    session, pursuit_id=runtime_pursuit_id,
                    organization_id=organization_a, actor_user_id=ids["user_a"],
                    actor_membership_id=owner_a, stage=destination,
                    expected_stage=expected,
                )

        await transition(TenderEngagementStatus.SAVED, TenderEngagementStatus.EVALUATING)
        await transition(TenderEngagementStatus.EVALUATING, TenderEngagementStatus.PREPARING)
        await transition(TenderEngagementStatus.PREPARING, TenderEngagementStatus.SUBMITTED)
        await transition(TenderEngagementStatus.SUBMITTED, TenderEngagementStatus.WON)
        async with sessions() as session:
            with pytest.raises(PursuitTransitionError):
                async with session.begin():
                    await transition_pursuit(
                        session, pursuit_id=runtime_pursuit_id,
                        organization_id=organization_a, actor_user_id=ids["user_a"],
                        actor_membership_id=owner_a, stage=TenderEngagementStatus.SAVED,
                        expected_stage=TenderEngagementStatus.WON,
                    )
        async with sessions() as session, session.begin():
            reopened = await reopen_pursuit(
                session, pursuit_id=runtime_pursuit_id,
                organization_id=organization_a, actor_user_id=ids["user_a"],
                actor_membership_id=owner_a,
                destination=TenderEngagementStatus.EVALUATING,
                expected_stage=TenderEngagementStatus.WON,
                reason="new procurement cycle",
            )
            assert reopened.id == runtime_pursuit_id

        async with sessions() as session:
            before_reads = (
                await session.scalar(select(func.count(OrganizationPursuit.id))),
                await session.scalar(select(func.count(PursuitLifecycleEvent.id))),
            )
            assert await get_owned_pursuit(
                session, pursuit_id=runtime_pursuit_id, organization_id=organization_b
            ) is None
            assert await get_owned_pursuit_by_legacy_id(
                session, legacy_engagement_id=runtime_legacy_id, organization_id=organization_b
            ) is None
            legacy_view = await get_tender_engagement(
                session, user_id=ids["user_a"], company_profile_id=ids["profile_a"],
                tender_id=second_tender,
            )
            assert legacy_view is not None
            assert legacy_view.id == runtime_legacy_id
            assert legacy_view.pursuit_id == runtime_pursuit_id
            after_reads = (
                await session.scalar(select(func.count(OrganizationPursuit.id))),
                await session.scalar(select(func.count(PursuitLifecycleEvent.id))),
            )
            assert after_reads == before_reads
        async with sessions() as session:
            with pytest.raises(PursuitOwnershipError):
                async with session.begin():
                    await assign_pursuit_owner(
                        session, pursuit_id=runtime_pursuit_id,
                        organization_id=organization_a,
                        actor_membership_id=owner_a,
                        owner_membership_id=owner_b,
                    )

        async with sessions() as session, session.begin():
            member_two = await invite_member(
                session, organization_id=organization_a,
                actor_membership_id=owner_a, user_id=ids["member_two"],
            )
            member_two_id = member_two.id
        async with sessions() as session, session.begin():
            await activate_invitation(session, membership_id=member_two_id, user_id=ids["member_two"])
            await assign_pursuit_owner(
                session, pursuit_id=runtime_pursuit_id,
                organization_id=organization_a, actor_membership_id=owner_a,
                owner_membership_id=member_two_id,
            )
        async with sessions() as session, session.begin():
            await revoke_membership(
                session, organization_id=organization_a,
                actor_membership_id=owner_a, membership_id=member_two_id,
            )
        async with sessions() as session:
            assert (await session.get(OrganizationPursuit, runtime_pursuit_id)).owner_membership_id is None
            assert (await session.get(Membership, member_two_id)).state == MembershipState.REVOKED
            with pytest.raises(OrganizationAccessDeniedError):
                await resolve_organization_context(session, user_id=ids["member_two"])
        async with sessions() as session, session.begin():
            reinvited = await invite_member(
                session, organization_id=organization_a,
                actor_membership_id=owner_a, user_id=ids["member_two"],
            )
            assert reinvited.id == member_two_id
            assert reinvited.state == MembershipState.INVITED

        multi_memberships: list[UUID] = []
        for organization_id, actor_id in ((organization_a, owner_a), (organization_b, owner_b)):
            async with sessions() as session, session.begin():
                invitation = await invite_member(
                    session, organization_id=organization_id,
                    actor_membership_id=actor_id, user_id=ids["multi"],
                )
                multi_memberships.append(invitation.id)
            async with sessions() as session, session.begin():
                await activate_invitation(
                    session, membership_id=multi_memberships[-1], user_id=ids["multi"]
                )
        async with sessions() as session:
            with pytest.raises(OrganizationContextRequiredError):
                await resolve_organization_context(session, user_id=ids["multi"])
            for organization_id in (organization_a, organization_b):
                context = await resolve_organization_context(
                    session, user_id=ids["multi"], organization_id=organization_id
                )
                assert context.organization.id == organization_id

        async with sessions() as session, session.begin():
            legacy_pursuit = await session.scalar(
                select(OrganizationPursuit).where(
                    OrganizationPursuit.legacy_engagement_id == ids["engagement"]
                )
            )
            await assign_pursuit_owner(
                session, pursuit_id=legacy_pursuit.id,
                organization_id=organization_a, actor_membership_id=owner_a,
                owner_membership_id=multi_memberships[0],
            )
        async with sessions() as session, session.begin():
            await revoke_membership(
                session, organization_id=organization_a,
                actor_membership_id=owner_a, membership_id=multi_memberships[0],
                transfer_to_membership_id=owner_a,
            )
        async with sessions() as session:
            assert (await session.get(OrganizationPursuit, legacy_pursuit.id)).owner_membership_id == owner_a
            assert (await session.get(Membership, multi_memberships[0])).state == MembershipState.REVOKED
            assert (await session.get(Membership, multi_memberships[1])).state == MembershipState.ACTIVE
            context = await resolve_organization_context(session, user_id=ids["multi"])
            assert context.organization.id == organization_b

        connection = await support.database_connection(database)
        try:
            await connection.execute("UPDATE users SET approval_status='disabled' WHERE id=$1", ids["member"])
            assert await connection.fetchval(
                "SELECT state::text FROM memberships WHERE id=$1", invited_id
            ) == "ACTIVE"
        finally:
            await connection.close()
        with pytest.raises(HTTPException) as disabled:
            await require_approved_user(SimpleNamespace(
                id=ids["member"], email="member@same-domain.invalid",
                approval_status="disabled", platform_role="pilot_user", is_admin=False,
            ))
        assert disabled.value.status_code == 403
        connection = await support.database_connection(database)
        try:
            await connection.execute("UPDATE users SET approval_status='approved' WHERE id=$1", ids["member"])
            assert await connection.fetchval(
                "SELECT state::text FROM memberships WHERE id=$1", invited_id
            ) == "ACTIVE"
        finally:
            await connection.close()

        async with sessions() as session:
            analysis = await get_owned_analysis_parent_for_tender(
                session, user_id=ids["user_a"], company_profile_id=ids["profile_a"],
                tender_id=ids["tender"],
            )
            assert analysis is not None and analysis.id == ids["analysis"]
        async with sessions() as session, session.begin():
            await revoke_membership(
                session, organization_id=organization_a,
                actor_membership_id=invited_id, membership_id=owner_a,
            )
        async with sessions() as session:
            assert await get_owned_analysis_parent_for_tender(
                session, user_id=ids["user_a"], company_profile_id=ids["profile_a"],
                tender_id=ids["tender"],
            ) is None
        async with sessions() as session:
            with pytest.raises(LastOwnerError):
                async with session.begin():
                    await revoke_membership(
                        session, organization_id=organization_a,
                        actor_membership_id=invited_id, membership_id=invited_id,
                    )

        assert await snapshots() == before
        check = await asyncio.to_thread(support.alembic, database, "check", success=False)
        assert check.returncode == 0, check.stderr or check.stdout
        assert "No new upgrade operations detected" in check.stdout + check.stderr
    finally:
        await engine.dispose()


def test_w2_foundation_against_disposable_postgresql() -> None:
    async def run() -> None:
        assert support.settings.POSTGRES_SERVER in {"localhost", "127.0.0.1", "::1"}
        database = support.database_name("w2_foundation")
        await support.create_database(database)
        try:
            await _scenario(database)
        finally:
            await support.drop_database(database)

    asyncio.run(run())


def test_w2_has_two_additive_revisions_and_no_destructive_legacy_ddl() -> None:
    migrations = [
        support.BACKEND_DIR / "alembic/versions/20260925_0001_w2_organization_membership.py",
        support.BACKEND_DIR / "alembic/versions/20260925_0002_w2_organization_pursuit.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in migrations)
    for table in (
        "company_profiles", "tender_engagements", "tenders", "projects",
        "proposals", "tender_analyses", "analysis_versions",
    ):
        assert f'op.drop_table("{table}")' not in combined
        assert f'DELETE FROM {table.upper()}' not in combined.upper()
    assert "INSERT INTO organization_pursuits" in combined
    assert "legacy_engagement_id" in combined
    assert "LEGACY_BACKFILL" in combined


def test_w2_revisions_do_not_implement_the_w3_private_document_boundary() -> None:
    migrations = [
        support.BACKEND_DIR / "alembic/versions/20260925_0001_w2_organization_membership.py",
        support.BACKEND_DIR / "alembic/versions/20260925_0002_w2_organization_pursuit.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in migrations)
    assert "private_documents" not in combined
    assert "private_document_versions" not in combined
    assert "organization_pursuits" in combined
