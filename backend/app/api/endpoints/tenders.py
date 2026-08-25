"""
Plasma AI - Tenders Endpoints

Public tender feed for the Autonomous Tender Officer.
"""

import asyncio
import hashlib
import html
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from time import monotonic
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.api.deps import (
    is_operator_or_admin,
    require_admin,
    require_approved_user,
    require_approved_pilot_access,
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
from app.core.geography import (
    CENTRAL_ASIA_REGION,
    COUNTRIES_BY_REGION,
    normalize_target_regions,
)
from app.core.parser import process_tender_document
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
from app.core.storage_paths import normalize_storage_path, storage_file_exists
from app.core.tender_actionability import (
    TENDER_NOT_ACTIONABLE_DETAIL,
    actionable_tender_condition,
    is_tender_actionable,
)
from app.core.services import normalize_target_services, service_label
from app.crud.crud_profile import get_profile_for_compliance_match
from app.crud.exceptions import ProfileNotFoundException
from app.db.session import get_db
from app.models.audit import TenderAnalysis
from app.models.all_models import (
    Proposal,
    RiskOverrideLog,
    SourceRefreshJob,
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
from app.schemas.tender import (
    TenderCompetitorGroup,
    TenderCompetitorIntelligenceResponse,
    TenderCompetitorResponse,
    TenderContactSubmissionResponse,
    TenderDecisionSnapshotResponse,
    TenderDocumentResponse,
    TenderResponse,
)
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
from app.services.giz_document_hydration import (
    hydrate_giz_tender_documents as hydrate_giz_tender_documents_inline,
)
from app.services.tender_sources.base import (
    NormalizedTender,
    assert_source_scope,
    reconcile_past_deadline_open_tenders,
)
from app.services.tender_sources.adb import (
    AdbTenderSource,
    reconcile_unresolved_adb_legacy_rows,
)
from app.services.tender_sources.diagnostics import (
    connector_failure_details,
    safe_failure_message,
)
from app.services.tender_sources.ebrd import EbrdTenderSource
from app.services.tender_sources.giz import (
    DEFAULT_GIZ_TENDER_PAGES,
    MAX_ARCHIVE_COMPRESSED_BYTES as GIZ_MAX_ARCHIVE_COMPRESSED_BYTES,
    MAX_ARCHIVE_EXTRACTED_BYTES as GIZ_MAX_ARCHIVE_EXTRACTED_BYTES,
    MAX_ARCHIVE_FILE_COUNT as GIZ_MAX_ARCHIVE_FILE_COUNT,
    MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES as GIZ_MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES,
    MAX_ARCHIVE_NESTING_DEPTH as GIZ_MAX_ARCHIVE_NESTING_DEPTH,
    GizTenderSource,
    _extension_from_url as _giz_extension_from_url,
    _safe_giz_url,
)
from app.services.tender_sources.uzex import UzExTenderSource
from app.services.tender_sources.uzex_constants import UZEX_ENTERPRISE_TYPE_ID
from app.services.tender_sources.uzex_contact import extract_uzex_contact_info
from app.services.tender_sources.uzex_scope import customer_visible_tender_condition
from app.services.tender_sources.world_bank import (
    WORLD_BANK_PROC_DETAIL_URL,
    WORLD_BANK_PROC_NOTICES_URL,
    WorldBankTenderSource,
    _sector_text as _world_bank_sector_text,
    extract_world_bank_contact_info,
)
from app.workers.tender_tasks import (
    _cleanup_temp_download,
    _file_sha256,
    _finalize_document_download,
    _persist_document_bytes,
    _reserve_document_download_path,
    hydrate_giz_documents,
    process_tender_docs,
)
from app.workers.source_refresh_tasks import refresh_tender_source

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
    rejected_count: int = 0
    failed_count: int = 0
    attachment_count: int = 0
    documents_downloaded: int = 0
    dry_run: bool = False
    failure_stage: str | None = None
    failure_class: str | None = None
    retryable: bool | None = None
    fallback_used: bool = False
    skip_reasons: dict[str, int] = Field(default_factory=dict)
    elapsed_ms: int | None = None
    source_newest_published_at: datetime | None = None
    source_oldest_published_at: datetime | None = None
    execution_health: str | None = None
    freshness_health: str | None = None
    coverage_health: str | None = None
    errors: list[str] = Field(default_factory=list)
    message: str


class SourceRefreshResponse(BaseModel):
    """Customer-safe source refresh state."""

    status: str
    source_system: str
    job_id: UUID
    created_count: int = 0
    updated_count: int = 0
    fetched_count: int = 0
    skipped_count: int = 0
    rejected_count: int = 0
    failed_count: int = 0
    fallback_used: bool = False
    skip_reasons: dict[str, int] = Field(default_factory=dict)
    failure_class: str | None = None
    failure_stage: str | None = None
    retryable: bool | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    elapsed_ms: int | None = None
    source_newest_published_at: datetime | None = None
    source_oldest_published_at: datetime | None = None
    source_age_days: int | None = None
    execution_health: str | None = None
    freshness_health: str | None = None
    coverage_health: str | None = None
    last_updated: datetime | None = None
    reused: bool = False
    message: str


class AdbSyncResponse(BaseModel):
    """Response for ADB tender sync."""

    status: str
    source_system: str = "adb"
    fetched: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    rejected_count: int = 0
    failed: int = 0
    attachments_discovered: int = 0
    documents_downloaded: int = 0
    dry_run: bool = False
    failure_stage: str | None = None
    failure_class: str | None = None
    retryable: bool | None = None
    fallback_used: bool = False
    skip_reasons: dict[str, int] = Field(default_factory=dict)
    elapsed_ms: int | None = None
    source_newest_published_at: datetime | None = None
    source_oldest_published_at: datetime | None = None
    execution_health: str | None = None
    freshness_health: str | None = None
    coverage_health: str | None = None
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


class GizHydrateRequest(BaseModel):
    """Operator request for targeted GIZ document hydration."""

    external_ids: list[str] = Field(min_length=1, max_length=50)
    force: bool = False


class GizHydrateJobResponse(BaseModel):
    external_id: str
    tender_id: UUID
    job_id: str
    status: str
    progress: int
    queued: bool
    message: str


class GizHydrateAcceptedResponse(BaseModel):
    message: str
    source_system: str = "giz"
    force: bool = False
    requested_count: int = 0
    accepted_count: int = 0
    enqueued_count: int = 0
    already_running_count: int = 0
    jobs: list[GizHydrateJobResponse] = Field(default_factory=list)


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
    source_system: str | None = None
    coverage_status: str | None = None
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
FAILED_EXTRACTION_STATUS_MESSAGE = (
    "ANALYSIS FAILED — Requirement extraction failed; do not rely on this "
    "compliance result until extraction succeeds."
)
DOCUMENT_STATUS_FILTERS = {
    "documents_available",
    "files_missing",
    "metadata_only",
    "access_required",
    "no_documents_found",
    "processing",
    "failed",
}
SORT_OPTIONS = {
    "newest",
    "deadline_soonest",
    "highest_price",
    "document_availability",
    "source",
}
SERVICE_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "construction": (
        "construction",
        "civil works",
        "building",
        "road",
        "bridge",
        "rehabilitation",
        "renovation",
        "reconstruction",
        "contractor",
        "qurilish",
        "қурилиш",
        "строител",
        "таъмир",
        "ремонт",
        "йўл",
        "йул",
        "yo'l",
        "дорога",
        "дамба",
    ),
    "medical": (
        "medical",
        "health",
        "hospital",
        "clinic",
        "pharma",
        "pharmaceutical",
        "medicine",
        "diagnostic",
        "laboratory",
        "tibbiy",
        "тиббий",
        "медицин",
        "шифохона",
        "больниц",
        "дори",
        "лекар",
        "диагност",
        "лаборатор",
    ),
    "IT": (
        "IT",
        "ICT",
        "software",
        "information technology",
        "digital",
        "computer",
        "network",
        "system",
        "ахборот",
        "информацион",
        "компьютер",
        "дастур",
        "программ",
        "тармоқ",
        "тармок",
    ),
    "industrial services": (
        "industrial",
        "maintenance",
        "repair",
        "engineering",
        "energy",
        "utility",
        "utilities",
        "manufacturing",
        "plant",
        "саноат",
        "производ",
        "завод",
        "энерг",
        "коммунал",
        "техник хизмат",
    ),
    "consulting": (
        "consulting",
        "consultant",
        "advisory",
        "technical assistance",
        "supervision",
        "feasibility",
        "assessment",
        "audit",
        "консалт",
        "маслаҳат",
        "маслахат",
        "maslahat",
        "аудит",
        "баҳолаш",
        "бахолаш",
    ),
    "equipment supply": (
        "equipment",
        "supply",
        "goods",
        "materials",
        "machinery",
        "vehicle",
        "device",
        "procurement of",
        "delivery",
        "харид",
        "поставка",
        "етказиб",
        "товар",
        "ускуна",
        "жиҳоз",
        "жихоз",
        "оборудован",
        "материал",
    ),
    "other": ("other", "miscellaneous"),
}
COMPETITOR_EMPTY_MESSAGE = "No historical competitor intelligence available yet."
COMPETITOR_AVAILABLE_MESSAGE = (
    "Historical competitor intelligence is available from public source metadata."
)
COMPETITOR_MAX_RELATED_TENDERS = 250
COMPETITOR_MAX_RESULTS = 30
COMPETITOR_NAME_MAX_LENGTH = 180
COMPETITOR_SOURCE_FETCH_TIMEOUT_SECONDS = 8.0
COMPETITOR_LIVE_SOURCE_ROWS = 80
COMPETITOR_LIVE_CACHE_TTL_SECONDS = 15 * 60
UZEX_DEALS_LIST_URL = "https://apietender.uzex.uz/api/common/DealsList"
ADB_CONTRACTS_AWARDED_RSS_URL = "http://feeds.feedburner.com/adb-contracts-awarded"
CompetitorLiveCacheKey = tuple[str, str, str]
_COMPETITOR_LIVE_CACHE: dict[
    CompetitorLiveCacheKey,
    tuple[float, list[TenderCompetitorResponse]],
] = {}
COMPETITOR_METADATA_KEYS: dict[str, tuple[str, ...]] = {
    "winner": (
        "awardee",
        "awarded_company",
        "awarded_supplier",
        "awarded_supplier_name",
        "awarded_to",
        "contract_awardee",
        "contract_winner",
        "contractor_name",
        "selected_consultant",
        "selected_consultant_name",
        "successful_supplier",
        "successful_tenderer",
        "supplier_name",
        "vendor_name",
        "winner",
        "winner_name",
        "winning_bidder",
        "winning_bidder_name",
    ),
    "participant": (
        "bidder_name",
        "bidder_names",
        "bidders",
        "evaluated_bidders",
        "participant_name",
        "participant_names",
        "participants",
        "qualified_bidders",
        "shortlisted_consultants",
        "shortlisted_firms",
        "submitted_bidders",
    ),
    "similar_market_actor": (
        "known_market_actor",
        "known_market_actors",
        "market_actor",
        "market_actors",
        "similar_companies",
        "similar_company_names",
        "similar_market_actor",
        "similar_market_actors",
    ),
}
COMPETITOR_NESTED_NAME_KEYS = {
    "company",
    "company_name",
    "contractor",
    "contractor_name",
    "firm",
    "firm_name",
    "name",
    "organization",
    "participant",
    "participant_name",
    "supplier",
    "supplier_name",
    "vendor",
    "vendor_name",
    "winner",
    "winner_name",
}
COMPETITOR_NAME_STOPWORDS = {
    "-",
    "n/a",
    "na",
    "none",
    "not applicable",
    "not available",
    "not specified",
    "unknown",
}
COMPETITOR_KEY_LOOKUP = {
    participation_type: {
        re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
        for key in keys
    }
    for participation_type, keys in COMPETITOR_METADATA_KEYS.items()
}


def _normalized_metadata_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().casefold()).strip("_")


def _metadata_values_for_keys(value: Any, keys: set[str]):
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if _normalized_metadata_key(key) in keys:
                yield nested_value
            if isinstance(nested_value, (dict, list, tuple)):
                yield from _metadata_values_for_keys(nested_value, keys)
        return

    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _metadata_values_for_keys(item, keys)


def _competitor_name_values(value: Any):
    if isinstance(value, str):
        for part in re.split(r"[\n;|]+", value):
            cleaned = part.strip(" \t\r\n,")
            if cleaned:
                yield cleaned
        return

    if isinstance(value, dict):
        for key, nested_value in value.items():
            if _normalized_metadata_key(key) in COMPETITOR_NESTED_NAME_KEYS:
                yield from _competitor_name_values(nested_value)
        return

    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _competitor_name_values(item)
        return

    if value is not None and not isinstance(value, (bool, int, float)):
        yield str(value)


