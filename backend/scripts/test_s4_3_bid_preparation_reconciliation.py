#!/usr/bin/env python3
"""Disposable PostgreSQL proof for Sprint 4.3 Bid Preparation semantics."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.base import TenderEngagementStatus
from app.services.bid_preparation import (
    BidPreparationNotFoundError,
    prepare_bid,
)
from scripts import test_s0_5b4_baseline as support


HEAD = "20260828_0003_s4_1_tender_engagement_foundation"


async def seed_user(
    connection: asyncpg.Connection,
    label: str,
    *,
    with_profile: bool = True,
) -> tuple[UUID, UUID | None]:
    user_id = uuid4()
    await connection.execute(
        """
        INSERT INTO users (
            id, google_id, email, name, subscription_tier, is_admin,
            approval_status, platform_role, auth_version
        ) VALUES ($1,$2,$3,$4,'SCOUT',false,'approved','pilot_user',0)
        """,
        user_id,
        f"s43-{label}-{user_id}",
        f"{label}-{user_id}@s43.invalid",
        label,
    )
    if not with_profile:
        return user_id, None
    profile_id = uuid4()
    await connection.execute(
        """
        INSERT INTO company_profiles (
            id,user_id,company_name,pilot_status,approval_status
        ) VALUES ($1,$2,'Same Name Company','active_pilot','approved')
        """,
        profile_id,
        user_id,
    )
    return user_id, profile_id


async def seed_tender(
    connection: asyncpg.Connection,
    label: str,
    *,
    status: str = "OPEN",
) -> UUID:
    tender_id = uuid4()
    await connection.execute(
        """
        INSERT INTO tenders (
            id,external_id,source_system,canonical_source_key,source_url,
            title,budget,currency,status,category
        ) VALUES ($1,$2,'uzex',$3,'https://example.invalid/s43',$4,1000,'USD',$5,'Other')
        """,
        tender_id,
        f"S43-{label}-{tender_id}",
        f"uzex:s43:{label}:{tender_id}",
        f"Sprint 4.3 {label}",
        status,
    )
    return tender_id


async def seed_proposal(
    connection: asyncpg.Connection,
    user_id: UUID,
    tender_id: UUID,
    *,
    status: str = "DRAFT",
) -> UUID:
    proposal_id = uuid4()
    await connection.execute(
        """
        INSERT INTO proposals (
            id,user_id,tender_id,status,ai_confidence_score,structured_data,
            margin_percent,include_vat,currency
        ) VALUES ($1,$2,$3,$4,0,'{}'::json,20,true,'USD')
        """,
        proposal_id,
        user_id,
        tender_id,
        status,
    )
    return proposal_id


async def seed_engagement(
    connection: asyncpg.Connection,
    user_id: UUID,
    profile_id: UUID,
    tender_id: UUID,
    status: TenderEngagementStatus,
) -> UUID:
    engagement_id = uuid4()
    await connection.execute(
        """
        INSERT INTO tender_engagements (
            id,user_id,company_profile_id,tender_id,status,origin
        ) VALUES ($1,$2,$3,$4,$5,'MANUAL_SAVE')
        """,
        engagement_id,
        user_id,
        profile_id,
        tender_id,
        status.value,
    )
    return engagement_id


async def scenario(database: str) -> dict[str, Any]:
    bootstrap = await asyncio.to_thread(support.run_bootstrap, database)
    assert bootstrap.returncode == 0, bootstrap.stderr or bootstrap.stdout
    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == HEAD
        user_a, profile_a = await seed_user(connection, "tenant-a")
        user_b, profile_b = await seed_user(connection, "tenant-b")
        incomplete_user, _ = await seed_user(connection, "incomplete", with_profile=False)
        assert profile_a and profile_b

        legacy: list[tuple[UUID, UUID]] = []
        for index in range(118):
            tender_id = await seed_tender(connection, f"legacy-{index:03d}")
            owner_id = user_a if index < 110 else incomplete_user
            artifact_status = "DRAFT" if index < 108 else "COMPLETED" if index < 117 else "SUBMITTED"
            proposal_id = await seed_proposal(
                connection,
                owner_id,
                tender_id,
                status=artifact_status,
            )
            legacy.append((proposal_id, tender_id))

        # Representative Proposal+engagement and engagement-only rows.
        await seed_engagement(
            connection,
            user_a,
            profile_a,
            legacy[0][1],
            TenderEngagementStatus.SAVED,
        )
        engagement_only_tender = await seed_tender(connection, "engagement-only")
        await seed_engagement(
            connection,
            user_a,
            profile_a,
            engagement_only_tender,
            TenderEngagementStatus.EVALUATING,
        )
        before_passive = int(await connection.fetchval("SELECT COUNT(*) FROM tender_engagements"))

        ownership = await connection.fetchrow(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE cp.id IS NOT NULL) AS valid,
                COUNT(*) FILTER (WHERE cp.id IS NULL) AS incomplete
            FROM proposals p
            LEFT JOIN company_profiles cp ON cp.user_id=p.user_id
            """
        )
        assert tuple(ownership) == (118, 110, 8)

        # Migration/startup/list/detail-style reads preserve history verbatim.
        noop_upgrade = await asyncio.to_thread(support.alembic, database, "upgrade", "head")
        assert noop_upgrade.returncode == 0, noop_upgrade.stderr or noop_upgrade.stdout
        await connection.fetch("SELECT id,status FROM proposals ORDER BY created_at")
        await connection.fetchrow("SELECT * FROM proposals WHERE id=$1", legacy[1][0])
        assert await connection.fetchval("SELECT COUNT(*) FROM proposals") == 118
        assert await connection.fetchval("SELECT COUNT(*) FROM tender_engagements") == before_passive
    finally:
        await connection.close()

    engine = create_async_engine(support.target_url(database), pool_size=12)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare_tender(tender_id: UUID):
        async with sessions() as session:
            async with session.begin():
                return await prepare_bid(
                    session,
                    user_id=user_a,
                    company_profile_id=profile_a,
                    tender_id=tender_id,
                )

    async def continue_proposal(proposal_id: UUID, *, user=user_a, profile=profile_a):
        async with sessions() as session:
            async with session.begin():
                return await prepare_bid(
                    session,
                    user_id=user,
                    company_profile_id=profile,
                    proposal_id=proposal_id,
                )

    # New explicit intent creates one of each under concurrency.
    connection = await support.database_connection(database)
    try:
        concurrent_new_tender = await seed_tender(connection, "concurrent-new")
    finally:
        await connection.close()
    new_a, new_b = await asyncio.gather(
        prepare_tender(concurrent_new_tender),
        prepare_tender(concurrent_new_tender),
    )
    assert new_a.proposal.id == new_b.proposal.id
    assert new_a.engagement.id == new_b.engagement.id
    assert new_a.engagement.status == TenderEngagementStatus.PREPARING

    # Every lifecycle input has the locked transition/non-downgrade behavior.
    transition_results: dict[str, str] = {}
    transition_rows: dict[str, tuple[UUID, UUID]] = {}
    connection = await support.database_connection(database)
    try:
        for current in TenderEngagementStatus:
            tender_id = await seed_tender(connection, f"from-{current.value.lower()}")
            engagement_id = await seed_engagement(
                connection, user_a, profile_a, tender_id, current
            )
            transition_rows[current.value] = (engagement_id, tender_id)
    finally:
        await connection.close()
    for current in TenderEngagementStatus:
        engagement_id, tender_id = transition_rows[current.value]
        result = await prepare_tender(tender_id)
        expected = (
            current
            if current in {
                TenderEngagementStatus.SUBMITTED,
                TenderEngagementStatus.WON,
                TenderEngagementStatus.LOST,
            }
            else TenderEngagementStatus.PREPARING
        )
        assert result.engagement.id == engagement_id
        assert result.engagement.status == expected
        transition_results[current.value] = expected.value

    # Concurrent Prepare from SAVED creates one Proposal and transitions one row.
    connection = await support.database_connection(database)
    try:
        saved_tender_id = await seed_tender(connection, "concurrent-saved")
        saved_engagement_id = await seed_engagement(
            connection,
            user_a,
            profile_a,
            saved_tender_id,
            TenderEngagementStatus.SAVED,
        )
    finally:
        await connection.close()
    saved_a, saved_b = await asyncio.gather(
        prepare_tender(saved_tender_id), prepare_tender(saved_tender_id)
    )
    assert saved_a.engagement.id == saved_b.engagement.id == saved_engagement_id
    assert saved_a.proposal.id == saved_b.proposal.id

    # Concurrent explicit Continue reuses the legacy Proposal and creates one engagement.
    continue_id, continue_tender = legacy[1]
    continued_a, continued_b = await asyncio.gather(
        continue_proposal(continue_id), continue_proposal(continue_id)
    )
    assert continued_a.proposal.id == continued_b.proposal.id == continue_id
    assert continued_a.engagement.id == continued_b.engagement.id
    assert continued_a.engagement.status == TenderEngagementStatus.PREPARING

    # Foreign same-name tenant cannot open/continue the artifact.
    try:
        await continue_proposal(continue_id, user=user_b, profile=profile_b)
    except BidPreparationNotFoundError:
        foreign_result = "not_found"
    else:
        raise AssertionError("foreign Proposal was continued")

    # Force Proposal persistence failure. The command transaction must roll back
    # its newly inserted PREPARING engagement; retry then succeeds.
    connection = await support.database_connection(database)
    try:
        rollback_tender = await seed_tender(connection, "forced-rollback")
        await connection.execute(
            f"""
            CREATE OR REPLACE FUNCTION s43_fail_proposal() RETURNS trigger AS $$
            BEGIN
                IF NEW.tender_id = '{rollback_tender}'::uuid THEN
                    RAISE EXCEPTION 'forced proposal failure';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER s43_fail_proposal_insert
            BEFORE INSERT ON proposals
            FOR EACH ROW EXECUTE FUNCTION s43_fail_proposal();
            """
        )
    finally:
        await connection.close()
    try:
        await prepare_tender(rollback_tender)
    except Exception as exc:
        assert "forced proposal failure" in str(exc)
    else:
        raise AssertionError("forced Proposal failure unexpectedly succeeded")
    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM tender_engagements WHERE tender_id=$1", rollback_tender
        ) == 0
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM proposals WHERE tender_id=$1", rollback_tender
        ) == 0
        await connection.execute("DROP TRIGGER s43_fail_proposal_insert ON proposals")
        await connection.execute("DROP FUNCTION s43_fail_proposal()")
    finally:
        await connection.close()
    retry = await prepare_tender(rollback_tender)
    assert retry.engagement.status == TenderEngagementStatus.PREPARING

    connection = await support.database_connection(database)
    try:
        new_cardinality = await connection.fetchrow(
            """
            SELECT
              (SELECT COUNT(*) FROM proposals WHERE tender_id=$1) AS proposals,
              (SELECT COUNT(*) FROM tender_engagements WHERE tender_id=$1) AS engagements
            """,
            concurrent_new_tender,
        )
        legacy_statuses = dict(
            await connection.fetch(
                "SELECT status::text,COUNT(*) FROM proposals WHERE id=ANY($1::uuid[]) GROUP BY status::text",
                [proposal_id for proposal_id, _ in legacy],
            )
        )
    finally:
        await connection.close()
    assert tuple(new_cardinality) == (1, 1)
    assert legacy_statuses == {"DRAFT": 108, "COMPLETED": 9, "SUBMITTED": 1}

    check = await asyncio.to_thread(support.alembic, database, "check", success=False)
    assert check.returncode == 0, check.stderr or check.stdout
    await engine.dispose()
    return {
        "head": HEAD,
        "alembic_check": "clean",
        "legacy_proposals": 118,
        "valid_owner_tender_profile": 110,
        "incomplete_ownership": 8,
        "passive_engagement_backfill": 0,
        "legacy_statuses": legacy_statuses,
        "concurrent_new_cardinality": {"proposals": 1, "engagements": 1},
        "concurrent_continue": "same_proposal_one_engagement",
        "concurrent_saved_prepare": "same_proposal_same_engagement",
        "forced_failure_rolled_back": True,
        "retry_succeeded": True,
        "state_results": transition_results,
        "same_name_foreign_continue": foreign_result,
        "completed_did_not_submit": True,
        "legacy_submitted_did_not_infer_engagement": True,
    }


async def main() -> int:
    database = support.database_name("s43_bid_preparation")
    await support.create_database(database)
    try:
        result = await scenario(database)
        print(json.dumps({"status": "ok", **result}, sort_keys=True))
        return 0
    finally:
        await support.drop_database(database)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
