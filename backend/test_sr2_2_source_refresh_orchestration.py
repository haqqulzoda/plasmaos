"""Focused SR-2.2 lifecycle, lease, route, and DTO contract tests."""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.api.endpoints import tenders
from app.models.all_models import SourceRefreshJob
from app.services.source_refresh_jobs import (
    SourceRefreshClaimStatus,
    active_job_needs_republish,
    claim_source_refresh_job,
    complete_source_refresh_job,
    renew_source_refresh_lease,
    validate_source_refresh_options,
)


class FakeSession:
    def __init__(self, job: SourceRefreshJob | None):
        self.job = job
        self.commits = 0
        self.rollbacks = 0

    async def get(self, _model, job_id):
        return self.job if self.job is not None and self.job.id == job_id else None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def job(*, status: str = "queued", now: datetime | None = None) -> SourceRefreshJob:
    timestamp = now or datetime.now(timezone.utc)
    return SourceRefreshJob(
        id=uuid4(),
        source_system="giz",
        requested_by_user_id=uuid4(),
        trigger_kind="customer",
        options_json={},
        status=status,
        force=False,
        created_count=0,
        updated_count=0,
        unchanged_count=0,
        fetched_count=0,
        skipped_count=0,
        rejected_count=0,
        failed_count=0,
        documents_discovered_count=0,
        documents_queued_count=0,
        created_at=timestamp,
        updated_at=timestamp,
        message="Refresh queued.",
    )


class SourceRefreshLeaseTests(IsolatedAsyncioTestCase):
    async def test_live_owner_blocks_duplicate_delivery(self):
        timestamp = datetime.now(timezone.utc)
        record = job(now=timestamp)
        owner_a, owner_b = uuid4(), uuid4()
        db = FakeSession(record)

        first = await claim_source_refresh_job(
            db,
            job_id=record.id,
            source_system="giz",
            lease_owner=owner_a,
            now=timestamp,
            lease_seconds=180,
        )
        duplicate = await claim_source_refresh_job(
            db,
            job_id=record.id,
            source_system="giz",
            lease_owner=owner_b,
            now=timestamp + timedelta(seconds=30),
            lease_seconds=180,
        )

        self.assertEqual(first.status, SourceRefreshClaimStatus.CLAIMED)
        self.assertEqual(duplicate.status, SourceRefreshClaimStatus.BUSY)
        self.assertEqual(record.lease_owner, owner_a)

    async def test_expired_takeover_resets_attempt_counts_and_fences_old_owner(self):
        timestamp = datetime.now(timezone.utc)
        record = job(status="running", now=timestamp)
        owner_a, owner_b = uuid4(), uuid4()
        record.lease_owner = owner_a
        record.lease_expires_at = timestamp - timedelta(seconds=1)
        record.created_count = 7
        record.unchanged_count = 11
        record.documents_discovered_count = 3
        db = FakeSession(record)

        takeover = await claim_source_refresh_job(
            db,
            job_id=record.id,
            source_system="giz",
            lease_owner=owner_b,
            now=timestamp,
        )
        old_heartbeat = await renew_source_refresh_lease(
            db,
            job_id=record.id,
            lease_owner=owner_a,
            now=timestamp + timedelta(seconds=1),
        )
        old_terminal = await complete_source_refresh_job(
            db,
            job_id=record.id,
            lease_owner=owner_a,
            terminal_status="completed",
            result_values={"message": "stale overwrite"},
            now=timestamp + timedelta(seconds=1),
        )

        self.assertEqual(takeover.status, SourceRefreshClaimStatus.CLAIMED)
        self.assertEqual(record.lease_owner, owner_b)
        self.assertEqual(record.created_count, 0)
        self.assertEqual(record.unchanged_count, 0)
        self.assertEqual(record.documents_discovered_count, 0)
        self.assertFalse(old_heartbeat)
        self.assertFalse(old_terminal)
        self.assertEqual(record.status, "running")

    async def test_current_owner_can_heartbeat_and_write_terminal_counters(self):
        timestamp = datetime.now(timezone.utc)
        record = job(now=timestamp)
        owner = uuid4()
        db = FakeSession(record)
        await claim_source_refresh_job(
            db,
            job_id=record.id,
            source_system="giz",
            lease_owner=owner,
            now=timestamp,
        )
        renewed = await renew_source_refresh_lease(
            db,
            job_id=record.id,
            lease_owner=owner,
            now=timestamp + timedelta(seconds=30),
        )
        completed = await complete_source_refresh_job(
            db,
            job_id=record.id,
            lease_owner=owner,
            terminal_status="partial",
            result_values={
                "fetched_count": 10,
                "created_count": 2,
                "updated_count": 3,
                "unchanged_count": 4,
                "skipped_count": 1,
                "failed_count": 0,
                "documents_discovered_count": 6,
                "documents_queued_count": 0,
                "message": "bounded partial result",
            },
            now=timestamp + timedelta(seconds=31),
        )

        self.assertTrue(renewed)
        self.assertTrue(completed)
        self.assertEqual(record.status, "partial")
        self.assertEqual(record.unchanged_count, 4)
        self.assertEqual(record.documents_discovered_count, 6)
        self.assertEqual(record.documents_queued_count, 0)
        self.assertIsNone(record.lease_owner)


