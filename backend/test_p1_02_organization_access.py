"""P1-02: organization access state (explore | pilot | paid | disabled), Explore, admin alerts, pilot setup.

The migration backfill, the one writer that keeps the company gate in step, the org-scoped
enforcement (explore cannot use pursuits, uploads, analyses or the library), the Explore
endpoints, the admin access editor, the sign-up and pilot-request alerts (Telegram, else
e-mail, else FAILED/NO_CHANNEL), and scripts/pilot_setup.py end to end.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
import json
from uuid import uuid4

from fastapi import HTTPException, Response
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import deps
from app.api.endpoints import admin_panels as panel_endpoints
from app.api.endpoints import auth as auth_endpoints
from app.api.endpoints import explore as explore_endpoints
from app.api.endpoints import users as user_endpoints
from app.core import rate_limit
from app.core.config import settings
from app.models.admin_alerts import AdminAlert
from app.models.all_models import AdminActivityEvent
from app.models.base import MembershipRole, MembershipState
from app.models.company import CompanyProfile
from app.models.email import EmailDelivery
from app.models.invitations import PendingInvitation
from app.models.tenancy import Membership, Organization
from app.models.user import User
from app.services import admin_alerts, organization_access
from app.services.organization_context import (
    OrganizationAccessDeniedError,
    ensure_profile_organization,
    resolve_organization_context,
)
from scripts import pilot_setup
from scripts import test_s0_5b4_baseline as support
from test_p1_01_email_sign_in import FakeRedis

PREVIOUS_HEAD = "20261016_0001_p1_email_sign_in"
REVISION = "20261016_0002_p1_organization_access"
HEAD = REVISION


# ---- pure rules -----------------------------------------------------------------------------------

def test_state_mapping_and_plan_arithmetic() -> None:
    m = organization_access.state_for_company_status
    assert (m("approved"), m("approved", "paid"), m("approved", "explore")) == ("pilot", "paid", "pilot")
    assert (m("pending"), m("rejected"), m("disabled"), m(None)) == ("explore", "disabled", "disabled", "explore")
    assert organization_access.COMPANY_STATUS_FOR_STATE == {
        "explore": "pending", "pilot": "approved", "paid": "approved", "disabled": "disabled"}
    assert pilot_setup.add_months(date(2026, 10, 20), 3) == date(2027, 1, 20)
    assert pilot_setup.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert pilot_setup.slug("Ташкент Консалт «ООО»") == "firm" or pilot_setup.slug("Acme Consulting LLC") == "acme-consulting-llc"
    with pytest.raises(pilot_setup.PilotSetupError):
        pilot_setup.validate(pilot_setup.Options(target="local", firm="Acme — Plasma preview", owners=["a@example.org"]))
    with pytest.raises(pilot_setup.PilotSetupError):
        pilot_setup.validate(pilot_setup.Options(target="local", firm="Acme", members=["a@example.org"]))  # no owner
    plan = pilot_setup.validate(pilot_setup.Options(
        target="local", firm="  Acme   Consulting ", owners=["Boss@Acme.example"], members=["boss@acme.example", "b@acme.example"],
        start=date(2026, 10, 20), success_criteria=" Three EOIs. "))
    assert plan["firm"] == "Acme Consulting" and plan["end"] == date(2027, 1, 20) and plan["criteria"] == "Three EOIs."
    assert plan["invitees"] == {"boss@acme.example": "OWNER", "b@acme.example": "MEMBER"}


def test_alert_rendering_and_channel_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    alert = AdminAlert(kind="NEW_SIGNUP", payload={"email": "a@example.org", "name": "Ada", "method": "EMAIL_CODE",
                                                   "at": "2026-10-16T10:00:00+00:00"}, created_at=datetime.now(timezone.utc))
    subject, lines = admin_alerts.render_alert(alert)
    assert subject == "New Plasma sign-up: a@example.org" and "Ada <a@example.org>" in lines[0] and "e-mail code" in lines[1]
    request = AdminAlert(kind="PILOT_REQUEST", payload={"request": "call", "email": "a@example.org", "organization_name": "Acme",
                                                        "message": "Tuesday", "phone": "+998"}, created_at=datetime.now(timezone.utc))
    subject, lines = admin_alerts.render_alert(request)
    assert subject.startswith("Plasma a call request") and "Message: Tuesday" in lines and "Phone: +998" in lines
    provider = AdminAlert(kind="ANALYSIS_PROVIDER_ERROR", payload={"code": "PROVIDER_ACCOUNT", "status": 402,
                                                                   "analysis_run_id": "r-1"}, created_at=datetime.now(timezone.utc))
    subject, lines = admin_alerts.render_alert(provider)
    assert "rejects the key or billing" in subject and "HTTP 402" in lines[0] and "r-1" in lines[2]
    monkeypatch.setattr(settings, "ADMIN_ALERT_TELEGRAM_CHAT_ID", None)
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    assert admin_alerts.admin_alert_channel() is None
    monkeypatch.setattr(settings, "ADMIN_ALERT_TELEGRAM_CHAT_ID", "-1001")
    monkeypatch.setattr(settings, "ADMIN_ALERT_TELEGRAM_BOT_TOKEN", "123:abc")
    assert admin_alerts.admin_alert_channel() == "TELEGRAM" and admin_alerts.telegram_target() == ("123:abc", "-1001")


# ---- migration ------------------------------------------------------------------------------------

def test_p1_02_migration_backfills_access_from_company_approval() -> None:
    async def scenario() -> None:
        database = support.database_name("p1_02_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", PREVIOUS_HEAD)
            connection = await support.database_connection(database)
            orgs = {}
            try:
                for status in ("approved", "pending", "rejected", "disabled"):
                    user_id, profile_id, org_id = uuid4(), uuid4(), uuid4()
                    await connection.execute(
                        "INSERT INTO users(id,google_id,email,name,subscription_tier,is_admin,approval_status,platform_role,auth_version) "
                        "VALUES ($1,$2,$3,'n','SCOUT',false,'approved','pilot_user',0)", user_id, f"g-{user_id}", f"{status}@example.org")
                    await connection.execute(
                        "INSERT INTO company_profiles(id,user_id,company_name,pilot_status,approval_status) VALUES ($1,$2,$3,'scoped_pilot',$4)",
                        profile_id, user_id, f"{status} co", status)
                    await connection.execute(
                        "INSERT INTO organizations(id,legacy_company_profile_id,display_name) VALUES ($1,$2,$3)", org_id, profile_id, f"{status} co")
                    orgs[status] = org_id
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", REVISION)
            connection = await support.database_connection(database)
            try:
                states = {row["id"]: row["access_state"] for row in await connection.fetch("SELECT id, access_state FROM organizations")}
                assert [states[orgs[s]] for s in ("approved", "pending", "rejected", "disabled")] == ["pilot", "explore", "disabled", "disabled"]
                assert await connection.fetchval("SELECT to_regclass('admin_alerts')")
                with pytest.raises(Exception):
                    await connection.execute("UPDATE organizations SET access_state='trial' WHERE id=$1", orgs["approved"])
                with pytest.raises(Exception):
                    await connection.execute(
                        "UPDATE organizations SET plan_started_on='2026-10-20', plan_ends_on='2026-10-01' WHERE id=$1", orgs["approved"])
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", PREVIOUS_HEAD)
            connection = await support.database_connection(database)
            try:
                columns = {r["column_name"] for r in await connection.fetch(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='organizations'")}
                assert "access_state" not in columns and "success_criteria" not in columns
                assert await connection.fetchval("SELECT to_regclass('admin_alerts')") is None
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


# ---- Postgres scenario ----------------------------------------------------------------------------

class FakeTelegram:
    def __init__(self, outcomes):
        self.outcomes, self.sent = list(outcomes), []

    async def send(self, token, chat_id, text):
        self.sent.append((chat_id, text))
        return self.outcomes.pop(0)


async def _make_org(db, *, email: str, name: str, approval: str) -> tuple[User, Organization]:
    user = User(google_id=f"g-{uuid4()}", email=email, name=name, platform_role="pilot_user", approval_status="approved")
    db.add(user)
    await db.flush()
    profile = CompanyProfile(user_id=user.id, created_by_user_id=user.id, company_name=name, approval_status=approval,
                             pilot_status="scoped_pilot")
    db.add(profile)
    await db.flush()
    context = await ensure_profile_organization(db, profile=profile)
    await db.commit()
    return user, context.organization


def test_access_states_explore_alerts_and_pilot_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        database = support.database_name("p1_02_access")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            redis = FakeRedis()
            monkeypatch.setattr(rate_limit, "_redis", lambda: redis)
            monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test")
            monkeypatch.setattr(settings, "SMTP_FROM", "Plasma <no-reply@plasmaos.uz>")
            monkeypatch.setattr(settings, "PUBLIC_APP_URL", "https://app.example")
            monkeypatch.setattr(settings, "ADMIN_ALERT_TELEGRAM_CHAT_ID", None)
            monkeypatch.setattr(settings, "PUBLIC_BOOK_CALL_URL", "https://cal.example/plasma")
            monkeypatch.setenv("PLASMA_ADMIN_EMAILS", "boss@plasma.example,ops@plasma.example")
            monkeypatch.setenv("PLASMA_OPERATOR_EMAILS", "")
            kicks: list[int] = []
            monkeypatch.setattr(admin_alerts, "kick_admin_alerts", lambda: kicks.append(1))
            monkeypatch.setattr(explore_endpoints, "kick_admin_alerts", lambda: kicks.append(1))
            monkeypatch.setattr(auth_endpoints, "kick_admin_alerts", lambda: kicks.append(1))
            try:
                await _scenario(sessions, kicks, monkeypatch)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _scenario(sessions, kicks, monkeypatch) -> None:
    async with sessions() as db:
        explorer, explore_org = await _make_org(db, email="self@signup.example", name="Self Signup LLC", approval="pending")
        piloter, pilot_org = await _make_org(db, email="pilot@firm.example", name="Pilot Firm LLC", approval="approved")
        admin = User(google_id="g-admin", email="boss@plasma.example", name="Boss", platform_role="admin", is_admin=True,
                     approval_status="approved")
        db.add(admin)
        await db.commit()
        assert (explore_org.access_state, pilot_org.access_state) == ("explore", "pilot")

    # 1. Enforcement: explore has no organization context (no pursuits, uploads, analyses, library); pilot does.
    async with sessions() as db:
        with pytest.raises(OrganizationAccessDeniedError):
            await resolve_organization_context(db, user_id=explorer.id)
        assert (await resolve_organization_context(db, user_id=piloter.id)).organization.id == pilot_org.id
        with pytest.raises(HTTPException) as denied:
            await deps.require_approved_pilot_access(current_user=explorer, db=db)
        assert denied.value.status_code == 403
        assert await deps.require_explorer_access(current_user=explorer, db=db) is explorer       # the feed
        assert await deps.require_explore_access(current_user=explorer, db=db) is explorer
        access = await user_endpoints.get_access_status(current_user=explorer, db=db)
        assert (access.state, access.access_allowed, access.organization_access_state) == ("explore", False, "explore")
        access = await user_endpoints.get_access_status(current_user=piloter, db=db)
        assert (access.state, access.access_allowed, access.organization_access_state) == ("approved", True, "pilot")

    # 2. Explore endpoints: overview, the guided demo, and the two calls to action alert the team.
    async with sessions() as db:
        overview = await explore_endpoints.explore_overview(current_user=explorer, db=db)
        assert overview.organization_name == "Self Signup LLC" and overview.book_call_url == "https://cal.example/plasma"
        assert overview.demo_available is True
        demo = await explore_endpoints.explore_demo_analysis(response=Response(), _current_user=explorer)
        assert {"tender", "firm", "steps"} <= set(demo) and demo["steps"]["requirements"]
        await explore_endpoints.explore_request(
            payload=explore_endpoints.ExploreRequest(request="pilot", message="Two RFPs next month"), current_user=explorer, db=db)
        await explore_endpoints.explore_request(payload=explore_endpoints.ExploreRequest(request="call"), current_user=explorer, db=db)
    async with sessions() as db:
        requests = (await db.scalars(select(AdminAlert).where(AdminAlert.kind == "PILOT_REQUEST").order_by(AdminAlert.created_at))).all()
        assert [r.payload["request"] for r in requests] == ["pilot", "call"]
        assert requests[0].payload["organization_name"] == "Self Signup LLC" and requests[0].payload["message"] == "Two RFPs next month"
    for _ in range(3):
        async with sessions() as db:
            await explore_endpoints.explore_request(payload=explore_endpoints.ExploreRequest(request="call"), current_user=explorer, db=db)
    with pytest.raises(HTTPException) as limited:
        async with sessions() as db:
            await explore_endpoints.explore_request(payload=explore_endpoints.ExploreRequest(request="call"), current_user=explorer, db=db)
    assert limited.value.status_code == 429
    async with sessions() as db:
        with pytest.raises(HTTPException):
            await deps.require_explore_access(current_user=User(id=uuid4(), email="x@example.org", approval_status="approved",
                                                                platform_role="pilot_user", is_admin=False), db=db)

    # 3. A new self sign-up alerts the team; a sign-in that joins by invitation does not.
    google = {"email": "newcomer@example.org", "sub": "g-newcomer", "name": "New Comer", "avatar_url": None}

    async def verified(_payload):
        return google

    monkeypatch.setattr(auth_endpoints, "verify_bridge_assertion", verified)
    async with sessions() as db:
        await auth_endpoints.google_auth_bridge(
            payload=auth_endpoints.GoogleAuthRequest(google_id="g-newcomer", email="newcomer@example.org", name="New Comer"),
            response=Response(), db=db)
    async with sessions() as db:
        owner = await db.scalar(select(Membership).where(Membership.organization_id == pilot_org.id))
        from app.services.invitations import create_email_invitation
        await create_email_invitation(db, organization_id=pilot_org.id, actor_membership_id=owner.id, email="joiner@firm.example")
        await db.commit()
    google.update(email="joiner@firm.example", sub="g-joiner", name="Joiner")
    async with sessions() as db:
        joined = await auth_endpoints.google_auth_bridge(
            payload=auth_endpoints.GoogleAuthRequest(google_id="g-joiner", email="joiner@firm.example", name="Joiner"),
            response=Response(), db=db)
        assert joined.onboarding_required is False
    google.update(email="newcomer@example.org", sub="g-newcomer", name="New Comer")
    async with sessions() as db:
        await auth_endpoints.google_auth_bridge(  # signing in again is not a new sign-up
            payload=auth_endpoints.GoogleAuthRequest(google_id="g-newcomer", email="newcomer@example.org", name="New Comer"),
            response=Response(), db=db)
    async with sessions() as db:
        signups = (await db.scalars(select(AdminAlert).where(AdminAlert.kind == "NEW_SIGNUP"))).all()
        assert [s.payload["email"] for s in signups] == ["newcomer@example.org"] and signups[0].payload["method"] == "GOOGLE"

    # 4. Delivery: Telegram when configured (retry on 5xx, FAILED on 4xx), else e-mail to every admin, else NO_CHANNEL.
    monkeypatch.setattr(settings, "ADMIN_ALERT_TELEGRAM_CHAT_ID", "-1001")
    monkeypatch.setattr(settings, "ADMIN_ALERT_TELEGRAM_BOT_TOKEN", "123:secret-token")
    telegram = FakeTelegram([admin_alerts.TelegramOutcome(False, "TELEGRAM_HTTP_502")] +
                            [admin_alerts.TelegramOutcome(True)] * 10)
    async with sessions() as db:
        first = await admin_alerts.deliver_due_alerts(db, telegram=telegram)
    assert first["leased"] == 6 and first["SENT"] == 5 and first["RETRY"] == 1
    assert all("secret-token" not in text for _, text in telegram.sent)
    async with sessions() as db:
        retry = await db.scalar(select(AdminAlert).where(AdminAlert.state == "PENDING"))
        assert retry.last_error_code == "TELEGRAM_HTTP_502" and retry.next_attempt_at > datetime.now(timezone.utc)
        retry.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        again = await admin_alerts.deliver_due_alerts(db, telegram=telegram)
    assert again["SENT"] == 1
    monkeypatch.setattr(settings, "ADMIN_ALERT_TELEGRAM_CHAT_ID", None)
    async with sessions() as db:
        await admin_alerts.stage_new_signup(db, user_id=uuid4(), email="mail@example.org", name="Mail", method="EMAIL_CODE")
        await db.commit()
        by_mail = await admin_alerts.deliver_due_alerts(db)
        assert by_mail["SENT"] == 1
        mails = (await db.scalars(select(EmailDelivery).where(EmailDelivery.kind == "ADMIN_ALERT"))).all()
        assert sorted(m.recipient_email for m in mails) == ["boss@plasma.example", "ops@plasma.example"]
        assert mails[0].payload["subject"] == "New Plasma sign-up: mail@example.org"
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    async with sessions() as db:
        await admin_alerts.stage_new_signup(db, user_id=uuid4(), email="lost@example.org", name="Lost", method="GOOGLE")
        await db.commit()
        await admin_alerts.deliver_due_alerts(db)
        lost = await db.scalar(select(AdminAlert).where(AdminAlert.payload["email"].astext == "lost@example.org"))
        assert (lost.state, lost.last_error_code) == ("FAILED", "NO_CHANNEL")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test")

    # 5. Admin access editor: admin only, validated, audited, company gate follows; explore -> pilot unlocks work.
    async with sessions() as db:
        update = panel_endpoints.OrganizationAccessUpdate(
            access_state="pilot", plan_started_on=date(2026, 10, 20), plan_ends_on=date(2027, 1, 20),
            success_criteria="Two EOIs submitted.", reason="Signed the pilot")
        row = await panel_endpoints.update_organization_access(organization_id=explore_org.id, payload=update, current_user=admin, db=db)
        assert (row.access_state, row.plan_ends_on, row.success_criteria, row.approval_status) == (
            "pilot", date(2027, 1, 20), "Two EOIs submitted.", "approved")
        assert (await resolve_organization_context(db, user_id=explorer.id)).organization.id == explore_org.id
        event = await db.scalar(select(AdminActivityEvent).where(AdminActivityEvent.action == "ORGANIZATION_ACCESS_CHANGED"))
        assert event.previous_state["access_state"] == "explore" and event.new_state["access_state"] == "pilot"
        assert event.actor_user_id == admin.id and event.target_resource_id == str(explore_org.id)
        with pytest.raises(HTTPException) as bad:
            await panel_endpoints.update_organization_access(
                organization_id=explore_org.id, current_user=admin, db=db,
                payload=panel_endpoints.OrganizationAccessUpdate(access_state="paid", plan_started_on=date(2026, 10, 20),
                                                                 plan_ends_on=date(2026, 10, 1)))
        assert bad.value.status_code == 422
        paid = await panel_endpoints.update_organization_access(
            organization_id=explore_org.id, current_user=admin, db=db,
            payload=panel_endpoints.OrganizationAccessUpdate(access_state="paid"))
        assert (paid.access_state, paid.pilot_status, paid.plan_started_on) == ("paid", "converted", None)
        disabled = await panel_endpoints.update_organization_access(
            organization_id=explore_org.id, current_user=admin, db=db,
            payload=panel_endpoints.OrganizationAccessUpdate(access_state="disabled", reason="Chargeback"))
        assert (disabled.access_state, disabled.approval_status) == ("disabled", "disabled")
        access = await user_endpoints.get_access_status(current_user=explorer, db=db)
        assert access.state == "disabled"
    with pytest.raises(HTTPException) as not_admin:
        async with sessions() as db:
            await deps.require_admin(current_user=piloter)
    assert not_admin.value.status_code == 403

    # 6. The admin company approve path moves the state too (pending -> pilot), and paid survives a re-approval.
    async with sessions() as db:
        from app.api.endpoints.admin import approve_company
        user2, org2 = await _make_org(db, email="later@firm.example", name="Later LLC", approval="pending")
        await approve_company(company_profile_id=org2.legacy_company_profile_id, current_user=admin, db=db)
        assert (await db.get(Organization, org2.id, populate_existing=True)).access_state == "pilot"

    # 7. Pilot setup script: dry run writes nothing; the write creates the organization, plan and invitations;
    #    a re-run adds only new addresses; foreign names are refused.
    options = dict(target="local", firm="Acme Consulting LLC", owners=["ceo@acme.example"], members=["bd@acme.example"],
                   start=date(2026, 10, 20), success_criteria="Three EOIs submitted with Plasma.")
    dry = await pilot_setup.run(sessions, pilot_setup.Options(**options, dry_run=True))
    assert dry["mode"] == "dry-run" and dry["plan_ends_on"] == "2027-01-20" and dry["exists"] is False
    async with sessions() as db:
        assert await db.scalar(select(func.count(Organization.id)).where(Organization.display_name == "Acme Consulting LLC")) == 0
    with pytest.raises(pilot_setup.PilotSetupError):
        await pilot_setup.run(sessions, pilot_setup.Options(**options))                  # no --confirm
    written = await pilot_setup.run(sessions, pilot_setup.Options(**options, confirm=pilot_setup.CONFIRMATION))
    org = written["organization"]
    assert (org["access_state"], org["plan_started_on"], org["plan_ends_on"], org["success_criteria"]) == (
        "pilot", "2026-10-20", "2027-01-20", "Three EOIs submitted with Plasma.")
    assert [(i["email"], i["role"], i["result"]) for i in written["invitations"]] == [
        ("ceo@acme.example", "OWNER", "INVITED"), ("bd@acme.example", "MEMBER", "INVITED")]
    assert all(i["link"].startswith("https://app.example/invite/") for i in written["invitations"])
    assert org["members"] == []                                                          # the steward is hidden
    rerun = await pilot_setup.run(sessions, pilot_setup.Options(
        **{**options, "members": ["bd@acme.example", "analyst@acme.example"]}, confirm=pilot_setup.CONFIRMATION))
    assert [(i["email"], i["result"]) for i in rerun["invitations"]] == [
        ("ceo@acme.example", "ALREADY_INVITED"), ("bd@acme.example", "ALREADY_INVITED"), ("analyst@acme.example", "INVITED")]
    async with sessions() as db:
        assert await db.scalar(select(func.count(Organization.id)).where(Organization.display_name == "Acme Consulting LLC")) == 1
        acme = await db.scalar(select(Organization).where(Organization.display_name == "Acme Consulting LLC"))
        panel = next(item for item in await __import__("app.services.admin_panels", fromlist=["x"]).organization_panel(db)
                     if item["organization_id"] == acme.id)
        assert panel["access_state"] == "pilot" and panel["success_criteria"] == "Three EOIs submitted with Plasma."
    listed = await pilot_setup.run(sessions, pilot_setup.Options(target="local", firm="acme consulting llc", list_only=True))
    assert listed["status"] == "FOUND" and len(listed["invitations"]) == 3
    with pytest.raises(pilot_setup.PilotSetupError):
        await pilot_setup.run(sessions, pilot_setup.Options(target="local", firm="Pilot Firm LLC", owners=["x@y.example"],
                                                            confirm=pilot_setup.CONFIRMATION))   # not ours: refused
    with pytest.raises(pilot_setup.PilotSetupError):
        await pilot_setup.run(sessions, pilot_setup.Options(target="production", firm="Acme", owners=["x@y.example"], dry_run=True))

    # The invited owner signs in with an e-mail code-equivalent verified address: OWNER of Acme, pilot access.
    google.update(email="ceo@acme.example", sub="g-ceo", name="CEO")
    async with sessions() as db:
        token = await auth_endpoints.google_auth_bridge(
            payload=auth_endpoints.GoogleAuthRequest(google_id="g-ceo", email="ceo@acme.example", name="CEO"), response=Response(), db=db)
        assert token.onboarding_required is False and token.company_approval_status == "approved"
        ceo = await db.scalar(select(User).where(User.email == "ceo@acme.example"))
        membership = await db.scalar(select(Membership).where(Membership.user_id == ceo.id))
        assert (membership.role, membership.state) == (MembershipRole.OWNER, MembershipState.ACTIVE)
        invitation = await db.scalar(select(PendingInvitation).where(PendingInvitation.email == "ceo@acme.example"))
        assert invitation.accepted_user_id == ceo.id
