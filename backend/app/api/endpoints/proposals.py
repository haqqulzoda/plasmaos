"""
Plasma AI - Proposals Endpoints

AI-generated proposal management with tier gating.
"""

import asyncio
import io
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_tier
from app.db.session import get_db
from app.models.all_models import Proposal, ProposalStatus, SubscriptionTier, Tender, User
from app.schemas.proposal import (
    ProposalCreate,
    ProposalResponse,
    ProposalUpdate,
    ProposalWithTenderResponse,
)

router = APIRouter()


# =============================================================================
# Additional Schemas
# =============================================================================

class AIItem(BaseModel):
    """Single item extracted from tender."""
    name: str
    quantity: int | float = 1
    unit: str = "pcs"


class AIDraftResponse(BaseModel):
    """Response from AI analysis."""
    estimated_cost: float
    suggested_margin: float
    delivery_days: int
    technical_summary: str
    confidence_score: int
    # Extended AI analysis fields
    items: list[AIItem] = []
    required_licenses: list[str] = []
    key_requirements: list[str] = []
    risks: list[str] = []


class PDFGenerateRequest(BaseModel):
    """Request body for PDF generation."""
    price: float
    delivery_days: int
    company_name: str = "Your Company LLC"


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/", response_model=ProposalResponse, status_code=status.HTTP_201_CREATED)
async def create_proposal(
    proposal_data: ProposalCreate,
    current_user: User = Depends(require_tier(SubscriptionTier.SCOUT)),
    db: AsyncSession = Depends(get_db),
) -> ProposalResponse:
    """
    Create a new proposal draft for a tender.
    
    Requires: Agent tier or higher.
    """
    # Verify tender exists
    result = await db.execute(
        select(Tender).where(Tender.id == proposal_data.tender_id)
    )
    tender = result.scalar_one_or_none()
    
    if not tender:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )
    
    # Check if user already has a proposal for this tender
    existing_result = await db.execute(
        select(Proposal).where(
            Proposal.user_id == current_user.id,
            Proposal.tender_id == proposal_data.tender_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    
    if existing:
        # Return existing proposal
        return ProposalResponse.model_validate(existing)
    
    # Create new proposal
    proposal = Proposal(
        user_id=current_user.id,
        tender_id=proposal_data.tender_id,
        status=ProposalStatus.DRAFT,
        ai_confidence_score=0,
        structured_data={},
    )
    db.add(proposal)
    await db.commit()
    await db.refresh(proposal)
    
    return ProposalResponse.model_validate(proposal)


@router.get("/", response_model=list[ProposalWithTenderResponse])
async def list_proposals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProposalWithTenderResponse]:
    """
    List all proposals for the current user.
    """
    result = await db.execute(
        select(Proposal)
        .options(selectinload(Proposal.tender))
        .where(Proposal.user_id == current_user.id)
        .order_by(Proposal.created_at.desc())
    )
    proposals = result.scalars().all()
    
    response = []
    for p in proposals:
        data = ProposalWithTenderResponse(
            id=p.id,
            user_id=p.user_id,
            tender_id=p.tender_id,
            status=p.status,
            ai_confidence_score=p.ai_confidence_score,
            structured_data=p.structured_data,
            final_pdf_url=p.final_pdf_url,
            margin_percent=p.margin_percent,
            include_vat=p.include_vat,
            currency=p.currency,
            created_at=p.created_at,
            tender_title=p.tender.title if p.tender else "Unknown",
            tender_budget=p.tender.budget if p.tender else 0,
            tender_currency=p.tender.currency if p.tender else "UZS",
            tender_deadline=p.tender.deadline if p.tender else None,
            tender_region=p.tender.region if p.tender else None,
        )
        response.append(data)
    
    return response


@router.get("/{proposal_id}", response_model=ProposalWithTenderResponse)
async def get_proposal(
    proposal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProposalWithTenderResponse:
    """
    Get a specific proposal with tender details.
    """
    result = await db.execute(
        select(Proposal)
        .options(selectinload(Proposal.tender))
        .where(
            Proposal.id == proposal_id,
            Proposal.user_id == current_user.id,
        )
    )
    proposal = result.scalar_one_or_none()
    
    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proposal not found",
        )
    
    return ProposalWithTenderResponse(
        id=proposal.id,
        user_id=proposal.user_id,
        tender_id=proposal.tender_id,
        status=proposal.status,
        ai_confidence_score=proposal.ai_confidence_score,
        structured_data=proposal.structured_data,
        final_pdf_url=proposal.final_pdf_url,
        margin_percent=proposal.margin_percent,
        include_vat=proposal.include_vat,
        currency=proposal.currency,
        created_at=proposal.created_at,
        tender_title=proposal.tender.title if proposal.tender else "Unknown",
        tender_budget=proposal.tender.budget if proposal.tender else 0,
        tender_currency=proposal.tender.currency if proposal.tender else "UZS",
        tender_deadline=proposal.tender.deadline if proposal.tender else None,
        tender_region=proposal.tender.region if proposal.tender else None,
    )


@router.put("/{proposal_id}", response_model=ProposalResponse)
async def update_proposal(
    proposal_id: UUID,
    update_data: ProposalUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProposalResponse:
    """
    Update proposal data with financial calculations.
    
    Calculates:
    - unit_price = base_cost × (1 + margin_percent/100)
    - subtotal = sum of all item totals
    - vat_amount = subtotal × 0.12 (if include_vat)
    - grand_total = subtotal + vat_amount
    """
    result = await db.execute(
        select(Proposal).where(
            Proposal.id == proposal_id,
            Proposal.user_id == current_user.id,
        )
    )
    proposal = result.scalar_one_or_none()
    
    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proposal not found",
        )
    
    # Update financial model fields
    if update_data.margin_percent is not None:
        proposal.margin_percent = update_data.margin_percent
    
    if update_data.include_vat is not None:
        proposal.include_vat = update_data.include_vat
    
    # Get current margin for calculations
    margin = proposal.margin_percent
    include_vat = proposal.include_vat
    
    # Update structured data
    if update_data.structured_data is not None:
        proposal.structured_data = update_data.structured_data
    
    current_data: dict[str, Any] = proposal.structured_data or {}
    
    # Process items with financial calculations
    if update_data.items is not None:
        calculated_items = []
        subtotal = 0.0
        
        for item in update_data.items:
            # Calculate unit sell price from base cost + margin
            unit_price = item.base_cost * (1 + margin / 100)
            total_item = unit_price * item.quantity
            subtotal += total_item
            
            calculated_items.append({
                "name": item.name,
                "unit": item.unit,
                "quantity": item.quantity,
                "base_cost": item.base_cost,
                "unit_price": round(unit_price, 2),
                "total": round(total_item, 2),
            })
        
        # Calculate VAT and grand total
        vat_amount = subtotal * 0.12 if include_vat else 0.0
        grand_total = subtotal + vat_amount
        
        # Store calculated values
        current_data["ai_items"] = calculated_items
        current_data["subtotal"] = round(subtotal, 2)
        current_data["vat_amount"] = round(vat_amount, 2)
        current_data["grand_total"] = round(grand_total, 2)
        current_data["our_price"] = round(grand_total, 2)
    
    # Update individual fields
    if update_data.our_price is not None:
        current_data["our_price"] = update_data.our_price
    
    if update_data.delivery_days is not None:
        current_data["delivery_days"] = update_data.delivery_days
    
    proposal.structured_data = current_data
    
    await db.commit()
    await db.refresh(proposal)
    
    return ProposalResponse.model_validate(proposal)


@router.post("/{proposal_id}/ai-draft", response_model=AIDraftResponse)
async def ai_draft_proposal(
    proposal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AIDraftResponse:
    """
    AI-powered proposal analysis using Google Gemini.
    
    1. Fetches tender documents from database
    2. Downloads the first PDF via scraper proxy
    3. Extracts text using pypdf
    4. Analyzes with Gemini 1.5 Flash
    5. Returns structured data (items, delivery, requirements)
    """
    from app.core.ai import analyze_tender_text_async
    from app.core.parser import extract_text_from_bytes
    from app.core.scraper import UzExScraper
    from app.models.all_models import TenderDocument
    
    # Fetch proposal with tender
    result = await db.execute(
        select(Proposal)
        .options(selectinload(Proposal.tender))
        .where(
            Proposal.id == proposal_id,
            Proposal.user_id == current_user.id,
        )
    )
    proposal = result.scalar_one_or_none()
    
    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proposal not found",
        )
    
    if not proposal.tender:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Proposal has no associated tender",
        )
    
    # Fetch tender documents
    doc_result = await db.execute(
        select(TenderDocument)
        .where(TenderDocument.tender_id == proposal.tender.id)
        .order_by(TenderDocument.created_at)
    )
    documents = doc_result.scalars().all()
    
    if not documents:
        # No documents - return fallback analysis
        tender_budget = proposal.tender.budget
        return AIDraftResponse(
            estimated_cost=tender_budget * 0.75,
            suggested_margin=20.0,
            delivery_days=30,
            technical_summary="No tender documents available for analysis. Please sync documents first.",
            confidence_score=50,
        )
    
    # Find first PDF document - REQUIRED for AI analysis
    pdf_doc = next((d for d in documents if d.file_type == "pdf"), None)
    if not pdf_doc:
        # No PDF available - need manual upload
        tender_budget = proposal.tender.budget
        doc_types = ", ".join(set(d.file_type for d in documents))
        return AIDraftResponse(
            estimated_cost=tender_budget * 0.75,
            suggested_margin=20.0,
            delivery_days=30,
            technical_summary=f"No PDF document available for analysis. Found: {doc_types}. Please upload the Technical Task PDF using the dropzone.",
            confidence_score=30,
        )
    
    # Extract file path from file_url
    file_path = ""
    if "path=" in pdf_doc.file_url:
        file_path = pdf_doc.file_url.split("path=")[-1]
    else:
        file_path = pdf_doc.file_url
    
    # Download the document via Playwright proxy and save to temp file
    import tempfile
    import os
    
    try:
        scraper = UzExScraper(headless=True)
        file_bytes, filename = await scraper.download_file(
            proposal.tender.source_url, 
            file_path
        )
        print(f"[AI-DRAFT] Downloaded {len(file_bytes)} bytes, filename={filename}")
        
        # Verify it's a valid PDF
        if not file_bytes or len(file_bytes) < 100:
            raise Exception("Downloaded file is empty or too small")
        
        if not file_bytes[:4] == b'%PDF':
            print(f"[AI-DRAFT] Warning: File doesn't start with PDF header, first 20 bytes: {file_bytes[:20]}")
        
    except Exception as e:
        # Download failed - return fallback
        tender_budget = proposal.tender.budget
        return AIDraftResponse(
            estimated_cost=tender_budget * 0.75,
            suggested_margin=20.0,
            delivery_days=30,
            technical_summary=f"Failed to download document for analysis: {e}",
            confidence_score=40,
        )
    
    # Save to temp file for Gemini upload
    temp_pdf_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(file_bytes)
            temp_pdf_path = f.name
        print(f"[AI-DRAFT] Saved to temp file: {temp_pdf_path}")
        
        # Build company context from user profile
        company_context = {
            "company_name": current_user.company_name or "",
            "core_services": getattr(current_user, 'core_services', '') or "",
            "past_experience": getattr(current_user, 'past_experience', '') or "",
        }
        
        # Analyze with Gemini AI (direct file upload - handles scanned PDFs!)
        from app.core.ai import analyze_tender_file_async
        ai_result = await analyze_tender_file_async(temp_pdf_path, company_context)
        
    finally:
        # Cleanup temp file
        if temp_pdf_path and os.path.exists(temp_pdf_path):
            try:
                os.unlink(temp_pdf_path)
                print(f"[AI-DRAFT] Cleaned up temp file")
            except Exception:
                pass
    
    # Calculate estimates based on AI analysis
    tender_budget = proposal.tender.budget
    items = ai_result.get("items", [])
    delivery_days = ai_result.get("delivery_days", 30)
    
    # Estimate cost (75% of budget as baseline)
    estimated_cost = tender_budget * 0.75
    suggested_price = tender_budget * 0.85  # 15% margin
    
    # Build technical summary
    summary = ai_result.get("summary", "Analysis complete.")
    requirements = ai_result.get("required_licenses", [])
    risks = ai_result.get("risks", [])
    
    if requirements:
        summary += f" Required: {', '.join(requirements[:3])}."
    if risks:
        summary += f" Risks: {risks[0]}."
    
    # Determine confidence score
    confidence = 85
    if "error" in ai_result:
        confidence = 50
    elif len(items) == 0:
        confidence = 65
    elif len(items) > 5:
        confidence = 90
    
    # Update proposal with AI analysis
    current_data: dict[str, Any] = proposal.structured_data or {}
    current_data["ai_estimated_cost"] = estimated_cost
    current_data["ai_suggested_price"] = suggested_price
    current_data["our_price"] = suggested_price
    current_data["delivery_days"] = delivery_days
    current_data["ai_items"] = items
    current_data["ai_requirements"] = requirements
    current_data["ai_risks"] = risks
    proposal.structured_data = current_data
    proposal.ai_confidence_score = confidence
    
    await db.commit()
    
    # Convert items to AIItem format
    ai_items = [
        AIItem(
            name=item.get("name", "Unknown"),
            quantity=item.get("quantity", 1),
            unit=item.get("unit", "pcs")
        )
        for item in items
    ]
    
    key_requirements = ai_result.get("key_requirements", [])
    
    return AIDraftResponse(
        estimated_cost=estimated_cost,
        suggested_margin=15.0,
        delivery_days=delivery_days,
        technical_summary=summary[:500],  # Limit length
        confidence_score=confidence,
        items=ai_items,
        required_licenses=requirements,
        key_requirements=key_requirements,
        risks=risks,
    )


