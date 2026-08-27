"""Customer-facing Compliance Analysis PDF builder."""

from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"

pdfmetrics.registerFont(TTFont("DejaVu", str(FONTS_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONTS_DIR / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily(
    "DejaVu",
    normal="DejaVu",
    bold="DejaVu-Bold",
    italic="DejaVu",
    boldItalic="DejaVu-Bold",
)

ACCENT = colors.HexColor("#4F46E5")
TEXT = colors.HexColor("#111827")
MUTED = colors.HexColor("#6B7280")
LINE = colors.HexColor("#E5E7EB")
SOFT = colors.HexColor("#F8FAFC")
WARN_SOFT = colors.HexColor("#FFFBEB")
BAD_SOFT = colors.HexColor("#FEF2F2")
GOOD_SOFT = colors.HexColor("#ECFDF5")


def _text(value: object, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        normalized = value.strip()
        return normalized if normalized else fallback
    return str(value)


def _xml(value: object, fallback: str = "") -> str:
    return escape(_text(value, fallback))


def _truncate(value: object, *, limit: int = 620) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _source_filename(value: object) -> str:
    raw = _text(value, "source document")
    normalized = raw.replace("\\", "/")
    name = PurePosixPath(normalized).name
    return name or "source document"


def _display_status(value: object) -> str:
    status = _text(value, "NEEDS_REVIEW")
    labels = {
        "NOT_ELIGIBLE": "Not eligible",
        "NEEDS_REVIEW": "Needs review",
        "ELIGIBLE_WITH_REVIEW": "Eligible with review",
        "COMPLIANT": "No failed bid-stage requirements detected",
    }
    return labels.get(status, status.replace("_", " ").title())


def _customer_text(value: object, *, limit: int = 620) -> str:
    text = _truncate(value, limit=limit)
    text = re.sub(
        r"\s*\|\s*\[[^\]]*(?:UUID|token)[^\]]*\]\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\bAI extraction\b", "requirement extraction", text, flags=re.IGNORECASE)
    text = re.sub(r"\bAI\b", "system", text)
    return text.strip()


def _format_confidence(value: object) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number <= 1:
        return f"{number * 100:.0f}%"
    return f"{number:.0f}%"


def _safe_filename_part(value: object) -> str:
    text = _text(value, "tender")
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text.strip("._-")[:80] or "tender"


def compliance_report_filename(*, external_id: object, generated_at: datetime) -> str:
    tender_part = _safe_filename_part(external_id)
    stamp = generated_at.strftime("%Y%m%d")
    return f"Plasma_Compliance_{tender_part}_{stamp}.pdf"


def _make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle(
            "PlasmaBrand",
            parent=base["Normal"],
            fontName="DejaVu-Bold",
            fontSize=9,
            leading=12,
            textColor=ACCENT,
            spaceAfter=3,
        ),
        "title": ParagraphStyle(
            "PlasmaReportTitle",
            parent=base["Title"],
            fontName="DejaVu-Bold",
            fontSize=20,
            leading=25,
            textColor=TEXT,
            spaceAfter=8,
        ),
        "subtitle": ParagraphStyle(
            "PlasmaSubtitle",
            parent=base["Normal"],
            fontName="DejaVu",
            fontSize=9,
            leading=13,
            textColor=MUTED,
            spaceAfter=12,
        ),
        "section": ParagraphStyle(
            "PlasmaSection",
            parent=base["Heading2"],
            fontName="DejaVu-Bold",
            fontSize=12,
            leading=16,
            textColor=TEXT,
            spaceBefore=12,
            spaceAfter=7,
        ),
        "body": ParagraphStyle(
            "PlasmaBody",
            parent=base["Normal"],
            fontName="DejaVu",
            fontSize=9,
            leading=13,
            textColor=TEXT,
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "PlasmaSmall",
            parent=base["Normal"],
            fontName="DejaVu",
            fontSize=7.5,
            leading=10.5,
            textColor=MUTED,
            spaceAfter=3,
        ),
        "quote": ParagraphStyle(
            "PlasmaQuote",
            parent=base["Normal"],
            fontName="DejaVu",
            fontSize=8,
            leading=11.5,
            textColor=colors.HexColor("#374151"),
            leftIndent=8,
            rightIndent=4,
            spaceBefore=2,
            spaceAfter=5,
        ),
        "center": ParagraphStyle(
            "PlasmaCenter",
            parent=base["Normal"],
            fontName="DejaVu-Bold",
            fontSize=12,
            leading=15,
            textColor=TEXT,
            alignment=TA_CENTER,
        ),
    }


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("DejaVu", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(2 * cm, 1 * cm, "Plasma AI Compliance Analysis Report")
    canvas.drawRightString(19 * cm, 1 * cm, f"Page {doc.page}")
    canvas.restoreState()


def _meta_table(rows: list[tuple[str, object]], styles: dict[str, ParagraphStyle]) -> Table:
    data = [
        [
            Paragraph(f"<b>{_xml(label)}</b>", styles["small"]),
            Paragraph(_xml(value, "-"), styles["small"]),
        ]
        for label, value in rows
    ]
    table = Table(data, colWidths=[4.0 * cm, 12.8 * cm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _counts_table(
    hybrid: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> Table:
    values = [
        ("Satisfied", hybrid.get("satisfied_count", 0)),
        ("Failed", hybrid.get("failed_count", 0)),
        ("Manual review", hybrid.get("manual_review_count", 0)),
        ("Recorded", hybrid.get("recorded_obligations_count", 0)),
        ("Skipped optional", hybrid.get("skipped_optional_count", 0)),
    ]
    data = [
        [Paragraph(f"<b>{_xml(label)}</b>", styles["small"]) for label, _ in values],
        [Paragraph(_xml(value, "0"), styles["center"]) for _, value in values],
    ]
    table = Table(data, colWidths=[3.36 * cm] * 5, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2FF")),
                ("BACKGROUND", (0, 1), (-1, 1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _section_title(
    elements: list[Any],
    title: str,
    styles: dict[str, ParagraphStyle],
) -> None:
    elements.append(Paragraph(_xml(title), styles["section"]))
    elements.append(HRFlowable(width="100%", thickness=0.7, color=LINE, spaceAfter=6))


def _detail_value(detail: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _text(detail.get(key))
        if value:
            return value
    return ""


def _append_requirement(
    elements: list[Any],
    detail: dict[str, Any],
    styles: dict[str, ParagraphStyle],
    *,
    tone: str,
    include_match: bool = False,
    recorded: bool = False,
) -> None:
    bg = {"bad": BAD_SOFT, "good": GOOD_SOFT, "warn": WARN_SOFT}.get(tone, SOFT)
    title = _detail_value(detail, "headline", "raw_text_snippet", "exact_quote")
    source = _source_filename(detail.get("source_filename"))
    source_page = _text(detail.get("source_page"), "1")
    reason = _customer_text(_detail_value(detail, "reason"), limit=520)
    quote = _truncate(_detail_value(detail, "exact_quote", "raw_text_snippet"), limit=620)

    meta_parts = [
        f"Source evidence: {source}, page {source_page}",
        f"Detected requirement: {_text(detail.get('category') or detail.get('requirement_type'), 'requirement')}",
    ]
    if recorded:
        meta_parts.append("Recorded as a non-bid obligation")

    paragraphs: list[Paragraph] = [
        Paragraph(f"<b>{_xml(title, 'Detected requirement')}</b>", styles["body"]),
        Paragraph(_xml(" | ".join(meta_parts)), styles["small"]),
    ]

    if reason:
        paragraphs.append(Paragraph(f"<b>Assessment:</b> {_xml(reason)}", styles["body"]))

    validation_reason = _customer_text(
        _detail_value(detail, "validation_reason", "eligibility_reason"),
        limit=420,
    )
    if validation_reason:
        paragraphs.append(
            Paragraph(f"<b>Review note:</b> {_xml(validation_reason)}", styles["small"])
        )

    vault_missing_reason = _customer_text(_detail_value(detail, "vault_missing_reason"), limit=420)
    if vault_missing_reason:
        paragraphs.append(
            Paragraph(f"<b>Company Vault gap:</b> {_xml(vault_missing_reason)}", styles["body"])
        )

    if include_match:
        match_parts = []
        matched_credential = _customer_text(_detail_value(detail, "matched_credential"), limit=180)
        if matched_credential:
            match_parts.append(f"Credential: {matched_credential}")
        vault_type = _detail_value(detail, "vault_match_type")
        if vault_type:
            match_parts.append(f"Type: {vault_type}")
        vault_source = _detail_value(detail, "vault_match_source")
        if vault_source:
            match_parts.append(f"Source: {vault_source.replace('_', ' ')}")
        confidence = _format_confidence(detail.get("vault_match_confidence"))
        if confidence:
            match_parts.append(f"Confidence: {confidence}")
        if match_parts:
            paragraphs.append(
                Paragraph(f"<b>Company Vault match:</b> {_xml('; '.join(match_parts))}", styles["body"])
            )

    if quote:
        paragraphs.append(Paragraph(f"<b>Quote:</b> &quot;{_xml(quote)}&quot;", styles["quote"]))

    table = Table([[paragraphs]], colWidths=[16.8 * cm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("BOX", (0, 0), (-1, -1), 0.35, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    elements.append(table)
    elements.append(Spacer(1, 6))


def _append_requirement_section(
    elements: list[Any],
    title: str,
    items: list[dict[str, Any]],
    styles: dict[str, ParagraphStyle],
    *,
    empty_message: str,
    tone: str,
    include_match: bool = False,
    recorded: bool = False,
) -> None:
    _section_title(elements, title, styles)
    if not items:
        elements.append(Paragraph(_xml(empty_message), styles["body"]))
        return
    for detail in items:
        _append_requirement(
            elements,
            detail,
            styles,
            tone=tone,
            include_match=include_match,
            recorded=recorded,
        )


def build_compliance_report_pdf(
    *,
    tender_title: object,
    tender_external_id: object,
    company_name: object,
    generated_at: datetime,
    analysis_id: object,
    content_hash: object,
    override_seal: object,
    hybrid_compliance: dict[str, Any],
    evidence_validation: dict[str, Any] | None,
    analysis_warnings: list[str],
    analysis_version: object | None = None,
    snapshot_completeness: object | None = None,
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
        leftMargin=2.0 * cm,
        rightMargin=2.0 * cm,
    )
    styles = _make_styles()
    elements: list[Any] = []

    status = _display_status(hybrid_compliance.get("verdict_status"))
    status_message = _customer_text(
        hybrid_compliance.get("status_message"),
        limit=620,
    ) or "Manual review required."
    warnings = [
        _customer_text(warning, limit=260)
        for warning in analysis_warnings
        if _text(warning)
    ]
    validation_summary = (evidence_validation or {}).get("summary") or {}

    elements.append(Paragraph("Plasma AI", styles["brand"]))
    elements.append(Paragraph("Compliance Analysis Report", styles["title"]))
    elements.append(Paragraph(_xml(tender_title, "Untitled tender"), styles["subtitle"]))
    elements.append(
        _meta_table(
            [
                ("Tender external ID", _text(tender_external_id, "-")),
                ("Company", _text(company_name, "-")),
                ("Generated", generated_at.strftime("%Y-%m-%d %H:%M UTC")),
                ("Analysis ID", _text(analysis_id, "-")),
                ("Analysis version", _text(analysis_version, "-")),
                (
                    "Snapshot completeness",
                    _text(snapshot_completeness, "Unknown"),
                ),
            ],
            styles,
        )
    )
    elements.append(Spacer(1, 12))

    _section_title(elements, "Executive Summary", styles)
    elements.append(Paragraph(f"<b>Verdict:</b> {_xml(status)}", styles["body"]))
    elements.append(Paragraph(_xml(status_message), styles["body"]))
    elements.append(Spacer(1, 5))
    elements.append(_counts_table(hybrid_compliance, styles))

    if validation_summary:
        elements.append(Spacer(1, 6))
        validation_text = (
            "Evidence validation summary: "
            f"{validation_summary.get('accepted', 0)} accepted, "
            f"{validation_summary.get('needs_review', 0)} requiring review, "
            f"{validation_summary.get('bid_affecting', 0)} bid-affecting detected requirements."
        )
        elements.append(Paragraph(_xml(validation_text), styles["small"]))

    if warnings:
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(f"<b>Warnings:</b> {len(warnings)}", styles["body"]))
        for warning in warnings[:6]:
            elements.append(Paragraph(f"- {_xml(warning)}", styles["small"]))
        if len(warnings) > 6:
            elements.append(
                Paragraph(f"- {_xml(len(warnings) - 6)} additional warning(s) omitted.", styles["small"])
            )

    _append_requirement_section(
        elements,
        "Failed / Missing Requirements",
        list(hybrid_compliance.get("failed_dealbreakers") or []),
        styles,
        empty_message="No failed bid-stage requirements were detected in this analysis.",
        tone="bad",
    )
    _append_requirement_section(
        elements,
        "Satisfied Requirements",
        list(hybrid_compliance.get("satisfied_requirements") or []),
        styles,
        empty_message="No satisfied requirements were recorded in this analysis.",
        tone="good",
        include_match=True,
    )
    _append_requirement_section(
        elements,
        "Manual Review Required",
        list(hybrid_compliance.get("manual_reviews_required") or []),
        styles,
        empty_message="No manual review items were recorded in this analysis.",
        tone="warn",
    )
    _append_requirement_section(
        elements,
        "Recorded Obligations",
        list(hybrid_compliance.get("recorded_obligations") or []),
        styles,
        empty_message="No non-bid obligations were recorded in this analysis.",
        tone="warn",
        recorded=True,
    )

    _section_title(elements, "Audit Trail", styles)
    elements.append(
        _meta_table(
            [
                ("Analysis ID", _text(analysis_id, "-")),
                ("Analysis version", _text(analysis_version, "-")),
                (
                    "Snapshot completeness",
                    _text(snapshot_completeness, "Unknown"),
                ),
                ("Content hash", _text(content_hash, "-")),
                ("Override seal", _text(override_seal, "No override seal recorded")),
                ("Generated timestamp", generated_at.isoformat()),
                ("Analysis warnings count", len(warnings)),
            ],
            styles,
        )
    )
    elements.append(Spacer(1, 8))
    elements.append(
        Paragraph(
            "This report summarizes detected tender requirements and source evidence. "
            "It is intended to support business review and does not replace legal or procurement advice.",
            styles["small"],
        )
    )

    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer.getvalue()
