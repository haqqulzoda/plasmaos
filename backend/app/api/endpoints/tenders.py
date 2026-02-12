"""
Plasma AI - Tenders Endpoints

Public tender feed for the Autonomous Tender Officer.
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scraper import UzExScraper
from app.db.session import get_db
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

@router.get("/", response_model=list[TenderResponse])
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
    from app.core.telegram import broadcast_new_tender
    from app.models.all_models import User
    
    new_count = 0
    updated_count = 0
    new_tenders_data: list[dict] = []  # Track new tenders for notification
    
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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Portal Unreachable: {type(e).__name__}: {str(e)}",
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
    
    try:
        # Scrape documents from source page
        scraper = UzExScraper(headless=True, timeout=30000)
        scraped_docs = await scraper.scrape_tender_documents(tender.source_url)
        
        # Get existing documents for this tender
        existing_result = await db.execute(
            select(TenderDocument).where(TenderDocument.tender_id == tender_id)
        )
        existing_docs = existing_result.scalars().all()
        existing_urls = {doc.file_url for doc in existing_docs}
        
        # Add new documents
        new_count = 0
        for doc_data in scraped_docs:
            if doc_data["file_url"] not in existing_urls:
                new_doc = TenderDocument(
                    id=uuid4(),
                    tender_id=tender_id,
                    file_url=doc_data["file_url"],
                    file_type=doc_data["file_type"],
                )
                db.add(new_doc)
                new_count += 1
        
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
            message=f"Synced {new_count} new documents, {len(all_docs)} total",
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
    [DEV ONLY] Seed the database with dummy tenders for demo.
    """
    now = datetime.now(timezone.utc)
    
    dummy_tenders = [
        {
            "id": uuid4(),
            "external_id": "UZEX-2026-00145",
            "source_url": "https://etender.uzex.uz/lot/145",
            "title": "Repair of School #45 Roof",
            "description": "Complete roof replacement for secondary school #45 including waterproofing, insulation, and drainage system installation.",
            "budget": 450_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=14),
            "region": "Tashkent",
            "status": TenderStatus.OPEN,
        },
        {
            "id": uuid4(),
            "external_id": "UZEX-2026-00238",
            "source_url": "https://etender.uzex.uz/lot/238",
            "title": "Supply of Desktop Computers (i5/16GB)",
            "description": "Procurement of 50 desktop computers for regional tax office. Specs: Intel i5 12th gen, 16GB RAM, 512GB SSD, 24\" monitor.",
            "budget": 120_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=7),
            "region": "Samarkand",
            "status": TenderStatus.OPEN,
        },
        {
            "id": uuid4(),
            "external_id": "UZEX-2026-00312",
            "source_url": "https://etender.uzex.uz/lot/312",
            "title": "Construction of Children's Playground",
            "description": "Full construction of outdoor playground with safety flooring, swings, slides, and climbing structures for kindergarten #12.",
            "budget": 800_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=21),
            "region": "Bukhara",
            "status": TenderStatus.OPEN,
        },
        {
            "id": uuid4(),
            "external_id": "UZEX-2026-00089",
            "source_url": "https://etender.uzex.uz/lot/089",
            "title": "Medical Equipment for District Hospital",
            "description": "Supply of MRI machine, X-ray equipment, and ultrasound devices for district hospital modernization project.",
            "budget": 2_500_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=30),
            "region": "Fergana",
            "status": TenderStatus.OPEN,
        },
        {
            "id": uuid4(),
            "external_id": "UZEX-2026-00401",
            "source_url": "https://etender.uzex.uz/lot/401",
            "title": "Road Repair Works - M39 Highway Section",
            "description": "Asphalt resurfacing for 12km section of M39 highway including drainage improvements and road markings.",
            "budget": 1_200_000_000.0,
            "currency": "UZS",
            "deadline": now + timedelta(days=10),
            "region": "Navoi",
            "status": TenderStatus.OPEN,
        },
    ]
    
    for tender_data in dummy_tenders:
        tender = Tender(**tender_data)
        db.add(tender)
    
    await db.commit()
    
    return {"message": f"Seeded {len(dummy_tenders)} tenders successfully"}
