from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.api.deps import require_approved_user
from app.api.endpoints.tenders import (
    SourceRefreshResponse,
    SourceSyncResponse,
    _request_source_refresh,
    _source_refresh_response,
)
from app.models.all_models import SourceRefreshJob
from app.services.source_registry import adapt_execution_result


def user(*, approval_status: str = "approved", role: str = "pilot_user"):
    return SimpleNamespace(
        id=uuid4(),
        approval_status=approval_status,
        platform_role=role,
        is_admin=role == "admin",
        email="pilot@example.com",
    )


class ScalarResult:
    def __init__(self, value=None):
        self.value = value

    def scalars(self):
        return self

    def first(self):
        return self.value


class FakeSession:
    def __init__(self, query_values=None):
        self.query_values = list(query_values or [])
        self.job = None

    async def execute(self, _query):
        return ScalarResult(self.query_values.pop(0) if self.query_values else None)

    def add(self, job):
        if job.id is None:
            job.id = uuid4()
        now = datetime.now(timezone.utc)
        job.created_at = now
        job.updated_at = now
        self.job = job

    async def commit(self):
        if self.job is not None:
            self.job.updated_at = datetime.now(timezone.utc)

    async def rollback(self):
        pass

    async def refresh(self, _job):
        pass

    async def get(self, _model, _job_id):
        return self.job


