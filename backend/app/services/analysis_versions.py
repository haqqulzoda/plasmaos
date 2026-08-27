"""Immutable compliance analysis version creation and ownership-aware reads."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.reproducibility import (
    canonical_marker_text_sha256,
    safe_basename,
    sha256_text,
    stable_json_sha256,
)
from app.models.all_models import Tender, TenderDocument
from app.models.audit import (
    ANALYSIS_OWNERSHIP_OWNED,
    ANALYSIS_SNAPSHOT_COMPLETE,
    ANALYSIS_SNAPSHOT_PARTIAL,
    ANALYSIS_VERSION_ORIGIN_RUNTIME_ANALYSIS,
    ANALYSIS_VERSION_ORIGIN_RUNTIME_REANALYSIS,
    ANALYSIS_VERSION_STATUS_FAILED,
    AnalysisVersion,
    AnalysisVersionDocumentSnapshot,
    TenderAnalysis,
)


ANALYSIS_PIPELINE_VERSION = "hybrid_compliance_s2_2_v1"


class AnalysisVersionOwnershipError(RuntimeError):
    """Raised when a customer-owned runtime version lacks a valid parent owner."""


@dataclass(frozen=True)
class DocumentSnapshotInput:
    tender_document_id: UUID | None
    source_system: str
    source_document_key: str | None
    source_url: str | None
    filename: str | None
    media_type: str | None
    content_hash: str | None
    storage_reference: str | None
    storage_version: str | None
    fetched_at: datetime | None
    observed_at: datetime | None
    snapshot_metadata: dict[str, Any]


def analysis_version_status(analysis_status: str | None) -> str:
    normalized = str(analysis_status or "completed").casefold()
    if normalized == "failed":
        return "FAILED"
    if normalized == "needs_review":
        return "NEEDS_REVIEW"
    return "COMPLETED"


def build_tender_snapshot(tender: Tender) -> dict[str, Any]:
    """Capture only tender values consumed or displayed by compliance."""
    return {
        "tender_id": str(tender.id),
        "source_system": tender.source_system,
        "external_id": tender.external_id,
        "canonical_source_key": tender.canonical_source_key,
        "title": tender.title,
        "buyer": tender.buyer,
        "deadline": tender.deadline.isoformat() if tender.deadline else None,
        "currency": tender.currency,
        "budget": tender.budget,
        "procurement_method": tender.procurement_method,
        "notice_type": tender.notice_type,
        "project_id": tender.project_id,
        "source_url": tender.source_url,
    }


def build_company_snapshot(
    *,
    company_profile_id: UUID,
    company_name: str,
    vault_payload: dict[str, Any],
    credential_taxonomy_node_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Capture the non-personal readiness inputs supplied to compliance."""
    return {
        "company_profile_id": str(company_profile_id),
        "company_name": company_name,
        "vault": deepcopy(vault_payload),
        "credential_taxonomy_node_ids": sorted(credential_taxonomy_node_ids),
    }


def build_evidence_snapshot(analysis_json: dict[str, Any]) -> dict[str, Any]:
    reproducibility = analysis_json.get("reproducibility_snapshot")
    if not isinstance(reproducibility, dict):
        reproducibility = {}
    return {
        "evidence_validation": deepcopy(analysis_json.get("evidence_validation")),
        "hybrid_compliance": deepcopy(analysis_json.get("hybrid_compliance")),
        "requirement_route_summary": deepcopy(
            reproducibility.get("requirement_route_summary")
        ),
    }


def document_snapshot_input(
    document: TenderDocument,
    *,
    source_system: str,
) -> DocumentSnapshotInput:
    parsed_text = document.parsed_text or ""
    filename_source = (
        document.source_document_url
        or document.file_url
        or document.storage_path
    )
    metadata = {
        "file_type": document.file_type,
        "file_size": document.file_size,
        "download_status": document.download_status,
        "source_document_type": document.source_document_type,
        "parsed_text_length": len(parsed_text),
        "parsed_text_sha256": sha256_text(parsed_text),
        "parsed_text_canonical_marker_sha256": canonical_marker_text_sha256(
            parsed_text
        ),
    }
    return DocumentSnapshotInput(
        tender_document_id=document.id,
        source_system=source_system,
        source_document_key=document.external_file_id,
        source_url=document.source_document_url or document.file_url,
        filename=safe_basename(filename_source),
        media_type=document.mime_type,
        content_hash=document.sha256,
        storage_reference=document.storage_path,
        storage_version=None,
        fetched_at=None,
        observed_at=document.created_at,
        snapshot_metadata=metadata,
    )


def document_set_hash(documents: Sequence[DocumentSnapshotInput]) -> str:
    payload = [
        {
            "tender_document_id": str(item.tender_document_id)
            if item.tender_document_id
            else None,
            "source_system": item.source_system,
            "source_document_key": item.source_document_key,
            "source_url": item.source_url,
            "filename": item.filename,
            "media_type": item.media_type,
            "content_hash": item.content_hash,
            "storage_reference": item.storage_reference,
            "storage_version": item.storage_version,
            "fetched_at": item.fetched_at.isoformat() if item.fetched_at else None,
            "observed_at": item.observed_at.isoformat() if item.observed_at else None,
            "snapshot_metadata": item.snapshot_metadata,
        }
        for item in documents
    ]
    payload.sort(key=stable_json_sha256)
    return stable_json_sha256(payload)


