"""Tenant-safe W5 candidate library and pursuit search endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, is_operator_user, require_approved_user
from app.core.security import authenticated_dependency
from app.db.session import get_db
from app.models.user import User
from app.schemas.candidate_retrieval import (
    CVVersionCreateRequest,
    CVVersionResponse,
    CandidateLibraryResponse,
    CandidateReviewRequest,
    CandidateReviewResponse,
    CandidateSearchRequest,
    CandidateSearchRunResponse,
    ExpertCreateRequest,
    ExpertResponse,
    ExpertUpdateRequest,
    FirmCreateRequest,
    FirmResponse,
    FirmUpdateRequest,
    ProjectReferenceCreateRequest,
    ProjectReferenceResponse,
    ProjectReferenceUpdateRequest,
    SelfFirmUpsertRequest,
)
from app.services.candidate_retrieval import (
    CandidateAccessError,
    CandidateEligibilityError,
    CandidateError,
    CandidateNotFoundError,
    CandidateValidationError,
    append_candidate_review,
    archive_project_reference,
    create_candidate_search,
    create_cv_version,
    create_expert,
    create_firm,
    create_project_reference,
    get_candidate_search,
    get_self_firm,
    list_candidate_library,
    list_candidate_searches,
    update_expert,
    update_firm,
    update_project_reference,
    upsert_self_firm,
)
from app.services.organization_context import (
    OrganizationAccessDeniedError,
    OrganizationContextRequiredError,
    resolve_organization_context,
)


router = APIRouter(dependencies=[authenticated_dependency(), Depends(require_approved_user)])
pursuit_router = APIRouter(dependencies=[authenticated_dependency(), Depends(require_approved_user)])


async def _context(db: AsyncSession, user: User, organization_id: UUID | None):
    try:
        return await resolve_organization_context(db, user_id=user.id, organization_id=organization_id)
    except OrganizationContextRequiredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Candidate resource not found") from exc


def _raise_domain(exc: Exception) -> None:
    if isinstance(exc, CandidateNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, CandidateAccessError):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, CandidateEligibilityError):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, CandidateValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.get("", response_model=CandidateLibraryResponse)
async def candidate_library(
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> CandidateLibraryResponse:
    context = await _context(db, current_user, x_organization_id)
    return await list_candidate_library(db, organization_id=context.organization.id)


@router.get("/self-firm", response_model=FirmResponse)
async def read_self_firm(
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> FirmResponse:
    """The organization's own firm and its project references. Passive: never creates."""
    context = await _context(db, current_user, x_organization_id)
    firm = await get_self_firm(db, organization_id=context.organization.id)
    if firm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Self firm not found")
    return firm


