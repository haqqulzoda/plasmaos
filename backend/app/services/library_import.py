"""P1 done-for-you onboarding: import project references and experts from a CSV or XLSX template.

Template (``build_template_xlsx``): sheets Instructions, References, Experts and Expert
assignments; CSV templates are one per sheet. ``parse_upload`` reads either format (XLSX
with the standard library only: no macros, formulas are read as their cached values, zip
and XML sizes are capped), ``preview`` validates every row against the same rules as the
library forms and marks duplicates (same firm and project name, same expert name, in the
library or earlier in the file), and ``commit`` writes the valid, new rows in ONE transaction,
tagged with the file's SHA-256 and row number. The commit re-reads the uploaded file and
refuses unless it is byte-identical to the previewed one.

Imported records are UNVERIFIED metadata (the same evidence state as a hand-typed record);
experts are organization-private. Existing CV upload stays the way to attach the CV itself.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import re
from typing import Any, Iterable
from uuid import UUID
from xml.etree import ElementTree
from xml.sax.saxutils import escape
import zipfile

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_retrieval import CVVersion, Expert, Firm, ProjectReference
from app.schemas.candidate_retrieval import (
    CVVersionCreateRequest,
    ExpertCreateRequest,
    ProjectReferenceCreateRequest,
    SelfFirmUpsertRequest,
)

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_ROWS_PER_SHEET = 1000
MAX_XML_PART_BYTES = 20 * 1024 * 1024
MAX_ZIP_ENTRIES = 200
LIST_SEPARATOR = re.compile(r"\s*[;\n|]\s*")

KINDS = ("references", "experts", "assignments")
SHEET_TITLES = {"references": "References", "experts": "Experts", "assignments": "Expert assignments"}

# (header, required, help). Headers are matched case-insensitively, ignoring "*" and spaces.
COLUMNS: dict[str, list[tuple[str, bool, str]]] = {
    "references": [
        ("firm", False, "Leave empty for your own firm. Otherwise the partner firm's name (created as a private partner firm if new)."),
        ("project_name", True, "Assignment title as in the contract."),
        ("client_name", False, "Client or contracting agency."),
        ("country", False, "Country of the assignment."),
        ("service", False, "Service, e.g. Feasibility study, Supervision, Audit."),
        ("sector", False, "Sector, e.g. Water, Energy, Health."),
        ("role", True, "Lead, JV member, Consortium member, Subconsultant, Subcontractor or Other."),
        ("contract_value", False, "Number, no currency sign (e.g. 1250000)."),
        ("currency", False, "ISO code: USD, EUR, UZS..."),
        ("value_basis", False, "Firm share, Consortium total or Contract total: required with contract_value (otherwise Unknown)."),
        ("share_percent", False, "Your share of the contract in percent (0-100)."),
        ("start_date", False, "YYYY-MM-DD or YYYY-MM."),
        ("completion_date", False, "YYYY-MM-DD or YYYY-MM."),
        ("status", False, "Completed, Ongoing, Not completed or Unknown (default: Completed when a completion date is in the past)."),
        ("scope", False, "Relevant scope: what the firm did (up to 10,000 characters)."),
    ],
    "experts": [
        ("full_name", True, "As on the CV."),
        ("position", False, "Proposed position or title, e.g. Team Leader / Water Engineer."),
        ("years_experience", False, "Whole years of professional experience."),
        ("education", False, "Degrees, separated by ; (e.g. MSc Hydraulic Engineering; BSc Civil Engineering)."),
        ("qualifications", False, "Key qualifications, separated by ;."),
        ("specializations", False, "Specializations, separated by ;."),
        ("languages", False, "Languages, separated by ; (e.g. English; Russian; Uzbek)."),
        ("certifications", False, "Certifications, separated by ;."),
        ("notes", False, "Private notes (never shown outside your organization)."),
    ],
    "assignments": [
        ("full_name", True, "Must match an expert on the Experts sheet (or already in your library)."),
        ("role", True, "The expert's role on the assignment."),
        ("project", True, "Assignment or project title."),
        ("client", False, "Client."),
        ("country", False, "Country."),
        ("start", False, "YYYY-MM or YYYY-MM-DD."),
        ("end", False, "YYYY-MM or YYYY-MM-DD, or 'present'."),
        ("description", False, "What the expert did."),
    ],
}
# The D2-02 per-tab CSV templates use the API field names: accept them too.
HEADER_ALIASES = {
    "references": {"completion_state": "status", "contract_share_percent": "share_percent", "contract_currency": "currency",
                   "relevant_scope": "scope", "firm_name": "firm", "partner_firm": "firm"},
    "experts": {"display_name": "full_name", "name": "full_name", "title": "position"},
    "assignments": {"expert": "full_name", "expert_name": "full_name", "display_name": "full_name"},
}
IGNORED_COLUMNS = {"evidence_state"}  # an import never claims review: every record is UNVERIFIED
ROLE_VALUES = {
    "lead": "LEAD", "lead firm": "LEAD", "leader": "LEAD", "prime": "LEAD",
    "jv member": "JV_MEMBER", "jv": "JV_MEMBER", "joint venture member": "JV_MEMBER", "joint venture": "JV_MEMBER",
    "consortium member": "CONSORTIUM_MEMBER", "consortium": "CONSORTIUM_MEMBER",
    "subconsultant": "SUBCONSULTANT", "sub-consultant": "SUBCONSULTANT", "sub consultant": "SUBCONSULTANT",
    "subcontractor": "SUBCONTRACTOR", "sub-contractor": "SUBCONTRACTOR",
    "other": "OTHER", "unknown": "UNKNOWN",
}
VALUE_BASIS_VALUES = {
    "firm share": "FIRM_SHARE", "share": "FIRM_SHARE", "consortium total": "CONSORTIUM_TOTAL",
    "contract total": "CONTRACT_TOTAL", "total": "CONTRACT_TOTAL", "unknown": "UNKNOWN", "": "UNKNOWN",
}
STATUS_VALUES = {
    "completed": "COMPLETED", "complete": "COMPLETED", "done": "COMPLETED", "ongoing": "ONGOING",
    "in progress": "ONGOING", "not completed": "NOT_COMPLETED", "terminated": "NOT_COMPLETED", "unknown": "UNKNOWN",
}
DROPDOWNS = {
    ("references", "role"): ["Lead", "JV member", "Consortium member", "Subconsultant", "Subcontractor", "Other"],
    ("references", "value_basis"): ["Firm share", "Consortium total", "Contract total", "Unknown"],
    ("references", "status"): ["Completed", "Ongoing", "Not completed", "Unknown"],
}


class ImportFileError(ValueError):
    """The file cannot be read at all (format, size, sheets)."""


@dataclass
class RowResult:
    kind: str
    row: int  # 1-based spreadsheet row (the header is row 1)
    values: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    duplicate: str | None = None
    payload: dict[str, Any] | None = None

    @property
    def status(self) -> str:
        return "ERROR" if self.errors else "DUPLICATE" if self.duplicate else "NEW"


@dataclass
class ImportPreview:
    file_sha256: str
    file_format: str
    rows: list[RowResult]
    warnings: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, dict[str, int]]:
        result = {kind: {"rows": 0, "new": 0, "duplicates": 0, "errors": 0} for kind in KINDS}
        for row in self.rows:
            bucket = result[row.kind]
            bucket["rows"] += 1
            bucket[{"NEW": "new", "DUPLICATE": "duplicates", "ERROR": "errors"}[row.status]] += 1
        return result


# ---- template ----------------------------------------------------------------------------------------------

def _col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _cell(ref: str, value: Any, style: int = 0) -> str:
    style_attr = f' s="{style}"' if style else ""
    if value is None or value == "":
        return f'<c r="{ref}"{style_attr}/>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{style_attr}><v>{value}</v></c>'
    text = escape(str(value))
    return f'<c r="{ref}" t="inlineStr"{style_attr}><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_xml(rows: list[list[Any]], *, widths: list[int], header_style: bool, validations: list[tuple[str, list[str]]]) -> str:
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    body = []
    for r, row in enumerate(rows, start=1):
        style = 1 if header_style and r == 1 else 0
        cells = "".join(_cell(f"{_col(c)}{r}", value, style) for c, value in enumerate(row))
        body.append(f'<row r="{r}">{cells}</row>')
    frozen = ('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
              'state="frozen"/></sheetView></sheetViews>') if header_style else ""
    dv = ""
    if validations:
        items = "".join(
            f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" sqref="{ref}">'
            f'<formula1>"{escape(",".join(options))}"</formula1></dataValidation>'
            for ref, options in validations
        )
        dv = f'<dataValidations count="{len(validations)}">{items}</dataValidations>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'{frozen}<cols>{cols}</cols><sheetData>{"".join(body)}</sheetData>{dv}</worksheet>')


def build_template_xlsx(rows: dict[str, list[list[Any]]] | None = None) -> bytes:
    """The import template: Instructions plus one sheet per record type (headers, then ``rows``)."""
    instructions = [
        ["Plasma library import (project references and experts)"],
        [""],
        ["1. Fill the References, Experts and Expert assignments sheets: one row per record, headers in row 1."],
        ["2. Columns marked * are required. Leave a cell empty when you do not know the value."],
        ["3. Lists (education, languages...) are separated by ; inside one cell."],
        ["4. Dates: YYYY-MM-DD or YYYY-MM. Numbers without currency signs or spaces."],
        ["5. In Plasma: Company & Experience > Import > upload this file > check the preview > Import."],
        ["   Nothing is saved until you press Import. Rows with errors are skipped and listed;"],
        ["   a record already in your library (same firm and project, or same expert name) is not imported twice."],
        [""],
        ["Sheet", "Column", "Required", "What to enter"],
    ]
    for kind in KINDS:
        for header, required, help_text in COLUMNS[kind]:
            instructions.append([SHEET_TITLES[kind], header, "yes" if required else "", help_text])
    instructions += [
        [""],
        ["Example (References)", "", "", "Water supply feasibility study, Bukhara | Ministry of Water Resources | Uzbekistan | "
         "Feasibility study | Water | Lead | 480000 | USD | Firm share | 100 | 2021-03 | 2022-06 | Completed"],
        ["Example (Experts)", "", "", "Dilnoza Karimova | Team Leader / Water Engineer | 16 | MSc Water Engineering | "
         "FIDIC contract administration | Distribution networks; NRW | English; Russian; Uzbek"],
    ]
    sheets: list[tuple[str, str]] = [("Instructions", _sheet_xml(instructions, widths=[24, 20, 10, 110], header_style=False, validations=[]))]
    for kind in KINDS:
        headers = [f"{name}*" if required else name for name, required, _ in COLUMNS[kind]]
        validations = []
        for index, (name, _, _) in enumerate(COLUMNS[kind]):
            options = DROPDOWNS.get((kind, name))
            if options:
                validations.append((f"{_col(index)}2:{_col(index)}{MAX_ROWS_PER_SHEET + 1}", options))
        widths = [max(14, min(60, len(h) + 6)) for h in headers]
        data_rows = [list(row) for row in (rows or {}).get(kind, [])]
        sheets.append((SHEET_TITLES[kind], _sheet_xml([headers, *data_rows], widths=widths, header_style=True, validations=validations)))

    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                     '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                     + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                               'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                               for i in range(1, len(sheets) + 1))
                     + '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                 '</Relationships>')
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                + "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, start=1))
                + '</sheets></workbook>')
    workbook_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                               f'Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
                     + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                     '</Relationships>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
              '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFE8EEF5"/><bgColor indexed="64"/></patternFill></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
              '</styleSheet>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", styles)
        for index, (_, xml) in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", xml)
    return buffer.getvalue()


def build_template_csv(kind: str) -> bytes:
    if kind not in KINDS:
        raise ImportFileError("unknown template kind")
    buffer = io.StringIO()
    csv.writer(buffer).writerow([f"{name}*" if required else name for name, required, _ in COLUMNS[kind]])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


# ---- reading -----------------------------------------------------------------------------------------------

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _read_part(archive: zipfile.ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > MAX_XML_PART_BYTES:
        raise ImportFileError("the spreadsheet is too large to import")
    data = archive.read(name)
    if b"<!DOCTYPE" in data[:2048] or b"<!ENTITY" in data:
        raise ImportFileError("the spreadsheet contains unsupported XML")
    return data


def _xlsx_sheets(content: bytes) -> dict[str, list[list[Any]]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise ImportFileError("not a readable .xlsx file") from None
    with archive:
        if len(archive.infolist()) > MAX_ZIP_ENTRIES:
            raise ImportFileError("the spreadsheet has too many parts")
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names:
            raise ImportFileError("not a readable .xlsx file")
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            for item in ElementTree.fromstring(_read_part(archive, "xl/sharedStrings.xml")).findall("m:si", _NS):
                shared.append("".join(node.text or "" for node in item.iter(f"{{{_NS['m']}}}t")))
        rels = {}
        if "xl/_rels/workbook.xml.rels" in names:
            for rel in ElementTree.fromstring(_read_part(archive, "xl/_rels/workbook.xml.rels")).findall("rel:Relationship", _NS):
                target = rel.get("Target", "")
                rels[rel.get("Id")] = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        workbook = ElementTree.fromstring(_read_part(archive, "xl/workbook.xml"))
        result: dict[str, list[list[Any]]] = {}
        for sheet in workbook.findall("m:sheets/m:sheet", _NS):
            path = rels.get(sheet.get(f"{{{_NS['r']}}}id"))
            if not path or path not in names:
                continue
            rows: list[list[Any]] = []
            for row in ElementTree.fromstring(_read_part(archive, path)).findall("m:sheetData/m:row", _NS):
                values: dict[int, Any] = {}
                for cell in row.findall("m:c", _NS):
                    ref = cell.get("r") or ""
                    letters = "".join(ch for ch in ref if ch.isalpha())
                    column = 0
                    for ch in letters:
                        column = column * 26 + (ord(ch.upper()) - 64)
                    column = column - 1 if letters else len(values)
                    kind = cell.get("t")
                    if kind == "inlineStr":
                        value: Any = "".join(node.text or "" for node in cell.iter(f"{{{_NS['m']}}}t"))
                    else:
                        raw = cell.findtext("m:v", default=None, namespaces=_NS)
                        if raw is None:
                            continue
                        if kind == "s":
                            value = shared[int(raw)] if raw.isdigit() and int(raw) < len(shared) else ""
                        elif kind in {"str", "e"}:
                            value = raw
                        elif kind == "b":
                            value = raw == "1"
                        else:
                            try:
                                number = float(raw)
                                value = int(number) if number.is_integer() else number
                            except ValueError:
                                value = raw
                    values[column] = value
                if values:
                    width = max(values) + 1
                    rows.append([values.get(index) for index in range(width)])
                if len(rows) > MAX_ROWS_PER_SHEET + 1:
                    raise ImportFileError(f"a sheet has more than {MAX_ROWS_PER_SHEET} rows")
            result[sheet.get("name") or path] = rows
        return result


def _csv_rows(content: bytes) -> list[list[Any]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("cp1251")
        except UnicodeDecodeError:
            raise ImportFileError("the CSV is not UTF-8 text") from None
    sample = text[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    rows = [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    if len(rows) > MAX_ROWS_PER_SHEET + 1:
        raise ImportFileError(f"the CSV has more than {MAX_ROWS_PER_SHEET} rows")
    return rows


def _header_key(value: Any) -> str:
    return re.sub(r"[\s*]+", "_", str(value or "").strip().lower()).strip("_")


def _canonical(kind: str, key: str) -> str:
    return HEADER_ALIASES.get(kind, {}).get(key, key)


def _identify(headers: list[Any]) -> str | None:
    raw = {_header_key(h) for h in headers if h not in (None, "")}
    best, best_score = None, 0
    for kind in KINDS:
        keys = {_canonical(kind, key) for key in raw}
        required = {name for name, req, _ in COLUMNS[kind] if req}
        if required <= keys:
            score = len(keys & {name for name, _, _ in COLUMNS[kind]})
            if score > best_score:
                best, best_score = kind, score
    return best


def _sheet_kind(name: str, headers: list[Any]) -> str | None:
    lowered = name.strip().lower()
    for kind, title in SHEET_TITLES.items():
        if lowered == title.lower():
            return kind
    return _identify(headers)


def parse_upload(filename: str, content: bytes) -> tuple[str, dict[str, list[dict[str, Any]]], list[str]]:
    """(format, {kind: [{"_row": n, header: value}]}, warnings)."""
    if not content:
        raise ImportFileError("the file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ImportFileError("the file is larger than 2 MB")
    name = (filename or "").lower()
    warnings: list[str] = []
    if content[:2] == b"PK" or name.endswith(".xlsx"):
        file_format = "xlsx"
        sheets = list(_xlsx_sheets(content).items())
    elif name.endswith(".csv") or name.endswith(".txt") or b"\x00" not in content[:1024]:
        file_format = "csv"
        sheets = [(filename or "upload.csv", _csv_rows(content))]
    else:
        raise ImportFileError("upload the .xlsx template or a .csv file")
    tables: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
    recognised = False
    for sheet_name, rows in sheets:
        if not rows or sheet_name.strip().lower() == "instructions":
            continue
        kind = _sheet_kind(sheet_name, rows[0])
        if kind is None:
            warnings.append(f"Sheet '{sheet_name}' was ignored: its first row does not match a template sheet.")
            continue
        recognised = True
        keys = [_canonical(kind, _header_key(h)) for h in rows[0]]
        known = {name for name, _, _ in COLUMNS[kind]}
        unknown = sorted({k for k in keys if k and k not in known and k not in IGNORED_COLUMNS})
        if unknown:
            warnings.append(f"{SHEET_TITLES[kind]}: columns ignored: {', '.join(unknown)}.")
        for index, row in enumerate(rows[1:], start=2):
            record = {keys[i]: row[i] for i in range(min(len(keys), len(row))) if keys[i] in known}
            if all(value in (None, "") or (isinstance(value, str) and not value.strip()) for value in record.values()):
                continue
            tables[kind].append({"_row": index, **record})
    if not recognised:
        raise ImportFileError("no References, Experts or Expert assignments sheet found (check the header row)")
    return file_format, tables, warnings


# ---- validation --------------------------------------------------------------------------------------------

def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = " ".join(str(value).split())
    return text or None


def _list(value: Any) -> list[str]:
    text = _text(value) if not isinstance(value, str) else value.strip()
    return [part for part in (p.strip() for p in LIST_SEPARATOR.split(text or "")) if part] if text else []


def _excel_date(serial: float) -> date:
    return date(1899, 12, 30) + timedelta(days=int(serial))


def _date(value: Any, label: str, errors: list[str]) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 20000 < float(value) < 80000:  # an Excel date serial (1954-2119)
            return _excel_date(float(value))
        if 1950 <= int(value) <= 2100 and float(value).is_integer():
            return date(int(value), 1, 1)
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%Y-%m", "%d.%m.%Y", "%m/%Y", "%Y/%m/%d", "%d/%m/%Y", "%Y"):
        try:
            parsed = datetime.strptime(text[:10] if pattern == "%Y-%m-%d" else text, pattern)
            return parsed.date()
        except ValueError:
            continue
    errors.append(f"{label}: not a date (use YYYY-MM-DD or YYYY-MM)")
    return None


def _decimal(value: Any, label: str, errors: list[str], *, low: float | None = None, high: float | None = None) -> Decimal | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(" ", "").replace(" ", "")
    text = text.rstrip("%")
    if text.count(",") == 1 and "." not in text:
        text = text.replace(",", ".")
    text = text.replace(",", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        errors.append(f"{label}: not a number")
        return None
    if (low is not None and number < Decimal(str(low))) or (high is not None and number > Decimal(str(high))):
        errors.append(f"{label}: must be between {low:g} and {high:g}")
        return None
    return number


def _choice(value: Any, mapping: dict[str, str], label: str, errors: list[str], *, default: str | None = None) -> str | None:
    key = (_text(value) or "").lower().replace("_", " ")
    if not key:
        return default
    if key in mapping:
        return mapping[key]
    upper = key.upper().replace(" ", "_")
    if upper in set(mapping.values()):
        return upper
    errors.append(f"{label}: '{_text(value)}' is not one of the template's values")
    return None


def _key(text: str | None) -> str:
    return " ".join((text or "").lower().split())


def _validation_messages(exc: ValidationError) -> list[str]:
    messages = []
    for error in exc.errors()[:5]:
        location = ".".join(str(part) for part in error.get("loc", ()))
        messages.append(f"{location}: {error.get('msg', 'invalid value')}")
    return messages


def _validate_reference(record: dict[str, Any], provenance: dict[str, Any]) -> RowResult:
    errors: list[str] = []
    values = {k: v for k, v in record.items() if k != "_row"}
    completion = _date(values.get("completion_date"), "completion_date", errors)
    start = _date(values.get("start_date"), "start_date", errors)
    if start and completion and completion < start:
        errors.append("completion_date: before start_date")
    status_default = "COMPLETED" if completion and completion <= date.today() else "ONGOING" if completion else "UNKNOWN"
    currency = (_text(values.get("currency")) or "").upper() or None
    contract_value = _decimal(values.get("contract_value"), "contract_value", errors, low=0, high=1e15)
    payload = {
        "project_name": _text(values.get("project_name")) or "",
        "client_name": _text(values.get("client_name")),
        "country": _text(values.get("country")),
        "service": _text(values.get("service")),
        "sector": _text(values.get("sector")),
        "role": _choice(values.get("role"), ROLE_VALUES, "role", errors),
        "contract_share_percent": _decimal(values.get("share_percent"), "share_percent", errors, low=0, high=100),
        "contract_value": contract_value,
        "contract_currency": currency,
        "value_basis": _choice(values.get("value_basis"), VALUE_BASIS_VALUES, "value_basis", errors, default="UNKNOWN"),
        "start_date": start,
        "completion_date": completion,
        "completion_state": _choice(values.get("status"), STATUS_VALUES, "status", errors, default=status_default),
        "relevant_scope": (str(values.get("scope")).strip() or None) if values.get("scope") not in (None, "") else None,
        "evidence_provenance": {**provenance, "row": record["_row"], "sheet": "References"},
        "evidence_state": "UNVERIFIED",
    }
    if not payload["project_name"]:
        errors.append("project_name: required")
    if payload["role"] is None and not any(e.startswith("role") for e in errors):
        errors.append("role: required")
    if contract_value is not None and not currency:
        errors.append("currency: required when contract_value is set")
    if contract_value is not None and payload["value_basis"] == "UNKNOWN":
        errors.append("value_basis: required when contract_value is set (Firm share, Consortium total or Contract total)")
    if currency and not re.fullmatch(r"[A-Z]{3}", currency):
        errors.append("currency: use a 3-letter ISO code such as USD")
    if not errors:
        try:
            ProjectReferenceCreateRequest(**payload)
        except ValidationError as exc:
            errors.extend(_validation_messages(exc))
    return RowResult(kind="references", row=record["_row"], values=values, errors=errors,
                     payload={**payload, "firm": _text(values.get("firm"))})


def _validate_expert(record: dict[str, Any], provenance: dict[str, Any]) -> RowResult:
    errors: list[str] = []
    values = {k: v for k, v in record.items() if k != "_row"}
    name = _text(values.get("full_name")) or ""
    if len(name) < 2:
        errors.append("full_name: required")
    years = _decimal(values.get("years_experience"), "years_experience", errors, low=0, high=70)
    position = _text(values.get("position"))
    education = _list(values.get("education"))
    qualifications = _list(values.get("qualifications"))
    specializations = _list(values.get("specializations"))
    languages = _list(values.get("languages"))
    certifications = _list(values.get("certifications"))
    expert = {
        "scope": "ORGANIZATION_PRIVATE", "display_name": name,
        "qualifications": [*education, *qualifications, *([f"{int(years)} years of professional experience"] if years is not None else [])],
        "languages": languages, "specializations": [*([position] if position else []), *specializations],
        "consent_state": "NOT_REQUIRED_PRIVATE", "evidence_state": "UNVERIFIED",
        "source_provenance": {**provenance, "row": record["_row"], "sheet": "Experts"},
        "private_notes": (str(values.get("notes")).strip() or None) if values.get("notes") not in (None, "") else None,
    }
    cv = {
        "education": [{"degree": degree} for degree in education],
        "qualifications": [{"title": position or "", "years_experience": int(years) if years is not None else None,
                            "summary": "; ".join(qualifications) or None}] if (position or years is not None or qualifications) else [],
        "certifications": [{"name": item} for item in certifications],
        "assignments": [],
        "languages": [{"language": language} for language in languages],
        "evidence_provenance": {**provenance, "row": record["_row"], "sheet": "Experts"},
        "evidence_state": "UNVERIFIED",
    }
    if not errors:
        try:
            ExpertCreateRequest(**expert)
            CVVersionCreateRequest(**cv)
        except ValidationError as exc:
            errors.extend(_validation_messages(exc))
    return RowResult(kind="experts", row=record["_row"], values=values, errors=errors, payload={"expert": expert, "cv": cv})


def _validate_assignment(record: dict[str, Any]) -> RowResult:
    errors: list[str] = []
    values = {k: v for k, v in record.items() if k != "_row"}
    name = _text(values.get("full_name")) or ""
    role = _text(values.get("role"))
    project = _text(values.get("project"))
    if not name:
        errors.append("full_name: required")
    if not role:
        errors.append("role: required")
    if not project:
        errors.append("project: required")
    start = _date(values.get("start"), "start", errors)
    end_raw = _text(values.get("end"))
    end = None if (end_raw or "").lower() in {"present", "current", "ongoing", "now"} else _date(values.get("end"), "end", errors)
    if start and end and end < start:
        errors.append("end: before start")
    assignment = {"role": role, "project": project, "client": _text(values.get("client")), "country": _text(values.get("country")),
                  "start": start.strftime("%Y-%m") if start else None,
                  "end": "present" if end_raw and end is None and not errors else (end.strftime("%Y-%m") if end else None),
                  "description": (str(values.get("description")).strip() or None) if values.get("description") not in (None, "") else None}
    return RowResult(kind="assignments", row=record["_row"], values=values, errors=errors,
                     payload={"full_name": name, "assignment": {k: v for k, v in assignment.items() if v is not None}})


async def _existing(db: AsyncSession, organization_id: UUID) -> tuple[UUID | None, dict[str, UUID], set[tuple[str, str]], dict[str, UUID]]:
    self_firm_id = await db.scalar(select(Firm.id).where(Firm.organization_id == organization_id))
    partners = {_key(name): firm_id for firm_id, name in (await db.execute(
        select(Firm.id, Firm.display_name).where(Firm.owner_organization_id == organization_id, Firm.organization_id.is_(None))
    )).all()}
    firm_ids = [fid for fid in [self_firm_id, *partners.values()] if fid is not None]
    references = set()
    if firm_ids:
        references = {(str(firm_id), _key(name)) for firm_id, name in (await db.execute(
            select(ProjectReference.firm_id, ProjectReference.project_name)
            .where(ProjectReference.firm_id.in_(firm_ids), ProjectReference.archived_at.is_(None))
        )).all()}
    experts = {_key(name): expert_id for expert_id, name in (await db.execute(
        select(Expert.id, Expert.display_name).where(Expert.owner_organization_id == organization_id)
    )).all()}
    return self_firm_id, partners, references, experts


async def _existing_assignments(db: AsyncSession, experts: dict[str, UUID]) -> dict[str, set[tuple[str, str]]]:
    """(project, role) keys on each existing expert's latest CV version."""
    if not experts:
        return {}
    latest = (
        select(CVVersion.expert_id, func.max(CVVersion.version_number).label("version"))
        .where(CVVersion.expert_id.in_(list(experts.values()))).group_by(CVVersion.expert_id).subquery()
    )
    rows = (await db.execute(
        select(CVVersion.expert_id, CVVersion.assignments)
        .join(latest, (latest.c.expert_id == CVVersion.expert_id) & (latest.c.version == CVVersion.version_number))
    )).all()
    by_id = {expert_id: {(_key(a.get("project")), _key(a.get("role"))) for a in (assignments or []) if isinstance(a, dict)}
             for expert_id, assignments in rows}
    return {name: by_id.get(expert_id, set()) for name, expert_id in experts.items()}


