"""P2 partner finder: suggestions from public award records, introduction requests, the team queue."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_approved_user, require_operator
from app.core.security import authenticated_dependency
from app.db.session import get_db
from app.models.user import User
from app.schemas.partner_finder import (
    AdminPartnerRequestResponse,
    ExpertSuggestionsResponse,
    PartnerGapsResponse,
    PartnerRequestCreate,
    PartnerRequestResponse,
    PartnerRequestStatusChange,
    PartnerSuggestionsResponse,
    ProspectiveMemberCreate,
)
from app.services import partner_finder as service
from app.services.admin_alerts import kick_admin_alerts
from app.services.organization_context import (
    OrganizationAccessDeniedError,
    OrganizationContextRequiredError,
    resolve_organization_context,
)

router = APIRouter(dependencies=[authenticated_dependency(), Depends(require_approved_user)])
admin_router = APIRouter(dependencies=[Depends(require_operator)])


async def _context(db: AsyncSession, user: User, organization_id: UUID | None):
    try:
        return await resolve_organization_context(db, user_id=user.id, organization_id=organization_id)
    except OrganizationContextRequiredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Pursuit not found") from exc


def _raise(exc: service.PartnerFinderError) -> None:
    if isinstance(exc, service.PartnerFinderNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, service.PartnerFinderEligibilityError):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise HTTPException(422, detail=str(exc)) from exc


@router.get("/{pursuit_id}/partner-finder", response_model=PartnerGapsResponse)
async def partner_gaps(
    pursuit_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> PartnerGapsResponse:
    """The latest analysis's Gaps a partner firm or an expert can close, and this pursuit's requests."""
    context = await _context(db, current_user, x_organization_id)
    try:
        return PartnerGapsResponse(**await service.list_partner_gaps(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
        ))
    except service.PartnerFinderError as exc:
        _raise(exc)


@router.get("/{pursuit_id}/partner-suggestions", response_model=PartnerSuggestionsResponse)
async def partner_suggestions(
    pursuit_id: UUID, analysis_run_id: UUID = Query(...), gap_id: UUID = Query(...),
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> PartnerSuggestionsResponse:
    """Up to 10 firms that won similar contracts. Passive: nothing is stored."""
    context = await _context(db, current_user, x_organization_id)
    try:
        return PartnerSuggestionsResponse(**await service.partner_suggestions(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            analysis_run_id=analysis_run_id, gap_id=gap_id,
        ))
    except service.PartnerFinderError as exc:
        _raise(exc)


@router.get("/{pursuit_id}/expert-suggestions", response_model=ExpertSuggestionsResponse)
async def expert_suggestions(
    pursuit_id: UUID, analysis_run_id: UUID = Query(...), gap_id: UUID = Query(...),
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> ExpertSuggestionsResponse:
    """Experts from the organization's library and the shared network for a key-expert Gap. Passive."""
    context = await _context(db, current_user, x_organization_id)
    try:
        return ExpertSuggestionsResponse(**await service.expert_suggestions(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            analysis_run_id=analysis_run_id, gap_id=gap_id,
        ))
    except service.PartnerFinderError as exc:
        _raise(exc)


@router.get("/{pursuit_id}/partner-requests", response_model=list[PartnerRequestResponse])
async def partner_requests(
    pursuit_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> list[PartnerRequestResponse]:
    context = await _context(db, current_user, x_organization_id)
    try:
        await service.require_pursuit(db, context.organization.id, pursuit_id)
    except service.PartnerFinderError as exc:
        _raise(exc)
    return [PartnerRequestResponse(**item) for item in await service.list_requests(
        db, organization_id=context.organization.id, pursuit_id=pursuit_id,
    )]


@router.post("/{pursuit_id}/partner-requests", response_model=PartnerRequestResponse)
async def request_introduction(
    pursuit_id: UUID, payload: PartnerRequestCreate, response: Response,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> PartnerRequestResponse:
    """Ask the Plasma team for an introduction (or to source an expert). Nothing is sent to the firm.

    201 for a new request; 200 with the existing request when this Gap and firm were already requested.
    """
    context = await _context(db, current_user, x_organization_id)
    try:
        item, created = await service.create_request(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            membership_id=context.membership.id, user=current_user,
            analysis_run_id=payload.analysis_run_id, gap_id=payload.gap_id, kind=payload.kind,
            firm_key=payload.firm_key, note=payload.note,
        )
    except service.PartnerFinderError as exc:
        _raise(exc)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    if created:
        kick_admin_alerts()
    return PartnerRequestResponse(**item)


@router.post("/{pursuit_id}/team-scenarios/{scenario_id}/prospective-members", status_code=status.HTTP_204_NO_CONTENT)
async def add_prospective_member(
    pursuit_id: UUID, scenario_id: UUID, payload: ProspectiveMemberCreate,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> Response:
    """Add a partner who accepted an introduction as a prospective JV member ("not yet confirmed")."""
    context = await _context(db, current_user, x_organization_id)
    try:
        await service.add_prospective_member(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id, scenario_id=scenario_id,
            membership_id=context.membership.id, partner_request_id=payload.partner_request_id,
        )
    except service.PartnerFinderError as exc:
        _raise(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{pursuit_id}/team-scenarios/{scenario_id}/prospective-members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_prospective_member(
    pursuit_id: UUID, scenario_id: UUID, member_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> Response:
    context = await _context(db, current_user, x_organization_id)
    try:
        await service.remove_prospective_member(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id, scenario_id=scenario_id,
            member_id=member_id,
        )
    except service.PartnerFinderError as exc:
        _raise(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- the Plasma team's queue (operators and admins) ----------------------------------------------

@admin_router.get("", response_model=list[AdminPartnerRequestResponse])
async def admin_partner_requests(
    status_filter: str | None = Query(default=None, alias="status", pattern=r"^(REQUESTED|CONTACTED|ACCEPTED|DECLINED|INTRODUCED)$"),
    db: AsyncSession = Depends(get_db),
) -> list[AdminPartnerRequestResponse]:
    return [AdminPartnerRequestResponse(**item) for item in await service.admin_queue(db, status=status_filter)]


@admin_router.post("/{request_id}/status", response_model=AdminPartnerRequestResponse)
async def admin_change_status(
    request_id: UUID, payload: PartnerRequestStatusChange,
    current_user: User = Depends(require_operator), db: AsyncSession = Depends(get_db),
) -> AdminPartnerRequestResponse:
    """requested -> contacted -> accepted | declined -> introduced; audited, visible to the requester."""
    try:
        item = await service.change_status(
            db, request_id=request_id, status=payload.status, message=payload.message, actor=current_user,
        )
    except service.PartnerFinderError as exc:
        _raise(exc)
    return AdminPartnerRequestResponse(**item)
