"""Minimal organization context and membership management API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_approved_user
from app.core.security import authenticated_dependency
from app.db.session import get_db
from app.models.base import MembershipState
from app.models.tenancy import Membership, Organization
from app.models.private_documents import MembershipLifecycleEvent
from app.models.user import User
from app.schemas.tenancy import (
    EmailInvitationCreateRequest,
    EmailInvitationResponse,
    InvitationPreviewResponse,
    InvitationResendRequest,
    InvitationTokenRequest,
    MembershipInvitationRequest,
    MembershipLifecycleEventResponse,
    MembershipResponse,
    MembershipRevokeRequest,
    MembershipRoleRequest,
    OrganizationSummary,
)
from app.models.invitations import PendingInvitation
from app.models.organization_records import OrganizationRecordEvent
from app.services.invitations import (
    InvitationConflictError,
    InvitationEmailMismatchError,
    InvitationError,
    InvitationNotFoundError,
    IssuedInvitation,
    accept_invitation_token,
    create_email_invitation,
    invitation_status,
    invite_path,
    invite_url,
    list_email_invitations,
    preview_invitation,
    resend_email_invitation,
    revoke_email_invitation,
)
from app.services.memberships import LastOwnerError, MembershipError, MembershipNotFoundError, MembershipPermissionError, activate_invitation, change_membership_role, invite_member, revoke_membership
from app.services.organization_context import OrganizationAccessDeniedError, OrganizationContextRequiredError, resolve_organization_context


router = APIRouter(dependencies=[authenticated_dependency(), Depends(require_approved_user)])
# Invitation landing page (R3): a token-gated public preview, and an accept for a signed-in
# (possibly still pending) user. Mounted at /api/v1/invitations.
invitations_router = APIRouter()


def _membership_response(membership: Membership, user: User | None = None) -> MembershipResponse:
    return MembershipResponse(
        membership_id=membership.id, organization_id=membership.organization_id,
        user_id=membership.user_id, role=membership.role, state=membership.state,
        created_at=membership.created_at, updated_at=membership.updated_at,
        activated_at=membership.activated_at, revoked_at=membership.revoked_at,
        user_name=user.name if user is not None else None,
        user_email=user.email if user is not None else None,
    )


def _invitation_response(
    invitation: PendingInvitation,
    *,
    inviter_name: str | None = None,
    issued: IssuedInvitation | None = None,
    email_delivery: str | None = None,
) -> EmailInvitationResponse:
    return EmailInvitationResponse(
        invitation_id=invitation.id, organization_id=invitation.organization_id,
        email=invitation.email, role=invitation.role, status=invitation_status(invitation),
        invited_by_membership_id=invitation.invited_by_membership_id, invited_by_name=inviter_name,
        expires_at=invitation.expires_at, created_at=invitation.created_at,
        last_sent_at=invitation.last_sent_at, send_count=invitation.send_count,
        accepted_at=invitation.accepted_at, revoked_at=invitation.revoked_at,
        accepted_user_id=invitation.accepted_user_id,
        invite_path=invite_path(issued.token) if issued is not None else None,
        invite_url=invite_url(issued.token) if issued is not None else None,
        email_delivery=email_delivery,
    )


def _invitation_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MembershipPermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail="OWNER membership required")
    if isinstance(exc, InvitationNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    if isinstance(exc, InvitationEmailMismatchError):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "EMAIL_MISMATCH", "message": str(exc)})
    if isinstance(exc, InvitationConflictError):
        return HTTPException(status.HTTP_409_CONFLICT, detail={"code": exc.code, "message": str(exc)})
    return HTTPException(422, detail=str(exc))


async def _context(db: AsyncSession, user: User, organization_id: UUID | None):
    try:
        return await resolve_organization_context(db, user_id=user.id, organization_id=organization_id)
    except OrganizationContextRequiredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organization not found") from exc


@router.get("", response_model=list[OrganizationSummary])
async def list_my_organizations(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[OrganizationSummary]:
    rows = (await db.execute(
        select(Organization, Membership).join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == current_user.id, Membership.state == MembershipState.ACTIVE)
        .order_by(Organization.created_at, Organization.id)
    )).all()
    return [OrganizationSummary(
        organization_id=organization.id, legacy_company_profile_id=organization.legacy_company_profile_id,
        display_name=organization.display_name, membership_id=membership.id,
        membership_role=membership.role, membership_state=membership.state,
    ) for organization, membership in rows]


@router.get("/context", response_model=OrganizationSummary)
async def get_organization_context(
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> OrganizationSummary:
    context = await _context(db, current_user, x_organization_id)
    return OrganizationSummary(
        organization_id=context.organization.id,
        legacy_company_profile_id=context.organization.legacy_company_profile_id,
        display_name=context.organization.display_name, membership_id=context.membership.id,
        membership_role=context.membership.role, membership_state=context.membership.state,
    )


@router.get("/{organization_id}/members", response_model=list[MembershipResponse])
async def list_members(organization_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[MembershipResponse]:
    context = await _context(db, current_user, organization_id)
    if context.membership.role.value != "OWNER":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="OWNER membership required")
    rows = (await db.execute(
        select(Membership, User).join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == organization_id).order_by(Membership.created_at, Membership.id)
    )).all()
    return [_membership_response(membership, user) for membership, user in rows]


@router.get("/{organization_id}/membership-events", response_model=list[MembershipLifecycleEventResponse])
async def list_membership_events(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MembershipLifecycleEventResponse]:
    context = await _context(db, current_user, organization_id)
    if context.membership.role.value != "OWNER":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="OWNER membership required")
    events = list(
        (
            await db.scalars(
                select(MembershipLifecycleEvent)
                .where(MembershipLifecycleEvent.organization_id == organization_id)
                .order_by(MembershipLifecycleEvent.created_at, MembershipLifecycleEvent.id)
                .limit(1000)
            )
        ).all()
    )
    return [
        MembershipLifecycleEventResponse(
            event_id=event.id,
            organization_id=event.organization_id,
            membership_id=event.membership_id,
            actor_user_id=event.actor_user_id,
            actor_membership_id=event.actor_membership_id,
            action=event.action,
            previous_role=event.previous_role,
            new_role=event.new_role,
            previous_state=event.previous_state,
            new_state=event.new_state,
            created_at=event.created_at,
        )
        for event in events
    ]


@router.post("/{organization_id}/invitations", response_model=MembershipResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    organization_id: UUID, payload: MembershipInvitationRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> MembershipResponse:
    context = await _context(db, current_user, organization_id)
    try:
        membership = await invite_member(db, organization_id=organization_id, actor_membership_id=context.membership.id, user_id=payload.user_id)
    except MembershipPermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except MembershipNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _membership_response(membership)


@router.post("/memberships/{membership_id}/activate", response_model=MembershipResponse)
async def accept_invitation(membership_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> MembershipResponse:
    try:
        membership = await activate_invitation(db, membership_id=membership_id, user_id=current_user.id)
    except MembershipNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invitation not found") from exc
    except MembershipError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _membership_response(membership)


@router.patch("/{organization_id}/members/{membership_id}/role", response_model=MembershipResponse)
async def update_member_role(
    organization_id: UUID, membership_id: UUID, payload: MembershipRoleRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> MembershipResponse:
    context = await _context(db, current_user, organization_id)
    try:
        membership = await change_membership_role(db, organization_id=organization_id, actor_membership_id=context.membership.id, membership_id=membership_id, role=payload.role)
    except MembershipPermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except MembershipNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Membership not found") from exc
    except (MembershipError, LastOwnerError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _membership_response(membership)


@router.post("/{organization_id}/members/{membership_id}/revoke", response_model=MembershipResponse)
async def revoke_member(
    organization_id: UUID, membership_id: UUID, payload: MembershipRevokeRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> MembershipResponse:
    context = await _context(db, current_user, organization_id)
    try:
        membership = await revoke_membership(
            db, organization_id=organization_id, actor_membership_id=context.membership.id,
            membership_id=membership_id, transfer_to_membership_id=payload.transfer_to_membership_id,
        )
    except MembershipPermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except MembershipNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Membership not found") from exc
    except (MembershipError, LastOwnerError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _membership_response(membership)


# ---- R3 Task 1: invitations by e-mail ------------------------------------------------------------


async def _require_owner_context(db: AsyncSession, user: User, organization_id: UUID):
    context = await _context(db, user, organization_id)
    if context.membership.role.value != "OWNER":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="OWNER membership required")
    return context


async def _queue_invitation_email(db: AsyncSession, issued: IssuedInvitation, inviter: User) -> str:
    """Queue the invitation e-mail when delivery is configured; DISABLED otherwise."""
    from app.services.email_notifications import queue_invitation_email

    return await queue_invitation_email(db, invitation=issued.invitation, token=issued.token, inviter=inviter)


@router.post(
    "/{organization_id}/invitations-by-email",
    response_model=EmailInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_email_invitation_endpoint(
    organization_id: UUID, payload: EmailInvitationCreateRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> EmailInvitationResponse:
    context = await _require_owner_context(db, current_user, organization_id)
    try:
        issued = await create_email_invitation(
            db, organization_id=organization_id, actor_membership_id=context.membership.id,
            email=payload.email, role=payload.role,
        )
    except (MembershipPermissionError, InvitationError) as exc:
        raise _invitation_http_error(exc) from exc
    delivery = await _queue_invitation_email(db, issued, current_user)
    return _invitation_response(
        issued.invitation, inviter_name=current_user.name, issued=issued, email_delivery=delivery
    )


@router.get("/{organization_id}/invitations-by-email", response_model=list[EmailInvitationResponse])
async def list_email_invitations_endpoint(
    organization_id: UUID,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> list[EmailInvitationResponse]:
    await _require_owner_context(db, current_user, organization_id)
    invitations = await list_email_invitations(db, organization_id=organization_id)
    inviter_ids = {invitation.invited_by_membership_id for invitation in invitations}
    names: dict[UUID, str] = {}
    if inviter_ids:
        names = dict(
            (
                await db.execute(
                    select(Membership.id, User.name).join(User, User.id == Membership.user_id)
                    .where(Membership.id.in_(inviter_ids))
                )
            ).all()
        )
    return [
        _invitation_response(invitation, inviter_name=names.get(invitation.invited_by_membership_id))
        for invitation in invitations
    ]


@router.post(
    "/{organization_id}/invitations-by-email/{invitation_id}/revoke",
    response_model=EmailInvitationResponse,
)
async def revoke_email_invitation_endpoint(
    organization_id: UUID, invitation_id: UUID,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> EmailInvitationResponse:
    context = await _require_owner_context(db, current_user, organization_id)
    try:
        invitation = await revoke_email_invitation(
            db, organization_id=organization_id, actor_membership_id=context.membership.id,
            invitation_id=invitation_id,
        )
    except (MembershipPermissionError, InvitationError) as exc:
        raise _invitation_http_error(exc) from exc
    return _invitation_response(invitation)


@router.post(
    "/{organization_id}/invitations-by-email/{invitation_id}/resend",
    response_model=EmailInvitationResponse,
)
async def resend_email_invitation_endpoint(
    organization_id: UUID, invitation_id: UUID, payload: InvitationResendRequest | None = None,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> EmailInvitationResponse:
    context = await _require_owner_context(db, current_user, organization_id)
    try:
        issued = await resend_email_invitation(
            db, organization_id=organization_id, actor_membership_id=context.membership.id,
            invitation_id=invitation_id,
        )
    except (MembershipPermissionError, InvitationError) as exc:
        raise _invitation_http_error(exc) from exc
    send_email = payload.send_email if payload is not None else True
    delivery = await _queue_invitation_email(db, issued, current_user) if send_email else "SKIPPED"
    return _invitation_response(
        issued.invitation, inviter_name=current_user.name, issued=issued, email_delivery=delivery
    )


@invitations_router.post("/preview", response_model=InvitationPreviewResponse)
async def preview_invitation_endpoint(
    payload: InvitationTokenRequest, db: AsyncSession = Depends(get_db),
) -> InvitationPreviewResponse:
    preview = await preview_invitation(db, token=payload.token)
    if preview is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    return InvitationPreviewResponse(**preview)


@invitations_router.post("/accept", response_model=MembershipResponse, dependencies=[authenticated_dependency()])
async def accept_invitation_endpoint(
    payload: InvitationTokenRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> MembershipResponse:
    try:
        membership = await accept_invitation_token(db, user=current_user, token=payload.token)
    except InvitationError as exc:
        raise _invitation_http_error(exc) from exc
    return _membership_response(membership, current_user)


# ---- R3 Task 6: who changed the organization's company profile and readiness records -------------


class OrganizationRecordEventResponse(BaseModel):
    event_id: UUID
    organization_id: UUID
    record_type: str
    record_id: UUID | None = None
    action: str
    changed_fields: list[str]
    actor_user_id: UUID | None = None
    actor_name: str | None = None
    actor_membership_id: UUID | None = None
    created_at: datetime


@router.get("/{organization_id}/record-events", response_model=list[OrganizationRecordEventResponse])
async def list_organization_record_events(
    organization_id: UUID,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> list[OrganizationRecordEventResponse]:
    await _require_owner_context(db, current_user, organization_id)
    rows = (await db.execute(
        select(OrganizationRecordEvent, User.name)
        .outerjoin(User, User.id == OrganizationRecordEvent.actor_user_id)
        .where(OrganizationRecordEvent.organization_id == organization_id)
        .order_by(OrganizationRecordEvent.created_at.desc(), OrganizationRecordEvent.id.desc())
        .limit(500)
    )).all()
    return [
        OrganizationRecordEventResponse(
            event_id=event.id, organization_id=event.organization_id, record_type=event.record_type,
            record_id=event.record_id, action=event.action, changed_fields=list(event.changed_fields or []),
            actor_user_id=event.actor_user_id, actor_name=name, actor_membership_id=event.actor_membership_id,
            created_at=event.created_at,
        )
        for event, name in rows
    ]
