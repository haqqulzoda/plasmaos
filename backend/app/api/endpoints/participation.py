"""Organization-private W6 participation routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_approved_user
from app.core.security import authenticated_dependency
from app.db.session import get_db
from app.models.user import User
from app.schemas.participation import (
    AvailabilityFactCreateRequest,
    CandidateParticipationResponse,
    InterestFactCreateRequest,
    ParticipationDecisionCreateRequest,
    ParticipationStartRequest,
)
from app.services.organization_context import (
    OrganizationAccessDeniedError,
    OrganizationContextRequiredError,
    resolve_organization_context,
)
from app.services.participation import (
    ParticipationEligibilityError,
    ParticipationNotFoundError,
    append_availability,
    append_interest,
    append_participation_decision,
    get_participation,
    list_participation,
    start_participation,
)


router = APIRouter(dependencies=[authenticated_dependency(), Depends(require_approved_user)])


async def _context(db: AsyncSession, user: User, organization_id: UUID | None):
    try:
        return await resolve_organization_context(
            db, user_id=user.id, organization_id=organization_id
        )
    except OrganizationContextRequiredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Participation resource not found") from exc


def _raise_domain(exc: Exception) -> None:
    if isinstance(exc, ParticipationNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ParticipationEligibilityError):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise exc


@router.post(
    "/{pursuit_id}/candidate-matches/{candidate_match_id}/participation-record",
    response_model=CandidateParticipationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_participation_record(
    pursuit_id: UUID, candidate_match_id: UUID, payload: ParticipationStartRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> CandidateParticipationResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await start_participation(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            candidate_match_id=candidate_match_id, membership_id=context.membership.id,
            request=payload,
        )
    except (ParticipationNotFoundError, ParticipationEligibilityError) as exc:
        _raise_domain(exc)


@router.get("/{pursuit_id}/participation-records", response_model=list[CandidateParticipationResponse])
async def participation_records(
    pursuit_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> list[CandidateParticipationResponse]:
    context = await _context(db, current_user, x_organization_id)
    return await list_participation(
        db, organization_id=context.organization.id, pursuit_id=pursuit_id,
    )


@router.get(
    "/{pursuit_id}/participation-records/{participation_record_id}",
    response_model=CandidateParticipationResponse,
)
async def participation_record(
    pursuit_id: UUID, participation_record_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> CandidateParticipationResponse:
    context = await _context(db, current_user, x_organization_id)
    result = await get_participation(
        db, organization_id=context.organization.id, pursuit_id=pursuit_id,
        participation_record_id=participation_record_id,
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Participation record not found")
    return result


@router.post(
    "/{pursuit_id}/participation-records/{participation_record_id}/availability-facts",
    response_model=CandidateParticipationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_availability(
    pursuit_id: UUID, participation_record_id: UUID, payload: AvailabilityFactCreateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> CandidateParticipationResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await append_availability(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            participation_record_id=participation_record_id,
            membership_id=context.membership.id, request=payload,
        )
    except (ParticipationNotFoundError, ParticipationEligibilityError) as exc:
        _raise_domain(exc)


@router.post(
    "/{pursuit_id}/participation-records/{participation_record_id}/interest-facts",
    response_model=CandidateParticipationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_interest(
    pursuit_id: UUID, participation_record_id: UUID, payload: InterestFactCreateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> CandidateParticipationResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await append_interest(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            participation_record_id=participation_record_id,
            membership_id=context.membership.id, request=payload,
        )
    except (ParticipationNotFoundError, ParticipationEligibilityError) as exc:
        _raise_domain(exc)


@router.post(
    "/{pursuit_id}/participation-records/{participation_record_id}/decisions",
    response_model=CandidateParticipationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_participation_decision(
    pursuit_id: UUID, participation_record_id: UUID,
    payload: ParticipationDecisionCreateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> CandidateParticipationResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await append_participation_decision(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            participation_record_id=participation_record_id,
            membership_id=context.membership.id, request=payload,
        )
    except (ParticipationNotFoundError, ParticipationEligibilityError) as exc:
        _raise_domain(exc)