@router.put("/self-firm", response_model=FirmResponse)
async def save_self_firm(
    payload: SelfFirmUpsertRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> FirmResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await upsert_self_firm(
            db, organization_id=context.organization.id, actor_user_id=current_user.id, payload=payload,
        )
    except CandidateError as exc:
        _raise_domain(exc)


@router.post("/firms", response_model=FirmResponse, status_code=status.HTTP_201_CREATED)
async def add_firm(
    payload: FirmCreateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> FirmResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await create_firm(
            db, organization_id=context.organization.id, actor_user_id=current_user.id,
            payload=payload, operator=is_operator_user(current_user),
        )
    except (CandidateAccessError, CandidateEligibilityError, CandidateNotFoundError) as exc:
        _raise_domain(exc)


@router.patch("/firms/{firm_id}", response_model=FirmResponse)
async def edit_firm(
    firm_id: UUID, payload: FirmUpdateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> FirmResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await update_firm(
            db, organization_id=context.organization.id, firm_id=firm_id,
            payload=payload, operator=is_operator_user(current_user),
        )
    except (CandidateAccessError, CandidateEligibilityError, CandidateNotFoundError) as exc:
        _raise_domain(exc)


@router.post("/firms/{firm_id}/project-references", response_model=ProjectReferenceResponse, status_code=status.HTTP_201_CREATED)
async def add_project_reference(
    firm_id: UUID, payload: ProjectReferenceCreateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> ProjectReferenceResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await create_project_reference(
            db, organization_id=context.organization.id, firm_id=firm_id,
            actor_user_id=current_user.id, payload=payload, operator=is_operator_user(current_user),
        )
    except (CandidateAccessError, CandidateEligibilityError, CandidateNotFoundError) as exc:
        _raise_domain(exc)


@router.patch("/firms/{firm_id}/project-references/{reference_id}", response_model=ProjectReferenceResponse)
async def edit_project_reference(
    firm_id: UUID, reference_id: UUID, payload: ProjectReferenceUpdateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> ProjectReferenceResponse:
    """Returns the reference that now carries the edited facts (a new reference_id when anything changed)."""
    context = await _context(db, current_user, x_organization_id)
    try:
        return await update_project_reference(
            db, organization_id=context.organization.id, firm_id=firm_id, reference_id=reference_id,
            actor_user_id=current_user.id, payload=payload, operator=is_operator_user(current_user),
        )
    except CandidateError as exc:
        _raise_domain(exc)


@router.post("/firms/{firm_id}/project-references/{reference_id}/archive", response_model=ProjectReferenceResponse)
async def retire_project_reference(
    firm_id: UUID, reference_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> ProjectReferenceResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await archive_project_reference(
            db, organization_id=context.organization.id, firm_id=firm_id, reference_id=reference_id,
            actor_user_id=current_user.id, operator=is_operator_user(current_user),
        )
    except CandidateError as exc:
        _raise_domain(exc)


@router.post("/experts", response_model=ExpertResponse, status_code=status.HTTP_201_CREATED)
async def add_expert(
    payload: ExpertCreateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> ExpertResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await create_expert(
            db, organization_id=context.organization.id, actor_user_id=current_user.id,
            payload=payload, operator=is_operator_user(current_user),
        )
    except (CandidateAccessError, CandidateEligibilityError, CandidateNotFoundError) as exc:
        _raise_domain(exc)


@router.patch("/experts/{expert_id}", response_model=ExpertResponse)
async def edit_expert(
    expert_id: UUID, payload: ExpertUpdateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> ExpertResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await update_expert(
            db, organization_id=context.organization.id, expert_id=expert_id,
            payload=payload, operator=is_operator_user(current_user),
        )
    except (CandidateAccessError, CandidateEligibilityError, CandidateNotFoundError) as exc:
        _raise_domain(exc)


@router.post("/experts/{expert_id}/cv-versions", response_model=CVVersionResponse, status_code=status.HTTP_201_CREATED)
async def add_cv_version(
    expert_id: UUID, payload: CVVersionCreateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> CVVersionResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await create_cv_version(
            db, organization_id=context.organization.id, expert_id=expert_id,
            actor_user_id=current_user.id, payload=payload, operator=is_operator_user(current_user),
        )
    except (CandidateAccessError, CandidateEligibilityError, CandidateNotFoundError) as exc:
        _raise_domain(exc)


@pursuit_router.post("/{pursuit_id}/candidate-search-runs", response_model=CandidateSearchRunResponse, status_code=status.HTTP_201_CREATED)
async def search_candidates(
    pursuit_id: UUID, payload: CandidateSearchRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> CandidateSearchRunResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await create_candidate_search(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            membership_id=context.membership.id, request=payload,
        )
    except (CandidateAccessError, CandidateEligibilityError, CandidateNotFoundError) as exc:
        _raise_domain(exc)


@pursuit_router.get("/{pursuit_id}/candidate-search-runs", response_model=list[CandidateSearchRunResponse])
async def candidate_search_history(
    pursuit_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> list[CandidateSearchRunResponse]:
    context = await _context(db, current_user, x_organization_id)
    return await list_candidate_searches(
        db, organization_id=context.organization.id, pursuit_id=pursuit_id,
    )


@pursuit_router.get("/{pursuit_id}/candidate-search-runs/{search_run_id}", response_model=CandidateSearchRunResponse)
async def candidate_search_detail(
    pursuit_id: UUID, search_run_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> CandidateSearchRunResponse:
    context = await _context(db, current_user, x_organization_id)
    result = await get_candidate_search(
        db, organization_id=context.organization.id, pursuit_id=pursuit_id,
        search_run_id=search_run_id,
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Candidate search run not found")
    return result


@pursuit_router.post(
    "/{pursuit_id}/candidate-search-runs/{search_run_id}/matches/{match_id}/reviews",
    response_model=CandidateReviewResponse, status_code=status.HTTP_201_CREATED,
)
async def review_candidate_match(
    pursuit_id: UUID, search_run_id: UUID, match_id: UUID, payload: CandidateReviewRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> CandidateReviewResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await append_candidate_review(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            search_run_id=search_run_id, match_id=match_id,
            membership_id=context.membership.id, request=payload,
        )
    except (CandidateAccessError, CandidateEligibilityError, CandidateNotFoundError) as exc:
        _raise_domain(exc)

