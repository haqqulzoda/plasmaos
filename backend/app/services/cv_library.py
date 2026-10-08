"""R3 Task 3: CV upload -> reviewable CV draft -> confirmed CVVersion.

An uploaded CV goes through the private-document intake as an organization library
document (no pursuit). When processing is READY, an extraction job proposes fields with
verified quotes (app.services.cv_extraction). Nothing becomes a CV until a person
confirms the reviewed fields: confirming writes a new immutable CVVersion
(evidence_state UNVERIFIED) whose provenance names the document version and the quotes.
A re-upload is a new document and a new draft; confirmed CVs are never changed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents import pursuit_analyzer
from app.models.base import DocumentProcessingState
from app.models.candidate_retrieval import CVVersion, Expert
from app.models.cv_drafts import CVDraft
from app.models.private_documents import DocumentProcessingJob, DocumentProcessingResult, DocumentVersion, PrivateDocument
from app.services.candidate_retrieval import _canonical_payload
from app.services.cv_extraction import (
    CV_EXTRACTION_BUDGET_SECONDS,
    PROMPT_VERSION,
    SECTION_LIMITS,
    SECTIONS,
    CVExtractionError,
    ProviderCall,
    extract_cv,
)
from app.services.private_documents import StagedPrivateFile, persist_library_document


MAX_EXTRACTION_ATTEMPTS = 2
TRANSIENT_FAILURES = frozenset({"PROVIDER_TIMEOUT", "PROVIDER_ERROR", "OUTPUT_INVALID", "BUDGET_EXCEEDED"})
REVIEW_TEXT_MAX_CHARACTERS = 200_000
CONFIRMABLE_STATES = frozenset({"QUEUED", "EXTRACTING", "READY", "FAILED"})
BLOCKING_FAILURES = frozenset({"DOCUMENT_REJECTED"})


class CVLibraryError(RuntimeError):
    pass


class CVLibraryNotFoundError(CVLibraryError):
    pass


class CVLibraryConflictError(CVLibraryError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _private_expert(db: AsyncSession, *, organization_id: UUID, expert_id: UUID, lock: bool = False) -> Expert:
    statement = select(Expert).where(
        Expert.id == expert_id,
        Expert.scope == "ORGANIZATION_PRIVATE",
        Expert.owner_organization_id == organization_id,
    )
    expert = await db.scalar(statement.with_for_update() if lock else statement)
    if expert is None:
        raise CVLibraryNotFoundError("Expert not found")
    return expert


# ---- upload -----------------------------------------------------------------------------------------

async def upload_cv(
    db: AsyncSession,
    *,
    organization_id: UUID,
    membership_id: UUID,
    staged: StagedPrivateFile,
    expert_id: UUID | None = None,
) -> tuple[CVDraft, UUID]:
    """Persist the CV through the private intake and open its draft. Returns (draft, job id)."""
    if expert_id is not None:
        await _private_expert(db, organization_id=organization_id, expert_id=expert_id)
    stored = None
    try:
        persisted = await persist_library_document(
            db, organization_id=organization_id, membership_id=membership_id, file=staged,
        )
        version = await db.get(DocumentVersion, persisted.version_id)
        stored = version.storage_key if version is not None else None
        draft = CVDraft(
            organization_id=organization_id,
            expert_id=expert_id,
            private_document_id=persisted.document_id,
            document_version_id=persisted.version_id,
            state="PROCESSING_DOCUMENT",
            proposal={},
            extraction_summary={},
            created_by_membership_id=membership_id,
        )
        db.add(draft)
        await db.commit()
    except BaseException:
        await db.rollback()
        if stored:
            from app.core.private_storage import resolve_private_storage_key

            try:
                resolve_private_storage_key(stored).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001 - best-effort cleanup of bytes never committed
                pass
        raise
    await db.refresh(draft)
    return draft, persisted.job_id


async def on_library_document_processed(
    db: AsyncSession, *, version_id: UUID, job: DocumentProcessingJob
) -> list[UUID]:
    """Called by the document job in its transaction: queue extraction or fail the draft."""
    draft = await db.scalar(
        select(CVDraft).where(CVDraft.document_version_id == version_id).with_for_update()
    )
    if draft is None or draft.state != "PROCESSING_DOCUMENT":
        return []
    now = _now()
    if job.state in {DocumentProcessingState.READY, DocumentProcessingState.PARTIAL}:
        text = await db.scalar(
            select(DocumentProcessingResult.extracted_text).where(DocumentProcessingResult.document_version_id == version_id)
        )
        if text and text.strip():
            draft.state = "QUEUED"
            draft.next_attempt_at = now
            draft.updated_at = now
            return [draft.id]
        draft.state, draft.failure_code = "FAILED", "DOCUMENT_TEXT_UNAVAILABLE"
    elif job.state == DocumentProcessingState.FAILED:
        draft.state = "FAILED"
        draft.failure_code = "DOCUMENT_REJECTED" if job.last_error_code == "MALWARE_DETECTED" else "DOCUMENT_FAILED"
    else:
        return []
    draft.updated_at = now
    return []


# ---- extraction job ---------------------------------------------------------------------------------

async def due_cv_draft_ids(db: AsyncSession, *, limit: int = 25) -> list[UUID]:
    now = _now()
    return list(
        (
            await db.scalars(
                select(CVDraft.id)
                .where(
                    CVDraft.next_attempt_at <= now,
                    or_(
                        CVDraft.state == "QUEUED",
                        (CVDraft.state == "EXTRACTING") & (CVDraft.lease_until.is_(None) | (CVDraft.lease_until <= now)),
                    ),
                )
                .order_by(CVDraft.next_attempt_at, CVDraft.id)
                .limit(limit)
            )
        ).all()
    )


async def process_cv_draft(db: AsyncSession, draft_id: UUID, *, call: ProviderCall | None = None) -> str:
    """Lease, extract, verify and store a proposal. Idempotent; never writes a CVVersion."""
    now = _now()
    draft = await db.scalar(select(CVDraft).where(CVDraft.id == draft_id).with_for_update())
    if draft is None:
        return "MISSING"
    if draft.state not in {"QUEUED", "EXTRACTING"}:
        return draft.state
    if draft.state == "EXTRACTING" and draft.lease_until is not None and draft.lease_until > now:
        return "LEASED"
    text = await db.scalar(
        select(DocumentProcessingResult.extracted_text).where(
            DocumentProcessingResult.document_version_id == draft.document_version_id,
            DocumentProcessingResult.malware_scan_status == "CLEAN",
        )
    )
    draft.state = "EXTRACTING"
    draft.attempt_count += 1
    draft.lease_until = now + timedelta(seconds=CV_EXTRACTION_BUDGET_SECONDS + 60)
    draft.updated_at = now
    await db.commit()
    if not text or not text.strip():
        return await _finish(db, draft_id, state="FAILED", failure_code="DOCUMENT_TEXT_UNAVAILABLE")
    try:
        result = await extract_cv(text, call)
    except CVExtractionError as exc:
        return await _finish(db, draft_id, state="FAILED", failure_code=exc.code, retry=exc.code in TRANSIENT_FAILURES)
    return await _finish(
        db, draft_id, state="READY", proposal=result.proposal, summary=result.summary, model_name=result.model_name,
    )


async def _finish(
    db: AsyncSession,
    draft_id: UUID,
    *,
    state: str,
    failure_code: str | None = None,
    retry: bool = False,
    proposal: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    model_name: str | None = None,
) -> str:
    draft = await db.scalar(select(CVDraft).where(CVDraft.id == draft_id).with_for_update())
    if draft is None:
        return "MISSING"
    if draft.state != "EXTRACTING":
        # Confirmed by hand while the model ran: the person's CV stands; nothing is overwritten.
        return draft.state
    now = _now()
    if retry and draft.attempt_count < MAX_EXTRACTION_ATTEMPTS:
        draft.state = "QUEUED"
        draft.next_attempt_at = now + timedelta(seconds=60)
    else:
        draft.state = state
    draft.failure_code = failure_code if draft.state == "FAILED" else None
    if proposal is not None:
        draft.proposal = proposal
    if summary is not None:
        draft.extraction_summary = summary
    elif failure_code:
        draft.extraction_summary = {"prompt_version": PROMPT_VERSION, "failure_code": failure_code}
    draft.model_name = model_name or draft.model_name
    draft.lease_until = None
    draft.updated_at = now
    final = draft.state
    await db.commit()
    return final


# ---- reads ------------------------------------------------------------------------------------------

async def list_cv_drafts(
    db: AsyncSession, *, organization_id: UUID, expert_id: UUID | None = None, limit: int = 50
) -> list[tuple[CVDraft, str | None, str | None]]:
    """Newest first, with the uploaded file name and expert name."""
    statement = (
        select(CVDraft, DocumentVersion.safe_display_filename, Expert.display_name)
        .join(DocumentVersion, DocumentVersion.id == CVDraft.document_version_id)
        .outerjoin(Expert, Expert.id == CVDraft.expert_id)
        .where(CVDraft.organization_id == organization_id)
        .order_by(CVDraft.created_at.desc(), CVDraft.id.desc())
        .limit(limit)
    )
    if expert_id is not None:
        statement = statement.where(CVDraft.expert_id == expert_id)
    return [(row[0], row[1], row[2]) for row in (await db.execute(statement)).all()]


async def get_cv_draft(db: AsyncSession, *, organization_id: UUID, draft_id: UUID) -> dict[str, Any]:
    """The draft with the parsed document text for side-by-side review. Passive."""
    row = (
        await db.execute(
            select(CVDraft, DocumentVersion, Expert.display_name)
            .join(DocumentVersion, DocumentVersion.id == CVDraft.document_version_id)
            .outerjoin(Expert, Expert.id == CVDraft.expert_id)
            .where(CVDraft.id == draft_id, CVDraft.organization_id == organization_id)
        )
    ).one_or_none()
    if row is None:
        raise CVLibraryNotFoundError("CV draft not found")
    draft, version, expert_name = row
    text = await db.scalar(
        select(DocumentProcessingResult.extracted_text).where(
            DocumentProcessingResult.document_version_id == version.id,
            DocumentProcessingResult.malware_scan_status == "CLEAN",
        )
    )
    return {
        "draft": draft,
        "display_filename": version.safe_display_filename,
        "expert_name": expert_name,
        "document_text": text[:REVIEW_TEXT_MAX_CHARACTERS] if text else None,
        "document_text_truncated": bool(text and len(text) > REVIEW_TEXT_MAX_CHARACTERS),
    }


# ---- confirm ----------------------------------------------------------------------------------------

def _clean(value: Any, limit: int = 500) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    return " ".join(str(value).split())[:limit]


def reviewed_rows(section: str, rows: list[dict[str, Any]], text: str | None) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """The person's rows: known fields only, empty rows dropped. Quotes are kept for
    provenance only when they are still verbatim in the document text."""
    fields = SECTIONS[section]
    facts: list[dict[str, str]] = []
    quotes: list[dict[str, Any]] = []
    for row in rows[: SECTION_LIMITS[section]]:
        if not isinstance(row, dict):
            continue
        values = {field: _clean(row.get(field), 2_000 if field == "description" else 500) for field in fields}
        values = {key: value for key, value in values.items() if value}
        if not values:
            continue
        quote = _clean(row.get("quote"), 600)
        verified = bool(text and quote and pursuit_analyzer._normalized_contains(text, quote))
        if verified:
            quotes.append({"section": section, "index": len(facts), "quote": quote})
        facts.append(values)
    return facts, quotes


async def confirm_cv_draft(
    db: AsyncSession,
    *,
    organization_id: UUID,
    membership_id: UUID,
    actor_user_id: UUID,
    draft_id: UUID,
    sections: dict[str, list[dict[str, Any]]],
    new_expert_name: str | None = None,
) -> tuple[CVVersion, Expert]:
    """Write the reviewed fields as a new immutable CVVersion (UNVERIFIED) in one transaction."""
    draft = await db.scalar(
        select(CVDraft).where(CVDraft.id == draft_id, CVDraft.organization_id == organization_id).with_for_update()
    )
    if draft is None:
        raise CVLibraryNotFoundError("CV draft not found")
    if draft.state == "CONFIRMED":
        raise CVLibraryConflictError("ALREADY_CONFIRMED", "This draft was already saved as a CV version")
    if draft.state not in CONFIRMABLE_STATES or draft.failure_code in BLOCKING_FAILURES:
        raise CVLibraryConflictError("NOT_CONFIRMABLE", "The uploaded document is not available for review")
    version = await db.get(DocumentVersion, draft.document_version_id)
    document = await db.get(PrivateDocument, draft.private_document_id)
    if version is None or document is None:
        raise CVLibraryNotFoundError("CV document not found")
    text = await db.scalar(
        select(DocumentProcessingResult.extracted_text).where(
            DocumentProcessingResult.document_version_id == version.id,
            DocumentProcessingResult.malware_scan_status == "CLEAN",
        )
    )
    facts: dict[str, list[dict[str, str]]] = {}
    quotes: list[dict[str, Any]] = []
    for section in SECTIONS:
        rows, row_quotes = reviewed_rows(section, sections.get(section) or [], text)
        facts[section] = rows
        quotes.extend(row_quotes)
    row_count = sum(len(rows) for rows in facts.values())
    if not row_count:
        raise CVLibraryConflictError("EMPTY_CV", "Add at least one education, assignment, language or certification")
    if draft.expert_id is not None:
        expert = await _private_expert(db, organization_id=organization_id, expert_id=draft.expert_id, lock=True)
    else:
        name = _clean(new_expert_name, 500)
        if len(name) < 2:
            raise CVLibraryConflictError("EXPERT_NAME_REQUIRED", "Name the expert this CV belongs to")
        expert = Expert(
            scope="ORGANIZATION_PRIVATE", owner_organization_id=organization_id, display_name=name,
            qualifications=[], languages=[], specializations=[], consent_state="NOT_REQUIRED_PRIVATE",
            evidence_state="UNVERIFIED",
            source_provenance={"source": "CV_UPLOAD", "cv_draft_id": str(draft.id)},
            created_by_user_id=actor_user_id,
        )
        db.add(expert)
        await db.flush()
    current = await db.scalar(select(func.max(CVVersion.version_number)).where(CVVersion.expert_id == expert.id))
    provenance = {
        "entry": "CV_UPLOAD_REVIEWED",
        "cv_draft_id": str(draft.id),
        "private_document_id": str(document.id),
        "document_version_id": str(version.id),
        "document_sha256": version.sha256,
        "document_filename": version.safe_display_filename,
        "model_name": draft.model_name,
        "prompt_version": (draft.extraction_summary or {}).get("prompt_version"),
        "extraction_state": draft.state,
        "quotes": quotes,
        "rows_with_verified_quote": len(quotes),
        "rows_without_verified_quote": row_count - len(quotes),
        "reviewed_by_membership_id": str(membership_id),
    }
    payload = {
        "education": facts["education"], "qualifications": [], "certifications": facts["certifications"],
        "assignments": facts["assignments"], "languages": facts["languages"],
        "evidence_provenance": provenance, "evidence_state": "UNVERIFIED",
    }
    cv = CVVersion(
        expert_id=expert.id, version_number=int(current or 0) + 1,
        structured_sha256=hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest(),
        created_by_user_id=actor_user_id, **payload,
    )
    db.add(cv)
    await db.flush()
    now = _now()
    draft.expert_id = expert.id
    draft.state = "CONFIRMED"
    draft.confirmed_cv_version_id = cv.id
    draft.confirmed_by_membership_id = membership_id
    draft.confirmed_at = now
    draft.lease_until = None
    draft.updated_at = now
    await db.commit()
    await db.refresh(cv)
    await db.refresh(expert)
    return cv, expert