class SourceRefreshTests(IsolatedAsyncioTestCase):
    def test_refresh_response_exposes_structured_counts_fallback_and_own_timestamp(self):
        completed = datetime(2026, 8, 24, 1, 2, 3, tzinfo=timezone.utc)
        newest = datetime(2026, 8, 20, tzinfo=timezone.utc)
        job = SourceRefreshJob(
            id=uuid4(),
            source_system="adb",
            requested_by_user_id=uuid4(),
            status="partial",
            force=False,
            fetched_count=35,
            created_count=0,
            updated_count=35,
            skipped_count=0,
            rejected_count=0,
            failed_count=0,
            fallback_used=True,
            skip_reasons={},
            failure_stage="listing",
            failure_class="HTTPStatusError",
            retryable=False,
            elapsed_ms=321,
            source_newest_published_at=newest,
            source_oldest_published_at=datetime(2026, 1, 27, tzinfo=timezone.utc),
            created_at=completed,
            updated_at=completed,
            started_at=completed,
            completed_at=completed,
            message="ADB partial fallback.",
        )

        response = _source_refresh_response(job)

        self.assertEqual(response.fetched_count, 35)
        self.assertEqual(response.updated_count, 35)
        self.assertTrue(response.fallback_used)
        self.assertNotIn("failure_class", response.model_dump())
        self.assertEqual(response.completed_at, completed)
        self.assertEqual(response.last_updated, completed)
        self.assertEqual(response.source_newest_published_at, newest)
        self.assertIsNotNone(response.source_age_days)

    async def test_approved_user_can_refresh_giz(self):
        db = FakeSession([None, None])
        with patch(
            "app.api.endpoints.tenders.refresh_tender_source.apply_async",
            return_value=SimpleNamespace(id="celery-job-id"),
        ) as enqueue:
            response = await _request_source_refresh(
                source_system="giz",
                force=False,
                current_user=user(),
                db=db,
            )

        self.assertIsInstance(response, SourceRefreshResponse)
        self.assertEqual(response.status, "queued")
        enqueue.assert_called_once()

    async def test_approved_user_cannot_force_refresh(self):
        with self.assertRaises(HTTPException) as raised:
            await _request_source_refresh(
                source_system="giz",
                force=True,
                current_user=user(),
                db=FakeSession(),
            )
        self.assertEqual(raised.exception.status_code, 403)
        self.assertNotIn("Operator access required", raised.exception.detail)

    async def test_pending_user_cannot_refresh(self):
        with self.assertRaises(HTTPException) as raised:
            await require_approved_user(user(approval_status="pending"))
        self.assertEqual(raised.exception.status_code, 403)

    async def test_admin_can_force_refresh(self):
        db = FakeSession([None])
        with patch(
            "app.api.endpoints.tenders.refresh_tender_source.apply_async",
            return_value=SimpleNamespace(id="celery-job-id"),
        ):
            response = await _request_source_refresh(
                source_system="giz",
                force=True,
                current_user=user(role="admin"),
                db=db,
            )
        self.assertEqual(response.status, "queued")
        self.assertTrue(db.job.force)

    async def test_repeated_click_reuses_active_job(self):
        now = datetime.now(timezone.utc)
        active = SourceRefreshJob(
            id=uuid4(),
            source_system="giz",
            requested_by_user_id=uuid4(),
            status="running",
            force=False,
            created_count=0,
            updated_count=0,
            failed_count=0,
            created_at=now,
            updated_at=now,
            started_at=now,
            message="Refreshing.",
        )
        runner = AsyncMock()
        with patch("app.api.endpoints.tenders._run_source_refresh", new=runner):
            response = await _request_source_refresh(
                source_system="giz",
                force=False,
                current_user=user(),
                db=FakeSession([active]),
            )
        self.assertEqual(response.status, "running")
        self.assertTrue(response.reused)
        self.assertEqual(response.message, "Already refreshing.")
        runner.assert_not_awaited()

    def test_unavailable_source_is_normalized_without_losing_cached_data(self):
        result = SourceSyncResponse(
            status="source_unavailable",
            source_system="giz",
            failed_count=1,
            message="GIZ sync failed while fetching public tender pages.",
        )
        canonical = adapt_execution_result("giz", result)
        self.assertEqual(canonical.status, "source_unavailable")
        self.assertEqual((canonical.created_count, canonical.updated_count, canonical.failed_count), (0, 0, 1))
        self.assertEqual(canonical.message, result.message)

    def test_parser_failure_is_not_misreported_as_source_unavailable(self):
        result = SourceSyncResponse(
            status="failed",
            source_system="giz",
            failed_count=1,
            failure_stage="listing",
            failure_class="XMLSyntaxError",
            retryable=False,
            message="GIZ connector failed during listing.",
        )
        canonical = adapt_execution_result("giz", result)
        self.assertEqual(canonical.status, "failed")
        self.assertEqual(canonical.failure_stage, "listing")
        self.assertEqual(canonical.failure_class, "XMLSyntaxError")
        self.assertFalse(canonical.retryable)

    def test_registry_adapter_preserves_counts_zeroes_and_safe_failure_state(self):
        for fields in (
            {"created_count": 2, "updated_count": 3, "unchanged_count": 4, "skipped_count": 5, "failed_count": 6},
            {"new_count": 2, "updated": 3, "unchanged": 4, "skipped": 5, "failed": 6},
        ):
            with self.subTest(fields=fields):
                result = adapt_execution_result("giz", SimpleNamespace(status="partial", **fields))
                self.assertEqual(result.source_system, "giz")
                self.assertEqual(result.status, "partial")
                self.assertEqual((result.created_count, result.updated_count, result.unchanged_count,
                                  result.skipped_count, result.failed_count), (2, 3, 4, 5, 6))
                self.assertEqual(result.rejected_count, 11)
        zero = adapt_execution_result("giz", SimpleNamespace(status="success", new_count=0,
                                     created_count=99, skipped_count=0, failed_count=0))
        self.assertEqual(zero.status, "completed")
        self.assertEqual((zero.created_count, zero.updated_count, zero.unchanged_count,
                          zero.skipped_count, zero.failed_count, zero.rejected_count), (0, 0, 0, 0, 0, 0))
        self.assertEqual(adapt_execution_result("giz", SimpleNamespace(status="unknown")).status, "failed")

    async def test_enqueue_failure_is_persisted_as_dispatch_failure(self):
        db = FakeSession([None, None])
        with patch(
            "app.api.endpoints.tenders.refresh_tender_source.apply_async",
            side_effect=ConnectionError("redis unavailable"),
        ):
            response = await _request_source_refresh(
                source_system="giz",
                force=False,
                current_user=user(),
                db=db,
            )

        self.assertEqual(response.status, "failed")
        self.assertEqual(response.failed_count, 1)
        self.assertIn("dispatch: ConnectionError", response.message)
