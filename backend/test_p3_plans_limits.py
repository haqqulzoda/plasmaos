"""P3 plans and limits: counting rules, periods, thresholds and gates (pure), the migration, then one
Postgres scenario (pursuit counter, limits, alerts, grants, Explore, seats, introductions, gates, admin)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
import hashlib
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException, Response
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.plans import CATALOG, INTELLIGENCE_FULL, INTELLIGENCE_NONE, INTELLIGENCE_SECTOR, plan_for
from app.services.organization_access import plan_for_state
from app.services.plans import notice_for, plan_period

HEAD = "20261025_0001_b1_billing"
P2_HEAD = "20261023_0001_p2_partner_finder"


def _org(plan: str, started: date | None = None, ends: date | None = None, created: date = date(2026, 1, 10)):
    return SimpleNamespace(plan=plan, plan_started_on=started, plan_ends_on=ends,
                           created_at=datetime(created.year, created.month, created.day, tzinfo=timezone.utc))


# ---- pure rules ------------------------------------------------------------------------------------

def test_catalog_follows_the_pricing_table() -> None:
    rows = {code: (p.pursuit_limit, p.introduction_limit, p.user_limit, p.eoi, p.own_evidence, p.partner_search, p.intelligence)
            for code, p in CATALOG.items()}
    assert rows == {
        "explore": (1, 0, 2, False, False, False, "sector_headlines"),
        "pilot": (6, 1, None, True, True, True, INTELLIGENCE_NONE),
        "pursuit_desk": (24, 2, None, True, True, True, INTELLIGENCE_SECTOR),
        "agent": (60, 12, None, True, True, True, INTELLIGENCE_FULL),
        "enterprise": (150, None, None, True, True, True, INTELLIGENCE_FULL),
        "per_tender": (1, 0, None, True, True, True, INTELLIGENCE_NONE),  # RC-5: terms §1, partner search on every paid plan
    }
    assert [code for code, p in CATALOG.items() if p.has("competitor_intelligence")] == ["agent", "enterprise"]
    assert all(p.has("tender_check") for p in CATALOG.values())
    assert plan_for(None).code == plan_for("unknown").code == "explore"
    assert [plan_for_state(state, current) for state, current in (
        ("explore", "agent"), ("pilot", None), ("paid", "pilot"), ("paid", "agent"), ("disabled", "agent"),
    )] == ["explore", "pilot", "pursuit_desk", "agent", "agent"]


def test_periods_month_pilot_term_plan_year_and_lifetime() -> None:
    today = date(2026, 10, 23)
    assert plan_period(_org("explore"), today)[:2] == (date(2026, 10, 1), date(2026, 10, 31))
    assert plan_period(_org("explore"), date(2028, 2, 10))[:2] == (date(2028, 2, 1), date(2028, 2, 29))
    pilot = plan_period(_org("pilot", date(2026, 9, 1), date(2026, 11, 30)), today)
    assert (pilot.start, pilot.end, pilot.count_until) == (date(2026, 9, 1), date(2026, 11, 30), None)  # all since start
    assert plan_period(_org("pilot", date(2026, 8, 31)), today).end == date(2026, 11, 29)  # 3 months by default
    year = plan_period(_org("agent", date(2025, 3, 15)), today)
    assert (year.start, year.end, year.count_until) == (date(2026, 3, 15), date(2027, 3, 14), date(2027, 3, 14))
    assert plan_period(_org("agent", date(2025, 11, 1)), today)[:2] == (date(2025, 11, 1), date(2026, 10, 31))
    assert plan_period(_org("pursuit_desk", date(2024, 2, 29)), date(2026, 3, 1))[:2] == (date(2026, 2, 28), date(2027, 2, 27))
    assert plan_period(_org("enterprise"), today)[:2] == (date(2026, 1, 10), date(2027, 1, 9))  # no start: created
    assert plan_period(_org("per_tender", date(2026, 5, 1)), today)[:3] == (date(2026, 5, 1), None, None)


def test_notice_at_80_and_100_percent() -> None:
    assert [notice_for(used, 24) for used in (0, 19, 20, 23, 24, 30)] == [
        "none", "none", "near_limit", "near_limit", "limit_reached", "limit_reached"]
    assert [notice_for(used, 6) for used in (4, 5, 6)] == ["none", "near_limit", "limit_reached"]
    assert [notice_for(used, 1) for used in (0, 1)] == ["none", "limit_reached"]
    assert notice_for(500, None) == "none" and notice_for(0, 0) == "limit_reached"


# ---- migration ----------------------------------------------------------------------------------------

def test_p3_migration_is_additive_reversible_and_drift_free() -> None:
    from scripts import test_s0_5b4_baseline as support
    from test_w2_organization_pursuit_foundation import W1_HEAD, _seed_w1

    async def scenario() -> None:
        database = support.database_name("p3_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", P2_HEAD)
            connection = await support.database_connection(database)
            try:
                states = dict(await connection.fetch("SELECT id, access_state FROM organizations"))
                pending = await connection.fetchval(
                    "SELECT o.id FROM organizations o WHERE o.legacy_company_profile_id=$1", ids["profile_b"])
                await connection.execute("UPDATE organizations SET access_state='paid' WHERE id=$1", pending)
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                plans = dict(await connection.fetch("SELECT id, plan FROM organizations"))
                expected = {"pilot": "pilot", "paid": "pursuit_desk", "explore": "explore", "disabled": "explore"}
                for organization_id, state in states.items():
                    assert plans[organization_id] == ("pursuit_desk" if organization_id == pending else expected[state])
                for table in ("organization_pursuit_usage", "organization_plan_grants"):
                    assert await connection.fetchval("SELECT to_regclass($1)", table)
                assert "PLAN_USAGE" in await connection.fetchval(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_admin_alert_kind'")
                with pytest.raises(Exception, match="ck_organizations_plan"):
                    await connection.execute("UPDATE organizations SET plan='gold' WHERE id=$1", pending)
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", P2_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('organization_pursuit_usage')") is None
                assert await connection.fetchval(
                    "SELECT count(*) FROM information_schema.columns WHERE table_name='organizations' AND column_name='plan'") == 0
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


# ---- Postgres scenario ---------------------------------------------------------------------------------

def test_postgres_counter_limits_alerts_grants_explore_seats_introductions_and_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import test_s0_5b4_baseline as support
    from test_w2_organization_pursuit_foundation import W1_HEAD, _seed_w1

    async def scenario() -> None:
        database = support.database_name("p3_plans")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                organization_a = await connection.fetchval(
                    "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"])
                organization_b = await connection.fetchval(
                    "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_b"])
                owner_a = await connection.fetchval(
                    "SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", organization_a, ids["user_a"])
                owner_b = await connection.fetchval(
                    "SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", organization_b, ids["user_b"])
                assert await connection.fetchval("SELECT plan FROM organizations WHERE id=$1", organization_a) == "pilot"
                await connection.execute(
                    "UPDATE tenders SET title='Consulting services for insurance claims management', country='Uzbekistan', "
                    "procurement_category='Consultant Services' WHERE id=$1", ids["tender"])
                await connection.execute(
                    "UPDATE organizations SET plan_started_on=current_date - 10, plan_ends_on=current_date + 80 WHERE id=$1",
                    organization_a)
                ids["admin"] = uuid4()
                await connection.execute(
                    "INSERT INTO users(id,google_id,email,name,subscription_tier,is_admin,approval_status,platform_role,"
                    "auth_version) VALUES ($1,$2,'admin@plasma.invalid','Plasma Admin','SCOUT',true,'approved','admin',0)",
                    ids["admin"], f"p3-admin-{ids['admin']}")
                ids["tenders"] = []
                for index in range(8):
                    tender_id = uuid4()
                    await connection.execute(
                        "INSERT INTO tenders(id,external_id,source_system,canonical_source_key,source_url,title,description,"
                        "budget,currency,deadline,status,category) VALUES ($1,$2,'world_bank',$3,$4,$5,'p3',1000,'USD',"
                        "'2027-12-31T00:00:00Z','OPEN','Services')",
                        tender_id, f"P3-{index}", f"world_bank:P3-{index}", f"https://example.invalid/p3-{index}",
                        f"P3 tender {index}")
                    ids["tenders"].append(tender_id)
            finally:
                await connection.close()

            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                await _counter_limits_alerts_and_grants(sessions, ids, organization_a, owner_a, monkeypatch)
                await _explore_month_gates_and_seats(sessions, ids, organization_b, owner_b)
                await _introduction_quota_and_feature_gates(sessions, ids, organization_a, monkeypatch)
                await _admin_plan_editing(sessions, ids, organization_a)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _source_pursuit(db, ids, organization_id, membership_id, tender_id, user_key="user_a"):
    from app.models.base import TenderEngagementOrigin, TenderEngagementStatus
    from app.services.pursuits import get_or_create_source_pursuit

    source = await get_or_create_source_pursuit(
        db, organization_id=organization_id, actor_user_id=ids[user_key], actor_membership_id=membership_id,
        tender_id=tender_id, stage=TenderEngagementStatus.SAVED,
        legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
    )
    await db.commit()
    return source.pursuit.id


async def _start_analysis(db, organization_id, membership_id, pursuit_id, tender_id, text: str):
    """The real start path (create_analysis_run): a parsed source document, the reviewed candidate."""
    from app.models.all_models import TenderDocument
    from app.schemas.tenancy import PursuitAnalysisStartRequest
    from app.services.private_documents import build_analysis_pack_candidate
    from app.services.pursuit_analysis import create_analysis_run

    document = await db.scalar(select(TenderDocument).where(TenderDocument.tender_id == tender_id))
    if document is None:
        document = TenderDocument(
            tender_id=tender_id, file_url=f"{tender_id}.pdf", file_type="pdf",
            source_document_url=f"https://example.invalid/{tender_id}.pdf", source_document_type="REOI",
            sha256=hashlib.sha256(text.encode()).hexdigest(), parsed_text=text,
        )
        db.add(document)
        await db.commit()
    candidate = await build_analysis_pack_candidate(db, organization_id=organization_id, pursuit_id=pursuit_id)
    return await create_analysis_run(
        db, organization_id=organization_id, pursuit_id=pursuit_id, membership_id=membership_id,
        request=PursuitAnalysisStartRequest(
            candidate_sha256=candidate.candidate_sha256, analysis_language="en", source_document_ids=[document.id],
        ),
    )


async def _usage(db, organization_id) -> int:
    from app.models.plans import OrganizationPursuitUsage

    return int(await db.scalar(select(func.count(OrganizationPursuitUsage.id)).where(
        OrganizationPursuitUsage.organization_id == organization_id)))


async def _counter_limits_alerts_and_grants(sessions, ids, organization_a, owner_a, monkeypatch) -> None:
    from app.api.endpoints import pursuits as pursuit_endpoints
    from app.models.admin_alerts import AdminAlert
    from app.models.tenancy import Organization
    from app.models.user import User
    from app.schemas.tenancy import PursuitAnalysisStartRequest
    from app.services.admin_alerts import render_alert
    from app.services.plans import PlanPursuitLimitError, add_grant, plan_status
    from app.services.private_documents import build_analysis_pack_candidate

    monkeypatch.setattr(pursuit_endpoints, "dispatch_run_ids", lambda run_ids: None)
    async with sessions() as db:
        # A pursuit counts once, when its first analysis starts; saving it counts nothing.
        pursuits = [await _source_pursuit(db, ids, organization_a, owner_a, tender) for tender in ids["tenders"][:7]]
        assert await _usage(db, organization_a) == 0
        first = await _start_analysis(db, organization_a, owner_a, pursuits[0], ids["tenders"][0], "Requirement one.")
        assert await _usage(db, organization_a) == 1
        # Re-analysis (a new run on the same pursuit, as after an amendment) never counts again.
        await _start_analysis(db, organization_a, owner_a, pursuits[0], ids["tenders"][0], "Requirement one.")
        assert await _usage(db, organization_a) == 1
        for index in range(1, 6):
            await _start_analysis(db, organization_a, owner_a, pursuits[index], ids["tenders"][index], f"Requirement {index}.")
        organization = await db.get(Organization, organization_a)
        status = await plan_status(db, organization)
        assert (status["plan"], status["pursuits"]["used"], status["pursuits"]["limit"], status["pursuits"]["notice"]) == (
            "pilot", 6, 6, "limit_reached")

        # One alert at 80% (5 of 6) and one at 100%, per period.
        alerts = list((await db.scalars(select(AdminAlert).where(AdminAlert.kind == "PLAN_USAGE")
                                        .order_by(AdminAlert.created_at))).all())
        assert sorted(alert.payload["threshold"] for alert in alerts) == [80, 100]
        subject, lines = render_alert(next(alert for alert in alerts if alert.payload["threshold"] == 100))
        assert "limit reached" in subject and "6 of 6 pursuits" in lines[0]

        # At the limit a new pursuit is blocked, at the HTTP edge too; a counted one still re-analyses.
        with pytest.raises(PlanPursuitLimitError, match="Upgrade or add pursuits"):
            await _start_analysis(db, organization_a, owner_a, pursuits[6], ids["tenders"][6], "Requirement six.")
        await db.rollback()
        user_a = await db.get(User, ids["user_a"])
        candidate = await build_analysis_pack_candidate(db, organization_id=organization_a, pursuit_id=pursuits[6])
        with pytest.raises(HTTPException) as blocked:
            await pursuit_endpoints.start_pursuit_analysis(
                pursuit_id=pursuits[6], payload=PursuitAnalysisStartRequest(
                    candidate_sha256=candidate.candidate_sha256, analysis_language="en",
                    source_document_ids=[item.tender_document_id for item in candidate.source_documents]),
                x_organization_id=organization_a, current_user=user_a, db=db)
        assert blocked.value.status_code == 402 and blocked.value.detail["code"] == "PLAN_PURSUIT_LIMIT"
        assert await _usage(db, organization_a) == 6
        await _start_analysis(db, organization_a, owner_a, pursuits[2], ids["tenders"][2], "Requirement 2.")
        assert first.analysis_run_id

        # An admin grants extra pursuits for this period: the blocked pursuit can start.
        admin = await db.get(User, ids["admin"])
        organization = await db.get(Organization, organization_a)
        await add_grant(db, organization=organization, kind="PURSUITS", quantity=2, reason="Two extra REOIs agreed",
                        actor_user=admin)
        await db.commit()
        await _start_analysis(db, organization_a, owner_a, pursuits[6], ids["tenders"][6], "Requirement six.")
        status = await plan_status(db, await db.get(Organization, organization_a))
        assert (status["pursuits"]["used"], status["pursuits"]["limit"], status["pursuits"]["extra_granted"]) == (7, 8, 2)
        assert status["pursuits"]["notice"] == "near_limit"


async def _explore_month_gates_and_seats(sessions, ids, organization_b, owner_b) -> None:
    from app.api.endpoints import eoi as eoi_endpoints
    from app.api.endpoints import organizations as organization_endpoints
    from app.models.tenancy import Organization
    from app.models.user import User
    from app.schemas.tenancy import EmailInvitationCreateRequest
    from app.services.organization_access import set_organization_access
    from app.services.organization_context import OrganizationAccessDeniedError, resolve_organization_context
    from app.services.plans import PlanFeatureError, PlanPursuitLimitError, plan_status, require_feature

    async with sessions() as db:
        organization = await db.get(Organization, organization_b, with_for_update=True)
        await set_organization_access(db, organization=organization, state="explore", plan="explore",
                                      actor_user=None, actor_label="test")
        await db.commit()
        assert organization.access_state == "explore"
        # The strict default still refuses an explore organization; the tender-check routes admit it.
        with pytest.raises(OrganizationAccessDeniedError):
            await resolve_organization_context(db, user_id=ids["user_b"])
        context = await resolve_organization_context(db, user_id=ids["user_b"], allow_explore=True)
        assert context.organization.id == organization_b

        first = await _source_pursuit(db, ids, organization_b, owner_b, ids["tenders"][7], user_key="user_b")
        await _start_analysis(db, organization_b, owner_b, first, ids["tenders"][7], "Explore requirement.")
        second = await _source_pursuit(db, ids, organization_b, owner_b, ids["tenders"][0], user_key="user_b")
        with pytest.raises(PlanPursuitLimitError, match="free tender check is used"):
            await _start_analysis(db, organization_b, owner_b, second, ids["tenders"][0], "Requirement one.")
        await db.rollback()
        organization = await db.get(Organization, organization_b)
        status = await plan_status(db, organization)
        assert (status["pursuits"]["used"], status["pursuits"]["limit"]) == (1, 1)
        next_month = (status["period_end"] + timedelta(days=1))
        assert (await plan_status(db, organization, today=next_month))["pursuits"]["used"] == 0  # a new month

        # Requirements view only: no EOI, no company records, no partner search, no competitor intelligence.
        for feature in ("eoi", "own_evidence", "partner_search", "competitor_intelligence"):
            with pytest.raises(PlanFeatureError):
                await require_feature(db, organization, feature)
        user_b = await db.get(User, ids["user_b"])
        with pytest.raises(HTTPException) as eoi:
            await eoi_endpoints._context(db, user_b, organization_b)
        assert eoi.value.status_code == 404  # explore never reaches organization work beyond the check

        # Two users on Explore: the owner and one invitation; a third is refused.
        invited = await organization_endpoints.create_email_invitation_endpoint(
            organization_id=organization_b, payload=EmailInvitationCreateRequest(email="colleague@example.org"),
            current_user=user_b, db=db)
        assert invited.email == "colleague@example.org"
        with pytest.raises(HTTPException) as third:
            await organization_endpoints.create_email_invitation_endpoint(
                organization_id=organization_b, payload=EmailInvitationCreateRequest(email="third@example.org"),
                current_user=user_b, db=db)
        assert third.value.status_code == 402 and third.value.detail["code"] == "PLAN_USER_LIMIT"
        plan = await organization_endpoints.get_organization_plan(
            x_organization_id=organization_b, current_user=user_b, db=db)
        assert (plan.plan, plan.users.used, plan.users.limit, plan.features.eoi) == ("explore", 2, 2, False)
        assert plan.pursuits.notice == "limit_reached"


async def _introduction_quota_and_feature_gates(sessions, ids, organization_a, monkeypatch) -> None:
    from app.api.endpoints import partner_finder as finder_endpoints
    from app.api.endpoints import tenders as tender_endpoints
    from app.models.tenancy import Membership, Organization
    from app.models.user import User
    from app.schemas.partner_finder import PartnerRequestCreate, PartnerRequestStatusChange
    from app.services.plans import plan_status
    from test_p2_partner_finder import _analysis, _seed_ledger

    monkeypatch.setattr(finder_endpoints, "kick_admin_alerts", lambda: None)
    await _seed_ledger(sessions)
    async with sessions() as db:
        owner_a = await db.scalar(select(Membership.id).where(
            Membership.organization_id == organization_a, Membership.user_id == ids["user_a"]))
        organization = await db.get(Organization, organization_a)
        organization.pursuit_limit_override = 50  # room for the P2 analysis pursuit
        await db.commit()
    pursuit_id, run_id = await _analysis(sessions, ids, organization_a, owner_a, monkeypatch)
    async with sessions() as db:
        user_a, admin = await db.get(User, ids["user_a"]), await db.get(User, ids["admin"])
        overview = await finder_endpoints.partner_gaps(pursuit_id=pursuit_id, x_organization_id=organization_a,
                                                       current_user=user_a, db=db)
        gap = next(item.gap_id for item in overview.gaps if item.features.basis == "EXPERIENCE")
        suggestions = await finder_endpoints.partner_suggestions(
            pursuit_id=pursuit_id, analysis_run_id=run_id, gap_id=gap, x_organization_id=organization_a,
            current_user=user_a, db=db)
        first_firm, second_firm = suggestions.suggestions[0].firm_key, suggestions.suggestions[1].firm_key

        async def request(firm_key):
            return await finder_endpoints.request_introduction(
                pursuit_id=pursuit_id, response=Response(), payload=PartnerRequestCreate(
                    analysis_run_id=run_id, gap_id=gap, kind="INTRODUCTION", firm_key=firm_key),
                x_organization_id=organization_a, current_user=user_a, db=db)

        # Pilot: one introduction. A repeat of the same request is free; a second firm is refused.
        first = await request(first_firm)
        assert (await request(first_firm)).request_id == first.request_id
        with pytest.raises(HTTPException) as quota:
            await request(second_firm)
        assert quota.value.status_code == 402 and quota.value.detail["code"] == "PLAN_INTRODUCTION_LIMIT"
        # The refused request rolled the session back (one session per request in the app): reload.
        user_a, admin = await db.get(User, ids["user_a"]), await db.get(User, ids["admin"])
        # A declined introduction gives the quota back.
        await finder_endpoints.admin_change_status(
            request_id=first.request_id, payload=PartnerRequestStatusChange(status="DECLINED"), current_user=admin, db=db)
        second = await request(second_firm)
        assert second.status == "REQUESTED"
        status = await plan_status(db, await db.get(Organization, organization_a))
        assert (status["introductions"]["used"], status["introductions"]["limit"]) == (1, 1)

        # Per-tender plan: partner search included (RC-5, terms §1). Pilot and Pursuit Desk: no competitor intelligence.
        organization = await db.get(Organization, organization_a)
        organization.plan = "per_tender"
        await db.commit()
        suggestions = await finder_endpoints.partner_suggestions(
            pursuit_id=pursuit_id, analysis_run_id=run_id, gap_id=gap, x_organization_id=organization_a,
            current_user=user_a, db=db)
        assert suggestions is not None
        for plan in ("pilot", "pursuit_desk"):
            organization = await db.get(Organization, organization_a)
            organization.plan = plan
            await db.commit()
            with pytest.raises(HTTPException) as intelligence:
                await tender_endpoints.get_tender_competitors(tender_id=ids["tender"], current_user=user_a, db=db)
            assert intelligence.value.status_code == 403 and intelligence.value.detail["feature"] == "competitor_intelligence"
        organization = await db.get(Organization, organization_a)
        organization.plan = "pilot"
        await db.commit()


async def _admin_plan_editing(sessions, ids, organization_a) -> None:
    from app.api.endpoints import admin_panels as panel_endpoints
    from app.models.user import User
    from app.schemas.plans import PlanGrantCreate

    async with sessions() as db:
        admin = await db.get(User, ids["admin"])
        update = panel_endpoints.OrganizationAccessUpdate(
            access_state="paid", plan="agent", plan_started_on=datetime.now(timezone.utc).date(), plan_ends_on=None,
            success_criteria="Six shortlists in a year", pursuit_limit_override=None, introduction_limit_override=15,
            reason="Signed Agent agreement")
        row = await panel_endpoints.update_organization_access(
            organization_id=organization_a, payload=update, current_user=admin, db=db)
        assert (row.plan, row.access_state, row.pursuit_limit, row.introduction_limit) == ("agent", "paid", 60, 15)
        # The plan year starts today and counts by date: today's 8 counted pursuits are in it.
        assert (row.pursuits_used, row.period_start) == (8, datetime.now(timezone.utc).date())
        detail = await panel_endpoints.grant_organization_allowance(
            organization_id=organization_a, payload=PlanGrantCreate(kind="INTRODUCTIONS", quantity=3, reason="Launch offer"),
            current_user=admin, db=db)
        assert detail.status.introductions.limit == 18 and detail.grants[0].granted_by_email == "admin@plasma.invalid"
        actions = [event.action for event in detail.audit_events]
        assert actions[:2] == ["ORGANIZATION_PLAN_GRANTED", "ORGANIZATION_ACCESS_CHANGED"]
        changed = next(event for event in detail.audit_events if event.action == "ORGANIZATION_ACCESS_CHANGED")
        assert (changed.previous_state["plan"], changed.new_state["plan"]) == ("pilot", "agent")
        assert changed.new_state["introduction_limit_override"] == 15
        # Disabled keeps the plan; the access state alone changes.
        update = update.model_copy(update={"access_state": "disabled", "reason": "Unpaid invoice"})
        row = await panel_endpoints.update_organization_access(
            organization_id=organization_a, payload=update, current_user=admin, db=db)
        assert (row.plan, row.access_state) == ("agent", "disabled")
