"""
Plasma AI - Quick PDF Generator

Standalone PDF generator for one-click proposal generation.
Uses reportlab with DejaVu Sans font for full Cyrillic/Unicode support.
"""

import io
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Register DejaVu Sans (Cyrillic-capable Unicode font) ──
FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"

pdfmetrics.registerFont(TTFont("DejaVu", str(FONTS_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONTS_DIR / "DejaVuSans-Bold.ttf")))

# Tell ReportLab to use DejaVu-Bold when <b> tags are used inside DejaVu
pdfmetrics.registerFontFamily(
    "DejaVu",
    normal="DejaVu",
    bold="DejaVu-Bold",
    italic="DejaVu",       # fallback to regular (no italic bundled)
    boldItalic="DejaVu-Bold",
)


def generate_quick_proposal_pdf(
    company_name: str,
    director_name: str,
    address: str,
    tender_title: str,
    tender_budget: float,
    currency: str,
    ai_summary: str,
    items: list[dict],
    delivery_days: int,
    inn: str = "",
    bank_name: str = "",
    mfo: str = "",
    account_number: str = "",
) -> bytes:
    """
    Generate a quick Commercial Proposal PDF.
    
    Args:
        company_name: Name of the user's company
        director_name: Name of the company director
        address: Company address
        tender_title: Title of the tender
        tender_budget: Budget amount
        currency: Currency code (UZS, USD, etc.)
        ai_summary: AI-generated technical summary
        items: List of items extracted by AI [{"name", "quantity", "unit"}]
        delivery_days: Delivery timeline in days
        inn: Company tax ID
        bank_name: Bank name
        mfo: Bank MFO code
        account_number: Bank account number
        
    Returns:
        PDF file as bytes
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
    )
    
    styles = getSampleStyleSheet()
    
    # ── Custom styles (all using DejaVu for Cyrillic support) ──
    title_style = ParagraphStyle(
        "KPTitle",
        parent=styles["Heading1"],
        fontName="DejaVu-Bold",
        fontSize=16,
        spaceAfter=20,
        alignment=1,  # Center
        textColor=colors.HexColor("#1a1a2e"),
    )
    
    heading_style = ParagraphStyle(
        "KPHeading",
        parent=styles["Heading2"],
        fontName="DejaVu-Bold",
        fontSize=12,
        spaceBefore=15,
        spaceAfter=8,
        textColor=colors.HexColor("#16213e"),
    )
    
    body_style = ParagraphStyle(
        "KPBody",
        parent=styles["Normal"],
        fontName="DejaVu",
        fontSize=10,
        leading=14,
        spaceAfter=6,
    )
    
    small_style = ParagraphStyle(
        "KPSmall",
        parent=styles["Normal"],
        fontName="DejaVu",
        fontSize=8,
        leading=11,
        textColor=colors.grey,
    )
    
    elements = []
    today = datetime.now().strftime("%d.%m.%Y")
    
    # ── Header ──
    elements.append(Paragraph("КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ", title_style))
    elements.append(Paragraph("(Commercial Proposal)", small_style))
    elements.append(Spacer(1, 10))
    
    # ── Date & Company Info ──
    header_data = [
        [f"Дата: {today}", f"От: {company_name}"],
    ]
    if address:
        header_data.append(["", f"Адрес: {address}"])
    
    header_table = Table(header_data, colWidths=[8 * cm, 9 * cm])
    header_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#333333")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 15))
    
    # ── Tender Reference ──
    elements.append(Paragraph("Предмет закупки (Tender Subject)", heading_style))
    elements.append(Paragraph(tender_title, body_style))
    elements.append(Spacer(1, 8))
    
    # ── Budget ──
    if tender_budget >= 1_000_000_000:
        budget_str = f"{tender_budget / 1_000_000_000:.2f} млрд {currency}"
    elif tender_budget >= 1_000_000:
        budget_str = f"{tender_budget / 1_000_000:.1f} млн {currency}"
    else:
        budget_str = f"{tender_budget:,.0f} {currency}"
    elements.append(Paragraph(f"<b>Бюджет тендера:</b> {budget_str}", body_style))
    elements.append(Spacer(1, 10))
    
    # ── AI Summary ──
    if ai_summary:
        elements.append(Paragraph("Техническое описание (Technical Summary)", heading_style))
        elements.append(Paragraph(ai_summary, body_style))
        elements.append(Spacer(1, 10))
    
    # ── Items Table ──
    if items:
        elements.append(Paragraph("Спецификация (Item Specification)", heading_style))
        
        table_data = [["№", "Наименование", "Кол-во", "Ед."]]
        for i, item in enumerate(items[:20], 1):  # Max 20 items
            table_data.append([
                str(i),
                str(item.get("name", "—"))[:60],
                str(item.get("quantity", 1)),
                str(item.get("unit", "шт")),
            ])
        
        item_table = Table(
            table_data,
            colWidths=[1.2 * cm, 10 * cm, 2.5 * cm, 2 * cm],
        )
        item_table.setStyle(TableStyle([
            # Header row
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            # Body rows
            ("FONTNAME", (0, 1), (-1, -1), "DejaVu"),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 1), (0, -1), "CENTER"),
            ("ALIGN", (2, 1), (3, -1), "CENTER"),
            # Grid
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(item_table)
        elements.append(Spacer(1, 10))
    
    # ── Delivery Terms ──
    elements.append(Paragraph("Условия поставки (Delivery Terms)", heading_style))
    elements.append(Paragraph(
        f"Срок поставки: <b>{delivery_days} рабочих дней</b> с момента подписания договора.",
        body_style,
    ))
    elements.append(Spacer(1, 15))
    
    # ── Banking Details ──
    if bank_name or inn:
        elements.append(Paragraph("Банковские реквизиты (Banking Details)", heading_style))
        bank_info = []
        if inn:
            bank_info.append(f"ИНН: {inn}")
        if bank_name:
            bank_info.append(f"Банк: {bank_name}")
        if mfo:
            bank_info.append(f"МФО: {mfo}")
        if account_number:
            bank_info.append(f"Р/с: {account_number}")
        elements.append(Paragraph("<br/>".join(bank_info), body_style))
        elements.append(Spacer(1, 15))
    
    # ── Signature ──
    elements.append(Spacer(1, 20))
    sig_data = [
        ["Директор / Director", ""],
        [director_name, "_____________________"],
    ]
    sig_table = Table(sig_data, colWidths=[10 * cm, 6 * cm])
    sig_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(sig_table)
    
    # ── Footer ──
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(
        f"Документ сгенерирован PlasmaOS • {today}",
        small_style,
    ))
    
    doc.build(elements)
    return buffer.getvalue()
