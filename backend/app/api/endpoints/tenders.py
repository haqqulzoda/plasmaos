"""
Plasma AI - Tenders Endpoints

Public tender feed for the Autonomous Tender Officer.
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, quote, unquote, urlparse
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.api.deps import get_current_user
from app.core.ai_analyzer import (
    ExtractedTenderRequirements,
    ExtractionError,
    extract_tender_requirements,
)
from app.core.celery_app import celery_app
from app.core.evaluator import DynamicComplianceResult, TaxNodeInfo, evaluate_compliance
from app.core.scraper import UzExScraper
from app.core.security import authenticated_dependency
from app.db.session import get_db
from app.models.audit import TenderAnalysis
from app.models.all_models import Proposal, RiskOverrideLog, TaxonomyNode, Tender, TenderDocument, TenderStatus, User
from app.models.company import CompanyProfile
from app.models.taxonomy import CompanyCredential
from app.schemas.tender import TenderResponse
from app.schemas.vault import (
    CertificationItem,
    CompanyVaultResponse,
    FinancialHistoryItem,
    LicenseItem,
)
from app.workers.tender_tasks import process_tender_docs

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[authenticated_dependency()])


class RefreshResponse(BaseModel):
    """Response for refresh endpoint."""
    status: str
    new_count: int
    updated_count: int
    message: str


class SyncDocsAcceptedResponse(BaseModel):
    """Response for sync-docs enqueue endpoint."""
    message: str
    job_id: str


class SyncStatusResponse(BaseModel):
    """Response for sync status polling endpoint."""
    job_id: str
    status: str
    message: str


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
    """Response payload for analyze-tender endpoint."""

    analysis_id: str
    requirements: ExtractedTenderRequirements
    evaluation: DynamicComplianceResult


class RiskOverrideRequest(BaseModel):
    """Request payload for cryptographic liability handshake."""

    node_id: UUID
    analysis_id: UUID
    justification: Optional[str] = None


class RiskOverrideStatusResponse(BaseModel):
    """Persisted override status for a tender and current user."""

    tender_id: UUID
    accepted_node_ids: list[str]


def _serialize_tender(tender: Tender) -> TenderResponse:
    payload = TenderResponse.model_validate(tender)
    if payload.source_url is not None and not payload.source_url.strip():
        payload.source_url = None
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


@router.post("/{tender_id}/analyze", response_model=AnalyzeTenderResponse)
async def analyze_tender(
    tender_id: UUID,
    force: bool = False,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Analyze pre-scraped tender text and persist analysis result.

    Returns cached analysis when the underlying text has not changed,
    unless ``force=True`` is passed to trigger a fresh Gemini call.
    """
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
        profile_result = await session.execute(
            select(CompanyProfile)
            .options(
                selectinload(CompanyProfile.certifications),
                selectinload(CompanyProfile.licenses),
                selectinload(CompanyProfile.financial_history),
            )
            .where(CompanyProfile.user_id == current_user.id)
        )
        profile = profile_result.scalar_one_or_none()

        if profile is None:
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

        taxonomy_query = select(TaxonomyNode)
        taxonomy_is_active = getattr(TaxonomyNode, "is_active", None)
        if taxonomy_is_active is not None:
            taxonomy_query = taxonomy_query.where(taxonomy_is_active.is_(True))
        taxonomy_result = await session.execute(taxonomy_query.order_by(TaxonomyNode.name.asc()))
        taxonomy_nodes = taxonomy_result.scalars().all()
        available_taxonomy = [
            {
                "id": str(node.id),
                "name": node.name,
                "description": node.description or "",
            }
            for node in taxonomy_nodes
        ]

        # ── Build credential UUID set for this user ──
        cred_result = await session.execute(
            select(CompanyCredential.taxonomy_node_id).where(
                CompanyCredential.company_profile_id == profile.id
            )
        )
        credential_uuids: set[str] = {
            str(row[0]) for row in cred_result.all()
        }

        # ── Build taxonomy lookup ──
        taxonomy_lookup: dict[str, TaxNodeInfo] = {
            str(node.id): TaxNodeInfo(
                name=node.name,
                impact_weight=node.impact_weight,
                is_fatal=node.is_fatal,
            )
            for node in taxonomy_nodes
        }

        # ── Build deterministic content hash over ALL evaluation inputs ──
        sorted_cred_str = ",".join(sorted(credential_uuids))
        sorted_tax_str = ",".join(sorted(taxonomy_lookup.keys()))
        hash_input = f"{tender_text}|{sorted_cred_str}|{sorted_tax_str}"
        current_content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

        # ── Cache check: reuse existing analysis only if content hash matches ──
        if not force:
            cached_result = await session.execute(
                select(TenderAnalysis)
                .where(
                    TenderAnalysis.tender_id == tender_id,
                    TenderAnalysis.company_name == analysis_owner_key,
                )
                .order_by(TenderAnalysis.created_at.desc())
                .limit(1)
            )
            cached = cached_result.scalar_one_or_none()

            if cached is not None and cached.content_hash == current_content_hash:
                cached_data = cached.analysis_json or {}
                try:
                    cached_reqs = ExtractedTenderRequirements.model_validate(
                        cached_data.get("requirements", {})
                    )
                    cached_eval = DynamicComplianceResult.model_validate(
                        cached_data.get("evaluation", {})
                    )
                    logger.info("Returning cached analysis %s for tender %s (hash match)", cached.id, tender_id)
                    return {
                        "analysis_id": str(cached.id),
                        "requirements": cached_reqs,
                        "evaluation": cached_eval,
                    }
                except (ValidationError, KeyError):
                    logger.warning(
                        "Cached analysis %s has legacy schema; forcing fresh extraction",
                        cached.id,
                    )

        # ── Fresh Gemini extraction ──
        requirements = await extract_tender_requirements(tender_text, available_taxonomy)
        evaluation = evaluate_compliance(
            mapped_requirement_uuids=requirements.mapped_requirement_uuids,
            unmapped_custom_requirements=requirements.unmapped_custom_requirements,
            credential_uuids=credential_uuids,
            taxonomy_lookup=taxonomy_lookup,
        )

        new_analysis = TenderAnalysis(
            tender_id=tender.id,
            tender_file_name=f"tender_{tender.external_id}",
            company_name=analysis_owner_key,
            raw_extracted_text=tender_text,
            analysis_json={
                "requirements": requirements.model_dump(mode="json"),
                "evaluation": evaluation.model_dump(mode="json"),
                "tenant_company_name": display_company_name,
            },
            content_hash=current_content_hash,
        )
        session.add(new_analysis)
        await session.commit()
        await session.refresh(new_analysis)
    except ExtractionError as exc:
        await session.rollback()
        logger.exception("Tender requirement extraction failed")
        status_code = getattr(exc, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR)
        raise HTTPException(
            status_code=status_code,
            detail=f"Tender requirement extraction failed: {exc}",
        ) from exc
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
        "requirements": requirements,
        "evaluation": evaluation,
    }


