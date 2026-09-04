#!/usr/bin/env python3
"""Disposable PostgreSQL proof for Sprint 4.4 engagement workflow semantics."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

import asyncpg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.base import TenderEngagementStatus
from app.services.bid_preparation import prepare_bid
from app.services.my_tenders import MyTendersQuery, list_my_tenders
from app.services.tender_engagements import (
    TenderEngagementNotFoundError,
    TenderEngagementTransitionError,
    correct_tender_engagement_status,
    dismiss,
    evaluate,
    mark_lost,
    mark_submitted,
    mark_won,
    save_tender_to_my_tenders,
    set_tender_engagement_status,
)
from scripts import test_s0_5b4_baseline as support


HEAD = "20260902_0001_s7_2_user_ui_locale"


async def seed_owner(connection: asyncpg.Connection, label: str) -> tuple[UUID, UUID]:
    user_id, profile_id = uuid4(), uuid4()
    await connection.execute(
        """
        INSERT INTO users (
            id,google_id,email,name,subscription_tier,is_admin,
            approval_status,platform_role,auth_version
        ) VALUES ($1,$2,$3,$4,'SCOUT',false,'approved','pilot_user',0)
        """,
        user_id,
        f"s44-{label}-{user_id}",
        f"{label}-{user_id}@s44.invalid",
        label,
    )
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
    source_status: str = "OPEN",
) -> UUID:
    tender_id = uuid4()
    await connection.execute(
        """
        INSERT INTO tenders (
            id,external_id,source_system,canonical_source_key,source_url,
            title,budget,currency,status,category
        ) VALUES ($1,$2,'uzex',$3,'https://example.invalid/s44',$4,1000,'USD',$5,'Other')
        """,
        tender_id,
        f"S44-{label}-{tender_id}",
        f"uzex:s44:{label}:{tender_id}",
        f"Sprint 4.4 {label}",
        source_status,
    )
    return tender_id


async def seed_engagement(
    connection: asyncpg.Connection,
    user_id: UUID,
    profile_id: UUID,
    tender_id: UUID,
    engagement_status: TenderEngagementStatus,
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
        engagement_status.value,
    )
    return engagement_id


async def scenario(database: str) -> dict[str, Any]:
    bootstrap = await asyncio.to_thread(support.run_bootstrap, database)
    assert bootstrap.returncode == 0, bootstrap.stderr or bootstrap.stdout
    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == HEAD
        user_a, profile_a = await seed_owner(connection, "tenant-a")
        user_b, profile_b = await seed_owner(connection, "tenant-b")
        workflow_tender = await seed_tender(connection, "workflow")
        no_proposal_tender = await seed_tender(connection, "no-proposal")
        cancelled_tender = await seed_tender(connection, "cancelled", source_status="CANCELLED")
        concurrency_tenders = {
            name: await seed_tender(connection, name)
            for name in ("a", "b", "c", "d")
        }
        await seed_engagement(connection, user_a, profile_a, no_proposal_tender, TenderEngagementStatus.PREPARING)
        await seed_engagement(connection, user_a, profile_a, cancelled_tender, TenderEngagementStatus.PREPARING)
        await seed_engagement(connection, user_a, profile_a, concurrency_tenders["a"], TenderEngagementStatus.PREPARING)
        await seed_engagement(connection, user_a, profile_a, concurrency_tenders["b"], TenderEngagementStatus.SUBMITTED)
        await seed_engagement(connection, user_a, profile_a, concurrency_tenders["c"], TenderEngagementStatus.PREPARING)
        await seed_engagement(connection, user_a, profile_a, concurrency_tenders["d"], TenderEngagementStatus.DISMISSED)
    finally:
        await connection.close()

    engine = create_async_engine(support.target_url(database), pool_size=12)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    scope = {"user_id": user_a, "company_profile_id": profile_a}

    async def transact(command: Callable[..., Awaitable], tender_id: UUID, **kwargs):
        async with sessions() as session:
            async with session.begin():
                return await command(session, tender_id=tender_id, **scope, **kwargs)

    async def status_of(tender_id: UUID) -> str:
        connection = await support.database_connection(database)
        try:
            return await connection.fetchval(
                "SELECT status::text FROM tender_engagements WHERE user_id=$1 AND company_profile_id=$2 AND tender_id=$3",
                user_a,
                profile_a,
                tender_id,
            )
        finally:
            await connection.close()

    # Full primary workflow. Proposal creation is coupled only to explicit Prepare.
    async with sessions() as session:
        async with session.begin():
            saved = await save_tender_to_my_tenders(session, tender_id=workflow_tender, **scope)
            assert saved.created and saved.engagement.status == TenderEngagementStatus.SAVED
    await transact(evaluate, workflow_tender, expected_status=TenderEngagementStatus.SAVED)
    async with sessions() as session:
        async with session.begin():
            prepared = await prepare_bid(session, tender_id=workflow_tender, **scope)
            assert prepared.engagement.status == TenderEngagementStatus.PREPARING
    await transact(mark_submitted, workflow_tender, expected_status=TenderEngagementStatus.PREPARING)
    await transact(mark_won, workflow_tender, expected_status=TenderEngagementStatus.SUBMITTED)
    await transact(
        correct_tender_engagement_status,
        workflow_tender,
        status=TenderEngagementStatus.LOST,
        expected_status=TenderEngagementStatus.WON,
    )
    await transact(
        correct_tender_engagement_status,
        workflow_tender,
        status=TenderEngagementStatus.SUBMITTED,
        expected_status=TenderEngagementStatus.LOST,
    )
    await transact(
        correct_tender_engagement_status,
        workflow_tender,
        status=TenderEngagementStatus.PREPARING,
        expected_status=TenderEngagementStatus.SUBMITTED,
    )

    # Submission and outcomes do not require a Proposal.
    await transact(mark_submitted, no_proposal_tender, expected_status=TenderEngagementStatus.PREPARING)
    await transact(mark_lost, no_proposal_tender, expected_status=TenderEngagementStatus.SUBMITTED)

    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval("SELECT COUNT(*) FROM proposals WHERE tender_id=$1", no_proposal_tender) == 0
        cancelled_before = await connection.fetchval("SELECT status::text FROM tender_engagements WHERE tender_id=$1", cancelled_tender)
        await connection.execute("UPDATE tenders SET status='CLOSED' WHERE id=$1", cancelled_tender)
        cancelled_after = await connection.fetchval("SELECT status::text FROM tender_engagements WHERE tender_id=$1", cancelled_tender)
        assert cancelled_before == cancelled_after == "PREPARING"
    finally:
        await connection.close()

    async def concurrent_pair(tender_id: UUID, left, right) -> tuple[list[str], str]:
        outcomes = await asyncio.gather(left(), right(), return_exceptions=True)
        kinds = sorted("conflict" if isinstance(value, TenderEngagementTransitionError) else "committed" for value in outcomes)
        assert kinds == ["committed", "conflict"]
        return kinds, await status_of(tender_id)

    a = concurrency_tenders["a"]
    a_result = await concurrent_pair(
        a,
        lambda: transact(mark_submitted, a, expected_status=TenderEngagementStatus.PREPARING),
        lambda: transact(dismiss, a, expected_status=TenderEngagementStatus.PREPARING),
    )
    assert a_result[1] in {"SUBMITTED", "DISMISSED"}
    b = concurrency_tenders["b"]
    b_result = await concurrent_pair(
        b,
        lambda: transact(mark_won, b, expected_status=TenderEngagementStatus.SUBMITTED),
        lambda: transact(mark_lost, b, expected_status=TenderEngagementStatus.SUBMITTED),
    )
    assert b_result[1] in {"WON", "LOST"}
    c = concurrency_tenders["c"]
    c_result = await concurrent_pair(
        c,
        lambda: transact(mark_submitted, c, expected_status=TenderEngagementStatus.PREPARING),
        lambda: transact(mark_submitted, c, expected_status=TenderEngagementStatus.PREPARING),
    )
    assert c_result[1] == "SUBMITTED"
    d = concurrency_tenders["d"]
    d_result = await concurrent_pair(
        d,
        lambda: transact(set_tender_engagement_status, d, status=TenderEngagementStatus.SAVED, expected_status=TenderEngagementStatus.DISMISSED),
        lambda: transact(set_tender_engagement_status, d, status=TenderEngagementStatus.PREPARING, expected_status=TenderEngagementStatus.DISMISSED),
    )
    assert d_result[1] in {"SAVED", "PREPARING"}

    # Same-name foreign owner cannot address the row through canonical scope.
    async with sessions() as session:
        try:
            async with session.begin():
                await mark_submitted(
                    session,
                    user_id=user_b,
                    company_profile_id=profile_b,
                    tender_id=no_proposal_tender,
                    expected_status=TenderEngagementStatus.LOST,
                )
        except TenderEngagementNotFoundError:
            foreign = "not_found"
        else:
            raise AssertionError("foreign workflow mutation succeeded")

    async with sessions() as session:
        listing = await list_my_tenders(
            session,
            user_id=user_a,
            company_profile_id=profile_a,
            query=MyTendersQuery(status="ALL"),
        )
        assert listing.counts.all == listing.total
        assert sum((listing.counts.saved, listing.counts.evaluating, listing.counts.preparing, listing.counts.submitted, listing.counts.won, listing.counts.lost, listing.counts.dismissed)) == listing.counts.all

    connection = await support.database_connection(database)
    try:
        integrity = await connection.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE status_changed_at IS NULL) AS missing_timestamps,
              COUNT(*) - COUNT(DISTINCT (user_id,company_profile_id,tender_id)) AS duplicate_keys
            FROM tender_engagements
            """
        )
        assert tuple(integrity) == (0, 0)
    finally:
        await connection.close()

    check = await asyncio.to_thread(support.alembic, database, "check", success=False)
    assert check.returncode == 0, check.stderr or check.stdout
    await engine.dispose()
    return {
        "head": HEAD,
        "alembic_check": "clean",
        "primary_workflow": "saved-evaluating-preparing-submitted-won-corrected",
        "no_proposal_outcome": "lost",
        "source_status_independence": True,
        "concurrency": {"preparing": a_result, "outcome": b_result, "duplicate": c_result, "resume": d_result},
        "tenant_isolation": foreign,
        "missing_timestamps": 0,
        "duplicate_keys": 0,
    }


async def main() -> int:
    database = support.database_name("s44_workflow")
    await support.create_database(database)
    try:
        result = await scenario(database)
        print(json.dumps({"status": "ok", **result}, sort_keys=True))
        return 0
    finally:
        await support.drop_database(database)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
