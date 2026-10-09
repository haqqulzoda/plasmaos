"""R3 Task 1: invite teammates to an organization by e-mail.

An OWNER invites an exact e-mail address. The response carries a one-time link; only the
SHA-256 of its token is stored. The invitation binds at Google sign-in when the verified
e-mail equals the invited address exactly (never on a shared domain alone): the platform
user is approved (the organization is already approved), an ACTIVE membership is created,
onboarding is skipped and the invitation is marked accepted, with an audit event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import (
    COMPANY_APPROVAL_APPROVED,
    USER_APPROVAL_APPROVED,
    USER_APPROVAL_PENDING,
    is_disabled_account,
    is_rejected_account,
)
from app.core.config import settings
from app.models.base import MembershipRole, MembershipState
from app.models.company import CompanyProfile
from app.models.invitations import INVITATION_TTL_DAYS, PendingInvitation
from app.models.private_documents import MembershipLifecycleEvent
from app.models.tenancy import Membership, Organization
from app.models.user import User
from app.services.admin_activity import (
    ACTION_INVITATION_ACCEPTED,
    ACTION_INVITATION_CREATED,
    ACTION_INVITATION_RESENT,
    ACTION_INVITATION_REVOKED,
    ACTOR_SYSTEM,
    ACTOR_USER,
    OUTCOME_SUCCESS,
    SOURCE_EMAIL_INVITATION,
    SOURCE_ORGANIZATION_API,
    bump_auth_version,
    record_admin_audit_event,
    user_role_snapshot,
)
from app.services.memberships import (
    MembershipPermissionError,
    _lock_organization,
    _require_owner,
)


MAX_OPEN_INVITATIONS = 100
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

STATUS_OPEN = "OPEN"
STATUS_EXPIRED = "EXPIRED"
STATUS_ACCEPTED = "ACCEPTED"
STATUS_REVOKED = "REVOKED"


class InvitationError(RuntimeError):
    pass


class InvitationNotFoundError(InvitationError):
    pass


class InvitationConflictError(InvitationError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InvitationEmailMismatchError(InvitationError):
    pass


__all__ = [
    "InvitationConflictError",
    "InvitationEmailMismatchError",
    "InvitationError",
    "InvitationNotFoundError",
    "IssuedInvitation",
    "MembershipPermissionError",
    "accept_invitation_token",
    "accept_open_invitations_for_sign_in",
    "create_email_invitation",
    "invitation_status",
    "invite_path",
    "invite_url",
    "list_email_invitations",
    "normalize_email",
    "preview_invitation",
    "resend_email_invitation",
    "revoke_email_invitation",
]


@dataclass(frozen=True)
class IssuedInvitation:
    invitation: PendingInvitation
    token: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def invite_path(token: str) -> str:
    return f"/invite/{token}"


def invite_url(token: str) -> str | None:
    base = (settings.PUBLIC_APP_URL or "").strip().rstrip("/")
    return f"{base}{invite_path(token)}" if base else None


def normalize_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if len(email) > 255 or not _EMAIL.fullmatch(email):
        raise InvitationError("a valid e-mail address is required")
    return email


def invitation_status(invitation: PendingInvitation, *, now: datetime | None = None) -> str:
    if invitation.accepted_at is not None:
        return STATUS_ACCEPTED
    if invitation.revoked_at is not None:
        return STATUS_REVOKED
    return STATUS_OPEN if invitation.expires_at > (now or _now()) else STATUS_EXPIRED


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}{'*' * max(1, min(len(local) - 1, 6))}@{domain}"


async def _actor_user(db: AsyncSession, membership: Membership) -> User:
    user = await db.get(User, membership.user_id)
    if user is None:
        raise MembershipPermissionError("active OWNER membership required")
    return user


async def _audit_owner_action(
    db: AsyncSession, *, action: str, actor: User, invitation: PendingInvitation
) -> None:
    await record_admin_audit_event(
        db,
        action=action,
        outcome=OUTCOME_SUCCESS,
        source=SOURCE_ORGANIZATION_API,
        actor_user=actor,
        actor_type=ACTOR_USER,
        target_user=None,
        target_email=invitation.email,
        target_resource_type="ORGANIZATION_INVITATION",
        target_resource_id=str(invitation.id),
        metadata={
            "organization_id": str(invitation.organization_id),
            "role": invitation.role.value,
            "expires_at": invitation.expires_at.isoformat(),
            "send_count": invitation.send_count,
        },
    )


async def _owner_invitation(
    db: AsyncSession, *, organization_id: UUID, invitation_id: UUID
) -> PendingInvitation:
    invitation = await db.scalar(
        select(PendingInvitation)
        .where(
            PendingInvitation.id == invitation_id,
            PendingInvitation.organization_id == organization_id,
        )
        .with_for_update()
    )
    if invitation is None:
        raise InvitationNotFoundError("invitation not found")
    return invitation


async def create_email_invitation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    actor_membership_id: UUID,
    email: str,
    role: MembershipRole = MembershipRole.MEMBER,
) -> IssuedInvitation:
    normalized = normalize_email(email)
    await _lock_organization(db, organization_id)
    actor_membership = await _require_owner(
        db, organization_id=organization_id, actor_membership_id=actor_membership_id
    )
    actor = await _actor_user(db, actor_membership)
    already_member = await db.scalar(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.organization_id == organization_id,
            Membership.state == MembershipState.ACTIVE,
            func.lower(User.email) == normalized,
        )
    )
    if already_member is not None:
        raise InvitationConflictError("ALREADY_MEMBER", "this person is already an active member")
    now = _now()
    existing = await db.scalar(
        select(PendingInvitation)
        .where(
            PendingInvitation.organization_id == organization_id,
            PendingInvitation.email == normalized,
            PendingInvitation.accepted_at.is_(None),
            PendingInvitation.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.expires_at > now:
            raise InvitationConflictError("ALREADY_INVITED", "an open invitation exists; resend it instead")
        # An expired invitation is closed so the new one can take the open slot.
        existing.revoked_at = now
        existing.updated_at = now
        await db.flush()
    open_count = await db.scalar(
        select(func.count(PendingInvitation.id)).where(
            PendingInvitation.organization_id == organization_id,
            PendingInvitation.accepted_at.is_(None),
            PendingInvitation.revoked_at.is_(None),
        )
    )
    if int(open_count or 0) >= MAX_OPEN_INVITATIONS:
        raise InvitationConflictError("TOO_MANY_OPEN", "too many open invitations")
    token = secrets.token_urlsafe(32)
    invitation = PendingInvitation(
        id=uuid4(),
        organization_id=organization_id,
        email=normalized,
        role=role,
        invited_by_membership_id=actor_membership.id,
        token_hash=hash_token(token),
        expires_at=now + timedelta(days=INVITATION_TTL_DAYS),
        send_count=1,
        last_sent_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(invitation)
    await db.flush()
    await _audit_owner_action(db, action=ACTION_INVITATION_CREATED, actor=actor, invitation=invitation)
    return IssuedInvitation(invitation=invitation, token=token)


async def list_email_invitations(
    db: AsyncSession, *, organization_id: UUID, limit: int = 200
) -> list[PendingInvitation]:
    return list(
        (
            await db.scalars(
                select(PendingInvitation)
                .where(PendingInvitation.organization_id == organization_id)
                .order_by(PendingInvitation.created_at.desc(), PendingInvitation.id.desc())
                .limit(limit)
            )
        ).all()
    )


async def revoke_email_invitation(
    db: AsyncSession, *, organization_id: UUID, actor_membership_id: UUID, invitation_id: UUID
) -> PendingInvitation:
    await _lock_organization(db, organization_id)
    actor_membership = await _require_owner(
        db, organization_id=organization_id, actor_membership_id=actor_membership_id
    )
    invitation = await _owner_invitation(db, organization_id=organization_id, invitation_id=invitation_id)
    if invitation.revoked_at is not None:
        return invitation
    if invitation.accepted_at is not None:
        raise InvitationConflictError("ALREADY_ACCEPTED", "an accepted invitation cannot be revoked")
    now = _now()
    invitation.revoked_at = now
    invitation.updated_at = now
    await db.flush()
    await _audit_owner_action(
        db, action=ACTION_INVITATION_REVOKED, actor=await _actor_user(db, actor_membership), invitation=invitation
    )
    return invitation


async def resend_email_invitation(
    db: AsyncSession, *, organization_id: UUID, actor_membership_id: UUID, invitation_id: UUID
) -> IssuedInvitation:
    """Rotate the token (the old link stops working) and restart the 14-day window."""
    await _lock_organization(db, organization_id)
    actor_membership = await _require_owner(
        db, organization_id=organization_id, actor_membership_id=actor_membership_id
    )
    invitation = await _owner_invitation(db, organization_id=organization_id, invitation_id=invitation_id)
    if invitation.accepted_at is not None:
        raise InvitationConflictError("ALREADY_ACCEPTED", "the invitation was already accepted")
    if invitation.revoked_at is not None:
        raise InvitationConflictError("REVOKED", "a revoked invitation cannot be resent; invite again")
    now = _now()
    token = secrets.token_urlsafe(32)
    invitation.token_hash = hash_token(token)
    invitation.expires_at = now + timedelta(days=INVITATION_TTL_DAYS)
    invitation.send_count = int(invitation.send_count or 0) + 1
    invitation.last_sent_at = now
    invitation.updated_at = now
    await db.flush()
    await _audit_owner_action(
        db, action=ACTION_INVITATION_RESENT, actor=await _actor_user(db, actor_membership), invitation=invitation
    )
    return IssuedInvitation(invitation=invitation, token=token)


async def _organization_profile(db: AsyncSession, organization_id: UUID) -> tuple[Organization, CompanyProfile] | None:
    row = (
        await db.execute(
            select(Organization, CompanyProfile)
            .join(CompanyProfile, CompanyProfile.id == Organization.legacy_company_profile_id)
            .where(Organization.id == organization_id)
        )
    ).one_or_none()
    return (row[0], row[1]) if row is not None else None


async def preview_invitation(db: AsyncSession, *, token: str) -> dict | None:
    """Public, token-gated summary for the invitation landing page. No private data."""
    if not token or len(token) > 200:
        return None
    invitation = await db.scalar(select(PendingInvitation).where(PendingInvitation.token_hash == hash_token(token)))
    if invitation is None:
        return None
    resolved = await _organization_profile(db, invitation.organization_id)
    inviter = await db.scalar(
        select(User.name)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.id == invitation.invited_by_membership_id)
    )
    organization_name = None
    if resolved is not None:
        organization_name = resolved[0].display_name or resolved[1].company_name
    return {
        "organization_name": organization_name,
        "inviter_name": inviter,
        "role": invitation.role,
        "email_hint": mask_email(invitation.email),
        "status": invitation_status(invitation),
        "expires_at": invitation.expires_at,
    }


async def _accept(
    db: AsyncSession, *, invitation_id: UUID, organization_id: UUID, user: User, actor_label: str
) -> Membership | None:
    """Accept one open invitation for ``user``. Returns None when it cannot bind.

    Lock order matches the OWNER commands: organization advisory lock, then the row.
    """
    now = _now()
    resolved = await _organization_profile(db, organization_id)
    if resolved is None or resolved[1].approval_status != COMPANY_APPROVAL_APPROVED:
        # The organization is no longer approved: leave the invitation open and let the
        # normal pending-approval path apply.
        return None
    await _lock_organization(db, organization_id)
    invitation = await db.scalar(
        select(PendingInvitation).where(PendingInvitation.id == invitation_id).with_for_update()
    )
    if invitation is None or invitation_status(invitation, now=now) != STATUS_OPEN:
        return None
    if invitation.email != (user.email or "").strip().lower():
        return None
    membership = await db.scalar(
        select(Membership)
        .where(Membership.organization_id == invitation.organization_id, Membership.user_id == user.id)
        .with_for_update()
    )
    previous_state = membership.state.value if membership is not None else None
    previous_role = membership.role.value if membership is not None else None
    if membership is None:
        membership_id = uuid4()
        await db.execute(
            pg_insert(Membership).values(
                id=membership_id,
                organization_id=invitation.organization_id,
                user_id=user.id,
                role=invitation.role,
                state=MembershipState.ACTIVE,
                created_at=now,
                updated_at=now,
                activated_at=now,
            )
        )
        membership = await db.get(Membership, membership_id)
        if membership is None:
            raise InvitationError("membership creation failed")
    elif membership.state != MembershipState.ACTIVE:
        membership.role = invitation.role
        membership.state = MembershipState.ACTIVE
        membership.activated_at = now
        membership.revoked_at = None
        membership.updated_at = now
    if previous_state != MembershipState.ACTIVE.value:
        db.add(
            MembershipLifecycleEvent(
                organization_id=invitation.organization_id,
                membership_id=membership.id,
                actor_user_id=user.id,
                actor_membership_id=membership.id,
                action="ACTIVATE",
                previous_role=previous_role,
                new_role=membership.role.value,
                previous_state=previous_state,
                new_state=MembershipState.ACTIVE.value,
            )
        )
    before = user_role_snapshot(user)
    approved_now = user.approval_status == USER_APPROVAL_PENDING
    if approved_now:
        inviter_user_id = await db.scalar(
            select(Membership.user_id).where(Membership.id == invitation.invited_by_membership_id)
        )
        user.approval_status = USER_APPROVAL_APPROVED
        user.approved_at = user.approved_at or now
        user.approved_by_user_id = inviter_user_id
        bump_auth_version(user)
    invitation.accepted_at = now
    invitation.accepted_user_id = user.id
    invitation.accepted_membership_id = membership.id
    invitation.updated_at = now
    await db.flush()
    await record_admin_audit_event(
        db,
        action=ACTION_INVITATION_ACCEPTED,
        outcome=OUTCOME_SUCCESS,
        source=SOURCE_EMAIL_INVITATION,
        target_user=user,
        actor_type=ACTOR_SYSTEM,
        actor_label=actor_label,
        target_resource_type="ORGANIZATION_INVITATION",
        target_resource_id=str(invitation.id),
        previous_state=before,
        new_state=user_role_snapshot(user, credentials_invalidated=approved_now),
        reason="Verified Google e-mail matched an open organization invitation exactly.",
        metadata={
            "organization_id": str(invitation.organization_id),
            "membership_id": str(membership.id),
            "role": membership.role.value,
            "previous_membership_state": previous_state,
            "user_approved_by_invitation": approved_now,
        },
    )
    return membership


async def accept_open_invitations_for_sign_in(
    db: AsyncSession, *, user: User, verified_email: str
) -> list[Membership]:
    """Bind every open, unexpired invitation for this exact verified e-mail."""
    if is_disabled_account(user) or is_rejected_account(user):
        return []
    email = (verified_email or "").strip().lower()
    if not email:
        return []
    rows = (
        await db.execute(
            select(PendingInvitation.id, PendingInvitation.organization_id)
            .where(
                PendingInvitation.email == email,
                PendingInvitation.accepted_at.is_(None),
                PendingInvitation.revoked_at.is_(None),
                PendingInvitation.expires_at > func.now(),
            )
            .order_by(PendingInvitation.created_at, PendingInvitation.id)
        )
    ).all()
    accepted: list[Membership] = []
    for invitation_id, organization_id in rows:
        membership = await _accept(
            db, invitation_id=invitation_id, organization_id=organization_id, user=user, actor_label="auth/google"
        )
        if membership is not None:
            accepted.append(membership)
    return accepted


async def accept_invitation_token(db: AsyncSession, *, user: User, token: str) -> Membership:
    """Accept from the invite link while already signed in with the invited e-mail."""
    if is_disabled_account(user) or is_rejected_account(user):
        raise InvitationNotFoundError("invitation not found")
    invitation = await db.scalar(
        select(PendingInvitation).where(PendingInvitation.token_hash == hash_token(token or ""))
    )
    if invitation is None:
        raise InvitationNotFoundError("invitation not found")
    status = invitation_status(invitation)
    if status != STATUS_OPEN:
        raise InvitationConflictError(status, f"invitation is {status.lower()}")
    if (user.email or "").strip().lower() != invitation.email:
        raise InvitationEmailMismatchError("signed in with a different e-mail address")
    membership = await _accept(
        db, invitation_id=invitation.id, organization_id=invitation.organization_id,
        user=user, actor_label="invitations/accept",
    )
    if membership is None:
        await db.refresh(invitation)
        status = invitation_status(invitation)
        if status != STATUS_OPEN:
            raise InvitationConflictError(status, f"invitation is {status.lower()}")
        raise InvitationConflictError("ORGANIZATION_NOT_APPROVED", "the organization is not approved")
    return membership


async def user_has_active_membership(db: AsyncSession, user_id: UUID) -> bool:
    return (
        await db.scalar(
            select(Membership.id)
            .where(Membership.user_id == user_id, Membership.state == MembershipState.ACTIVE)
            .limit(1)
        )
    ) is not None
