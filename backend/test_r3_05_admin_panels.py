"""R3 Task 5: admin/operator panels for sources, analysis runs and organizations.

Access control, passive reads, no private content, and the analysis retry through the
customer's explicit re-run path.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import deps
from app.api.endpoints import admin_panels as endpoints
from app.core.agents.pursuit_analyzer import VerifiedFact
from app.models.all_models import AdminActivityEvent, SourceRefreshJob, TenderDocument
from app.models.base import MembershipState, TenderEngagementOrigin, TenderEngagementStatus
from app.models.pursuit_analysis import AnalysisPackItem, AnalysisRun
from app.models.tenancy import Membership
from app.models.user import User
from app.schemas.tenancy import PursuitAnalysisStartRequest
from app.services import admin_panels
from app.services import pursuit_analysis as analysis_service
from app.services.private_documents import build_analysis_pack_candidate
from app.services.pursuit_analysis import create_analysis_run, process_analysis_run
from app.services.pursuits import get_or_create_source_pursuit
from scripts import test_s0_5b4_baseline as support
from test_d2_01_own_experience import SUBSTATION, _fact
from test_w2_organization_pursuit_foundation import W1_HEAD, _seed_w1


HEAD = "20261011_0001_r3_organization_record_events"
SECRET_REASON = "provider said: confidential tender wording 'Substation design for Navoi' leaked"


def test_demo_marker_matches_the_seed_command() -> None:
    seed = (Path(__file__).parent / "scripts" / "demo" / "seed_demo.py").read_text(encoding="utf-8")
    assert f'PROFILE_MARKER = "{admin_panels.DEMO_PROFILE_MARKER}"' in seed


def test_panels_are_operator_only() -> None:
    dependencies = [dependency.dependency for dependency in endpoints.router.dependencies]
    assert deps.require_operator in dependencies

    async def check() -> None:
        pilot = User(email="pilot@example.org", name="Pilot", google_id="g", approval_status="approved",
                     platform_role="pilot_user", is_admin=False)
        with pytest.raises(HTTPException) as denied:
            await deps.require_operator(current_user=pilot)
        assert denied.value.status_code == 403
        operator = User(email="op@example.org", name="Op", google_id="o", approval_status="approved",
                        platform_role="operator", is_admin=False)
        assert await deps.require_operator(current_user=operator) is operator

    asyncio.run(check())


def test_admin_panels_passive_private_and_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_REFRESH_SCHEDULE", "world_bank=24h,uzex=24h")
    monkeypatch.setattr(endpoints, "dispatch_run_ids", lambda ids: None)

    async def scenario() -> None:
        database = support.database_name("r3_05_admin")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                org_a = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"])
                org_b = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_b"])
                owner_a = await connection.fetchval("SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", org_a, ids["user_a"])
                await connection.execute(
                    "UPDATE company_profiles SET notes=$2 WHERE id=$1",
                    ids["profile_b"], '[plasma-demo-seed] {"demo": true} Synthetic demonstration company',
                )
                await connection.execute(
                    "UPDATE users SET platform_role='operator', approval_status='approved' WHERE id=$1", ids["multi"],
                )
            finally:
                await connection.close()
            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                await _flow(sessions, ids, org_a, org_b, owner_a, monkeypatch)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _counts(db) -> dict[str, int]:
    tables = ("analysis_runs", "pursuit_analysis_runs", "source_refresh_jobs", "admin_activity_events", "organizations",
              "memberships", "organization_pursuits", "notification_outbox", "email_deliveries")
    counts = {}
    for table in tables:
        if await db.scalar(text("SELECT to_regclass(:name)"), {"name": table}):
            counts[table] = await db.scalar(text(f"SELECT count(*) FROM {table}"))
    return counts


async def _flow(sessions, ids, org_a, org_b, owner_a, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    async with sessions() as db:
        source = await get_or_create_source_pursuit(
            db, organization_id=org_a, actor_user_id=ids["user_a"], actor_membership_id=owner_a, tender_id=ids["tender"],
            stage=TenderEngagementStatus.SAVED, legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
        )
        pursuit_id = source.pursuit.id
        document = TenderDocument(
            tender_id=ids["tender"], file_url="r305.pdf", file_type="pdf", source_document_url="https://example.invalid/r305.pdf",
            source_document_type="RFP", sha256=hashlib.sha256(SUBSTATION.encode()).hexdigest(), parsed_text=SUBSTATION,
        )
        db.add(document)
        db.add(SourceRefreshJob(
            source_system="world_bank", requested_by_user_id=ids["user_a"], status="completed", trigger_kind="scheduled",
            options_json={}, created_count=7, updated_count=3, fetched_count=12, created_at=now - timedelta(days=3),
            started_at=now - timedelta(days=3), completed_at=now - timedelta(days=3),
        ))
        await db.commit()
        run_ids = []
        for _ in range(4):
            candidate = await build_analysis_pack_candidate(db, organization_id=org_a, pursuit_id=pursuit_id)
            started = await create_analysis_run(
                db, organization_id=org_a, pursuit_id=pursuit_id, membership_id=owner_a,
                request=PursuitAnalysisStartRequest(candidate_sha256=candidate.candidate_sha256, analysis_language="ru",
                                                    source_document_ids=[document.id]),
            )
            run_ids.append(started.analysis_run_id)

    async def extracted(sealed, language):
        item = sealed[0]
        return [VerifiedFact(item.pack_item_id, _fact(original_quote=SUBSTATION, normalized_text=SUBSTATION), 0, len(SUBSTATION), None, 1)]

    monkeypatch.setattr(analysis_service.pursuit_analyzer, "analyze_pack_items", extracted)
    async with sessions() as db:
        for run_id in run_ids[2:]:
            await process_analysis_run(db, run_id, worker_id="r3-05")
    failed, stuck, long_run, quick = run_ids
    async with sessions() as db:
        await db.execute(update(AnalysisRun).where(AnalysisRun.id == failed).values(
            status="FAILED", failure_stage="EXTRACTION", failure_reason=SECRET_REASON, attempt_count=3,
            started_at=now - timedelta(minutes=3), completed_at=now - timedelta(minutes=2),
            extraction_diagnostics={"failure_code": "PROVIDER_ACCOUNT", "error_type": "ProviderAccountError"},
        ))
        await db.execute(update(AnalysisRun).where(AnalysisRun.id == stuck).values(
            status="RUNNING", attempt_count=3, started_at=now - timedelta(hours=2), lease_until=now - timedelta(hours=1),
            lease_owner="gone-worker",
        ))
        await db.execute(update(AnalysisRun).where(AnalysisRun.id == long_run).values(
            started_at=now - timedelta(minutes=30), completed_at=now - timedelta(minutes=5),
        ))
        await db.commit()

    async with sessions() as db:
        before = await _counts(db)
        sources = await endpoints.sources_panel(db=db)
        runs = await endpoints.analysis_runs_panel(kind=["failed", "stuck", "long"], limit=100, db=db)
        failed_only = await endpoints.analysis_runs_panel(kind=["failed"], limit=100, db=db)
        organizations = await endpoints.organizations_panel(db=db)
        # Passive: reads write nothing.
        assert await _counts(db) == before
        with pytest.raises(HTTPException) as bad_kind:
            await endpoints.analysis_runs_panel(kind=["everything"], limit=10, db=db)
        assert bad_kind.value.status_code == 422

    by_source = {item.source_system: item for item in sources}
    world_bank = by_source["world_bank"]
    assert (world_bank.status, world_bank.new_count, world_bank.updated_count) == ("completed", 7, 3)
    assert world_bank.stale is True and world_bank.can_run_now is True and world_bank.scheduled_cadence_seconds == 86400
    assert world_bank.next_scheduled_run_at is not None and world_bank.last_success_at is not None
    assert by_source["uzex"].status == "never_run" and by_source["uzex"].last_attempt_at is None

    listed = {item.analysis_run_id: item for item in runs}
    assert set(listed) == {failed, stuck, long_run} and quick not in listed
    assert [item.analysis_run_id for item in failed_only] == [failed]
    assert listed[failed].failure_code == "PROVIDER_ACCOUNT" and listed[failed].retry_allowed
    assert listed[stuck].stuck and listed[stuck].retry_allowed and listed[stuck].latency_ms >= 7_000_000
    assert listed[long_run].long and not listed[long_run].retry_allowed and listed[long_run].status == "COMPLETED"
    assert listed[failed].organization_name == "Same Name Company" and listed[failed].model_name

    organizations_by_id = {item.organization_id: item for item in organizations}
    a, b = organizations_by_id[org_a], organizations_by_id[org_b]
    assert (a.members_count, a.pursuits_count, a.demo) == (1, 1, False) and a.last_activity_at is not None
    assert (b.members_count, b.pursuits_count, b.demo) == (1, 0, True) and b.last_activity_at is None

    # No private content: no failure text, no document or requirement wording, no e-mail addresses.
    payload = json.dumps([item.model_dump(mode="json") for item in [*sources, *runs, *organizations]])
    for private in (SECRET_REASON, SUBSTATION[:40], "Navoi", "@same-domain.invalid", "Synthetic demonstration"):
        assert private not in payload

    # Retry: a new run for the same requester with the same documents; the old run is untouched.
    async with sessions() as db:
        operator = await db.get(User, ids["multi"])
        retried = await endpoints.retry_analysis_run_endpoint(run_id=failed, current_user=operator, db=db)
        assert retried.retried_run_id == failed and retried.status == "QUEUED"
        new_run = await db.get(AnalysisRun, retried.analysis_run_id)
        old_run = await db.get(AnalysisRun, failed)
        assert new_run.requested_by_membership_id == owner_a and new_run.analysis_language == "ru"
        assert old_run.status == "FAILED" and old_run.failure_reason == SECRET_REASON
        new_items = (await db.scalars(select(AnalysisPackItem.tender_document_id).where(AnalysisPackItem.pack_id == new_run.pack_id))).all()
        assert list(new_items) == [document.id]
        event = await db.scalar(select(AdminActivityEvent).where(AdminActivityEvent.action == "ANALYSIS_RUN_RETRIED"))
        assert event.actor_user_id == ids["multi"] and event.target_resource_id == str(failed)
        assert event.metadata_json["new_analysis_run_id"] == str(new_run.id)
        stuck_retry = await endpoints.retry_analysis_run_endpoint(run_id=stuck, current_user=operator, db=db)
        assert stuck_retry.analysis_run_id != retried.analysis_run_id
        for run_id, code in ((quick, "NOT_RETRYABLE"), (long_run, "NOT_RETRYABLE")):
            with pytest.raises(HTTPException) as refused:
                await endpoints.retry_analysis_run_endpoint(run_id=run_id, current_user=operator, db=db)
            assert refused.value.status_code == 409 and refused.value.detail["code"] == code
        # A requester who left the organization cannot be re-run for.
        await db.execute(update(Membership).where(Membership.id == owner_a).values(
            state=MembershipState.REVOKED, revoked_at=now,
        ))
        await db.execute(update(AnalysisRun).where(AnalysisRun.id == quick).values(status="FAILED", completed_at=now))
        await db.commit()
        with pytest.raises(HTTPException) as gone:
            await endpoints.retry_analysis_run_endpoint(run_id=quick, current_user=operator, db=db)
        assert gone.value.detail["code"] == "REQUESTER_INACTIVE"
        assert await db.scalar(select(func.count(AnalysisRun.id))) == 6