def runtime_snapshot_completeness(
    *,
    status: str,
    input_hash: str | None,
    provenance_snapshot: dict[str, Any],
    documents: Sequence[DocumentSnapshotInput],
) -> str:
    requirement = provenance_snapshot.get("requirement_extractor")
    prompt_hash = (
        requirement.get("prompt_template_hash")
        if isinstance(requirement, dict)
        else None
    )
    model_name = (
        requirement.get("model_name") if isinstance(requirement, dict) else None
    )
    documents_complete = bool(documents) and all(
        item.content_hash
        or (
            item.snapshot_metadata.get("parsed_text_length", 0) > 0
            and item.snapshot_metadata.get("parsed_text_sha256")
        )
        for item in documents
    )
    if (
        status != ANALYSIS_VERSION_STATUS_FAILED
        and input_hash
        and model_name
        and prompt_hash
        and documents_complete
    ):
        return ANALYSIS_SNAPSHOT_COMPLETE
    return ANALYSIS_SNAPSHOT_PARTIAL


def _version_hash_payload(
    *,
    analysis_id: UUID,
    version_number: int,
    supersedes_version_id: UUID | None,
    origin: str,
    status: str,
    analysis_schema_version: str | None,
    pipeline_version: str | None,
    model_provider: str | None,
    model_name: str | None,
    model_version: str | None,
    prompt_template_version: str | None,
    prompt_template_hash: str | None,
    provenance_snapshot: dict[str, Any],
    tender_snapshot: dict[str, Any],
    company_snapshot: dict[str, Any],
    result_snapshot: dict[str, Any],
    evidence_snapshot: dict[str, Any],
    input_hash: str | None,
    output_hash: str,
    evidence_hash: str,
    document_set_hash_value: str,
    snapshot_completeness: str,
    requested_by_user_id: UUID | None,
) -> dict[str, Any]:
    return {
        "analysis_id": str(analysis_id),
        "version_number": version_number,
        "supersedes_version_id": str(supersedes_version_id)
        if supersedes_version_id
        else None,
        "origin": origin,
        "status": status,
        "analysis_schema_version": analysis_schema_version,
        "pipeline_version": pipeline_version,
        "model_provider": model_provider,
        "model_name": model_name,
        "model_version": model_version,
        "prompt_template_version": prompt_template_version,
        "prompt_template_hash": prompt_template_hash,
        "provenance_snapshot": provenance_snapshot,
        "tender_snapshot": tender_snapshot,
        "company_snapshot": company_snapshot,
        "result_snapshot": result_snapshot,
        "evidence_snapshot": evidence_snapshot,
        "input_hash": input_hash,
        "output_hash": output_hash,
        "evidence_hash": evidence_hash,
        "document_set_hash": document_set_hash_value,
        "snapshot_completeness": snapshot_completeness,
        "requested_by_user_id": str(requested_by_user_id)
        if requested_by_user_id
        else None,
    }