@router.post("/test-scrape", response_model=TestScrapeResponse)
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


@router.post("/proxy-download")
async def proxy_download(request: ProxyDownloadRequest):
    """
    Proxy download endpoint for UzEx files.
    
    UzEx uses POST with dynamic validation tokens, so we relay via Playwright.
    
    Returns the file as a downloadable response.
    """
    from fastapi.responses import Response
    
    try:
        scraper = UzExScraper(headless=True)
        file_bytes, filename = await scraper.download_file(request.tender_url, request.file_path)
        content_type = _guess_download_content_type(filename=filename)
        
        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={"Content-Disposition": _safe_content_disposition("attachment", filename)}
        )
        
    except Exception as e:
        logger.error(f"Proxy download failed: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


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
        .join(Proposal, Proposal.tender_id == Tender.id)
        .where(
            TenderDocument.id == doc_id,
            Proposal.user_id == current_user.id,
        )
    )
    row = result.first()
    
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc, tender = row
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

    # ── Hard fail: storage_path is set but the physical file is missing ──
    # Do NOT fall back to a live UzEx download — UzEx blocks direct HTTP
    # requests (405 / 0 bytes), which silently serves an empty file to the user.
    if doc.storage_path:
        logger.error(
            "Document %s has storage_path '%s' but physical file is missing from disk",
            doc_id,
            doc.storage_path,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "Document file missing from physical storage. "
                "Please re-sync documents for this tender."
            ),
        )

    # ── No storage_path at all: document was never downloaded by the worker ──
    # Attempt a live Playwright download as a last resort.
    file_path = _extract_remote_file_path(doc.file_url)
    if not file_path:
        raise HTTPException(status_code=500, detail="Document file path is invalid")

    filename = Path(file_path).name if file_path else f"document.{doc.file_type}"
    
    try:
        from fastapi.responses import Response

        scraper = UzExScraper(headless=True)
        file_bytes, downloaded_name = await scraper.download_file(tender.source_url, file_path)
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
        
    except Exception as e:
        logger.error(f"Document download failed for {doc_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

@router.get("", response_model=list[TenderResponse])
async def list_tenders(
    db: AsyncSession = Depends(get_db),
) -> list[TenderResponse]:
    """
    List all tenders, sorted by created_at descending.
    
    Returns up to 20 tenders.
    """
    result = await db.execute(
        select(Tender)
        .options(
            load_only(
                Tender.id,
                Tender.external_id,
                Tender.source_url,
                Tender.title,
                Tender.description,
                Tender.budget,
                Tender.currency,
                Tender.deadline,
                Tender.region,
                Tender.status,
                Tender.category,
                Tender.compiled_master_text,
                Tender.created_at,
            )
        )
        .order_by(Tender.created_at.desc())
        .limit(20)
    )
    tenders = result.scalars().all()
    
    return [_serialize_tender(t) for t in tenders]


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
                Tender.source_url,
                Tender.title,
                Tender.description,
                Tender.budget,
                Tender.currency,
                Tender.deadline,
                Tender.region,
                Tender.status,
                Tender.category,
                Tender.compiled_master_text,
                Tender.created_at,
            )
        )
        .where(Tender.id == tender_id)
    )
    tender = result.scalar_one_or_none()
    
    if not tender:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )
    
    return _serialize_tender(tender)


