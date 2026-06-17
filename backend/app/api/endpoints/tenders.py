"""
Plasma AI - Tenders Endpoints

Public tender feed for the Autonomous Tender Officer.
"""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.api.deps import (
    get_current_user,
    is_operator_or_admin,
    require_admin,
    require_operator_or_admin,
)
from app.core.agents.requirement_extractor import (
    EvidenceValidationStatus,
    EXTRACTOR_SCHEMA_VERSION,
    MAX_PAYLOAD_CHARS,
    MODEL_NAME as REQUIREMENT_MODEL_NAME,
    ScopeReviewStatus,
    build_failed_extraction_artifacts_metadata,
    build_failed_extraction_coverage,
    build_extraction_warnings,
    classify_requirements_scope,
    extract_requirements_with_coverage,
    validate_requirements_evidence,
)
from app.core.agents.strategy_extractor import (
    TenderStrategyIntelligence,
    extract_strategy_intelligence,
)
from app.core.ai_analyzer import ExtractedTenderRequirements
from app.core.compliance_pdf import (
    build_compliance_report_pdf,
    compliance_report_filename,
)
from app.core.evaluator import DynamicComplianceResult, TaxNodeInfo
from app.core.reproducibility import (
    annotate_evidence_validation,
    annotate_hybrid_compliance,
    canonical_marker_text_sha256,
    canonical_source_filename,
    engine_metadata,
    evidence_validation_route_records,
    marker_counts,
    requirement_fingerprint,
    requirement_route_records,
    safe_basename,
    sanitize_internal_requirement_diagnostics,
    sha256_text,
    stable_document_order_key,
    stable_json_sha256,
)
from app.core.scraper import UzExScraper
from app.crud.crud_profile import get_profile_for_compliance_match
from app.crud.exceptions import ProfileNotFoundException
from app.db.session import get_db
from app.models.audit import TenderAnalysis
from app.models.all_models import (
    Proposal,
    RiskOverrideLog,
    TaxonomyNode,
    Tender,
    TenderDocument,
    TenderStatus,
    TenderSyncJob,
    TenderSyncStatus,
    User,
)
from app.models.company import CompanyProfile
from app.models.taxonomy import CompanyCredential
from app.schemas.tender import TenderDocumentResponse, TenderResponse
from app.schemas.vault import (
    CertificationItem,
    CompanyVaultResponse,
    FinancialHistoryItem,
    LicenseItem,
)
from app.services.compliance_engine import (
    ComplianceResult as HybridComplianceResult,
    ComplianceVerdictStatus,
    MatchMethod,
    MatchVerdict,
    RequirementMatchDetail,
    evaluate_tender_compliance,
)
from app.services.tender_sources.base import NormalizedTender
from app.services.tender_sources.adb import AdbTenderSource
from app.services.tender_sources.uzex import UzExTenderSource
from app.services.tender_sources.uzex_constants import UZEX_ENTERPRISE_TYPE_ID
from app.services.tender_sources.uzex_scope import customer_visible_tender_condition
from app.services.tender_sources.world_bank import WorldBankTenderSource
from app.workers.tender_tasks import process_tender_docs

logger = logging.getLogger(__name__)

router = APIRouter()


class RefreshResponse(BaseModel):
    """Response for refresh endpoint."""
    status: str
    new_count: int
    updated_count: int
    message: str


class SourceSyncResponse(BaseModel):
    """Response for source-specific tender sync endpoints."""

    status: str
    source_system: str
    fetched_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    attachment_count: int = 0
    documents_downloaded: int = 0
    dry_run: bool = False
    errors: list[str] = Field(default_factory=list)
    message: str


class AdbSyncResponse(BaseModel):
    """Response for ADB tender sync."""

    status: str
    source_system: str = "adb"
    fetched: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    attachments_discovered: int = 0
    documents_downloaded: int = 0
    dry_run: bool = False
    errors: list[str] = Field(default_factory=list)
    message: str


class SyncDocsAcceptedResponse(BaseModel):
    """Response for idempotent sync-docs enqueue endpoint."""

    message: str
    job_id: str
    tender_id: UUID
    user_id: UUID
    status: str
    progress: int
    error_message: str | None = None
    reparse_markerless: bool = False


class SyncMarkerDiagnostics(BaseModel):
    """Marker provenance diagnostics for compiled tender text."""

    compiled_master_text_length: int = 0
    compiled_file_marker_count: int = 0
    compiled_page_marker_count: int = 0
    documents_total: int = 0
    documents_parsed: int = 0
    documents_markerized: int = 0
    documents_markerless: int = 0


class SyncStatusResponse(BaseModel):
    """Canonical sync status payload for a tender."""

    state: str
    progress: int
    docs_parsed: int
    error: str | None = None
    diagnostics: SyncMarkerDiagnostics | None = None


class TestScrapeRequest(BaseModel):
    """Request body for test-scrape endpoint."""
    url: str


class TestScrapeResponse(BaseModel):
    """Response for test-scrape endpoint."""
    status: str
    url: str
    documents: list[dict]
    count: int
    message: str


class AnalyzeTenderResponse(BaseModel):
    """Response payload for analyze-tender endpoint.

    Maintains backward compatibility with the frontend contract
    (requirements + evaluation) while adding the new hybrid
    compliance result and strategic bidding intelligence.
    """

    analysis_id: str
    requirements: ExtractedTenderRequirements
    evaluation: DynamicComplianceResult
    hybrid_compliance: HybridComplianceResult | None = None
    strategy_intelligence: TenderStrategyIntelligence | None = None
    content_hash: str
    override_seal: str | None = None
    evidence_validation: dict[str, Any] | None = None
    analysis_warnings: list[str] = Field(default_factory=list)
    coverage_metadata: dict[str, Any] | None = None
    analysis_status: str = "completed"
    extraction_error: str | None = None


class TenderCompiledTextResponse(BaseModel):
    tender_id: UUID
    compiled_master_text: str | None = None


class RiskOverrideRequest(BaseModel):
    """Request payload for cryptographic liability handshake.

    Justification is mandatory — the user must state why they are
    overriding the system flag to complete the liability handshake.
    """

    node_id: UUID
    analysis_id: UUID
    justification: str = Field(
        ...,
        min_length=10,
        description=(
            "Mandatory justification for overriding the system flag. "
            "Must explain why the user possesses offline context "
            "(e.g. physical waiver) that the AI cannot see."
        ),
    )


class RiskOverrideStatusResponse(BaseModel):
    """Persisted override status for a tender and current user."""

    tender_id: UUID
    accepted_node_ids: list[str]
    override_seal: str | None = None


DocumentSummary = dict[str, int | bool | str | None]

AVAILABLE_DOCUMENT_STATUSES = {"available", "downloaded"}
UNAVAILABLE_LEGACY_DOCUMENT_STATUSES = {
    "error",
    "metadata_only",
    "failed",
    "processing",
}


def _normalize_tender_source_filter(source_system: str | None) -> str | None:
    if not source_system:
        return None
    normalized_source = source_system.strip().casefold().replace("-", "_")
    if normalized_source in {"", "all", "all_sources"}:
        return None
    if normalized_source == "worldbank":
        normalized_source = "world_bank"
    if normalized_source not in {"uzex", "world_bank", "adb"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported source_system",
        )
    return normalized_source


def _document_status_from_summary(summary: DocumentSummary) -> str:
    if int(summary.get("available_document_count") or 0) > 0:
        return "documents_available"
    if int(summary.get("metadata_only_document_count") or 0) > 0:
        return "metadata_only"
    if bool(summary.get("processing")):
        return "processing"
    if int(summary.get("failed_document_count") or 0) > 0:
        return "failed"
    return "no_documents_found"


def _compliance_unavailable_reason(
    *,
    source_system: str,
    has_compiled_text: bool,
    document_status: str,
) -> str | None:
    if has_compiled_text and document_status == "documents_available":
        return None
    if source_system == "adb" and document_status == "metadata_only":
        return "PDF notice discovered — download/parse required before analysis."
    return "Document ingestion required before analysis."


def _empty_tender_summary(*, has_compiled_text: bool = False) -> DocumentSummary:
    return {
        "has_compiled_text": has_compiled_text,
        "document_status": "no_documents_found",
        "document_count": 0,
        "available_document_count": 0,
        "metadata_only_document_count": 0,
        "failed_document_count": 0,
        "processing": False,
    }


async def _batched_tender_summaries(
    *,
    db: AsyncSession,
    tender_ids: list[UUID],
) -> dict[UUID, DocumentSummary]:
    if not tender_ids:
        return {}

    summaries = {
        tender_id: _empty_tender_summary()
        for tender_id in tender_ids
    }

    text_rows = await db.execute(
        select(
            Tender.id,
            (
                Tender.compiled_master_text.is_not(None)
                & (func.length(func.trim(Tender.compiled_master_text)) > 0)
            ).label("has_compiled_text"),
        ).where(Tender.id.in_(tender_ids))
    )
    for tender_id, has_compiled_text in text_rows.all():
        summaries[tender_id]["has_compiled_text"] = bool(has_compiled_text)

    lowered_status = func.lower(
        func.coalesce(func.nullif(func.trim(TenderDocument.download_status), ""), "")
    )
    storage_path_present = (
        TenderDocument.storage_path.is_not(None)
        & (func.length(func.trim(TenderDocument.storage_path)) > 0)
    )
    file_url_present = (
        TenderDocument.file_url.is_not(None)
        & (func.length(func.trim(TenderDocument.file_url)) > 0)
    )
    available_status_condition = lowered_status.in_(tuple(AVAILABLE_DOCUMENT_STATUSES))
    legacy_uzex_available_condition = (
        (Tender.source_system == "uzex")
        & file_url_present
        & (~lowered_status.in_(tuple(UNAVAILABLE_LEGACY_DOCUMENT_STATUSES)))
    )
    available_condition = (
        available_status_condition
        | storage_path_present
        | legacy_uzex_available_condition
    )
    metadata_only_condition = lowered_status == "metadata_only"
    failed_condition = lowered_status == "failed"
    processing_condition = lowered_status == "processing"

    document_rows = await db.execute(
        select(
            TenderDocument.tender_id,
            func.count(TenderDocument.id).label("document_count"),
            func.sum(case((available_condition, 1), else_=0)).label(
                "available_document_count"
            ),
            func.sum(case((metadata_only_condition, 1), else_=0)).label(
                "metadata_only_document_count"
            ),
            func.sum(case((failed_condition, 1), else_=0)).label(
                "failed_document_count"
            ),
            func.sum(case((processing_condition, 1), else_=0)).label(
                "processing_document_count"
            ),
        )
        .join(Tender, TenderDocument.tender_id == Tender.id)
        .where(TenderDocument.tender_id.in_(tender_ids))
        .group_by(TenderDocument.tender_id)
    )
    for row in document_rows.mappings().all():
        tender_id = row["tender_id"]
        summaries[tender_id].update(
            document_count=int(row["document_count"] or 0),
            available_document_count=int(row["available_document_count"] or 0),
            metadata_only_document_count=int(row["metadata_only_document_count"] or 0),
            failed_document_count=int(row["failed_document_count"] or 0),
            processing=bool(row["processing_document_count"] or 0),
        )

    for summary in summaries.values():
        summary["document_status"] = _document_status_from_summary(summary)

    return summaries


async def _single_tender_summary(
    *,
    db: AsyncSession,
    tender_id: UUID,
) -> DocumentSummary:
    return (
        await _batched_tender_summaries(db=db, tender_ids=[tender_id])
    ).get(tender_id, _empty_tender_summary())


def _safe_source_notice_url(source_url: str | None) -> str | None:
    candidate = (source_url or "").strip()
    if not candidate:
        return None
    path = urlparse(candidate).path.lower()
    if Path(path).suffix in {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".zip",
        ".rar",
        ".7z",
    }:
        return None
    return candidate


