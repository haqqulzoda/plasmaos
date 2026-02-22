"""
Plasma AI - Tenders Endpoints

Public tender feed for the Autonomous Tender Officer.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_analyzer import GapAnalysisResult, analyze_tender_gaps
from app.core.parser import process_tender_document
from app.core.scraper import UzExScraper
from app.db.session import get_db
from app.models.audit import TenderAnalysis
from app.models.all_models import Tender, TenderDocument, TenderStatus
from app.schemas.tender import TenderResponse

logger = logging.getLogger(__name__)

router = APIRouter()


class RefreshResponse(BaseModel):
    """Response for refresh endpoint."""
    status: str
    new_count: int
    updated_count: int
    message: str


class TenderDocumentResponse(BaseModel):
    """Response for tender document."""
    id: UUID
    file_url: str
    file_type: str
    created_at: datetime
    
    model_config = {"from_attributes": True}


class SyncDocsResponse(BaseModel):
    """Response for sync-docs endpoint."""
    status: str
    documents: list[TenderDocumentResponse]
    new_count: int
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
    analysis: GapAnalysisResult


@router.post("/{tender_id}/analyze", response_model=AnalyzeTenderResponse)
async def analyze_tender(
    tender_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Analyze pre-scraped tender text and persist analysis result.
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
        company_profile_dict: dict[str, Any] = {
            "name": "Extracted Company",
        }
        analysis = await analyze_tender_gaps(
            tender_text=tender_text,
            company_profile=company_profile_dict,
        )

        company_name = str(company_profile_dict.get("name") or "Extracted Company")
        new_analysis = TenderAnalysis(
            tender_id=tender.id,
            tender_file_name=f"tender_{tender.external_id}",
            company_name=company_name,
            raw_extracted_text=tender_text,
            analysis_json=analysis.model_dump(mode="json"),
        )
        session.add(new_analysis)
        await session.commit()
        await session.refresh(new_analysis)
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
        "analysis": analysis,
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
        
        # Determine content type
        content_type = "application/octet-stream"
        if filename.endswith(".pdf"):
            content_type = "application/pdf"
        elif filename.endswith(".docx"):
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif filename.endswith(".doc"):
            content_type = "application/msword"
        elif filename.endswith(".xlsx"):
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif filename.endswith(".xls"):
            content_type = "application/vnd.ms-excel"
        elif filename.endswith(".zip"):
            content_type = "application/zip"
        
        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
        
    except Exception as e:
        logger.error(f"Proxy download failed: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@router.get("/documents/{doc_id}/download")
async def download_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Download a tender document by ID.
    
    Looks up the document in the database, gets its tender's source URL,
    and proxies the download through Playwright (needed because UzEx
    requires POST with dynamic validation tokens).
    
    Can be used as href in <a> tags or src in <iframe> for PDF preview.
    """
    from fastapi.responses import Response
    
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
    
    # Extract file path from file_url
    # e.g., "https://apietender.uzex.uz/api/common/DownloadFile?path=/files/2025/12/23/xxx.pdf"
    file_path = ""
    if "path=" in doc.file_url:
        file_path = doc.file_url.split("path=")[-1]
    else:
        file_path = doc.file_url
    
    filename = file_path.split("/")[-1] if "/" in file_path else f"document.{doc.file_type}"
    
    try:
        scraper = UzExScraper(headless=True)
        file_bytes, downloaded_name = await scraper.download_file(tender.source_url, file_path)
        
        # Determine content type
        content_type = "application/octet-stream"
        if doc.file_type == "pdf" or filename.endswith(".pdf"):
            content_type = "application/pdf"
        elif doc.file_type in ("doc", "docx"):
            content_type = "application/msword"
        elif doc.file_type in ("xls", "xlsx"):
            content_type = "application/vnd.ms-excel"
        elif doc.file_type == "zip":
            content_type = "application/zip"
        
        # Use inline disposition for PDF (enables iframe preview), attachment for others
        disposition = "inline" if content_type == "application/pdf" else "attachment"
        
        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={"Content-Disposition": f'{disposition}; filename="{downloaded_name or filename}"'}
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
        .order_by(Tender.created_at.desc())
        .limit(20)
    )
    tenders = result.scalars().all()
    
    return [TenderResponse.model_validate(t) for t in tenders]