async def preview(db: AsyncSession, *, organization_id: UUID, filename: str, content: bytes) -> ImportPreview:
    file_format, tables, warnings = parse_upload(filename, content)
    digest = hashlib.sha256(content).hexdigest()
    provenance = {"import": "library_import", "file_sha256": digest, "file_format": file_format}
    self_firm_id, partners, existing_refs, existing_experts = await _existing(db, organization_id)
    rows: list[RowResult] = []
    seen_refs: set[tuple[str, str]] = set()
    for record in tables["references"]:
        result = _validate_reference(record, provenance)
        if not result.errors:
            firm_name = result.payload["firm"]
            firm_key = "self" if not firm_name else _key(firm_name)
            firm_id = str(self_firm_id) if not firm_name else (str(partners[_key(firm_name)]) if _key(firm_name) in partners else None)
            ref_key = (firm_key, _key(result.payload["project_name"]))
            if firm_id and (firm_id, ref_key[1]) in existing_refs:
                result.duplicate = "already in your library"
            elif ref_key in seen_refs:
                result.duplicate = "repeated in this file"
            seen_refs.add(ref_key)
        rows.append(result)
    file_experts: set[str] = set()
    for record in tables["experts"]:
        result = _validate_expert(record, provenance)
        if not result.errors:
            key = _key(result.payload["expert"]["display_name"])
            if key in existing_experts:
                result.duplicate = "already in your library"
            elif key in file_experts:
                result.duplicate = "repeated in this file"
            file_experts.add(key)
        rows.append(result)
    on_cv = await _existing_assignments(db, existing_experts)
    seen_assignments: set[tuple[str, str, str]] = set()
    for record in tables["assignments"]:
        result = _validate_assignment(record)
        if not result.errors:
            key = _key(result.payload["full_name"])
            assignment = result.payload["assignment"]
            triple = (key, _key(assignment.get("project")), _key(assignment.get("role")))
            if key not in file_experts and key not in existing_experts:
                result.errors.append("full_name: no expert with this name on the Experts sheet or in your library")
            elif key in existing_experts and triple[1:] in on_cv.get(key, set()):
                result.duplicate = "already on this expert's CV"
            elif triple in seen_assignments:
                result.duplicate = "repeated in this file"
            seen_assignments.add(triple)
        rows.append(result)
    return ImportPreview(file_sha256=digest, file_format=file_format, rows=rows, warnings=warnings)