def _price_fields(tender: Tender) -> tuple[float | None, str | None, str | None]:
    try:
        amount = float(tender.budget or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if amount <= 0:
        return None, None, None

    currency = (tender.currency or "").strip().upper() or None
    amount_display = f"{amount:,.2f}".rstrip("0").rstrip(".")
    price_display = (
        f"{amount_display} {currency}" if currency else amount_display
    )
    return amount, currency, price_display


def _parse_uzex_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def _uzex_trade_list_date_map(
    external_ids: set[str],
) -> dict[str, tuple[datetime | None, datetime | None]]:
    if not external_ids:
        return {}

    date_map: dict[str, tuple[datetime | None, datetime | None]] = {}
    payload_base = {
        "From": 1,
        "To": 1000,
        "System_Id": 0,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://apietender.uzex.uz/api/common/TradeList",
            json={**payload_base, "TypeId": UZEX_ENTERPRISE_TYPE_ID},
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            return date_map
        for row in rows:
            if not isinstance(row, dict):
                continue
            external_id = str(row.get("id") or "").strip()
            if external_id not in external_ids:
                continue
            date_map[external_id] = (
                _parse_uzex_datetime(row.get("start_date")),
                _parse_uzex_datetime(row.get("end_date")),
            )
    return date_map


async def _apply_live_uzex_dates(tenders: list[Tender]) -> None:
    external_ids = {
        tender.external_id
        for tender in tenders
        if tender.source_system == "uzex" and tender.external_id
    }
    if not external_ids:
        return
    try:
        date_map = await _uzex_trade_list_date_map(external_ids)
    except Exception:
        logger.exception("Failed to enrich UzEx publication/deadline dates")
        return

    for tender in tenders:
        if tender.source_system != "uzex":
            continue
        publication_date, deadline = date_map.get(tender.external_id, (None, None))
        if publication_date is not None:
            tender.publication_date = publication_date
        if deadline is not None:
            tender.deadline = deadline


def _serialize_tender(
    tender: Tender,
    *,
    summary: DocumentSummary | None = None,
) -> TenderResponse:
    payload = TenderResponse.model_validate(tender)
    payload.source_url = _safe_source_notice_url(payload.source_url)
    (
        payload.price_amount,
        payload.price_currency,
        payload.price_display,
    ) = _price_fields(tender)
    summary = summary or _empty_tender_summary()
    payload.has_compiled_text = bool(summary.get("has_compiled_text"))
    payload.document_status = str(
        summary.get("document_status") or "no_documents_found"
    )
    payload.document_count = int(summary.get("document_count") or 0)
    payload.available_document_count = int(
        summary.get("available_document_count") or 0
    )
    payload.metadata_only_document_count = int(
        summary.get("metadata_only_document_count") or 0
    )
    payload.failed_document_count = int(summary.get("failed_document_count") or 0)
    unavailable_reason = _compliance_unavailable_reason(
        source_system=payload.source_system,
        has_compiled_text=payload.has_compiled_text,
        document_status=payload.document_status,
    )
    payload.compliance_analysis_available = unavailable_reason is None
    payload.compliance_unavailable_reason = unavailable_reason
    return payload


def _build_company_vault_response(profile: CompanyProfile) -> CompanyVaultResponse:
    certifications = [
        CertificationItem.model_validate(item)
        for item in sorted(
            profile.certifications,
            key=lambda x: (x.issue_date, x.expiry_date, x.cert_type),
        )
    ]
    licenses = [
        LicenseItem.model_validate(item)
        for item in sorted(
            profile.licenses,
            key=lambda x: x.license_name.lower(),
        )
    ]
    financial_history = [
        FinancialHistoryItem.model_validate(item)
        for item in sorted(
            profile.financial_history,
            key=lambda x: x.year,
        )
    ]

    return CompanyVaultResponse(
        id=profile.id,
        user_id=profile.user_id,
        company_name=profile.company_name,
        director_name=profile.director_name,
        address=profile.address,
        phone_contact=profile.phone_contact,
        bank_name=profile.bank_name,
        mfo=profile.mfo,
        account_number=profile.account_number,
        inn=profile.inn,
        certifications=certifications,
        licenses=licenses,
        financial_history=financial_history,
    )


def _is_vault_completely_empty(vault: CompanyVaultResponse) -> bool:
    root_values = [
        vault.company_name,
        vault.director_name,
        vault.address,
        vault.phone_contact,
        vault.bank_name,
        vault.mfo,
        vault.account_number,
        vault.inn,
    ]
    root_is_empty = all(not (value and value.strip()) for value in root_values)
    return (
        root_is_empty
        and not vault.certifications
        and not vault.licenses
        and not vault.financial_history
    )


def _vault_cache_payload(profile: CompanyProfile) -> dict[str, Any]:
    """Return stable Company Vault values that affect compliance matching."""
    return {
        "certifications": [
            {
                "cert_type": item.cert_type,
                "issue_date": item.issue_date.isoformat(),
                "expiry_date": item.expiry_date.isoformat(),
            }
            for item in sorted(
                profile.certifications,
                key=lambda cert: (
                    cert.cert_type.casefold(),
                    cert.issue_date,
                    cert.expiry_date,
                ),
            )
        ],
        "licenses": [
            {
                "license_name": item.license_name,
                "is_active": item.is_active,
            }
            for item in sorted(
                profile.licenses,
                key=lambda license_item: (
                    license_item.license_name.casefold(),
                    license_item.is_active,
                ),
            )
        ],
        "financial_history": [
            {
                "year": item.year,
                "turnover_uzs": item.turnover_uzs,
            }
            for item in sorted(
                profile.financial_history,
                key=lambda history_item: history_item.year,
            )
        ],
    }


def _taxonomy_fingerprint_payload(taxonomy_nodes: list[TaxonomyNode]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(node.id),
            "category": node.category.value if hasattr(node.category, "value") else str(node.category),
            "name": node.name,
            "impact_weight": node.impact_weight,
            "is_fatal": node.is_fatal,
        }
        for node in sorted(taxonomy_nodes, key=lambda item: str(item.id))
    ]


def _document_fingerprint_payload(doc: TenderDocument) -> dict[str, Any]:
    response = _document_response(doc)
    parsed_text = doc.parsed_text or ""
    counts = marker_counts(parsed_text)
    parsed_source_filenames_canonical = [
        canonical
        for canonical in (
            canonical_source_filename(filename)
            for filename in response.parsed_source_filenames
        )
        if canonical
    ]
    archive_inner_filenames_canonical = [
        canonical
        for canonical in (
            canonical_source_filename(filename)
            for filename in response.archive_inner_filenames
        )
        if canonical
    ]
    return {
        "document_id": str(doc.id),
        "display_name": safe_basename(response.display_name),
        "display_name_canonical": canonical_source_filename(response.display_name),
        "file_type": doc.file_type,
        "file_size": doc.file_size,
        "parsed_source_filenames": response.parsed_source_filenames,
        "parsed_source_filenames_canonical": parsed_source_filenames_canonical,
        "archive_inner_filenames": response.archive_inner_filenames,
        "archive_inner_filenames_canonical": archive_inner_filenames_canonical,
        "parsed_text_length": len(parsed_text),
        "parsed_text_sha256": sha256_text(parsed_text),
        "parsed_text_canonical_marker_sha256": canonical_marker_text_sha256(
            parsed_text
        ),
        **counts,
    }


def _document_fingerprint_sort_key(fingerprint: dict[str, Any]) -> tuple[Any, ...]:
    return stable_document_order_key(
        source_filename=fingerprint.get("display_name_canonical")
        or fingerprint.get("display_name"),
        file_type=fingerprint.get("file_type"),
        file_size=fingerprint.get("file_size"),
        parsed_text_canonical_marker_sha256=fingerprint.get(
            "parsed_text_canonical_marker_sha256"
        ),
        document_id=fingerprint.get("document_id"),
    )


def _document_order_fingerprint_payload(
    document_fingerprints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "display_name_canonical": item.get("display_name_canonical"),
            "parsed_source_filenames_canonical": item.get(
                "parsed_source_filenames_canonical"
            )
            or [],
            "archive_inner_filenames_canonical": item.get(
                "archive_inner_filenames_canonical"
            )
            or [],
            "file_type": item.get("file_type"),
            "file_size": item.get("file_size"),
            "parsed_text_canonical_marker_sha256": item.get(
                "parsed_text_canonical_marker_sha256"
            ),
        }
        for item in document_fingerprints
    ]


def _source_chunk_index_by_fingerprint(requirements: list[Any]) -> dict[str, int | None]:
    mapping: dict[str, int | None] = {}
    for req in requirements:
        payload = req.model_dump(mode="json") if hasattr(req, "model_dump") else dict(req)
        mapping[requirement_fingerprint(payload)] = payload.get("source_chunk_index")
    return mapping


def _build_reproducibility_snapshot(
    *,
    tender: Tender,
    tender_text: str,
    documents: list[TenderDocument],
    profile: CompanyProfile,
    taxonomy_nodes: list[TaxonomyNode],
    coverage_metadata: dict[str, Any],
    hybrid_compliance: dict[str, Any],
    evidence_validation: dict[str, Any],
) -> dict[str, Any]:
    source_system = tender.source_system
    input_counts = marker_counts(tender_text)
    vault_payload = _vault_cache_payload(profile)
    taxonomy_payload = _taxonomy_fingerprint_payload(taxonomy_nodes)
    extractor_mode = (
        str(coverage_metadata.get("extractor_mode"))
        if isinstance(coverage_metadata, dict) and coverage_metadata.get("extractor_mode")
        else None
    )

    hybrid_route_summary = requirement_route_records(hybrid_compliance)
    evidence_route_summary = evidence_validation_route_records(evidence_validation)
    document_fingerprints = sorted(
        (_document_fingerprint_payload(doc) for doc in documents),
        key=_document_fingerprint_sort_key,
    )

    return {
        "tender_identity": {
            "source_system": source_system,
            "external_id": tender.external_id,
            "tender_id": str(tender.id),
            "canonical_source_key": tender.canonical_source_key,
        },
        "input_fingerprints": {
            "compiled_text_length": len(tender_text),
            "compiled_text_sha256": sha256_text(tender_text),
            **input_counts,
            "document_count": len(documents),
            "document_order_fingerprint": stable_json_sha256(
                _document_order_fingerprint_payload(document_fingerprints)
            ),
            "ordered_canonical_filenames": [
                item.get("display_name_canonical") for item in document_fingerprints
            ],
            "document_fingerprints": document_fingerprints,
        },
        "engine_metadata": engine_metadata(
            extractor_schema_version=EXTRACTOR_SCHEMA_VERSION,
            requirement_model_name=REQUIREMENT_MODEL_NAME,
            temperature=0.0,
            max_payload_chars=MAX_PAYLOAD_CHARS,
            extractor_mode=extractor_mode,
        ),
        "coverage": {
            "coverage_metadata": coverage_metadata,
            "chunk_count": coverage_metadata.get("chunk_count"),
            "chunks_processed": coverage_metadata.get("chunks_processed"),
            "chunks_failed": coverage_metadata.get("chunks_failed"),
            "coverage_status": coverage_metadata.get("coverage_status"),
            "coverage_warnings": coverage_metadata.get("coverage_warnings") or [],
        },
        "vault_fingerprint": {
            "company_profile_id": str(profile.id),
            "certification_count": len(profile.certifications),
            "license_count": len(profile.licenses),
            "financial_history_count": len(profile.financial_history),
            "vault_sha256": stable_json_sha256(vault_payload),
        },
        "taxonomy_fingerprint": {
            "taxonomy_count": len(taxonomy_payload),
            "taxonomy_sha256": stable_json_sha256(taxonomy_payload),
        },
        "output_summary": {
            "verdict_status": hybrid_compliance.get("verdict_status"),
            "failed_count": hybrid_compliance.get("failed_count"),
            "manual_review_count": hybrid_compliance.get("manual_review_count"),
            "satisfied_count": hybrid_compliance.get("satisfied_count"),
            "recorded_obligations_count": hybrid_compliance.get("recorded_obligations_count"),
            "skipped_optional_count": hybrid_compliance.get("skipped_optional_count"),
        },
        "requirement_route_summary": [
            *hybrid_route_summary,
            *evidence_route_summary,
        ],
    }


def _analysis_owner_key(
    *,
    current_user: User,
    profile: CompanyProfile | None,
) -> str:
    """
    Build a tenant-safe ownership key for TenderAnalysis rows.

    TenderAnalysis does not currently store a user_id, so we persist and query
    by this deterministic key to avoid cross-tenant collisions.
    """
    profile_token = str(profile.id) if profile is not None else "no-profile"
    return f"{current_user.id}:{profile_token}"


