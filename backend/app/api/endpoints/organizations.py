"""Minimal organization context and membership management API."""

from __future__ import annotations

from uuid import UUID

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
from app.schemas.tenancy import MembershipInvitationRequest, MembershipLifecycleEventResponse, MembershipResponse, MembershipRevokeRequest, MembershipRoleRequest, OrganizationSummary
from app.services.memberships import LastOwnerError, MembershipError, MembershipNotFoundError, MembershipPermissionError, activate_invitation, change_membership_role, invite_member, revoke_membership
from app.services.organization_context import OrganizationAccessDeniedError, OrganizationContextRequiredError, resolve_organization_context


router = APIRouter(dependencies=[authenticated_dependency(), Depends(require_approved_user)])


def _membership_response(membership: Membership) -> MembershipResponse:
    return MembershipResponse(
        membership_id=membership.id, organization_id=membership.organization_id,
        user_id=membership.user_id, role=membership.role, state=membership.state,
        created_at=membership.created_at, updated_at=membership.updated_at,
        activated_at=membership.activated_at, revoked_at=membership.revoked_at,
    )


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
    memberships = list((await db.execute(
        select(Membership).where(Membership.organization_id == organization_id).order_by(Membership.created_at, Membership.id)
    )).scalars())
    return [_membership_response(membership) for membership in memberships]


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
