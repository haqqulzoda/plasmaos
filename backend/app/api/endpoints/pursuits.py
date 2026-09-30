"""Tenant-scoped canonical pursuit API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from pydantic import ValidationError

from app.api.deps import get_current_user, require_approved_user
from app.core.deadline_truth import truth_fields
from app.core.security import authenticated_dependency
from app.db.session import get_db
from app.models.all_models import Tender
from app.core.private_storage import PrivateUploadError, private_storage_root, resolve_private_storage_key, stage_private_upload
from app.models.base import DocumentProcessingState, PrivateDocumentRole, PursuitOrigin, TenderEngagementOrigin, TenderEngagementStatus
from app.models.private_documents import DocumentProcessingJob, DocumentVersion, PrivateDocument, PrivateDocumentBatch, PursuitTenderContext
from app.models.tenancy import Membership, OrganizationPursuit
from app.models.user import User
from app.schemas.tenancy import (
    AnalysisLineageRequest,
    AnalysisLineageResponse,
    AnalysisPackCandidateResponse,
    AnalysisReviewAssertionRequest,
    AnalysisReviewAssertionResponse,
    PrivateDocumentItem,
    PrivateDocumentListResponse,
    PrivateDocumentRoleRequest,
    PrivateUploadResponse,
    PursuitContextResponse,
    PursuitContextFieldProvenanceResponse,
    PursuitContextSuggestionResponse,
    PursuitContextUpdateRequest,
    PursuitAnalysisResponse,
    PursuitAnalysisStartRequest,
    PursuitAnalysisStartResponse,
    PursuitListResponse,
    PursuitOwnerRequest,
    PursuitReopenRequest,
    PursuitResponse,
    PursuitTransitionRequest,
    SourcePursuitCreateRequest,
)
from app.services.pursuit_analysis import (
    AnalysisAdmissionError,
    AnalysisNotFoundError,
    append_lineage,
    append_review_assertion,
    create_analysis_run,
    get_analysis_run,
)
from app.services.organization_context import OrganizationAccessDeniedError, OrganizationContextRequiredError, resolve_organization_context
from app.services.private_documents import (
    build_analysis_pack_candidate,
    PrivateDocumentError,
    PrivateDocumentNotFoundError,
    PrivateDocumentRetryError,
    StagedPrivateFile,
    add_document_version,
    get_authorized_version,
    get_context,
    list_private_documents,
    persist_private_pack,
    retry_processing_job,
    update_document_role,
    update_context,
)
from app.services.pursuits import PursuitError, PursuitNotFoundError, PursuitOwnershipError, PursuitTransitionError, assign_pursuit_owner, create_upload_pursuit, get_or_create_source_pursuit, get_owned_pursuit, reopen_pursuit, transition_pursuit
from app.workers.private_document_tasks import dispatch_job_ids
from app.workers.pursuit_analysis_tasks import dispatch_run_ids


router = APIRouter(dependencies=[authenticated_dependency(), Depends(require_approved_user)])


@dataclass(frozen=True)
class _ProcessingRollup:
    state: DocumentProcessingState
    processed_count: int
    failed_count: int


async def _context(db: AsyncSession, user: User, organization_id: UUID | None):
    try:
        return await resolve_organization_context(db, user_id=user.id, organization_id=organization_id)
    except OrganizationContextRequiredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Pursuit not found") from exc


def _response(
    pursuit: OrganizationPursuit,
    tender: Tender | None = None,
    context: PursuitTenderContext | None = None,
    batch: PrivateDocumentBatch | _ProcessingRollup | None = None,
    file_count: int = 0,
    owner_name: str | None = None,
) -> PursuitResponse:
    truth = truth_fields(tender.source_system, tender.status, tender.deadline, country=tender.country) if tender else {}
    return PursuitResponse(
        source_tender_status=truth["status"].value if truth else None,
        source_tender_status_reason=truth.get("status_reason"),
        source_deadline_time_basis=truth.get("deadline_time_basis"),
        source_deadline_timezone=truth.get("deadline_timezone"),
        source_deadline_published_local=truth.get("deadline_published_local"),
        source_deadline_effective_at=truth.get("deadline_effective_at"),
        source_deadline_closes_at=truth.get("deadline_closes_at"),
        pursuit_id=pursuit.id, organization_id=pursuit.organization_id,
        source_tender_id=pursuit.source_tender_id, origin=pursuit.origin,
        legacy_engagement_id=pursuit.legacy_engagement_id,
        owner_membership_id=pursuit.owner_membership_id, stage=pursuit.stage,
        internal_target_at=pursuit.internal_target_at, archived_at=pursuit.archived_at,
        created_at=pursuit.created_at, updated_at=pursuit.updated_at,
        stage_changed_at=pursuit.stage_changed_at,
        tender_title=tender.title if tender else None,
        source_deadline=tender.deadline if tender else None,
        title=context.title if context else (tender.title if tender else None),
        buyer=context.buyer if context else (tender.buyer if tender else None),
        declared_funder=context.declared_funder if context else None,
        country=context.country if context else (tender.country if tender else None),
        reference=context.reference if context else (tender.external_id if tender else None),
        external_deadline=context.external_deadline if context else None,
        deadline_timezone=context.deadline_timezone if context else None,
        source_url=context.source_url if context else None,
        confirmed_fields=sorted((context.confirmed_fields or {}).keys()) if context else [],
        processing_state=batch.state if batch else None,
        file_count=file_count,
        processed_count=batch.processed_count if batch else 0,
        failed_count=batch.failed_count if batch else 0,
        owner_name=owner_name,
    )


async def _enrichment_maps(db: AsyncSession, pursuit_ids: list[UUID]):
    if not pursuit_ids:
        return {}, {}
    terminal_states = (
        DocumentProcessingState.READY,
        DocumentProcessingState.PARTIAL,
        DocumentProcessingState.FAILED,
    )
    rows = (
        await db.execute(
            select(
                PrivateDocument.pursuit_id,
                func.count(PrivateDocument.id),
                func.count(DocumentProcessingJob.id).filter(
                    DocumentProcessingJob.state.in_(terminal_states)
                ),
                func.count(DocumentProcessingJob.id).filter(
                    DocumentProcessingJob.state == DocumentProcessingState.FAILED
                ),
                func.count(DocumentProcessingJob.id).filter(
                    DocumentProcessingJob.state == DocumentProcessingState.PARTIAL
                ),
                func.count(DocumentProcessingJob.id).filter(
                    DocumentProcessingJob.state == DocumentProcessingState.EXTRACTING
                ),
            )
            .join(
                DocumentVersion,
                DocumentVersion.id == PrivateDocument.current_version_id,
            )
            .outerjoin(
                DocumentProcessingJob,
                DocumentProcessingJob.document_version_id == DocumentVersion.id,
            )
            .where(
                PrivateDocument.pursuit_id.in_(pursuit_ids),
                PrivateDocument.state == "ACTIVE",
            )
            .group_by(PrivateDocument.pursuit_id)
        )
    ).all()
    counts: dict[UUID, int] = {}
    rollups: dict[UUID, _ProcessingRollup] = {}
    for pursuit_id, total, processed, failed, partial, extracting in rows:
        total = int(total)
        processed = int(processed)
        failed = int(failed)
        if processed == total:
            state = (
                DocumentProcessingState.FAILED
                if failed == total
                else DocumentProcessingState.PARTIAL
                if failed or int(partial)
                else DocumentProcessingState.READY
            )
        else:
            state = (
                DocumentProcessingState.EXTRACTING
                if int(extracting)
                else DocumentProcessingState.CHECKING
            )
        counts[pursuit_id] = total
        rollups[pursuit_id] = _ProcessingRollup(
            state=state,
            processed_count=processed,
            failed_count=failed,
        )
    return counts, rollups


async def _pursuit_detail_row(db: AsyncSession, organization_id: UUID, pursuit_id: UUID):
    owner_membership = aliased(Membership)
    owner_user = aliased(User)
    return (
        await db.execute(
            select(OrganizationPursuit, Tender, PursuitTenderContext, owner_user.name)
            .outerjoin(Tender, Tender.id == OrganizationPursuit.source_tender_id)
            .outerjoin(PursuitTenderContext, PursuitTenderContext.pursuit_id == OrganizationPursuit.id)
            .outerjoin(owner_membership, owner_membership.id == OrganizationPursuit.owner_membership_id)
            .outerjoin(owner_user, owner_user.id == owner_membership.user_id)
            .where(
                OrganizationPursuit.organization_id == organization_id,
                OrganizationPursuit.id == pursuit_id,
            )
        )
    ).one_or_none()


def _http_private_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PrivateUploadError):
        return HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.detail})
    if isinstance(exc, PrivateDocumentNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, PrivateDocumentRetryError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


def _roles(raw: str, count: int) -> list[PrivateDocumentRole]:
    try:
        values = json.loads(raw or "[]")
        if not isinstance(values, list) or len(values) not in {0, count}:
            raise ValueError()
        return [PrivateDocumentRole(value) for value in values] if values else [PrivateDocumentRole.OTHER] * count
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Document roles must match uploaded files") from None


async def _stage_files(
    files: list[UploadFile], roles_raw: str, directory: str | Path
) -> list[StagedPrivateFile]:
    if not files:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="At least one accepted file is required")
    roles = _roles(roles_raw, len(files))
    staging_directory = Path(directory)
    staged: list[StagedPrivateFile] = []
    try:
        for upload, role in zip(files, roles, strict=True):
            path, original, display, size, digest = await stage_private_upload(
                upload, staging_directory
            )
            staged.append(
                StagedPrivateFile(
                    path=path,
                    original_filename=original,
                    safe_display_filename=display,
                    media_type=(upload.content_type or "").split(";", 1)[0].casefold(),
                    byte_size=size,
                    sha256=digest,
                    role=role,
                )
            )
    except Exception:
        for item in staged:
            item.path.unlink(missing_ok=True)
        raise
    return staged


@router.get("", response_model=PursuitListResponse)
async def list_pursuits(
    origin: PursuitOrigin | None = Query(default=None),
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    offset: int = Query(default=0, ge=0), limit: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> PursuitListResponse:
    context = await _context(db, current_user, x_organization_id)
    owner_membership = aliased(Membership)
    owner_user = aliased(User)
    statement = (
        select(OrganizationPursuit, Tender, PursuitTenderContext, owner_user.name)
        .outerjoin(Tender, Tender.id == OrganizationPursuit.source_tender_id)
        .outerjoin(PursuitTenderContext, PursuitTenderContext.pursuit_id == OrganizationPursuit.id)
        .outerjoin(owner_membership, owner_membership.id == OrganizationPursuit.owner_membership_id)
        .outerjoin(owner_user, owner_user.id == owner_membership.user_id)
        .where(OrganizationPursuit.organization_id == context.organization.id)
        .order_by(OrganizationPursuit.updated_at.desc(), OrganizationPursuit.id)
        .offset(offset).limit(limit)
    )
    if origin is not None:
        statement = statement.where(OrganizationPursuit.origin == origin)
    rows = (await db.execute(statement)).all()
    pursuit_ids = [row[0].id for row in rows]
    counts, batches = await _enrichment_maps(db, pursuit_ids)
    total_statement = select(func.count(OrganizationPursuit.id)).where(
        OrganizationPursuit.organization_id == context.organization.id
    )
    if origin is not None:
        total_statement = total_statement.where(OrganizationPursuit.origin == origin)
    total = int(await db.scalar(
        total_statement
    ) or 0)
    return PursuitListResponse(
        items=[
            _response(
                pursuit,
                tender,
                private_context,
                batches.get(pursuit.id),
                int(counts.get(pursuit.id, 0)),
                owner_name,
            )
            for pursuit, tender, private_context, owner_name in rows
        ],
        total=total, limit=limit, offset=offset,
    )


@router.post("/upload", response_model=PrivateUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_tender(
    files: list[UploadFile] = File(...),
    roles: str = Form(default="[]"),
    context_json: str = Form(default="{}"),
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PrivateUploadResponse:
    organization_context = await _context(db, current_user, x_organization_id)
    try:
        raw_context = json.loads(context_json or "{}")
        context_payload = PursuitContextUpdateRequest.model_validate(raw_context)
    except (json.JSONDecodeError, ValidationError, TypeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Tender context is invalid") from None
    staging_root = private_storage_root() / ".staging"
    staging_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with TemporaryDirectory(prefix="pack-", dir=staging_root) as temporary:
            staged = await _stage_files(files, roles, temporary)
            pursuit = await create_upload_pursuit(
                db,
                organization_id=organization_context.organization.id,
                actor_user_id=current_user.id,
                actor_membership_id=organization_context.membership.id,
            )
            values = context_payload.model_dump(exclude_unset=True, exclude={"confirmed_fields"})
            now = datetime.now(timezone.utc)
            confirmed = {
                key: {
                    "membership_id": str(organization_context.membership.id),
                    "confirmed_at": now.isoformat(),
                }
                for key in context_payload.confirmed_fields
            }
            private_context = PursuitTenderContext(
                pursuit_id=pursuit.id,
                organization_id=pursuit.organization_id,
                confirmed_fields=confirmed,
                confirmed_by_membership_id=(organization_context.membership.id if confirmed else None),
                confirmed_at=(now if confirmed else None),
                **values,
            )
            db.add(private_context)
            pack = await persist_private_pack(
                db,
                pursuit=pursuit,
                membership_id=organization_context.membership.id,
                files=staged,
            )
    except (PrivateUploadError, PrivateDocumentError) as exc:
        raise _http_private_error(exc) from exc
    dispatch_job_ids(pack.job_ids)
    return PrivateUploadResponse(
        pursuit=_response(pursuit, context=private_context, batch=pack.batch, file_count=len(pack.document_ids), owner_name=current_user.name),
        batch_id=pack.batch.id,
        document_ids=list(pack.document_ids),
        processing_state=pack.batch.state,
        duplicate_document_ids=list(pack.duplicate_document_ids),
    )


@router.post("/source/{tender_id}/documents", response_model=PrivateUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_source_pursuit_documents(
    tender_id: UUID,
    files: list[UploadFile] = File(...),
    roles: str = Form(default="[]"),
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PrivateUploadResponse:
    organization_context = await _context(db, current_user, x_organization_id)
    staging_root = private_storage_root() / ".staging"
    staging_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with TemporaryDirectory(prefix="pack-", dir=staging_root) as temporary:
            staged = await _stage_files(files, roles, temporary)
            resolution = await get_or_create_source_pursuit(
                db,
                organization_id=organization_context.organization.id,
                actor_user_id=current_user.id,
                actor_membership_id=organization_context.membership.id,
                tender_id=tender_id,
                stage=TenderEngagementStatus.SAVED,
                legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
            )
            pack = await persist_private_pack(
                db,
                pursuit=resolution.pursuit,
                membership_id=organization_context.membership.id,
                files=staged,
            )
    except PursuitNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Tender not found") from exc
    except (PrivateUploadError, PrivateDocumentError) as exc:
        raise _http_private_error(exc) from exc
    dispatch_job_ids(pack.job_ids)
    return PrivateUploadResponse(
        pursuit=_response(pack.pursuit, batch=pack.batch, file_count=len(pack.document_ids), owner_name=current_user.name),
        batch_id=pack.batch.id,
        document_ids=list(pack.document_ids),
        processing_state=pack.batch.state,
        duplicate_document_ids=list(pack.duplicate_document_ids),
    )


@router.post(
    "/source",
    response_model=PursuitResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": PursuitResponse, "description": "The organization's existing pursuit for this tender."}},
)
async def create_source_pursuit(
    payload: SourcePursuitCreateRequest,
    response: Response,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> PursuitResponse:
    """Create-or-resolve the organization's SOURCE pursuit for a tender (D1-06 one door).

    Idempotent per (organization, tender): 201 when this call created the pursuit (one
    CREATE lifecycle event), 200 when it already existed (no event, stage untouched).
    """
    context = await _context(db, current_user, x_organization_id)
    try:
        result = await get_or_create_source_pursuit(
            db, organization_id=context.organization.id, actor_user_id=current_user.id,
            actor_membership_id=context.membership.id, tender_id=payload.tender_id,
            stage=payload.stage, legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
        )
    except PursuitNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Tender not found") from exc
    except PursuitTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return _response(result.pursuit)


@router.get("/{pursuit_id}", response_model=PursuitResponse)
async def get_pursuit(
    pursuit_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> PursuitResponse:
    context = await _context(db, current_user, x_organization_id)
    row = await _pursuit_detail_row(db, context.organization.id, pursuit_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Pursuit not found")
    pursuit, tender, private_context, owner_name = row
    counts, batches = await _enrichment_maps(db, [pursuit.id])
    return _response(
        pursuit,
        tender,
        private_context,
        batches.get(pursuit.id),
        int(counts.get(pursuit.id, 0)),
        owner_name,
    )


@router.get("/{pursuit_id}/documents", response_model=PrivateDocumentListResponse)
async def get_private_documents(
    pursuit_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PrivateDocumentListResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        rows = await list_private_documents(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id
        )
    except PrivateDocumentError as exc:
        raise _http_private_error(exc) from exc
    items = []
    for document, version, job, result in rows:
        processing = job.state if job else DocumentProcessingState.CHECKING
        if processing == DocumentProcessingState.QUEUED:
            processing = DocumentProcessingState.CHECKING
        items.append(
            PrivateDocumentItem(
                document_id=document.id,
                current_version_id=version.id,
                role=document.role,
                display_name=document.display_name,
                version_number=version.version_number,
                media_type=version.media_type,
                byte_size=version.byte_size,
                sha256=version.sha256,
                processing_state=processing,
                page_count=result.page_count if result else None,
                page_count_known=bool(result and result.page_count_status == "KNOWN"),
                retry_allowed=bool(job and job.state in {DocumentProcessingState.FAILED, DocumentProcessingState.PARTIAL}),
                error_code=job.last_error_code if job else None,
                created_at=version.created_at,
                updated_at=document.updated_at,
            )
        )
    return PrivateDocumentListResponse(items=items)


@router.get(
    "/{pursuit_id}/analysis-pack-candidate",
    response_model=AnalysisPackCandidateResponse,
)
async def get_analysis_pack_candidate(
    pursuit_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalysisPackCandidateResponse:
    organization_context = await _context(db, current_user, x_organization_id)
    try:
        return await build_analysis_pack_candidate(
            db,
            organization_id=organization_context.organization.id,
            pursuit_id=pursuit_id,
        )
    except PrivateDocumentError as exc:
        raise _http_private_error(exc) from exc


def _analysis_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AnalysisNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/{pursuit_id}/analysis-runs",
    response_model=PursuitAnalysisStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_pursuit_analysis(
    pursuit_id: UUID,
    payload: PursuitAnalysisStartRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PursuitAnalysisStartResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        response = await create_analysis_run(
            db,
            organization_id=context.organization.id,
            pursuit_id=pursuit_id,
            membership_id=context.membership.id,
            request=payload,
        )
    except (AnalysisAdmissionError, AnalysisNotFoundError) as exc:
        raise _analysis_error(exc) from exc
    dispatch_run_ids([response.analysis_run_id])
    return response


@router.get("/{pursuit_id}/analysis-runs/latest", response_model=PursuitAnalysisResponse | None)
async def latest_pursuit_analysis(
    pursuit_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PursuitAnalysisResponse | None:
    context = await _context(db, current_user, x_organization_id)
    return await get_analysis_run(
        db, organization_id=context.organization.id, pursuit_id=pursuit_id
    )


@router.get("/{pursuit_id}/analysis-runs/{run_id}", response_model=PursuitAnalysisResponse)
async def pursuit_analysis_run(
    pursuit_id: UUID,
    run_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PursuitAnalysisResponse:
    context = await _context(db, current_user, x_organization_id)
    response = await get_analysis_run(
        db, organization_id=context.organization.id, pursuit_id=pursuit_id, run_id=run_id
    )
    if response is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Analysis run not found")
    return response


@router.post(
    "/{pursuit_id}/analysis-runs/{run_id}/reviews",
    response_model=AnalysisReviewAssertionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def review_pursuit_analysis(
    pursuit_id: UUID,
    run_id: UUID,
    payload: AnalysisReviewAssertionRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalysisReviewAssertionResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await append_review_assertion(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            run_id=run_id, membership_id=context.membership.id, request=payload,
        )
    except (AnalysisAdmissionError, AnalysisNotFoundError) as exc:
        raise _analysis_error(exc) from exc


@router.post(
    "/{pursuit_id}/analysis-lineage",
    response_model=AnalysisLineageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def link_pursuit_analysis_lineage(
    pursuit_id: UUID,
    payload: AnalysisLineageRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalysisLineageResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        return await append_lineage(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id,
            membership_id=context.membership.id, request=payload,
        )
    except (AnalysisAdmissionError, AnalysisNotFoundError) as exc:
        raise _analysis_error(exc) from exc


@router.post("/{pursuit_id}/documents/{document_id}/versions", response_model=PrivateUploadResponse, status_code=status.HTTP_201_CREATED)
async def replace_private_document(
    pursuit_id: UUID,
    document_id: UUID,
    file: UploadFile = File(...),
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PrivateUploadResponse:
    context = await _context(db, current_user, x_organization_id)
    staging_root = private_storage_root() / ".staging"
    staging_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with TemporaryDirectory(prefix="revision-", dir=staging_root) as temporary:
            staged = (await _stage_files([file], "[]", temporary))[0]
            pack = await add_document_version(
                db,
                organization_id=context.organization.id,
                pursuit_id=pursuit_id,
                document_id=document_id,
                membership_id=context.membership.id,
                staged=staged,
            )
    except (PrivateUploadError, PrivateDocumentError) as exc:
        raise _http_private_error(exc) from exc
    dispatch_job_ids(pack.job_ids)
    return PrivateUploadResponse(
        pursuit=_response(pack.pursuit, batch=pack.batch, file_count=1),
        batch_id=pack.batch.id,
        document_ids=list(pack.document_ids),
        processing_state=pack.batch.state,
        duplicate_document_ids=[],
    )


@router.get("/{pursuit_id}/documents/{document_id}/versions/{version_id}/download")
async def download_private_document(
    pursuit_id: UUID,
    document_id: UUID,
    version_id: UUID,
    preview: bool = Query(default=False),
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    context = await _context(db, current_user, x_organization_id)
    try:
        _, version, _ = await get_authorized_version(
            db,
            organization_id=context.organization.id,
            pursuit_id=pursuit_id,
            document_id=document_id,
            version_id=version_id,
        )
        path = resolve_private_storage_key(version.storage_key)
        if not path.is_file():
            raise PrivateDocumentNotFoundError("Private document version is not available")
    except PrivateDocumentError as exc:
        raise _http_private_error(exc) from exc
    return FileResponse(
        path,
        media_type=version.media_type,
        filename=version.safe_display_filename,
        content_disposition_type="inline" if preview and version.media_type == "application/pdf" else "attachment",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/{pursuit_id}/documents/{document_id}/retry", response_model=PrivateDocumentItem)
async def retry_private_document(
    pursuit_id: UUID,
    document_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PrivateDocumentItem:
    context = await _context(db, current_user, x_organization_id)
    try:
        job = await retry_processing_job(
            db,
            organization_id=context.organization.id,
            pursuit_id=pursuit_id,
            document_id=document_id,
            membership_id=context.membership.id,
        )
        dispatch_job_ids([job.id])
        rows = await list_private_documents(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id
        )
        document, version, _, result = next(row for row in rows if row[0].id == document_id)
    except (PrivateDocumentError, StopIteration) as exc:
        raise _http_private_error(exc if isinstance(exc, PrivateDocumentError) else PrivateDocumentNotFoundError("Private document not found")) from exc
    return PrivateDocumentItem(
        document_id=document.id,
        current_version_id=version.id,
        role=document.role,
        display_name=document.display_name,
        version_number=version.version_number,
        media_type=version.media_type,
        byte_size=version.byte_size,
        sha256=version.sha256,
        processing_state=DocumentProcessingState.CHECKING,
        page_count=result.page_count if result else None,
        page_count_known=bool(result and result.page_count_status == "KNOWN"),
        retry_allowed=False,
        error_code=None,
        created_at=version.created_at,
        updated_at=document.updated_at,
    )


@router.patch("/{pursuit_id}/documents/{document_id}/role", response_model=PrivateDocumentItem)
async def correct_private_document_role(
    pursuit_id: UUID,
    document_id: UUID,
    payload: PrivateDocumentRoleRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PrivateDocumentItem:
    context = await _context(db, current_user, x_organization_id)
    try:
        await update_document_role(
            db,
            organization_id=context.organization.id,
            pursuit_id=pursuit_id,
            document_id=document_id,
            membership_id=context.membership.id,
            role=payload.role,
        )
        rows = await list_private_documents(
            db, organization_id=context.organization.id, pursuit_id=pursuit_id
        )
        document, version, job, result = next(row for row in rows if row[0].id == document_id)
    except (PrivateDocumentError, StopIteration) as exc:
        mapped = exc if isinstance(exc, PrivateDocumentError) else PrivateDocumentNotFoundError("Private document not found")
        raise _http_private_error(mapped) from exc
    processing = job.state if job else DocumentProcessingState.CHECKING
    if processing == DocumentProcessingState.QUEUED:
        processing = DocumentProcessingState.CHECKING
    return PrivateDocumentItem(
        document_id=document.id,
        current_version_id=version.id,
        role=document.role,
        display_name=document.display_name,
        version_number=version.version_number,
        media_type=version.media_type,
        byte_size=version.byte_size,
        sha256=version.sha256,
        processing_state=processing,
        page_count=result.page_count if result else None,
        page_count_known=bool(result and result.page_count_status == "KNOWN"),
        retry_allowed=bool(job and job.state in {DocumentProcessingState.FAILED, DocumentProcessingState.PARTIAL}),
        error_code=job.last_error_code if job else None,
        created_at=version.created_at,
        updated_at=document.updated_at,
    )


def _context_response(pursuit_id: UUID, context, suggestions) -> PursuitContextResponse:
    fields = (
        "title", "buyer", "declared_funder", "country", "reference",
        "procurement_stage", "external_deadline", "deadline_timezone", "source_url",
    )
    confirmed = set((context.confirmed_fields or {}).keys()) if context else set()
    latest_source = {item.field_name: item for item in suggestions}

    def display(value) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def equivalent(field_name: str, source_value: str, user_value) -> bool:
        if field_name == "external_deadline" and isinstance(user_value, datetime):
            try:
                parsed = datetime.fromisoformat(source_value.replace("Z", "+00:00"))
                return parsed.astimezone(timezone.utc) == user_value.astimezone(timezone.utc)
            except ValueError:
                return False
        normalize = lambda value: " ".join(str(value).split()).casefold()
        return normalize(source_value) == normalize(user_value)

    provenance: list[PursuitContextFieldProvenanceResponse] = []
    for field_name in fields:
        source = latest_source.get(field_name)
        user_value = getattr(context, field_name, None) if context else None
        if source and field_name in confirmed:
            state = (
                "USER_CONFIRMED"
                if equivalent(field_name, source.suggested_value, user_value)
                else "USER_OVERRIDE_CONFLICTS_WITH_SOURCE"
            )
        elif source:
            state = "SOURCE_DETECTED"
        elif field_name in confirmed:
            state = "USER_CONFIRMED"
        else:
            state = "UNKNOWN"
        provenance.append(PursuitContextFieldProvenanceResponse(
            field_name=field_name,
            provenance_state=state,
            source_value=source.suggested_value if source else None,
            user_confirmed_value=display(user_value) if field_name in confirmed else None,
        ))

    return PursuitContextResponse(
        pursuit_id=pursuit_id,
        title=context.title if context else None,
        buyer=context.buyer if context else None,
        declared_funder=context.declared_funder if context else None,
        country=context.country if context else None,
        reference=context.reference if context else None,
        procurement_stage=context.procurement_stage if context else None,
        external_deadline=context.external_deadline if context else None,
        deadline_timezone=context.deadline_timezone if context else None,
        source_url=context.source_url if context else None,
        confirmed_fields=sorted((context.confirmed_fields or {}).keys()) if context else [],
        suggestions=[
            PursuitContextSuggestionResponse(
                suggestion_id=item.id,
                field_name=item.field_name,
                suggested_value=item.suggested_value,
                document_version_id=item.document_version_id,
                page_number=item.page_number,
                evidence_span=item.evidence_span,
                confidence=item.confidence,
                review_state=item.review_state,
                provenance_state=next(
                    value.provenance_state for value in provenance if value.field_name == item.field_name
                ),
                user_confirmed_value=next(
                    value.user_confirmed_value for value in provenance if value.field_name == item.field_name
                ),
            )
            for item in suggestions
        ],
        field_provenance=provenance,
    )


@router.get("/{pursuit_id}/context", response_model=PursuitContextResponse)
async def get_pursuit_context(
    pursuit_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PursuitContextResponse:
    organization_context = await _context(db, current_user, x_organization_id)
    try:
        context, suggestions = await get_context(
            db, organization_id=organization_context.organization.id, pursuit_id=pursuit_id
        )
    except PrivateDocumentError as exc:
        raise _http_private_error(exc) from exc
    return _context_response(pursuit_id, context, suggestions)


@router.patch("/{pursuit_id}/context", response_model=PursuitContextResponse)
async def confirm_pursuit_context(
    pursuit_id: UUID,
    payload: PursuitContextUpdateRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PursuitContextResponse:
    organization_context = await _context(db, current_user, x_organization_id)
    try:
        context = await update_context(
            db,
            organization_id=organization_context.organization.id,
            pursuit_id=pursuit_id,
            membership_id=organization_context.membership.id,
            values=payload.model_dump(exclude_unset=True, exclude={"confirmed_fields"}),
            confirmed_fields=payload.confirmed_fields,
        )
        _, suggestions = await get_context(
            db, organization_id=organization_context.organization.id, pursuit_id=pursuit_id
        )
    except PrivateDocumentError as exc:
        raise _http_private_error(exc) from exc
    return _context_response(pursuit_id, context, suggestions)


@router.post("/{pursuit_id}/transition", response_model=PursuitResponse)
async def apply_transition(
    pursuit_id: UUID, payload: PursuitTransitionRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> PursuitResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        pursuit = await transition_pursuit(
            db, pursuit_id=pursuit_id, organization_id=context.organization.id,
            actor_user_id=current_user.id, actor_membership_id=context.membership.id,
            stage=payload.destination, expected_stage=payload.expected_stage, reason=payload.reason,
        )
    except PursuitNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Pursuit not found") from exc
    except PursuitTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _response(pursuit)


@router.post("/{pursuit_id}/reopen", response_model=PursuitResponse)
async def reopen_closed_pursuit(
    pursuit_id: UUID, payload: PursuitReopenRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> PursuitResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        pursuit = await reopen_pursuit(
            db, pursuit_id=pursuit_id, organization_id=context.organization.id,
            actor_user_id=current_user.id, actor_membership_id=context.membership.id,
            destination=payload.destination, expected_stage=payload.expected_stage,
            reason=payload.reason,
        )
    except PursuitNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Pursuit not found") from exc
    except PursuitTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _response(pursuit)


@router.patch("/{pursuit_id}/owner", response_model=PursuitResponse)
async def update_owner(
    pursuit_id: UUID, payload: PursuitOwnerRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> PursuitResponse:
    context = await _context(db, current_user, x_organization_id)
    try:
        pursuit = await assign_pursuit_owner(
            db, pursuit_id=pursuit_id, organization_id=context.organization.id,
            actor_membership_id=context.membership.id,
            owner_membership_id=payload.owner_membership_id,
        )
    except PursuitNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Pursuit not found") from exc
    except (PursuitOwnershipError, PursuitError) as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return _response(pursuit)
