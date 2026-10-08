"""R3 Task 1: invite teammates by e-mail.

Pure rules, the additive migration, then one Postgres scenario that drives the OWNER
endpoints, the token-gated preview/accept and the Google sign-in binding.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
from uuid import uuid4

from fastapi import HTTPException, Response
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import deps
from app.api.endpoints import auth as auth_endpoints
from app.api.endpoints import organizations as org_endpoints
from app.api.endpoints import users as user_endpoints
from app.core.config import settings
from app.models.all_models import AdminActivityEvent
from app.models.base import MembershipRole, MembershipState
from app.models.invitations import PendingInvitation
from app.models.private_documents import MembershipLifecycleEvent
from app.models.tenancy import Membership
from app.models.user import User
from app.schemas.tenancy import EmailInvitationCreateRequest, InvitationTokenRequest
from app.services import invitations as service
from app.services.memberships import activate_invitation, invite_member
from scripts import test_s0_5b4_baseline as support
from test_w2_organization_pursuit_foundation import W1_HEAD, _seed_w1


PREVIOUS_HEAD = "20261005_0001_d2_05_eoi_drafts"
REVISION = "20261008_0001_r3_pending_invitations"
HEAD = "20261010_0001_r3_email_notifications"


# ---- pure rules -----------------------------------------------------------------------------------

def test_email_normalization_masking_and_links(monkeypatch: pytest.MonkeyPatch) -> None:
    assert service.normalize_email("  Ada.Lovelace@Example.ORG ") == "ada.lovelace@example.org"
    for bad in ("", "no-at-sign", "two@@example.org", "a b@example.org", "x@nodot", "a@" + "b" * 260 + ".org"):
        with pytest.raises(service.InvitationError):
            service.normalize_email(bad)
    assert service.mask_email("ada@example.org") == "a**@example.org"
    assert service.mask_email("a@example.org") == "a*@example.org"
    token = "t" * 43
    assert service.hash_token(token) == hashlib.sha256(token.encode()).hexdigest()
    assert service.invite_path(token) == f"/invite/{token}"
    monkeypatch.setattr(settings, "PUBLIC_APP_URL", None)
    assert service.invite_url(token) is None
    monkeypatch.setattr(settings, "PUBLIC_APP_URL", "https://app.example/")
    assert service.invite_url(token) == f"https://app.example/invite/{token}"


# ---- migration ------------------------------------------------------------------------------------

def test_r3_01_migration_is_additive_reversible_and_drift_free() -> None:
    async def scenario() -> None:
        database = support.database_name("r3_01_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", PREVIOUS_HEAD)
            await asyncio.to_thread(support.alembic, database, "upgrade", REVISION)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT version_num FROM alembic_version") == REVISION
                assert await connection.fetchval("SELECT to_regclass('pending_invitations')")
                assert await connection.fetchval("SELECT to_regclass('uq_pending_invitation_open_email')")
                assert await connection.fetchval(
                    "SELECT count(*) FROM pg_constraint WHERE conname LIKE 'ck_pending_invitation_%'"
                ) == 5
                default = await connection.fetchval(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_name='pending_invitations' AND column_name='expires_at'"
                )
                assert "14 days" in default
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", PREVIOUS_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('pending_invitations')") is None
                # The shared enum stays: memberships still use it.
                assert await connection.fetchval("SELECT count(*) FROM pg_type WHERE typname='membership_role'") == 1
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


# ---- Postgres scenario ----------------------------------------------------------------------------

def test_invitations_owner_only_isolated_and_bound_at_sign_in(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        database = support.database_name("r3_01_invitations")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                org_a = await connection.fetchval(
                    "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"]
                )
                org_b = await connection.fetchval(
                    "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_b"]
                )
                owner_a = await connection.fetchval(
                    "SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", org_a, ids["user_a"]
                )
            finally:
                await connection.close()
            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            monkeypatch.setattr(settings, "PUBLIC_APP_URL", "https://app.example")
            try:
                await _owner_endpoints(sessions, ids, org_a, org_b, owner_a)
                await _sign_in_binding(sessions, ids, org_a, org_b, monkeypatch, database)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


def _create(email: str, role: MembershipRole = MembershipRole.MEMBER) -> EmailInvitationCreateRequest:
    return EmailInvitationCreateRequest(email=email, role=role)


async def _owner_endpoints(sessions, ids, org_a, org_b, owner_a) -> None:
    create = org_endpoints.create_email_invitation_endpoint
    listing = org_endpoints.list_email_invitations_endpoint
    revoke = org_endpoints.revoke_email_invitation_endpoint
    resend = org_endpoints.resend_email_invitation_endpoint

    # A MEMBER of A (activated through the existing user-id invitation) for the OWNER-only checks.
    async with sessions() as db, db.begin():
        invited = await invite_member(db, organization_id=org_a, actor_membership_id=owner_a, user_id=ids["member"])
        member_membership = invited.id
    async with sessions() as db, db.begin():
        await activate_invitation(db, membership_id=member_membership, user_id=ids["member"])

    async with sessions() as db:
        user_a = await db.get(User, ids["user_a"])
        user_b = await db.get(User, ids["user_b"])
        member = await db.get(User, ids["member"])

        created = await create(organization_id=org_a, payload=_create("  New.Person@Example.ORG "), current_user=user_a, db=db)
        assert created.email == "new.person@example.org" and created.status == "OPEN"
        assert created.role == MembershipRole.MEMBER and created.send_count == 1
        assert created.invite_path.startswith("/invite/") and created.invite_url == f"https://app.example{created.invite_path}"
        assert created.email_delivery == "DISABLED"
        token = created.invite_path.removeprefix("/invite/")
        stored = await db.get(PendingInvitation, created.invitation_id)
        assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest() and token not in stored.token_hash
        lifetime = stored.expires_at - stored.created_at
        assert 13.9 < lifetime.total_seconds() / 86400 <= 14.0

        # Duplicate open invitation and an existing active member are refused.
        for email, code in (("new.person@example.org", "ALREADY_INVITED"), ("member@same-domain.invalid", "ALREADY_MEMBER")):
            with pytest.raises(HTTPException) as conflict:
                await create(organization_id=org_a, payload=_create(email), current_user=user_a, db=db)
            assert conflict.value.status_code == 409 and conflict.value.detail["code"] == code
        with pytest.raises(HTTPException) as invalid:
            await create(organization_id=org_a, payload=_create("not-an-email"), current_user=user_a, db=db)
        assert invalid.value.status_code == 422

        # OWNER only: a MEMBER can neither invite, list, resend nor revoke.
        for call in (
            lambda: create(organization_id=org_a, payload=_create("x@example.org"), current_user=member, db=db),
            lambda: listing(organization_id=org_a, current_user=member, db=db),
            lambda: resend(organization_id=org_a, invitation_id=created.invitation_id, current_user=member, db=db),
            lambda: revoke(organization_id=org_a, invitation_id=created.invitation_id, current_user=member, db=db),
        ):
            with pytest.raises(HTTPException) as forbidden:
                await call()
            assert forbidden.value.status_code == 403

        # Tenant isolation: B cannot see or touch A's invitations, through either organization.
        with pytest.raises(HTTPException) as foreign:
            await listing(organization_id=org_a, current_user=user_b, db=db)
        assert foreign.value.status_code == 404
        assert await listing(organization_id=org_b, current_user=user_b, db=db) == []
        for call in (revoke, resend):
            with pytest.raises(HTTPException) as cross:
                await call(organization_id=org_b, invitation_id=created.invitation_id, current_user=user_b, db=db)
            assert cross.value.status_code == 404

        # The list never carries a link; the member list names people.
        listed = await listing(organization_id=org_a, current_user=user_a, db=db)
        assert [item.invitation_id for item in listed] == [created.invitation_id]
        assert listed[0].invite_path is None and listed[0].invite_url is None
        assert listed[0].invited_by_name == user_a.name
        members = await org_endpoints.list_members(organization_id=org_a, current_user=user_a, db=db)
        assert {item.user_email for item in members} == {user_a.email, member.email}

        # Resend rotates the token and restarts the window; the old link stops working.
        resent = await resend(organization_id=org_a, invitation_id=created.invitation_id, current_user=user_a, db=db)
        new_token = resent.invite_path.removeprefix("/invite/")
        assert new_token != token and resent.send_count == 2
        with pytest.raises(HTTPException) as stale:
            await org_endpoints.preview_invitation_endpoint(payload=InvitationTokenRequest(token=token), db=db)
        assert stale.value.status_code == 404
        preview = await org_endpoints.preview_invitation_endpoint(payload=InvitationTokenRequest(token=new_token), db=db)
        assert preview.organization_name == "Same Name Company" and preview.inviter_name == user_a.name
        assert preview.email_hint == "n******@example.org" and preview.status == "OPEN"

        # Revoke is idempotent; a revoked invitation cannot be resent.
        revoked = await create(organization_id=org_a, payload=_create("gone@example.org"), current_user=user_a, db=db)
        first = await revoke(organization_id=org_a, invitation_id=revoked.invitation_id, current_user=user_a, db=db)
        again = await revoke(organization_id=org_a, invitation_id=revoked.invitation_id, current_user=user_a, db=db)
        assert first.status == again.status == "REVOKED" and first.revoked_at == again.revoked_at
        with pytest.raises(HTTPException) as dead:
            await resend(organization_id=org_a, invitation_id=revoked.invitation_id, current_user=user_a, db=db)
        assert dead.value.status_code == 409 and dead.value.detail["code"] == "REVOKED"

        # Invitations for the sign-in scenario.
        late = await create(organization_id=org_a, payload=_create("late@example.org"), current_user=user_a, db=db)
        owner_invite = await create(
            organization_id=org_b, payload=_create("second.owner@example.org", MembershipRole.OWNER), current_user=user_b, db=db,
        )
        await create(organization_id=org_a, payload=_create("linked@example.org"), current_user=user_a, db=db)
        await db.commit()
        assert owner_invite.role == MembershipRole.OWNER

        # Audit: one event per OWNER command, never carrying the token.
        events = (await db.execute(
            select(AdminActivityEvent.action, AdminActivityEvent.target_email, AdminActivityEvent.metadata_json)
            .where(AdminActivityEvent.action.like("ORGANIZATION_INVITATION_%"))
        )).all()
        actions = sorted(action for action, _, _ in events)
        assert actions.count("ORGANIZATION_INVITATION_CREATED") == 5
        assert actions.count("ORGANIZATION_INVITATION_RESENT") == 1
        assert actions.count("ORGANIZATION_INVITATION_REVOKED") == 1
        assert all(token not in str(metadata) and new_token not in str(metadata) for _, _, metadata in events)

    async with sessions() as db, db.begin():
        await db.execute(
            text("UPDATE pending_invitations SET expires_at = now() - interval '1 minute' WHERE id = :id"),
            {"id": late.invitation_id},
        )


async def _sign_in(sessions, monkeypatch, email: str, google_id: str | None = None):
    identity = {"email": email, "sub": google_id or f"google-{uuid4()}", "name": email.split("@")[0], "avatar_url": None}

    async def verified(_payload):
        return identity

    monkeypatch.setattr(auth_endpoints, "verify_bridge_assertion", verified)
    async with sessions() as db:
        payload = auth_endpoints.GoogleAuthRequest(google_id=identity["sub"], email=email, name=identity["name"])
        return await auth_endpoints.google_auth_bridge(payload=payload, response=Response(), db=db)


async def _sign_in_binding(sessions, ids, org_a, org_b, monkeypatch, database) -> None:
    # Exact verified e-mail: approved, ACTIVE membership, onboarding skipped, invitation accepted.
    token = await _sign_in(sessions, monkeypatch, "New.Person@example.org")
    assert token.approval_status == "approved" and token.onboarding_required is False
    assert str(token.company_profile_id) == str(ids["profile_a"]) and token.company_approval_status == "approved"
    async with sessions() as db:
        invitee = await db.scalar(select(User).where(User.email == "new.person@example.org"))
        membership = await db.scalar(select(Membership).where(Membership.user_id == invitee.id))
        assert (membership.organization_id, membership.role, membership.state) == (org_a, MembershipRole.MEMBER, MembershipState.ACTIVE)
        invitation = await db.scalar(select(PendingInvitation).where(PendingInvitation.email == "new.person@example.org"))
        assert invitation.accepted_at is not None and invitation.accepted_membership_id == membership.id
        assert invitation.accepted_user_id == invitee.id
        owner_user_id = await db.scalar(select(User.id).where(User.id == ids["user_a"]))
        assert invitee.approved_by_user_id == owner_user_id and invitee.auth_version == 1
        event = await db.scalar(
            select(AdminActivityEvent).where(AdminActivityEvent.action == "ORGANIZATION_INVITATION_ACCEPTED")
        )
        assert event.target_user_id == invitee.id and event.actor_type == "SYSTEM" and event.source == "EMAIL_INVITATION"
        assert event.metadata_json["membership_id"] == str(membership.id)
        assert event.metadata_json["user_approved_by_invitation"] is True
        assert event.previous_state["approval_status"] == "pending" and event.new_state["approval_status"] == "approved"
        lifecycle = await db.scalar(
            select(MembershipLifecycleEvent).where(MembershipLifecycleEvent.membership_id == membership.id)
        )
        assert lifecycle.action == "ACTIVATE" and lifecycle.new_state == "ACTIVE"
        # Account gates follow the organization: access allowed, onboarding complete.
        access = await user_endpoints.get_access_status(current_user=invitee, db=db)
        assert access.access_allowed and access.onboarding_completed and access.state == "approved"
        assert access.company_profile_id == ids["profile_a"]
        assert await deps.require_approved_pilot_access(current_user=invitee, db=db) is invitee
        assert await deps.require_active_initial_membership(current_user=invitee, db=db) is invitee
        # A MEMBER cannot edit the organization profile, and never onboards a second company.
        with pytest.raises(HTTPException) as edit:
            await user_endpoints.update_company_profile(
                profile_data=user_endpoints.CompanyProfileUpdate(company_name="Hijack"), current_user=invitee, db=db,
            )
        assert edit.value.status_code == 403
        with pytest.raises(HTTPException) as onboarding:
            await user_endpoints.submit_company_onboarding(
                payload=user_endpoints.CompanyOnboardingRequest.model_construct(company_name="Second Co"),
                current_user=invitee, db=db,
            )
        assert onboarding.value.status_code == 409

    # Signing in again changes nothing: no second acceptance, no second event.
    await _sign_in(sessions, monkeypatch, "new.person@example.org", google_id=invitee.google_id)
    async with sessions() as db:
        assert await db.scalar(
            select(func.count(AdminActivityEvent.id)).where(AdminActivityEvent.action == "ORGANIZATION_INVITATION_ACCEPTED")
        ) == 1

    # Same domain is not an invitation; expired and revoked invitations take the normal pending path.
    for email in ("someone@example.org", "late@example.org", "gone@example.org"):
        result = await _sign_in(sessions, monkeypatch, email)
        assert result.approval_status == "pending" and result.onboarding_required is True, email
        async with sessions() as db:
            user = await db.scalar(select(User).where(User.email == email))
            assert await db.scalar(select(func.count(Membership.id)).where(Membership.user_id == user.id)) == 0
    async with sessions() as db:
        late = await db.scalar(select(PendingInvitation).where(PendingInvitation.email == "late@example.org"))
        assert late.accepted_at is None and service.invitation_status(late) == "EXPIRED"
        # Inviting again closes the expired invitation and opens a fresh one.
        user_a = await db.get(User, ids["user_a"])
        fresh = await org_endpoints.create_email_invitation_endpoint(
            organization_id=org_a, payload=_create("late@example.org"), current_user=user_a, db=db,
        )
        await db.commit()
        await db.refresh(late)
        assert late.revoked_at is not None and fresh.status == "OPEN"

    # From the link while signed in: the exact e-mail accepts, a different e-mail is refused.
    async with sessions() as db:
        late_user = await db.scalar(select(User).where(User.email == "late@example.org"))
        stranger = await db.scalar(select(User).where(User.email == "someone@example.org"))
        token = fresh.invite_path.removeprefix("/invite/")
        with pytest.raises(HTTPException) as mismatch:
            await org_endpoints.accept_invitation_endpoint(payload=InvitationTokenRequest(token=token), current_user=stranger, db=db)
        assert mismatch.value.status_code == 403 and mismatch.value.detail["code"] == "EMAIL_MISMATCH"
        accepted = await org_endpoints.accept_invitation_endpoint(
            payload=InvitationTokenRequest(token=token), current_user=late_user, db=db,
        )
        await db.commit()
        assert accepted.organization_id == org_a and accepted.state == MembershipState.ACTIVE
        with pytest.raises(HTTPException) as used:
            await org_endpoints.accept_invitation_endpoint(payload=InvitationTokenRequest(token=token), current_user=late_user, db=db)
        assert used.value.status_code == 409 and used.value.detail["code"] == "ACCEPTED"
        # An accepted invitation cannot be revoked.
        with pytest.raises(HTTPException) as final:
            await org_endpoints.revoke_email_invitation_endpoint(
                organization_id=org_a, invitation_id=fresh.invitation_id, current_user=user_a, db=db,
            )
        assert final.value.status_code == 409

    # An OWNER invitation binds as OWNER, and the invitee may edit the organization profile.
    result = await _sign_in(sessions, monkeypatch, "second.owner@example.org")
    assert result.approval_status == "approved" and result.onboarding_required is False
    async with sessions() as db:
        owner_two = await db.scalar(select(User).where(User.email == "second.owner@example.org"))
        membership = await db.scalar(select(Membership).where(Membership.user_id == owner_two.id))
        assert (membership.organization_id, membership.role) == (org_b, MembershipRole.OWNER)
        updated = await user_endpoints.update_company_profile(
            profile_data=user_endpoints.CompanyProfileUpdate(website="https://b.example"), current_user=owner_two, db=db,
        )
        assert updated.website == "https://b.example"
        await db.rollback()

    # An organization that is no longer approved does not bind: the invitation stays open.
    connection = await support.database_connection(database)
    try:
        await connection.execute("UPDATE company_profiles SET approval_status='pending' WHERE id=$1", ids["profile_a"])
    finally:
        await connection.close()
    result = await _sign_in(sessions, monkeypatch, "linked@example.org")
    assert result.approval_status == "pending" and result.onboarding_required is True
    async with sessions() as db:
        linked = await db.scalar(select(PendingInvitation).where(PendingInvitation.email == "linked@example.org"))
        assert linked.accepted_at is None and service.invitation_status(linked, now=datetime.now(timezone.utc)) == "OPEN"