@router.post("/refresh", response_model=RefreshResponse)
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
        scraped_tenders = await scraper.fetch_latest_tenders(limit=10)
        
        logger.info(f"Scraped {len(scraped_tenders)} tenders from portal")
        
        for scraped in scraped_tenders:
            # Check if tender exists by external_id
            result = await db.execute(
                select(Tender).where(Tender.external_id == scraped.external_id)
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                # Update existing tender
                existing.title = scraped.title
                existing.budget = scraped.budget
                existing.currency = scraped.currency
                existing.source_url = scraped.source_url
                if scraped.region:
                    existing.region = scraped.region
                if scraped.deadline:
                    existing.deadline = scraped.deadline
                existing.category = scraped.category
                updated_count += 1
                logger.info(f"Updated tender: {scraped.external_id}")
            else:
                # Insert new tender
                tender = Tender(
                    id=uuid4(),
                    external_id=scraped.external_id,
                    source_url=scraped.source_url,
                    title=scraped.title,
                    description=None,
                    budget=scraped.budget,
                    currency=scraped.currency,
                    deadline=scraped.deadline,
                    region=scraped.region,
                    category=scraped.category,
                    status=TenderStatus.OPEN,
                )
                db.add(tender)
                new_count += 1
                logger.info(f"Added new tender: {scraped.external_id}")
        
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


def _normalize_task_status(state: str) -> str:
    normalized = state.upper()
    if normalized in {"PENDING", "STARTED", "SUCCESS", "FAILURE"}:
        return normalized
    if normalized in {"RECEIVED", "RETRY"}:
        return "STARTED"
    if normalized in {"REVOKED"}:
        return "FAILURE"
    return "PENDING"


@router.post(
    "/{tender_id}/sync-docs",
    response_model=SyncDocsAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_tender_documents(
    tender_id: UUID,
) -> SyncDocsAcceptedResponse:
    """
    Enqueue tender document sync to Celery worker.
    """
    task = process_tender_docs.delay(str(tender_id))
    return SyncDocsAcceptedResponse(message="Sync started", job_id=task.id)


@router.get("/sync-status/{job_id}", response_model=SyncStatusResponse)
async def get_sync_status(job_id: str) -> SyncStatusResponse:
    task = celery_app.AsyncResult(job_id)
    normalized_status = _normalize_task_status(task.status)
    return SyncStatusResponse(
        job_id=job_id,
        status=normalized_status,
        message=f"Job status: {normalized_status}",
    )


@router.get("/{tender_id}/documents")
async def get_tender_documents(
    tender_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all parsed documents for a given tender.
    """
    access_result = await db.execute(
        select(Proposal.id)
        .where(
            Proposal.tender_id == tender_id,
            Proposal.user_id == current_user.id,
        )
        .limit(1)
    )
    if access_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )

    result = await db.execute(
        select(TenderDocument)
        .join(Proposal, Proposal.tender_id == TenderDocument.tender_id)
        .where(
            TenderDocument.tender_id == tender_id,
            Proposal.user_id == current_user.id,
        )
        .distinct()
    )
    return result.scalars().all()


@router.get("/{tender_id}/docs-status")
async def get_docs_status(
    tender_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Lightweight check for whether tender documents are already synced.

    Used by the frontend to skip redundant Celery sync-docs calls.
    """
    access_result = await db.execute(
        select(Proposal.id)
        .where(
            Proposal.tender_id == tender_id,
            Proposal.user_id == current_user.id,
        )
        .limit(1)
    )
    if access_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )

    result = await db.execute(
        select(TenderDocument)
        .join(Proposal, Proposal.tender_id == TenderDocument.tender_id)
        .where(
            TenderDocument.tender_id == tender_id,
            Proposal.user_id == current_user.id,
        )
        .distinct()
    )
    docs = result.scalars().all()
    has_parsed = any(bool(d.parsed_text and d.parsed_text.strip()) for d in docs)
    return {
        "tender_id": str(tender_id),
        "doc_count": len(docs),
        "has_parsed_text": has_parsed,
    }


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
    profile_result = await db.execute(
        select(CompanyProfile).where(CompanyProfile.user_id == current_user.id)
    )
    profile = profile_result.scalar_one_or_none()
    analysis_owner_key = _analysis_owner_key(
        current_user=current_user,
        profile=profile,
    )

    result = await db.execute(
        select(TenderAnalysis)
        .where(
            TenderAnalysis.tender_id == tender_id,
            TenderAnalysis.company_name == analysis_owner_key,
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
        }

    analysis_data = analysis.analysis_json or {}
    return {
        "analysis_id": str(analysis.id),
        "requirements": analysis_data.get("requirements"),
        "evaluation": analysis_data.get("evaluation"),
    }


@router.post("/{tender_id}/override")
async def override_risk(
    tender_id: UUID,
    request: RiskOverrideRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """
    Record liability acceptance override with a cryptographic state hash.
    """
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
    analysis_result = await db.execute(
        select(TenderAnalysis.id).where(
            TenderAnalysis.id == request.analysis_id,
            TenderAnalysis.tender_id == tender_id,
        )
    )
    if analysis_result.scalar_one_or_none() is None:
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
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Failed to persist risk override log")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database write failed: {exc}",
        ) from exc

    return {"state_hash": state_hash}


@router.get("/{tender_id}/overrides", response_model=RiskOverrideStatusResponse)
async def get_risk_overrides(
    tender_id: UUID,
    analysis_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RiskOverrideStatusResponse:
    """
    Return node IDs that the current user has already overridden for this tender.

    When ``analysis_id`` is provided, only overrides recorded against that
    specific analysis run are returned.  This prevents liability handshakes
    from leaking between analysis runs.
    """
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
    if analysis_id is not None:
        filters.append(RiskOverrideLog.analysis_id == analysis_id)

    result = await db.execute(
        select(RiskOverrideLog.missing_node_id).where(*filters)
    )
    accepted_node_ids = sorted({str(row[0]) for row in result.all()})
    return RiskOverrideStatusResponse(
        tender_id=tender_id,
        accepted_node_ids=accepted_node_ids,
    )


@router.post("/seed", response_model=dict)
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
        # Check if already exists
        result = await db.execute(
            select(Tender).where(Tender.external_id == tender_data["external_id"])
        )
        if result.scalar_one_or_none():
            skip_count += 1
            continue
        
        tender = Tender(id=uuid4(), **tender_data)
        db.add(tender)
        new_count += 1
    
    await db.commit()
    
    return {"message": f"Seeded {new_count} new tenders ({skip_count} already existed)"}
