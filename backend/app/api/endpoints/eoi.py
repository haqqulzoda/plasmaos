"""D2-05 Expression of Interest routes (organization context + ACTIVE membership)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_approved_user
from app.core.security import authenticated_dependency
from app.db.session import get_db
from app.models.user import User
from app.schemas.eoi import EoiDraftCreateRequest, EoiDraftResponse, EoiSuggestionsResponse
from app.services.eoi import (
    EoiConflictError,
    EoiNotFoundError,
    create_eoi_draft,
    eoi_suggestions,
    get_eoi_draft,
    list_eoi_drafts,
    resolve_eoi_artifact,
)
from app.services.organization_context import (
    OrganizationAccessDeniedError,
    OrganizationContextRequiredError,
    resolve_organization_context,
)


router = APIRouter(dependencies=[authenticated_dependency(), Depends(require_approved_user)])


async def _context(db: AsyncSession, user: User, organization_id: UUID | None):
    try:
        return await resolve_organization_context(db, user_id=user.id, organization_id=organization_id)
    except OrganizationContextRequiredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Pursuit not found") from exc


def _raise(exc: Exception) -> None:
    if isinstance(exc, EoiNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, EoiConflictError):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise exc


@router.get("/{pursuit_id}/eoi/suggestions", response_model=EoiSuggestionsResponse)
async def read_eoi_suggestions(
    pursuit_id: UUID, analysis_run_id: UUID = Query(...),
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> EoiSuggestionsResponse:
    """Passive: reads the analysis, the organization's records and the notice. No AI, no writes."""
    context = await _context(db, current_user, x_organization_id)
    try:
        return await eoi_suggestions(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id, analysis_run_id=analysis_run_id,
        )
    except (EoiNotFoundError, EoiConflictError) as exc:
        _raise(exc)


@router.post("/{pursuit_id}/eoi-drafts", response_model=EoiDraftResponse, status_code=status.HTTP_201_CREATED)
async def create_draft(
    pursuit_id: UUID, payload: EoiDraftCreateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> EoiDraftResponse:
    """Synchronous: 201 only after both the DOCX and the PDF are stored."""
    context = await _context(db, current_user, x_organization_id)
    try:
        return await create_eoi_draft(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            membership_id=context.membership.id, request=payload,
        )
    except (EoiNotFoundError, EoiConflictError) as exc:
        _raise(exc)


@router.get("/{pursuit_id}/eoi-drafts", response_model=list[EoiDraftResponse])
async def read_drafts(
    pursuit_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> list[EoiDraftResponse]:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await list_eoi_drafts(db, organization_id=context.organization.id, pursuit_id=pursuit_id)
    except (EoiNotFoundError, EoiConflictError) as exc:
        _raise(exc)


@router.get("/{pursuit_id}/eoi-drafts/{draft_id}", response_model=EoiDraftResponse)
async def read_draft(
    pursuit_id: UUID, draft_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> EoiDraftResponse:
    context = await _context(db, current_user, x_organization_id)
    draft = await get_eoi_draft(db, organization_id=context.organization.id, pursuit_id=pursuit_id, draft_id=draft_id)
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="EOI draft not found")
    return draft


@router.get("/{pursuit_id}/eoi-artifacts/{artifact_id}/download")
async def download_artifact(
    pursuit_id: UUID, artifact_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> FileResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        artifact, draft, path = await resolve_eoi_artifact(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            artifact_id=artifact_id, membership_id=context.membership.id,
        )
    except (EoiNotFoundError, EoiConflictError) as exc:
        _raise(exc)
    suffix = "docx" if artifact.format == "DOCX" else "pdf"
    return FileResponse(
        path, media_type=artifact.media_type,
        filename=f"expression-of-interest-v{draft.version}-{draft.language}.{suffix}",
        headers={"Cache-Control": "private, no-store"},
    )