@router.post("/{proposal_id}/upload-tz", response_model=AIDraftResponse)
async def upload_tender_tz(
    proposal_id: UUID,
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AIDraftResponse:
    """
    Upload a Technical Task PDF for tenders with archive (ZIP/RAR) documents.
    
    1. Saves uploaded PDF to backend/uploads/{tender_id}.pdf
    2. Updates/creates TenderDocument record to point to local file
    3. Extracts text and runs AI analysis
    4. Returns AI analysis result (same as ai-draft endpoint)
    """
    import os
    from pathlib import Path
    
    from app.core.ai import analyze_tender_text_async
    from app.core.parser import extract_text_from_file
    from app.models.all_models import TenderDocument
    
    # Fetch proposal with tender
    result = await db.execute(
        select(Proposal)
        .options(selectinload(Proposal.tender))
        .where(
            Proposal.id == proposal_id,
            Proposal.user_id == current_user.id,
        )
    )
    proposal = result.scalar_one_or_none()
    
    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proposal not found",
        )
    
    if not proposal.tender:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Proposal has no associated tender",
        )
    
    # Validate file type
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted",
        )
    
    # Save file to uploads directory
    uploads_dir = Path(__file__).parent.parent.parent.parent / "uploads"
    uploads_dir.mkdir(exist_ok=True)
    
    file_path = uploads_dir / f"{proposal.tender.id}.pdf"
    
    # Write file
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Find or create TenderDocument for this PDF
    doc_result = await db.execute(
        select(TenderDocument)
        .where(
            TenderDocument.tender_id == proposal.tender.id,
            TenderDocument.file_type == "pdf",
        )
    )
    doc = doc_result.scalar_one_or_none()
    
    if doc:
        # Update existing document
        doc.file_url = f"local://{file_path}"
    else:
        # Create new document
        doc = TenderDocument(
            tender_id=proposal.tender.id,
            file_url=f"local://{file_path}",
            file_type="pdf",
        )
        db.add(doc)
    
    await db.commit()
    await db.refresh(doc)
    
    # Extract text and update compiled_master_text for the Compliance Engine
    try:
        extracted_text = await extract_text_from_file(str(file_path))
        if extracted_text and extracted_text.strip():
            proposal.tender.compiled_master_text = extracted_text.strip()
            await db.commit()
            logger.info(f"[UPLOAD-TZ] Updated compiled_master_text ({len(extracted_text)} chars)")
    except Exception as parse_exc:
        logger.warning(f"[UPLOAD-TZ] Text extraction failed, compiled_master_text not updated: {parse_exc}")
    
    # Build company context from user profile
    company_context = {
        "company_name": current_user.company_name or "",
        "core_services": getattr(current_user, 'core_services', '') or "",
        "past_experience": getattr(current_user, 'past_experience', '') or "",
    }
    
    # Analyze with Gemini AI (direct file upload - handles scanned PDFs!)
    print(f"[UPLOAD-TZ] Analyzing file with Gemini: {file_path}")
    from app.core.ai import analyze_tender_file_async
    ai_result = await analyze_tender_file_async(str(file_path), company_context)
    
    # Calculate estimates based on AI analysis
    tender_budget = proposal.tender.budget
    items = ai_result.get("items", [])
    delivery_days = ai_result.get("delivery_days", 30)
    
    # Estimate cost (75% of budget as baseline)
    estimated_cost = tender_budget * 0.75
    suggested_price = tender_budget * 0.85  # 15% margin
    
    # Build technical summary
    summary = ai_result.get("summary", "Analysis complete.")
    requirements = ai_result.get("required_licenses", [])
    risks = ai_result.get("risks", [])
    
    if requirements:
        summary += f" Required: {', '.join(requirements[:3])}."
    if risks:
        summary += f" Risks: {risks[0]}."
    
    # Determine confidence score
    confidence = 85
    if "error" in ai_result:
        confidence = 50
    elif len(items) == 0:
        confidence = 65
    elif len(items) > 5:
        confidence = 90
    
    # Update proposal with AI analysis
    current_data: dict[str, Any] = proposal.structured_data or {}
    current_data["ai_estimated_cost"] = estimated_cost
    current_data["ai_suggested_price"] = suggested_price
    current_data["our_price"] = suggested_price
    current_data["delivery_days"] = delivery_days
    current_data["ai_items"] = items
    current_data["ai_requirements"] = requirements
    current_data["ai_risks"] = risks
    proposal.structured_data = current_data
    proposal.ai_confidence_score = confidence
    
    await db.commit()
    
    # Convert items to AIItem format
    ai_items = [
        AIItem(
            name=item.get("name", "Unknown"),
            quantity=item.get("quantity", 1),
            unit=item.get("unit", "pcs")
        )
        for item in items
    ]
    
    key_requirements = ai_result.get("key_requirements", [])
    
    return AIDraftResponse(
        estimated_cost=estimated_cost,
        suggested_margin=15.0,
        delivery_days=delivery_days,
        technical_summary=summary[:500],  # Limit length
        confidence_score=confidence,
        items=ai_items,
        required_licenses=requirements,
        key_requirements=key_requirements,
        risks=risks,
    )


