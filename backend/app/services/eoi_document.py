"""D2-05 EOI package rendering: one manifest, two formats (DOCX and PDF), en and ru.

Everything printed comes from the manifest. Labels are the only template text;
every fact sits in the manifest with the id of the record or notice quote it came from.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import io
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn
from docx.shared import Mm, Pt
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"
PDF_FONT = "PlasmaEoiRoboto"
PDF_FONT_BOLD = "PlasmaEoiRoboto-Bold"
DOCX_FONT = "Arial"  # ships with Word and LibreOffice everywhere, with full Cyrillic coverage

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "letter_heading": "Expression of Interest",
        "subject": "Subject: Expression of Interest — {title} (Ref. {reference})",
        "to": "To:",
        "dear_named": "Dear {name},",
        "dear": "Dear Sir or Madam,",
        "interest": "{firm} hereby expresses its interest in providing the consulting services for “{title}”, reference {reference}.",
        "association": "We submit this expression of interest in association with {partners}.",
        "as_jv": "{firm} as joint-venture member",
        "as_sub": "{firm} as sub-consultant",
        "attached": "The following pages describe our firm and our relevant experience, set out against the shortlisting criteria of the notice.",
        "contact": "Contact for this expression of interest",
        "email": "E-mail", "phone": "Telephone", "address": "Address",
        "closing": "Yours faithfully,",
        "signature": "Signature: ______________________________",
        "date": "Date: ______________________________",
        "profile_heading": "Firm profile",
        "lead_firm": "Lead firm", "partner_firm": "Partner firm",
        "name": "Name", "legal_name": "Legal name", "country": "Country", "services": "Services",
        "sectors": "Sectors", "regions": "Regions", "website": "Website", "role_in_eoi": "Role in this expression of interest",
        "experience_heading": "Relevant experience",
        "col_no": "No.", "col_assignment": "Assignment", "col_country": "Country", "col_client": "Client",
        "col_firm": "Firm & role", "col_period": "Period", "col_value": "Contract value",
        "col_services": "Description of services", "col_relevance": "Relevance to this assignment",
        "lead": "Lead", "JV_MEMBER": "JV member", "SUBCONSULTANT": "Sub-consultant",
        "recorded_role": "role on the assignment: {role}",
        "not_recorded": "Not recorded", "ongoing": "ongoing", "from": "from {start}",
        "basis_FIRM_SHARE": "firm share", "basis_CONSORTIUM_TOTAL": "consortium total", "basis_CONTRACT_TOTAL": "contract total",
        "draft_note": "Draft note — verify: {text}",
        "criteria_heading": "Shortlisting criteria cross-reference",
        "col_criterion": "Criterion (notice)", "col_addressed": "Experience rows",
        "notice_page": "Notice, page {page}", "notice_paragraph": "Notice, paragraph {paragraph}", "notice": "Notice",
        "addressed_by": "Addressed by references #{rows}",
        "not_addressed": "No selected reference addresses this criterion",
        "notes_heading": "Submission notes (follow when submitting)",
        "note_INFORMATIONAL": "Information", "note_SUBMISSION_INSTRUCTION": "Submission instruction",
        "no_notes": "The analysis recorded no submission instructions.",
        "documents_heading": "Supporting documents checklist",
        "doc_reference": "Completion certificate / client reference letter — reference #{row}: {name}",
        "doc_registration": "Company registration: {name}",
        "doc_registration_missing": "Company registration certificate",
        "on_record": "On record", "to_attach": "To attach",
        "disclosure": "Draft prepared with Plasma from the organization's own records and the official notice. The firm is responsible for the accuracy of all statements. No price information included.",
        "role_LEAD": "lead", "role_JV_MEMBER": "JV member", "role_CONSORTIUM_MEMBER": "consortium member",
        "role_SUBCONSULTANT": "sub-consultant", "role_SUBCONTRACTOR": "subcontractor", "role_OTHER": "other",
        "role_UNKNOWN": "not recorded",
    },
    "ru": {
        "letter_heading": "Выражение заинтересованности",
        "subject": "Тема: выражение заинтересованности — {title} (номер {reference})",
        "to": "Кому:",
        "dear_named": "Уважаемый(ая) {name}!",
        "dear": "Уважаемые господа!",
        "interest": "{firm} настоящим выражает заинтересованность в оказании консультационных услуг по заданию «{title}», номер {reference}.",
        "association": "Мы подаём данное выражение заинтересованности совместно с {partners}.",
        "as_jv": "{firm} в качестве участника совместного предприятия",
        "as_sub": "{firm} в качестве субконсультанта",
        "attached": "На следующих страницах описаны наша фирма и наш релевантный опыт в сопоставлении с критериями отбора из объявления.",
        "contact": "Контакт по данному выражению заинтересованности",
        "email": "Эл. почта", "phone": "Телефон", "address": "Адрес",
        "closing": "С уважением,",
        "signature": "Подпись: ______________________________",
        "date": "Дата: ______________________________",
        "profile_heading": "Профиль фирмы",
        "lead_firm": "Ведущая фирма", "partner_firm": "Фирма-партнёр",
        "name": "Название", "legal_name": "Юридическое название", "country": "Страна", "services": "Услуги",
        "sectors": "Отрасли", "regions": "Регионы", "website": "Сайт", "role_in_eoi": "Роль в данном выражении заинтересованности",
        "experience_heading": "Релевантный опыт",
        "col_no": "№", "col_assignment": "Задание", "col_country": "Страна", "col_client": "Заказчик",
        "col_firm": "Фирма и роль", "col_period": "Период", "col_value": "Стоимость контракта",
        "col_services": "Описание услуг", "col_relevance": "Связь с данным заданием",
        "lead": "Лидер", "JV_MEMBER": "Участник СП", "SUBCONSULTANT": "Субконсультант",
        "recorded_role": "роль в задании: {role}",
        "not_recorded": "Не указано", "ongoing": "выполняется", "from": "с {start}",
        "basis_FIRM_SHARE": "доля фирмы", "basis_CONSORTIUM_TOTAL": "сумма консорциума", "basis_CONTRACT_TOTAL": "сумма контракта",
        "draft_note": "Черновая заметка — проверьте: {text}",
        "criteria_heading": "Сопоставление с критериями отбора",
        "col_criterion": "Критерий (объявление)", "col_addressed": "Строки опыта",
        "notice_page": "Объявление, страница {page}", "notice_paragraph": "Объявление, абзац {paragraph}", "notice": "Объявление",
        "addressed_by": "Относятся референции №{rows}",
        "not_addressed": "Ни одна выбранная референция не относится к этому критерию",
        "notes_heading": "Указания по подаче (выполните при подаче)",
        "note_INFORMATIONAL": "Информация", "note_SUBMISSION_INSTRUCTION": "Указание по подаче",
        "no_notes": "Анализ не выявил указаний по подаче.",
        "documents_heading": "Перечень подтверждающих документов",
        "doc_reference": "Акт выполненных работ / рекомендательное письмо заказчика — референция №{row}: {name}",
        "doc_registration": "Регистрация компании: {name}",
        "doc_registration_missing": "Свидетельство о регистрации компании",
        "on_record": "Есть в записях", "to_attach": "Приложить",
        "disclosure": "Черновик подготовлен в Plasma на основе собственных записей организации и официального объявления. Фирма несёт ответственность за точность всех утверждений. Ценовая информация не включена.",
        "role_LEAD": "лидер", "role_JV_MEMBER": "участник СП", "role_CONSORTIUM_MEMBER": "участник консорциума",
        "role_SUBCONSULTANT": "субконсультант", "role_SUBCONTRACTOR": "субподрядчик", "role_OTHER": "другое",
        "role_UNKNOWN": "не указана",
    },
}


def labels(language: str) -> dict[str, str]:
    return LABELS.get(language, LABELS["en"])


def _month(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m")
    return str(value)[:7]


def period_text(row: dict[str, Any], t: dict[str, str]) -> str:
    start, end = _month(row.get("start_date")), _month(row.get("completion_date"))
    if row.get("completion_state") == "ONGOING" and not end:
        return f"{start} – {t['ongoing']}" if start else t["ongoing"]
    if start and end:
        return f"{start} – {end}"
    if end:
        return end
    if start:
        return t["from"].format(start=start)
    return t["not_recorded"]


def _amount(value: Any) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if number == number.to_integral():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def value_text(row: dict[str, Any], t: dict[str, str]) -> str:
    if row.get("contract_value") in (None, "") or not row.get("contract_currency"):
        return t["not_recorded"]
    basis = t.get(f"basis_{row.get('value_basis')}")
    amount = f"{_amount(row['contract_value'])} {row['contract_currency']}"
    return f"{amount} ({basis})" if basis else amount


def firm_role_text(row: dict[str, Any], t: dict[str, str]) -> str:
    eoi_role = t["lead"] if row["eoi_role"] == "LEAD" else t[row["eoi_role"]]
    text = f"{row['firm_name']} — {eoi_role}"
    recorded = row.get("recorded_role")
    if recorded and recorded != "UNKNOWN" and not (row["eoi_role"] == "LEAD" and recorded == "LEAD"):
        text += "; " + t["recorded_role"].format(role=t.get(f"role_{recorded}", recorded))
    return text


def locator_text(locator: dict[str, Any], t: dict[str, str]) -> str:
    if locator.get("page_number"):
        return t["notice_page"].format(page=locator["page_number"])
    if locator.get("paragraph_number"):
        return t["notice_paragraph"].format(paragraph=locator["paragraph_number"])
    return t["notice"]


def addressed_text(rows: list[int], t: dict[str, str]) -> str:
    return t["addressed_by"].format(rows=", #".join(str(row) for row in rows)) if rows else t["not_addressed"]


def _profile_lines(profile: list[dict[str, Any]], t: dict[str, str]) -> list[tuple[str, str]]:
    lines = []
    for item in profile:
        value = item["value"]
        if isinstance(value, list):
            value = "; ".join(str(entry) for entry in value)
        if value:
            lines.append((t.get(item["field"], item["field"]), str(value)))
    return lines


def letter_paragraphs(manifest: dict[str, Any]) -> dict[str, Any]:
    """The cover letter as text blocks, shared by both renderers."""
    t = labels(manifest["language"])
    notice, letter, lead = manifest["notice"], manifest["letter"], manifest["lead"]
    title = notice["assignment_title"]["value"]
    reference = notice["reference_no"]["value"]
    associations = [
        (t["as_jv"] if partner["role"] == "JV_MEMBER" else t["as_sub"]).format(firm=partner["display_name"])
        for partner in manifest["partners"]
    ]
    contact = [(t["email"], letter["contact_email"])]
    if letter.get("contact_phone"):
        contact.append((t["phone"], letter["contact_phone"]))
    if letter.get("contact_address"):
        contact.append((t["address"], letter["contact_address"]))
    return {
        "to": [value for value in (letter.get("addressee_name"), letter["addressee_organization"]) if value],
        "subject": t["subject"].format(title=title, reference=reference),
        "salutation": t["dear_named"].format(name=letter["addressee_name"]) if letter.get("addressee_name") else t["dear"],
        "body": [
            t["interest"].format(firm=lead["display_name"], title=title, reference=reference),
            *([t["association"].format(partners="; ".join(associations))] if associations else []),
            t["attached"],
        ],
        "contact": contact,
        "signature": [t["closing"], letter["signatory_name"], letter["signatory_title"], lead["display_name"],
                      t["signature"], t["date"]],
    }


def document_text(manifest: dict[str, Any]) -> list[str]:
    """All printed text in reading order (used by tests and for a plain-text audit)."""
    t = labels(manifest["language"])
    letter = letter_paragraphs(manifest)
    out = [t["letter_heading"], *letter["to"], letter["subject"], letter["salutation"], *letter["body"], t["contact"]]
    out += [f"{label}: {value}" for label, value in letter["contact"]]
    out += letter["signature"]
    out.append(t["profile_heading"])
    for firm in [manifest["lead"], *manifest["partners"]]:
        out += [f"{label}: {value}" for label, value in _profile_lines(firm["profile"], t)]
    out.append(t["experience_heading"])
    for row in manifest["experience"]:
        out += [str(row["no"]), row["project_name"], row.get("country") or t["not_recorded"],
                row.get("client_name") or t["not_recorded"], firm_role_text(row, t), period_text(row, t),
                value_text(row, t), row.get("relevant_scope") or t["not_recorded"]]
        if row.get("relevance_note"):
            out.append(t["draft_note"].format(text=row["relevance_note"]["text"]))
    out.append(t["criteria_heading"])
    for criterion in manifest["criteria"]:
        out += [criterion["statement"], criterion["original_quote"], locator_text(criterion["locator"], t),
                addressed_text(criterion["addressed_by"], t)]
    out.append(t["notes_heading"])
    out += [f"{t['note_' + note['note_kind']]}: {note['statement']}" for note in manifest["notes"]] or [t["no_notes"]]
    out.append(t["documents_heading"])
    out += [document_line(item, t) for item in manifest["supporting_documents"]]
    out.append(t["disclosure"])
    return out


def document_line(item: dict[str, Any], t: dict[str, str]) -> str:
    status = t["on_record"] if item["status"] == "ON_RECORD" else t["to_attach"]
    if item["kind"] == "REFERENCE_PROOF":
        label = t["doc_reference"].format(row=item["row"], name=item["name"])
    elif item.get("name"):
        label = t["doc_registration"].format(name=item["name"])
    else:
        label = t["doc_registration_missing"]
    return f"[ ] {label} — {status}"


# ---- DOCX ---------------------------------------------------------------------------------------------

def _normalize_docx(raw: bytes) -> bytes:
    source = ZipFile(io.BytesIO(raw), "r")
    target = io.BytesIO()
    with source, ZipFile(target, "w", ZIP_DEFLATED, compresslevel=9) as output:
        for name in sorted(source.namelist()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            output.writestr(info, source.read(name))
    return target.getvalue()


def _docx_font(document: Any) -> None:
    for style_name in ("Normal", "Title", "Heading 1", "Heading 2", "Table Grid"):
        try:
            style = document.styles[style_name]
        except KeyError:
            continue
        style.font.name = DOCX_FONT
        fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
        for attribute in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            fonts.set(qn(attribute), DOCX_FONT)
    document.styles["Normal"].font.size = Pt(10)


def docx_bytes(manifest: dict[str, Any]) -> bytes:
    t = labels(manifest["language"])
    letter = letter_paragraphs(manifest)
    document = Document()
    _docx_font(document)
    fixed = datetime(2000, 1, 1, tzinfo=timezone.utc)
    document.core_properties.title = t["letter_heading"]
    document.core_properties.author = manifest["lead"]["display_name"]
    document.core_properties.created = fixed
    document.core_properties.modified = fixed
    document.core_properties.language = manifest["language"]
    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)

    document.add_heading(t["letter_heading"], level=1)
    document.add_paragraph(t["to"] + " " + ", ".join(letter["to"]))
    document.add_paragraph().add_run(letter["subject"]).bold = True
    document.add_paragraph(letter["salutation"])
    for text in letter["body"]:
        document.add_paragraph(text)
    document.add_paragraph().add_run(t["contact"]).bold = True
    for label, value in letter["contact"]:
        document.add_paragraph(f"{label}: {value}")
    for text in letter["signature"]:
        document.add_paragraph(text)

    landscape_section = document.add_section()
    landscape_section.orientation = WD_ORIENT.LANDSCAPE
    landscape_section.page_width, landscape_section.page_height = Mm(297), Mm(210)
    document.add_heading(t["profile_heading"], level=1)
    for firm in [manifest["lead"], *manifest["partners"]]:
        heading = t["lead_firm"] if firm is manifest["lead"] else t["partner_firm"]
        document.add_heading(f"{heading}: {firm['display_name']}", level=2)
        for label, value in _profile_lines(firm["profile"], t):
            document.add_paragraph(f"{label}: {value}")

    document.add_heading(t["experience_heading"], level=1)
    columns = ["col_no", "col_assignment", "col_country", "col_client", "col_firm", "col_period", "col_value", "col_services"]
    table = document.add_table(rows=1, cols=len(columns))
    table.style = "Table Grid"
    for index, key in enumerate(columns):
        table.rows[0].cells[index].text = t[key]
    for row in manifest["experience"]:
        cells = table.add_row().cells
        values = [str(row["no"]), row["project_name"], row.get("country") or t["not_recorded"],
                  row.get("client_name") or t["not_recorded"], firm_role_text(row, t), period_text(row, t),
                  value_text(row, t), row.get("relevant_scope") or t["not_recorded"]]
        for index, value in enumerate(values):
            cells[index].text = value
        if row.get("relevance_note"):
            cells[7].add_paragraph(f"{t['col_relevance']}: " + t["draft_note"].format(text=row["relevance_note"]["text"]))

    document.add_heading(t["criteria_heading"], level=1)
    table = document.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    table.rows[0].cells[0].text = t["col_criterion"]
    table.rows[0].cells[1].text = t["col_addressed"]
    for criterion in manifest["criteria"]:
        cells = table.add_row().cells
        cells[0].text = criterion["statement"]
        quote = cells[0].add_paragraph(f"“{criterion['original_quote']}” — {locator_text(criterion['locator'], t)}")
        quote.runs[0].italic = True
        cells[1].text = addressed_text(criterion["addressed_by"], t)

    document.add_heading(t["notes_heading"], level=1)
    if manifest["notes"]:
        for note in manifest["notes"]:
            document.add_paragraph(f"[ ] {t['note_' + note['note_kind']]}: {note['statement']}")
    else:
        document.add_paragraph(t["no_notes"])

    document.add_heading(t["documents_heading"], level=1)
    for item in manifest["supporting_documents"]:
        document.add_paragraph(document_line(item, t))
    document.add_paragraph()
    document.add_paragraph().add_run(t["disclosure"]).italic = True
    for current in document.sections:
        current.footer.paragraphs[0].text = t["disclosure"]
    stream = io.BytesIO()
    document.save(stream)
    return _normalize_docx(stream.getvalue())


# ---- PDF ----------------------------------------------------------------------------------------------

def _register_fonts() -> None:
    if PDF_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(PDF_FONT, str(FONTS_DIR / "Roboto-Regular.ttf")))
        pdfmetrics.registerFont(TTFont(PDF_FONT_BOLD, str(FONTS_DIR / "Roboto-Bold.ttf")))


class _InvariantCanvas(Canvas):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["invariant"] = 1
        super().__init__(*args, **kwargs)


def pdf_bytes(manifest: dict[str, Any]) -> bytes:
    _register_fonts()
    t = labels(manifest["language"])
    letter = letter_paragraphs(manifest)
    base = getSampleStyleSheet()
    body = ParagraphStyle("EoiBody", parent=base["BodyText"], fontName=PDF_FONT, fontSize=9.5, leading=13, alignment=TA_LEFT)
    small = ParagraphStyle("EoiSmall", parent=body, fontSize=7.5, leading=9.5)
    heading = ParagraphStyle("EoiHeading", parent=base["Heading2"], fontName=PDF_FONT_BOLD, fontSize=13, leading=16, spaceAfter=6)
    subheading = ParagraphStyle("EoiSubheading", parent=heading, fontSize=11, leading=14)
    bold = ParagraphStyle("EoiBold", parent=body, fontName=PDF_FONT_BOLD)

    def para(text: str, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    stream = io.BytesIO()

    def footer(canvas: Canvas, document: Any) -> None:
        canvas.saveState()
        canvas.setFont(PDF_FONT, 6.5)
        width = canvas._pagesize[0] - 2 * document.leftMargin
        for index, line in enumerate(simpleSplit(t["disclosure"], PDF_FONT, 6.5, width)[:3]):
            canvas.drawString(document.leftMargin, (10 - 3 * index) * mm, line)
        canvas.restoreState()

    # The cover letter is a portrait page; the profile and tables that follow are landscape.
    document = BaseDocTemplate(
        stream, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=20 * mm,
        bottomMargin=18 * mm, title=t["letter_heading"], author=manifest["lead"]["display_name"],
    )
    portrait_size, landscape_size = A4, landscape(A4)
    document.addPageTemplates([
        PageTemplate(id="portrait", pagesize=portrait_size, onPage=footer, frames=[Frame(
            20 * mm, 18 * mm, portrait_size[0] - 40 * mm, portrait_size[1] - 38 * mm, id="portrait-frame")]),
        PageTemplate(id="landscape", pagesize=landscape_size, onPage=footer, frames=[Frame(
            15 * mm, 16 * mm, landscape_size[0] - 30 * mm, landscape_size[1] - 31 * mm, id="landscape-frame")]),
    ])
    story: list[Any] = [para(t["letter_heading"], heading), para(t["to"] + " " + ", ".join(letter["to"])),
                        Spacer(1, 4), para(letter["subject"], bold), Spacer(1, 4), para(letter["salutation"])]
    story += [para(text) for text in letter["body"]]
    story += [Spacer(1, 6), para(t["contact"], bold)]
    story += [para(f"{label}: {value}") for label, value in letter["contact"]]
    story += [Spacer(1, 8)] + [para(text) for text in letter["signature"]]
    story += [NextPageTemplate("landscape"), PageBreak()]

    story.append(para(t["profile_heading"], heading))
    for firm in [manifest["lead"], *manifest["partners"]]:
        label = t["lead_firm"] if firm is manifest["lead"] else t["partner_firm"]
        story.append(para(f"{label}: {firm['display_name']}", subheading))
        story += [para(f"{name}: {value}") for name, value in _profile_lines(firm["profile"], t)]
    story += [Spacer(1, 8), para(t["experience_heading"], heading)]

    header = [para(t[key], bold) for key in ("col_no", "col_assignment", "col_country", "col_client", "col_firm",
                                             "col_period", "col_value", "col_services")]
    rows = [header]
    for row in manifest["experience"]:
        services = row.get("relevant_scope") or t["not_recorded"]
        cell = [para(services, small)]
        if row.get("relevance_note"):
            cell.append(para(t["draft_note"].format(text=row["relevance_note"]["text"]), small))
        rows.append([para(str(row["no"]), small), para(row["project_name"], small),
                     para(row.get("country") or t["not_recorded"], small), para(row.get("client_name") or t["not_recorded"], small),
                     para(firm_role_text(row, t), small), para(period_text(row, t), small),
                     para(value_text(row, t), small), cell])
    widths = [10 * mm, 40 * mm, 22 * mm, 32 * mm, 38 * mm, 24 * mm, 32 * mm, 69 * mm]
    story.append(_table(rows, widths))

    story += [Spacer(1, 8), para(t["criteria_heading"], heading)]
    rows = [[para(t["col_criterion"], bold), para(t["col_addressed"], bold)]]
    for criterion in manifest["criteria"]:
        rows.append([
            [para(criterion["statement"], small),
             para(f"“{criterion['original_quote']}” — {locator_text(criterion['locator'], t)}", small)],
            para(addressed_text(criterion["addressed_by"], t), small),
        ])
    story.append(_table(rows, [190 * mm, 77 * mm]))

    story += [Spacer(1, 8), para(t["notes_heading"], heading)]
    story += [para(f"[ ] {t['note_' + note['note_kind']]}: {note['statement']}") for note in manifest["notes"]] or [para(t["no_notes"])]
    story += [Spacer(1, 8), para(t["documents_heading"], heading)]
    story += [para(document_line(item, t)) for item in manifest["supporting_documents"]]
    story += [Spacer(1, 10), para(t["disclosure"], small)]
    document.build(story, canvasmaker=_InvariantCanvas)
    return stream.getvalue()


def _table(rows: list[list[Any]], widths: list[float]) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF7")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#A9B4C6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table
