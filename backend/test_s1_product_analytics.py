"""Sprint 1: server-side product events, the AI cost ledger, admin metrics and the smoke rule.

Events and cost rows are produced by the real service paths (sign-in, invitation, analysis
start/finish, review, view events) against a disposable database; properties are codes and
numbers only; the analytics tables are append-only; metrics are admin-only.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException, Response
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import deps
from app.api.endpoints import admin_metrics as metrics_endpoints
from app.api.endpoints import auth as auth_endpoints
from app.api.endpoints import eoi as eoi_endpoints
from app.api.endpoints import pursuits as pursuit_endpoints
from app.api.endpoints import tenders as tender_endpoints
from app.core import ai_usage
from app.core.agents.pursuit_analyzer import ProviderAccountError, VerifiedFact
from app.core.ai_pricing import price_table
from app.models.all_models import TenderDocument
from app.models.base import TenderEngagementOrigin, TenderEngagementStatus
from app.models.product_analytics import AICallCost, ProductEvent
from app.models.pursuit_analysis import PursuitRequirement
from app.models.user import User
from app.schemas.tenancy import AnalysisReviewAssertionRequest, PursuitAnalysisStartRequest
from app.services import product_analytics
from app.services import pursuit_analysis as analysis_service
from app.services.invitations import create_email_invitation
from app.services.private_documents import build_analysis_pack_candidate
from app.services.product_analytics import clean_properties, record_view_event, stage_product_event
from app.services.pursuit_analysis import append_review_assertion, create_analysis_run, process_analysis_run
from app.services.pursuits import get_or_create_source_pursuit
from scripts import test_s0_5b4_baseline as support
from test_d2_01_own_experience import SUBSTATION, _fact
from test_w2_organization_pursuit_foundation import W1_HEAD, _seed_w1


HEAD = "20261012_0002_s1_product_analytics"


# ---- units --------------------------------------------------------------------------------------------

def test_properties_keep_codes_and_numbers_only() -> None:
    run_id = uuid4()
    cleaned = clean_properties({
        "language": "en", "document_count": 2, "ratio": 0.5, "new_account": True, "run": run_id,
        "reason": "Bidder failed because of the substation design", "Bad-Key": "x", "nan": float("nan"),
        "nested": {"a": 1}, "none": None,
    })
    assert cleaned == {"language": "en", "document_count": 2, "ratio": 0.5, "new_account": True, "run": str(run_id)}
    with pytest.raises(ValueError):
        stage_product_event(SimpleNamespace(add=lambda _: None), "document_text_viewed")


def test_price_table_estimates_and_never_guesses(monkeypatch: pytest.MonkeyPatch) -> None:
    table = price_table()
    # 1M input at 0.75 + (0.5M output + 0.5M thinking) at 3.75 = 4.50
    assert table.estimate("gemini-3.8-flash", 1_000_000, 500_000, 500_000) == Decimal("4.500000")
    assert table.estimate("unknown-model", 10, 10, 0) is None
    assert table.estimate("gemini-3.8-flash", None, None, None) is None
    monkeypatch.setenv("AI_PRICE_TABLE_JSON", json.dumps({"version": "test-1", "models": {"m": {"input": 1, "output": 2}}}))
    custom = price_table()
    assert custom.version == "test-1" and custom.estimate("m", 1_000_000, 1_000_000, 0) == Decimal("3.000000")
    monkeypatch.setenv("AI_PRICE_TABLE_JSON", "{not json")
    assert price_table().version == "gemini-2026-10-unverified"


def _response(prompt: int, output: int, total: int):
    return SimpleNamespace(usage_metadata=SimpleNamespace(
        prompt_token_count=prompt, candidates_token_count=output, total_token_count=total))


def test_usage_collector_spans_threads_and_tasks() -> None:
    async def scenario() -> list:
        with ai_usage.collect_ai_usage() as calls:
            started = 0.0

            def provider() -> None:
                ai_usage.record_ai_call("gemini-3.8-flash", started=started, response=_response(100, 20, 150), succeeded=True)

            await asyncio.gather(asyncio.to_thread(provider), asyncio.create_task(asyncio.to_thread(provider)))
            ai_usage.record_ai_call("gemini-3.8-flash", started=started, succeeded=False)
        ai_usage.record_ai_call("ignored", started=started, succeeded=True)  # outside a collector: no-op
        return calls

    calls = asyncio.run(scenario())
    assert [(call.outcome, call.input_tokens, call.output_tokens, call.thinking_tokens) for call in calls] == [
        ("SUCCEEDED", 100, 20, 30), ("SUCCEEDED", 100, 20, 30), ("FAILED", None, None, None)]


def test_smoke_auto_pick_needs_a_long_official_notice() -> None:
    from scripts import analysis_smoke

    lengths = {"short": 4_999, "none": None, "long": 5_000, "longer": 9_000}

    class FakeApi:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def call(self, method, path, payload=None):  # noqa: ARG002
            self.calls.append(path)
            if path.startswith("/explorer/tenders"):
                return 200, {"items": [{"tender": {"id": key}} for key in lengths]}
            key = path.split("/")[2]
            notice = None if lengths[key] is None else {"character_count": lengths[key]}
            return 200, {"documents": {"state": "READY", "data": {"official_notice": notice}}}

    api = FakeApi()
    assert analysis_smoke.pick_reoi(api) == "long"
    assert api.calls[1:] == ["/tenders/short/details", "/tenders/none/details", "/tenders/long/details"]
    lengths.pop("long"), lengths.pop("longer")
    with pytest.raises(analysis_smoke.LiveSmokeError, match="5000 characters"):
        analysis_smoke.pick_reoi(FakeApi())


def test_metrics_are_admin_only_and_view_events_hang_on_routes() -> None:
    assert deps.require_admin in [dependency.dependency for dependency in metrics_endpoints.router.dependencies]

    def tracked(router, path: str) -> bool:
        route = next(route for route in router.routes if getattr(route, "path", None) == path and "GET" in route.methods)
        return any(getattr(dependency.dependency, "__qualname__", "").startswith("track_view")
                   for dependency in route.dependencies)

    assert tracked(tender_endpoints.router, "/{tender_id}/details")
    assert tracked(pursuit_endpoints.router, "/{pursuit_id}")
    assert tracked(eoi_endpoints.router, "/{pursuit_id}/eoi-artifacts/{artifact_id}/download")


# ---- end to end against a disposable database ---------------------------------------------------------

def test_events_costs_and_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        database = support.database_name("s1_analytics")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                org_a = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"])
                owner_a = await connection.fetchval(
                    "SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", org_a, ids["user_a"])
            finally:
                await connection.close()
            engine = create_async_engine(support.target_url(database), pool_size=6)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                await _flow(sessions, ids, org_a, owner_a, monkeypatch)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _flow(sessions, ids, org_a, owner_a, monkeypatch) -> None:
    # Invitation sent, then accepted on first sign-in (sign_in + invite_accepted).
    async with sessions() as db:
        issued = await create_email_invitation(
            db, organization_id=org_a, actor_membership_id=owner_a, email="new.analyst@example.org")
        await db.commit()

    identity = {"email": "new.analyst@example.org", "sub": "google-new-analyst", "name": "New Analyst", "avatar_url": None}

    async def verified(_payload):
        return identity

    monkeypatch.setattr(auth_endpoints, "verify_bridge_assertion", verified)
    async with sessions() as db:
        await auth_endpoints.google_auth_bridge(
            payload=auth_endpoints.GoogleAuthRequest(google_id=identity["sub"], email=identity["email"], name="New Analyst"),
            response=Response(), db=db,
        )

    # Two analyses: one completes (two provider calls), one fails terminally (one failed call).
    async with sessions() as db:
        source = await get_or_create_source_pursuit(
            db, organization_id=org_a, actor_user_id=ids["user_a"], actor_membership_id=owner_a, tender_id=ids["tender"],
            stage=TenderEngagementStatus.SAVED, legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
        )
        pursuit_id = source.pursuit.id
        document = TenderDocument(
            tender_id=ids["tender"], file_url="s1.pdf", file_type="pdf", source_document_url="https://example.invalid/s1.pdf",
            source_document_type="RFP", sha256=hashlib.sha256(SUBSTATION.encode()).hexdigest(), parsed_text=SUBSTATION,
        )
        db.add(document)
        await db.commit()
        run_ids = []
        for _ in range(2):
            candidate = await build_analysis_pack_candidate(db, organization_id=org_a, pursuit_id=pursuit_id)
            started = await create_analysis_run(
                db, organization_id=org_a, pursuit_id=pursuit_id, membership_id=owner_a,
                request=PursuitAnalysisStartRequest(candidate_sha256=candidate.candidate_sha256, analysis_language="en",
                                                    source_document_ids=[document.id]),
            )
            run_ids.append(started.analysis_run_id)

    def provider_call(model: str, prompt_tokens: int, succeeded: bool) -> None:
        ai_usage.record_ai_call(model, started=0.0, response=_response(prompt_tokens, 1_000, prompt_tokens + 1_500),
                                succeeded=succeeded)

    async def extracted(sealed, language):
        await asyncio.to_thread(provider_call, "gemini-3.8-flash", 10_000, True)
        await asyncio.to_thread(provider_call, "gemini-3.8-flash", 20_000, True)
        item = sealed[0]
        return [VerifiedFact(item.pack_item_id, _fact(original_quote=SUBSTATION, normalized_text=SUBSTATION), 0, len(SUBSTATION), None, 1)]

    async def refused(sealed, language):
        await asyncio.to_thread(provider_call, "gemini-3.8-flash", 5_000, False)
        raise ProviderAccountError(402)

    monkeypatch.setattr(analysis_service.pursuit_analyzer, "analyze_pack_items", extracted)
    async with sessions() as db:
        await process_analysis_run(db, run_ids[0], worker_id="s1")
    monkeypatch.setattr(analysis_service.pursuit_analyzer, "analyze_pack_items", refused)
    async with sessions() as db:
        with pytest.raises(ProviderAccountError):
            await process_analysis_run(db, run_ids[1], worker_id="s1")

    async with sessions() as db:
        requirement_id = await db.scalar(select(PursuitRequirement.id).where(PursuitRequirement.analysis_run_id == run_ids[0]))
        await append_review_assertion(
            db, organization_id=org_a, pursuit_id=pursuit_id, run_id=run_ids[0], membership_id=owner_a,
            request=AnalysisReviewAssertionRequest(
                target_kind="REQUIREMENT", target_id=requirement_id, new_coverage_state="SUPPORTED",
                new_review_state="CONFIRMED", reason="Confirmed against the substation design reference",
            ),
        )

    # View events: written in their own session after the response, organization resolved.
    await record_view_event("tender_viewed", user_id=ids["user_a"], selected_organization_id=None,
                            tender_id=ids["tender"], session_factory=sessions)
    await record_view_event("workspace_opened", user_id=ids["user_a"], selected_organization_id=None,
                            pursuit_id=pursuit_id, session_factory=sessions)
    # A view under an organization the user does not belong to is not recorded, and never raises.
    await record_view_event("tender_viewed", user_id=ids["user_a"], selected_organization_id=uuid4(),
                            session_factory=sessions)

    async with sessions() as db:
        events = (await db.scalars(select(ProductEvent).order_by(ProductEvent.occurred_at, ProductEvent.event_name))).all()
        by_name: dict[str, list[ProductEvent]] = {}
        for event in events:
            by_name.setdefault(event.event_name, []).append(event)
        assert set(by_name) == {
            "invite_sent", "invite_accepted", "sign_in", "analysis_started", "analysis_completed", "analysis_failed",
            "review_confirmed", "tender_viewed", "workspace_opened",
        }
        assert len(by_name["analysis_started"]) == 2 and len(by_name["tender_viewed"]) == 1
        assert by_name["invite_sent"][0].subject_id == issued.invitation.id
        assert by_name["invite_sent"][0].actor_user_id == ids["user_a"]
        accepted = by_name["invite_accepted"][0]
        sign_in = by_name["sign_in"][0]
        assert accepted.organization_id == org_a and sign_in.organization_id == org_a
        assert sign_in.actor_user_id == accepted.actor_user_id and sign_in.properties["new_account"] is True
        completed = by_name["analysis_completed"][0]
        assert (completed.organization_id, completed.actor_membership_id, completed.analysis_run_id) == (org_a, owner_a, run_ids[0])
        assert completed.actor_user_id == ids["user_a"] and completed.properties["time_to_result_ms"] >= 0
        failed = by_name["analysis_failed"][0]
        assert failed.analysis_run_id == run_ids[1] and failed.properties["failure_stage"] == "EXTRACTION"
        assert by_name["review_confirmed"][0].subject_id == requirement_id
        viewed = by_name["tender_viewed"]
        assert viewed[0].organization_id == org_a and viewed[0].tender_id == ids["tender"] and viewed[0].actor_membership_id == owner_a
        assert by_name["workspace_opened"][0].organization_id == org_a
        # No document content, names, e-mails or free text anywhere in the events.
        dumped = json.dumps([event.properties for event in events])
        for secret in ("substation", "Substation", "new.analyst", "New Analyst", "Confirmed against"):
            assert secret not in dumped

        costs = (await db.scalars(select(AICallCost).order_by(AICallCost.input_tokens))).all()
        assert [(cost.subject_id, cost.outcome, cost.input_tokens) for cost in costs] == [
            (run_ids[1], "FAILED", 5_000), (run_ids[0], "SUCCEEDED", 10_000), (run_ids[0], "SUCCEEDED", 20_000)]
        assert all(cost.call_kind == "ANALYSIS" and cost.organization_id == org_a for cost in costs)
        # 10k in at 0.75/M + (1k out + 500 thinking) at 3.75/M
        assert costs[1].estimated_cost_usd == Decimal("0.013125")
        assert costs[1].thinking_tokens == 500 and costs[1].price_table_version == "gemini-2026-10-unverified"

        # Append-only.
        for statement in ("UPDATE product_events SET event_name='sign_in'", "DELETE FROM ai_call_costs"):
            with pytest.raises(Exception) as blocked:
                async with db.begin_nested():
                    await db.execute(text(statement))
            assert "product_analytics_immutable" in str(blocked.value)
        await db.rollback()

        metrics = await metrics_endpoints.admin_product_metrics(weeks=4, funnel_days=28, include_demo=False, db=db)
        assert metrics.weekly_active_organizations[-1].active_organizations == 1
        funnel = {step.step: step for step in metrics.funnel}
        assert (funnel["analysis_started"].organizations, funnel["analysis_started"].events) == (1, 2)
        assert funnel["eoi_downloaded"].events == 0
        assert metrics.other_events == {"analysis_failed": 1, "invite_sent": 1, "invite_accepted": 1}
        assert (metrics.analysis.completed, metrics.analysis.failed) == (1, 1)
        assert metrics.analysis.median_time_to_result_ms is not None
        analysis_cost = next(item for item in metrics.cost.by_kind if item.call_kind == "ANALYSIS")
        assert (analysis_cost.calls, analysis_cost.subjects, analysis_cost.input_tokens) == (3, 2, 35_000)
        assert metrics.cost.analyses_with_cost == 1
        assert metrics.cost.mean_cost_per_analysis_usd == pytest.approx(0.013125 + 0.020625)

        # Demo organizations are excluded unless asked for.
        await db.execute(text(
            "UPDATE company_profiles SET notes='[plasma-demo-seed] demo' WHERE id=:id"), {"id": ids["profile_a"]})
        await db.commit()
        hidden = await product_analytics.product_metrics(db, weeks=4)
        assert hidden["excluded_demo_organizations"] == 1
        assert hidden["weekly_active_organizations"][-1]["active_organizations"] == 0
        assert (await product_analytics.product_metrics(db, weeks=4, include_demo=True))["analysis"]["completed"] == 1

    async def check_access() -> None:
        operator = User(email="op@example.org", name="Op", google_id="o", approval_status="approved",
                        platform_role="operator", is_admin=False)
        with pytest.raises(HTTPException) as denied:
            await deps.require_admin(current_user=operator)
        assert denied.value.status_code == 403

    await check_access()
