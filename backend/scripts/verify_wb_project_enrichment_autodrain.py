#!/usr/bin/env python3
"""Disposable PostgreSQL proof for automatic World Bank backlog draining."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.all_models import Project
from app.services.project_enrichment import (
    PROJECT_ENRICHMENT_ACTIVE_LEASE,
    WORLD_BANK_ENRICHMENT_RETRY_BACKOFF,
    claim_world_bank_projects_for_enrichment,
    enqueue_world_bank_project_enrichment_batch,
    world_bank_project_backlog_snapshot,
)
from app.workers import project_enrichment_tasks
from scripts import test_s0_5b4_baseline as support


HEAD = "20260828_0003_s4_1_tender_engagement_foundation"
BATCH_SIZE = 25


def source_record(project_id: str, *, partial: bool = False) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": project_id,
        "project_name": f"Authoritative {project_id}",
        "countryshortname": "Uzbekistan",
        "regionname": "Europe and Central Asia",
        "projectstatusdisplay": "Active",
        "boardapprovaldate": "2025-01-01T00:00:00Z",
        "closingdate": "12/31/2028 12:00:00 AM",
        "borrower": "Republic of Uzbekistan",
        "impagency": "Test Implementing Agency",
        "teamleadname": "Project Leader",
        "url": (
            "https://projects.worldbank.org/en/projects-operations/project-detail/"
            f"{project_id}"
        ),
    }
    if partial:
        del record["teamleadname"]
    return record


class ControlledWorldBankClient:
    async def fetch_project(self, external_project_id: str) -> dict[str, Any]:
        return source_record(
            external_project_id,
            partial=external_project_id.endswith("1"),
        )


async def seed_linked_projects(
    database: str,
    *,
    first_number: int,
    count: int,
    status: str = "never_attempted",
    attempted_at: datetime | None = None,
    enriched_at: datetime | None = None,
    failure_class: str | None = None,
) -> list[UUID]:
    connection = await support.database_connection(database)
    project_ids: list[UUID] = []
    try:
        for offset in range(count):
            number = first_number + offset
            project_id = uuid4()
            tender_id = uuid4()
            project_ids.append(project_id)
            external_project_id = f"P{number:06d}"
            await connection.execute(
                """
                INSERT INTO projects (
                    id, source_system, external_project_id, enrichment_status,
                    enrichment_last_attempted_at, last_enriched_at,
                    enrichment_failure_class
                ) VALUES ($1, 'world_bank', $2, $3, $4, $5, $6)
                """,
                project_id,
                external_project_id,
                status,
                attempted_at,
                enriched_at,
                failure_class,
            )
            await connection.execute(
                """
                INSERT INTO tenders (
                    id, external_id, source_url, title, budget, currency,
                    status, category, source_system, canonical_source_key,
                    project_id, source_metadata_json, scrape_status
                ) VALUES (
                    $1, $2, $3, $4, 1, 'USD', 'OPEN', 'World Bank',
                    'world_bank', $5, $6, '{}'::json, 'success'
                )
                """,
                tender_id,
                f"WB-AUTODRAIN-{number}",
                f"https://example.test/tenders/{number}",
                f"Autodrain tender {number}",
                f"world_bank:WB-AUTODRAIN-{number}",
                external_project_id,
            )
            await connection.execute(
                """
                INSERT INTO tender_projects (
                    id, tender_id, project_id, linkage_method,
                    source_value, provenance
                ) VALUES (
                    $1, $2, $3, 'SOURCE_PROJECT_ID', $4,
                    '{"source_field": "tenders.project_id"}'::json
                )
                """,
                uuid4(),
                tender_id,
                project_id,
                external_project_id,
            )
    finally:
        await connection.close()
    return project_ids


async def prove_multi_batch_drain(
    sessions: async_sessionmaker,
) -> dict[str, Any]:
    progression: list[int] = []
    dispatched_ids: list[UUID] = []

    def capture_dispatch(*, args: list[str], **_: Any) -> None:
        dispatched_ids.append(UUID(args[0]))

    fixed_now = datetime(2026, 8, 27, 3, 0, tzinfo=timezone.utc)
    with patch.object(
        project_enrichment_tasks.enrich_world_bank_project_task,
        "apply_async",
        side_effect=capture_dispatch,
    ):
        while True:
            async with sessions() as db:
                before = await world_bank_project_backlog_snapshot(db, now=fixed_now)
                progression.append(before.eligible_now)
                if before.eligible_now == 0:
                    break
                dispatched_ids.clear()
                result = await enqueue_world_bank_project_enrichment_batch(
                    db,
                    limit=BATCH_SIZE,
                    now=fixed_now,
                )
                assert result.claimed == min(BATCH_SIZE, before.eligible_now)
                assert result.enqueued == result.claimed
                assert len(dispatched_ids) == len(set(dispatched_ids)) == result.claimed
                await db.execute(
                    update(Project)
                    .where(Project.id.in_(dispatched_ids))
                    .values(
                        enrichment_status="successful",
                        enrichment_last_attempted_at=fixed_now,
                        last_enriched_at=fixed_now,
                        enrichment_failure_class=None,
                    )
                )
                await db.commit()

    assert progression == [125, 100, 75, 50, 25, 0]
    return {"seeded": 125, "batch_size": BATCH_SIZE, "progression": progression}


async def prove_live_like_worker_chain(
    database: str,
    sessions: async_sessionmaker,
) -> dict[str, Any]:
    project_ids = await seed_linked_projects(
        database,
        first_number=910000,
        count=4,
    )
    pending_dispatches: list[UUID] = []

    def capture_dispatch(*, args: list[str], **_: Any) -> None:
        pending_dispatches.append(UUID(args[0]))

    client = ControlledWorldBankClient()
    statuses: list[str] = []
    with (
        patch.object(
            project_enrichment_tasks.enrich_world_bank_project_task,
            "apply_async",
            side_effect=capture_dispatch,
        ),
        patch.object(project_enrichment_tasks, "AsyncSessionLocal", sessions),
    ):
        for _ in range(2):
            pending_dispatches.clear()
            async with sessions() as db:
                dispatched = await enqueue_world_bank_project_enrichment_batch(
                    db,
                    limit=2,
                )
            assert dispatched.claimed == dispatched.enqueued == 2
            for project_id in pending_dispatches:
                result = (
                    await project_enrichment_tasks._execute_world_bank_project_enrichment(
                        project_id,
                        client=client,
                    )
                )
                statuses.append(str(result["status"]))

        async with sessions() as db:
            snapshot = await world_bank_project_backlog_snapshot(db)
            rows = (
                await db.execute(
                    select(Project.enrichment_status).where(Project.id.in_(project_ids))
                )
            ).scalars().all()
        assert snapshot.eligible_now == 0
        assert set(rows).issubset({"successful", "partial"})
        assert "partial" in rows
    return {
        "projects": len(project_ids),
        "scheduled_batches": 2,
        "persisted_statuses": sorted(statuses),
        "eligible_after": 0,
    }


async def prove_concurrent_dispatch(
    database: str,
    sessions: async_sessionmaker,
) -> dict[str, Any]:
    project_ids = await seed_linked_projects(
        database,
        first_number=920000,
        count=50,
    )
    dispatched_ids: list[UUID] = []

    def capture_dispatch(*, args: list[str], **_: Any) -> None:
        dispatched_ids.append(UUID(args[0]))

    async def dispatch_once() -> int:
        async with sessions() as db:
            result = await enqueue_world_bank_project_enrichment_batch(
                db,
                limit=BATCH_SIZE,
            )
            return result.claimed

    with patch.object(
        project_enrichment_tasks.enrich_world_bank_project_task,
        "apply_async",
        side_effect=capture_dispatch,
    ):
        claims = await asyncio.gather(dispatch_once(), dispatch_once())
    assert claims == [BATCH_SIZE, BATCH_SIZE]
    assert len(dispatched_ids) == len(set(dispatched_ids)) == len(project_ids)
    async with sessions() as db:
        await db.execute(
            update(Project)
            .where(Project.id.in_(project_ids))
            .values(
                enrichment_status="successful",
                last_enriched_at=datetime.now(timezone.utc),
                enrichment_failure_class=None,
            )
        )
        await db.commit()
    return {
        "dispatchers": 2,
        "claimed": claims,
        "unique_active_jobs": len(set(dispatched_ids)),
        "duplicates": 0,
    }


async def prove_recovery_and_failure_policy(
    database: str,
    sessions: async_sessionmaker,
) -> dict[str, Any]:
    now = datetime(2026, 8, 27, 4, 0, tzinfo=timezone.utc)
    expired = await seed_linked_projects(
        database,
        first_number=930000,
        count=1,
        status="queued",
        attempted_at=now - PROJECT_ENRICHMENT_ACTIVE_LEASE - timedelta(seconds=1),
    )
    active = await seed_linked_projects(
        database,
        first_number=930001,
        count=1,
        status="running",
        attempted_at=now,
    )
    retry_wait = await seed_linked_projects(
        database,
        first_number=930002,
        count=1,
        status="source_unavailable",
        attempted_at=now - WORLD_BANK_ENRICHMENT_RETRY_BACKOFF + timedelta(seconds=1),
        failure_class="http_503",
    )
    terminal = await seed_linked_projects(
        database,
        first_number=930003,
        count=1,
        status="failed",
        attempted_at=now - timedelta(days=1),
        failure_class="identity_mismatch",
    )
    recent_partial = await seed_linked_projects(
        database,
        first_number=930004,
        count=1,
        status="partial",
        attempted_at=now,
        enriched_at=now,
        failure_class="leadership_roster_incomplete",
    )
    async with sessions() as db:
        snapshot = await world_bank_project_backlog_snapshot(db, now=now)
        claimed = await claim_world_bank_projects_for_enrichment(db, now=now, limit=10)
        await db.rollback()
    assert claimed == expired
    assert snapshot.expired_lease == 1
    assert snapshot.retry_wait == 1
    assert snapshot.failed_terminal == 1
    assert not ({*active, *retry_wait, *terminal, *recent_partial} & set(claimed))
    return {
        "expired_lease_reclaimed": True,
        "active_lease_skipped": True,
        "retry_wait_skipped": True,
        "terminal_failure_skipped": True,
        "fresh_partial_skipped": True,
    }


async def scenario(database: str) -> dict[str, Any]:
    bootstrap = await asyncio.to_thread(support.run_bootstrap, database)
    assert bootstrap.returncode == 0, bootstrap.stderr or bootstrap.stdout
    connection = await support.database_connection(database)
    try:
        assert await connection.fetchval(
            "SELECT version_num FROM alembic_version"
        ) == HEAD
    finally:
        await connection.close()

    await seed_linked_projects(database, first_number=900000, count=125)
    engine = create_async_engine(
        support.target_url(database),
        pool_size=5,
        max_overflow=5,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        return {
            "multi_batch_drain": await prove_multi_batch_drain(sessions),
            "live_like_worker": await prove_live_like_worker_chain(database, sessions),
            "concurrent_dispatch": await prove_concurrent_dispatch(database, sessions),
            "lease_and_failures": await prove_recovery_and_failure_policy(
                database,
                sessions,
            ),
        }
    finally:
        await engine.dispose()


async def main() -> int:
    database = support.database_name("wb_autodrain")
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