def _legacy_analysis_owner_names(
    *,
    current_user: User,
    profile: CompanyProfile | None,
) -> list[str]:
    """
    Legacy TenderAnalysis rows stored the display company name instead of a
    tenant-safe owner key. Restrict compatibility to names from the current
    authenticated user context.
    """
    candidates = [
        profile.company_name if profile is not None else None,
        current_user.company_name,
        current_user.name,
    ]
    names: list[str] = []
    for candidate in candidates:
        name = str(candidate).strip() if candidate else ""
        if name and name not in names:
            names.append(name)
    return names


def _analysis_owner_candidates(
    *,
    current_user: User,
    profile: CompanyProfile | None,
) -> list[str]:
    owner_key = _analysis_owner_key(current_user=current_user, profile=profile)
    return [
        owner_key,
        *[
            name
            for name in _legacy_analysis_owner_names(
                current_user=current_user,
                profile=profile,
            )
            if name != owner_key
        ],
    ]


def _claim_legacy_analysis_owner(
    *,
    analysis: TenderAnalysis,
    owner_key: str,
    legacy_owner_names: list[str],
) -> None:
    if analysis.company_name == owner_key or analysis.company_name not in legacy_owner_names:
        return

    analysis_data = dict(analysis.analysis_json or {})
    analysis_data.setdefault("tenant_company_name", analysis.company_name)
    analysis.company_name = owner_key
    analysis.analysis_json = analysis_data


def _extract_remote_file_path(file_url: str) -> str:
    raw_value = (file_url or "").strip()
    if not raw_value:
        return ""

    parsed = urlparse(raw_value)
    query_path = parse_qs(parsed.query).get("path", [None])[0]
    if query_path:
        return unquote(query_path).strip()

    if parsed.scheme and parsed.netloc:
        return unquote(parsed.path).strip()

    return unquote(parsed.path or raw_value).strip()


def _guess_download_content_type(*, filename: str, file_type: str | None = None) -> str:
    extension = (file_type or Path(filename).suffix.lstrip(".")).lower()
    content_types = {
        "pdf": "application/pdf",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xls": "application/vnd.ms-excel",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "zip": "application/zip",
        "rar": "application/vnd.rar",
        "7z": "application/x-7z-compressed",
        "tar": "application/x-tar",
        "gz": "application/gzip",
    }
    return content_types.get(extension, "application/octet-stream")


def _safe_content_disposition(disposition: str, filename: str) -> str:
    """Build a Content-Disposition header that is safe for non-ASCII filenames.

    Uses RFC 5987 ``filename*=UTF-8''...`` for the real name and an ASCII-safe
    ``filename=`` fallback so every browser gets a usable download name.
    """
    try:
        filename.encode("ascii")
        return f'{disposition}; filename="{filename}"'
    except UnicodeEncodeError:
        ascii_fallback = filename.encode("ascii", errors="replace").decode("ascii")
        utf8_quoted = quote(filename, safe="")
        return (
            f'{disposition}; filename="{ascii_fallback}"; '
            f"filename*=UTF-8''{utf8_quoted}"
        )


def _stored_download_name(storage_path: str) -> str:
    stored_name = Path(storage_path).name
    prefix, _, remainder = stored_name.partition("_")
    if len(prefix) == 32 and remainder:
        return remainder
    return stored_name or "document.bin"


_TRACE_FILE_MARKER_RE = re.compile(r"\[\[FILE:\s*([^\]\n]+?)\s*\]\]")


def _filename_from_document_url(file_url: str) -> str | None:
    file_path = _extract_remote_file_path(file_url)
    filename = Path(file_path).name if file_path else ""
    return filename or None


def _has_filename_extension(filename: str | None) -> bool:
    return bool(filename and Path(filename).suffix)


def _is_archive_filename(filename: str | None) -> bool:
    return (Path(filename or "").suffix.lower().lstrip(".") in {"zip", "rar", "7z", "tar", "gz"})


def _is_archive_document(doc: TenderDocument, *, display_name: str | None = None) -> bool:
    file_type = (doc.file_type or "").lower().strip().lstrip(".")
    return file_type in {"zip", "rar", "7z", "tar", "gz"} or _is_archive_filename(display_name)


def _parsed_source_filenames(parsed_text: str | None) -> list[str]:
    filenames: list[str] = []
    seen: set[str] = set()

    for match in _TRACE_FILE_MARKER_RE.finditer(parsed_text or ""):
        filename = match.group(1).strip()
        key = filename.casefold()
        if filename and key not in seen:
            seen.add(key)
            filenames.append(filename)

    return filenames


def _normalized_document_download_status(doc: TenderDocument) -> str:
    return (doc.download_status or "").strip().casefold()


def _document_has_storage_path(doc: TenderDocument) -> bool:
    return bool((doc.storage_path or "").strip())


def _legacy_uzex_document_can_use_plasma_route(
    doc: TenderDocument,
    *,
    source_system: str | None,
) -> bool:
    if (source_system or "").strip().casefold() != "uzex":
        return False
    if _normalized_document_download_status(doc) in UNAVAILABLE_LEGACY_DOCUMENT_STATUSES:
        return False
    return bool(_extract_remote_file_path(doc.file_url))


def _document_download_status(
    doc: TenderDocument,
    *,
    source_system: str | None = None,
) -> str:
    raw_status = _normalized_document_download_status(doc)
    if raw_status in AVAILABLE_DOCUMENT_STATUSES:
        return "available"
    if _document_has_storage_path(doc):
        return "available"
    if _legacy_uzex_document_can_use_plasma_route(
        doc,
        source_system=source_system,
    ):
        return "available"
    if raw_status == "metadata_only":
        return "metadata_only"
    if raw_status == "failed":
        return "failed"
    if raw_status == "processing":
        return "processing"
    return "metadata_only"


def _document_response(
    doc: TenderDocument,
    *,
    source_system: str | None = None,
) -> TenderDocumentResponse:
    original_filename = _filename_from_document_url(
        doc.source_document_url or doc.file_url
    )
    storage_filename = _stored_download_name(doc.storage_path) if doc.storage_path else None
    display_name = (
        storage_filename if _has_filename_extension(storage_filename) else None
    ) or original_filename or storage_filename or (
        f"document.{doc.file_type}" if doc.file_type else "document"
    )
    parsed_source_filenames = _parsed_source_filenames(doc.parsed_text)
    parent_names = {
        name.casefold()
        for name in (display_name, original_filename, storage_filename)
        if name
    }
    archive_inner_filenames = [
        filename
        for filename in parsed_source_filenames
        if _is_archive_document(doc, display_name=display_name)
        and filename.casefold() not in parent_names
    ]

    return TenderDocumentResponse(
        id=doc.id,
        file_type=doc.file_type,
        display_name=display_name,
        download_url=f"/api/v1/tenders/documents/{doc.id}/download",
        download_status=_document_download_status(doc, source_system=source_system),
        original_filename=original_filename,
        storage_filename=storage_filename,
        parsed_source_filenames=parsed_source_filenames,
        archive_inner_filenames=archive_inner_filenames,
        file_size=doc.file_size,
        created_at=doc.created_at,
    )


def _split_validated_requirements(
    requirements: list[Any],
) -> tuple[list[Any], list[Any], list[Any]]:
    accepted = [
        req
        for req in requirements
        if req.validation_status == EvidenceValidationStatus.ACCEPTED
    ]
    needs_review = [
        req
        for req in requirements
        if req.validation_status == EvidenceValidationStatus.NEEDS_REVIEW
    ]
    rejected = [
        req
        for req in requirements
        if req.validation_status == EvidenceValidationStatus.REJECTED
    ]
    return accepted, needs_review, rejected


def _evidence_validation_payload(
    *,
    all_requirements: list[Any],
    accepted: list[Any],
    needs_review: list[Any],
    rejected: list[Any],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "summary": {
            "total_extracted": len(all_requirements),
            "accepted": len(accepted),
            "needs_review": len(needs_review),
            "rejected": len(rejected),
            "scope_needs_review": sum(
                1
                for req in all_requirements
                if req.scope_review_status == ScopeReviewStatus.NEEDS_REVIEW
            ),
            "bid_affecting": sum(
                1
                for req in all_requirements
                if req.affects_bid_eligibility
            ),
        },
        "warnings": warnings,
        "accepted_requirements": [
            req.model_dump(mode="json") for req in accepted
        ],
        "needs_review_requirements": [
            req.model_dump(mode="json") for req in needs_review
        ],
        # Debug/admin visibility only. These are intentionally not fed into the
        # normal compliance result.
        "rejected_requirements": [
            req.model_dump(mode="json") for req in rejected
        ],
    }


def _public_evidence_validation_payload(
    evidence_validation: dict[str, Any] | None,
    *,
    include_debug: bool = False,
) -> dict[str, Any] | None:
    if evidence_validation is None:
        return None
    payload = sanitize_internal_requirement_diagnostics(dict(evidence_validation))
    if not include_debug:
        payload.pop("rejected_requirements", None)
    return payload


def _manual_review_detail_from_validation(req: Any) -> RequirementMatchDetail:
    category = req.category.value if hasattr(req.category, "value") else str(req.category)
    return RequirementMatchDetail(
        category=category,
        headline=req.headline,
        source_filename=req.source_filename,
        source_page=req.source_page,
        exact_quote=req.exact_quote,
        raw_text_snippet=req.exact_quote,
        requirement_type=category,
        is_dealbreaker=bool(req.is_dealbreaker),
        confidence_score=1.0,
        validation_status=req.validation_status.value,
        validation_reason=req.validation_reason,
        source_verified=req.source_verified,
        requirement_scope=req.requirement_scope.value,
        scope_review_status=req.scope_review_status.value,
        affects_bid_eligibility=req.affects_bid_eligibility,
        eligibility_reason=req.eligibility_reason,
        verdict=MatchVerdict.NEEDS_MANUAL_REVIEW,
        match_method=MatchMethod.SKIPPED,
        matched_credential=None,
        taxonomy_node_id=None,
        parent_section_header=None,
        reason=(
            "Evidence validation requires manual review: "
            f"{req.validation_reason}"
        ),
    )


def _serialize_cached_analysis_response(
    cached: TenderAnalysis,
    *,
    content_hash: str,
    extra_warnings: list[str] | None = None,
    include_debug: bool = False,
) -> dict[str, Any]:
    cached_data = cached.analysis_json or {}
    cached_reqs = ExtractedTenderRequirements.model_validate(
        cached_data.get("requirements", {})
    )
    cached_eval = DynamicComplianceResult.model_validate(
        cached_data.get("evaluation", {})
    )
    cached_hybrid = None
    if "hybrid_compliance" in cached_data:
        try:
            public_hybrid = sanitize_internal_requirement_diagnostics(
                cached_data["hybrid_compliance"]
            )
            cached_hybrid = HybridComplianceResult.model_validate(
                public_hybrid
            )
        except (ValidationError, KeyError):
            pass

    cached_strategy = None
    if "strategy_intelligence" in cached_data:
        try:
            cached_strategy = TenderStrategyIntelligence.model_validate(
                cached_data["strategy_intelligence"]
            )
        except (ValidationError, KeyError):
            pass

    analysis_warnings = list(cached_data.get("analysis_warnings") or [])
    if extra_warnings:
        analysis_warnings.extend(extra_warnings)

    return {
        "analysis_id": str(cached.id),
        "requirements": cached_reqs,
        "evaluation": cached_eval,
        "hybrid_compliance": cached_hybrid,
        "strategy_intelligence": cached_strategy,
        "content_hash": content_hash,
        "override_seal": cached.override_seal,
        "evidence_validation": _public_evidence_validation_payload(
            cached_data.get("evidence_validation"),
            include_debug=include_debug,
        ),
        "analysis_warnings": analysis_warnings,
        "coverage_metadata": cached_data.get("coverage_metadata"),
        "analysis_status": cached_data.get("analysis_status", "completed"),
        "extraction_error": cached_data.get("extraction_error"),
    }


