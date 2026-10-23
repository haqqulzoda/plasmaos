"""B1: the bank transfer invoice as a PDF (A4, English). Rendered from the stored invoice, so the
same invoice always renders the same figures (the CBU rate and the buyer are stored on it)."""

from __future__ import annotations

from decimal import Decimal
import io
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import settings
from app.models.billing import BillingInvoice, BillingOrder

FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"
FONT = "PlasmaInvoiceRoboto"
FONT_BOLD = "PlasmaInvoiceRoboto-Bold"

PRODUCT_LINES = {
    "pilot": "Plasma Pilot, 3 months: 6 pursuits, 1 partner introduction, EOI, own evidence, partner search",
    "pursuit_desk": "Plasma Pursuit Desk, 12 months: 24 pursuits a year, 2 partner introductions a year",
    "extra_pursuit": "Extra pursuit: 1 additional pursuit in the current plan period",
}
PILOT_NOTE = "The pilot payment is credited to the first annual invoice."


def _fonts() -> None:
    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT, str(FONTS_DIR / "Roboto-Regular.ttf")))
        pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONTS_DIR / "Roboto-Bold.ttf")))


def usd(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}USD {abs(cents) / 100:,.2f}"


def uzs(amount: Decimal) -> str:
    return f"UZS {amount:,.2f}".replace(",", "\u00a0")  # no-break spaces: never split a number


def bank_lines(currency: str) -> list[str]:
    raw = settings.INVOICE_BANK_DETAILS_UZS if currency == "UZS" else settings.INVOICE_BANK_DETAILS_USD
    return [line.strip() for line in (raw or "").split("|") if line.strip()]


def render_invoice_pdf(invoice: BillingInvoice, order: BillingOrder) -> bytes:
    _fonts()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Invoice {invoice.number}", author=settings.INVOICE_SELLER_NAME,
    )
    body = ParagraphStyle("body", fontName=FONT, fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11.5, textColor=colors.HexColor("#444444"))
    title = ParagraphStyle("title", parent=body, fontName=FONT_BOLD, fontSize=18, leading=22)
    heading = ParagraphStyle("heading", parent=body, fontName=FONT_BOLD, fontSize=10.5, leading=14)

    def para(text: str, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    buyer = invoice.customer or {}
    seller = [settings.INVOICE_SELLER_NAME, settings.INVOICE_SELLER_ADDRESS]
    if settings.INVOICE_SELLER_TIN:
        seller.append(f"TIN {settings.INVOICE_SELLER_TIN}")
    seller.append(f"{settings.INVOICE_SELLER_EMAIL} · {settings.INVOICE_SELLER_PHONE}")
    bill_to = [str(buyer.get("legal_name") or "")]
    if buyer.get("tin"):
        bill_to.append(f"TIN {buyer['tin']}")
    bill_to += [str(buyer.get("address") or ""), str(buyer.get("country") or ""), str(buyer.get("billing_email") or "")]

    story: list = [
        para(f"Invoice {invoice.number}", title), Spacer(1, 3 * mm),
        para(f"Issued {invoice.issued_on:%d %B %Y} · Due {invoice.due_on:%d %B %Y}", small), Spacer(1, 6 * mm),
    ]
    parties = Table(
        [[para("From", heading), para("Bill to", heading)], [para("\n".join(seller)), para("\n".join(bill_to))]],
        colWidths=[87 * mm, 87 * mm],
    )
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [parties, Spacer(1, 7 * mm)]

    term = ""
    if order.plan_started_on and order.plan_ends_on:
        term = f"\nTerm {order.plan_started_on:%d %b %Y} to {order.plan_ends_on:%d %b %Y}"
    rows = [
        [para("Description", heading), para("Amount", heading)],
        [para(PRODUCT_LINES.get(order.product, order.product) + term), para(usd(invoice.list_amount_cents))],
    ]
    if invoice.credit_cents:
        rows.append([para("Pilot credit (the paid pilot, credited once)"), para(usd(-invoice.credit_cents))])
    rows.append([para("Total", heading), para(usd(invoice.total_usd_cents), heading)])
    if invoice.currency == "UZS" and invoice.total_uzs is not None and invoice.fx_rate is not None:
        rows.append([
            para(f"Total payable in UZS at the Central Bank of Uzbekistan rate of {invoice.fx_rate_date:%d.%m.%Y}: "
                 f"{invoice.fx_rate:,.2f} UZS per USD".replace(",", "\u00a0"), heading),
            para(uzs(Decimal(invoice.total_uzs)), heading),
        ])
    lines = Table(rows, colWidths=[134 * mm, 40 * mm])
    lines.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
        ("LINEABOVE", (0, -1 if invoice.currency == "USD" else -2), (-1, -1 if invoice.currency == "USD" else -2), 0.6, colors.black),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [lines, Spacer(1, 6 * mm)]
    if order.product == "pilot":
        story += [para(PILOT_NOTE, heading), Spacer(1, 4 * mm)]

    story += [para("Payment by bank transfer", heading)]
    details = bank_lines(invoice.currency)
    story += [para("\n".join(details) if details else "Bank details: ask hq@plasmaos.uz")]
    story += [
        Spacer(1, 2 * mm),
        para(f"Payment reference: {invoice.number}", heading),
        Spacer(1, 4 * mm),
        para(
            f"The plan is active from the issue date. Please pay by {invoice.due_on:%d %B %Y}: an invoice unpaid "
            f"on that day returns the organization to the free Explore plan until the payment arrives.", small,
        ),
    ]
    if order.product == "pilot":
        story += [para("Full refund within 30 days of payment if the pilot does not work for you.", small)]
    document.build(story)
    return buffer.getvalue()
