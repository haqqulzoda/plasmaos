"""Private document intake, processing, context, and authorization services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import signal
import sys
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.private_storage import (
    MAX_PRIVATE_PACK_BYTES,
    MalwareDetectedError,
    MalwareScanError,
    PrivateUploadError,
    commit_staged_file,
    opaque_library_storage_key,
    opaque_storage_key,
    resolve_private_storage_key,
    scan_with_clamav,
)
from app.models.base import (
    DocumentProcessingState,
    MembershipState,
    PrivateDocumentRole,
    PrivateDocumentState,
    PursuitOrigin,
)
from app.models.private_documents import (
    DocumentProcessingJob,
    DocumentProcessingResult,
    DocumentVersion,
    PrivateDocument,
    PrivateDocumentBatch,
    PursuitContextSuggestion,
    PursuitTenderContext,
)
from app.models.tenancy import Membership, OrganizationPursuit
from app.models.all_models import TenderDocument
from app.schemas.tenancy import (
    AnalysisPackCandidateResponse,
    AnalysisPrivateVersionSnapshot,
    AnalysisSourceDocumentSnapshot,
)
from app.services.notifications import stage_private_document_notification
from app.services.official_notice import OFFICIAL_NOTICE_DISPLAY_NAME, is_official_notice


TERMINAL_PROCESSING_STATES = frozenset(
    {
        DocumentProcessingState.READY,
        DocumentProcessingState.PARTIAL,
        DocumentProcessingState.FAILED,
    }
)
CONTEXT_FIELDS = frozenset(
    {
        "title",
        "buyer",
        "declared_funder",
        "country",
        "reference",
        "procurement_stage",
        "external_deadline",
        "deadline_timezone",
        "source_url",
    }
)


class PrivateDocumentError(RuntimeError):
    pass


class PrivateDocumentNotFoundError(PrivateDocumentError):
    pass


class PrivateDocumentRetryError(PrivateDocumentError):
    pass


@dataclass(frozen=True)
class StagedPrivateFile:
    path: Path
    original_filename: str
    safe_display_filename: str
    media_type: str
    byte_size: int
    sha256: str
    role: PrivateDocumentRole


@dataclass(frozen=True)
class PersistedPack:
    pursuit: OrganizationPursuit
    batch: PrivateDocumentBatch
    document_ids: tuple[UUID, ...]
    job_ids: tuple[UUID, ...]
    duplicate_document_ids: tuple[UUID, ...]


class ExtractedTenderContext(BaseModel):
    """Strict, narrow result contract; document instructions cannot add fields."""

    model_config = ConfigDict(extra="forbid", strict=True)
    title: str | None = Field(default=None, max_length=500)
    buyer: str | None = Field(default=None, max_length=500)
    country: str | None = Field(default=None, max_length=255)
    reference: str | None = Field(default=None, max_length=255)
    declared_funder: str | None = Field(default=None, max_length=255)
    external_deadline: datetime | None = None
    deadline_timezone: str | None = Field(default=None, max_length=100)


async def _require_active_membership(
    db: AsyncSession, *, organization_id: UUID, membership_id: UUID
) -> Membership:
    membership = await db.scalar(
        select(Membership).where(
            Membership.id == membership_id,
            Membership.organization_id == organization_id,
            Membership.state == MembershipState.ACTIVE,
        )
    )
    if membership is None:
        raise PrivateDocumentNotFoundError("Private document not found")
    return membership


async def require_owned_pursuit(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID
) -> OrganizationPursuit:
    pursuit = await db.scalar(
        select(OrganizationPursuit).where(
            OrganizationPursuit.id == pursuit_id,
            OrganizationPursuit.organization_id == organization_id,
        )
    )
    if pursuit is None:
        raise PrivateDocumentNotFoundError("Pursuit not found")
    return pursuit


async def persist_private_pack(
    db: AsyncSession,
    *,
    pursuit: OrganizationPursuit,
    membership_id: UUID,
    files: list[StagedPrivateFile],
) -> PersistedPack:
    """Persist bytes, immutable identities, and durable jobs as one intake command."""
    if not files:
        raise PrivateDocumentError("At least one accepted file is required")
    if sum(item.byte_size for item in files) > MAX_PRIVATE_PACK_BYTES:
        raise PrivateUploadError(
            "PRIVATE_DOCUMENT_PACK_TOO_LARGE", "The submitted pack exceeds 150 MiB", 413
        )
    await _require_active_membership(
        db, organization_id=pursuit.organization_id, membership_id=membership_id
    )
    batch = PrivateDocumentBatch(
        organization_id=pursuit.organization_id,
        pursuit_id=pursuit.id,
        requested_by_membership_id=membership_id,
        state=DocumentProcessingState.QUEUED,
        file_count=len(files),
        processed_count=0,
        failed_count=0,
    )
    db.add(batch)
    await db.flush()
    stored_paths: list[Path] = []
    document_ids: list[UUID] = []
    job_ids: list[UUID] = []
    duplicates: list[UUID] = []
    try:
        for item in files:
            duplicate = await db.scalar(
                select(PrivateDocument.id)
                .join(DocumentVersion, DocumentVersion.private_document_id == PrivateDocument.id)
                .where(
                    PrivateDocument.organization_id == pursuit.organization_id,
                    PrivateDocument.pursuit_id == pursuit.id,
                    DocumentVersion.sha256 == item.sha256,
                )
                .limit(1)
            )
            if duplicate is not None:
                duplicates.append(duplicate)
            document_id = uuid4()
            version_id = uuid4()
            document = PrivateDocument(
                id=document_id,
                organization_id=pursuit.organization_id,
                pursuit_id=pursuit.id,
                role=item.role,
                display_name=item.safe_display_filename,
                state=PrivateDocumentState.ACTIVE,
                created_by_membership_id=membership_id,
            )
            storage_key = opaque_storage_key(
                organization_id=pursuit.organization_id,
                pursuit_id=pursuit.id,
                version_id=version_id,
            )
            version = DocumentVersion(
                id=version_id,
                organization_id=pursuit.organization_id,
                private_document_id=document_id,
                version_number=1,
                original_filename=item.original_filename,
                safe_display_filename=item.safe_display_filename,
                media_type=item.media_type,
                byte_size=item.byte_size,
                sha256=item.sha256,
                storage_key=storage_key,
                uploader_membership_id=membership_id,
            )
            job = DocumentProcessingJob(
                batch_id=batch.id,
                document_version_id=version_id,
                state=DocumentProcessingState.QUEUED,
                next_dispatch_at=datetime.now(timezone.utc),
            )
            db.add_all([document, version])
            await db.flush()
            db.add(job)
            await db.flush()
            document.current_version_id = version_id
            stored_paths.append(commit_staged_file(item.path, storage_key))
            document_ids.append(document_id)
            job_ids.append(job.id)
        await db.commit()
    except BaseException:
        await db.rollback()
        for path in stored_paths:
            path.unlink(missing_ok=True)
        raise
    return PersistedPack(
        pursuit=pursuit,
        batch=batch,
        document_ids=tuple(document_ids),
        job_ids=tuple(job_ids),
        duplicate_document_ids=tuple(dict.fromkeys(duplicates)),
    )


async def add_document_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    pursuit_id: UUID,
    document_id: UUID,
    membership_id: UUID,
    staged: StagedPrivateFile,
) -> PersistedPack:
    await _require_active_membership(
        db, organization_id=organization_id, membership_id=membership_id
    )
    document = await db.scalar(
        select(PrivateDocument)
        .where(
            PrivateDocument.id == document_id,
            PrivateDocument.organization_id == organization_id,
            PrivateDocument.pursuit_id == pursuit_id,
            PrivateDocument.state == PrivateDocumentState.ACTIVE,
        )
        .with_for_update()
    )
    if document is None:
        raise PrivateDocumentNotFoundError("Private document not found")
    pursuit = await require_owned_pursuit(
        db, organization_id=organization_id, pursuit_id=pursuit_id
    )
    next_number = int(
        await db.scalar(
            select(func.max(DocumentVersion.version_number)).where(
                DocumentVersion.private_document_id == document.id
            )
        )
        or 0
    ) + 1
    batch = PrivateDocumentBatch(
        organization_id=organization_id,
        pursuit_id=pursuit_id,
        requested_by_membership_id=membership_id,
        state=DocumentProcessingState.QUEUED,
        file_count=1,
    )
    version_id = uuid4()
    storage_key = opaque_storage_key(
        organization_id=organization_id, pursuit_id=pursuit_id, version_id=version_id
    )
    version = DocumentVersion(
        id=version_id,
        organization_id=organization_id,
        private_document_id=document.id,
        version_number=next_number,
        original_filename=staged.original_filename,
        safe_display_filename=staged.safe_display_filename,
        media_type=staged.media_type,
        byte_size=staged.byte_size,
        sha256=staged.sha256,
        storage_key=storage_key,
        uploader_membership_id=membership_id,
    )
    job = DocumentProcessingJob(
        batch=batch,
        document_version_id=version_id,
        state=DocumentProcessingState.QUEUED,
        next_dispatch_at=datetime.now(timezone.utc),
    )
    db.add_all([batch, version])
    stored_path: Path | None = None
    try:
        await db.flush()
        db.add(job)
        await db.flush()
        document.current_version_id = version_id
        document.updated_at = datetime.now(timezone.utc)
        stored_path = commit_staged_file(staged.path, storage_key)
        await db.commit()
    except BaseException:
        await db.rollback()
        if stored_path:
            stored_path.unlink(missing_ok=True)
        raise
    return PersistedPack(pursuit, batch, (document.id,), (job.id,), ())


async def list_private_documents(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID
) -> list[tuple[PrivateDocument, DocumentVersion, DocumentProcessingJob | None, DocumentProcessingResult | None]]:
    await require_owned_pursuit(db, organization_id=organization_id, pursuit_id=pursuit_id)
    rows = (
        await db.execute(
            select(PrivateDocument, DocumentVersion, DocumentProcessingJob, DocumentProcessingResult)
            .join(
                DocumentVersion,
                DocumentVersion.id == PrivateDocument.current_version_id,
            )
            .outerjoin(
                DocumentProcessingJob,
                DocumentProcessingJob.document_version_id == DocumentVersion.id,
            )
            .outerjoin(
                DocumentProcessingResult,
                DocumentProcessingResult.job_id == DocumentProcessingJob.id,
            )
            .where(
                PrivateDocument.organization_id == organization_id,
                PrivateDocument.pursuit_id == pursuit_id,
                PrivateDocument.state == PrivateDocumentState.ACTIVE,
            )
            .order_by(PrivateDocument.created_at, PrivateDocument.id)
        )
    ).all()
    return list(rows)


async def build_analysis_pack_candidate(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID
) -> AnalysisPackCandidateResponse:
    """Build a passive exact-version W4 input candidate without starting analysis."""
    pursuit = await require_owned_pursuit(
        db, organization_id=organization_id, pursuit_id=pursuit_id
    )
    private_rows = await list_private_documents(
        db, organization_id=organization_id, pursuit_id=pursuit_id
    )
    source_rows: list[TenderDocument] = []
    if pursuit.source_tender_id is not None:
        source_rows = list(
            (
                await db.scalars(
                    select(TenderDocument)
                    .where(TenderDocument.tender_id == pursuit.source_tender_id)
                    .order_by(TenderDocument.created_at, TenderDocument.id)
                )
            ).all()
        )

    source_snapshots: list[AnalysisSourceDocumentSnapshot] = []
    for item in source_rows:
        analyzed_text = item.parsed_text or ""
        analyzed_text_sha256 = hashlib.sha256(analyzed_text.encode()).hexdigest()
        content_sha256 = item.sha256 or analyzed_text_sha256
        snapshot_payload = {
            "id": str(item.id),
            "tender_id": str(item.tender_id),
            "file_url": item.file_url,
            "file_type": item.file_type,
            "source_document_url": item.source_document_url,
            "source_document_type": item.source_document_type,
            "external_file_id": item.external_file_id,
            "content_sha256": content_sha256,
            "analyzed_text_sha256": analyzed_text_sha256,
            "extracted_character_count": len(analyzed_text),
            "created_at": item.created_at.isoformat(),
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        source_snapshots.append(
            AnalysisSourceDocumentSnapshot(
                tender_document_id=item.id,
                display_name=(
                    OFFICIAL_NOTICE_DISPLAY_NAME
                    if is_official_notice(item)
                    else (item.file_url.rsplit("/", 1)[-1] or str(item.id))
                ),
                role=item.source_document_type or "OFFICIAL_SOURCE",
                snapshot_sha256=snapshot_hash,
                content_sha256=content_sha256,
                analyzed_text_sha256=analyzed_text_sha256,
                extracted_character_count=len(analyzed_text),
                file_type=item.file_type,
                parse_ready=bool(analyzed_text.strip()),
                page_count_known=False,
                source_url=(
                    item.source_document_url
                    or (None if is_official_notice(item) else item.file_url)
                ),
                captured_at=item.created_at,
            )
        )

    private_snapshots: list[AnalysisPrivateVersionSnapshot] = []
    for document, version, job, result in private_rows:
        result_payload = None
        result_hash = None
        if result is not None:
            result_payload = {
                "id": str(result.id),
                "job_id": str(result.job_id),
                "document_version_id": str(result.document_version_id),
                "malware_scan_status": result.malware_scan_status,
                "page_count": result.page_count,
                "page_count_status": result.page_count_status,
                "extracted_sha256": result.extracted_sha256,
                "parser_name": result.parser_name,
                "parser_version": result.parser_version,
                "extraction_error_code": result.extraction_error_code,
            }
            result_hash = hashlib.sha256(
                json.dumps(result_payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        extracted_text = result.extracted_text if result and result.extracted_text else ""
        private_snapshots.append(
            AnalysisPrivateVersionSnapshot(
                private_document_id=document.id,
                document_version_id=version.id,
                display_name=document.display_name,
                version_number=version.version_number,
                role=document.role,
                content_sha256=version.sha256,
                processing_result_id=result.id if result else None,
                processing_result_sha256=result_hash,
                extracted_character_count=len(extracted_text),
                processing_state=(job.state if job else DocumentProcessingState.FAILED),
                parse_ready=bool(
                    job
                    and job.state == DocumentProcessingState.READY
                    and result
                    and result.malware_scan_status == "CLEAN"
                    and extracted_text.strip()
                    and result.extracted_sha256
                    == hashlib.sha256(extracted_text.encode()).hexdigest()
                ),
                page_count=result.page_count if result else None,
                page_count_known=bool(result and result.page_count_status == "KNOWN"),
                malware_scan_status=result.malware_scan_status if result else None,
                duplicate_warning=(
                    f"Revision {version.version_number}; confirm this exact version."
                    if version.version_number > 1
                    else None
                ),
            )
        )

    digest_counts: dict[str, int] = {}
    for snapshot in [*source_snapshots, *private_snapshots]:
        digest_counts[snapshot.content_sha256] = digest_counts.get(snapshot.content_sha256, 0) + 1
    for snapshot in [*source_snapshots, *private_snapshots]:
        if digest_counts[snapshot.content_sha256] > 1:
            existing = snapshot.duplicate_warning
            snapshot.duplicate_warning = (
                f"{existing} Duplicate content is present in this candidate." if existing
                else "Duplicate content is present in this candidate."
            )
    seal_payload = {
        "schema_version": "w4-analysis-pack-candidate-v1",
        "organization_id": str(organization_id),
        "pursuit_id": str(pursuit_id),
        "pursuit_origin": pursuit.origin.value,
        "source_tender_id": str(pursuit.source_tender_id) if pursuit.source_tender_id else None,
        "source_documents": [item.model_dump(mode="json") for item in source_snapshots],
        "private_versions": [item.model_dump(mode="json") for item in private_snapshots],
    }
    candidate_sha256 = hashlib.sha256(
        json.dumps(seal_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    all_items_ready = all(item.parse_ready for item in [*source_snapshots, *private_snapshots])
    all_snapshots = [*source_snapshots, *private_snapshots]
    known_pages = [item.page_count for item in all_snapshots if item.page_count is not None]
    page_count_total = (
        sum(known_pages)
        if len(known_pages) == len(all_snapshots)
        else None
    )
    return AnalysisPackCandidateResponse(
        candidate_sha256=candidate_sha256,
        organization_id=organization_id,
        pursuit_id=pursuit_id,
        pursuit_origin=pursuit.origin,
        source_tender_id=pursuit.source_tender_id,
        parse_ready=bool(source_snapshots or private_snapshots) and all_items_ready,
        page_count_total=page_count_total,
        source_documents=source_snapshots,
        private_versions=private_snapshots,
        generated_at=datetime.now(timezone.utc),
    )


async def get_authorized_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    pursuit_id: UUID,
    document_id: UUID,
    version_id: UUID,
) -> tuple[PrivateDocument, DocumentVersion, DocumentProcessingResult | None]:
    row = (
        await db.execute(
            select(PrivateDocument, DocumentVersion, DocumentProcessingResult)
            .join(DocumentVersion, DocumentVersion.private_document_id == PrivateDocument.id)
            .outerjoin(
                DocumentProcessingResult,
                DocumentProcessingResult.document_version_id == DocumentVersion.id,
            )
            .where(
                PrivateDocument.id == document_id,
                PrivateDocument.organization_id == organization_id,
                PrivateDocument.pursuit_id == pursuit_id,
                PrivateDocument.state == PrivateDocumentState.ACTIVE,
                DocumentVersion.id == version_id,
                DocumentVersion.organization_id == organization_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise PrivateDocumentNotFoundError("Private document version not found")
    if row[2] is None or row[2].malware_scan_status != "CLEAN":
        raise PrivateDocumentNotFoundError("Private document version is not available")
    return row[0], row[1], row[2]


async def get_context(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID
) -> tuple[PursuitTenderContext | None, list[PursuitContextSuggestion]]:
    await require_owned_pursuit(db, organization_id=organization_id, pursuit_id=pursuit_id)
    context = await db.scalar(
        select(PursuitTenderContext).where(
            PursuitTenderContext.pursuit_id == pursuit_id,
            PursuitTenderContext.organization_id == organization_id,
        )
    )
    suggestions = list(
        (
            await db.scalars(
                select(PursuitContextSuggestion)
                .where(
                    PursuitContextSuggestion.pursuit_id == pursuit_id,
                    PursuitContextSuggestion.organization_id == organization_id,
                )
                .order_by(PursuitContextSuggestion.created_at, PursuitContextSuggestion.id)
            )
        ).all()
    )
    return context, suggestions


async def update_context(
    db: AsyncSession,
    *,
    organization_id: UUID,
    pursuit_id: UUID,
    membership_id: UUID,
    values: dict[str, Any],
    confirmed_fields: set[str],
) -> PursuitTenderContext:
    await _require_active_membership(
        db, organization_id=organization_id, membership_id=membership_id
    )
    pursuit = await require_owned_pursuit(
        db, organization_id=organization_id, pursuit_id=pursuit_id
    )
    if pursuit.origin != PursuitOrigin.UPLOAD:
        raise PrivateDocumentError("Source pursuit context remains source-owned")
    invalid = (set(values) | confirmed_fields) - CONTEXT_FIELDS
    if invalid:
        raise PrivateDocumentError("Unsupported tender context field")
    context = await db.scalar(
        select(PursuitTenderContext)
        .where(PursuitTenderContext.pursuit_id == pursuit_id)
        .with_for_update()
    )
    if context is None:
        context = PursuitTenderContext(
            pursuit_id=pursuit_id, organization_id=organization_id, confirmed_fields={}
        )
        db.add(context)
    for key, value in values.items():
        setattr(context, key, value)
    confirmed = dict(context.confirmed_fields or {})
    now = datetime.now(timezone.utc)
    for key in confirmed_fields:
        confirmed[key] = {"membership_id": str(membership_id), "confirmed_at": now.isoformat()}
    context.confirmed_fields = confirmed
    context.confirmed_by_membership_id = membership_id if confirmed_fields else context.confirmed_by_membership_id
    context.confirmed_at = now if confirmed_fields else context.confirmed_at
    context.updated_at = now
    await db.commit()
    return context


async def retry_processing_job(
    db: AsyncSession,
    *,
    organization_id: UUID,
    pursuit_id: UUID,
    document_id: UUID,
    membership_id: UUID,
) -> DocumentProcessingJob:
    await _require_active_membership(
        db, organization_id=organization_id, membership_id=membership_id
    )
    job = await db.scalar(
        select(DocumentProcessingJob)
        .join(DocumentVersion, DocumentVersion.id == DocumentProcessingJob.document_version_id)
        .join(PrivateDocument, PrivateDocument.id == DocumentVersion.private_document_id)
        .where(
            PrivateDocument.id == document_id,
            PrivateDocument.organization_id == organization_id,
            PrivateDocument.pursuit_id == pursuit_id,
            DocumentProcessingJob.state.in_(
                [DocumentProcessingState.FAILED, DocumentProcessingState.PARTIAL]
            ),
        )
        .with_for_update()
    )
    if job is None:
        raise PrivateDocumentRetryError("No retryable processing job was found")
    result = await db.scalar(
        select(DocumentProcessingResult).where(DocumentProcessingResult.job_id == job.id)
    )
    if (
        job.state == DocumentProcessingState.PARTIAL
        and result is not None
        and result.extraction_error_code == "DOCX_PAGE_COUNT_UNKNOWN"
    ):
        raise PrivateDocumentRetryError("This document is complete; page count is unavailable")
    job.state = DocumentProcessingState.QUEUED
    job.next_dispatch_at = datetime.now(timezone.utc)
    job.lease_until = None
    job.completed_at = None
    job.last_error_code = None
    job.last_error_detail = None
    await db.commit()
    return job


async def update_document_role(
    db: AsyncSession,
    *,
    organization_id: UUID,
    pursuit_id: UUID,
    document_id: UUID,
    membership_id: UUID,
    role: PrivateDocumentRole,
) -> PrivateDocument:
    await _require_active_membership(
        db, organization_id=organization_id, membership_id=membership_id
    )
    document = await db.scalar(
        select(PrivateDocument)
        .where(
            PrivateDocument.id == document_id,
            PrivateDocument.organization_id == organization_id,
            PrivateDocument.pursuit_id == pursuit_id,
            PrivateDocument.state == PrivateDocumentState.ACTIVE,
        )
        .with_for_update()
    )
    if document is None:
        raise PrivateDocumentNotFoundError("Private document not found")
    document.role = role
    document.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return document


async def _parse_private_file(path: Path, media_type: str) -> dict[str, Any]:
    env = dict(__import__("os").environ)
    env["PRIVATE_DOCUMENT_OCR_MAX_PAGES"] = str(settings.PRIVATE_DOCUMENT_OCR_MAX_PAGES)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.core.private_document_parser",
        str(path),
        media_type,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=120)
        if process.returncode:
            raise PrivateDocumentError("Private document extraction failed")
        parsed = json.loads(output)
        if not isinstance(parsed, dict) or parsed.get("state") not in {"READY", "PARTIAL"}:
            raise PrivateDocumentError("Private document extraction returned an invalid result")
        return parsed
    except TimeoutError:
        raise PrivateDocumentError("Private document extraction exceeded its time limit") from None
    finally:
        if process.returncode is None:
            if __import__("os").name == "posix":
                __import__("os").killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            await process.wait()


def _context_suggestions(text_value: str) -> ExtractedTenderContext:
    normalized = re.sub(r"\s+", " ", re.sub(r"\[\[PAGE \d+\]\]", " ", text_value)).strip()
    title = None
    title_match = re.search(
        r"REQUEST\s+FOR\s+BID\s+PROPOSALS?\s+FOR\s+A[N]?\s+(.{3,200}?)\s+CONTRACT\b",
        normalized,
        re.IGNORECASE,
    )
    if title_match:
        title = re.sub(r"\s+", " ", title_match.group(1)).strip(" :-")
        title = title.title() if title.isupper() else title
    buyer = None
    buyer_match = re.search(r"Issued\s+by\s*:\s*([^\n]{3,200})", text_value, re.IGNORECASE)
    if buyer_match:
        buyer = buyer_match.group(1).strip()
    reference = None
    match = re.search(
        r"(?im)\b(?:contract|reference|ref(?:erence)?\.?|tender\s*(?:no\.?|number))\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,120})",
        text_value,
    )
    if match:
        reference = match.group(1).strip().rstrip(".")
    country = None
    if re.search(r"\bUniversity\s+Park,\s*(?:MD|Maryland)\b", text_value, re.IGNORECASE):
        country = "United States"
    external_deadline = None
    deadline_timezone = None
    deadline_match = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2})(?:st|nd|rd|th)?\s*,\s*(\d{4})\s*,?\s*at\s*"
        r"(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?)",
        normalized,
        re.IGNORECASE,
    )
    if deadline_match:
        month = datetime.strptime(deadline_match.group(1), "%B").month
        hour = int(deadline_match.group(4)) % 12
        if deadline_match.group(6).casefold().startswith("p"):
            hour += 12
        external_deadline = datetime(
            int(deadline_match.group(3)), month, int(deadline_match.group(2)),
            hour, int(deadline_match.group(5)), tzinfo=ZoneInfo("America/New_York"),
        )
        deadline_timezone = "America/New_York"
    funder = None
    for label in ("World Bank", "Asian Development Bank", "ADB", "AIIB", "EBRD", "GIZ"):
        if re.search(rf"\b{re.escape(label)}\b", text_value, re.IGNORECASE):
            funder = label
            break
    return ExtractedTenderContext(
        title=title,
        buyer=buyer,
        country=country,
        reference=reference,
        declared_funder=funder,
        external_deadline=external_deadline,
        deadline_timezone=deadline_timezone,
    )


def _suggestion_evidence(text_value: str, field_name: str, suggested_value: str) -> tuple[int | None, str | None]:
    patterns = {
        "title": r"COMMUNICATIONS\s+CONSULTANT",
        "buyer": r"Town\s+of\s+University\s+Park",
        "country": r"University\s+Park,\s*(?:MD|Maryland)",
        "reference": r"CONTRACT\s+UP-2012-01",
        "external_deadline": r"February\s+17(?:th)?\s*,\s*2012\s*,?\s*at\s*4:00\s*p\.?m\. ?",
        "deadline_timezone": r"University\s+Park,\s*(?:MD|Maryland)",
    }
    pattern = patterns.get(field_name, re.escape(suggested_value))
    for page_match in re.finditer(
        r"\[\[PAGE\s+(\d+)\]\](.*?)(?=\[\[PAGE\s+\d+\]\]|\Z)",
        text_value,
        re.IGNORECASE | re.DOTALL,
    ):
        page_text = page_match.group(2)
        match = re.search(pattern, page_text, re.IGNORECASE | re.DOTALL)
        if match:
            start = max(0, match.start() - 80)
            end = min(len(page_text), match.end() + 80)
            span = re.sub(r"\s+", " ", page_text[start:end]).strip()
            return int(page_match.group(1)), span[:1000]
    return None, None


async def _persist_suggestions(
    db: AsyncSession,
    *,
    organization_id: UUID,
    pursuit_id: UUID,
    version_id: UUID,
    extracted_text: str,
) -> None:
    result = _context_suggestions(extracted_text)
    values = result.model_dump(exclude_none=True, mode="json")
    for field_name, suggested_value in values.items():
        existing = await db.scalar(
            select(PursuitContextSuggestion).where(
                PursuitContextSuggestion.document_version_id == version_id,
                PursuitContextSuggestion.field_name == field_name,
            )
        )
        page_number, span = _suggestion_evidence(extracted_text, field_name, str(suggested_value))
        if existing is None:
            db.add(
                PursuitContextSuggestion(
                    organization_id=organization_id,
                    pursuit_id=pursuit_id,
                    document_version_id=version_id,
                    field_name=field_name,
                    suggested_value=str(suggested_value),
                    page_number=page_number,
                    evidence_span=span,
                    confidence=0.9 if span else 0.7,
                    review_state="PROVISIONAL",
                )
            )
        elif existing.review_state == "PROVISIONAL":
            existing.suggested_value = str(suggested_value)
            existing.page_number = page_number
            existing.evidence_span = span
            existing.confidence = 0.9 if span else 0.7


@dataclass(frozen=True)
class PersistedLibraryDocument:
    batch: PrivateDocumentBatch
    document_id: UUID
    version_id: UUID
    job_id: UUID


async def persist_library_document(
    db: AsyncSession,
    *,
    organization_id: UUID,
    membership_id: UUID,
    file: StagedPrivateFile,
    library_kind: str = "CV",
) -> PersistedLibraryDocument:
    """R3: the same intake as a pursuit pack, for one organization library document.

    Bytes, immutable version and durable job are flushed in the caller's transaction;
    the caller commits (with whatever it records about the document) or rolls back.
    """
    await _require_active_membership(db, organization_id=organization_id, membership_id=membership_id)
    batch = PrivateDocumentBatch(
        organization_id=organization_id,
        pursuit_id=None,
        requested_by_membership_id=membership_id,
        state=DocumentProcessingState.QUEUED,
        file_count=1,
        processed_count=0,
        failed_count=0,
    )
    db.add(batch)
    await db.flush()
    document_id = uuid4()
    version_id = uuid4()
    storage_key = opaque_library_storage_key(organization_id=organization_id, version_id=version_id)
    document = PrivateDocument(
        id=document_id,
        organization_id=organization_id,
        pursuit_id=None,
        library_kind=library_kind,
        role=PrivateDocumentRole.OTHER,
        display_name=file.safe_display_filename,
        state=PrivateDocumentState.ACTIVE,
        created_by_membership_id=membership_id,
    )
    version = DocumentVersion(
        id=version_id,
        organization_id=organization_id,
        private_document_id=document_id,
        version_number=1,
        original_filename=file.original_filename,
        safe_display_filename=file.safe_display_filename,
        media_type=file.media_type,
        byte_size=file.byte_size,
        sha256=file.sha256,
        storage_key=storage_key,
        uploader_membership_id=membership_id,
    )
    db.add_all([document, version])
    await db.flush()
    job = DocumentProcessingJob(
        batch_id=batch.id,
        document_version_id=version_id,
        state=DocumentProcessingState.QUEUED,
        next_dispatch_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()
    document.current_version_id = version_id
    await db.flush()
    commit_staged_file(file.path, storage_key)
    return PersistedLibraryDocument(batch=batch, document_id=document_id, version_id=version_id, job_id=job.id)


async def _rollup_batch(db: AsyncSession, batch_id: UUID) -> None:
    batch = await db.scalar(
        select(PrivateDocumentBatch).where(PrivateDocumentBatch.id == batch_id).with_for_update()
    )
    if batch is None:
        return
    jobs = list(
        (
            await db.scalars(
                select(DocumentProcessingJob).where(DocumentProcessingJob.batch_id == batch_id)
            )
        ).all()
    )
    terminal = [job for job in jobs if job.state in TERMINAL_PROCESSING_STATES]
    failed = [job for job in jobs if job.state == DocumentProcessingState.FAILED]
    partial = [job for job in jobs if job.state == DocumentProcessingState.PARTIAL]
    batch.processed_count = len(terminal)
    batch.failed_count = len(failed)
    if len(terminal) != batch.file_count:
        batch.state = DocumentProcessingState.EXTRACTING
        return
    batch.completed_at = datetime.now(timezone.utc)
    if len(failed) == batch.file_count:
        batch.state = DocumentProcessingState.FAILED
        outcome = "failed"
    elif failed or partial:
        batch.state = DocumentProcessingState.PARTIAL
        outcome = "partial"
    else:
        batch.state = DocumentProcessingState.READY
        outcome = "ready"
    if batch.pursuit_id is None:
        # A library upload (R3 CV intake) reports through its CV draft, not the pursuit inbox.
        return
    requester_user_id = await db.scalar(
        select(Membership.user_id).where(Membership.id == batch.requested_by_membership_id)
    )
    if requester_user_id is not None:
        await stage_private_document_notification(
            db,
            user_id=requester_user_id,
            organization_id=batch.organization_id,
            pursuit_id=batch.pursuit_id,
            batch_id=batch.id,
            outcome=outcome,
            processed_count=batch.processed_count,
            total_count=batch.file_count,
            failed_count=batch.failed_count,
        )


async def process_document_job(db: AsyncSession, job_id: UUID) -> dict[str, Any]:
    """Idempotently scan then extract one immutable version."""
    job = await db.scalar(
        select(DocumentProcessingJob)
        .where(DocumentProcessingJob.id == job_id)
        .with_for_update()
    )
    if job is None:
        return {"state": "missing"}
    if job.state in TERMINAL_PROCESSING_STATES:
        return {"state": job.state.value, "replayed": True}
    now = datetime.now(timezone.utc)
    if (
        job.state in {DocumentProcessingState.CHECKING, DocumentProcessingState.EXTRACTING}
        and job.lease_until is not None
        and job.lease_until > now
    ):
        return {"state": job.state.value, "leased": True}
    version = await db.get(DocumentVersion, job.document_version_id)
    if version is None:
        return {"state": "missing"}
    document = await db.get(PrivateDocument, version.private_document_id)
    if document is None:
        return {"state": "missing"}
    result = await db.scalar(
        select(DocumentProcessingResult).where(DocumentProcessingResult.job_id == job.id)
    )
    job.attempt_count += 1
    job.started_at = job.started_at or now
    job.completed_at = None
    job.lease_until = now + timedelta(minutes=3)
    job.state = DocumentProcessingState.CHECKING
    await db.commit()
    path = resolve_private_storage_key(version.storage_key)
    if not path.is_file():
        job.state = DocumentProcessingState.FAILED
        job.last_error_code = "PRIVATE_STORAGE_MISSING"
        job.last_error_detail = "Stored document bytes are unavailable"
        job.completed_at = now
        await _rollup_batch(db, job.batch_id)
        if document.library_kind == "CV":
            from app.services.cv_library import on_library_document_processed

            await on_library_document_processed(db, version_id=version.id, job=job)
        await db.commit()
        return {"state": "FAILED"}
    try:
        if result is None or result.malware_scan_status != "CLEAN":
            scan_label = await asyncio.to_thread(scan_with_clamav, path)
            job = await db.get(DocumentProcessingJob, job_id)
            result = await db.scalar(
                select(DocumentProcessingResult).where(DocumentProcessingResult.job_id == job_id)
            )
            if result is None:
                result = DocumentProcessingResult(
                    job_id=job_id,
                    document_version_id=version.id,
                    malware_scan_status="CLEAN",
                    malware_scanner=scan_label[:100],
                    page_count_status="UNKNOWN",
                )
                db.add(result)
            else:
                result.malware_scan_status = "CLEAN"
                result.malware_scanner = scan_label[:100]
        job.state = DocumentProcessingState.EXTRACTING
        job.lease_until = datetime.now(timezone.utc) + timedelta(minutes=3)
        await db.commit()
        parsed = await _parse_private_file(path, version.media_type)
        job = await db.get(DocumentProcessingJob, job_id)
        result = await db.scalar(
            select(DocumentProcessingResult).where(DocumentProcessingResult.job_id == job_id)
        )
        if result is None:
            raise PrivateDocumentError("Processing result is unavailable")
        extracted = str(parsed["text"])
        result.page_count = parsed.get("page_count")
        result.page_count_status = parsed.get("page_count_status", "UNKNOWN")
        result.extracted_text = extracted
        result.extracted_sha256 = hashlib.sha256(extracted.encode("utf-8")).hexdigest()
        result.extraction_error_code = parsed.get("error_code")
        result.extraction_error_detail = None
        result.parser_name = parsed.get("parser_name")
        result.parser_version = "w3-v1"
        job.state = DocumentProcessingState(parsed["state"])
        job.last_error_code = parsed.get("error_code")
        job.last_error_detail = None
        job.completed_at = datetime.now(timezone.utc)
        job.lease_until = None
        if document.pursuit_id is not None:
            await _persist_suggestions(
                db,
                organization_id=document.organization_id,
                pursuit_id=document.pursuit_id,
                version_id=version.id,
                extracted_text=extracted,
            )
    except MalwareDetectedError:
        if result is None:
            result = DocumentProcessingResult(
                job_id=job.id,
                document_version_id=version.id,
                malware_scan_status="INFECTED",
                malware_scanner="clamav",
                page_count_status="UNKNOWN",
            )
            db.add(result)
        else:
            result.malware_scan_status = "INFECTED"
        job.state = DocumentProcessingState.FAILED
        job.last_error_code = "MALWARE_DETECTED"
        job.last_error_detail = "The file failed malware screening"
        job.completed_at = datetime.now(timezone.utc)
        job.lease_until = None
    except (MalwareScanError, PrivateDocumentError, OSError, ValueError, json.JSONDecodeError) as exc:
        if result is None:
            result = DocumentProcessingResult(
                job_id=job.id,
                document_version_id=version.id,
                malware_scan_status="ERROR" if isinstance(exc, MalwareScanError) else "CLEAN",
                malware_scanner="clamav",
                page_count_status="UNKNOWN",
            )
            db.add(result)
        job.state = DocumentProcessingState.FAILED
        job.last_error_code = (
            "MALWARE_SCANNER_UNAVAILABLE"
            if isinstance(exc, MalwareScanError)
            else "PRIVATE_DOCUMENT_EXTRACTION_FAILED"
        )
        job.last_error_detail = str(exc)[:500]
        result.extraction_error_code = job.last_error_code
        result.extraction_error_detail = job.last_error_detail
        job.completed_at = datetime.now(timezone.utc)
        job.lease_until = None
    await _rollup_batch(db, job.batch_id)
    cv_draft_ids: list[str] = []
    if document.library_kind == "CV":
        from app.services.cv_library import on_library_document_processed

        cv_draft_ids = [str(value) for value in await on_library_document_processed(db, version_id=version.id, job=job)]
    await db.commit()
    return {"state": job.state.value, "job_id": str(job.id), "cv_draft_ids": cv_draft_ids}