class SourceRefreshContractTests(TestCase):
    def test_live_lease_not_job_age_controls_staleness(self):
        timestamp = datetime.now(timezone.utc)
        record = job(status="running", now=timestamp - timedelta(hours=2))
        record.lease_owner = uuid4()
        record.lease_expires_at = timestamp + timedelta(seconds=90)
        self.assertFalse(active_job_needs_republish(record, now=timestamp))
        record.lease_expires_at = timestamp - timedelta(microseconds=1)
        self.assertTrue(active_job_needs_republish(record, now=timestamp))

    def test_source_specific_options_are_bounded(self):
        self.assertEqual(
            validate_source_refresh_options(
                "world-bank",
                {"max_pages": 20, "rows": 100, "dry_run": True},
            ),
            {"max_pages": 20, "rows": 100, "dry_run": True},
        )
        with self.assertRaises(ValueError):
            validate_source_refresh_options("world_bank", {"max_pages": 101})
        with self.assertRaises(ValueError):
            validate_source_refresh_options("giz", {"arbitrary_url": "https://x"})
        with self.assertRaises(ValueError):
            validate_source_refresh_options("giz", {"download_documents": True})

    def test_status_dto_has_no_private_worker_or_requester_fields(self):
        record = job(status="completed")
        record.completed_at = datetime.now(timezone.utc)
        payload = tenders._source_refresh_response(record).model_dump()
        self.assertIn("display_name", payload)
        self.assertIn("unchanged_count", payload)
        self.assertIn("heartbeat_at", payload)
        self.assertNotIn("lease_owner", payload)
        self.assertNotIn("options_json", payload)
        self.assertNotIn("requested_by_user_id", payload)

    def test_connector_executors_are_not_http_routes(self):
        for executor in (
            tenders.sync_world_bank_tenders,
            tenders.sync_giz_tenders,
            tenders.sync_adb_tenders,
            tenders.sync_ebrd_tenders,
        ):
            source = inspect.getsource(executor)
            self.assertNotIn("@router", source)

    def test_operator_urls_are_async_job_responses(self):
        route_by_path = {
            route.path: route
            for route in tenders.router.routes
            if "POST" in getattr(route, "methods", set())
        }
        for source in ("world-bank", "giz", "adb", "ebrd"):
            route = route_by_path[f"/sources/{source}/sync"]
            self.assertIs(route.response_model, tenders.SourceRefreshResponse)

    def test_duplicate_publications_use_fresh_delivery_ids(self):
        record = job()
        with patch(
            "app.api.endpoints.tenders.refresh_tender_source.apply_async",
            side_effect=(
                SimpleNamespace(id="delivery-a"),
                SimpleNamespace(id="delivery-b"),
            ),
        ) as publish:
            tenders._publish_source_refresh_job(record)
            tenders._publish_source_refresh_job(record)
        first_id = publish.call_args_list[0].kwargs["task_id"]
        second_id = publish.call_args_list[1].kwargs["task_id"]
        self.assertNotEqual(first_id, second_id)
        self.assertNotEqual(first_id, str(record.id))
        self.assertEqual(
            publish.call_args_list[0].kwargs["args"],
            ["giz", str(record.id)],
        )


class OperatorRouteTests(IsolatedAsyncioTestCase):
    async def test_giz_document_coupling_is_explicitly_rejected(self):
        operator = SimpleNamespace(
            id=uuid4(), platform_role="operator", is_admin=False
        )
        with self.assertRaises(HTTPException) as raised:
            await tenders._request_source_refresh(
                source_system="giz",
                force=True,
                current_user=operator,
                db=AsyncMock(),
                trigger_kind="operator",
                options={"download_documents": True},
            )
        self.assertEqual(raised.exception.status_code, 400)

    async def test_operator_wrapper_only_calls_canonical_request_service(self):
        response = tenders.SourceRefreshResponse(
            status="queued",
            source_system="world_bank",
            display_name="World Bank",
            job_id=uuid4(),
            message="Refresh queued.",
        )
        with patch.object(
            tenders,
            "_request_source_refresh",
            new=AsyncMock(return_value=response),
        ) as request:
            returned = await tenders.request_world_bank_sync(
                max_pages=2,
                rows=50,
                active_only=True,
                dry_run=False,
                current_user=SimpleNamespace(id=uuid4()),
                db=AsyncMock(),
            )
        self.assertIs(returned, response)
        request.assert_awaited_once()