@router.get("/{proposal_id}/uploaded-tz")
async def get_uploaded_tz(
    proposal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Serve the uploaded Technical Task PDF for preview.
    
    Returns the PDF file that was uploaded via /upload-tz endpoint.
    """
    from pathlib import Path
    from fastapi.responses import Response
    
    # Fetch proposal with tender
    result = await db.execute(
        select(Proposal)
        .options(selectinload(Proposal.tender))
        .where(
            Proposal.id == proposal_id,
            Proposal.user_id == current_user.id,
        )
    )
    proposal = result.scalar_one_or_none()
    
    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proposal not found",
        )
    
    if not proposal.tender:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Proposal has no associated tender",
        )
    
    # Look for uploaded PDF
    uploads_dir = Path(__file__).parent.parent.parent.parent / "uploads"
    file_path = uploads_dir / f"{proposal.tender.id}.pdf"
    
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No uploaded PDF found for this tender",
        )
    
    # Read file and return as Response (same pattern as working document download)
    file_bytes = file_path.read_bytes()
    
    return Response(
        content=file_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=tz_{proposal.tender.id}.pdf"},
    )


@router.post("/{proposal_id}/generate-pdf")
async def generate_proposal_pdf(
    proposal_id: UUID,
    pdf_data: PDFGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Generate a professional Commercial Proposal (KP) PDF.
    
    Uses company details from user profile and AI-extracted items from proposal.
    Returns a downloadable PDF document suitable for tender submissions.
    """
    # Fetch proposal with tender
    result = await db.execute(
        select(Proposal)
        .options(selectinload(Proposal.tender))
        .where(
            Proposal.id == proposal_id,
            Proposal.user_id == current_user.id,
        )
    )
    proposal = result.scalar_one_or_none()
    
    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proposal not found",
        )
    
    tender = proposal.tender
    if not tender:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tender not found for this proposal",
        )
    
    # Get company details from user profile (fallback to pdf_data for backwards compat)
    company_name = current_user.company_name or pdf_data.company_name
    director_name = current_user.director_name or "Director"
    company_address = current_user.address or ""
    
    # Get AI-extracted items from proposal structured_data
    structured_data = proposal.structured_data or {}
    ai_items = structured_data.get("ai_items", [])
    our_price = structured_data.get("our_price", pdf_data.price)
    delivery_days = structured_data.get("delivery_days", pdf_data.delivery_days)
    
    # Create PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4, 
        topMargin=1.5*cm, 
        bottomMargin=1.5*cm,
        leftMargin=2*cm,
        rightMargin=2*cm,
    )
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'KPTitle',
        parent=styles['Heading1'],
        fontSize=16,
        spaceAfter=20,
        alignment=1,  # Center
        textColor=colors.HexColor('#1a1a1a'),
    )
    header_style = ParagraphStyle(
        'HeaderBold',
        parent=styles['Normal'],
        fontSize=12,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#1a1a1a'),
    )
    normal_style = ParagraphStyle(
        'KPNormal',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#333333'),
        spaceAfter=6,
    )
    small_style = ParagraphStyle(
        'KPSmall',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#666666'),
    )
    
    elements = []
    
    # ========== HEADER ==========
    # Company name (left) and Date (right) on same line using table
    header_data = [[
        Paragraph(f"<b>{company_name}</b>", header_style),
        Paragraph(f"<b>Sana:</b> {datetime.now().strftime('%d.%m.%Y')}", normal_style),
    ]]
    header_table = Table(header_data, colWidths=[10*cm, 6*cm])
    header_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(header_table)
    
    # Company address if available
    if company_address:
        elements.append(Paragraph(company_address, small_style))
    elements.append(Spacer(1, 20))
    
    # ========== TITLE ==========
    elements.append(Paragraph(
        f"TIJORAT TAKLIFI (COMMERCIAL PROPOSAL)<br/>№ KP-{str(proposal_id)[:8].upper()}",
        title_style
    ))
    elements.append(Spacer(1, 15))
    
    # ========== INTRO ==========
    intro_text = f"Biz, <b>{company_name}</b>, {tender.external_id} raqamli tender bo'yicha quyidagi xizmatlarni taklif etamiz:"
    elements.append(Paragraph(intro_text, normal_style))
    elements.append(Spacer(1, 15))
    
    # ========== ITEMS TABLE ==========
    if ai_items and len(ai_items) > 0:
        # Calculate unit prices (distribute total evenly if no individual prices)
        total_qty = sum(item.get("quantity", 1) for item in ai_items)
        
        # Table headers
        items_table_data = [
            ["#", "Nomi (Name)", "Birlik", "Miqdor", "Narxi", "Jami"],
        ]
        
        running_total = 0
        for idx, item in enumerate(ai_items, 1):
            name = item.get("name", "Item")[:50]  # Truncate long names
            unit = item.get("unit", "dona")
            qty = item.get("quantity", 1)
            # Use pre-calculated unit_price if available, else estimate
            unit_price = item.get("unit_price", (our_price * qty / total_qty) / qty if total_qty > 0 else our_price / len(ai_items))
            item_total = item.get("total", unit_price * qty)
            running_total += item_total
            
            items_table_data.append([
                str(idx),
                name,
                unit,
                f"{qty:,.0f}",
                f"{unit_price:,.0f}",
                f"{item_total:,.0f}",
            ])
        
        # Get calculated values from structured_data
        subtotal = structured_data.get("subtotal", running_total)
        vat_amount = structured_data.get("vat_amount", 0)
        grand_total = structured_data.get("grand_total", our_price)
        
        # Subtotal row
        items_table_data.append([
            "", "", "", "", Paragraph("<b>Jami summa:</b>", normal_style), 
            Paragraph(f"<b>{subtotal:,.0f}</b>", normal_style)
        ])
        
        # VAT row (only if VAT is included)
        if proposal.include_vat and vat_amount > 0:
            items_table_data.append([
                "", "", "", "", Paragraph("QQS (12%):", normal_style), 
                Paragraph(f"+{vat_amount:,.0f}", normal_style)
            ])
        
        # Grand Total row
        items_table_data.append([
            "", "", "", "", Paragraph("<b>YAKUNIY JAMI:</b>", normal_style), 
            Paragraph(f"<b>{grand_total:,.0f} {tender.currency}</b>", normal_style)
        ])
        
        items_table = Table(
            items_table_data, 
            colWidths=[1*cm, 7*cm, 2*cm, 2*cm, 2.5*cm, 2.5*cm]
        )
        items_table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F46E5')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            # Data rows
            ('BACKGROUND', (0, 1), (-1, -2), colors.HexColor('#FAFAFA')),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # # column
            ('ALIGN', (2, 1), (-1, -1), 'CENTER'),  # Numeric columns
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            # Total row
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E8E8FF')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ]))
        elements.append(items_table)
    else:
        # Fallback: Simple summary table if no items
        summary_data = [
            ["Tavsif (Description)", "Qiymat (Value)"],
            ["Tender byudjeti", f"{tender.budget:,.0f} {tender.currency}"],
            ["Bizning narximiz", f"{our_price:,.0f} {tender.currency}"],
        ]
        summary_table = Table(summary_data, colWidths=[8*cm, 8*cm])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F46E5')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#FAFAFA')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(summary_table)
    
    elements.append(Spacer(1, 20))
    
    # ========== DELIVERY & TERMS ==========
    elements.append(Paragraph("<b>Yetkazib berish muddati:</b>", normal_style))
    elements.append(Paragraph(f"{delivery_days} ish kuni", normal_style))
    elements.append(Spacer(1, 10))
    
    elements.append(Paragraph("<b>To'lov shartlari:</b>", normal_style))
    elements.append(Paragraph("15% oldindan to'lov, 85% yetkazib berilgandan keyin", normal_style))
    elements.append(Spacer(1, 10))
    
    # VAT notice if applicable
    if proposal.include_vat:
        elements.append(Paragraph("<b>QQS:</b> Narxlar 12% QQSni o'z ichiga oladi (Prices include 12% VAT)", normal_style))
        elements.append(Spacer(1, 10))
    
    elements.append(Paragraph("<b>Taklif amal qilish muddati:</b> 30 kun", normal_style))
    elements.append(Spacer(1, 30))
    
    # ========== SIGNATURE ==========
    elements.append(Paragraph("<b>Direktor:</b>", normal_style))
    elements.append(Spacer(1, 20))
    
    sig_data = [[
        Paragraph(f"{director_name}", normal_style),
        "_" * 25,
        "(imzo / signature)"
    ]]
    sig_table = Table(sig_data, colWidths=[6*cm, 5*cm, 5*cm])
    sig_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
    ]))
    elements.append(sig_table)
    
    elements.append(Spacer(1, 20))
    
    # Stamp placeholder
    elements.append(Paragraph("M.O. (Muhr joyi / Stamp)", small_style))
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    # Update proposal status
    proposal.status = ProposalStatus.COMPLETED
    await db.commit()
    
    filename = f"KP_{tender.external_id}_{datetime.now().strftime('%Y%m%d')}.pdf"
    
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
        },
    )