@dataclass(frozen=True)
class CommitResult:
    file_sha256: str
    references_created: int
    partner_firms_created: int
    experts_created: int
    cv_versions_created: int
    assignments_attached: int
    skipped_duplicates: int
    skipped_errors: int


async def commit(
    db: AsyncSession, *, organization_id: UUID, actor_user_id: UUID, filename: str, content: bytes, expected_sha256: str,
) -> CommitResult:
    """Write every NEW row of the previewed file in one transaction (the caller commits)."""
    from app.services.candidate_retrieval import _canonical_payload, _clean_list, upsert_self_firm

    digest = hashlib.sha256(content).hexdigest()
    if digest != (expected_sha256 or "").strip().lower():
        raise ImportFileError("this is not the file you previewed: preview it again")
    if await db.scalar(select(Firm.id).where(Firm.organization_id == organization_id)) is None:
        await upsert_self_firm(db, organization_id=organization_id, actor_user_id=actor_user_id, payload=SelfFirmUpsertRequest())
    result = await preview(db, organization_id=organization_id, filename=filename, content=content)
    self_firm_id, partners, _, existing_experts = await _existing(db, organization_id)
    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    counts = {"references": 0, "firms": 0, "experts": 0, "cv": 0, "assignments": 0}
    assignments_by_name: dict[str, list[dict[str, Any]]] = {}
    for row in result.rows:
        if row.kind == "assignments" and row.status == "NEW":
            assignments_by_name.setdefault(_key(row.payload["full_name"]), []).append(row.payload["assignment"])

    for row in result.rows:
        if row.kind != "references" or row.status != "NEW":
            continue
        facts = {key: value for key, value in row.payload.items() if key != "firm"}
        facts["evidence_provenance"] = {**facts["evidence_provenance"], "imported_at": imported_at}
        firm_name = row.payload["firm"]
        if not firm_name:
            firm_id = self_firm_id
        else:
            firm_id = partners.get(_key(firm_name))
            if firm_id is None:
                firm = Firm(
                    scope="ORGANIZATION_PRIVATE", owner_organization_id=organization_id, canonical_name=firm_name,
                    display_name=firm_name, country=facts.get("country"), regions=[], services=_clean_list([facts.get("service") or ""]),
                    capabilities=[], sectors=_clean_list([facts.get("sector") or ""]), source_type="EXPLICIT_IMPORT",
                    source_provenance={k: v for k, v in facts["evidence_provenance"].items() if k != "row"},
                    evidence_state="UNVERIFIED", created_by_user_id=actor_user_id,
                )
                db.add(firm)
                await db.flush()
                partners[_key(firm_name)] = firm_id = firm.id
                counts["firms"] += 1
        db.add(ProjectReference(firm_id=firm_id, created_by_user_id=actor_user_id,
                                **ProjectReferenceCreateRequest(**facts).model_dump()))
        counts["references"] += 1

    new_experts: dict[str, UUID] = {}
    for row in result.rows:
        if row.kind != "experts" or row.status != "NEW":
            continue
        payload = ExpertCreateRequest(**row.payload["expert"])
        expert = Expert(
            scope=payload.scope, owner_organization_id=organization_id, display_name=" ".join(payload.display_name.split()),
            qualifications=_clean_list(payload.qualifications), languages=_clean_list(payload.languages),
            specializations=_clean_list(payload.specializations), consent_state=payload.consent_state,
            evidence_state=payload.evidence_state, source_provenance={**payload.source_provenance, "imported_at": imported_at},
            private_notes=payload.private_notes, created_by_user_id=actor_user_id,
        )
        db.add(expert)
        await db.flush()
        new_experts[_key(payload.display_name)] = expert.id
        cv = dict(row.payload["cv"])
        cv["assignments"] = assignments_by_name.pop(_key(payload.display_name), [])
        counts["assignments"] += len(cv["assignments"])
        facts = CVVersionCreateRequest(**cv).model_dump()
        db.add(CVVersion(expert_id=expert.id, version_number=1,
                         structured_sha256=hashlib.sha256(_canonical_payload(facts).encode("utf-8")).hexdigest(),
                         created_by_user_id=actor_user_id, **facts))
        counts["experts"] += 1
        counts["cv"] += 1

    # Assignments for experts already in the library: a new CV version carrying the previous facts plus these.
    for name_key, assignments in assignments_by_name.items():
        expert_id = existing_experts.get(name_key)
        if expert_id is None or not assignments:
            continue
        expert = await db.scalar(select(Expert).where(Expert.id == expert_id).with_for_update())
        latest = await db.scalar(select(CVVersion).where(CVVersion.expert_id == expert_id)
                                 .order_by(CVVersion.version_number.desc()).limit(1))
        base = {key: list(getattr(latest, key) or []) for key in ("education", "qualifications", "certifications", "assignments", "languages")} \
            if latest is not None else {"education": [], "qualifications": [], "certifications": [], "assignments": [], "languages": []}
        known = {(_key(a.get("project")), _key(a.get("role"))) for a in base["assignments"]}
        fresh = [a for a in assignments if (_key(a.get("project")), _key(a.get("role"))) not in known]
        if not fresh or expert is None:
            continue
        facts = CVVersionCreateRequest(
            **{**base, "assignments": [*base["assignments"], *fresh]},
            evidence_provenance={"import": "library_import", "file_sha256": digest, "imported_at": imported_at},
            evidence_state="UNVERIFIED",
        ).model_dump()
        current = await db.scalar(select(func.max(CVVersion.version_number)).where(CVVersion.expert_id == expert_id))
        db.add(CVVersion(expert_id=expert_id, version_number=int(current or 0) + 1,
                         structured_sha256=hashlib.sha256(_canonical_payload(facts).encode("utf-8")).hexdigest(),
                         created_by_user_id=actor_user_id, **facts))
        counts["cv"] += 1
        counts["assignments"] += len(fresh)
    await db.flush()
    statuses = [row.status for row in result.rows]
    return CommitResult(
        file_sha256=digest, references_created=counts["references"], partner_firms_created=counts["firms"],
        experts_created=counts["experts"], cv_versions_created=counts["cv"], assignments_attached=counts["assignments"],
        skipped_duplicates=statuses.count("DUPLICATE"), skipped_errors=statuses.count("ERROR"),
    )


def preview_payload(result: ImportPreview, *, limit: int = 1000) -> dict[str, Any]:
    def visible(row: RowResult) -> dict[str, Any]:
        shown = {key: (value.isoformat() if isinstance(value, (date, datetime)) else value)
                 for key, value in row.values.items() if value not in (None, "")}
        return {"kind": row.kind, "row": row.row, "status": row.status, "errors": row.errors,
                "duplicate": row.duplicate, "values": shown}

    return {
        "file_sha256": result.file_sha256, "file_format": result.file_format, "warnings": result.warnings,
        "counts": result.counts(), "rows": [visible(row) for row in result.rows[:limit]],
        "truncated": len(result.rows) > limit,
    }


def iter_kinds() -> Iterable[str]:
    return iter(KINDS)