async def append_analysis_version(
    db: AsyncSession,
    *,
    analysis_id: UUID,
    requested_by_user_id: UUID,
    company_profile_id: UUID,
    status: str,
    analysis_schema_version: str | None,
    model_provider: str | None,
    model_name: str | None,
    model_version: str | None,
    prompt_template_version: str | None,
    prompt_template_hash: str | None,
    provenance_snapshot: dict[str, Any],
    tender_snapshot: dict[str, Any],
    company_snapshot: dict[str, Any],
    result_snapshot: dict[str, Any],
    evidence_snapshot: dict[str, Any],
    input_hash: str | None,
    documents: Sequence[DocumentSnapshotInput],
    completed_at: datetime | None = None,
) -> AnalysisVersion:
    """Lock the parent, allocate N+1, and stage one immutable version."""
    parent_result = await db.execute(
        select(TenderAnalysis)
        .where(TenderAnalysis.id == analysis_id)
        .with_for_update()
    )
    parent = parent_result.scalar_one_or_none()
    if (
        parent is None
        or parent.ownership_state != ANALYSIS_OWNERSHIP_OWNED
        or parent.user_id != requested_by_user_id
        or parent.company_profile_id != company_profile_id
    ):
        raise AnalysisVersionOwnershipError("analysis parent is not owned by requester")

    previous_result = await db.execute(
        select(AnalysisVersion)
        .where(AnalysisVersion.analysis_id == analysis_id)
        .order_by(AnalysisVersion.version_number.desc())
        .limit(1)
    )
    previous = previous_result.scalar_one_or_none()
    version_number = (previous.version_number + 1) if previous else 1
    origin = (
        ANALYSIS_VERSION_ORIGIN_RUNTIME_REANALYSIS
        if previous
        else ANALYSIS_VERSION_ORIGIN_RUNTIME_ANALYSIS
    )
    supersedes_version_id = previous.id if previous else None

    result_copy = deepcopy(result_snapshot)
    evidence_copy = deepcopy(evidence_snapshot)
    provenance_copy = deepcopy(provenance_snapshot)
    tender_copy = deepcopy(tender_snapshot)
    company_copy = deepcopy(company_snapshot)
    output_hash = stable_json_sha256(result_copy)
    evidence_hash = stable_json_sha256(evidence_copy)
    document_hash = document_set_hash(documents)
    completeness = runtime_snapshot_completeness(
        status=status,
        input_hash=input_hash,
        provenance_snapshot=provenance_copy,
        documents=documents,
    )
    version_hash = stable_json_sha256(
        _version_hash_payload(
            analysis_id=analysis_id,
            version_number=version_number,
            supersedes_version_id=supersedes_version_id,
            origin=origin,
            status=status,
            analysis_schema_version=analysis_schema_version,
            pipeline_version=ANALYSIS_PIPELINE_VERSION,
            model_provider=model_provider,
            model_name=model_name,
            model_version=model_version,
            prompt_template_version=prompt_template_version,
            prompt_template_hash=prompt_template_hash,
            provenance_snapshot=provenance_copy,
            tender_snapshot=tender_copy,
            company_snapshot=company_copy,
            result_snapshot=result_copy,
            evidence_snapshot=evidence_copy,
            input_hash=input_hash,
            output_hash=output_hash,
            evidence_hash=evidence_hash,
            document_set_hash_value=document_hash,
            snapshot_completeness=completeness,
            requested_by_user_id=requested_by_user_id,
        )
    )

    version = AnalysisVersion(
        analysis_id=analysis_id,
        version_number=version_number,
        supersedes_version_id=supersedes_version_id,
        origin=origin,
        status=status,
        analysis_schema_version=analysis_schema_version,
        pipeline_version=ANALYSIS_PIPELINE_VERSION,
        model_provider=model_provider,
        model_name=model_name,
        model_version=model_version,
        prompt_template_version=prompt_template_version,
        prompt_template_hash=prompt_template_hash,
        provenance_snapshot=provenance_copy,
        tender_snapshot=tender_copy,
        company_snapshot=company_copy,
        result_snapshot=result_copy,
        evidence_snapshot=evidence_copy,
        input_hash=input_hash,
        output_hash=output_hash,
        evidence_hash=evidence_hash,
        document_set_hash=document_hash,
        version_hash=version_hash,
        snapshot_completeness=completeness,
        requested_by_user_id=requested_by_user_id,
        completed_at=completed_at or datetime.now(timezone.utc),
    )
    db.add(version)
    await db.flush()

    for item in documents:
        db.add(
            AnalysisVersionDocumentSnapshot(
                analysis_version_id=version.id,
                tender_document_id=item.tender_document_id,
                source_system=item.source_system,
                source_document_key=item.source_document_key,
                source_url=item.source_url,
                filename=item.filename,
                media_type=item.media_type,
                content_hash=item.content_hash,
                storage_reference=item.storage_reference,
                storage_version=item.storage_version,
                fetched_at=item.fetched_at,
                observed_at=item.observed_at,
                snapshot_metadata=deepcopy(item.snapshot_metadata),
            )
        )
    await db.flush()
    return version


async def create_initial_analysis_version(
    db: AsyncSession,
    **version_values: Any,
) -> AnalysisVersion:
    """Stage v1 and reject accidental use against an existing aggregate."""
    version = await append_analysis_version(db, **version_values)
    if version.version_number != 1:
        raise RuntimeError("initial analysis version already exists")
    return version


async def get_latest_analysis_version(
    db: AsyncSession,
    *,
    analysis_id: UUID,
    user_id: UUID,
    company_profile_id: UUID,
) -> AnalysisVersion | None:
    result = await db.execute(
        select(AnalysisVersion)
        .join(TenderAnalysis, TenderAnalysis.id == AnalysisVersion.analysis_id)
        .where(
            AnalysisVersion.analysis_id == analysis_id,
            TenderAnalysis.user_id == user_id,
            TenderAnalysis.company_profile_id == company_profile_id,
            TenderAnalysis.ownership_state == ANALYSIS_OWNERSHIP_OWNED,
        )
        .order_by(AnalysisVersion.version_number.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_analysis_versions(
    db: AsyncSession,
    *,
    analysis_id: UUID,
    user_id: UUID,
    company_profile_id: UUID,
) -> list[AnalysisVersion]:
    result = await db.execute(
        select(AnalysisVersion)
        .join(TenderAnalysis, TenderAnalysis.id == AnalysisVersion.analysis_id)
        .where(
            AnalysisVersion.analysis_id == analysis_id,
            TenderAnalysis.user_id == user_id,
            TenderAnalysis.company_profile_id == company_profile_id,
            TenderAnalysis.ownership_state == ANALYSIS_OWNERSHIP_OWNED,
        )
        .order_by(AnalysisVersion.version_number.asc())
    )
    return list(result.scalars().all())
