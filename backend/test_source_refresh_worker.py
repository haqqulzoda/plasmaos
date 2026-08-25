"""Deterministic tests for durable source refresh worker execution."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.api.endpoints.tenders import SourceSyncResponse
from app.models.all_models import SourceRefreshJob
from app.workers.source_refresh_tasks import _execute_source_refresh


class FakeSession:
    def __init__(self, job: SourceRefreshJob):
        self.job = job
        self.commit_count = 0

    async def get(self, _model, job_id):
        return self.job if self.job.id == job_id else None

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        pass


class SessionContext:
    def __init__(self, session: FakeSession):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


def source_job(*, status: str = "queued") -> SourceRefreshJob:
    now = datetime.now(timezone.utc)
    return SourceRefreshJob(
        id=uuid4(),
        source_system="giz",
        requested_by_user_id=uuid4(),
        status=status,
        force=False,
        created_count=0,
        updated_count=0,
        failed_count=0,
        created_at=now,
        updated_at=now,
        message="Refresh queued.",
    )


class SourceRefreshWorkerTests(IsolatedAsyncioTestCase):
    async def test_worker_persists_terminal_counts_and_diagnostics(self):
        job = source_job()
        db = FakeSession(job)
        result = SourceSyncResponse(
            status="partial",
            source_system="giz",
            fetched_count=8,
            created_count=3,
            updated_count=2,
            skipped_count=1,
            failed_count=2,
            failure_stage="eproc_detail",
            failure_class="ReadTimeout",
            retryable=True,
            fallback_used=True,
            skip_reasons={"duplicate": 1},
            rejected_count=3,
            elapsed_ms=125,
            source_newest_published_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
            source_oldest_published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            execution_health="PASS",
            freshness_health="CURRENT",
            coverage_health="PARTIAL",
            message="GIZ sync completed with partial coverage.",
        )
        with (
            patch(
                "app.workers.source_refresh_tasks.AsyncSessionLocal",
                return_value=SessionContext(db),
            ),
            patch(
                "app.api.endpoints.tenders._run_source_refresh",
                new=AsyncMock(return_value=result),
            ),
        ):
            payload = await _execute_source_refresh("giz", job.id)

        self.assertEqual(job.status, "partial")
        self.assertEqual((job.created_count, job.updated_count, job.failed_count), (3, 2, 2))
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.completed_at)
        self.assertEqual(job.fetched_count, 8)
        self.assertEqual(job.skipped_count, 1)
        self.assertEqual(job.rejected_count, 3)
        self.assertTrue(job.fallback_used)
        self.assertEqual(job.skip_reasons, {"duplicate": 1})
        self.assertEqual(job.failure_stage, "eproc_detail")
        self.assertEqual(job.failure_class, "ReadTimeout")
        self.assertTrue(job.retryable)
        self.assertEqual(job.elapsed_ms, 125)
        self.assertEqual(
            job.source_newest_published_at,
            datetime(2026, 8, 23, tzinfo=timezone.utc),
        )
        self.assertEqual(job.execution_health, "PASS")
        self.assertEqual(job.freshness_health, "CURRENT")
        self.assertEqual(job.coverage_health, "PARTIAL")
        self.assertEqual(payload["rows_fetched"], 8)
        self.assertEqual(payload["rows_persisted"], 5)
        self.assertEqual(payload["rows_rejected"], 3)

    async def test_terminal_redelivery_does_not_run_connector_twice(self):
        job = source_job(status="completed")
        db = FakeSession(job)
        runner = AsyncMock()
        with (
            patch(
                "app.workers.source_refresh_tasks.AsyncSessionLocal",
                return_value=SessionContext(db),
            ),
            patch("app.api.endpoints.tenders._run_source_refresh", new=runner),
        ):
            payload = await _execute_source_refresh("giz", job.id)

        self.assertTrue(payload["reused"])
        runner.assert_not_awaited()
