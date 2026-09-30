"""Integration fix 3b: source refresh bookkeeping when a connector fails after saving rows.

* Reproduction: a connector persists N tenders, commits, then hits a ConnectError. The
  job was recorded as source_unavailable with 0 created; it is now "partial" with the
  true created/updated counts. A failure before any commit still records 0.
* The stale indicator treats a partial run that saved or confirmed tenders as fresh
  data (with last_success_partial for a visible note); an empty partial run does not.
* World Bank and GIZ requests retry a ConnectError exactly once, after a bounded backoff.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.models.all_models import SourceRefreshJob, Tender
from app.models.base import TenderStatus
from app.services.source_refresh_activity import source_refresh_status
from app.services.tender_sources import diagnostics
from app.services.tender_sources.base import NormalizedTender, persist_tender_batch
from app.services.tender_sources.giz import GizTenderSource
from app.services.tender_sources.world_bank import WorldBankTenderSource
from app.workers.source_refresh_tasks import _execute_source_refresh
from test_d1_04_05_freshness_truth import _database

PERSISTED = 7


def _batch(prefix: str, count: int) -> list[NormalizedTender]:
    deadline = datetime.now(UTC) + timedelta(days=20)
    return [
        NormalizedTender(
            source_system="world_bank", external_id=f"{prefix}-{n}",
            source_url=f"https://example.test/{prefix}-{n}", title=f"{prefix} tender {n}",
            description="d", deadline=deadline, status=TenderStatus.OPEN, country="Mongolia",
        )
        for n in range(count)
    ]


def _queued_job(user_id) -> SourceRefreshJob:
    now = datetime.now(UTC)
    return SourceRefreshJob(
        id=uuid4(), source_system="world_bank", requested_by_user_id=user_id, status="queued",
        force=False, created_count=0, updated_count=0, failed_count=0,
        created_at=now, updated_at=now, message="Refresh queued.",
    )


def test_connect_error_after_persisted_rows_records_a_partial_job_with_true_counts() -> None:
    async def scenario() -> None:
        async with _database("int_3b_partial") as (_name, ids, sessions, _engine):
            async def persists_then_fails(source_system, db, *, options):
                await persist_tender_batch(db, _batch("INT3B-SAVED", PERSISTED))
                await db.commit()
                # a later fetch loses the connection
                raise httpx.ConnectError("connection refused")

            async def fails_before_commit(source_system, db, *, options):
                await persist_tender_batch(db, _batch("INT3B-LOST", 3))
                raise httpx.ConnectError("connection refused")

            results = {}
            for label, runner in (("saved", persists_then_fails), ("lost", fails_before_commit)):
                async with sessions() as db:
                    job = _queued_job(ids["user_a"])
                    db.add(job)
                    await db.commit()
                with (
                    patch("app.workers.source_refresh_tasks.AsyncSessionLocal", sessions),
                    patch("app.api.endpoints.tenders._run_source_refresh", new=AsyncMock(side_effect=runner)),
                ):
                    await _execute_source_refresh("world_bank", job.id)
                async with sessions() as db:
                    results[label] = await db.get(SourceRefreshJob, job.id)

            saved = results["saved"]
            assert saved.status == "partial"
            assert (saved.created_count, saved.updated_count, saved.unchanged_count) == (PERSISTED, 0, 0)
            assert saved.failure_class == "ConnectError" and saved.retryable is True
            assert f"{PERSISTED} created" in saved.message
            lost = results["lost"]
            assert lost.status == "source_unavailable"
            assert (lost.created_count, lost.updated_count, lost.unchanged_count) == (0, 0, 0)
            async with sessions() as db:
                assert await db.scalar(select(func.count()).where(Tender.external_id.like("INT3B-SAVED-%"))) == PERSISTED
                assert await db.scalar(select(func.count()).where(Tender.external_id.like("INT3B-LOST-%"))) == 0

                # Stale indicator: the partial run with data is the last success, with a note.
                items = {item.source_system: item for item in await source_refresh_status(db)}
                world_bank = items["world_bank"]
                assert world_bank.last_success_at is not None and world_bank.last_success_partial is True
                assert world_bank.last_partial.created_count == PERSISTED

                # A later partial run that saved nothing is not fresh data: the earlier
                # partial run with data stays the last success.
                empty = _queued_job(ids["user_a"])
                empty.status, empty.completed_at = "partial", datetime.now(UTC) + timedelta(minutes=5)
                db.add(empty)
                await db.commit()
                items = {item.source_system: item for item in await source_refresh_status(db)}
                assert items["world_bank"].last_success_at == world_bank.last_success_at
                assert items["world_bank"].last_success_partial is True
                assert items["world_bank"].last_partial.job_id == empty.id  # newest partial still reported

                # A clean refresh afterwards clears the partial note.
                clean = _queued_job(ids["user_a"])
                clean.status, clean.completed_at = "completed", datetime.now(UTC) + timedelta(minutes=10)
                db.add(clean)
                await db.commit()
                items = {item.source_system: item for item in await source_refresh_status(db)}
                assert items["world_bank"].last_success_partial is False
                assert items["world_bank"].last_success_at == clean.completed_at

    asyncio.run(scenario())


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _client(*outcomes):
    calls = []

    async def get(url, params=None):
        calls.append(url)
        outcome = outcomes[min(len(calls), len(outcomes)) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    client = type("Client", (), {"get": staticmethod(get)})()
    return client, calls


@pytest.fixture
def sleeps(monkeypatch):
    recorded: list[float] = []

    async def fake_sleep(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setenv("SOURCE_CONNECT_RETRY_BACKOFF_SECONDS", "5")
    return recorded


def test_world_bank_retries_a_connect_error_once_after_a_bounded_backoff(sleeps) -> None:
    source = WorldBankTenderSource()
    ok = _Response({"procnotices": []})
    client, calls = _client(httpx.ConnectError("refused"), ok)
    assert asyncio.run(source._get_json(client, {})) == {"procnotices": []}
    assert len(calls) == 2 and len(sleeps) == 1 and 5.0 <= sleeps[0] <= 6.0

    sleeps.clear()
    client, calls = _client(httpx.ConnectError("refused"), httpx.ConnectError("refused"), ok)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(source._get_json(client, {}))
    assert len(calls) == 2 and len(sleeps) == 1  # exactly one retry

    # Other failures keep the existing quick retries (max_retries=2).
    sleeps.clear()
    client, calls = _client(httpx.ReadTimeout("slow"))
    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(source._get_json(client, {}))
    assert len(calls) == 3 and sleeps == [0.5, 1.0]


def test_giz_retries_a_connect_error_once_after_a_bounded_backoff(sleeps) -> None:
    source = GizTenderSource()
    calls = []
    request = httpx.Request("GET", "https://www.giz.de/en/workingwithgiz/tenders.html")

    async def fake_request(method, url, **kwargs):
        calls.append(url)
        if len(calls) == 1 or kwargs.get("_always_fail"):
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, request=request, content=b"ok")

    client = type("Client", (), {"request": staticmethod(fake_request)})()
    response = asyncio.run(source._request(client, "GET", str(request.url)))
    assert response.status_code == 200 and len(calls) == 2
    assert len(sleeps) == 1 and 5.0 <= sleeps[0] <= 6.0

    sleeps.clear()
    calls.clear()

    async def always_refused(method, url, **kwargs):
        calls.append(url)
        raise httpx.ConnectError("refused", request=request)

    client = type("Client", (), {"request": staticmethod(always_refused)})()
    with pytest.raises(httpx.ConnectError):
        asyncio.run(source._request(client, "GET", str(request.url)))
    assert len(calls) == 2 and len(sleeps) == 1


def test_connect_backoff_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_CONNECT_RETRY_BACKOFF_SECONDS", "999")
    assert 30.0 <= diagnostics.connect_retry_backoff_seconds() <= 31.0
    monkeypatch.setenv("SOURCE_CONNECT_RETRY_BACKOFF_SECONDS", "not-a-number")
    assert 5.0 <= diagnostics.connect_retry_backoff_seconds() <= 6.0
    assert diagnostics.is_connect_error(httpx.ConnectError("x")) and not diagnostics.is_connect_error(httpx.ReadTimeout("x"))
