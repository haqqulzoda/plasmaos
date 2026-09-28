"""Organization-private W7 team scenario routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_approved_user
from app.core.security import authenticated_dependency
from app.db.session import get_db
from app.models.user import User
from app.schemas.team_scenarios import (
    ProposalHandoffResponse,
    TeamScenarioCreateRequest,
    TeamScenarioDecisionCreateRequest,
    TeamScenarioResponse,
    TeamScenarioRevisionCreateRequest,
)
from app.services.organization_context import (
    OrganizationAccessDeniedError,
    OrganizationContextRequiredError,
    resolve_organization_context,
)
from app.services.team_scenarios import (
    TeamScenarioEligibilityError,
    TeamScenarioNotFoundError,
    append_team_scenario_decision,
    create_team_scenario,
    get_proposal_handoff,
    get_team_scenario,
    list_team_scenarios,
    revise_team_scenario,
)


router = APIRouter(dependencies=[authenticated_dependency(), Depends(require_approved_user)])


async def _context(db: AsyncSession, user: User, organization_id: UUID | None):
    try:
        return await resolve_organization_context(db, user_id=user.id, organization_id=organization_id)
    except OrganizationContextRequiredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Team scenario resource not found") from exc


def _raise_domain(exc: Exception) -> None:
    if isinstance(exc, TeamScenarioNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, TeamScenarioEligibilityError):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise exc


@router.post("/{pursuit_id}/team-scenarios", response_model=TeamScenarioResponse, status_code=status.HTTP_201_CREATED)
async def create_scenario(
    pursuit_id: UUID, payload: TeamScenarioCreateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> TeamScenarioResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await create_team_scenario(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            membership_id=context.membership.id, request=payload,
        )
    except (TeamScenarioNotFoundError, TeamScenarioEligibilityError) as exc:
        _raise_domain(exc)


@router.get("/{pursuit_id}/team-scenarios", response_model=list[TeamScenarioResponse])
async def scenarios(
    pursuit_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> list[TeamScenarioResponse]:
    context = await _context(db, current_user, x_organization_id)
    return await list_team_scenarios(db, organization_id=context.organization.id, pursuit_id=pursuit_id)


@router.get("/{pursuit_id}/team-scenarios/{scenario_id}", response_model=TeamScenarioResponse)
async def scenario(
    pursuit_id: UUID, scenario_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> TeamScenarioResponse:
    context = await _context(db, current_user, x_organization_id)
    result = await get_team_scenario(
        db, organization_id=context.organization.id, pursuit_id=pursuit_id, scenario_id=scenario_id,
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Team scenario not found")
    return result


@router.post(
    "/{pursuit_id}/team-scenarios/{scenario_id}/revisions",
    response_model=TeamScenarioResponse, status_code=status.HTTP_201_CREATED,
)
async def revise_scenario(
    pursuit_id: UUID, scenario_id: UUID, payload: TeamScenarioRevisionCreateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> TeamScenarioResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await revise_team_scenario(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            scenario_id=scenario_id, membership_id=context.membership.id, request=payload,
        )
    except (TeamScenarioNotFoundError, TeamScenarioEligibilityError) as exc:
        _raise_domain(exc)


@router.post(
    "/{pursuit_id}/team-scenarios/{scenario_id}/revisions/{revision_id}/decisions",
    response_model=TeamScenarioResponse, status_code=status.HTTP_201_CREATED,
)
async def record_scenario_decision(
    pursuit_id: UUID, scenario_id: UUID, revision_id: UUID,
    payload: TeamScenarioDecisionCreateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> TeamScenarioResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await append_team_scenario_decision(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            scenario_id=scenario_id, revision_id=revision_id,
            membership_id=context.membership.id, request=payload,
        )
    except (TeamScenarioNotFoundError, TeamScenarioEligibilityError) as exc:
        _raise_domain(exc)


@router.get(
    "/{pursuit_id}/team-scenarios/{scenario_id}/revisions/{revision_id}/proposal-handoff",
    response_model=ProposalHandoffResponse,
)
async def proposal_handoff(
    pursuit_id: UUID, scenario_id: UUID, revision_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> ProposalHandoffResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await get_proposal_handoff(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            scenario_id=scenario_id, revision_id=revision_id,
        )
    except (TeamScenarioNotFoundError, TeamScenarioEligibilityError) as exc:
        _raise_domain(exc)
