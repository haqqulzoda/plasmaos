"""Organization-private W8 Proposal Evidence Pack routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_approved_user
from app.core.security import authenticated_dependency
from app.db.session import get_db
from app.models.user import User
from app.schemas.proposal_evidence import (
    ProposalEvidenceArtifactResponse,
    ProposalEvidenceExportRequest,
    ProposalEvidencePackResponse,
    ProposalEvidenceSealRequest,
    PursuitProposalWorkspaceResponse,
)
from app.services.organization_context import (
    OrganizationAccessDeniedError,
    OrganizationContextRequiredError,
    resolve_organization_context,
)
from app.services.proposal_evidence import (
    ProposalEvidenceEligibilityError,
    ProposalEvidenceNotFoundError,
    generate_proposal_evidence_artifact,
    get_proposal_evidence_pack,
    get_proposal_workspace,
    resolve_proposal_evidence_artifact,
    seal_proposal_evidence_pack,
)


router = APIRouter(dependencies=[authenticated_dependency(), Depends(require_approved_user)])


async def _context(db: AsyncSession, user: User, organization_id: UUID | None):
    try:
        return await resolve_organization_context(db, user_id=user.id, organization_id=organization_id)
    except OrganizationContextRequiredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Proposal workspace not found") from exc


def _domain_error(exc: Exception) -> None:
    if isinstance(exc, ProposalEvidenceNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ProposalEvidenceEligibilityError):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise exc


@router.get("/{pursuit_id}/proposal-workspace", response_model=PursuitProposalWorkspaceResponse)
async def proposal_workspace(
    pursuit_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> PursuitProposalWorkspaceResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await get_proposal_workspace(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            user_id=current_user.id,
        )
    except (ProposalEvidenceNotFoundError, ProposalEvidenceEligibilityError) as exc:
        _domain_error(exc)


@router.post(
    "/{pursuit_id}/proposal-evidence-packs",
    response_model=ProposalEvidencePackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def seal_pack(
    pursuit_id: UUID, payload: ProposalEvidenceSealRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> ProposalEvidencePackResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await seal_proposal_evidence_pack(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            membership_id=context.membership.id, request=payload,
        )
    except (ProposalEvidenceNotFoundError, ProposalEvidenceEligibilityError) as exc:
        _domain_error(exc)


@router.get(
    "/{pursuit_id}/proposal-evidence-packs/{pack_id}",
    response_model=ProposalEvidencePackResponse,
)
async def pack_detail(
    pursuit_id: UUID, pack_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> ProposalEvidencePackResponse:
    context = await _context(db, current_user, x_organization_id)
    result = await get_proposal_evidence_pack(
        db, organization_id=context.organization.id, pursuit_id=pursuit_id, pack_id=pack_id,
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Proposal Evidence Pack not found")
    return result


@router.post(
    "/{pursuit_id}/proposal-evidence-packs/{pack_id}/exports",
    response_model=ProposalEvidenceArtifactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_export(
    pursuit_id: UUID, pack_id: UUID, payload: ProposalEvidenceExportRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> ProposalEvidenceArtifactResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await generate_proposal_evidence_artifact(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            pack_id=pack_id, membership_id=context.membership.id, request=payload,
        )
    except (ProposalEvidenceNotFoundError, ProposalEvidenceEligibilityError) as exc:
        _domain_error(exc)


@router.get("/{pursuit_id}/proposal-evidence-artifacts/{artifact_id}/download")
async def download_export(
    pursuit_id: UUID, artifact_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> FileResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        artifact, path = await resolve_proposal_evidence_artifact(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            artifact_id=artifact_id, membership_id=context.membership.id,
        )
    except (ProposalEvidenceNotFoundError, ProposalEvidenceEligibilityError) as exc:
        _domain_error(exc)
    suffix = {"PDF": "pdf", "DOCX": "docx", "JSON": "json"}[artifact.artifact_type]
    historical = "-historical" if artifact.historical_snapshot else ""
    return FileResponse(
        path, media_type=artifact.media_type,
        filename=f"proposal-evidence-{artifact.pack_id}{historical}.{suffix}",
    )