@router.post("/{tender_id}/analyze", response_model=AnalyzeTenderResponse)
async def analyze_tender(
    tender_id: UUID,
    force: bool = False,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Analyze pre-scraped tender text using the Hybrid Compliance Engine.

    Pipeline:
        1. Extract requirements via Gemini (new structured extractor).
        2. Load taxonomy + credentials for UUID matching.
        3. Run hybrid evaluation: UUID Strike -> Token Fallback -> Manual Guard.
        4. Bridge results back to legacy frontend contract.
        5. Persist analysis and return.

    Returns cached analysis when content hash matches, unless ``force=True``.
    """
    await _ensure_tender_access(
        db=session,
        tender_id=tender_id,
        user_id=current_user.id,
        current_user=current_user,
        allow_operator=True,
    )

    try:
        result = await session.execute(select(Tender).where(Tender.id == tender_id))
        tender = result.scalar_one_or_none()
    except SQLAlchemyError as exc:
        logger.exception("Failed to query tender record")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database query failed: {exc}",
        ) from exc

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )

    tender_text = (tender.compiled_master_text or "").strip()
    if not tender_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tender has no compiled master text. Documents may not be parsed yet.",
        )

    try:
        try:
            profile = await get_profile_for_compliance_match(
                db=session,
                user_id=current_user.id,
            )
        except ProfileNotFoundException:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Company vault is empty. Please fill out your company settings first.",
            )

        company_vault = _build_company_vault_response(profile)
        if _is_vault_completely_empty(company_vault):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Company vault is empty. Please fill out your company settings first.",
            )

        display_company_name = str(
            company_vault.company_name or current_user.name or "Unknown Company"
        )
        analysis_owner_key = _analysis_owner_key(
            current_user=current_user,
            profile=profile,
        )
        analysis_owner_names = _analysis_owner_candidates(
            current_user=current_user,
            profile=profile,
        )

        taxonomy_query = select(TaxonomyNode)
        taxonomy_is_active = getattr(TaxonomyNode, "is_active", None)
        if taxonomy_is_active is not None:
            taxonomy_query = taxonomy_query.where(taxonomy_is_active.is_(True))
        taxonomy_result = await session.execute(
            taxonomy_query.order_by(TaxonomyNode.name.asc())
        )
        taxonomy_nodes = taxonomy_result.scalars().all()

        cred_result = await session.execute(
            select(CompanyCredential.taxonomy_node_id).where(
                CompanyCredential.company_profile_id == profile.id
            )
        )
        credential_uuids: set[str] = {
            str(row[0]) for row in cred_result.all()
        }

        taxonomy_lookup: dict[str, TaxNodeInfo] = {
            str(node.id): TaxNodeInfo(
                name=node.name,
                impact_weight=node.impact_weight,
                is_fatal=node.is_fatal,
            )
            for node in taxonomy_nodes
        }

        documents_result = await session.execute(
            select(TenderDocument).where(TenderDocument.tender_id == tender.id)
        )
        tender_documents = documents_result.scalars().all()

        sorted_cred_str = ",".join(sorted(credential_uuids))
        sorted_tax_str = ",".join(sorted(taxonomy_lookup.keys()))
        vault_cache_str = json.dumps(
            _vault_cache_payload(profile),
            sort_keys=True,
            separators=(",", ":"),
        )
        hash_input = (
            f"{EXTRACTOR_SCHEMA_VERSION}|{tender_text}|"
            f"{sorted_cred_str}|{sorted_tax_str}|{vault_cache_str}"
        )
        current_content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

        latest_cached: TenderAnalysis | None = None
        if not force:
            cached_result = await session.execute(
                select(TenderAnalysis)
                .where(
                    TenderAnalysis.tender_id == tender_id,
                    TenderAnalysis.company_name.in_(analysis_owner_names),
                )
                .order_by(TenderAnalysis.created_at.desc())
                .limit(1)
            )
            latest_cached = cached_result.scalar_one_or_none()

            if latest_cached is not None and latest_cached.content_hash == current_content_hash:
                _claim_legacy_analysis_owner(
                    analysis=latest_cached,
                    owner_key=analysis_owner_key,
                    legacy_owner_names=_legacy_analysis_owner_names(
                        current_user=current_user,
                        profile=profile,
                    ),
                )
                try:
                    logger.info(
                        "Returning cached analysis %s for tender %s (hash match)",
                        latest_cached.id,
                        tender_id,
                    )
                    return _serialize_cached_analysis_response(
                        latest_cached,
                        content_hash=current_content_hash,
                        include_debug=current_user.is_admin,
                    )
                except (ValidationError, KeyError):
                    logger.warning(
                        "Cached analysis %s has legacy schema; forcing fresh extraction",
                        latest_cached.id,
                    )

        # ── Concurrent Extraction: Compliance + Strategy ──────────
        # Both agents read the same input text with zero data dependency.
        # Strategy extraction is wrapped in fault isolation — a failure
        # must never block the compliance result.
        async def _safe_strategy_extraction() -> TenderStrategyIntelligence | None:
            try:
                return await extract_strategy_intelligence(tender_text)
            except Exception as strategy_exc:
                logger.warning(
                    "Strategy extraction failed (non-fatal, compliance unaffected): %s",
                    strategy_exc,
                )
                return None

        async def _safe_requirement_extraction() -> tuple[
            list[Any],
            dict[str, Any],
            list[dict[str, Any]],
            str | None,
        ]:
            try:
                extraction_result = await extract_requirements_with_coverage(
                    tender_text
                )
                coverage_metadata = extraction_result.coverage_metadata.model_dump(
                    mode="json"
                )
                artifacts_metadata = [
                    item.model_dump(mode="json")
                    for item in extraction_result.extraction_artifacts_metadata
                ]
                extraction_error = None
                if coverage_metadata.get("coverage_status") == "failed":
                    extraction_error = (
                        "Requirement extraction failed for all document sections."
                    )
                return (
                    extraction_result.requirements,
                    coverage_metadata,
                    artifacts_metadata,
                    extraction_error,
                )
            except Exception as extraction_exc:
                logger.exception(
                    "Requirement extraction failed for tender %s",
                    tender_id,
                )
                failed_coverage = build_failed_extraction_coverage(
                    tender_text,
                    error=f"{type(extraction_exc).__name__}: {extraction_exc}",
                )
                failed_artifacts = build_failed_extraction_artifacts_metadata(
                    tender_text,
                    error=f"{type(extraction_exc).__name__}: {extraction_exc}",
                )
                return (
                    [],
                    failed_coverage.model_dump(mode="json"),
                    [
                        item.model_dump(mode="json")
                        for item in failed_artifacts
                    ],
                    str(extraction_exc),
                )

        (
            (extracted_reqs, coverage_metadata, extraction_artifacts_metadata, extraction_error),
            strategy_result,
        ) = await asyncio.gather(
            _safe_requirement_extraction(),
            _safe_strategy_extraction(),
        )
        analysis_warnings = build_extraction_warnings(
            tender_text,
            coverage_metadata=coverage_metadata,
        )

        if extraction_error and latest_cached is not None:
            cached_data = latest_cached.analysis_json or {}
            if cached_data.get("analysis_status") != "failed":
                try:
                    return _serialize_cached_analysis_response(
                        latest_cached,
                        content_hash=latest_cached.content_hash or current_content_hash,
                        include_debug=current_user.is_admin,
                        extra_warnings=[
                            (
                                "Fresh compliance extraction failed; returning the "
                                f"previous analysis. Error: {extraction_error}"
                            )
                        ],
                    )
                except (ValidationError, KeyError):
                    logger.warning(
                        "Previous analysis %s could not be reused after extraction failure",
                        latest_cached.id,
                    )

        validated_reqs = classify_requirements_scope(
            validate_requirements_evidence(
                extracted_reqs,
                tender_text,
            ),
            tender_text,
        )
        accepted_reqs, needs_review_reqs, rejected_reqs = _split_validated_requirements(
            validated_reqs,
        )
        scope_review_reqs = [
            req
            for req in accepted_reqs
            if req.scope_review_status == ScopeReviewStatus.NEEDS_REVIEW
        ]
        evidence_validation = _evidence_validation_payload(
            all_requirements=validated_reqs,
            accepted=accepted_reqs,
            needs_review=needs_review_reqs,
            rejected=rejected_reqs,
            warnings=analysis_warnings,
        )

        coverage_status = str(coverage_metadata.get("coverage_status") or "")
        if extraction_error or coverage_status == "failed":
            analysis_status = "failed"
            analysis_warnings.append(
                "Requirement extraction failed; no new compliance requirements were confirmed."
            )
        elif (
            coverage_status == "partial"
            or needs_review_reqs
            or rejected_reqs
            or scope_review_reqs
            or analysis_warnings
        ):
            analysis_status = "needs_review"
        else:
            analysis_status = "completed"

        if extraction_error or coverage_status == "failed":
            hybrid_result = HybridComplianceResult(
                is_eligible=True,
                total_requirements=0,
                satisfied_count=0,
                failed_count=0,
                manual_review_count=0,
                skipped_optional_count=0,
                uuid_match_count=0,
                token_match_count=0,
                verdict_status=ComplianceVerdictStatus.NEEDS_REVIEW,
                failed_dealbreakers=[],
                manual_reviews_required=[],
                satisfied_requirements=[],
                status_message=(
                    "NEEDS REVIEW — Requirement extraction failed; manual "
                    "review is required before relying on this compliance result."
                ),
            )
        else:
            hybrid_result = evaluate_tender_compliance(
                extracted_reqs=accepted_reqs,
                profile=profile,
                credential_uuids=credential_uuids if credential_uuids else None,
                taxonomy_lookup=taxonomy_lookup if taxonomy_lookup else None,
            )

            validation_manual_reviews = [
                _manual_review_detail_from_validation(req)
                for req in needs_review_reqs
            ]
            if validation_manual_reviews:
                manual_reviews_required = [
                    *hybrid_result.manual_reviews_required,
                    *validation_manual_reviews,
                ]
                has_confirmed_items = bool(
                    hybrid_result.satisfied_requirements
                    or hybrid_result.recorded_obligations
                )
                if not hybrid_result.failed_dealbreakers and not has_confirmed_items:
                    verdict_status = ComplianceVerdictStatus.NEEDS_REVIEW
                    status_message = "No verified requirements yet — manual review required."
                elif not hybrid_result.failed_dealbreakers:
                    verdict_status = ComplianceVerdictStatus.ELIGIBLE_WITH_REVIEW
                    status_message = (
                        f"ELIGIBLE WITH REVIEW — {len(validation_manual_reviews)} "
                        f"requirement(s) could not be source-verified | "
                        f"{hybrid_result.status_message}"
                    )
                else:
                    verdict_status = hybrid_result.verdict_status
                    status_message = (
                        f"NEEDS REVIEW — {len(validation_manual_reviews)} "
                        f"requirement(s) could not be source-verified | "
                        f"{hybrid_result.status_message}"
                    )
                hybrid_result = hybrid_result.model_copy(
                    update={
                        "total_requirements": (
                            hybrid_result.total_requirements
                            + len(validation_manual_reviews)
                        ),
                        "manual_review_count": len(manual_reviews_required),
                        "manual_reviews_required": manual_reviews_required,
                        "verdict_status": verdict_status,
                        "status_message": status_message,
                    }
                )

        source_chunk_index_by_fingerprint = _source_chunk_index_by_fingerprint(
            validated_reqs
        )
        persisted_hybrid_compliance = annotate_hybrid_compliance(
            hybrid_result.model_dump(mode="json"),
            source_chunk_index_by_fingerprint=source_chunk_index_by_fingerprint,
        )
        final_bucket_by_fingerprint = {
            str(record["requirement_fingerprint"]): str(record["final_bucket"])
            for record in requirement_route_records(persisted_hybrid_compliance)
            if record.get("requirement_fingerprint") and record.get("final_bucket")
        }
        persisted_evidence_validation = annotate_evidence_validation(
            evidence_validation,
            final_bucket_by_fingerprint=final_bucket_by_fingerprint,
        )
        reproducibility_snapshot = _build_reproducibility_snapshot(
            tender=tender,
            tender_text=tender_text,
            documents=tender_documents,
            profile=profile,
            taxonomy_nodes=taxonomy_nodes,
            coverage_metadata=coverage_metadata,
            hybrid_compliance=persisted_hybrid_compliance,
            evidence_validation=persisted_evidence_validation,
        )

        from app.core.evaluator import MetRequirement, MissingRequirement

        legacy_met: list[MetRequirement] = []
        legacy_missing: list[MissingRequirement] = []
        legacy_unmapped: list[str] = []

        for detail in hybrid_result.satisfied_requirements:
            if detail.taxonomy_node_id:
                legacy_met.append(
                    MetRequirement(
                        uuid=detail.taxonomy_node_id,
                        name=detail.matched_credential or detail.taxonomy_node_id,
                    )
                )

        for detail in hybrid_result.failed_dealbreakers:
            if detail.taxonomy_node_id:
                node_info = taxonomy_lookup.get(detail.taxonomy_node_id)
                legacy_missing.append(
                    MissingRequirement(
                        uuid=detail.taxonomy_node_id,
                        name=node_info.name if node_info else detail.taxonomy_node_id,
                        impact_weight=node_info.impact_weight if node_info else 0,
                        is_fatal=node_info.is_fatal if node_info else True,
                    )
                )
            else:
                legacy_unmapped.append(detail.raw_text_snippet[:200])

        for detail in hybrid_result.manual_reviews_required:
            legacy_unmapped.append(detail.raw_text_snippet[:200])

        legacy_requirements = ExtractedTenderRequirements(
            mapped_requirement_uuids=[m.uuid for m in legacy_met] + [
                detail.taxonomy_node_id
                for detail in hybrid_result.failed_dealbreakers
                if detail.taxonomy_node_id
            ],
            unmapped_custom_requirements=legacy_unmapped,
        )

        legacy_evaluation = DynamicComplianceResult(
            is_compliant=hybrid_result.is_eligible,
            met_requirements=legacy_met,
            missing_requirements=legacy_missing,
            unmapped_requirements=legacy_unmapped,
            status_message=hybrid_result.status_message,
        )

        new_analysis = TenderAnalysis(
            tender_id=tender.id,
            tender_file_name=f"tender_{tender.external_id}",
            company_name=analysis_owner_key,
            raw_extracted_text=tender_text,
            analysis_json={
                "requirements": legacy_requirements.model_dump(mode="json"),
                "evaluation": legacy_evaluation.model_dump(mode="json"),
                "hybrid_compliance": persisted_hybrid_compliance,
                "evidence_validation": persisted_evidence_validation,
                "reproducibility_snapshot": reproducibility_snapshot,
                "extraction_artifacts_metadata": extraction_artifacts_metadata,
                "analysis_warnings": analysis_warnings,
                "coverage_metadata": coverage_metadata,
                "analysis_status": analysis_status,
                "extraction_error": extraction_error,
                "strategy_intelligence": (
                    strategy_result.model_dump(mode="json")
                    if strategy_result is not None
                    else None
                ),
                "tenant_company_name": display_company_name,
            },
            content_hash=current_content_hash,
        )
        session.add(new_analysis)
        await session.commit()
        await session.refresh(new_analysis)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.exception("Database integrity/persistence failure during tender analysis")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database write failed: {exc}",
        ) from exc
    except Exception as exc:
        await session.rollback()
        logger.exception("AI analysis failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI analysis failed: {exc}",
        ) from exc

    return {
        "analysis_id": str(new_analysis.id),
        "requirements": legacy_requirements,
        "evaluation": legacy_evaluation,
        "hybrid_compliance": hybrid_result,
        "strategy_intelligence": strategy_result,
        "content_hash": current_content_hash,
        "override_seal": None,
        "evidence_validation": _public_evidence_validation_payload(
            evidence_validation,
            include_debug=current_user.is_admin,
        ),
        "analysis_warnings": analysis_warnings,
        "coverage_metadata": coverage_metadata,
        "analysis_status": analysis_status,
        "extraction_error": extraction_error,
    }


@router.post("/test-scrape", response_model=TestScrapeResponse, dependencies=[Depends(require_admin)])
async def test_scrape(request: TestScrapeRequest) -> TestScrapeResponse:
    """
    Manual test endpoint to verify scraper on a specific URL.
    
    Use this to paste a known tender URL and see what documents the scraper finds.
    """
    try:
        scraper = UzExScraper(headless=True)
        docs = await scraper.scrape_tender_documents(request.url)
        
        return TestScrapeResponse(
            status="success",
            url=request.url,
            documents=docs,
            count=len(docs),
            message=f"Found {len(docs)} documents"
        )
    except Exception as e:
        logger.error(f"Test scrape failed: {e}")
        return TestScrapeResponse(
            status="error",
            url=request.url,
            documents=[],
            count=0,
            message=f"Scraper failed: {str(e)}"
        )


class ProxyDownloadRequest(BaseModel):
    """Request body for proxy-download endpoint."""
    tender_url: str  # e.g., https://etender.uzex.uz/lot/465790
    file_path: str   # e.g., /files/2025/12/23/xxx.pdf


@router.post("/proxy-download", dependencies=[Depends(require_admin)])
async def proxy_download(request: ProxyDownloadRequest):
    """
    Proxy download endpoint for UzEx files.
    
    UzEx uses POST with dynamic validation tokens, so we relay via Playwright.
    
    Returns the file as a downloadable response.
    """
    try:
        scraper = UzExScraper(headless=True)
        file_bytes, filename = await scraper.download_file(request.tender_url, request.file_path)
        if not file_bytes:
            raise HTTPException(status_code=502, detail="Document download returned an empty file.")
        content_type = _guess_download_content_type(filename=filename)
        
        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={"Content-Disposition": _safe_content_disposition("attachment", filename)}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Proxy download failed")
        raise HTTPException(
            status_code=502,
            detail="Document download failed. Please try again later.",
        ) from e


@router.get("/documents/{doc_id}/download")
async def download_document(
    doc_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Download a tender document by ID.
    
    Looks up the document in the database, gets its tender's source URL,
    and proxies the download through Playwright (needed because UzEx
    requires POST with dynamic validation tokens).
    
    Can be used as href in <a> tags or src in <iframe> for PDF preview.
    """
    # Look up document and its tender
    result = await db.execute(
        select(TenderDocument, Tender)
        .join(Tender, TenderDocument.tender_id == Tender.id)
        .where(TenderDocument.id == doc_id)
    )
    row = result.first()
    
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc, tender = row

    try:
        await _ensure_tender_access(
            db=db,
            tender_id=tender.id,
            user_id=current_user.id,
            current_user=current_user,
            allow_operator=True,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=403,
                detail="You do not have access to this document",
            ) from exc
        raise

    local_path = Path(doc.storage_path) if doc.storage_path else None

    if local_path and local_path.is_file():
        resolved_name = _stored_download_name(doc.storage_path)
        content_type = _guess_download_content_type(
            filename=resolved_name,
            file_type=doc.file_type,
        )
        disposition = "inline" if content_type == "application/pdf" else "attachment"
        return Response(
            content=local_path.read_bytes(),
            media_type=content_type,
            headers={"Content-Disposition": _safe_content_disposition(disposition, resolved_name)},
        )

    # ── Expected unavailable state: storage_path exists but the file is gone ──
    # Do NOT fall back to a live UzEx download — UzEx blocks direct HTTP
    # requests (405 / 0 bytes), which silently serves an empty file to the user.
    if doc.storage_path:
        logger.warning(
            "Document %s has a missing stored file",
            doc_id,
        )
        raise HTTPException(
            status_code=404,
            detail=(
                "Document file is no longer available in storage. "
                "Please re-sync documents for this tender."
            ),
        )

    raw_download_status = (doc.download_status or "").strip().casefold()
    if raw_download_status == "metadata_only" or tender.source_system != "uzex":
        raise HTTPException(
            status_code=404,
            detail=(
                "Document metadata has been captured, but the file has not "
                "been downloaded into Plasma storage yet."
            ),
        )

    # ── No storage_path at all: document was never downloaded by the worker ──
    # Attempt a live UzEx Playwright download as a last resort.
    file_path = _extract_remote_file_path(doc.file_url)
    if not file_path:
        raise HTTPException(
            status_code=404,
            detail="Document source file path is unavailable. Please re-sync documents for this tender.",
        )

    filename = Path(file_path).name if file_path else f"document.{doc.file_type}"
    
    try:
        scraper = UzExScraper(headless=True)
        file_bytes, downloaded_name = await scraper.download_file(tender.source_url, file_path)
        if not file_bytes:
            raise HTTPException(
                status_code=502,
                detail="Document download returned an empty file. Please re-sync documents for this tender.",
            )
        resolved_name = downloaded_name or filename
        content_type = _guess_download_content_type(
            filename=resolved_name,
            file_type=doc.file_type,
        )
        disposition = "inline" if content_type == "application/pdf" else "attachment"
        
        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={"Content-Disposition": _safe_content_disposition(disposition, resolved_name)}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Document download failed for %s", doc_id)
        raise HTTPException(
            status_code=502,
            detail="Document download failed. Please try again or re-sync documents for this tender.",
        ) from e

@router.get("", response_model=list[TenderResponse])
async def list_tenders(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    source_system: str | None = Query(default=None),
    q: str | None = Query(default=None),
    country: str | None = Query(default=None),
    deadline_status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[TenderResponse]:
    """
    List all tenders, sorted by created_at descending.

    Returns a paginated tender list.
    """
    query = select(Tender).options(
        load_only(
            Tender.id,
            Tender.external_id,
            Tender.source_system,
            Tender.canonical_source_key,
            Tender.source_url,
            Tender.title,
            Tender.description,
            Tender.budget,
            Tender.currency,
            Tender.deadline,
            Tender.publication_date,
            Tender.country,
            Tender.region,
            Tender.sector,
            Tender.buyer,
            Tender.procurement_category,
            Tender.procurement_method,
            Tender.notice_type,
            Tender.project_id,
            Tender.status,
            Tender.category,
            Tender.created_at,
        )
    ).where(customer_visible_tender_condition(Tender))
    normalized_source = _normalize_tender_source_filter(source_system)
    if normalized_source:
        query = query.where(Tender.source_system == normalized_source)

    search_term = (q or "").strip()
    if search_term:
        pattern = f"%{search_term}%"
        query = query.where(
            or_(
                Tender.title.ilike(pattern),
                Tender.description.ilike(pattern),
                Tender.buyer.ilike(pattern),
                Tender.project_id.ilike(pattern),
                Tender.external_id.ilike(pattern),
                Tender.sector.ilike(pattern),
                Tender.category.ilike(pattern),
                Tender.procurement_category.ilike(pattern),
                Tender.procurement_method.ilike(pattern),
                Tender.notice_type.ilike(pattern),
            )
        )

    country_filter = (country or "").strip()
    if country_filter:
        query = query.where(Tender.country.ilike(f"%{country_filter}%"))

    normalized_deadline_status = (deadline_status or "").strip().casefold()
    if normalized_deadline_status:
        now = datetime.now(timezone.utc)
        if normalized_deadline_status == "active":
            query = query.where(Tender.deadline.is_not(None), Tender.deadline >= now)
        elif normalized_deadline_status == "expired":
            query = query.where(Tender.deadline.is_not(None), Tender.deadline < now)
        elif normalized_deadline_status == "unknown":
            query = query.where(Tender.deadline.is_(None))
        elif normalized_deadline_status not in {"all", "any"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported deadline_status",
            )

    category_filter = (category or "").strip()
    if category_filter and category_filter.casefold() not in {"all", "any"}:
        pattern = f"%{category_filter}%"
        query = query.where(
            or_(
                Tender.sector.ilike(pattern),
                Tender.procurement_category.ilike(pattern),
                Tender.category.ilike(pattern),
            )
        )

    query = (
        query
        .order_by(Tender.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(
        query
    )
    tenders = result.scalars().all()
    summaries = await _batched_tender_summaries(
        db=db,
        tender_ids=[tender.id for tender in tenders],
    )
    await _apply_live_uzex_dates(tenders)

    return [
        _serialize_tender(t, summary=summaries.get(t.id))
        for t in tenders
    ]


@router.get("/{tender_id}", response_model=TenderResponse)
async def get_tender(
    tender_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> TenderResponse:
    """
    Get a specific tender by ID.
    """
    result = await db.execute(
        select(Tender)
        .options(
            load_only(
                Tender.id,
                Tender.external_id,
                Tender.source_system,
                Tender.canonical_source_key,
                Tender.source_url,
                Tender.title,
                Tender.description,
                Tender.budget,
                Tender.currency,
                Tender.deadline,
                Tender.publication_date,
                Tender.country,
                Tender.region,
                Tender.sector,
                Tender.buyer,
                Tender.procurement_category,
                Tender.procurement_method,
                Tender.notice_type,
                Tender.project_id,
                Tender.status,
                Tender.category,
                Tender.created_at,
            )
        )
        .where(
            Tender.id == tender_id,
            customer_visible_tender_condition(Tender),
        )
    )
    tender = result.scalar_one_or_none()
    
    if not tender:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )
    
    summary = await _single_tender_summary(db=db, tender_id=tender.id)
    await _apply_live_uzex_dates([tender])
    return _serialize_tender(tender, summary=summary)


@router.get("/{tender_id}/compiled-text", response_model=TenderCompiledTextResponse)
async def get_tender_compiled_text(
    tender_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenderCompiledTextResponse:
    """
    Return compiled source text only to users with access to this tender.
    """
    await _ensure_tender_access(
        db=db,
        tender_id=tender_id,
        user_id=current_user.id,
        current_user=current_user,
        allow_operator=True,
    )

    result = await db.execute(
        select(Tender.compiled_master_text).where(Tender.id == tender_id)
    )
    compiled_text = result.scalar_one_or_none()
    if compiled_text is None:
        tender_exists = await db.execute(select(Tender.id).where(Tender.id == tender_id))
        if tender_exists.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tender not found",
            )

    return TenderCompiledTextResponse(
        tender_id=tender_id,
        compiled_master_text=compiled_text,
    )


@router.post("/refresh", response_model=RefreshResponse, dependencies=[Depends(require_operator_or_admin)])
async def refresh_tenders(
    db: AsyncSession = Depends(get_db),
) -> RefreshResponse:
    """
    Scrape latest tenders from UzEx portal and upsert into database.
    
    This endpoint triggers a live scrape of etender.uzex.uz
    and updates the database with new or modified tenders.
    
    Returns count of new and updated tenders.
    """
    import traceback
    
    new_count = 0
    updated_count = 0
    
    try:
        logger.info("Starting tender refresh from UzEx portal...")
        scraper = UzExScraper(headless=True, timeout=30000)
        scraped_tenders = await scraper.fetch_latest_tenders(limit=50)
        
        logger.info(f"Scraped {len(scraped_tenders)} tenders from portal")
        if not scraped_tenders:
            raise RuntimeError("UzEx TradeList returned no tender rows")
        
        source = UzExTenderSource()
        for scraped in scraped_tenders:
            normalized = source.normalize(scraped)
            _, created = await source.upsert(db, normalized)
            if created:
                new_count += 1
            else:
                updated_count += 1
        
        await db.commit()
        
        return RefreshResponse(
            status="success",
            new_count=new_count,
            updated_count=updated_count,
            message=f"Successfully refreshed feed: {new_count} new, {updated_count} updated",
        )
        
    except Exception as e:
        error_tb = traceback.format_exc()
        logger.error(f"Refresh failed: {e}\n{error_tb}")
        return RefreshResponse(
            status="partial",
            new_count=0,
            updated_count=0,
            message=f"Portal temporarily unavailable. Existing tenders are still shown. ({type(e).__name__})",
        )


@router.post(
    "/sources/world-bank/sync",
    response_model=SourceSyncResponse,
    dependencies=[Depends(require_operator_or_admin)],
)
async def sync_world_bank_tenders(
    max_pages: int = Query(default=3, ge=1, le=10),
    rows: int = Query(default=100, ge=1, le=100),
    active_only: bool = Query(default=True),
    dry_run: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> SourceSyncResponse:
    """
    Import World Bank procurement notices via the official procnotices API.
    """
    source = WorldBankTenderSource(
        rows=rows,
        max_pages=max_pages,
        active_only=active_only,
    )
    errors: list[str] = []
    fetched_count = 0
    created_count = 0
    updated_count = 0
    skipped_count = 0
    failed_count = 0
    attachment_count = 0

    try:
        raw_notices = await source.list_opportunities()
    except Exception as exc:
        logger.exception("world_bank_sync_fetch_failed")
        return SourceSyncResponse(
            status="failed",
            source_system=source.source_system,
            failed_count=1,
            dry_run=dry_run,
            errors=[type(exc).__name__],
            message="World Bank sync failed while fetching notices.",
        )

    fetched_count = len(raw_notices)
    for raw_notice in raw_notices:
        external_id = str(raw_notice.get("id") or "").strip()
        try:
            if not source.should_import(raw_notice):
                skipped_count += 1
                continue

            normalized = source.normalize(raw_notice)
            attachments = await source.discover_attachments(normalized)
            attachment_count += len(attachments)

            if dry_run:
                continue

            tender, created = await source.upsert(db, normalized)
            await db.flush()
            if attachments:
                await source.upsert_attachments(
                    db,
                    tender=tender,
                    attachments=attachments,
                )
            if created:
                created_count += 1
            else:
                updated_count += 1
        except Exception as exc:
            failed_count += 1
            logger.warning(
                "world_bank_sync_notice_failed source_system=%s external_id=%s status=failed error_type=%s",
                source.source_system,
                external_id,
                type(exc).__name__,
            )
            if len(errors) < 10:
                errors.append(
                    f"{external_id or 'unknown'}: {type(exc).__name__}"
                )

    if dry_run:
        await db.rollback()
    else:
        try:
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.exception("world_bank_sync_commit_failed")
            return SourceSyncResponse(
                status="failed",
                source_system=source.source_system,
                fetched_count=fetched_count,
                created_count=created_count,
                updated_count=updated_count,
                skipped_count=skipped_count,
                failed_count=failed_count + 1,
                attachment_count=attachment_count,
                dry_run=dry_run,
                errors=[*errors, f"commit: {type(exc).__name__}"][:10],
                message="World Bank sync failed while saving notices.",
            )

    status_value = "success" if failed_count == 0 else "partial"
    return SourceSyncResponse(
        status=status_value,
        source_system=source.source_system,
        fetched_count=fetched_count,
        created_count=created_count,
        updated_count=updated_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        attachment_count=attachment_count,
        dry_run=dry_run,
        errors=errors,
        message=(
            "World Bank sync dry run completed."
            if dry_run
            else (
                "World Bank sync completed: "
                f"{created_count} created, {updated_count} updated, "
                f"{skipped_count} skipped, {failed_count} failed."
            )
        ),
    )


@router.post(
    "/sources/adb/sync",
    response_model=AdbSyncResponse,
    dependencies=[Depends(require_operator_or_admin)],
)
async def sync_adb_tenders(
    max_items: int = Query(default=50, ge=1, le=100),
    feed_type: str = Query(default="invitation_for_bids"),
    dry_run: bool = Query(default=False),
    download_documents: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> AdbSyncResponse:
    """
    Import ADB tender notices from official RSS feeds.
    """
    if download_documents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "ADB PDF download and parsing is deferred in INT-3. "
                "Run with download_documents=false to capture metadata."
            ),
        )

    try:
        source = AdbTenderSource(feed_type=feed_type, max_items=max_items)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    errors: list[str] = []
    fetched = 0
    created_count = 0
    updated_count = 0
    skipped_count = 0
    failed_count = 0
    attachments_discovered = 0

    try:
        raw_notices = await source.list_opportunities()
    except Exception as exc:
        logger.exception("adb_sync_fetch_failed")
        return AdbSyncResponse(
            status="failed",
            fetched=0,
            failed=1,
            dry_run=dry_run,
            errors=[type(exc).__name__],
            message="ADB sync failed while fetching RSS feed.",
        )

    fetched = len(raw_notices)
    for index, raw_notice in enumerate(raw_notices):
        if index > 0:
            await asyncio.sleep(source.config.request_delay_seconds)
        external_id = str(raw_notice.get("guid") or "").strip()
        try:
            if not source.should_import(raw_notice):
                skipped_count += 1
                continue

            normalized = source.normalize(raw_notice)
            attachments = await source.discover_attachments(normalized)
            attachments_discovered += len(attachments)

            if dry_run:
                continue

            tender, created = await source.upsert(db, normalized)
            await db.flush()
            if attachments:
                await source.upsert_attachments(
                    db,
                    tender=tender,
                    attachments=attachments,
                )
            if created:
                created_count += 1
            else:
                updated_count += 1
        except Exception as exc:
            failed_count += 1
            logger.warning(
                "adb_sync_notice_failed source_system=%s external_id=%s status=failed error_type=%s",
                source.source_system,
                external_id,
                type(exc).__name__,
            )
            if len(errors) < 10:
                errors.append(f"{external_id or 'unknown'}: {type(exc).__name__}")

    if dry_run:
        await db.rollback()
    else:
        try:
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.exception("adb_sync_commit_failed")
            return AdbSyncResponse(
                status="failed",
                fetched=fetched,
                created=created_count,
                updated=updated_count,
                skipped=skipped_count,
                failed=failed_count + 1,
                attachments_discovered=attachments_discovered,
                dry_run=dry_run,
                errors=[*errors, f"commit: {type(exc).__name__}"][:10],
                message="ADB sync failed while saving notices.",
            )

    status_value = "success" if failed_count == 0 else "partial"
    return AdbSyncResponse(
        status=status_value,
        fetched=fetched,
        created=created_count,
        updated=updated_count,
        skipped=skipped_count,
        failed=failed_count,
        attachments_discovered=attachments_discovered,
        documents_downloaded=0,
        dry_run=dry_run,
        errors=errors,
        message=(
            "ADB sync dry run completed. No tenders were written."
            if dry_run
            else (
                "ADB sync completed: "
                f"{created_count} created, {updated_count} updated, "
                f"{skipped_count} skipped, {failed_count} failed."
            )
        ),
    )


def _serialize_sync_job(
    job: TenderSyncJob,
    *,
    message: str,
    reparse_markerless: bool = False,
) -> SyncDocsAcceptedResponse:
    return SyncDocsAcceptedResponse(
        message=message,
        job_id=job.job_id,
        tender_id=job.tender_id,
        user_id=job.user_id,
        status=job.status.value,
        progress=job.progress,
        error_message=job.error_message,
        reparse_markerless=reparse_markerless,
    )


async def _ensure_tender_access(
    *,
    db: AsyncSession,
    tender_id: UUID,
    user_id: UUID,
    current_user: User | None = None,
    allow_operator: bool = False,
) -> None:
    if allow_operator and current_user is not None and is_operator_or_admin(current_user):
        return

    access_result = await db.execute(
        select(Proposal.id)
        .where(
            Proposal.tender_id == tender_id,
            Proposal.user_id == user_id,
        )
        .limit(1)
    )
    if access_result.scalar_one_or_none() is not None:
        return

    if current_user is not None:
        profile_result = await db.execute(
            select(CompanyProfile).where(CompanyProfile.user_id == current_user.id)
        )
        profile = profile_result.scalar_one_or_none()
        owner_key = _analysis_owner_key(current_user=current_user, profile=profile)
        analysis_access_result = await db.execute(
            select(TenderAnalysis.id)
            .where(
                TenderAnalysis.tender_id == tender_id,
                TenderAnalysis.company_name == owner_key,
            )
            .limit(1)
        )
        if analysis_access_result.scalar_one_or_none() is not None:
            return

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Tender not found",
    )


async def _get_analysis_owner_key_for_user(
    *,
    db: AsyncSession,
    current_user: User,
) -> str:
    profile_result = await db.execute(
        select(CompanyProfile).where(CompanyProfile.user_id == current_user.id)
    )
    profile = profile_result.scalar_one_or_none()
    return _analysis_owner_key(
        current_user=current_user,
        profile=profile,
    )


async def _get_owned_analysis(
    *,
    db: AsyncSession,
    analysis_id: UUID,
    tender_id: UUID,
    current_user: User,
) -> TenderAnalysis | None:
    owner_key = await _get_analysis_owner_key_for_user(
        db=db,
        current_user=current_user,
    )
    profile_result = await db.execute(
        select(CompanyProfile).where(CompanyProfile.user_id == current_user.id)
    )
    profile = profile_result.scalar_one_or_none()
    owner_names = _analysis_owner_candidates(
        current_user=current_user,
        profile=profile,
    )
    result = await db.execute(
        select(TenderAnalysis).where(
            TenderAnalysis.id == analysis_id,
            TenderAnalysis.tender_id == tender_id,
            TenderAnalysis.company_name.in_(owner_names),
        )
    )
    analysis = result.scalar_one_or_none()
    if analysis is not None:
        _claim_legacy_analysis_owner(
            analysis=analysis,
            owner_key=owner_key,
            legacy_owner_names=_legacy_analysis_owner_names(
                current_user=current_user,
                profile=profile,
            ),
        )
    return analysis


async def _get_latest_sync_job_for_user_tender(
    *,
    db: AsyncSession,
    tender_id: UUID,
    user_id: UUID,
) -> TenderSyncJob | None:
    result = await db.execute(
        select(TenderSyncJob)
        .where(
            TenderSyncJob.tender_id == tender_id,
            TenderSyncJob.user_id == user_id,
        )
        .order_by(TenderSyncJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_active_sync_job_for_user_tender(
    *,
    db: AsyncSession,
    tender_id: UUID,
    user_id: UUID,
) -> TenderSyncJob | None:
    active_statuses = (TenderSyncStatus.PENDING, TenderSyncStatus.IN_PROGRESS)
    result = await db.execute(
        select(TenderSyncJob)
        .where(
            TenderSyncJob.tender_id == tender_id,
            TenderSyncJob.user_id == user_id,
            TenderSyncJob.status.in_(active_statuses),
        )
        .order_by(TenderSyncJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _count_parsed_documents(
    *,
    db: AsyncSession,
    tender_id: UUID,
) -> int:
    result = await db.execute(
        select(func.count(TenderDocument.id))
        .where(
            TenderDocument.tender_id == tender_id,
            TenderDocument.parsed_text.is_not(None),
            func.length(func.trim(TenderDocument.parsed_text)) > 0,
        )
    )
    return int(result.scalar_one() or 0)


def _count_marker(text: str | None, marker: str) -> int:
    return (text or "").count(marker)


def _has_real_trace_markers(text: str | None) -> bool:
    normalized = (text or "").strip()
    return "[[FILE:" in normalized and "[[PAGE" in normalized


async def _get_sync_marker_diagnostics(
    *,
    db: AsyncSession,
    tender_id: UUID,
) -> SyncMarkerDiagnostics:
    tender_result = await db.execute(
        select(Tender)
        .options(load_only(Tender.compiled_master_text))
        .where(Tender.id == tender_id)
    )
    tender = tender_result.scalar_one_or_none()
    compiled_text = tender.compiled_master_text if tender is not None else ""

    docs_result = await db.execute(
        select(TenderDocument).where(TenderDocument.tender_id == tender_id)
    )
    documents = docs_result.scalars().all()
    parsed_documents = [
        doc
        for doc in documents
        if doc.parsed_text and doc.parsed_text.strip()
    ]

    return SyncMarkerDiagnostics(
        compiled_master_text_length=len(compiled_text or ""),
        compiled_file_marker_count=_count_marker(compiled_text, "[[FILE:"),
        compiled_page_marker_count=_count_marker(compiled_text, "[[PAGE"),
        documents_total=len(documents),
        documents_parsed=len(parsed_documents),
        documents_markerized=sum(
            1 for doc in parsed_documents if _has_real_trace_markers(doc.parsed_text)
        ),
        documents_markerless=sum(
            1 for doc in parsed_documents if not _has_real_trace_markers(doc.parsed_text)
        ),
    )


@router.post(
    "/{tender_id}/sync-docs",
    response_model=SyncDocsAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_tender_documents(
    tender_id: UUID,
    reparse_markerless: bool = Query(
        default=False,
        description=(
            "Reparse stored documents whose parsed_text lacks real parser "
            "[[FILE]]/[[PAGE]] markers before rebuilding compiled text."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SyncDocsAcceptedResponse:
    """
    Enqueue tender document sync as an idempotent operation.
    """
    await _ensure_tender_access(
        db=db,
        tender_id=tender_id,
        user_id=current_user.id,
        current_user=current_user,
        allow_operator=True,
    )

    existing_job = await _get_active_sync_job_for_user_tender(
        db=db,
        tender_id=tender_id,
        user_id=current_user.id,
    )
    if existing_job is not None:
        return _serialize_sync_job(
            existing_job,
            message="Sync already in progress",
            reparse_markerless=reparse_markerless,
        )

    new_job = TenderSyncJob(
        id=uuid4(),
        job_id=str(uuid4()),
        tender_id=tender_id,
        user_id=current_user.id,
        status=TenderSyncStatus.PENDING,
        progress=0,
        error_message=None,
    )
    db.add(new_job)

    try:
        await db.commit()
        await db.refresh(new_job)
    except IntegrityError:
        await db.rollback()
        existing_job = await _get_active_sync_job_for_user_tender(
            db=db,
            tender_id=tender_id,
            user_id=current_user.id,
        )
        if existing_job is not None:
            return _serialize_sync_job(
                existing_job,
                message="Sync already in progress",
                reparse_markerless=reparse_markerless,
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A sync job already exists for this tender.",
        )
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Failed to persist tender sync job before enqueue")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database write failed: {exc}",
        ) from exc

    try:
        process_tender_docs.apply_async(
            args=[str(tender_id), new_job.job_id],
            kwargs={"reparse_markerless": reparse_markerless},
            task_id=new_job.job_id,
        )
    except Exception as exc:
        logger.exception("Failed to enqueue sync task for tender %s", tender_id)
        try:
            new_job.status = TenderSyncStatus.FAILED
            new_job.progress = 0
            new_job.error_message = "Failed to enqueue worker task."
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            logger.exception(
                "Failed to persist enqueue failure for sync job %s",
                new_job.job_id,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue tender document sync task.",
        ) from exc

    return _serialize_sync_job(
        new_job,
        message=(
            "Sync started with markerless reparse"
            if reparse_markerless
            else "Sync started"
        ),
        reparse_markerless=reparse_markerless,
    )


@router.get("/{tender_id}/sync-status", response_model=SyncStatusResponse)
async def get_sync_status(
    tender_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SyncStatusResponse:
    await _ensure_tender_access(
        db=db,
        tender_id=tender_id,
        user_id=current_user.id,
        current_user=current_user,
        allow_operator=True,
    )

    latest_job = await _get_latest_sync_job_for_user_tender(
        db=db,
        tender_id=tender_id,
        user_id=current_user.id,
    )
    docs_parsed = await _count_parsed_documents(
        db=db,
        tender_id=tender_id,
    )
    diagnostics = await _get_sync_marker_diagnostics(
        db=db,
        tender_id=tender_id,
    )

    if latest_job is None:
        return SyncStatusResponse(
            state="SUCCESS" if docs_parsed > 0 else "IDLE",
            progress=100 if docs_parsed > 0 else 0,
            docs_parsed=docs_parsed,
            error=None,
            diagnostics=diagnostics,
        )

    return SyncStatusResponse(
        state=latest_job.status.value,
        progress=latest_job.progress,
        docs_parsed=docs_parsed,
        error=latest_job.error_message,
        diagnostics=diagnostics,
    )


@router.get("/{tender_id}/documents", response_model=list[TenderDocumentResponse])
async def get_tender_documents(
    tender_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TenderDocumentResponse]:
    """
    Return safe document metadata for a given tender.
    """
    tender_result = await db.execute(
        select(Tender.source_system).where(Tender.id == tender_id)
    )
    source_system = tender_result.scalar_one_or_none()
    if source_system is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )

    result = await db.execute(
        select(TenderDocument)
        .where(TenderDocument.tender_id == tender_id)
        .order_by(TenderDocument.created_at.asc())
    )
    return [
        _document_response(doc, source_system=source_system)
        for doc in result.scalars().all()
    ]


@router.get("/{tender_id}/latest-analysis")
async def get_latest_analysis(
    tender_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Return the most recent TenderAnalysis for this tender and the
    authenticated user's company.  Returns null fields when no
    cached analysis exists.
    """
    await _ensure_tender_access(
        db=db,
        tender_id=tender_id,
        user_id=current_user.id,
        current_user=current_user,
        allow_operator=True,
    )

    profile_result = await db.execute(
        select(CompanyProfile).where(CompanyProfile.user_id == current_user.id)
    )
    profile = profile_result.scalar_one_or_none()
    analysis_owner_key = _analysis_owner_key(
        current_user=current_user,
        profile=profile,
    )
    analysis_owner_names = _analysis_owner_candidates(
        current_user=current_user,
        profile=profile,
    )

    result = await db.execute(
        select(TenderAnalysis)
        .where(
            TenderAnalysis.tender_id == tender_id,
            TenderAnalysis.company_name.in_(analysis_owner_names),
        )
        .order_by(TenderAnalysis.created_at.desc())
        .limit(1)
    )
    analysis = result.scalar_one_or_none()

    if analysis is None:
        return {
            "analysis_id": None,
            "requirements": None,
            "evaluation": None,
            "hybrid_compliance": None,
            "content_hash": None,
            "override_seal": None,
            "evidence_validation": None,
            "analysis_warnings": [],
            "coverage_metadata": None,
            "analysis_status": "not_found",
            "extraction_error": None,
        }

    _claim_legacy_analysis_owner(
        analysis=analysis,
        owner_key=analysis_owner_key,
        legacy_owner_names=_legacy_analysis_owner_names(
            current_user=current_user,
            profile=profile,
        ),
    )

    analysis_data = analysis.analysis_json or {}
    return {
        "analysis_id": str(analysis.id),
        "requirements": analysis_data.get("requirements"),
        "evaluation": analysis_data.get("evaluation"),
        "hybrid_compliance": sanitize_internal_requirement_diagnostics(
            analysis_data.get("hybrid_compliance")
        ),
        "content_hash": analysis.content_hash,
        "override_seal": analysis.override_seal,
        "evidence_validation": _public_evidence_validation_payload(
            analysis_data.get("evidence_validation"),
            include_debug=current_user.is_admin,
        ),
        "analysis_warnings": analysis_data.get("analysis_warnings") or [],
        "coverage_metadata": analysis_data.get("coverage_metadata"),
        "analysis_status": analysis_data.get("analysis_status", "completed"),
        "extraction_error": analysis_data.get("extraction_error"),
    }


@router.get("/{tender_id}/compliance/export/pdf")
async def export_compliance_pdf(
    tender_id: UUID,
    analysis_id: UUID | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Export a customer-facing Compliance Analysis PDF for this tender.

    The export is read-only and uses the persisted analysis snapshot for the
    current authenticated user/profile. It does not expose compiled tender text
    or raw analysis internals.
    """
    await _ensure_tender_access(
        db=db,
        tender_id=tender_id,
        user_id=current_user.id,
        current_user=current_user,
        allow_operator=True,
    )

    tender_result = await db.execute(
        select(Tender)
        .options(
            load_only(
                Tender.id,
                Tender.external_id,
                Tender.title,
            )
        )
        .where(Tender.id == tender_id)
    )
    tender = tender_result.scalar_one_or_none()
    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )

    profile_result = await db.execute(
        select(CompanyProfile).where(CompanyProfile.user_id == current_user.id)
    )
    profile = profile_result.scalar_one_or_none()
    analysis_owner_key = _analysis_owner_key(
        current_user=current_user,
        profile=profile,
    )
    analysis_owner_names = _analysis_owner_candidates(
        current_user=current_user,
        profile=profile,
    )

    analysis_query = select(TenderAnalysis).where(
        TenderAnalysis.tender_id == tender_id,
        TenderAnalysis.company_name.in_(analysis_owner_names),
    )
    if analysis_id is not None:
        analysis_query = analysis_query.where(TenderAnalysis.id == analysis_id)
    else:
        analysis_query = analysis_query.order_by(TenderAnalysis.created_at.desc()).limit(1)

    analysis_result = await db.execute(analysis_query)
    analysis = analysis_result.scalar_one_or_none()
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Compliance analysis not found for this tender.",
        )

    _claim_legacy_analysis_owner(
        analysis=analysis,
        owner_key=analysis_owner_key,
        legacy_owner_names=_legacy_analysis_owner_names(
            current_user=current_user,
            profile=profile,
        ),
    )

    analysis_data = analysis.analysis_json or {}
    hybrid_compliance = sanitize_internal_requirement_diagnostics(
        analysis_data.get("hybrid_compliance")
    )
    if not isinstance(hybrid_compliance, dict):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This analysis does not contain exportable compliance results.",
        )

    generated_at = datetime.now(timezone.utc)
    company_name = (
        analysis_data.get("tenant_company_name")
        or (profile.company_name if profile is not None else None)
        or current_user.company_name
        or current_user.name
    )

    evidence_validation = analysis_data.get("evidence_validation")
    if not isinstance(evidence_validation, dict):
        evidence_validation = None
    else:
        evidence_validation = _public_evidence_validation_payload(
            evidence_validation,
            include_debug=current_user.is_admin,
        )
    raw_warnings = analysis_data.get("analysis_warnings")
    analysis_warnings = raw_warnings if isinstance(raw_warnings, list) else []

    try:
        pdf_bytes = build_compliance_report_pdf(
            tender_title=tender.title,
            tender_external_id=tender.external_id,
            company_name=company_name,
            generated_at=generated_at,
            analysis_id=str(analysis.id),
            content_hash=analysis.content_hash,
            override_seal=analysis.override_seal,
            hybrid_compliance=hybrid_compliance,
            evidence_validation=evidence_validation,
            analysis_warnings=[str(warning) for warning in analysis_warnings],
        )
    except Exception as exc:
        logger.exception("Compliance PDF export failed for tender %s", tender_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Compliance PDF export failed. Please try again later.",
        ) from exc

    filename = compliance_report_filename(
        external_id=tender.external_id,
        generated_at=generated_at,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": _safe_content_disposition("attachment", filename),
        },
    )


@router.post("/{tender_id}/override")
async def override_risk(
    tender_id: UUID,
    request: RiskOverrideRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Record liability acceptance override with a cryptographic state hash.

    After persisting the override, recomputes the ``override_seal`` on the
    parent TenderAnalysis so the cryptographic audit trail permanently
    reflects that manual intervention occurred.
    """
    await _ensure_tender_access(
        db=db,
        tender_id=tender_id,
        user_id=current_user.id,
        current_user=current_user,
    )

    tender_result = await db.execute(
        select(Tender.id).where(Tender.id == tender_id)
    )
    if tender_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )

    node_result = await db.execute(
        select(TaxonomyNode.id).where(TaxonomyNode.id == request.node_id)
    )
    if node_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Taxonomy node not found",
        )

    timestamp = datetime.now(timezone.utc).isoformat()
    raw_string = f"{current_user.id}:{tender_id}:{request.node_id}:{timestamp}"
    state_hash = hashlib.sha256(raw_string.encode("utf-8")).hexdigest()

    # Verify the analysis exists and belongs to this tender
    analysis = await _get_owned_analysis(
        db=db,
        analysis_id=request.analysis_id,
        tender_id=tender_id,
        current_user=current_user,
    )
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found for this tender",
        )

    log_entry = RiskOverrideLog(
        user_id=current_user.id,
        tender_id=tender_id,
        analysis_id=request.analysis_id,
        missing_node_id=request.node_id,
        justification=request.justification,
        state_hash=state_hash,
    )
    db.add(log_entry)

    try:
        # Flush so the new log_entry is visible in the next query
        await db.flush()

        # ── Recompute override_seal ──────────────────────────────────
        # Query ALL overrides for this analysis to build the seal
        all_overrides_result = await db.execute(
            select(
                RiskOverrideLog.missing_node_id,
                RiskOverrideLog.created_at,
            )
            .where(
                RiskOverrideLog.analysis_id == request.analysis_id,
                RiskOverrideLog.user_id == current_user.id,
            )
            .order_by(RiskOverrideLog.created_at.asc())
        )
        all_overrides = all_overrides_result.all()

        # Build deterministic seal payload:
        # SHA-256(content_hash | node_id_1:ts_1 | node_id_2:ts_2 | ...)
        content_hash = analysis.content_hash or "NONE"
        override_entries = "|".join(
            f"{row[0]}:{row[1].isoformat()}"
            for row in all_overrides
        )
        seal_input = f"{content_hash}|{override_entries}"
        override_seal = hashlib.sha256(
            seal_input.encode("utf-8")
        ).hexdigest()

        # Persist the seal on the analysis record
        analysis.override_seal = override_seal

        overridden_node_ids = sorted(
            {str(row[0]) for row in all_overrides}
        )

        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Failed to persist risk override log")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database write failed: {exc}",
        ) from exc

    return {
        "state_hash": state_hash,
        "override_seal": override_seal,
        "overridden_node_ids": overridden_node_ids,
    }


@router.get("/{tender_id}/overrides", response_model=RiskOverrideStatusResponse)
async def get_risk_overrides(
    tender_id: UUID,
    analysis_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RiskOverrideStatusResponse:
    """
    Return node IDs that the current user has already overridden for this tender.

    When ``analysis_id`` is provided, only overrides recorded against that
    specific analysis run are returned.  This prevents liability handshakes
    from leaking between analysis runs.

    Also returns the current ``override_seal`` from the parent analysis.
    """
    await _ensure_tender_access(
        db=db,
        tender_id=tender_id,
        user_id=current_user.id,
        current_user=current_user,
    )

    tender_result = await db.execute(
        select(Tender.id).where(Tender.id == tender_id)
    )
    if tender_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )

    filters = [
        RiskOverrideLog.tender_id == tender_id,
        RiskOverrideLog.user_id == current_user.id,
    ]
    override_seal: str | None = None
    if analysis_id is not None:
        owned_analysis = await _get_owned_analysis(
            db=db,
            analysis_id=analysis_id,
            tender_id=tender_id,
            current_user=current_user,
        )
        if owned_analysis is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Analysis not found for this tender",
            )
        override_seal = owned_analysis.override_seal
        filters.append(RiskOverrideLog.analysis_id == analysis_id)

    result = await db.execute(
        select(RiskOverrideLog.missing_node_id).where(*filters)
    )
    accepted_node_ids = sorted({str(row[0]) for row in result.all()})

    return RiskOverrideStatusResponse(
        tender_id=tender_id,
        accepted_node_ids=accepted_node_ids,
        override_seal=override_seal,
    )


@router.post("/seed", response_model=dict, dependencies=[Depends(require_admin)])
async def seed_tenders(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    [DEV ONLY] Seed the database with realistic tenders for demo.
    Skips tenders that already exist (by external_id).
    """
    now = datetime.now(timezone.utc)
    
    dummy_tenders = [
        # === Construction (4) ===
        {
            "external_id": "467201",
            "source_url": "https://etender.uzex.uz/lot/467201",
            "title": "45-sonli umumta'lim maktabi tomini ta'mirlash ishlari (kapital ta'mir)",
            "description": "Tom qoplama materiallarini almashtirish, gidroizolyatsiya, issiqlik izolyatsiyasi va suv oqish tizimini o'rnatish.",
            "budget": 450_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=14),
            "region": "Tashkent",
            "category": "Construction",
            "status": TenderStatus.OPEN,
        },
        {
            "external_id": "467215",
            "source_url": "https://etender.uzex.uz/lot/467215",
            "title": "M39 avtomobil yo'lining 12 km qismini asfalt qoplama ta'mirlash ishlari",
            "description": "Asfalt yuzasini yangilash, drenaj tizimini takomillashtirish va yo'l belgilarini chizish ishlari.",
            "budget": 1_200_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=10),
            "region": "Navoi",
            "category": "Construction",
            "status": TenderStatus.OPEN,
        },
        {
            "external_id": "467230",
            "source_url": "https://etender.uzex.uz/lot/467230",
            "title": "Bolalar bog'chasi №12 uchun o'yin maydonchasi qurilishi",
            "description": "Xavfsizlik qoplamasi, arqonli tirmashish, sirpanish va atraktsionlarni o'z ichiga olgan to'liq qurilish ishlari.",
            "budget": 800_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=21),
            "region": "Bukhara",
            "category": "Construction",
            "status": TenderStatus.OPEN,
        },
        {
            "external_id": "467245",
            "source_url": "https://etender.uzex.uz/lot/467245",
            "title": "Tuman hokimligi binosi ichki va tashqi remont ishlari",
            "description": "Bino ichki devorlarini suvash, bo'yash, pol yotqizish, tashqi fasadni yangilash va elektr tarmoqlarini almashtirish.",
            "budget": 680_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=18),
            "region": "Kashkadarya",
            "category": "Construction",
            "status": TenderStatus.OPEN,
        },
        # === IT & Tech (3) ===
        {
            "external_id": "467260",
            "source_url": "https://etender.uzex.uz/lot/467260",
            "title": "Soliq boshqarmasi uchun 50 dona kompyuter ta'minoti (i5/16GB/512GB SSD)",
            "description": "Intel Core i5 12-avlod, 16GB RAM, 512GB SSD, 24 dyuymli monitor va klaviatura/sichqoncha to'plami.",
            "budget": 1_250_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=7),
            "region": "Samarkand",
            "category": "IT & Tech",
            "status": TenderStatus.OPEN,
        },
        {
            "external_id": "467275",
            "source_url": "https://etender.uzex.uz/lot/467275",
            "title": "Server jihozlari va tarmoq infratuzilmasini modernizatsiya qilish",
            "description": "2 dona rack server, UPS, tarmoq kommutatorlari, patch-panellar va optik tolali kabellar yetkazib berish.",
            "budget": 890_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=12),
            "region": "Tashkent",
            "category": "IT & Tech",
            "status": TenderStatus.OPEN,
        },
        {
            "external_id": "467290",
            "source_url": "https://etender.uzex.uz/lot/467290",
            "title": "Printer va kartridj ta'minoti — HP LaserJet Pro 30 dona",
            "description": "HP LaserJet Pro MFP M428fdn printerlari va har biriga 3 tadan zaxira kartridjlar.",
            "budget": 320_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=9),
            "region": "Fergana",
            "category": "IT & Tech",
            "status": TenderStatus.OPEN,
        },
        # === Medical (2) ===
        {
            "external_id": "467305",
            "source_url": "https://etender.uzex.uz/lot/467305",
            "title": "Tuman shifoxonasiga tibbiy asbob-uskunalar yetkazib berish",
            "description": "MRT apparati, rentgen jihozi, UZI apparati va laboratoriya uskunalarini yetkazib berish va o'rnatish.",
            "budget": 2_500_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=30),
            "region": "Fergana",
            "category": "Medical",
            "status": TenderStatus.OPEN,
        },
        {
            "external_id": "467320",
            "source_url": "https://etender.uzex.uz/lot/467320",
            "title": "Dori-darmon vositalari va tibbiy sarf materiallarini xarid qilish",
            "description": "Oilaviy poliklinikalar uchun yillik dori-darmon ta'minoti: antibiotiklar, og'riq qoldiruvchilar, shpritslar, maskalar.",
            "budget": 380_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=15),
            "region": "Andijan",
            "category": "Medical",
            "status": TenderStatus.OPEN,
        },
        # === Office (2) ===
        {
            "external_id": "467335",
            "source_url": "https://etender.uzex.uz/lot/467335",
            "title": "Kantselyariya tovarlari va ofis jihozlari ta'minoti",
            "description": "A4 qog'oz (500 qadoq), ruchka, papka, shtamp siyohi, steplyer va boshqa kantselyariya buyumlari.",
            "budget": 85_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=5),
            "region": "Tashkent",
            "category": "Office",
            "status": TenderStatus.OPEN,
        },
        {
            "external_id": "467350",
            "source_url": "https://etender.uzex.uz/lot/467350",
            "title": "Maktab partalarini va stullarini xarid qilish — 200 to'plam",
            "description": "O'quvchi parta va stullari (200 to'plam), o'qituvchi stoli (15 dona), shkaflar (10 dona).",
            "budget": 240_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=20),
            "region": "Namangan",
            "category": "Office",
            "status": TenderStatus.OPEN,
        },
        # === Other (1) ===
        {
            "external_id": "467365",
            "source_url": "https://etender.uzex.uz/lot/467365",
            "title": "Avtotransport xizmati — oylik reyslar uchun GMS yoqilg'i ta'minoti",
            "description": "Davlat tashkiloti avtoparki uchun AI-92, AI-95 va dizel yoqilg'isi yillik ta'minot shartnomasi.",
            "budget": 560_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=25),
            "region": "Jizzakh",
            "category": "Other",
            "status": TenderStatus.OPEN,
        },
    ]
    
    new_count = 0
    skip_count = 0
    
    for tender_data in dummy_tenders:
        normalized = NormalizedTender(
            source_system="uzex",
            external_id=tender_data["external_id"],
            source_url=tender_data["source_url"],
            title=tender_data["title"],
            description=tender_data["description"],
            budget=tender_data["budget"],
            currency=tender_data["currency"],
            deadline=tender_data["deadline"],
            region=tender_data["region"],
            category=tender_data["category"],
            status=tender_data["status"],
        )
        _, created = await UzExTenderSource().upsert(db, normalized)
        if created:
            new_count += 1
        else:
            skip_count += 1
    
    await db.commit()
    
    return {"message": f"Seeded {new_count} new tenders ({skip_count} already existed)"}