@router.get("/{tender_id}", response_model=TenderResponse)
async def get_tender(
    tender_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> TenderResponse:
    """
    Get a specific tender by ID.
    """
    result = await db.execute(
        select(Tender).where(Tender.id == tender_id)
    )
    tender = result.scalar_one_or_none()
    
    if not tender:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )
    
    return TenderResponse.model_validate(tender)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_tenders(
    db: AsyncSession = Depends(get_db),
) -> RefreshResponse:
    """
    Scrape latest tenders from UzEx portal and upsert into database.
    
    This endpoint triggers a live scrape of etender.uzex.uz
    and updates the database with new or modified tenders.
    
    Also sends Telegram alerts for new tenders to all users with telegram_id.
    
    Returns count of new and updated tenders.
    """
    import traceback
    
    new_count = 0
    updated_count = 0
    new_tenders_data: list[dict] = []  # Track new tenders for notification
    
    try:
        from app.core.telegram import broadcast_new_tender
        from app.models.all_models import User
        
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
                
                # Track for telegram notification
                new_tenders_data.append({
                    "id": str(tender.id),
                    "title": scraped.title,
                    "budget": scraped.budget,
                    "currency": scraped.currency,
                    "region": scraped.region,
                })
                logger.info(f"Added new tender: {scraped.external_id}")
        
        await db.commit()
        
        # Send Telegram alerts for new tenders
        if new_tenders_data:
            try:
                # Get all users with telegram_id
                users_result = await db.execute(
                    select(User.telegram_id).where(User.telegram_id.isnot(None))
                )
                chat_ids = [row[0] for row in users_result.fetchall() if row[0]]
                
                logger.info(f"Broadcasting {len(new_tenders_data)} new tenders to {len(chat_ids)} users")
                
                for tender_info in new_tenders_data:
                    await broadcast_new_tender(
                        tender_id=tender_info["id"],
                        title=tender_info["title"],
                        budget=tender_info["budget"],
                        currency=tender_info["currency"],
                        region=tender_info["region"],
                        user_chat_ids=chat_ids,
                    )
            except Exception as e:
                logger.error(f"Telegram broadcast failed: {e}")
                # Don't fail the whole request if notifications fail
        
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


@router.post("/{tender_id}/sync-docs", response_model=SyncDocsResponse)
async def sync_tender_documents(
    tender_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> SyncDocsResponse:
    """
    Fetch and sync documents from a tender's source page.
    
    Scrapes the tender detail page for PDF/DOC/XLS files and stores them.
    """
    import traceback
    
    # Get tender from DB
    result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = result.scalar_one_or_none()
    
    if not tender:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )
    
    def extract_file_path(file_url: str) -> str:
        """
        Extract downloadable file path from UzEx URLs.

        Examples:
        - https://.../DownloadFile?path=/files/2025/..../doc.pdf -> /files/...
        - /files/2025/.../doc.pdf -> /files/...
        """
        parsed = urlparse(file_url)
        query_path = parse_qs(parsed.query).get("path", [None])[0]
        if query_path:
            return unquote(query_path)
        return file_url

    try:
        # Scrape documents from source page
        scraper = UzExScraper(headless=True, timeout=30000)
        scraped_docs = await scraper.scrape_tender_documents(tender.source_url)
        
        # Get existing documents for this tender
        existing_result = await db.execute(
            select(TenderDocument).where(TenderDocument.tender_id == tender_id)
        )
        existing_docs = existing_result.scalars().all()
        existing_by_url = {doc.file_url: doc for doc in existing_docs}
        
        # Add new documents
        new_count = 0
        parsed_count = 0
        parsed_text_by_url: dict[str, str] = {
            doc.file_url: doc.parsed_text.strip()
            for doc in existing_docs
            if doc.parsed_text and doc.parsed_text.strip()
        }

        for doc_data in scraped_docs:
            doc = existing_by_url.get(doc_data["file_url"])
            if not doc:
                new_doc = TenderDocument(
                    id=uuid4(),
                    tender_id=tender_id,
                    file_url=doc_data["file_url"],
                    file_type=doc_data["file_type"],
                )
                db.add(new_doc)
                doc = new_doc
                existing_by_url[doc_data["file_url"]] = doc
                new_count += 1

            # Download and parse every discovered document so master text stays current.
            file_path = extract_file_path(doc.file_url)
            try:
                file_bytes, filename = await scraper.download_file(
                    tender_url=tender.source_url,
                    file_path=file_path,
                )
                extracted_text = await process_tender_document(
                    source=file_bytes,
                    filename=filename,
                )
                if extracted_text.strip():
                    doc.parsed_text = extracted_text
                    parsed_count += 1
                    parsed_text_by_url[doc.file_url] = f"[{filename}]\n{extracted_text.strip()}"
            except Exception as parse_exc:
                logger.warning(
                    "Failed to parse tender document '%s' for tender %s: %s",
                    doc.file_url,
                    tender_id,
                    parse_exc,
                )
                continue

        compiled_chunks = [text for text in parsed_text_by_url.values() if text.strip()]
        tender.compiled_master_text = "\n\n".join(compiled_chunks).strip() if compiled_chunks else None
        
        await db.commit()
        
        # Fetch all documents to return
        all_docs_result = await db.execute(
            select(TenderDocument).where(TenderDocument.tender_id == tender_id)
        )
        all_docs = all_docs_result.scalars().all()
        
        return SyncDocsResponse(
            status="success",
            documents=[TenderDocumentResponse.model_validate(d) for d in all_docs],
            new_count=new_count,
            message=(
                f"Synced {new_count} new documents, parsed {parsed_count} documents, "
                f"{len(all_docs)} total"
            ),
        )
        
    except Exception as e:
        error_tb = traceback.format_exc()
        logger.error(f"Document sync failed: {e}\n{error_tb}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to fetch documents: {str(e)}",
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
