#!/usr/bin/env python3
"""Disposable PostgreSQL proof for the Sprint 4.2 My Tenders read model."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.base import TenderEngagementOrigin, TenderEngagementStatus, TenderStatus
from app.services.my_tenders import MyTendersQuery, get_owned_my_tender_item, list_my_tenders
from app.services.tender_engagements import save_tender_to_my_tenders
from scripts import test_s0_5b4_baseline as support


HEAD = "20260828_0003_s4_1_tender_engagement_foundation"
STATUSES = tuple(TenderEngagementStatus)
SOURCES = ("uzex", "world_bank", "adb", "giz", "ebrd")


async def seed_owner(
    connection: asyncpg.Connection,
    label: str,
) -> tuple[UUID, UUID]:
    user_id, profile_id = uuid4(), uuid4()
    await connection.execute(
        """
        INSERT INTO users (
            id, google_id, email, name, subscription_tier, is_admin,
            approval_status, platform_role, auth_version
        ) VALUES ($1,$2,$3,$4,'SCOUT',false,'approved','pilot_user',0)
        """,
        user_id,
        f"s42-{label}-{user_id}",
        f"{label}-{user_id}@s42.invalid",
        label,
    )
    await connection.execute(
        """
        INSERT INTO company_profiles (
            id, user_id, company_name, pilot_status, approval_status
        ) VALUES ($1,$2,'Acme Engineering','active_pilot','approved')
        """,
        profile_id,
        user_id,
    )
    return user_id, profile_id


async def seed_tender(
    connection: asyncpg.Connection,
    index: int,
    *,
    source: str = "uzex",
    title: str | None = None,
    status: str = "OPEN",
    deadline: datetime | None = None,
) -> UUID:
    tender_id = uuid4()
    await connection.execute(
        """
        INSERT INTO tenders (
            id, external_id, source_system, canonical_source_key, source_url,
            title, buyer, budget, currency, deadline, country, region,
            notice_type, procurement_method, status, category
        ) VALUES (
            $1,$2,$3,$4,'https://example.invalid/s42',$5,$6,$7,'USD',$8,
            'Uzbekistan','Tashkent','Invitation','Open procedure',$9,'Other'
        )
        """,
        tender_id,
        f"S42-{index}-{tender_id}",
        source,
        f"{source}:s42:{index}:{tender_id}",
        title or f"Representative Tender {index:03d}",
        f"Buyer {index % 11:02d}",
        float(index * 1000 + 500),
        deadline,
        status,
    )
    return tender_id


async def scenario(database: str) -> dict[str, Any]:
    bootstrap = await asyncio.to_thread(support.run_bootstrap, database)
    assert bootstrap.returncode == 0, bootstrap.stderr or bootstrap.stdout
    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == HEAD
        user_a, profile_a = await seed_owner(connection, "tenant-a")
        user_b, profile_b = await seed_owner(connection, "tenant-b")
        now = datetime.now(timezone.utc)
        tender_ids: list[UUID] = []
        engagement_ids: list[UUID] = []
        expected_counts = {status: 0 for status in STATUSES}
        for index in range(150):
            deadline = None if index % 13 == 0 else now + timedelta(days=index - 25)
            tender_id = await seed_tender(
                connection,
                index,
                source=SOURCES[index % len(SOURCES)],
                deadline=deadline,
            )
            engagement_id = uuid4()
            engagement_status = STATUSES[index % len(STATUSES)]
            expected_counts[engagement_status] += 1
            changed_at = now - timedelta(minutes=index)
            await connection.execute(
                """
                INSERT INTO tender_engagements (
                    id, user_id, company_profile_id, tender_id, status, origin,
                    created_at, updated_at, status_changed_at
                ) VALUES ($1,$2,$3,$4,$5,'MANUAL_SAVE',$6,$6,$6)
                """,
                engagement_id,
                user_a,
                profile_a,
                tender_id,
                engagement_status.value,
                changed_at,
            )
            tender_ids.append(tender_id)
            engagement_ids.append(engagement_id)

        # Project enrichment is intentionally pending and must not block rows.
        project_id = uuid4()
        await connection.execute(
            """
            INSERT INTO projects (
                id, source_system, external_project_id, name, enrichment_status
            ) VALUES ($1,'world_bank','P424242',NULL,'queued')
            """,
            project_id,
        )
        await connection.execute(
            """
            INSERT INTO tender_projects (
                id, tender_id, project_id, linkage_method, source_value, provenance
            ) VALUES ($1,$2,$3,'SOURCE_PROJECT_ID','P424242','{}'::json)
            """,
            uuid4(),
            tender_ids[1],
            project_id,
        )

        # Proposal-only legacy Tender must never enter My Tenders.
        proposal_only_tender = await seed_tender(
            connection, 900, title="Legacy Proposal Only"
        )
        await connection.execute(
            """
            INSERT INTO proposals (
                id, user_id, tender_id, status, ai_confidence_score,
                structured_data, margin_percent, include_vat, currency
            ) VALUES ($1,$2,$3,'DRAFT',0,'{}'::json,20,true,'USD')
            """,
            uuid4(),
            user_a,
            proposal_only_tender,
        )
        # One mixed Tender has both artifacts; it must still appear only once.
        await connection.execute(
            """
            INSERT INTO proposals (
                id, user_id, tender_id, status, ai_confidence_score,
                structured_data, margin_percent, include_vat, currency
            ) VALUES ($1,$2,$3,'DRAFT',0,'{}'::json,20,true,'USD')
            """,
            uuid4(),
            user_a,
            tender_ids[2],
        )
        # Same-name tenant uses the same Tender without crossing list scope.
        tenant_b_engagement_id = uuid4()
        await connection.execute(
            """
            INSERT INTO tender_engagements (
                id, user_id, company_profile_id, tender_id, status, origin
            ) VALUES ($1,$2,$3,$4,'SAVED','MANUAL_SAVE')
            """,
            tenant_b_engagement_id,
            user_b,
            profile_b,
            tender_ids[0],
        )
    finally:
        await connection.close()

    engine = create_async_engine(support.target_url(database), pool_size=8)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    query_count = 0

    def count_query(*_args) -> None:
        nonlocal query_count
        query_count += 1

    event.listen(engine.sync_engine, "before_cursor_execute", count_query)
    started = monotonic()
    async with sessions() as session:
        active_page = await list_my_tenders(
            session,
            user_id=user_a,
            company_profile_id=profile_a,
            query=MyTendersQuery(limit=25),
        )
    elapsed_ms = round((monotonic() - started) * 1000, 3)
    event.remove(engine.sync_engine, "before_cursor_execute", count_query)
    assert query_count == 3
    assert len(active_page.items) == 25
    assert active_page.total == 150 - expected_counts[TenderEngagementStatus.DISMISSED]
    assert active_page.counts.all == 150
    assert active_page.counts.dismissed == expected_counts[TenderEngagementStatus.DISMISSED]
    assert proposal_only_tender not in {item.tender_id for item in active_page.items}

    async with sessions() as session:
        dismissed = await list_my_tenders(
            session,
            user_id=user_a,
            company_profile_id=profile_a,
            query=MyTendersQuery(status="DISMISSED", limit=100),
        )
        assert dismissed.total == expected_counts[TenderEngagementStatus.DISMISSED]
        assert all(item.engagement_status == TenderEngagementStatus.DISMISSED for item in dismissed.items)

        searched = await list_my_tenders(
            session,
            user_id=user_a,
            company_profile_id=profile_a,
            query=MyTendersQuery(status="ALL", search="Representative Tender 042"),
        )
        assert [item.tender_id for item in searched.items] == [tender_ids[42]]

        source_filtered = await list_my_tenders(
            session,
            user_id=user_a,
            company_profile_id=profile_a,
            query=MyTendersQuery(status="ALL", source_system="world_bank", limit=100),
        )
        assert source_filtered.items
        assert all(item.source_system == "world_bank" for item in source_filtered.items)
        pending_project = next(item for item in source_filtered.items if item.tender_id == tender_ids[1])
        assert pending_project.project_external_id == "P424242"
        assert pending_project.project_name is None
        assert pending_project.project_enrichment_status == "queued"

        first_page = await list_my_tenders(
            session,
            user_id=user_a,
            company_profile_id=profile_a,
            query=MyTendersQuery(status="ALL", sort="recently_added", limit=25),
        )
        second_page = await list_my_tenders(
            session,
            user_id=user_a,
            company_profile_id=profile_a,
            query=MyTendersQuery(
                status="ALL", sort="recently_added", offset=25, limit=25
            ),
        )
        assert not ({item.engagement_id for item in first_page.items} & {item.engagement_id for item in second_page.items})

        deadlines = await list_my_tenders(
            session,
            user_id=user_a,
            company_profile_id=profile_a,
            query=MyTendersQuery(status="ALL", sort="deadline_soonest", limit=100),
        )
        seen_null = False
        for item in deadlines.items:
            if item.deadline is None:
                seen_null = True
            else:
                assert not seen_null

        tenant_b = await list_my_tenders(
            session,
            user_id=user_b,
            company_profile_id=profile_b,
            query=MyTendersQuery(status="ALL"),
        )
        assert tenant_b.total == 1
        assert tenant_b.items[0].engagement_id == tenant_b_engagement_id
        assert await get_owned_my_tender_item(
            session,
            engagement_id=tenant_b_engagement_id,
            user_id=user_a,
            company_profile_id=profile_a,
        ) is None

    # Closed/cancelled source drift changes presentation only.
    connection = await support.database_connection(database)
    try:
        original_engagement_status = await connection.fetchval(
            "SELECT status::text FROM tender_engagements WHERE id=$1",
            engagement_ids[3],
        )
        await connection.execute(
            "UPDATE tenders SET status='CANCELLED' WHERE id=$1", tender_ids[3]
        )
    finally:
        await connection.close()
    async with sessions() as session:
        drift = await list_my_tenders(
            session,
            user_id=user_a,
            company_profile_id=profile_a,
            query=MyTendersQuery(status="ALL", search="Representative Tender 003"),
        )
        assert drift.items[0].tender_status == TenderStatus.CANCELLED
        assert drift.items[0].engagement_status.value == original_engagement_status

    # Concurrent explicit Save creates one deterministic row.
    connection = await support.database_connection(database)
    try:
        save_tender_id = await seed_tender(connection, 1000, title="Concurrent Save")
    finally:
        await connection.close()

    async def save_once(tender_id: UUID):
        async with sessions() as session:
            async with session.begin():
                return await save_tender_to_my_tenders(
                    session,
                    user_id=user_a,
                    company_profile_id=profile_a,
                    tender_id=tender_id,
                )

    save_a, save_b = await asyncio.gather(save_once(save_tender_id), save_once(save_tender_id))
    assert sorted((save_a.created, save_b.created)) == [False, True]
    assert save_a.engagement.id == save_b.engagement.id
    assert save_a.engagement.status == TenderEngagementStatus.SAVED
    assert save_a.engagement.origin == TenderEngagementOrigin.MANUAL_SAVE

    # Save never downgrades higher states.
    connection = await support.database_connection(database)
    try:
        higher_rows: list[tuple[UUID, UUID, TenderEngagementStatus]] = []
        for index, higher_status in enumerate(
            (
                TenderEngagementStatus.PREPARING,
                TenderEngagementStatus.SUBMITTED,
                TenderEngagementStatus.WON,
                TenderEngagementStatus.LOST,
            ),
            start=1100,
        ):
            tender_id = await seed_tender(connection, index, title=f"Higher {higher_status.value}")
            engagement_id = uuid4()
            await connection.execute(
                """
                INSERT INTO tender_engagements (
                    id,user_id,company_profile_id,tender_id,status,origin
                ) VALUES ($1,$2,$3,$4,$5,'BID_PREPARATION')
                """,
                engagement_id,
                user_a,
                profile_a,
                tender_id,
                higher_status.value,
            )
            higher_rows.append((engagement_id, tender_id, higher_status))
        dismissed_tender_id = await seed_tender(connection, 1200, title="Resume Dismissed")
        dismissed_id = uuid4()
        await connection.execute(
            """
            INSERT INTO tender_engagements (
                id,user_id,company_profile_id,tender_id,status,origin
            ) VALUES ($1,$2,$3,$4,'DISMISSED','MANUAL_SAVE')
            """,
            dismissed_id,
            user_a,
            profile_a,
            dismissed_tender_id,
        )
    finally:
        await connection.close()

    for engagement_id, tender_id, higher_status in higher_rows:
        result = await save_once(tender_id)
        assert result.engagement.id == engagement_id
        assert result.engagement.status == higher_status
        assert not result.created and not result.reengaged
    resumed = await save_once(dismissed_tender_id)
    assert resumed.engagement.id == dismissed_id
    assert resumed.engagement.status == TenderEngagementStatus.SAVED
    assert resumed.reengaged

    connection = await support.database_connection(database)
    try:
        saved_rows = int(
            await connection.fetchval(
                """
                SELECT COUNT(*) FROM tender_engagements
                WHERE user_id=$1 AND company_profile_id=$2 AND tender_id=$3
                """,
                user_a,
                profile_a,
                save_tender_id,
            )
        )
        plan = await connection.fetchval(
            """
            EXPLAIN (FORMAT JSON)
            SELECT id FROM tender_engagements
            WHERE user_id=$1 AND company_profile_id=$2
            ORDER BY status_changed_at DESC, id DESC
            LIMIT 25
            """,
            user_a,
            profile_a,
        )
    finally:
        await connection.close()
    assert saved_rows == 1
    check = await asyncio.to_thread(support.alembic, database, "check", success=False)
    assert check.returncode == 0, check.stderr or check.stdout
    await engine.dispose()
    return {
        "head": HEAD,
        "representative_engagements": 150,
        "page_queries": query_count,
        "page_runtime_ms": elapsed_ms,
        "n_plus_one": False,
        "query_plan_root": json.loads(plan)[0]["Plan"]["Node Type"],
        "pagination": "bounded_deterministic",
        "proposal_only_absent": True,
        "mixed_fixture": "engagement_rows_only_no_duplicates",
        "same_name_isolated": True,
        "direct_id_cross_tenant": "not_found",
        "concurrent_save_rows": saved_rows,
        "higher_state_preserved": True,
        "dismissed_reengaged": True,
        "project_pending_renderable": True,
        "source_status_separate": True,
        "alembic_check": "clean",
    }


async def main() -> int:
    database = support.database_name("s42_my_tenders")
    await support.create_database(database)
    try:
        result = await scenario(database)
        print(json.dumps({"status": "ok", **result}, sort_keys=True))
        return 0
    finally:
        await support.drop_database(database)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