def _clean_competitor_name(value: Any, *, buyer: str | None = None) -> str | None:
    cleaned = _clean_contact_text(value, max_length=COMPETITOR_NAME_MAX_LENGTH)
    if not cleaned:
        return None
    cleaned = re.sub(r"[\"“”‘’`]+", "", cleaned.strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+\((?:\d{3,}|ID:?\s*\d+)\)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    if cleaned.casefold() in COMPETITOR_NAME_STOPWORDS:
        return None
    if "@" in cleaned or cleaned.casefold().startswith(("http://", "https://")):
        return None
    if buyer and cleaned.casefold() == str(buyer).strip().casefold():
        return None
    return cleaned


def _competitor_source_label(source_system: str) -> str:
    if source_system == "world_bank":
        return "World Bank"
    if source_system == "adb":
        return "ADB"
    if source_system == "ebrd":
        return "EBRD"
    return "UzEx"


def _source_record_as_tender_like(
    *,
    title: str | None,
    description: str | None = None,
    sector: str | None = None,
    category: str | None = None,
    procurement_category: str | None = None,
    procurement_method: str | None = None,
    notice_type: str | None = None,
):
    return SimpleNamespace(
        title=title,
        description=description,
        sector=sector,
        category=category,
        procurement_category=procurement_category,
        procurement_method=procurement_method,
        notice_type=notice_type,
    )


def _text_matches_service_term(blob: str, term: str) -> bool:
    cleaned = term.strip()
    if not cleaned:
        return False
    if len(cleaned) <= 3 and re.fullmatch(r"[A-Za-z0-9]+", cleaned):
        return re.search(
            rf"(?<![A-Za-z0-9]){re.escape(cleaned)}(?![A-Za-z0-9])",
            blob,
            re.IGNORECASE,
        ) is not None
    return cleaned.casefold() in blob.casefold()


def _tender_service_text(tender: Tender) -> str:
    return " ".join(
        str(getattr(tender, field, "") or "")
        for field in (
            "sector",
            "category",
            "procurement_category",
            "procurement_method",
            "notice_type",
            "title",
            "description",
        )
    )


def _infer_tender_service_category(tender: Tender) -> str:
    explicit_services = normalize_target_services(
        [
            getattr(tender, "sector", None),
            getattr(tender, "category", None),
            getattr(tender, "procurement_category", None),
        ],
        reject_invalid=False,
    )
    if explicit_services:
        return explicit_services[0]

    blob = _tender_service_text(tender)
    for service, terms in SERVICE_SEARCH_TERMS.items():
        if service == "other":
            continue
        if any(_text_matches_service_term(blob, term) for term in terms):
            return service
    return "other"


def _same_text(left: str | None, right: str | None) -> bool:
    return bool(left and right and left.strip().casefold() == right.strip().casefold())


def _meaningful_competitor_filter_text(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    if cleaned.casefold() in {"adb", "other", "uzex", "world bank"}:
        return None
    return cleaned


def _related_tender_match_summary(
    *,
    target_tender: Tender,
    related_tender: Tender,
    service_category: str,
) -> str:
    matches: list[str] = []
    if _same_text(getattr(target_tender, "buyer", None), getattr(related_tender, "buyer", None)):
        matches.append("the same buyer")
    if _same_text(getattr(target_tender, "country", None), getattr(related_tender, "country", None)):
        matches.append("the same country")
    if service_category != "other":
        matches.append(f"the {service_label(service_category)} service category")
    elif _same_text(getattr(target_tender, "sector", None), getattr(related_tender, "sector", None)):
        matches.append("a matching sector")
    elif _same_text(
        getattr(target_tender, "procurement_category", None),
        getattr(related_tender, "procurement_category", None),
    ):
        matches.append("a matching procurement category")

    return ", ".join(dict.fromkeys(matches)) or "public historical procurement metadata"


def _competitor_reason(
    *,
    participation_type: str,
    match_summary: str,
) -> str:
    if participation_type == "winner":
        return (
            "Public winner data was found in a related historical tender "
            f"sharing {match_summary}."
        )
    if participation_type == "participant":
        return (
            "Public participant data was found in a related historical tender "
            f"sharing {match_summary}."
        )
    return (
        "Public source metadata lists this company as a similar market actor "
        f"for a tender sharing {match_summary}."
    )


def _live_source_reason(
    *,
    source_system: str,
    participation_type: str,
    match_summary: str,
) -> str:
    source_label = _competitor_source_label(source_system)
    if participation_type == "winner":
        return (
            f"Public {source_label} historical award/deal data names this "
            f"company for a record sharing {match_summary}."
        )
    if participation_type == "participant":
        return (
            f"Public {source_label} historical evaluation data names this "
            f"company for a record sharing {match_summary}."
        )
    return (
        f"Public {source_label} historical activity names this company for "
        f"a record sharing {match_summary}."
    )


def _source_record_match_summary(
    *,
    target_tender: Tender,
    source_system: str,
    service_category: str,
    source_country: str | None = None,
    exact_service_match: bool = False,
) -> str:
    matches: list[str] = []
    if source_country and _same_text(getattr(target_tender, "country", None), source_country):
        matches.append("the same country")
    if exact_service_match and service_category != "other":
        matches.append(f"the {service_label(service_category)} service category")
    if not matches:
        matches.append(f"the {_competitor_source_label(source_system)} procurement source")
    return ", ".join(dict.fromkeys(matches))


def _extract_public_competitor_records(
    *,
    target_tender: Tender,
    related_tender: Tender,
    target_service_category: str,
) -> list[TenderCompetitorResponse]:
    metadata = getattr(related_tender, "source_metadata_json", None)
    if not isinstance(metadata, dict):
        return []

    related_service_category = _infer_tender_service_category(related_tender)
    service_category = (
        target_service_category
        if target_service_category != "other"
        else related_service_category
    )
    industry = service_label(service_category)
    match_summary = _related_tender_match_summary(
        target_tender=target_tender,
        related_tender=related_tender,
        service_category=service_category,
    )
    evidence_source = _safe_source_notice_url(getattr(related_tender, "source_url", None))
    records: list[TenderCompetitorResponse] = []
    seen: set[tuple[str, str]] = set()

    for participation_type, keys in COMPETITOR_KEY_LOOKUP.items():
        for metadata_value in _metadata_values_for_keys(metadata, keys):
            for raw_name in _competitor_name_values(metadata_value):
                company_name = _clean_competitor_name(
                    raw_name,
                    buyer=getattr(related_tender, "buyer", None),
                )
                if not company_name:
                    continue

                dedupe_key = (company_name.casefold(), participation_type)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                confidence = (
                    "high"
                    if participation_type in {"winner", "participant"}
                    else "low"
                )
                records.append(
                    TenderCompetitorResponse(
                        company_name=company_name,
                        industry=industry,
                        service_category=service_category,
                        source=str(getattr(related_tender, "source_system", "") or ""),
                        related_tender_id=getattr(related_tender, "id", None),
                        buyer=getattr(related_tender, "buyer", None),
                        country=getattr(related_tender, "country", None),
                        sector=getattr(related_tender, "sector", None),
                        category=(
                            getattr(related_tender, "procurement_category", None)
                            or getattr(related_tender, "category", None)
                        ),
                        participation_type=participation_type,
                        confidence=confidence,
                        reason=_competitor_reason(
                            participation_type=participation_type,
                            match_summary=match_summary,
                        ),
                        evidence_source=evidence_source,
                    )
                )

    return records


def _competitor_confidence_rank(value: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(value, 0)


def _competitor_participation_rank(value: str) -> int:
    return {"winner": 3, "participant": 2, "similar_market_actor": 1}.get(value, 0)


def _group_competitor_records(
    records: list[TenderCompetitorResponse],
) -> list[TenderCompetitorGroup]:
    history_keys: dict[tuple[str, str], set[str]] = {}
    for record in records:
        key = (record.company_name.casefold(), record.service_category.casefold())
        history_keys.setdefault(key, set()).add(
            str(record.related_tender_id or record.evidence_source or record.source)
        )

    deduped: dict[tuple[str, str], TenderCompetitorResponse] = {}
    for record in records:
        key = (record.company_name.casefold(), record.service_category.casefold())
        history_count = len(history_keys.get(key, set()))
        candidate = record
        if (
            record.participation_type == "similar_market_actor"
            and record.confidence == "low"
            and history_count >= 2
        ):
            candidate = record.model_copy(
                update={
                    "confidence": "medium",
                    "reason": (
                        f"Repeated similar tender history appears in {history_count} "
                        f"public records for {record.industry}."
                    ),
                }
            )

        existing = deduped.get(key)
        if existing is None:
            deduped[key] = candidate
            continue

        candidate_rank = (
            _competitor_confidence_rank(candidate.confidence),
            _competitor_participation_rank(candidate.participation_type),
        )
        existing_rank = (
            _competitor_confidence_rank(existing.confidence),
            _competitor_participation_rank(existing.participation_type),
        )
        if candidate_rank > existing_rank:
            deduped[key] = candidate

    grouped: dict[str, TenderCompetitorGroup] = {}
    for record in sorted(
        deduped.values(),
        key=lambda item: (
            item.industry.casefold(),
            -_competitor_confidence_rank(item.confidence),
            item.company_name.casefold(),
        ),
    )[:COMPETITOR_MAX_RESULTS]:
        group = grouped.setdefault(
            record.service_category,
            TenderCompetitorGroup(
                industry=record.industry,
                service_category=record.service_category,
                competitors=[],
            ),
        )
        group.competitors.append(record)

    return list(grouped.values())


def _live_competitor_record(
    *,
    company_name: str,
    source_system: str,
    service_category: str,
    participation_type: str,
    confidence: str,
    reason: str,
    evidence_source: str | None,
    buyer: str | None = None,
    country: str | None = None,
    sector: str | None = None,
    category: str | None = None,
) -> TenderCompetitorResponse:
    return TenderCompetitorResponse(
        company_name=company_name,
        industry=service_label(service_category),
        service_category=service_category,
        source=source_system,
        related_tender_id=None,
        buyer=buyer,
        country=country,
        sector=sector,
        category=category,
        participation_type=participation_type,
        confidence=confidence,
        reason=reason,
        evidence_source=evidence_source,
    )


def _source_record_exact_service_match(
    *,
    target_service_category: str,
    source_service_category: str,
) -> bool:
    if target_service_category == "other":
        return source_service_category != "other"
    return target_service_category == source_service_category


async def _fetch_json_payload(
    *,
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    json_payload: dict[str, Any] | None = None,
    referer: str | None = None,
) -> Any:
    headers = {
        "Accept": "application/json",
        "User-Agent": "PlasmaOS CompetitorIntelligence/1.0",
    }
    if referer:
        headers["Referer"] = referer
    async with httpx.AsyncClient(
        timeout=COMPETITOR_SOURCE_FETCH_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers=headers,
    ) as client:
        response = await client.request(
            method,
            url,
            params=params,
            json=json_payload,
        )
        response.raise_for_status()
        return response.json()


async def _fetch_text_payload(
    *,
    url: str,
    referer: str | None = None,
) -> str:
    headers = {
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "User-Agent": "PlasmaOS CompetitorIntelligence/1.0",
    }
    if referer:
        headers["Referer"] = referer
    async with httpx.AsyncClient(
        timeout=COMPETITOR_SOURCE_FETCH_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers=headers,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def _live_uzex_competitor_records(
    *,
    target_tender: Tender,
    target_service_category: str,
) -> list[TenderCompetitorResponse]:
    if getattr(target_tender, "source_system", None) != "uzex":
        return []

    try:
        payload = await _fetch_json_payload(
            method="POST",
            url=UZEX_DEALS_LIST_URL,
            json_payload={
                "From": 1,
                "To": COMPETITOR_LIVE_SOURCE_ROWS,
                "TypeId": UZEX_ENTERPRISE_TYPE_ID,
                "System_Id": 0,
            },
            referer="https://etender.uzex.uz/",
        )
    except Exception:
        logger.exception(
            "uzex_competitor_deals_fetch_failed tender_id=%s",
            getattr(target_tender, "id", None),
        )
        return []

    if not isinstance(payload, list):
        return []

    records: list[TenderCompetitorResponse] = []
    broad_records: list[TenderCompetitorResponse] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        company_name = _clean_competitor_name(
            row.get("provider_name"),
            buyer=row.get("customer_name"),
        )
        if not company_name:
            continue

        category = _clean_contact_text(row.get("category_name"), max_length=220)
        source_like = _source_record_as_tender_like(
            title=category,
            description=category,
            sector=category,
            category=category,
            procurement_category=category,
        )
        source_service_category = _infer_tender_service_category(source_like)
        exact_service_match = _source_record_exact_service_match(
            target_service_category=target_service_category,
            source_service_category=source_service_category,
        )
        service_category = (
            source_service_category
            if target_service_category == "other" and source_service_category != "other"
            else target_service_category
        )
        if service_category == "other":
            service_category = source_service_category

        match_summary = _source_record_match_summary(
            target_tender=target_tender,
            source_system="uzex",
            service_category=service_category,
            source_country="Uzbekistan",
            exact_service_match=exact_service_match,
        )
        evidence_source = None
        trade_id = row.get("trade_id")
        if trade_id:
            evidence_source = f"https://etender.uzex.uz/lot/{quote(str(trade_id), safe='')}"

        record = _live_competitor_record(
            company_name=company_name,
            source_system="uzex",
            service_category=service_category,
            participation_type="winner",
            confidence="high",
            reason=_live_source_reason(
                source_system="uzex",
                participation_type="winner",
                match_summary=match_summary,
            ),
            evidence_source=evidence_source,
            buyer=_clean_contact_text(row.get("customer_name"), max_length=220),
            country="Uzbekistan",
            sector=category,
            category=category,
        )
        if exact_service_match:
            records.append(record)
        else:
            broad_records.append(record)

    if target_service_category != "other":
        return records[:COMPETITOR_MAX_RESULTS]
    return (records or broad_records)[:COMPETITOR_MAX_RESULTS]


WORLD_BANK_AWARD_SECTION_LABELS = (
    "Awarded Bidder",
    "Awarded Bidder(s)",
    "Awarded Firm",
    "Awarded Firm(s)",
    "Evaluated Bidder",
    "Evaluated Bidder(s)",
    "Rejected Bidder",
    "Rejected Bidder(s)",
)


def _strip_html_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", html.unescape(value or "")).strip()


def _world_bank_award_sections(
    notice_text: str,
    *,
    label_patterns: tuple[str, ...],
) -> list[str]:
    start_positions = sorted(
        match.start()
        for pattern in label_patterns
        for match in re.finditer(re.escape(pattern), notice_text, flags=re.IGNORECASE)
    )
    if not start_positions:
        return []

    all_label_positions = sorted(
        match.start()
        for label in WORLD_BANK_AWARD_SECTION_LABELS
        for match in re.finditer(re.escape(label), notice_text, flags=re.IGNORECASE)
    )
    sections: list[str] = []
    for start in start_positions:
        following_label_positions = [
            position
            for position in all_label_positions
            if position > start + 20
        ]
        end = min(following_label_positions) if following_label_positions else len(notice_text)
        sections.append(notice_text[start:end])
    return sections


def _world_bank_award_names(
    notice_text: str | None,
    *,
    participation_type: str,
) -> list[str]:
    if not notice_text:
        return []
    if participation_type == "winner":
        sections = _world_bank_award_sections(
            notice_text,
            label_patterns=(
                "Awarded Bidder",
                "Awarded Bidder(s)",
                "Awarded Firm",
                "Awarded Firm(s)",
            ),
        )
    else:
        sections = _world_bank_award_sections(
            notice_text,
            label_patterns=(
                "Evaluated Bidder",
                "Evaluated Bidder(s)",
                "Rejected Bidder",
                "Rejected Bidder(s)",
            ),
        )
    if not sections:
        return []

    names: list[str] = []
    seen: set[str] = set()
    for section in sections:
        for match in re.finditer(r"<b>\s*(?P<name>[^<]{2,220})\s*</b>\s*<br\s*/?>", section, flags=re.IGNORECASE):
            raw_name = _strip_html_tags(match.group("name"))
            if re.search(
                r"\b(?:awarded|evaluated|rejected|price|contract|project|method|scope|duration|currency|amount)\b",
                raw_name,
                flags=re.IGNORECASE,
            ):
                continue
            company_name = _clean_competitor_name(raw_name)
            if not company_name:
                continue
            key = company_name.casefold()
            if key in seen:
                continue
            names.append(company_name)
            seen.add(key)
    return names


async def _live_world_bank_competitor_records(
    *,
    target_tender: Tender,
    target_service_category: str,
) -> list[TenderCompetitorResponse]:
    if getattr(target_tender, "source_system", None) != "world_bank":
        return []

    try:
        payload = await _fetch_json_payload(
            method="GET",
            url=WORLD_BANK_PROC_NOTICES_URL,
            params={
                "format": "json",
                "apilang": "en",
                "fl": "*",
                "rows": COMPETITOR_LIVE_SOURCE_ROWS,
                "os": 0,
                "notice_type": "Contract Award",
                "srt": "noticedate desc,id asc",
            },
        )
    except Exception:
        logger.exception(
            "world_bank_competitor_awards_fetch_failed tender_id=%s",
            getattr(target_tender, "id", None),
        )
        return []

    rows = payload.get("procnotices") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []

    records: list[TenderCompetitorResponse] = []
    broad_records: list[TenderCompetitorResponse] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_like = _source_record_as_tender_like(
            title=row.get("noticetitle") or row.get("bid_description"),
            description=_strip_html_tags(str(row.get("notice_text") or "")),
            sector=_world_bank_sector_text(row),
            category=row.get("procurement_group_desc"),
            procurement_category=row.get("procurement_group_desc"),
            procurement_method=row.get("procurement_method_name"),
            notice_type=row.get("notice_type"),
        )
        source_service_category = _infer_tender_service_category(source_like)
        exact_service_match = _source_record_exact_service_match(
            target_service_category=target_service_category,
            source_service_category=source_service_category,
        )
        same_country = _same_text(
            getattr(target_tender, "country", None),
            row.get("project_ctry_name"),
        )
        if target_service_category != "other" and not exact_service_match:
            continue
        if target_service_category == "other" and not exact_service_match and not same_country:
            continue

        service_category = (
            source_service_category
            if target_service_category == "other" and source_service_category != "other"
            else target_service_category
        )
        if service_category == "other":
            service_category = source_service_category
        match_summary = _source_record_match_summary(
            target_tender=target_tender,
            source_system="world_bank",
            service_category=service_category,
            source_country=row.get("project_ctry_name"),
            exact_service_match=exact_service_match,
        )
        evidence_source = None
        if row.get("id"):
            evidence_source = WORLD_BANK_PROC_DETAIL_URL.format(id=quote(str(row["id"]), safe=""))

        for participation_type in ("winner", "participant"):
            for company_name in _world_bank_award_names(
                row.get("notice_text"),
                participation_type=participation_type,
            ):
                record = _live_competitor_record(
                    company_name=company_name,
                    source_system="world_bank",
                    service_category=service_category,
                    participation_type=participation_type,
                    confidence="high",
                    reason=_live_source_reason(
                        source_system="world_bank",
                        participation_type=participation_type,
                        match_summary=match_summary,
                    ),
                    evidence_source=evidence_source,
                    buyer=_clean_contact_text(row.get("agency_name"), max_length=220),
                    country=_clean_contact_text(row.get("project_ctry_name"), max_length=120),
                    sector=_world_bank_sector_text(row),
                    category=_clean_contact_text(row.get("procurement_group_desc"), max_length=120),
                )
                if exact_service_match or same_country:
                    records.append(record)
                else:
                    broad_records.append(record)

    return (records or broad_records)[:COMPETITOR_MAX_RESULTS]


def _adb_title_company_candidate(title: str | None) -> str | None:
    text = _clean_contact_text(title, max_length=COMPETITOR_NAME_MAX_LENGTH)
    if not text:
        return None
    match = re.search(
        r"\b(?:awarded\s+to|contract\s+awarded\s+to|winner)\s+(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return _clean_competitor_name(match.group(1))


async def _live_adb_competitor_records(
    *,
    target_tender: Tender,
    target_service_category: str,
) -> list[TenderCompetitorResponse]:
    if getattr(target_tender, "source_system", None) != "adb":
        return []

    try:
        rss_text = await _fetch_text_payload(url=ADB_CONTRACTS_AWARDED_RSS_URL)
    except Exception:
        logger.exception(
            "adb_competitor_awards_fetch_failed tender_id=%s",
            getattr(target_tender, "id", None),
        )
        return []

    try:
        root = ET.fromstring(rss_text)
    except ET.ParseError:
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    records: list[TenderCompetitorResponse] = []
    for item in channel.findall("item")[:COMPETITOR_LIVE_SOURCE_ROWS]:
        title = item.findtext("title")
        company_name = _adb_title_company_candidate(title)
        if not company_name:
            continue
        categories = [
            category.text or ""
            for category in item.findall("category")
            if category.text
        ]
        category_text = " | ".join(categories)
        source_like = _source_record_as_tender_like(
            title=title,
            description=category_text,
            sector=category_text,
            category="ADB",
        )
        source_service_category = _infer_tender_service_category(source_like)
        exact_service_match = _source_record_exact_service_match(
            target_service_category=target_service_category,
            source_service_category=source_service_category,
        )
        if not exact_service_match and target_service_category != "other":
            continue
        service_category = (
            source_service_category
            if target_service_category == "other" and source_service_category != "other"
            else target_service_category
        )
        match_summary = _source_record_match_summary(
            target_tender=target_tender,
            source_system="adb",
            service_category=service_category,
            exact_service_match=exact_service_match,
        )
        records.append(
            _live_competitor_record(
                company_name=company_name,
                source_system="adb",
                service_category=service_category,
                participation_type="winner",
                confidence="high",
                reason=_live_source_reason(
                    source_system="adb",
                    participation_type="winner",
                    match_summary=match_summary,
                ),
                evidence_source=item.findtext("link"),
                category="ADB awarded contract RSS",
            )
        )

    return records[:COMPETITOR_MAX_RESULTS]


def _competitor_live_cache_key(
    *,
    target_tender: Tender,
    target_service_category: str,
) -> CompetitorLiveCacheKey:
    country = str(getattr(target_tender, "country", "") or "").strip().casefold()
    return (
        str(getattr(target_tender, "source_system", "") or "").strip().casefold(),
        target_service_category.strip().casefold(),
        country,
    )


def _copy_competitor_records(
    records: list[TenderCompetitorResponse],
) -> list[TenderCompetitorResponse]:
    return [record.model_copy(deep=True) for record in records]


def _get_live_competitor_cache(
    key: CompetitorLiveCacheKey,
    *,
    allow_stale: bool = False,
) -> list[TenderCompetitorResponse] | None:
    cached = _COMPETITOR_LIVE_CACHE.get(key)
    if cached is None:
        return None
    cached_at, records = cached
    is_fresh = monotonic() - cached_at <= COMPETITOR_LIVE_CACHE_TTL_SECONDS
    if not is_fresh and not allow_stale:
        return None
    return _copy_competitor_records(records)


def _set_live_competitor_cache(
    key: CompetitorLiveCacheKey,
    records: list[TenderCompetitorResponse],
) -> None:
    _COMPETITOR_LIVE_CACHE[key] = (monotonic(), _copy_competitor_records(records))


async def _live_source_competitor_records(
    *,
    target_tender: Tender,
    target_service_category: str,
) -> list[TenderCompetitorResponse]:
    cache_key = _competitor_live_cache_key(
        target_tender=target_tender,
        target_service_category=target_service_category,
    )
    cached = _get_live_competitor_cache(cache_key)
    if cached is not None:
        return cached

    source_system = getattr(target_tender, "source_system", None)
    try:
        if source_system == "uzex":
            records = await _live_uzex_competitor_records(
                target_tender=target_tender,
                target_service_category=target_service_category,
            )
        elif source_system == "world_bank":
            records = await _live_world_bank_competitor_records(
                target_tender=target_tender,
                target_service_category=target_service_category,
            )
        elif source_system == "adb":
            records = await _live_adb_competitor_records(
                target_tender=target_tender,
                target_service_category=target_service_category,
            )
        else:
            records = []
    except Exception:
        logger.exception(
            "competitor_live_source_dispatch_failed tender_id=%s source=%s",
            getattr(target_tender, "id", None),
            source_system,
        )
        return _get_live_competitor_cache(cache_key, allow_stale=True) or []

    if records:
        _set_live_competitor_cache(cache_key, records)
        return records

    return _get_live_competitor_cache(cache_key, allow_stale=True) or []


def _normalize_tender_source_filter(source_system: str | None) -> str | None:
    if not source_system:
        return None
    normalized_source = source_system.strip().casefold().replace("-", "_")
    if normalized_source in {"", "all", "all_sources"}:
        return None
    if normalized_source == "worldbank":
        normalized_source = "world_bank"
    if normalized_source not in {"uzex", "world_bank", "adb", "giz", "ebrd"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported source_system",
        )
    return normalized_source


def _tender_lifecycle_condition(value: str | None):
    """Resolve Explorer lifecycle filtering; the default is actionable OPEN."""
    normalized = (value or "open").strip().casefold()
    if normalized in {"all", "any"}:
        return None
    if normalized == "open":
        return actionable_tender_condition(Tender)
    try:
        lifecycle_status = TenderStatus(normalized.upper())
    except ValueError as exc:
        raise ValueError("Unsupported tender status") from exc
    return Tender.status == lifecycle_status


def _split_query_values(values: list[str] | str | None) -> list[str]:
    if values is None:
        return []
    raw_values = values if isinstance(values, list) else [values]
    normalized: list[str] = []
    for raw_value in raw_values:
        for item in str(raw_value).split(","):
            cleaned = item.strip()
            if cleaned:
                normalized.append(cleaned)
    return normalized


def _normalize_list_filter(
    values: list[str] | str | None,
    *,
    supported_values: set[str] | None = None,
    label: str,
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    supported_lookup = (
        {value.casefold(): value for value in supported_values}
        if supported_values is not None
        else None
    )
    for item in _split_query_values(values):
        if item.casefold() in {"all", "any"}:
            continue
        canonical = (
            supported_lookup.get(item.casefold())
            if supported_lookup is not None
            else item
        )
        if canonical is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported {label}",
            )
        key = canonical.casefold()
        if key not in seen:
            normalized.append(canonical)
            seen.add(key)
    return normalized


def _normalize_region_filter(region: str | list[str] | None) -> list[str]:
    try:
        return normalize_target_regions(_split_query_values(region)) or []
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def _normalize_service_filter(services: str | list[str] | None) -> list[str]:
    try:
        return normalize_target_services(_split_query_values(services)) or []
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def _expanded_region_countries(regions: list[str]) -> list[str]:
    countries: list[str] = []
    seen: set[str] = set()
    for region in regions:
        for country in COUNTRIES_BY_REGION.get(region, ()):
            key = country.casefold()
            if key not in seen:
                countries.append(country)
                seen.add(key)
    return countries


def _country_predicate(countries: list[str]):
    return or_(*[Tender.country.ilike(f"%{country}%") for country in countries])


def _service_predicate(services: list[str]):
    searchable_columns = (
        Tender.sector,
        Tender.category,
        Tender.procurement_category,
        Tender.procurement_method,
        Tender.notice_type,
        Tender.title,
        Tender.description,
    )
    predicates = []
    for service in services:
        service_terms = SERVICE_SEARCH_TERMS.get(service, (service,))
        for term in service_terms:
            pattern = f"%{term}%"
            predicates.extend(column.ilike(pattern) for column in searchable_columns)
    return or_(*predicates)


def _document_availability_condition():
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
    unavailable_status_condition = lowered_status.in_(
        tuple(UNAVAILABLE_LEGACY_DOCUMENT_STATUSES)
    )
    legacy_uzex_available_condition = (
        (Tender.source_system == "uzex")
        & file_url_present
        & (~unavailable_status_condition)
    )
    return (
        (available_status_condition | storage_path_present | legacy_uzex_available_condition)
        & (~unavailable_status_condition)
    )


def _document_status_exists(condition):
    return exists(
        select(1).where(
            TenderDocument.tender_id == Tender.id,
            condition,
        )
    )


def _document_status_predicate(document_status: str):
    lowered_status = func.lower(
        func.coalesce(func.nullif(func.trim(TenderDocument.download_status), ""), "")
    )
    available_exists = _document_status_exists(_document_availability_condition())
    metadata_exists = _document_status_exists(lowered_status == "metadata_only")
    access_required_exists = _document_status_exists(lowered_status == "access_required")
    processing_exists = _document_status_exists(lowered_status == "processing")
    failed_exists = _document_status_exists(lowered_status == "failed")
    missing_file_exists = _document_status_exists(
        TenderDocument.storage_path.is_not(None)
        & (func.length(func.trim(TenderDocument.storage_path)) > 0)
        & (~_document_availability_condition())
    )

    if document_status == "documents_available":
        return available_exists & (~failed_exists)
    if document_status == "files_missing":
        return (~failed_exists) & (~available_exists) & missing_file_exists
    if document_status == "metadata_only":
        return (
            (~failed_exists)
            & (~available_exists)
            & (~missing_file_exists)
            & metadata_exists
        )
    if document_status == "access_required":
        return (
            (~failed_exists)
            & (~available_exists)
            & (~missing_file_exists)
            & access_required_exists
        )
    if document_status == "processing":
        return (
            (~failed_exists)
            & (~available_exists)
            & (~missing_file_exists)
            & (~metadata_exists)
            & processing_exists
        )
    if document_status == "failed":
        return failed_exists
    return (
        (~available_exists)
        & (~missing_file_exists)
        & (~metadata_exists)
        & (~access_required_exists)
        & (~processing_exists)
        & (~failed_exists)
    )


def _apply_tender_sort(query, sort: str | None):
    normalized_sort = (sort or "newest").strip().casefold().replace("-", "_")
    if normalized_sort in {"", "default"}:
        normalized_sort = "newest"
    if normalized_sort not in SORT_OPTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported sort",
        )

    if normalized_sort == "deadline_soonest":
        return query.order_by(
            Tender.deadline.is_(None).asc(),
            Tender.deadline.asc(),
            Tender.created_at.desc(),
        )
    if normalized_sort == "highest_price":
        return query.order_by(Tender.budget.desc(), Tender.created_at.desc())
    if normalized_sort == "document_availability":
        available_rank = case(
            (_document_status_predicate("documents_available"), 0),
            (_document_status_predicate("files_missing"), 1),
            (_document_status_predicate("metadata_only"), 2),
            (_document_status_predicate("processing"), 3),
            (_document_status_predicate("failed"), 4),
            else_=5,
        )
        return query.order_by(available_rank.asc(), Tender.created_at.desc())
    if normalized_sort == "source":
        return query.order_by(Tender.source_system.asc(), Tender.created_at.desc())
    return query.order_by(
        func.coalesce(Tender.publication_date, Tender.created_at).desc(),
        Tender.created_at.desc(),
    )


def _document_status_from_summary(summary: DocumentSummary) -> str:
    if int(summary.get("failed_document_count") or 0) > 0:
        return "failed"
    if int(summary.get("downloadable_document_count") or 0) > 0:
        return "documents_available"
    if int(summary.get("missing_file_document_count") or 0) > 0:
        return "files_missing"
    if bool(summary.get("access_required")):
        return "access_required"
    if int(summary.get("metadata_only_document_count") or 0) > 0:
        return "metadata_only"
    if bool(summary.get("processing")):
        return "processing"
    return "no_documents_found"


def _giz_coverage_status_from_metadata(
    source_metadata: dict[str, Any] | None,
) -> str | None:
    coverage = (source_metadata or {}).get("giz_document_coverage")
    if not isinstance(coverage, dict):
        return None
    coverage_status = str(coverage.get("coverage_status") or "").strip().casefold()
    return coverage_status or None


def _compliance_unavailable_reason(
    *,
    source_system: str,
    has_compiled_text: bool,
    document_status: str,
    parsed_document_count: int = 0,
    source_metadata: dict[str, Any] | None = None,
) -> str | None:
    if source_system == "ebrd":
        return "EBRD notices are metadata-only; participation documents require ECEPP registration and are not parsed for compliance."
    if source_system == "giz":
        coverage_status = _giz_coverage_status_from_metadata(source_metadata) or ""
        if not has_compiled_text or parsed_document_count <= 0:
            return "Prepare documents for analysis"
        if coverage_status in {"failed", "unavailable"}:
            return "Preparation failed"
        return None
    if document_status == "failed":
        return "Preparation failed"
    if has_compiled_text:
        return None
    if source_system == "adb" and document_status == "metadata_only":
        return "Document discovered — preparation required before analysis."
    if document_status == "files_missing":
        return "Preparation failed. Try preparing documents again before analysis."
    return "Prepare documents for analysis"


def _empty_tender_summary(*, has_compiled_text: bool = False) -> DocumentSummary:
    return {
        "has_compiled_text": has_compiled_text,
        "document_status": "no_documents_found",
        "document_count": 0,
        "available_document_count": 0,
        "downloadable_document_count": 0,
        "missing_file_document_count": 0,
        "parsed_document_count": 0,
        "metadata_only_document_count": 0,
        "failed_document_count": 0,
        "processing": False,
        "access_required": False,
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

    document_rows = await db.execute(
        select(
            TenderDocument.tender_id,
            TenderDocument.download_status,
            TenderDocument.storage_path,
            TenderDocument.file_url,
            (
                TenderDocument.parsed_text.is_not(None)
                & (func.length(func.trim(TenderDocument.parsed_text)) > 0)
            ).label("has_parsed_text"),
            Tender.source_system,
        )
        .join(Tender, TenderDocument.tender_id == Tender.id)
        .where(TenderDocument.tender_id.in_(tender_ids))
    )
    for row in document_rows.mappings().all():
        tender_id = row["tender_id"]
        summary = summaries[tender_id]
        summary["document_count"] = int(summary.get("document_count") or 0) + 1
        status = _document_download_status(
            SimpleNamespace(
                download_status=row["download_status"],
                storage_path=row["storage_path"],
                file_url=row["file_url"],
            ),
            source_system=row["source_system"],
        )
        if status == "available":
            downloadable_count = (
                int(summary.get("downloadable_document_count") or 0) + 1
            )
            summary["downloadable_document_count"] = downloadable_count
            summary["available_document_count"] = downloadable_count
        elif status == "missing_file":
            summary["missing_file_document_count"] = (
                int(summary.get("missing_file_document_count") or 0) + 1
            )
        elif status == "metadata_only":
            summary["metadata_only_document_count"] = (
                int(summary.get("metadata_only_document_count") or 0) + 1
            )
        elif status == "access_required":
            summary["access_required"] = True
        elif status == "failed":
            summary["failed_document_count"] = (
                int(summary.get("failed_document_count") or 0) + 1
            )
        elif status == "processing":
            summary["processing"] = True
        if row["has_parsed_text"]:
            summary["parsed_document_count"] = (
                int(summary.get("parsed_document_count") or 0) + 1
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


CONTACT_TEXT_MAX_LENGTH = 500
EMAIL_RE = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+")
LABELED_PHONE_RE = re.compile(
    r"(?:phone|telephone|tel\.?|mobile|cell)\s*[:\-]?\s*"
    r"(\+?[0-9][0-9\s()./\-]{6,})",
    re.IGNORECASE,
)
INTERNAL_PATH_RE = re.compile(
    r"^(?:/[^\s]+|[A-Za-z]:[\\/]|\\\\|file://)",
    re.IGNORECASE,
)

CONTACT_METADATA_KEYS = {
    "buyer_agency": (
        "buyer_agency",
        "buyer",
        "buyer_name",
        "agency_name",
        "contact_organization",
        "executing_agency",
        "implementing_agency",
        "borrower",
    ),
    "contact_person": (
        "contact_person",
        "contact_person_name",
        "contact_name",
        "procurement_contact_name",
        "focal_point",
    ),
    "email": (
        "email",
        "e_mail",
        "contact_email",
        "contact_email_address",
        "procurement_email",
    ),
    "phone": (
        "phone",
        "telephone",
        "tel",
        "contact_phone",
        "contact_phone_no",
        "contact_telephone",
        "contact_tel",
        "procurement_phone",
    ),
    "address": (
        "address",
        "contact_address",
        "buyer_address",
        "agency_address",
        "procurement_address",
    ),
    "submission_method": (
        "submission_method",
        "submission_method_name",
        "bid_submission_method",
        "submission_channel",
        "submission_instructions",
        "delivery_method",
    ),
    "question_deadline": (
        "question_deadline",
        "clarification_deadline",
        "inquiry_deadline",
        "pre_bid_question_deadline",
    ),
    "procedure_type": (
        "procedure_type",
        "procurement_procedure_type",
        "procedure_kind",
        "procurement_method",
    ),
    "participation_instructions": (
        "participation_instructions",
        "participation_access_instructions",
        "access_instructions",
        "submission_access_instructions",
    ),
    "document_access_notes": (
        "document_access_notes",
        "document_access",
        "access_notes",
        "documents_access",
        "document_obtaining",
        "document_collection",
    ),
}


def _clean_contact_text(
    value: Any,
    *,
    max_length: int = CONTACT_TEXT_MAX_LENGTH,
) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    if not cleaned or INTERNAL_PATH_RE.match(cleaned):
        return None
    return cleaned[:max_length]


def _metadata_first_text(
    metadata: dict[str, Any] | None,
    keys: tuple[str, ...],
) -> str | None:
    if not isinstance(metadata, dict):
        return None
    normalized_keys = {key.casefold() for key in keys}
    for key, value in metadata.items():
        if str(key).casefold() in normalized_keys:
            cleaned = _clean_contact_text(value)
            if cleaned:
                return cleaned
    return None


def _parse_contact_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc)
            if value.tzinfo
            else value.replace(tzinfo=timezone.utc)
        )
    text = _clean_contact_text(value, max_length=80)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                pass
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _metadata_first_datetime(
    metadata: dict[str, Any] | None,
    keys: tuple[str, ...],
) -> datetime | None:
    if not isinstance(metadata, dict):
        return None
    normalized_keys = {key.casefold() for key in keys}
    for key, value in metadata.items():
        if str(key).casefold() in normalized_keys:
            parsed = _parse_contact_datetime(value)
            if parsed:
                return parsed
    return None


def _notice_text(metadata: dict[str, Any] | None) -> str | None:
    if not isinstance(metadata, dict):
        return None
    return _clean_contact_text(metadata.get("notice_text"), max_length=MAX_PAYLOAD_CHARS)


def _extract_email(metadata: dict[str, Any] | None) -> str | None:
    structured = _metadata_first_text(metadata, CONTACT_METADATA_KEYS["email"])
    if structured:
        match = EMAIL_RE.search(structured)
        if match:
            return match.group(0)
    text = _notice_text(metadata)
    if not text:
        return None
    match = EMAIL_RE.search(text)
    return match.group(0) if match else None


def _extract_phone(metadata: dict[str, Any] | None) -> str | None:
    structured = _metadata_first_text(metadata, CONTACT_METADATA_KEYS["phone"])
    if structured:
        return structured
    text = _notice_text(metadata)
    if not text:
        return None
    match = LABELED_PHONE_RE.search(text)
    if not match:
        return None
    return _clean_contact_text(match.group(1), max_length=80)


def _contact_submission_response(
    tender: Tender,
    *,
    source_url: str | None,
    include_metadata: bool,
    metadata_override: dict[str, Any] | None = None,
) -> TenderContactSubmissionResponse:
    metadata = (
        metadata_override
        if metadata_override is not None
        else tender.source_metadata_json if include_metadata else None
    )
    world_bank_contact = (
        extract_world_bank_contact_info(metadata)
        if tender.source_system == "world_bank"
        else {}
    )
    buyer_agency = (
        _clean_contact_text(world_bank_contact.get("buyer_agency"))
        or _metadata_first_text(metadata, CONTACT_METADATA_KEYS["buyer_agency"])
        or _clean_contact_text(getattr(tender, "buyer", None))
    )
    submission_deadline = getattr(tender, "deadline", None)
    if not isinstance(submission_deadline, datetime):
        submission_deadline = _metadata_first_datetime(
            metadata,
            ("submission_deadline", "submission_deadline_date", "submission_date"),
        )

    return TenderContactSubmissionResponse(
        buyer_agency=buyer_agency,
        contact_person=_clean_contact_text(world_bank_contact.get("contact_person"))
        or _metadata_first_text(
            metadata,
            CONTACT_METADATA_KEYS["contact_person"],
        ),
        email=_clean_contact_text(world_bank_contact.get("email"))
        or _extract_email(metadata),
        phone=_clean_contact_text(world_bank_contact.get("phone"))
        or _extract_phone(metadata),
        address=_clean_contact_text(world_bank_contact.get("address"))
        or _metadata_first_text(metadata, CONTACT_METADATA_KEYS["address"]),
        submission_method=_metadata_first_text(
            metadata,
            CONTACT_METADATA_KEYS["submission_method"],
        ),
        submission_deadline=submission_deadline,
        question_deadline=_metadata_first_datetime(
            metadata,
            CONTACT_METADATA_KEYS["question_deadline"],
        ),
        procedure_type=_metadata_first_text(
            metadata,
            CONTACT_METADATA_KEYS["procedure_type"],
        ),
        participation_instructions=_metadata_first_text(
            metadata,
            CONTACT_METADATA_KEYS["participation_instructions"],
        ),
        source_url=source_url,
        document_access_notes=_metadata_first_text(
            metadata,
            CONTACT_METADATA_KEYS["document_access_notes"],
        ),
    )


def _has_world_bank_contact_metadata(metadata: dict[str, Any] | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    return any(
        _clean_contact_text(metadata.get(key))
        for key in (
            "contact_name",
            "contact_email",
            "contact_phone_no",
            "contact_phone",
            "contact_address",
            "contact_organization",
        )
    )


async def _world_bank_contact_metadata_override(tender: Tender) -> dict[str, Any] | None:
    if tender.source_system != "world_bank":
        return None
    metadata = tender.source_metadata_json
    if _has_world_bank_contact_metadata(metadata):
        return None

    try:
        detail = await WorldBankTenderSource(
            rows=1,
            max_pages=1,
            timeout_seconds=8.0,
            max_retries=1,
        ).fetch_detail(tender.external_id)
    except Exception:
        logger.exception(
            "world_bank_contact_detail_fetch_failed external_id=%s",
            tender.external_id,
        )
        return None

    if not isinstance(detail, dict) or not _has_world_bank_contact_metadata(detail):
        return None
    return {**(metadata or {}), **detail}


def _has_adb_contact_metadata(metadata: dict[str, Any] | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    return any(
        _clean_contact_text(metadata.get(key))
        for key in (
            "contact_person",
            "email",
            "phone",
            "address",
            "buyer_agency",
            "submission_method",
        )
    )


async def _adb_contact_metadata_override(tender: Tender) -> dict[str, Any] | None:
    if tender.source_system != "adb":
        return None
    metadata = tender.source_metadata_json or {}
    if _has_adb_contact_metadata(metadata):
        return None

    try:
        detail = await AdbTenderSource(
            timeout_seconds=12.0,
            max_retries=1,
        ).fetch_contact_metadata(
            node_url=str(metadata.get("node_url") or tender.source_url),
            final_pdf_url=metadata.get("final_pdf_url"),
        )
    except Exception:
        logger.exception(
            "adb_contact_detail_fetch_failed external_id=%s",
            tender.external_id,
        )
        return None

    if not isinstance(detail, dict) or not _has_adb_contact_metadata(detail):
        return None
    return {**metadata, **detail}


def _has_uzex_contact_metadata(metadata: dict[str, Any] | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    return any(
        _clean_contact_text(metadata.get(key))
        for key in (
            "contact_person",
            "email",
            "phone",
            "address",
            "submission_method",
        )
    )


async def _uzex_contact_metadata_override(tender: Tender) -> dict[str, Any] | None:
    if tender.source_system != "uzex":
        return None
    metadata = tender.source_metadata_json or {}
    if _has_uzex_contact_metadata(metadata):
        return None
    external_id = str(tender.external_id or "").strip()
    if not external_id:
        return None

    trade_url = (
        "https://apietender.uzex.uz/api/common/GetTrade/"
        f"{quote(external_id, safe='')}/0"
    )
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            response = await client.get(
                trade_url,
                headers={
                    "Accept": "application/json",
                    "Referer": str(tender.source_url or ""),
                },
            )
            response.raise_for_status()
            payload = response.json()
    except Exception:
        logger.exception(
            "uzex_contact_detail_fetch_failed external_id=%s",
            tender.external_id,
        )
        return None

    detail = extract_uzex_contact_info(
        payload if isinstance(payload, dict) else None
    )
    if not detail or not _has_uzex_contact_metadata(detail):
        return None
    return {**metadata, **detail}


def _has_giz_contact_metadata(metadata: dict[str, Any] | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    return any(
        _clean_contact_text(metadata.get(key))
        for key in (
            "contact_person",
            "email",
            "phone",
            "address",
            "submission_method",
            "procedure_type",
            "participation_instructions",
        )
    )


async def _giz_contact_metadata_override(tender: Tender) -> dict[str, Any] | None:
    if tender.source_system != "giz":
        return None
    metadata = tender.source_metadata_json or {}
    if _has_giz_contact_metadata(metadata):
        return None
    project_url = str(
        metadata.get("eproc_project_url")
        or metadata.get("official_source_url")
        or tender.source_url
        or ""
    )
    if "ausschreibungen.giz.de" not in project_url:
        return None
    try:
        detail = await GizTenderSource(
            source_pages=[],
            include_eproc=False,
            timeout_seconds=12.0,
            max_retries=1,
        ).fetch_contact_metadata(project_url=project_url)
    except Exception:
        logger.exception(
            "giz_contact_detail_fetch_failed external_id=%s",
            tender.external_id,
        )
        return None
    if not isinstance(detail, dict) or not _has_giz_contact_metadata(detail):
        return None
    return {**metadata, **detail}


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
    include_contact_metadata: bool = False,
    contact_metadata_override: dict[str, Any] | None = None,
) -> TenderResponse:
    payload = TenderResponse.model_validate(tender)
    payload.source_url = _safe_source_notice_url(payload.source_url)
    payload.contact_submission = _contact_submission_response(
        tender,
        source_url=payload.source_url,
        include_metadata=include_contact_metadata,
        metadata_override=contact_metadata_override,
    )
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
    payload.downloadable_document_count = int(
        summary.get("downloadable_document_count") or 0
    )
    payload.missing_file_document_count = int(
        summary.get("missing_file_document_count") or 0
    )
    payload.parsed_document_count = int(summary.get("parsed_document_count") or 0)
    payload.metadata_only_document_count = int(
        summary.get("metadata_only_document_count") or 0
    )
    payload.failed_document_count = int(summary.get("failed_document_count") or 0)
    giz_coverage_status = _giz_coverage_status_from_metadata(tender.source_metadata_json)
    if (
        payload.source_system == "giz"
        and giz_coverage_status == "partial"
        and payload.has_compiled_text
        and payload.parsed_document_count > 0
    ):
        payload.document_status = "partial"
    elif (
        payload.source_system == "giz"
        and giz_coverage_status == "complete"
        and payload.has_compiled_text
        and payload.parsed_document_count > 0
    ):
        payload.document_status = "documents_available"
    unavailable_reason = _compliance_unavailable_reason(
        source_system=payload.source_system,
        has_compiled_text=payload.has_compiled_text,
        document_status=payload.document_status,
        parsed_document_count=payload.parsed_document_count,
        source_metadata=tender.source_metadata_json,
    )
    payload.compliance_analysis_available = unavailable_reason is None
    payload.compliance_unavailable_reason = unavailable_reason
    return payload


def _deadline_urgency(
    deadline: datetime | None,
    *,
    now: datetime | None = None,
) -> str:
    if deadline is None:
        return "unknown"

    comparable_deadline = deadline
    if comparable_deadline.tzinfo is None:
        comparable_deadline = comparable_deadline.replace(tzinfo=timezone.utc)
    else:
        comparable_deadline = comparable_deadline.astimezone(timezone.utc)

    comparable_now = now or datetime.now(timezone.utc)
    if comparable_now.tzinfo is None:
        comparable_now = comparable_now.replace(tzinfo=timezone.utc)
    else:
        comparable_now = comparable_now.astimezone(timezone.utc)

    remaining = comparable_deadline - comparable_now
    if remaining.total_seconds() < 0:
        return "expired"
    if remaining <= timedelta(days=7):
        return "urgent"
    if remaining <= timedelta(days=30):
        return "soon"
    return "normal"


def _contact_availability(
    contact: TenderContactSubmissionResponse | None,
) -> str:
    if contact is None:
        return "missing"
    if any(
        _clean_contact_text(getattr(contact, field, None))
        for field in ("contact_person", "email", "phone", "address")
    ):
        return "available"
    if (
        _clean_contact_text(contact.source_url, max_length=500)
        or _clean_contact_text(contact.document_access_notes)
    ):
        return "partial"
    return "missing"


def _snapshot_service_category(tender: TenderResponse) -> str | None:
    return (
        _clean_contact_text(tender.sector)
        or _clean_contact_text(tender.procurement_category)
        or _clean_contact_text(tender.category)
    )


def _decision_snapshot_response(
    tender: TenderResponse,
    *,
    competitor_intelligence: TenderCompetitorIntelligenceResponse,
    now: datetime | None = None,
) -> TenderDecisionSnapshotResponse:
    return TenderDecisionSnapshotResponse(
        tender_id=tender.id,
        source=tender.source_system,
        country=tender.country,
        region=tender.region,
        service_category=_snapshot_service_category(tender),
        deadline=tender.deadline,
        deadline_urgency=_deadline_urgency(tender.deadline, now=now),
        price_amount=tender.price_amount,
        price_currency=tender.price_currency,
        price_display=tender.price_display,
        document_status=tender.document_status,
        document_count=tender.document_count,
        downloadable_document_count=tender.downloadable_document_count,
        missing_file_document_count=tender.missing_file_document_count,
        parsed_document_count=tender.parsed_document_count,
        contact_availability=_contact_availability(tender.contact_submission),
        competitor_intelligence_status=(
            "available" if competitor_intelligence.groups else "unavailable"
        ),
        compliance_availability=(
            "available" if tender.compliance_analysis_available else "unavailable"
        ),
        source_notice_available=bool(tender.source_url),
    )


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
        "rtf": "application/rtf",
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
    resolved_path = normalize_storage_path(storage_path)
    stored_name = resolved_path.name if resolved_path is not None else ""
    prefix, _, remainder = stored_name.partition("_")
    if len(prefix) == 32 and remainder:
        return remainder
    return stored_name or "document.bin"


_TRACE_FILE_MARKER_RE = re.compile(r"\[\[FILE:\s*([^\]\n]+?)\s*\]\]")


def _filename_from_document_url(file_url: str) -> str | None:
    file_path = _extract_remote_file_path(file_url)
    filename = Path(file_path).name if file_path else ""
    return filename or None


def _giz_inner_display_name_from_document_url(file_url: str | None) -> str | None:
    raw_value = (file_url or "").strip()
    if not raw_value:
        return None
    parsed = urlparse(raw_value)
    if not parsed.fragment.startswith("giz-inner="):
        return None
    inner_path = unquote(parsed.fragment.split("=", 1)[1]).strip("/")
    if not inner_path:
        return None
    archive_name = Path(parsed.path).name
    return f"{archive_name}!/{inner_path}" if archive_name else inner_path


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


def _document_storage_file_exists(doc: TenderDocument) -> bool:
    return storage_file_exists(doc.storage_path)


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
    if raw_status == "failed":
        return "failed"
    if raw_status == "processing":
        return "processing"
    if raw_status == "access_required":
        return "access_required"
    if raw_status == "metadata_only":
        return "metadata_only"
    if _document_has_storage_path(doc):
        return "available" if _document_storage_file_exists(doc) else "missing_file"
    if raw_status in AVAILABLE_DOCUMENT_STATUSES:
        if _legacy_uzex_document_can_use_plasma_route(
            doc,
            source_system=source_system,
        ):
            return "available"
        return "missing_file"
    if _legacy_uzex_document_can_use_plasma_route(
        doc,
        source_system=source_system,
    ):
        return "available"
    return "metadata_only"


def _document_response(
    doc: TenderDocument,
    *,
    source_system: str | None = None,
) -> TenderDocumentResponse:
    document_url = doc.source_document_url or doc.file_url
    inner_display_name = _giz_inner_display_name_from_document_url(document_url)
    original_filename = inner_display_name or _filename_from_document_url(document_url)
    storage_filename = _stored_download_name(doc.storage_path) if doc.storage_path else None
    display_name = (
        storage_filename if _has_filename_extension(storage_filename) else None
    ) or inner_display_name or original_filename or storage_filename or (
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
        analysis_text_available=bool(doc.parsed_text and doc.parsed_text.strip()),
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


def _public_coverage_metadata_payload(
    coverage_metadata: dict[str, Any] | None,
    *,
    include_debug: bool = False,
) -> dict[str, Any] | None:
    if coverage_metadata is None:
        return None
    payload = dict(coverage_metadata)
    if not include_debug:
        payload.pop("technical_warnings", None)
    return payload


def _giz_document_coverage_payload(tender: Tender) -> dict[str, Any] | None:
    if tender.source_system != "giz":
        return None
    metadata = tender.source_metadata_json or {}
    coverage = metadata.get("giz_document_coverage")
    return dict(coverage) if isinstance(coverage, dict) else None


def _merge_giz_document_coverage(
    coverage_metadata: dict[str, Any],
    *,
    tender: Tender,
    analysis_warnings: list[str],
) -> dict[str, Any]:
    giz_coverage = _giz_document_coverage_payload(tender)
    if not giz_coverage:
        return coverage_metadata

    merged = dict(coverage_metadata)
    source_status = str(giz_coverage.get("coverage_status") or "").casefold()
    merged["source_document_coverage"] = giz_coverage
    coverage_warnings = list(merged.get("coverage_warnings") or [])
    for warning in giz_coverage.get("coverage_warnings") or []:
        if warning not in coverage_warnings:
            coverage_warnings.append(warning)
        if warning not in analysis_warnings:
            analysis_warnings.append(warning)
    if source_status in {"failed", "unavailable"}:
        merged["coverage_status"] = "failed"
    elif source_status == "partial" and merged.get("coverage_status") != "failed":
        merged["coverage_status"] = "partial"
    merged["coverage_warnings"] = coverage_warnings
    return merged


def _failed_analysis_evaluation_payload(
    evaluation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if evaluation is None:
        return None
    payload = dict(evaluation)
    payload["is_compliant"] = False
    payload["status_message"] = FAILED_EXTRACTION_STATUS_MESSAGE
    return payload


def _failed_analysis_hybrid_payload(
    hybrid_compliance: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if hybrid_compliance is None:
        return None
    payload = dict(hybrid_compliance)
    payload["is_eligible"] = False
    payload["verdict_status"] = ComplianceVerdictStatus.NEEDS_REVIEW.value
    payload["status_message"] = FAILED_EXTRACTION_STATUS_MESSAGE
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
    analysis_status = str(cached_data.get("analysis_status") or "completed")
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

    if analysis_status == "failed":
        cached_eval = cached_eval.model_copy(
            update={
                "is_compliant": False,
                "status_message": FAILED_EXTRACTION_STATUS_MESSAGE,
            }
        )
        if cached_hybrid is not None:
            cached_hybrid = cached_hybrid.model_copy(
                update={
                    "is_eligible": False,
                    "verdict_status": ComplianceVerdictStatus.NEEDS_REVIEW,
                    "status_message": FAILED_EXTRACTION_STATUS_MESSAGE,
                }
            )

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
        "coverage_metadata": _public_coverage_metadata_payload(
            cached_data.get("coverage_metadata"),
            include_debug=include_debug,
        ),
        "analysis_status": analysis_status,
        "extraction_error": cached_data.get("extraction_error"),
    }


@router.post("/{tender_id}/analyze", response_model=AnalyzeTenderResponse)
async def analyze_tender(
    tender_id: UUID,
    force: bool = False,
    current_user: User = Depends(require_approved_pilot_access),
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

    if not is_tender_actionable(tender):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=TENDER_NOT_ACTIONABLE_DETAIL,
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
        source_coverage_cache_str = json.dumps(
            _giz_document_coverage_payload(tender) or {},
            sort_keys=True,
            separators=(",", ":"),
        )
        hash_input = (
            f"{EXTRACTOR_SCHEMA_VERSION}|{tender_text}|"
            f"{sorted_cred_str}|{sorted_tax_str}|{vault_cache_str}|"
            f"{source_coverage_cache_str}"
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
        coverage_metadata = _merge_giz_document_coverage(
            coverage_metadata,
            tender=tender,
            analysis_warnings=analysis_warnings,
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
        giz_source_coverage_status = ""
        if isinstance(coverage_metadata.get("source_document_coverage"), dict):
            giz_source_coverage_status = str(
                coverage_metadata["source_document_coverage"].get("coverage_status") or ""
            ).casefold()
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
                is_eligible=False,
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
                status_message=FAILED_EXTRACTION_STATUS_MESSAGE,
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
            if (
                tender.source_system == "giz"
                and giz_source_coverage_status == "partial"
                and hybrid_result.verdict_status == ComplianceVerdictStatus.COMPLIANT
            ):
                hybrid_result = hybrid_result.model_copy(
                    update={
                        "verdict_status": ComplianceVerdictStatus.ELIGIBLE_WITH_REVIEW,
                        "status_message": (
                            "ELIGIBLE WITH REVIEW — GIZ document coverage is partial; "
                            "manual review is required before relying on this result."
                        ),
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
        "coverage_metadata": _public_coverage_metadata_payload(
            coverage_metadata,
            include_debug=current_user.is_admin,
        ),
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
    current_user: User = Depends(require_approved_pilot_access),
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

    local_path = normalize_storage_path(doc.storage_path)

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
    source: str | None = Query(default=None),
    source_system: str | None = Query(default=None),
    q: str | None = Query(default=None),
    region: list[str] | None = Query(default=None),
    country: str | None = Query(default=None),
    countries: list[str] | None = Query(default=None),
    service: str | None = Query(default=None),
    services: list[str] | None = Query(default=None),
    tender_status: str | None = Query(default=None, alias="status"),
    deadline_status: str | None = Query(default=None),
    deadline_from: datetime | None = Query(default=None),
    deadline_to: datetime | None = Query(default=None),
    price_min: float | None = Query(default=None, ge=0),
    price_max: float | None = Query(default=None, ge=0),
    document_status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    sort: str | None = Query(default="newest"),
    db: AsyncSession = Depends(get_db),
) -> list[TenderResponse]:
    """
    List customer-visible tenders with explorer filters.

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
            Tender.source_metadata_json,
            Tender.status,
            Tender.category,
            Tender.created_at,
        )
    ).where(customer_visible_tender_condition(Tender))
    try:
        lifecycle_condition = _tender_lifecycle_condition(tender_status)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    if lifecycle_condition is not None:
        query = query.where(lifecycle_condition)
    normalized_source = _normalize_tender_source_filter(source_system or source)
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

    normalized_regions = _normalize_region_filter(region)
    normalized_countries = _normalize_list_filter(
        [*(_split_query_values(country)), *(_split_query_values(countries))],
        label="country",
    )
    region_countries = _expanded_region_countries(normalized_regions)
    country_predicates = []
    if normalized_countries:
        country_predicates.append(_country_predicate(normalized_countries))
    if region_countries:
        country_predicates.append(_country_predicate(region_countries))
    for selected_region in normalized_regions:
        if selected_region != CENTRAL_ASIA_REGION:
            country_predicates.append(Tender.region.ilike(f"%{selected_region}%"))
    if country_predicates:
        query = query.where(or_(*country_predicates))

    normalized_services = _normalize_service_filter(
        [*(_split_query_values(service)), *(_split_query_values(services))]
    )
    if normalized_services:
        query = query.where(_service_predicate(normalized_services))

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
    if deadline_from is not None:
        query = query.where(Tender.deadline.is_not(None), Tender.deadline >= deadline_from)
    if deadline_to is not None:
        query = query.where(Tender.deadline.is_not(None), Tender.deadline <= deadline_to)
    if price_min is not None:
        query = query.where(Tender.budget >= price_min)
    if price_max is not None:
        query = query.where(Tender.budget <= price_max)
    if price_min is not None and price_max is not None and price_min > price_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="price_min cannot be greater than price_max",
        )

    normalized_document_status = (document_status or "").strip().casefold()
    if normalized_document_status:
        if normalized_document_status in {"all", "any"}:
            normalized_document_status = ""
        elif normalized_document_status not in DOCUMENT_STATUS_FILTERS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported document_status",
            )
    if normalized_document_status and normalized_document_status != "files_missing":
        query = query.where(_document_status_predicate(normalized_document_status))

    category_filter = (category or "").strip()
    if category_filter and category_filter.casefold() not in {"all", "any"}:
        pattern = f"%{category_filter}%"
        query = query.where(
            or_(
                Tender.sector.ilike(pattern),
                Tender.procurement_category.ilike(pattern),
                Tender.category.ilike(pattern),
                Tender.procurement_method.ilike(pattern),
                Tender.notice_type.ilike(pattern),
                Tender.title.ilike(pattern),
                Tender.description.ilike(pattern),
            )
        )

    query = (
        _apply_tender_sort(query, sort)
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

    serialized_tenders = [
        _serialize_tender(t, summary=summaries.get(t.id))
        for t in tenders
    ]
    if normalized_document_status:
        serialized_tenders = [
            tender
            for tender in serialized_tenders
            if tender.document_status == normalized_document_status
        ]
    return serialized_tenders


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
                Tender.source_metadata_json,
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
    contact_metadata_override = (
        await _world_bank_contact_metadata_override(tender)
        or await _adb_contact_metadata_override(tender)
        or await _uzex_contact_metadata_override(tender)
        or await _giz_contact_metadata_override(tender)
    )
    return _serialize_tender(
        tender,
        summary=summary,
        include_contact_metadata=True,
        contact_metadata_override=contact_metadata_override,
    )


async def _build_tender_competitor_intelligence(
    *,
    db: AsyncSession,
    target_tender: Tender,
) -> TenderCompetitorIntelligenceResponse:
    target_service_category = _infer_tender_service_category(target_tender)
    related_query = (
        select(Tender)
        .options(
            load_only(
                Tender.id,
                Tender.external_id,
                Tender.source_system,
                Tender.source_url,
                Tender.title,
                Tender.description,
                Tender.country,
                Tender.sector,
                Tender.buyer,
                Tender.procurement_category,
                Tender.procurement_method,
                Tender.notice_type,
                Tender.category,
                Tender.publication_date,
                Tender.created_at,
                Tender.source_metadata_json,
            )
        )
        .where(
            Tender.id != target_tender.id,
            Tender.source_metadata_json.is_not(None),
            customer_visible_tender_condition(Tender),
        )
    )

    if target_service_category != "other":
        related_query = related_query.where(
            _service_predicate([target_service_category])
        )
    else:
        fallback_predicates = []
        target_buyer = _meaningful_competitor_filter_text(target_tender.buyer)
        target_sector = _meaningful_competitor_filter_text(target_tender.sector)
        target_category = _meaningful_competitor_filter_text(
            target_tender.procurement_category or target_tender.category
        )
        if target_buyer:
            fallback_predicates.append(Tender.buyer.ilike(target_buyer))
        if target_sector:
            fallback_predicates.append(Tender.sector.ilike(f"%{target_sector}%"))
        if target_category:
            fallback_predicates.append(
                or_(
                    Tender.procurement_category.ilike(f"%{target_category}%"),
                    Tender.category.ilike(f"%{target_category}%"),
                )
            )
        if not fallback_predicates:
            return TenderCompetitorIntelligenceResponse(
                tender_id=target_tender.id,
                message=COMPETITOR_EMPTY_MESSAGE,
                groups=[],
            )
        related_query = related_query.where(or_(*fallback_predicates))

    related_result = await db.execute(
        related_query.order_by(
            func.coalesce(Tender.publication_date, Tender.created_at).desc(),
            Tender.created_at.desc(),
        ).limit(COMPETITOR_MAX_RELATED_TENDERS)
    )
    records: list[TenderCompetitorResponse] = []
    for related_tender in related_result.scalars().all():
        records.extend(
            _extract_public_competitor_records(
                target_tender=target_tender,
                related_tender=related_tender,
                target_service_category=target_service_category,
            )
        )
    records.extend(
        await _live_source_competitor_records(
            target_tender=target_tender,
            target_service_category=target_service_category,
        )
    )

    groups = _group_competitor_records(records)
    return TenderCompetitorIntelligenceResponse(
        tender_id=target_tender.id,
        message=COMPETITOR_AVAILABLE_MESSAGE if groups else COMPETITOR_EMPTY_MESSAGE,
        groups=groups,
    )


@router.get(
    "/{tender_id}/decision-snapshot",
    response_model=TenderDecisionSnapshotResponse,
)
async def get_tender_decision_snapshot(
    tender_id: UUID,
    current_user: User = Depends(require_approved_pilot_access),
    db: AsyncSession = Depends(get_db),
) -> TenderDecisionSnapshotResponse:
    """
    Return compact, non-speculative decision-support facts for tender detail.
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
                Tender.source_metadata_json,
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
    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )

    summary = await _single_tender_summary(db=db, tender_id=tender.id)
    await _apply_live_uzex_dates([tender])
    contact_metadata_override = (
        await _world_bank_contact_metadata_override(tender)
        or await _adb_contact_metadata_override(tender)
        or await _uzex_contact_metadata_override(tender)
        or await _giz_contact_metadata_override(tender)
    )
    serialized_tender = _serialize_tender(
        tender,
        summary=summary,
        include_contact_metadata=True,
        contact_metadata_override=contact_metadata_override,
    )
    competitor_intelligence = await _build_tender_competitor_intelligence(
        db=db,
        target_tender=tender,
    )
    return _decision_snapshot_response(
        serialized_tender,
        competitor_intelligence=competitor_intelligence,
    )


@router.get(
    "/{tender_id}/competitors",
    response_model=TenderCompetitorIntelligenceResponse,
)
async def get_tender_competitors(
    tender_id: UUID,
    current_user: User = Depends(require_approved_pilot_access),
    db: AsyncSession = Depends(get_db),
) -> TenderCompetitorIntelligenceResponse:
    """
    Return conservative competitor intelligence for a visible tender.

    The response is derived only from whitelisted public historical source
    metadata. It does not confirm participation in the current tender.
    """
    target_result = await db.execute(
        select(Tender)
        .options(
            load_only(
                Tender.id,
                Tender.external_id,
                Tender.source_system,
                Tender.source_url,
                Tender.title,
                Tender.description,
                Tender.country,
                Tender.sector,
                Tender.buyer,
                Tender.procurement_category,
                Tender.procurement_method,
                Tender.notice_type,
                Tender.category,
            )
        )
        .where(
            Tender.id == tender_id,
            customer_visible_tender_condition(Tender),
        )
    )
    target_tender = target_result.scalar_one_or_none()
    if target_tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )

    return await _build_tender_competitor_intelligence(
        db=db,
        target_tender=target_tender,
    )


@router.get("/{tender_id}/compiled-text", response_model=TenderCompiledTextResponse)
async def get_tender_compiled_text(
    tender_id: UUID,
    current_user: User = Depends(require_approved_pilot_access),
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


async def _sync_uzex_tenders(
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
            status="source_unavailable",
            new_count=0,
            updated_count=0,
            message=f"Portal temporarily unavailable. Existing tenders are still shown. ({type(e).__name__})",
        )


@router.post("/refresh", response_model=SourceRefreshResponse)
async def refresh_tenders(
    force: bool = Query(default=False),
    current_user: User = Depends(require_approved_user),
    db: AsyncSession = Depends(get_db),
) -> SourceRefreshResponse:
    """Request a customer-safe UzEx refresh."""
    return await _request_source_refresh(
        source_system="uzex",
        force=force,
        current_user=current_user,
        db=db,
    )


@router.post(
    "/sources/world-bank/sync",
    response_model=SourceSyncResponse,
    dependencies=[Depends(require_operator_or_admin)],
)
async def sync_world_bank_tenders(
    max_pages: int = Query(default=25, ge=1, le=100),
    rows: int = Query(default=100, ge=1, le=100),
    active_only: bool = Query(default=True),
    dry_run: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> SourceSyncResponse:
    """
    Import World Bank procurement notices via the official procnotices API.
    """
    sync_started = monotonic()
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
    lifecycle_closed_count = 0
    skip_reasons: Counter[str] = Counter()

    try:
        raw_notices = await source.list_opportunities()
    except Exception as exc:
        failure = connector_failure_details(exc)
        logger.exception("world_bank_sync_fetch_failed")
        return SourceSyncResponse(
            status=failure.status,
            source_system=source.source_system,
            failed_count=1,
            dry_run=dry_run,
            failure_stage="listing",
            failure_class=failure.failure_class,
            retryable=failure.retryable,
            elapsed_ms=int((monotonic() - sync_started) * 1000),
            errors=[type(exc).__name__],
            message=safe_failure_message("World Bank", "listing", exc),
        )

    fetched_count = len(raw_notices) + source.last_duplicate_count
    if source.last_duplicate_count:
        skipped_count += source.last_duplicate_count
        skip_reasons["duplicate"] += source.last_duplicate_count
    for raw_notice in raw_notices:
        external_id = str(raw_notice.get("id") or "").strip()
        try:
            if not source.should_import(raw_notice):
                skipped_count += 1
                skip_reasons[source.skip_reason(raw_notice) or "non_actionable_notice"] += 1
                continue

            normalized = source.normalize(raw_notice)
            documents = await source.discover_documents(normalized)
            attachment_count += len(documents)

            if dry_run:
                continue

            tender, created = await source.upsert(db, normalized)
            await db.flush()
            if documents:
                await source.upsert_documents(
                    db,
                    tender=tender,
                    documents=documents,
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

    try:
        lifecycle_closed_count = await reconcile_past_deadline_open_tenders(
            db,
            source_system="world_bank",
        )
        updated_count += lifecycle_closed_count
    except Exception as exc:
        failed_count += 1
        errors.append(f"lifecycle: {type(exc).__name__}")
        logger.exception("world_bank_lifecycle_reconciliation_failed")

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

    status_value = (
        "success"
        if failed_count == 0 and not source.last_truncated
        else "partial"
    )
    if source.last_truncated:
        errors.insert(0, "pagination: safety_cap_or_repeated_page")
    return SourceSyncResponse(
        status=status_value,
        source_system=source.source_system,
        fetched_count=fetched_count,
        created_count=created_count,
        updated_count=updated_count,
        skipped_count=skipped_count,
        rejected_count=skipped_count + failed_count,
        failed_count=failed_count,
        attachment_count=attachment_count,
        dry_run=dry_run,
        skip_reasons=dict(skip_reasons),
        elapsed_ms=int((monotonic() - sync_started) * 1000),
        source_newest_published_at=source.source_newest_published_at,
        source_oldest_published_at=source.source_oldest_published_at,
        errors=errors,
        message=(
            "World Bank sync dry run completed."
            if dry_run
            else (
                "World Bank sync completed: "
                f"{created_count} created, {updated_count} updated, "
                f"{skipped_count} skipped, {failed_count} failed; "
                f"{lifecycle_closed_count} lifecycle row(s) closed; "
                f"{source.last_pages_fetched} page(s) fetched"
                + ("; coverage truncated." if source.last_truncated else ".")
            )
        ),
    )


def _giz_payload_looks_like_html(file_bytes: bytes) -> bool:
    head = file_bytes[:512].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html", b"<head", b"<body")) or b"<html" in head[:200]


GIZ_PARSEABLE_DOCUMENT_EXTENSIONS = {"pdf", "docx", "txt"}
GIZ_ARCHIVE_DOCUMENT_EXTENSIONS = {"zip"}
GIZ_DANGEROUS_DOCUMENT_EXTENSIONS = {
    "app",
    "bat",
    "bin",
    "cmd",
    "com",
    "cpl",
    "dll",
    "dmg",
    "exe",
    "hta",
    "jar",
    "js",
    "jse",
    "msi",
    "msp",
    "pif",
    "ps1",
    "scr",
    "sh",
    "vbe",
    "vbs",
    "wsf",
}
GIZ_MAX_COMPRESSION_RATIO = 100


def _giz_archive_limits_payload() -> dict[str, int]:
    return {
        "max_compressed_archive_bytes": GIZ_MAX_ARCHIVE_COMPRESSED_BYTES,
        "max_extracted_bytes": GIZ_MAX_ARCHIVE_EXTRACTED_BYTES,
        "max_file_count": GIZ_MAX_ARCHIVE_FILE_COUNT,
        "max_individual_file_bytes": GIZ_MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES,
        "max_nesting_depth": GIZ_MAX_ARCHIVE_NESTING_DEPTH,
        "max_compression_ratio": GIZ_MAX_COMPRESSION_RATIO,
    }


def _giz_official_listed_document_count(tender: Tender) -> int:
    metadata = tender.source_metadata_json or {}
    participation_documents = metadata.get("participation_documents")
    if isinstance(participation_documents, list):
        return len(participation_documents)
    attachments = metadata.get("attachments")
    if isinstance(attachments, list):
        return len(attachments)
    return 0


def _giz_inner_source_url(archive_doc: TenderDocument, inner_path: str) -> str:
    base_url = (archive_doc.source_document_url or archive_doc.file_url or "").split("#", 1)[0]
    digest = hashlib.sha256(f"{base_url}|{inner_path}".encode("utf-8")).hexdigest()[:16]
    quoted_path = quote(inner_path, safe="/")
    candidate = f"{base_url}#giz-inner={quoted_path}"
    if len(candidate) <= 1000:
        return candidate
    return f"{base_url}#giz-inner-sha={digest}"


def _giz_file_url_for_source(source_url: str) -> str:
    if len(source_url) <= 500:
        return source_url
    base_url = source_url.split("#", 1)[0]
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16]
    return f"{base_url[:470]}#giz-inner-sha={digest}"


def _giz_zip_member_name(raw_name: str) -> str | None:
    normalized = raw_name.replace("\\", "/").strip()
    if not normalized or normalized.endswith("/"):
        return None
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return None
    path = PurePosixPath(normalized)
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return str(path)


def _giz_zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def _giz_archive_member_extension(member_name: str) -> str:
    return Path(member_name).suffix.lower().lstrip(".")


def _giz_member_storage_filename(*, archive_name: str, inner_path: str) -> str:
    safe_inner = re.sub(r"[^A-Za-z0-9._-]+", "_", inner_path).strip("._")
    return f"{Path(archive_name).stem}__{safe_inner or Path(inner_path).name}"


def _giz_relabel_parsed_text(parsed_text: str, source_label: str) -> str:
    marker = f"[[FILE: {source_label}]]"
    relabeled = _TRACE_FILE_MARKER_RE.sub(marker, parsed_text)
    if "[[PAGE" not in relabeled:
        relabeled = f"{marker}\n[[PAGE 1]]\n{relabeled.strip()}"
    return relabeled.strip()


async def _giz_upsert_inner_document(
    db: AsyncSession,
    *,
    tender: Tender,
    archive_doc: TenderDocument,
    inner_path: str,
    file_type: str,
    file_size: int | None = None,
) -> TenderDocument:
    source_url = _giz_inner_source_url(archive_doc, inner_path)
    result = await db.execute(
        select(TenderDocument).where(
            TenderDocument.tender_id == tender.id,
            TenderDocument.source_document_url == source_url,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        doc = TenderDocument(
            tender_id=tender.id,
            file_url=_giz_file_url_for_source(source_url),
            file_type=file_type or "unknown",
            source_document_url=source_url,
            source_document_type=file_type or "unknown",
            external_file_id=hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:32],
            download_status="metadata_only",
            file_size=file_size,
            mime_type=_guess_download_content_type(
                filename=Path(inner_path).name,
                file_type=file_type or None,
            ),
        )
        db.add(doc)
        await db.flush()
    else:
        doc.file_type = file_type or doc.file_type or "unknown"
        doc.source_document_type = file_type or doc.source_document_type
        if file_size is not None:
            doc.file_size = file_size
        if not doc.mime_type:
            doc.mime_type = _guess_download_content_type(
                filename=Path(inner_path).name,
                file_type=file_type or None,
            )
    return doc


async def _giz_find_duplicate_document_by_sha(
    db: AsyncSession,
    *,
    tender: Tender,
    sha256_digest: str,
    excluding_doc_id: UUID,
) -> TenderDocument | None:
    result = await db.execute(
        select(TenderDocument)
        .where(
            TenderDocument.tender_id == tender.id,
            TenderDocument.id != excluding_doc_id,
            TenderDocument.sha256 == sha256_digest,
            TenderDocument.storage_path.is_not(None),
        )
        .order_by(TenderDocument.created_at.asc(), TenderDocument.id.asc())
        .limit(1)
    )
    duplicate = result.scalar_one_or_none()
    if duplicate is not None and storage_file_exists(duplicate.storage_path):
        return duplicate
    return None


def _giz_mark_document_failed(doc: TenderDocument, message: str) -> None:
    doc.download_status = "failed"
    doc.download_error = message[:1000]


async def _giz_parse_stored_document(
    *,
    doc: TenderDocument,
    source_label: str,
) -> bool:
    previous_error = doc.download_error or ""
    if (doc.download_status or "").casefold() == "failed" and (
        previous_error.startswith("Unsupported GIZ")
        or previous_error.startswith("GIZ document parsed to empty text")
        or previous_error.startswith("GIZ document exceeds the individual")
    ):
        return False
    extension = (doc.file_type or Path(source_label).suffix.lstrip(".")).strip().casefold()
    if extension not in GIZ_PARSEABLE_DOCUMENT_EXTENSIONS:
        _giz_mark_document_failed(
            doc,
            f"Unsupported GIZ document type for parsing: {extension or 'unknown'}.",
        )
        return False
    local_path = normalize_storage_path(doc.storage_path)
    if local_path is None or not local_path.is_file():
        _giz_mark_document_failed(doc, "GIZ document file is missing from storage.")
        return False
    if local_path.stat().st_size > GIZ_MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES:
        _giz_mark_document_failed(doc, "GIZ document exceeds the individual file parsing limit.")
        return False
    if doc.parsed_text and doc.parsed_text.strip():
        doc.download_status = "downloaded"
        doc.download_error = None
        return False

    file_bytes = await asyncio.to_thread(local_path.read_bytes)
    parsed_text = await process_tender_document(file_bytes, filename=source_label)
    if not parsed_text.strip():
        _giz_mark_document_failed(doc, "GIZ document parsed to empty text.")
        return False

    doc.parsed_text = _giz_relabel_parsed_text(parsed_text, source_label)
    doc.download_status = "downloaded"
    doc.download_error = None
    return True


def _giz_zip_member_rejection_reason(
    info: zipfile.ZipInfo,
    *,
    safe_name: str | None,
    current_depth: int,
) -> str | None:
    if safe_name is None:
        return "Rejected unsafe ZIP member path."
    if _giz_zip_member_is_symlink(info):
        return "Rejected ZIP symlink member."
    extension = _giz_archive_member_extension(safe_name)
    if extension in GIZ_DANGEROUS_DOCUMENT_EXTENSIONS:
        return f"Rejected executable or script member: .{extension}."
    if extension in GIZ_ARCHIVE_DOCUMENT_EXTENSIONS and current_depth >= GIZ_MAX_ARCHIVE_NESTING_DEPTH:
        return "Rejected nested archive beyond the allowed GIZ nesting depth."
    if info.file_size > GIZ_MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES:
        return "Rejected ZIP member above the GIZ individual file size limit."
    if info.compress_size > 0 and info.file_size / info.compress_size > GIZ_MAX_COMPRESSION_RATIO:
        return "Rejected ZIP member with excessive compression ratio."
    return None


async def _giz_extract_supported_zip_members(
    db: AsyncSession,
    *,
    tender: Tender,
    archive_doc: TenderDocument,
    current_depth: int = 0,
) -> None:
    archive_path = normalize_storage_path(archive_doc.storage_path)
    if archive_path is None or not archive_path.is_file():
        _giz_mark_document_failed(archive_doc, "GIZ ZIP archive is missing from storage.")
        return
    compressed_size = archive_path.stat().st_size
    if compressed_size > GIZ_MAX_ARCHIVE_COMPRESSED_BYTES:
        _giz_mark_document_failed(archive_doc, "GIZ ZIP archive exceeds the compressed size limit.")
        return

    archive_name = Path(archive_doc.source_document_url or archive_doc.file_url or archive_path.name).name
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if len(infos) > GIZ_MAX_ARCHIVE_FILE_COUNT:
                _giz_mark_document_failed(archive_doc, "GIZ ZIP archive exceeds the file count limit.")
                return
            total_uncompressed = sum(max(0, info.file_size) for info in infos)
            total_compressed = sum(max(0, info.compress_size) for info in infos)
            if total_uncompressed > GIZ_MAX_ARCHIVE_EXTRACTED_BYTES:
                _giz_mark_document_failed(archive_doc, "GIZ ZIP archive exceeds the extracted size limit.")
                return
            if total_compressed > 0 and total_uncompressed / total_compressed > GIZ_MAX_COMPRESSION_RATIO:
                _giz_mark_document_failed(archive_doc, "GIZ ZIP archive has excessive compression ratio.")
                return

            for info in infos:
                safe_name = _giz_zip_member_name(info.filename)
                file_type = _giz_archive_member_extension(safe_name or info.filename) or "unknown"
                inner_doc = await _giz_upsert_inner_document(
                    db,
                    tender=tender,
                    archive_doc=archive_doc,
                    inner_path=safe_name or info.filename,
                    file_type=file_type,
                    file_size=max(0, info.file_size),
                )
                rejection_reason = _giz_zip_member_rejection_reason(
                    info,
                    safe_name=safe_name,
                    current_depth=current_depth,
                )
                if rejection_reason:
                    _giz_mark_document_failed(inner_doc, rejection_reason)
                    continue
                if file_type not in GIZ_PARSEABLE_DOCUMENT_EXTENSIONS:
                    _giz_mark_document_failed(
                        inner_doc,
                        f"Unsupported GIZ archive member type for parsing: {file_type}.",
                    )
                    continue
                if storage_file_exists(inner_doc.storage_path):
                    await _giz_parse_stored_document(
                        doc=inner_doc,
                        source_label=f"{archive_name}!/{safe_name}",
                    )
                    continue

                storage_filename = _giz_member_storage_filename(
                    archive_name=archive_name,
                    inner_path=safe_name,
                )
                temp_path, final_path = _reserve_document_download_path(
                    tender_id=tender.id,
                    filename=storage_filename,
                )
                try:
                    total_written = 0
                    with archive.open(info) as source_handle, Path(temp_path).open("wb") as target_handle:
                        while True:
                            chunk = source_handle.read(1024 * 1024)
                            if not chunk:
                                break
                            total_written += len(chunk)
                            if total_written > GIZ_MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES:
                                raise ValueError("ZIP member exceeded individual extraction limit")
                            target_handle.write(chunk)
                    storage_path, file_size, sha256_digest = _finalize_document_download(
                        temp_path=temp_path,
                        final_path=final_path,
                    )
                except Exception as exc:
                    _cleanup_temp_download(temp_path)
                    _giz_mark_document_failed(
                        inner_doc,
                        f"GIZ ZIP member extraction failed: {type(exc).__name__}.",
                    )
                    continue

                duplicate = await _giz_find_duplicate_document_by_sha(
                    db,
                    tender=tender,
                    sha256_digest=sha256_digest,
                    excluding_doc_id=inner_doc.id,
                )
                if duplicate is not None:
                    try:
                        Path(storage_path).unlink(missing_ok=True)
                    except OSError:
                        logger.warning("Failed to remove duplicate GIZ extracted file: %s", storage_path)
                    inner_doc.storage_path = duplicate.storage_path
                    inner_doc.file_size = duplicate.file_size
                    inner_doc.mime_type = duplicate.mime_type
                    inner_doc.sha256 = duplicate.sha256
                else:
                    inner_doc.storage_path = storage_path
                    inner_doc.file_size = file_size
                    inner_doc.sha256 = sha256_digest
                    inner_doc.mime_type = _guess_download_content_type(
                        filename=safe_name,
                        file_type=file_type,
                    )
                inner_doc.download_status = "downloaded"
                inner_doc.download_error = None
                await _giz_parse_stored_document(
                    doc=inner_doc,
                    source_label=f"{archive_name}!/{safe_name}",
                )
    except zipfile.BadZipFile:
        _giz_mark_document_failed(archive_doc, "GIZ ZIP archive is corrupted or unreadable.")
    except Exception as exc:
        _giz_mark_document_failed(
            archive_doc,
            f"GIZ ZIP archive processing failed: {type(exc).__name__}.",
        )


async def _update_giz_document_coverage(
    db: AsyncSession,
    *,
    tender: Tender,
) -> dict[str, Any]:
    result = await db.execute(
        select(TenderDocument).where(TenderDocument.tender_id == tender.id)
    )
    docs = result.scalars().all()
    official_count = _giz_official_listed_document_count(tender)
    inner_docs = [
        doc
        for doc in docs
        if "#giz-inner=" in (doc.source_document_url or doc.file_url or "")
        or "#giz-inner-sha=" in (doc.source_document_url or doc.file_url or "")
    ]
    parsed_count = sum(1 for doc in docs if doc.parsed_text and doc.parsed_text.strip())
    unsupported_count = sum(
        1
        for doc in docs
        if "Unsupported GIZ" in (doc.download_error or "")
        or "Rejected executable" in (doc.download_error or "")
        or "Rejected nested archive" in (doc.download_error or "")
    )
    failed_count = sum(
        1
        for doc in docs
        if (doc.download_status or "").casefold() == "failed"
        and "Unsupported GIZ" not in (doc.download_error or "")
    )
    processed_count = parsed_count + unsupported_count + failed_count
    missing_count = max(official_count - processed_count, 0)

    if official_count == 0 and not docs:
        coverage_status = "unavailable"
    elif parsed_count == 0 and (failed_count or unsupported_count or docs):
        coverage_status = "failed"
    elif failed_count or unsupported_count or missing_count:
        coverage_status = "partial"
    else:
        coverage_status = "complete"

    warnings: list[str] = []
    if unsupported_count:
        warnings.append(f"{unsupported_count} GIZ document(s) are unsupported for parsing.")
    if failed_count:
        warnings.append(f"{failed_count} GIZ document(s) failed download, extraction, or parsing.")
    if missing_count:
        warnings.append(f"{missing_count} official GIZ document(s) are not yet parsed.")

    coverage = {
        "coverage_status": coverage_status,
        "official_listed_document_count": official_count,
        "extracted_file_count": len(inner_docs),
        "parsed_file_count": parsed_count,
        "unsupported_file_count": unsupported_count,
        "failed_file_count": failed_count,
        "missing_file_count": missing_count,
        "limits": _giz_archive_limits_payload(),
        "coverage_warnings": warnings,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    metadata = dict(tender.source_metadata_json or {})
    metadata["giz_document_coverage"] = coverage
    tender.source_metadata_json = metadata
    return coverage


def _giz_rejected_payload_content_type(content_type: str | None) -> bool:
    normalized = (content_type or "").split(";", 1)[0].strip().casefold()
    if not normalized:
        return False
    if "html" in normalized:
        return True
    return normalized in {"application/json", "text/json", "text/plain"}


def _giz_valid_file_signature(
    file_bytes: bytes,
    extension: str,
    content_type: str | None,
) -> bool:
    head = file_bytes[:16]
    ext = extension.casefold()
    normalized_type = (content_type or "").split(";", 1)[0].strip().casefold()
    if ext == "pdf":
        return file_bytes.lstrip().startswith(b"%PDF") or normalized_type == "application/pdf"
    if ext == "zip":
        return head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
    if ext in {"docx", "xlsx"}:
        return head.startswith(b"PK\x03\x04")
    if ext in {"doc", "xls"}:
        return head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if ext == "rtf":
        return file_bytes.lstrip().startswith(b"{\\rtf")
    return normalized_type.startswith("application/")


async def _download_giz_document_into_storage(
    *,
    client: httpx.AsyncClient,
    tender: Tender,
    doc: TenderDocument,
    max_bytes: int,
) -> bool:
    assert_source_scope("giz", tender)
    if doc.tender_id != tender.id:
        raise ValueError("GIZ document does not belong to the supplied tender")
    source_url = (doc.source_document_url or doc.file_url or "").strip()
    if "#giz-inner=" in source_url or "#giz-inner-sha=" in source_url:
        return False
    if (doc.download_status or "").strip().casefold() == "access_required":
        return False
    extension = _giz_extension_from_url(source_url)
    if not source_url or not extension or not _safe_giz_url(source_url):
        if not storage_file_exists(doc.storage_path):
            doc.download_status = doc.download_status or "metadata_only"
        return False
    if storage_file_exists(doc.storage_path):
        doc.download_status = "downloaded"
        doc.download_error = None
        return False

    request_url = source_url.split("#", 1)[0]
    filename = Path(urlparse(request_url).path).name or f"giz-document.{extension}"
    temp_path: str | None = None
    try:
        async with client.stream("GET", request_url) as response:
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip()
            content_length = response.headers.get("content-length")
            try:
                declared_length = int(content_length) if content_length else None
            except ValueError:
                declared_length = None
            if declared_length is not None and declared_length > max_bytes:
                doc.download_status = "failed"
                doc.download_error = "Public GIZ document exceeds configured download size limit."
                return False
            if _giz_rejected_payload_content_type(content_type):
                doc.download_status = "access_required" if "html" in content_type.casefold() else "failed"
                doc.download_error = "Public GIZ document URL returned a page or error payload, not a document file."
                return False

            temp_path, final_path = _reserve_document_download_path(
                tender_id=tender.id,
                filename=filename,
            )
            first_bytes = bytearray()
            total_bytes = 0
            with Path(temp_path).open("wb") as file_handle:
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        _cleanup_temp_download(temp_path)
                        doc.download_status = "failed"
                        doc.download_error = "Public GIZ document exceeds configured download size limit."
                        return False
                    if len(first_bytes) < 2048:
                        first_bytes.extend(chunk[: 2048 - len(first_bytes)])
                    file_handle.write(chunk)
    except Exception as exc:
        if temp_path:
            _cleanup_temp_download(temp_path)
        doc.download_status = "failed"
        doc.download_error = f"GIZ public document download failed: {type(exc).__name__}"
        logger.warning(
            "giz_document_download_failed tender_id=%s doc_id=%s error_type=%s",
            tender.id,
            doc.id,
            type(exc).__name__,
        )
        return False

    file_head = bytes(first_bytes)
    if total_bytes < 32:
        if temp_path:
            _cleanup_temp_download(temp_path)
        doc.download_status = "failed"
        doc.download_error = "GIZ public document download returned an empty or trivial file."
        return False
    if _giz_payload_looks_like_html(file_head):
        if temp_path:
            _cleanup_temp_download(temp_path)
        doc.download_status = "access_required"
        doc.download_error = "GIZ public document download returned HTML instead of a document."
        return False
    if not _giz_valid_file_signature(file_head, extension, content_type):
        if temp_path:
            _cleanup_temp_download(temp_path)
        doc.download_status = "failed"
        doc.download_error = "GIZ public document download did not match the expected file signature."
        return False

    storage_path, file_size, sha256_digest = await asyncio.to_thread(
        _finalize_document_download,
        temp_path=temp_path,
        final_path=final_path,
    )
    if not storage_file_exists(storage_path):
        doc.download_status = "failed"
        doc.download_error = "GIZ public document was written but is not present on disk."
        return False
    doc.storage_path = storage_path
    doc.file_size = file_size
    doc.mime_type = content_type or doc.mime_type or _guess_download_content_type(
        filename=filename,
        file_type=extension,
    )
    doc.sha256 = sha256_digest
    doc.download_status = "downloaded"
    doc.download_error = None
    return True


async def _process_giz_documents_for_compliance(
    db: AsyncSession,
    *,
    tender: Tender,
) -> dict[str, Any]:
    assert_source_scope("giz", tender)
    result = await db.execute(
        select(TenderDocument)
        .where(TenderDocument.tender_id == tender.id)
        .order_by(TenderDocument.source_document_url.asc(), TenderDocument.id.asc())
    )
    docs = result.scalars().all()
    for doc in docs:
        source_url = doc.source_document_url or doc.file_url or ""
        if "#giz-inner=" in source_url or "#giz-inner-sha=" in source_url:
            if storage_file_exists(doc.storage_path):
                archive_name = Path(urlparse(source_url.split("#", 1)[0]).path).name
                if "#giz-inner=" in source_url:
                    inner_name = unquote(source_url.split("#giz-inner=", 1)[-1])
                    source_label = f"{archive_name}!/{inner_name}" if archive_name else inner_name
                else:
                    source_label = _stored_download_name(doc.storage_path or "")
                await _giz_parse_stored_document(doc=doc, source_label=source_label)
            continue
        extension = (doc.file_type or _giz_extension_from_url(source_url) or "").casefold()
        if extension in GIZ_ARCHIVE_DOCUMENT_EXTENSIONS and storage_file_exists(doc.storage_path):
            await _giz_extract_supported_zip_members(db, tender=tender, archive_doc=doc)
        elif storage_file_exists(doc.storage_path):
            display_name = Path(urlparse(source_url).path).name or _stored_download_name(doc.storage_path or "")
            await _giz_parse_stored_document(doc=doc, source_label=display_name)

    coverage = await _update_giz_document_coverage(db, tender=tender)
    await _compile_tender_text_from_documents(db=db, tender=tender)
    return coverage


async def _compile_tender_text_from_documents(
    *,
    db: AsyncSession,
    tender: Tender,
) -> None:
    result = await db.execute(
        select(TenderDocument)
        .where(TenderDocument.tender_id == tender.id)
        .order_by(TenderDocument.source_document_url.asc(), TenderDocument.id.asc())
    )
    docs = result.scalars().all()
    parsed_parts = [doc.parsed_text.strip() for doc in docs if doc.parsed_text and doc.parsed_text.strip()]
    tender.compiled_master_text = "\n\n".join(parsed_parts) if parsed_parts else None


def _giz_commit_error_message(exc: Exception) -> str:
    error_text = str(exc)
    if "ck_tenders_source_system_allowed" in error_text or "source_system" in error_text:
        return (
            "GIZ sync failed while saving tenders. "
            "Database schema does not allow source_system='giz' yet; "
            "run Alembic migration 20260702_0001_s5_1_giz_source."
        )
    return "GIZ sync failed while saving tenders."


def _giz_invalid_visibility_reason(tender: Tender) -> str | None:
    external_id = str(tender.external_id or "").strip()
    title = str(tender.title or "").strip()
    metadata = tender.source_metadata_json or {}
    if external_id.startswith("page-"):
        return "missing_official_stable_id"
    if title.casefold() in {"bidding list", "tender", "tenders", "download", "downloads"}:
        return "listing_or_download_placeholder"
    if not str(tender.source_url or "").startswith(("https://www.giz.de/", "https://ausschreibungen.giz.de/")):
        return "invalid_official_source_url"
    if not external_id or not title:
        return "missing_required_notice_identity"
    if metadata.get("giz_visibility") == "hidden":
        return str(metadata.get("giz_visibility_reason") or "previously_quarantined")
    return None


async def _quarantine_invalid_giz_tenders(db: AsyncSession) -> int:
    result = await db.execute(select(Tender).where(Tender.source_system == "giz"))
    changed = 0
    for tender in result.scalars().all():
        reason = _giz_invalid_visibility_reason(tender)
        if not reason:
            continue
        metadata = dict(tender.source_metadata_json or {})
        if (
            metadata.get("giz_visibility") == "hidden"
            and metadata.get("giz_visibility_reason") == reason
        ):
            continue
        metadata["giz_visibility"] = "hidden"
        metadata["giz_visibility_reason"] = reason
        metadata["giz_quarantined_at"] = datetime.now(timezone.utc).isoformat()
        tender.source_metadata_json = metadata
        tender.scrape_status = "quarantined"
        changed += 1
    return changed


async def _quarantine_stale_missing_giz_tenders(
    db: AsyncSession,
    *,
    active_external_ids: set[str],
) -> int:
    if not active_external_ids:
        return 0
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Tender).where(
            Tender.source_system == "giz",
            Tender.external_id.not_in(active_external_ids),
        )
    )
    changed = 0
    for tender in result.scalars().all():
        metadata = dict(tender.source_metadata_json or {})
        if metadata.get("giz_visibility") == "hidden":
            continue
        deadline = tender.deadline
        if deadline is None:
            continue
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if deadline >= now:
            continue
        metadata["giz_visibility"] = "hidden"
        metadata["giz_visibility_reason"] = "stale_not_rediscovered"
        metadata["giz_quarantined_at"] = now.isoformat()
        tender.source_metadata_json = metadata
        tender.scrape_status = "quarantined"
        changed += 1
    return changed


@router.post(
    "/sources/giz/sync",
    response_model=SourceSyncResponse,
    dependencies=[Depends(require_operator_or_admin)],
)
async def sync_giz_tenders(
    max_pages: int = Query(default=6, ge=1, le=12),
    dry_run: bool = Query(default=False),
    download_documents: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> SourceSyncResponse:
    """
    Import GIZ country-office tenders from official public giz.de tender pages.
    """
    sync_started = monotonic()
    source = GizTenderSource(
        source_pages=DEFAULT_GIZ_TENDER_PAGES[:max_pages],
        eproc_max_pages=max_pages,
    )
    errors: list[str] = []
    fetched_count = 0
    created_count = 0
    updated_count = 0
    skipped_count = 0
    failed_count = 0
    attachment_count = 0
    documents_downloaded = 0

    try:
        raw_notices = await source.list_opportunities()
    except Exception as exc:
        failure = connector_failure_details(exc)
        logger.exception("giz_sync_fetch_failed")
        return SourceSyncResponse(
            status=failure.status,
            source_system=source.source_system,
            failed_count=1,
            dry_run=dry_run,
            failure_stage="listing",
            failure_class=failure.failure_class,
            retryable=failure.retryable,
            elapsed_ms=int((monotonic() - sync_started) * 1000),
            errors=[type(exc).__name__],
            message=safe_failure_message("GIZ", "listing", exc),
        )

    fetched_count = len(raw_notices)
    quarantined_count = 0
    if not dry_run:
        quarantined_count = await _quarantine_invalid_giz_tenders(db)
        quarantined_count += await _quarantine_stale_missing_giz_tenders(
            db,
            active_external_ids={
                str(raw_notice.get("external_id") or "").strip()
                for raw_notice in raw_notices
                if str(raw_notice.get("external_id") or "").strip()
            },
        )
    for raw_notice in raw_notices:
        external_id = str(raw_notice.get("external_id") or "").strip()
        try:
            normalized = source.normalize(raw_notice)
            documents = await source.discover_documents(normalized)
            attachment_count += len(documents)

            if dry_run:
                continue

            tender, created = await source.upsert(db, normalized)
            await db.flush()
            if documents:
                await source.upsert_documents(
                    db,
                    tender=tender,
                    documents=documents,
                )
                await db.flush()
            if download_documents and documents:
                hydration_result = await hydrate_giz_tender_documents_inline(
                    db,
                    tender=tender,
                    force=False,
                )
                documents_downloaded += int(hydration_result.get("documents_downloaded") or 0)
            if created:
                created_count += 1
            else:
                updated_count += 1
        except Exception as exc:
            failed_count += 1
            logger.warning(
                "giz_sync_notice_failed source_system=%s external_id=%s status=failed error_type=%s",
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
            logger.exception("giz_sync_commit_failed")
            return SourceSyncResponse(
                status="failed",
                source_system=source.source_system,
                fetched_count=fetched_count,
                created_count=created_count,
                updated_count=updated_count,
                skipped_count=skipped_count,
                failed_count=failed_count + 1,
                attachment_count=attachment_count,
                documents_downloaded=documents_downloaded,
                dry_run=dry_run,
                errors=[*errors, f"commit: {type(exc).__name__}"][:10],
                message=_giz_commit_error_message(exc),
            )

    status_value = (
        "success"
        if failed_count == 0 and not source.last_failure_details
        else "partial"
    )
    if source.last_failure_details:
        first_failure = source.last_failure_details[0]
        errors.insert(
            0,
            "listing: "
            f"{first_failure['failure_class']}"
            f"; retryable={str(first_failure['retryable']).lower()}",
        )
    return SourceSyncResponse(
        status=status_value,
        source_system=source.source_system,
        fetched_count=fetched_count,
        created_count=created_count,
        updated_count=updated_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        attachment_count=attachment_count,
        documents_downloaded=documents_downloaded,
        dry_run=dry_run,
        failure_stage=(
            str(source.last_failure_details[0]["stage"])
            if source.last_failure_details
            else None
        ),
        failure_class=(
            str(source.last_failure_details[0]["failure_class"])
            if source.last_failure_details
            else None
        ),
        retryable=(
            bool(source.last_failure_details[0]["retryable"])
            if source.last_failure_details
            else None
        ),
        elapsed_ms=int((monotonic() - sync_started) * 1000),
        errors=errors,
        message=(
            "GIZ sync dry run completed. No tenders were written."
            if dry_run
            else (
                "GIZ sync completed: "
                f"{created_count} created, {updated_count} updated, "
                f"{quarantined_count} quarantined, "
                f"{attachment_count} public document link(s), "
                f"{documents_downloaded} downloaded, {failed_count} failed."
                + (
                    " Partial source coverage: "
                    f"stage={source.last_failure_details[0]['stage']}, "
                    f"failure_class={source.last_failure_details[0]['failure_class']}, "
                    "retryable="
                    f"{str(source.last_failure_details[0]['retryable']).lower()}."
                    if source.last_failure_details
                    else ""
                )
            )
        ),
    )


@router.post(
    "/sources/giz/hydrate",
    response_model=GizHydrateAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def hydrate_giz_tenders(
    payload: GizHydrateRequest,
    current_user: User = Depends(require_approved_pilot_access),
    db: AsyncSession = Depends(get_db),
) -> GizHydrateAcceptedResponse:
    """
    Enqueue targeted document hydration for exact persisted GIZ external IDs.

    Approved pilots may hydrate one accessible tender with force=false.
    Operators and admins may hydrate batches and force refreshes.
    """
    external_ids: list[str] = []
    seen_external_ids: set[str] = set()
    for raw_external_id in payload.external_ids:
        external_id = str(raw_external_id or "").strip()
        if not external_id:
            continue
        if external_id in seen_external_ids:
            continue
        seen_external_ids.add(external_id)
        external_ids.append(external_id)

    if not external_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one exact GIZ external_id is required.",
        )

    has_operator_scope = is_operator_or_admin(current_user)
    if not has_operator_scope and payload.force:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Force GIZ hydration requires operator access.",
        )
    if not has_operator_scope and len(external_ids) != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Batch GIZ hydration requires operator access.",
        )

    tenders_result = await db.execute(
        select(Tender).where(
            Tender.source_system == "giz",
            Tender.external_id.in_(external_ids),
        )
    )
    tenders_by_external_id = {
        str(tender.external_id): tender
        for tender in tenders_result.scalars().all()
    }
    missing_external_ids = [
        external_id
        for external_id in external_ids
        if external_id not in tenders_by_external_id
    ]
    if missing_external_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "GIZ tender(s) were not found for exact external_id values.",
                "missing_external_ids": missing_external_ids,
            },
        )

    jobs: list[GizHydrateJobResponse] = []
    enqueued_count = 0
    already_running_count = 0

    for external_id in external_ids:
        tender = tenders_by_external_id[external_id]
        assert_source_scope("giz", tender)
        if not has_operator_scope:
            await _ensure_tender_access(
                db=db,
                tender_id=tender.id,
                user_id=current_user.id,
                current_user=current_user,
                allow_operator=False,
            )

        await db.execute(
            select(Tender)
            .where(Tender.id == tender.id)
            .with_for_update()
        )
        existing_job = await _get_active_sync_job_for_tender(
            db=db,
            tender_id=tender.id,
        )
        if existing_job is not None:
            already_running_count += 1
            jobs.append(
                GizHydrateJobResponse(
                    external_id=external_id,
                    tender_id=tender.id,
                    job_id=existing_job.job_id,
                    status=existing_job.status.value,
                    progress=existing_job.progress,
                    queued=False,
                    message="GIZ hydration already in progress",
                )
            )
            continue

        new_job = TenderSyncJob(
            id=uuid4(),
            job_id=str(uuid4()),
            tender_id=tender.id,
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
            existing_job = await _get_active_sync_job_for_tender(
                db=db,
                tender_id=tender.id,
            )
            if existing_job is not None:
                already_running_count += 1
                jobs.append(
                    GizHydrateJobResponse(
                        external_id=external_id,
                        tender_id=tender.id,
                        job_id=existing_job.job_id,
                        status=existing_job.status.value,
                        progress=existing_job.progress,
                        queued=False,
                        message="GIZ hydration already in progress",
                    )
                )
                continue
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A hydration job already exists for this GIZ tender.",
            )
        except SQLAlchemyError as exc:
            await db.rollback()
            logger.exception("Failed to persist GIZ hydration job before enqueue")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database write failed: {exc}",
            ) from exc

        try:
            task_result = hydrate_giz_documents.apply_async(
                args=[str(tender.id), new_job.job_id],
                kwargs={"force": payload.force},
                task_id=new_job.job_id,
                queue="heavy_dl_queue",
                routing_key="heavy_dl_queue",
                retry=True,
                retry_policy={
                    "max_retries": 3,
                    "interval_start": 0,
                    "interval_step": 0.2,
                    "interval_max": 1,
                },
            )
            logger.info(
                "Enqueued GIZ hydration task tender_id=%s external_id=%s job_id=%s celery_task_id=%s queue=%s",
                tender.id,
                external_id,
                new_job.job_id,
                task_result.id,
                "heavy_dl_queue",
            )
            enqueued_count += 1
            jobs.append(
                GizHydrateJobResponse(
                    external_id=external_id,
                    tender_id=tender.id,
                    job_id=new_job.job_id,
                    status=new_job.status.value,
                    progress=new_job.progress,
                    queued=True,
                    message="GIZ hydration enqueued",
                )
            )
        except Exception as exc:
            error_type = type(exc).__name__
            logger.exception(
                "Failed to enqueue GIZ hydration task tender_id=%s external_id=%s job_id=%s error_type=%s",
                tender.id,
                external_id,
                new_job.job_id,
                error_type,
            )
            try:
                new_job.status = TenderSyncStatus.FAILED
                new_job.progress = 0
                new_job.error_message = "Failed to enqueue GIZ hydration worker task."
                await db.commit()
            except SQLAlchemyError:
                await db.rollback()
                logger.exception(
                    "Failed to persist GIZ hydration enqueue failure for job %s",
                    new_job.job_id,
                )
            jobs.append(
                GizHydrateJobResponse(
                    external_id=external_id,
                    tender_id=tender.id,
                    job_id=new_job.job_id,
                    status=TenderSyncStatus.FAILED.value,
                    progress=0,
                    queued=False,
                    message=(
                        "Failed to enqueue GIZ hydration worker task. "
                        "Check Redis and the heavy document worker."
                    ),
                )
            )

    return GizHydrateAcceptedResponse(
        message=(
            "GIZ hydration accepted: "
            f"{enqueued_count} enqueued, {already_running_count} already running."
        ),
        force=payload.force,
        requested_count=len(external_ids),
        accepted_count=len(jobs),
        enqueued_count=enqueued_count,
        already_running_count=already_running_count,
        jobs=jobs,
    )


@router.post(
    "/sources/ebrd/sync",
    response_model=SourceSyncResponse,
    dependencies=[Depends(require_operator_or_admin)],
)
async def sync_ebrd_tenders(
    max_items: int = Query(default=50, ge=1, le=200),
    detail_items: int = Query(default=25, ge=0, le=100),
    active_only: bool = Query(default=True),
    dry_run: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> SourceSyncResponse:
    """
    Import EBRD ECEPP public procurement notices as metadata-only records.
    """
    sync_started = monotonic()
    source = EbrdTenderSource(
        max_items=max_items,
        detail_items=detail_items,
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
        failure = connector_failure_details(exc)
        logger.exception("ebrd_sync_fetch_failed")
        return SourceSyncResponse(
            status=failure.status,
            source_system=source.source_system,
            failed_count=1,
            dry_run=dry_run,
            failure_stage="listing",
            failure_class=failure.failure_class,
            retryable=failure.retryable,
            elapsed_ms=int((monotonic() - sync_started) * 1000),
            errors=[type(exc).__name__],
            message=safe_failure_message("EBRD", "listing", exc),
        )
    if source.last_used_bootstrap_fallback and source.last_fetch_error_type:
        errors.append(f"live_fetch: {source.last_fetch_error_type}; used bootstrap fallback")

    fetched_count = len(raw_notices)
    for raw_notice in raw_notices:
        external_id = str(raw_notice.get("external_id") or "").strip()
        try:
            if not source.should_import(raw_notice):
                skipped_count += 1
                continue

            normalized = source.normalize(raw_notice)
            documents = await source.discover_documents(normalized)
            attachment_count += len(documents)

            if dry_run:
                continue

            tender, created = await source.upsert(db, normalized)
            await db.flush()
            if documents:
                await source.upsert_documents(
                    db,
                    tender=tender,
                    documents=documents,
                )
            if created:
                created_count += 1
            else:
                updated_count += 1
        except Exception as exc:
            failed_count += 1
            logger.warning(
                "ebrd_sync_notice_failed source_system=%s external_id=%s status=failed error_type=%s",
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
            logger.exception("ebrd_sync_commit_failed")
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
                message="EBRD sync failed while saving notices.",
            )

    status_value = "success" if failed_count == 0 else "partial"
    if source.last_used_bootstrap_fallback and failed_count == 0:
        status_value = "partial"
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
        failure_stage="listing" if source.last_used_bootstrap_fallback else None,
        failure_class=source.last_fetch_error_type,
        retryable=(
            source.last_fetch_retryable
            if source.last_used_bootstrap_fallback
            else None
        ),
        fallback_used=source.last_used_bootstrap_fallback,
        elapsed_ms=int((monotonic() - sync_started) * 1000),
        errors=errors,
        message=(
            "EBRD sync dry run completed. No tenders were written."
            if dry_run
            else (
                "EBRD sync completed from bundled public fallback metadata because "
                f"live ECEPP fetch failed ({source.last_fetch_error_type}). "
                f"{created_count} created, {updated_count} updated, "
                f"{skipped_count} skipped, {failed_count} failed."
            )
            if source.last_used_bootstrap_fallback
            else (
                "EBRD sync completed: "
                f"{created_count} created, {updated_count} updated, "
                f"{skipped_count} skipped, {failed_count} failed. "
                "Participation documents remain external-access only."
            )
        ),
    )


@router.post(
    "/sources/adb/sync",
    response_model=AdbSyncResponse,
    dependencies=[Depends(require_operator_or_admin)],
)
async def sync_adb_tenders(
    max_items: int = Query(default=500, ge=1, le=2000),
    max_pages: int = Query(default=25, ge=1, le=100),
    feed_type: str = Query(default="invitation_for_bids"),
    dry_run: bool = Query(default=False),
    download_documents: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> AdbSyncResponse:
    """
    Import ADB tender notices from the official current listing, with degraded RSS fallback.
    """
    sync_started = monotonic()
    if download_documents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "ADB PDF download and parsing is deferred in INT-3. "
                "Run with download_documents=false to capture metadata."
            ),
        )

    try:
        source = AdbTenderSource(
            feed_type=feed_type,
            max_items=max_items,
            max_pages=max_pages,
        )
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
    lifecycle_closed_count = 0
    legacy_unresolved_count = 0
    skip_reasons: Counter[str] = Counter()

    try:
        raw_notices = await source.list_opportunities()
    except Exception as exc:
        failure = connector_failure_details(exc)
        logger.exception("adb_sync_fetch_failed")
        return AdbSyncResponse(
            status=failure.status,
            fetched=0,
            failed=1,
            dry_run=dry_run,
            failure_stage="listing",
            failure_class=failure.failure_class,
            retryable=failure.retryable,
            execution_health="FAIL",
            freshness_health="UNKNOWN",
            coverage_health="NONE",
            elapsed_ms=int((monotonic() - sync_started) * 1000),
            errors=[type(exc).__name__],
            message=safe_failure_message("ADB", "listing", exc),
        )

    fetched = len(raw_notices)
    for raw_notice in raw_notices:
        external_id = str(raw_notice.get("guid") or "").strip()
        try:
            if not source.should_import(raw_notice):
                skipped_count += 1
                skip_reasons[source.skip_reason(raw_notice) or "non_actionable_notice"] += 1
                continue

            normalized = source.normalize(raw_notice)
            documents = await source.discover_documents(normalized)
            attachments_discovered += len(documents)

            if dry_run:
                continue

            tender, created = await source.upsert(db, normalized)
            await db.flush()
            if documents:
                await source.upsert_documents(
                    db,
                    tender=tender,
                    documents=documents,
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

    try:
        lifecycle_closed_count = await reconcile_past_deadline_open_tenders(
            db,
            source_system="adb",
        )
        authoritative_ids = (
            {str(row.get("guid") or "").strip() for row in raw_notices}
            if not source.fallback_used
            else set()
        )
        legacy_unresolved_count = await reconcile_unresolved_adb_legacy_rows(
            db,
            authoritative_ids=authoritative_ids,
        )
        updated_count += lifecycle_closed_count + legacy_unresolved_count
    except Exception as exc:
        failed_count += 1
        errors.append(f"lifecycle: {type(exc).__name__}")
        logger.exception("adb_lifecycle_reconciliation_failed")

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
                execution_health="FAIL",
                freshness_health=source.freshness_health,
                coverage_health=source.coverage_health,
                errors=[*errors, f"commit: {type(exc).__name__}"][:10],
                message="ADB sync failed while saving notices.",
            )

    status_value = (
        "success"
        if failed_count == 0
        and source.execution_health == "PASS"
        and source.freshness_health == "CURRENT"
        and source.coverage_health == "COMPLETE"
        else "partial"
    )
    if source.fallback_used:
        errors.insert(
            0,
            f"primary_listing: {source.primary_failure_class}; used legacy RSS fallback",
        )
    if source.last_truncated:
        errors.insert(0, "pagination: safety_cap_reached")
    return AdbSyncResponse(
        status=status_value,
        fetched=fetched,
        created=created_count,
        updated=updated_count,
        skipped=skipped_count,
        rejected_count=skipped_count + failed_count,
        failed=failed_count,
        attachments_discovered=attachments_discovered,
        documents_downloaded=0,
        dry_run=dry_run,
        failure_stage="listing" if source.fallback_used else None,
        failure_class=source.primary_failure_class,
        retryable=source.primary_failure_retryable,
        fallback_used=source.fallback_used,
        skip_reasons=dict(skip_reasons),
        elapsed_ms=int((monotonic() - sync_started) * 1000),
        source_newest_published_at=source.source_newest_published_at,
        source_oldest_published_at=source.source_oldest_published_at,
        execution_health=source.execution_health,
        freshness_health=source.freshness_health,
        coverage_health=source.coverage_health,
        errors=errors,
        message=(
            "ADB sync dry run completed. No tenders were written."
            if dry_run
            else (
                "ADB sync completed: "
                f"{created_count} created, {updated_count} updated, "
                f"{skipped_count} skipped, {failed_count} failed; "
                f"{lifecycle_closed_count} deadline row(s) closed; "
                f"{legacy_unresolved_count} legacy row(s) marked unknown"
                + (
                    "; legacy RSS fallback used because the official current "
                    "listing was unavailable."
                    if source.fallback_used
                    else "."
                )
            )
        ),
    )


SOURCE_REFRESH_DEFAULTS: dict[str, dict[str, Any]] = {
    "world_bank": {
        "max_pages": 25,
        "rows": 100,
        "active_only": True,
        "dry_run": False,
    },
    "giz": {
        "max_pages": 6,
        "dry_run": False,
        "download_documents": False,
    },
    "ebrd": {
        "max_items": 50,
        "detail_items": 25,
        "active_only": True,
        "dry_run": False,
    },
    "adb": {
        "max_items": 500,
        "max_pages": 25,
        "feed_type": "invitation_for_bids",
        "dry_run": False,
        "download_documents": False,
    },
}
SOURCE_REFRESH_SYSTEMS = {"uzex", *SOURCE_REFRESH_DEFAULTS}


def _source_refresh_seconds(setting: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(setting, str(default))))
    except (TypeError, ValueError):
        return default


def _source_refresh_response(
    job: SourceRefreshJob,
    *,
    status_value: str | None = None,
    reused: bool = False,
    message: str | None = None,
) -> SourceRefreshResponse:
    newest = getattr(job, "source_newest_published_at", None)
    source_age_days = None
    if newest is not None:
        comparable = newest
        if comparable.tzinfo is None:
            comparable = comparable.replace(tzinfo=timezone.utc)
        source_age_days = max(
            0,
            (datetime.now(timezone.utc).date() - comparable.date()).days,
        )
    return SourceRefreshResponse(
        status=status_value or job.status,
        source_system=job.source_system,
        job_id=job.id,
        created_count=job.created_count,
        updated_count=job.updated_count,
        fetched_count=int(getattr(job, "fetched_count", 0) or 0),
        skipped_count=int(getattr(job, "skipped_count", 0) or 0),
        rejected_count=int(getattr(job, "rejected_count", 0) or 0),
        failed_count=job.failed_count,
        fallback_used=bool(getattr(job, "fallback_used", False)),
        skip_reasons=getattr(job, "skip_reasons", None) or {},
        failure_class=getattr(job, "failure_class", None),
        failure_stage=getattr(job, "failure_stage", None),
        retryable=getattr(job, "retryable", None),
        started_at=job.started_at,
        completed_at=job.completed_at,
        elapsed_ms=getattr(job, "elapsed_ms", None),
        source_newest_published_at=newest,
        source_oldest_published_at=getattr(job, "source_oldest_published_at", None),
        source_age_days=source_age_days,
        execution_health=getattr(job, "execution_health", None),
        freshness_health=getattr(job, "freshness_health", None),
        coverage_health=getattr(job, "coverage_health", None),
        last_updated=job.completed_at,
        reused=reused,
        message=message or job.message or "Refresh requested.",
    )


async def _run_source_refresh(
    source_system: str,
    db: AsyncSession,
) -> RefreshResponse | SourceSyncResponse | AdbSyncResponse:
    if source_system == "uzex":
        return await _sync_uzex_tenders(db=db)
    if source_system == "world_bank":
        return await sync_world_bank_tenders(
            **SOURCE_REFRESH_DEFAULTS[source_system],
            db=db,
        )
    if source_system == "giz":
        return await sync_giz_tenders(
            **SOURCE_REFRESH_DEFAULTS[source_system],
            db=db,
        )
    if source_system == "ebrd":
        return await sync_ebrd_tenders(
            **SOURCE_REFRESH_DEFAULTS[source_system],
            db=db,
        )
    return await sync_adb_tenders(
        **SOURCE_REFRESH_DEFAULTS[source_system],
        db=db,
    )


def _normalized_source_result(
    result: RefreshResponse | SourceSyncResponse | AdbSyncResponse,
) -> tuple[str, int, int, int, str]:
    raw_status = str(result.status).casefold()
    created = int(
        getattr(result, "new_count", getattr(result, "created_count", getattr(result, "created", 0)))
        or 0
    )
    updated = int(
        getattr(result, "updated_count", getattr(result, "updated", 0)) or 0
    )
    failed = int(
        getattr(result, "failed_count", getattr(result, "failed", 0)) or 0
    )
    message = result.message

    if raw_status == "success":
        return "completed", created, updated, failed, message
    if raw_status == "source_unavailable":
        return "source_unavailable", created, updated, failed, message
    if raw_status == "partial":
        return "partial", created, updated, failed, message
    return "failed", created, updated, failed, message


async def _request_source_refresh(
    *,
    source_system: str,
    force: bool,
    current_user: User,
    db: AsyncSession,
) -> SourceRefreshResponse:
    normalized_source = source_system.strip().casefold().replace("-", "_")
    if normalized_source not in SOURCE_REFRESH_SYSTEMS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unsupported tender source",
        )
    if force and not is_operator_or_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Force refresh requires operator access",
        )

    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(
        seconds=_source_refresh_seconds("SOURCE_REFRESH_ACTIVE_TIMEOUT_SECONDS", 1800)
    )
    active_result = await db.execute(
        select(SourceRefreshJob)
        .where(
            SourceRefreshJob.source_system == normalized_source,
            SourceRefreshJob.status.in_(("queued", "running")),
        )
        .order_by(SourceRefreshJob.created_at.desc())
    )
    active_job = active_result.scalars().first()
    if active_job is not None:
        active_updated_at = active_job.updated_at
        if active_updated_at.tzinfo is None:
            active_updated_at = active_updated_at.replace(tzinfo=timezone.utc)
        if active_updated_at >= stale_before:
            return _source_refresh_response(
                active_job,
                status_value=active_job.status,
                reused=True,
                message=(
                    "Already queued."
                    if active_job.status == "queued"
                    else "Already refreshing."
                ),
            )
        active_job.status = "failed"
        active_job.completed_at = now
        active_job.message = "Previous refresh timed out."
        await db.commit()

    if not force:
        cooldown_after = now - timedelta(
            seconds=_source_refresh_seconds("SOURCE_REFRESH_COOLDOWN_SECONDS", 300)
        )
        recent_result = await db.execute(
            select(SourceRefreshJob)
            .where(
                SourceRefreshJob.source_system == normalized_source,
                SourceRefreshJob.status == "completed",
                SourceRefreshJob.completed_at >= cooldown_after,
            )
            .order_by(SourceRefreshJob.completed_at.desc())
        )
        recent_job = recent_result.scalars().first()
        if recent_job is not None:
            return _source_refresh_response(
                recent_job,
                status_value="fresh",
                reused=True,
                message="Source is already fresh.",
            )

    job = SourceRefreshJob(
        source_system=normalized_source,
        requested_by_user_id=current_user.id,
        status="queued",
        force=force,
        created_count=0,
        updated_count=0,
        fetched_count=0,
        skipped_count=0,
        rejected_count=0,
        failed_count=0,
        fallback_used=False,
        skip_reasons={},
        message="Refresh queued.",
    )
    db.add(job)
    try:
        await db.commit()
        await db.refresh(job)
    except IntegrityError:
        await db.rollback()
        concurrent_result = await db.execute(
            select(SourceRefreshJob)
            .where(
                SourceRefreshJob.source_system == normalized_source,
                SourceRefreshJob.status.in_(("queued", "running")),
            )
            .order_by(SourceRefreshJob.created_at.desc())
        )
        concurrent_job = concurrent_result.scalars().first()
        if concurrent_job is None:
            raise
        return _source_refresh_response(
            concurrent_job,
            status_value="running",
            reused=True,
            message="Already refreshing.",
        )

    try:
        task_result = refresh_tender_source.apply_async(
            args=[normalized_source, str(job.id)],
            task_id=str(job.id),
            queue="celery",
            routing_key="celery",
            retry=True,
            retry_policy={
                "max_retries": 3,
                "interval_start": 0,
                "interval_step": 0.2,
                "interval_max": 1,
            },
        )
        logger.info(
            "source_refresh_enqueued source_system=%s job_id=%s celery_task_id=%s "
            "queue=celery",
            normalized_source,
            job.id,
            task_result.id,
        )
    except Exception as exc:
        logger.exception(
            "source_refresh_enqueue_failed source_system=%s job_id=%s "
            "stage=dispatch failure_class=%s retryable=true",
            normalized_source,
            job.id,
            type(exc).__name__,
        )
        job.status = "failed"
        job.failed_count = 1
        job.message = (
            "Refresh could not be queued. Existing tenders remain available. "
            f"(dispatch: {type(exc).__name__}; retryable=true)"
        )
        job.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(job)
        return _source_refresh_response(job)

    return _source_refresh_response(job)


@router.post(
    "/sources/{source_system}/refresh",
    response_model=SourceRefreshResponse,
)
async def request_source_refresh(
    source_system: str,
    force: bool = Query(default=False),
    current_user: User = Depends(require_approved_user),
    db: AsyncSession = Depends(get_db),
) -> SourceRefreshResponse:
    """
    Request a source refresh without exposing scraper tuning controls.

    Approved users may request the default refresh. Operators and administrators
    may additionally bypass the cooldown with ``force=true``.
    """
    return await _request_source_refresh(
        source_system=source_system,
        force=force,
        current_user=current_user,
        db=db,
    )


@router.get(
    "/sources/refresh-status",
    response_model=list[SourceRefreshResponse],
)
async def get_source_refresh_status(
    _current_user: User = Depends(require_approved_user),
    db: AsyncSession = Depends(get_db),
) -> list[SourceRefreshResponse]:
    """Return the latest refresh state for each source."""
    responses: list[SourceRefreshResponse] = []
    for source_system in sorted(SOURCE_REFRESH_SYSTEMS):
        result = await db.execute(
            select(SourceRefreshJob)
            .where(SourceRefreshJob.source_system == source_system)
            .order_by(SourceRefreshJob.created_at.desc())
            .limit(1)
        )
        job = result.scalars().first()
        if job is not None:
            responses.append(_source_refresh_response(job))
    return responses


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


async def _get_latest_sync_job_for_tender(
    *,
    db: AsyncSession,
    tender_id: UUID,
) -> TenderSyncJob | None:
    result = await db.execute(
        select(TenderSyncJob)
        .where(TenderSyncJob.tender_id == tender_id)
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


async def _get_active_sync_job_for_tender(
    *,
    db: AsyncSession,
    tender_id: UUID,
) -> TenderSyncJob | None:
    active_statuses = (TenderSyncStatus.PENDING, TenderSyncStatus.IN_PROGRESS)
    result = await db.execute(
        select(TenderSyncJob)
        .where(
            TenderSyncJob.tender_id == tender_id,
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
    current_user: User = Depends(require_approved_pilot_access),
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
    tender_result = await db.execute(
        select(Tender)
        .options(load_only(Tender.source_system, Tender.status))
        .where(Tender.id == tender_id)
    )
    tender = tender_result.scalar_one_or_none()
    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )
    if tender.source_system != "uzex":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document sync worker is UzEx-only for this source.",
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

    if not is_tender_actionable(tender):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=TENDER_NOT_ACTIONABLE_DETAIL,
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
        task_result = process_tender_docs.apply_async(
            args=[str(tender_id), new_job.job_id],
            kwargs={"reparse_markerless": reparse_markerless},
            task_id=new_job.job_id,
            queue="heavy_dl_queue",
            routing_key="heavy_dl_queue",
            retry=True,
            retry_policy={
                "max_retries": 3,
                "interval_start": 0,
                "interval_step": 0.2,
                "interval_max": 1,
            },
        )
        logger.info(
            "Enqueued tender document sync task tender_id=%s job_id=%s celery_task_id=%s queue=%s",
            tender_id,
            new_job.job_id,
            task_result.id,
            "heavy_dl_queue",
        )
    except Exception as exc:
        error_type = type(exc).__name__
        logger.exception(
            "Failed to enqueue sync task for tender %s job_id=%s error_type=%s",
            tender_id,
            new_job.job_id,
            error_type,
        )
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
            detail=(
                "Failed to enqueue tender document sync task "
                f"({error_type}). Check Redis and the heavy document worker."
            ),
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
    current_user: User = Depends(require_approved_pilot_access),
    db: AsyncSession = Depends(get_db),
) -> SyncStatusResponse:
    await _ensure_tender_access(
        db=db,
        tender_id=tender_id,
        user_id=current_user.id,
        current_user=current_user,
        allow_operator=True,
    )

    tender_result = await db.execute(
        select(Tender.source_system, Tender.source_metadata_json).where(
            Tender.id == tender_id
        )
    )
    tender_row = tender_result.one_or_none()
    if tender_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )

    tender_mapping = tender_row._mapping
    source_system = str(tender_mapping["source_system"] or "")
    coverage_status = (
        _giz_coverage_status_from_metadata(tender_mapping["source_metadata_json"])
        if source_system == "giz"
        else None
    )
    if source_system == "giz":
        latest_job = await _get_latest_sync_job_for_tender(
            db=db,
            tender_id=tender_id,
        )
    else:
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
            source_system=source_system,
            coverage_status=coverage_status,
            diagnostics=diagnostics,
        )

    return SyncStatusResponse(
        state=latest_job.status.value,
        progress=latest_job.progress,
        docs_parsed=docs_parsed,
        error=latest_job.error_message,
        source_system=source_system,
        coverage_status=coverage_status,
        diagnostics=diagnostics,
    )


@router.get("/{tender_id}/documents", response_model=list[TenderDocumentResponse])
async def get_tender_documents(
    tender_id: UUID,
    current_user: User = Depends(require_approved_pilot_access),
    db: AsyncSession = Depends(get_db),
) -> list[TenderDocumentResponse]:
    """
    Return safe document metadata for a given tender.
    """
    await _ensure_tender_access(
        db=db,
        tender_id=tender_id,
        user_id=current_user.id,
        current_user=current_user,
        allow_operator=True,
    )

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
    current_user: User = Depends(require_approved_pilot_access),
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
            "created_at": None,
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
    analysis_status = str(analysis_data.get("analysis_status") or "completed")
    evaluation_payload = analysis_data.get("evaluation")
    hybrid_payload = sanitize_internal_requirement_diagnostics(
        analysis_data.get("hybrid_compliance")
    )
    if analysis_status == "failed":
        evaluation_payload = _failed_analysis_evaluation_payload(evaluation_payload)
        hybrid_payload = _failed_analysis_hybrid_payload(hybrid_payload)

    return {
        "analysis_id": str(analysis.id),
        "requirements": analysis_data.get("requirements"),
        "evaluation": evaluation_payload,
        "hybrid_compliance": hybrid_payload,
        "content_hash": analysis.content_hash,
        "override_seal": analysis.override_seal,
        "evidence_validation": _public_evidence_validation_payload(
            analysis_data.get("evidence_validation"),
            include_debug=current_user.is_admin,
        ),
        "analysis_warnings": analysis_data.get("analysis_warnings") or [],
        "coverage_metadata": _public_coverage_metadata_payload(
            analysis_data.get("coverage_metadata"),
            include_debug=current_user.is_admin,
        ),
        "analysis_status": analysis_status,
        "extraction_error": analysis_data.get("extraction_error"),
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


@router.get("/{tender_id}/compliance/export/pdf")
async def export_compliance_pdf(
    tender_id: UUID,
    analysis_id: UUID | None = Query(default=None),
    current_user: User = Depends(require_approved_pilot_access),
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
    current_user: User = Depends(require_approved_pilot_access),
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
    current_user: User = Depends(require_approved_pilot_access),
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
