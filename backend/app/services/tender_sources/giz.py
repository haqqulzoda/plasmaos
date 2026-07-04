"""GIZ public country-office tender connector."""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import logging
import mimetypes
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from lxml import html

from app.models.all_models import TenderDocument, TenderStatus
from app.core.geography import CENTRAL_ASIA_COUNTRIES, CENTRAL_ASIA_REGION
from app.services.tender_sources.base import (
    NormalizedAttachment,
    NormalizedTender,
    assert_source_scope,
    canonical_documents_from_attachments,
    upsert_tender,
)

logger = logging.getLogger(__name__)

GIZ_BASE_URL = "https://www.giz.de"
GIZ_EPROC_BASE_URL = "https://ausschreibungen.giz.de"
GIZ_EPROC_WELCOME_URL = f"{GIZ_EPROC_BASE_URL}/Satellite/company/welcome.do"
GIZ_USER_AGENT = "PlasmaOS GIZConnector/1.0"
DEFAULT_GIZ_TENDER_PAGES: tuple[str, ...] = (
    "https://www.giz.de/en/regions/africa/ghana/tenders",
    "https://www.giz.de/en/regions/africa/south-africa/tenders",
    "https://www.giz.de/en/regions/africa/tanzania/tenders",
    "https://www.giz.de/en/regions/asia/indonesia/tenders",
    "https://www.giz.de/en/regions/asia/lao-peoples-democratic-republic/tenders",
    "https://www.giz.de/en/regions/asia/viet-nam/tenders",
)
GIZ_ALLOWED_HOST_SUFFIXES = ("giz.de",)
GIZ_ALLOWED_FILE_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "zip", "rtf"}
GIZ_REFERENCE_RE = re.compile(r"\b\d{8,10}\b")
EMAIL_RE = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+")
GIZ_EPROC_PROJECT_RE = re.compile(r"/project/([^/]+)/")
def _env_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


MAX_ARCHIVE_COMPRESSED_BYTES = _env_positive_int(
    "GIZ_MAX_ARCHIVE_COMPRESSED_BYTES",
    100 * 1024 * 1024,
)
MAX_ARCHIVE_EXTRACTED_BYTES = _env_positive_int(
    "GIZ_MAX_ARCHIVE_EXTRACTED_BYTES",
    250 * 1024 * 1024,
)
MAX_ARCHIVE_FILE_COUNT = _env_positive_int("GIZ_MAX_ARCHIVE_FILE_COUNT", 200)
MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES = _env_positive_int(
    "GIZ_MAX_ARCHIVE_INDIVIDUAL_FILE_BYTES",
    50 * 1024 * 1024,
)
MAX_ARCHIVE_NESTING_DEPTH = _env_positive_int("GIZ_MAX_ARCHIVE_NESTING_DEPTH", 1)
MAX_DOWNLOAD_BYTES = MAX_ARCHIVE_COMPRESSED_BYTES
MAX_GIZ_EPROC_PAGES = 6
GIZ_PLACEHOLDER_TITLES = {
    "bidding list",
    "tender",
    "tenders",
    "download",
    "downloads",
}

CENTRAL_ASIA_EXPLICIT_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Uzbekistan", ("uzbekistan", "usbekistan", "tashkent", "taschkent")),
    ("Kazakhstan", ("kazakhstan", "kasachstan", "astana", "almaty")),
    ("Kyrgyzstan", ("kyrgyzstan", "kirgisistan", "bishkek")),
    ("Tajikistan", ("tajikistan", "tadschikistan", "dushanbe")),
    ("Turkmenistan", ("turkmenistan", "ashgabat", "aschgabat")),
)


@dataclass(frozen=True)
class GizSyncConfig:
    source_pages: tuple[str, ...] = DEFAULT_GIZ_TENDER_PAGES
    eproc_max_pages: int = MAX_GIZ_EPROC_PAGES
    include_eproc: bool = True
    timeout_seconds: float = 30.0
    request_delay_seconds: float = 0.25
    max_retries: int = 2
    max_download_bytes: int = MAX_DOWNLOAD_BYTES


def _clean_whitespace(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or None


def _parse_date(value: str | None) -> datetime | None:
    text = _clean_whitespace(value)
    if not text:
        return None
    text = re.sub(r"^Deadline:\s*", "", text, flags=re.IGNORECASE)
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _parse_giz_datetime(value: str | None) -> datetime | None:
    text = _clean_whitespace(value)
    if not text or text.casefold() == "nv":
        return None
    text = text.replace("Uhr", "").strip()
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return _parse_date(text)


def _source_region(url: str) -> str | None:
    match = re.search(r"/regions/([^/]+)/", urlparse(url).path)
    if not match:
        return None
    return match.group(1).replace("-", " ").title()


def _node_text(node: Any) -> str | None:
    return _clean_whitespace(node.text_content() if node is not None else None)


def _first_text(root: Any, xpath: str) -> str | None:
    nodes = root.xpath(xpath)
    return _node_text(nodes[0]) if nodes else None


def _safe_giz_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    hostname = (parsed.hostname or "").casefold()
    return any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in GIZ_ALLOWED_HOST_SUFFIXES
    )


def _extension_from_url(url: str) -> str | None:
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    return suffix if suffix in GIZ_ALLOWED_FILE_EXTENSIONS else None


def _parse_size_bytes(value: str | None) -> int | None:
    text = _clean_whitespace(value)
    if not text:
        return None
    text = text.replace(",", ".")
    match = re.match(r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>kb|mb|gb|b)\b", text, re.IGNORECASE)
    if not match:
        return None
    number = float(match.group("number"))
    unit = match.group("unit").casefold()
    multiplier = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3}[unit]
    return int(number * multiplier)


def _decode_giz_mail_token(value: str | None) -> str | None:
    token = _clean_whitespace(value)
    if not token:
        return None
    decoded = codecs.decode(token, "rot_13")
    decoded = decoded.replace("/at/", "@").replace("/dot/", ".")
    decoded = decoded.replace("[at]", "@").replace("[dot]", ".")
    decoded = decoded.replace(" at ", "@").replace(" dot ", ".")
    match = EMAIL_RE.search(decoded)
    return match.group(0) if match else None


def _extract_page_email(root: Any) -> str | None:
    for value in root.xpath(".//*[@data-mail-to]/@data-mail-to"):
        decoded = _decode_giz_mail_token(value)
        if decoded:
            return decoded
    match = EMAIL_RE.search(root.text_content() or "")
    return match.group(0) if match else None


def _is_giz_placeholder_title(title: str | None) -> bool:
    normalized = _clean_whitespace(title)
    if not normalized:
        return True
    return normalized.casefold() in GIZ_PLACEHOLDER_TITLES


def _title_without_download_text(wrapper: Any) -> str:
    title = _first_text(wrapper, './/*[contains(concat(" ", normalize-space(@class), " "), " list-item__title ")]')
    return title or "GIZ tender"


def _description(wrapper: Any) -> str | None:
    title = _title_without_download_text(wrapper)
    sub = _first_text(wrapper, './/*[contains(concat(" ", normalize-space(@class), " "), " list-item__sub ")]')
    if sub and sub != title:
        return f"{title} {sub}"
    return title


def _document_title(download_node: Any, href: str) -> str:
    title = _first_text(
        download_node,
        './/*[contains(concat(" ", normalize-space(@class), " "), " download__title ")]',
    )
    if title:
        return title
    return Path(urlparse(href).path).name or "document"


def _download_infos(download_node: Any) -> tuple[str | None, int | None]:
    infos = [
        _node_text(node)
        for node in download_node.xpath(
            './/*[contains(concat(" ", normalize-space(@class), " "), " download__info ")]'
        )
    ]
    doc_type = None
    size = None
    for item in infos:
        if not item:
            continue
        if item.casefold() in GIZ_ALLOWED_FILE_EXTENSIONS:
            doc_type = item.casefold()
        parsed_size = _parse_size_bytes(item)
        if parsed_size is not None:
            size = parsed_size
    return doc_type, size


def _attachment_from_download_node(
    download_node: Any,
    *,
    page_url: str,
) -> dict[str, Any] | None:
    hrefs = []
    hrefs.extend(download_node.xpath('.//a[@href]/@href'))
    hrefs.extend(download_node.xpath('.//*[@data-pdf-download-file]/@data-pdf-download-file'))
    hrefs.extend(download_node.xpath('.//*[@data-pdf-file]/@data-pdf-file'))
    href = next((item for item in hrefs if item), None)
    if not href:
        return None
    absolute_url = urljoin(page_url, href)
    extension = _extension_from_url(absolute_url)
    if not extension or not _safe_giz_url(absolute_url):
        return None
    doc_type, file_size = _download_infos(download_node)
    filename = _document_title(download_node, absolute_url)
    return {
        "source_document_url": absolute_url,
        "source_document_type": doc_type or extension,
        "external_file_id": hashlib.sha256(
            absolute_url.encode("utf-8")
        ).hexdigest()[:32],
        "file_size": file_size,
        "mime_type": mimetypes.guess_type(filename)[0],
        "filename": filename,
    }


def _extract_attachments(wrapper: Any, *, page_url: str) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    seen: set[str] = set()
    for download_node in wrapper.xpath(
        './/*[contains(concat(" ", normalize-space(@class), " "), " download ")]'
    ):
        attachment = _attachment_from_download_node(download_node, page_url=page_url)
        if not attachment:
            continue
        source_url = attachment["source_document_url"]
        if source_url in seen:
            continue
        seen.add(source_url)
        attachments.append(attachment)
    return attachments


def _document_type_from_name(filename: str | None) -> str | None:
    suffix = Path(str(filename or "")).suffix.lower().lstrip(".")
    return suffix if suffix in GIZ_ALLOWED_FILE_EXTENSIONS else None


def _stable_external_id(*, title: str, attachments: list[dict[str, Any]]) -> str | None:
    blob = " ".join(
        [title, *[str(item.get("source_document_url") or "") for item in attachments]]
    )
    match = GIZ_REFERENCE_RE.search(blob)
    if match:
        return match.group(0).upper()
    return None


def _external_id(*, title: str, attachments: list[dict[str, Any]], page_url: str) -> str:
    stable = _stable_external_id(title=title, attachments=attachments)
    if stable:
        return stable
    digest = hashlib.sha256(f"{page_url}|{title}".encode("utf-8")).hexdigest()[:16]
    return f"page-{digest}"


def _category(title: str) -> tuple[str | None, str | None]:
    normalized = title.casefold()
    if "goods" in normalized or "supply" in normalized:
        return "Goods", "equipment supply"
    if "construction" in normalized or "works" in normalized:
        return "Works", "construction"
    if "service" in normalized or "consult" in normalized or "proposal" in normalized:
        return "Services", "consulting"
    return None, None


def _deadline_from_download_title(title: str) -> datetime | None:
    text = _clean_whitespace(title)
    if not text or "deadline" not in text.casefold():
        return None
    match = re.search(
        r"deadline.{0,24}?(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return _parse_date(match.group(1).replace("-", ".").replace("/", "."))
    match = re.search(r"deadline[-_\s]+(\d{6})\b", text, flags=re.IGNORECASE)
    if match:
        raw = match.group(1)
        return _parse_date(f"{raw[:2]}.{raw[2:4]}.20{raw[4:]}")
    return None


def _title_from_download_filename(filename: str, external_id: str) -> str:
    stem = Path(filename).stem
    title = re.sub(
        rf"^deadline.*?{re.escape(external_id)}[-_\s]*",
        "",
        stem,
        count=1,
        flags=re.IGNORECASE,
    )
    title = title.replace(external_id, "")
    title = re.sub(r"[_-]+", " ", title)
    return _clean_whitespace(title) or stem or f"GIZ tender {external_id}"


def _parse_flat_download_tenders(
    root: Any,
    *,
    page_url: str,
    country: str | None,
    region: str | None,
    page_email: str | None,
    submission_method: str | None,
    exclude_external_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    seen_external_ids: set[str] = set(exclude_external_ids or set())
    for download_node in root.xpath(
        '//div[contains(concat(" ", normalize-space(@class), " "), " download ")]'
    ):
        attachment = _attachment_from_download_node(download_node, page_url=page_url)
        if not attachment:
            continue
        filename = str(attachment.get("filename") or "")
        deadline = _deadline_from_download_title(filename)
        if deadline is None:
            continue
        external_id = _external_id(
            title=filename,
            attachments=[attachment],
            page_url=page_url,
        )
        if external_id.startswith("page-"):
            continue
        if external_id in seen_external_ids:
            continue
        seen_external_ids.add(external_id)
        title = _title_from_download_filename(filename, external_id)
        procurement_category, sector = _category(title)
        payloads.append(
            {
                "source_system": "giz",
                "external_id": external_id,
                "source_url": page_url,
                "title": title,
                "description": title,
                "country": country,
                "region": region,
                "sector": sector,
                "buyer": f"GIZ {country}" if country else "GIZ",
                "procurement_category": procurement_category,
                "procurement_method": None,
                "notice_type": "Tender",
                "project_id": None,
                "publication_date": None,
                "deadline": deadline,
                "attachments": [attachment],
                "source_metadata_json": {
                    "source_page_url": page_url,
                    "country": country,
                    "region": region,
                    "buyer_agency": f"GIZ {country}" if country else "GIZ",
                    "email": page_email,
                    "submission_method": submission_method,
                    "document_access_notes": (
                        "Public GIZ country-office page includes a direct downloadable tender document."
                    ),
                    "document_status_hint": "documents_available",
                    "document_filenames": [filename] if filename else [],
                },
            }
        )
    return payloads


def parse_giz_tender_page(html_text: str | bytes, *, page_url: str) -> list[dict[str, Any]]:
    """Parse public GIZ country-office tender lists from static HTML."""
    root = html.fromstring(html_text)
    country = _first_text(root, "//main//h1") or _first_text(root, "//h1")
    region = _source_region(page_url)
    page_email = _extract_page_email(root)
    page_text = root.text_content() or ""
    submission_method = None
    if "filetransfer.giz.de" in page_text:
        submission_method = "Electronic submission by email and filetransfer.giz.de as specified by GIZ"
    elif re.search(r"\bsubmit(?:ted)? electronically\b|\bvia email\b|\bby emailing\b", page_text, re.IGNORECASE):
        submission_method = "Electronic submission by email as specified by GIZ"

    payloads: list[dict[str, Any]] = []
    for wrapper in root.xpath(
        '//div[contains(concat(" ", normalize-space(@class), " "), " list-item__wrapper ")]'
    ):
        deadline_text = _first_text(
            wrapper,
            './/*[contains(concat(" ", normalize-space(@class), " "), " list-item__meta ")]',
        )
        if not deadline_text or "deadline" not in deadline_text.casefold():
            continue
        title = _title_without_download_text(wrapper)
        if _is_giz_placeholder_title(title):
            continue
        attachments = _extract_attachments(wrapper, page_url=page_url)
        external_id = _stable_external_id(title=title, attachments=attachments)
        if not external_id:
            continue
        procurement_category, sector = _category(title)
        document_access_notes = (
            "Public GIZ country-office page includes direct downloadable tender documents."
            if attachments
            else "Public GIZ country-office page lists the tender; no direct document links were found."
        )
        payloads.append(
            {
                "source_system": "giz",
                "external_id": external_id,
                "source_url": page_url,
                "title": title,
                "description": _description(wrapper),
                "country": country,
                "region": region,
                "sector": sector,
                "buyer": f"GIZ {country}" if country else "GIZ",
                "procurement_category": procurement_category,
                "procurement_method": None,
                "notice_type": "Tender",
                "project_id": None,
                "publication_date": None,
                "deadline": _parse_date(deadline_text),
                "attachments": attachments,
                "source_metadata_json": {
                    "source_page_url": page_url,
                    "country": country,
                    "region": region,
                    "buyer_agency": f"GIZ {country}" if country else "GIZ",
                    "email": page_email,
                    "submission_method": submission_method,
                    "document_access_notes": document_access_notes,
                    "document_status_hint": (
                        "documents_available" if attachments else "no_documents_found"
                    ),
                    "document_filenames": [
                        item.get("filename") for item in attachments if item.get("filename")
                    ],
                },
            }
        )
    payloads.extend(
        _parse_flat_download_tenders(
            root,
            page_url=page_url,
            country=country,
            region=region,
            page_email=page_email,
            submission_method=submission_method,
            exclude_external_ids={str(item["external_id"]) for item in payloads},
        )
    )
    return payloads


def _remove_script_text(root: Any) -> None:
    for node in root.xpath("//script|//style|//noscript"):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)


def _field_values(root: Any) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}

    def add(label: str | None, value: str | None) -> None:
        clean_label = _clean_whitespace(label)
        clean_value = _clean_whitespace(value)
        if not clean_label or not clean_value or clean_label == clean_value:
            return
        fields.setdefault(clean_label, [])
        if clean_value not in fields[clean_label]:
            fields[clean_label].append(clean_value)

    for group in root.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " control-group ")]'):
        label = _first_text(group, './/label[contains(concat(" ", normalize-space(@class), " "), " control-label ")]')
        if not label:
            continue
        value = _first_text(group, './/*[contains(concat(" ", normalize-space(@class), " "), " controls ")]')
        if not value:
            group_text = _node_text(group)
            value = group_text[len(label):].strip() if group_text and group_text.startswith(label) else group_text
        add(label, value)

    for headline in root.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " sub-headline-container ")]'):
        label = _first_text(headline, './/h4|.//span')
        parent = headline.getparent()
        if parent is None:
            continue
        seen = False
        value = None
        for child in parent:
            if child is headline:
                seen = True
                continue
            if not seen:
                continue
            classes = f" {child.get('class') or ''} "
            if " sub-headline-container " in classes:
                break
            value = _node_text(child)
            if value:
                break
        add(label, value)

    return fields


def _first_field(fields: dict[str, list[str]], *labels: str) -> str | None:
    wanted = {label.casefold() for label in labels}
    for label, values in fields.items():
        if label.casefold() in wanted:
            return values[0] if values else None
    return None


def _first_regex(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return _clean_whitespace(match.group(1)) if match else None


def _eproc_project_id(url: str) -> str | None:
    match = GIZ_EPROC_PROJECT_RE.search(urlparse(url).path)
    return match.group(1) if match else None


def _eproc_reference(title: str | None) -> str | None:
    text = _clean_whitespace(title)
    if not text:
        return None
    match = re.match(r"(?P<ref>\d{8,12}[A-Za-z]?)\b", text)
    if match:
        return match.group("ref").upper()
    return None


def _normalize_eproc_geography(*texts: str | None) -> tuple[str | None, str | None]:
    blob = " ".join(text for text in texts if text).casefold()
    country = None
    for canonical, markers in CENTRAL_ASIA_EXPLICIT_MARKERS:
        if any(re.search(rf"\b{re.escape(marker)}\b", blob) for marker in markers):
            country = canonical
            break
    region = None
    if country in CENTRAL_ASIA_COUNTRIES or re.search(r"\bcentral asia\b", blob):
        region = CENTRAL_ASIA_REGION
    return country, region


def _compose_address(fields: dict[str, list[str]]) -> str | None:
    street = _first_field(fields, "Postanschrift", "Address")
    postal = _first_field(fields, "Postleitzahl", "Postal code")
    city = _first_field(fields, "Ort", "Town")
    country = _first_field(fields, "Land", "Country")
    city_line = _clean_whitespace(" ".join(part for part in (postal, city) if part))
    return "; ".join(part for part in (street, city_line, country) if part) or None


def _extract_eproc_procedure_metadata(
    procedure_html: str | bytes,
    *,
    procedure_url: str,
    project_url: str,
    title: str,
) -> dict[str, Any]:
    root = html.fromstring(procedure_html)
    _remove_script_text(root)
    fields = _field_values(root)
    text = _node_text(root) or ""
    email = _first_field(fields, "E-Mail", "Email") or _extract_page_email(root)
    phone = _first_field(fields, "Telefon", "Phone", "Telephone")
    procedure_type = (
        _first_regex(text, r"\bVergabeart:\s*([^:]+?)(?:\s+Status:|\s+Auftraggeber|\s*$)")
        or _first_regex(text, r"\bVerfahrensart\s+([^:]+?)(?:\s+Beschleunigtes|\s+Angaben|\s*$)")
    )
    submission_deadline = (
        _first_field(fields, "Angebotsfrist", "Schlusstermin für den Eingang der Angebote")
        or _first_regex(text, r"(?:Angebotsfrist|Schlusstermin für den Eingang der Angebote)\s+(\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2})?)")
    )
    question_deadline = (
        _first_field(fields, "Frist zur Einreichung von Aufklärungsfragen")
        or _first_regex(text, r"Frist zur Einreichung von Aufklärungsfragen\s+(\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2})?)")
    )
    notice_url = _first_regex(
        text,
        r"(https://ausschreibungen\.giz\.de/Satellite/notice/[A-Za-z0-9]+)",
    )
    submission_method = None
    if notice_url or re.search(r"elektronisch über diese Vergabeplattform", text, re.IGNORECASE):
        submission_method = "Electronic submission through the GIZ e-procurement platform"
    contact_person = _first_field(fields, "Kontaktstelle", "zu Händen von")
    if contact_person and contact_person.casefold() in {"zu händen von", "kontaktstelle"}:
        contact_person = None
    participation = _first_field(fields, "Zusätzliche Angaben")
    if not participation and "Projektbereich" in text:
        participation = "Communication takes place through the project area of the GIZ procurement portal."
    country, region = _normalize_eproc_geography(title, text)
    return {
        "buyer_agency": _first_field(fields, "Offizielle Bezeichnung") or "Deutsche Gesellschaft für Internationale Zusammenarbeit (GIZ) GmbH",
        "contact_person": contact_person,
        "email": email,
        "phone": phone,
        "address": _compose_address(fields),
        "submission_deadline": submission_deadline,
        "question_deadline": question_deadline,
        "submission_method": submission_method,
        "procedure_type": procedure_type,
        "participation_instructions": participation,
        "document_access_notes": "Tender documents are available through the GIZ e-procurement project page.",
        "procedure_information_url": procedure_url,
        "eproc_project_url": project_url,
        "eproc_notice_url": notice_url,
        "country": country,
        "region": region,
    }


def _parse_eproc_listing_page(html_text: str | bytes, *, page_url: str) -> list[dict[str, Any]]:
    root = html.fromstring(html_text)
    rows: list[dict[str, Any]] = []
    for tr in root.xpath("//table[1]//tr[position() > 1]"):
        cols = [_node_text(cell) for cell in tr.xpath("./td")]
        hrefs = tr.xpath('.//a[contains(@href, "projectForwarding.do")]/@href')
        if len(cols) < 5 or not hrefs:
            continue
        publication_text, deadline_text, title, procedure_kind, buyer = cols[:5]
        if not title or _is_giz_placeholder_title(title):
            continue
        if not deadline_text or deadline_text.casefold() == "nv":
            continue
        kind = procedure_kind or ""
        if "vergebener auftrag" in kind.casefold():
            continue
        if "ausschreibung" not in kind.casefold() and "tnw" not in kind.casefold():
            continue
        rows.append(
            {
                "source_system": "giz",
                "source_url": urljoin(page_url, hrefs[0]),
                "title": title,
                "buyer": buyer or "Deutsche Gesellschaft für Internationale Zusammenarbeit (GIZ) GmbH",
                "publication_date": _parse_giz_datetime(publication_text),
                "deadline": _parse_giz_datetime(deadline_text),
                "notice_type": kind,
                "source_metadata_json": {
                    "source_page_url": page_url,
                    "eproc_listing_url": page_url,
                    "eproc_listing_type": kind,
                    "buyer_agency": buyer,
                },
            }
        )
    return rows


def _discover_procedure_information_url(project_html: str | bytes, *, project_url: str) -> str | None:
    root = html.fromstring(project_html)
    for anchor in root.xpath('//a[@href]'):
        label = _node_text(anchor) or ""
        href = anchor.get("href")
        if href and (
            "Verfahrensangaben" in label
            or "Procedure Information" in label
            or "/processdata/" in href
        ):
            return urljoin(project_url, href)
    return None


def _discover_participation_documents_url(project_html: str | bytes, *, project_url: str) -> str | None:
    root = html.fromstring(project_html)
    for anchor in root.xpath("//a[@href]"):
        label = _node_text(anchor) or ""
        href = anchor.get("href")
        if not href:
            continue
        haystack = f"{label} {href}".casefold()
        if (
            "vergabeunterlagen" in haystack
            or "participation documents" in haystack
            or "/documents" in haystack
        ) and "/archive/" not in haystack:
            return urljoin(project_url, href)
    return None


def _extract_eproc_documents_metadata(
    documents_html: str | bytes,
    *,
    documents_url: str,
    project_id: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    root = html.fromstring(documents_html)
    _remove_script_text(root)
    listed_documents: list[dict[str, Any]] = []
    for row in root.xpath("//tr"):
        cells = [_node_text(cell) for cell in row.xpath("./td")]
        if len(cells) < 4:
            continue
        filename, added_at, doc_type, size_text = cells[:4]
        if not filename or filename.casefold() == "dateiname":
            continue
        inferred_type = _clean_whitespace(doc_type) or _document_type_from_name(filename)
        if not inferred_type:
            continue
        listed_documents.append(
            {
                "document_name": filename,
                "document_type": inferred_type,
                "size": size_text,
                "size_bytes": _parse_size_bytes(size_text),
                "added_at": added_at,
                "source_page_url": documents_url,
            }
        )

    archive_url = None
    for anchor in root.xpath("//a[@href]"):
        label = _node_text(anchor) or ""
        href = anchor.get("href")
        if not href:
            continue
        haystack = f"{label} {href}".casefold()
        if "/archive/" in haystack or "alle dokumente als zip" in haystack:
            archive_url = urljoin(documents_url, href)
            break

    if archive_url and _safe_giz_url(archive_url):
        filename = Path(urlparse(archive_url).path).name or f"Vergabeunterlagen_{project_id or 'giz'}.zip"
        archive = {
            "source_document_url": archive_url,
            "source_document_type": "zip",
            "external_file_id": hashlib.sha256(
                f"{archive_url}|{project_id or ''}|participation-documents".encode("utf-8")
            ).hexdigest()[:32],
            "file_size": None,
            "mime_type": "application/zip",
            "filename": filename,
            "source_metadata_json": {
                "source_page_url": documents_url,
                "download_action": "GET",
                "document_bundle": "participation_documents_zip",
                "listed_documents": listed_documents,
            },
        }
        return listed_documents, archive

    if listed_documents:
        access_url = f"{documents_url}#participation-documents"
        access_record = {
            "source_document_url": access_url,
            "source_document_type": "access_required",
            "external_file_id": hashlib.sha256(
                f"{documents_url}|{project_id or ''}|access-required".encode("utf-8")
            ).hexdigest()[:32],
            "file_size": None,
            "mime_type": None,
            "filename": "GIZ participation documents",
            "download_status": "access_required",
            "source_metadata_json": {
                "source_page_url": documents_url,
                "download_action": None,
                "document_bundle": "participation_documents",
                "listed_documents": listed_documents,
                "access_required_reason": "GIZ requires participation or login before public file download links are exposed.",
            },
        }
        return listed_documents, access_record

    return listed_documents, None


class GizTenderSource:
    source_system = "giz"

    def __init__(
        self,
        *,
        source_pages: tuple[str, ...] | list[str] | None = None,
        include_eproc: bool = True,
        eproc_max_pages: int = MAX_GIZ_EPROC_PAGES,
        timeout_seconds: float = 30.0,
        request_delay_seconds: float = 0.25,
        max_retries: int = 2,
        max_download_bytes: int = MAX_DOWNLOAD_BYTES,
    ) -> None:
        pages = tuple(source_pages or DEFAULT_GIZ_TENDER_PAGES)
        self.config = GizSyncConfig(
            source_pages=pages,
            include_eproc=include_eproc,
            eproc_max_pages=max(0, min(MAX_GIZ_EPROC_PAGES, int(eproc_max_pages))),
            timeout_seconds=max(1.0, float(timeout_seconds)),
            request_delay_seconds=max(0.0, float(request_delay_seconds)),
            max_retries=max(0, int(max_retries)),
            max_download_bytes=max(1024, int(max_download_bytes)),
        )

    async def _request(self, client: Any, method: str, url: str, **kwargs: Any) -> Any:
        for attempt in range(self.config.max_retries + 1):
            try:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except Exception:
                if attempt >= self.config.max_retries:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))
        raise RuntimeError("GIZ request failed")

    async def list_opportunities(self) -> list[dict[str, Any]]:
        import httpx

        opportunities: list[dict[str, Any]] = []
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            headers={"User-Agent": GIZ_USER_AGENT},
            follow_redirects=True,
        ) as client:
            for index, page_url in enumerate(self.config.source_pages):
                if index > 0:
                    await asyncio.sleep(self.config.request_delay_seconds)
                if not _safe_giz_url(page_url):
                    logger.warning("giz_source_page_skipped unsafe_url=%s", page_url)
                    continue
                response = await self._request(client, "GET", page_url)
                parsed = parse_giz_tender_page(response.content, page_url=str(response.url))
                logger.info("giz_source_page_parsed url=%s tenders=%s", page_url, len(parsed))
                opportunities.extend(parsed)
            if self.config.include_eproc and self.config.eproc_max_pages > 0:
                eproc = await self._list_eproc_opportunities(client)
                logger.info("giz_eproc_parsed tenders=%s", len(eproc))
                opportunities.extend(eproc)
        deduped: dict[str, dict[str, Any]] = {}
        for opportunity in opportunities:
            external_id = str(opportunity.get("external_id") or "").strip()
            if not external_id or external_id in deduped:
                continue
            deduped[external_id] = opportunity
        return sorted(
            deduped.values(),
            key=lambda item: (
                item.get("region") != CENTRAL_ASIA_REGION,
                item.get("country") not in CENTRAL_ASIA_COUNTRIES,
                str(item.get("deadline") or ""),
                str(item.get("external_id") or ""),
            ),
        )

    async def fetch_detail(self, external_id: str) -> Any:
        return None

    async def _list_eproc_opportunities(self, client: Any) -> list[dict[str, Any]]:
        listing_rows: list[dict[str, Any]] = []
        for page in range(1, self.config.eproc_max_pages + 1):
            if page > 1:
                await asyncio.sleep(self.config.request_delay_seconds)
            page_url = GIZ_EPROC_WELCOME_URL
            if page > 1:
                page_url = (
                    f"{GIZ_EPROC_WELCOME_URL}?method=showTable&fromSearch=1"
                    f"&selectedTablePagePROJECT_RESULT={page}"
                )
            response = await self._request(client, "GET", page_url)
            listing_rows.extend(
                _parse_eproc_listing_page(response.content, page_url=str(response.url))
            )

        enriched: list[dict[str, Any]] = []
        listing_rows.sort(
            key=lambda row: (
                not any(
                    marker in str(row.get("title") or "").casefold()
                    for _, markers in CENTRAL_ASIA_EXPLICIT_MARKERS
                    for marker in markers
                )
                and "central asia" not in str(row.get("title") or "").casefold(),
                str(row.get("deadline") or ""),
            )
        )
        for row in listing_rows:
            await asyncio.sleep(self.config.request_delay_seconds)
            try:
                enriched.append(await self._enrich_eproc_listing_row(client, row))
            except Exception:
                logger.exception(
                    "giz_eproc_detail_failed source_url=%s",
                    row.get("source_url"),
                )
        return enriched

    async def _enrich_eproc_listing_row(
        self,
        client: Any,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        project_response = await self._request(client, "GET", str(row["source_url"]))
        project_url = str(project_response.url)
        project_id = _eproc_project_id(project_url)
        procedure_url = _discover_procedure_information_url(
            project_response.content,
            project_url=project_url,
        )
        procedure_metadata: dict[str, Any] = {}
        if procedure_url:
            procedure_response = await self._request(client, "GET", procedure_url)
            procedure_metadata = _extract_eproc_procedure_metadata(
                procedure_response.content,
                procedure_url=str(procedure_response.url),
                project_url=project_url,
                title=str(row["title"]),
            )
        participation_documents_url = _discover_participation_documents_url(
            project_response.content,
            project_url=project_url,
        )
        listed_documents: list[dict[str, Any]] = []
        archive_attachment: dict[str, Any] | None = None
        if participation_documents_url:
            documents_response = await self._request(client, "GET", participation_documents_url)
            listed_documents, archive_attachment = _extract_eproc_documents_metadata(
                documents_response.content,
                documents_url=str(documents_response.url),
                project_id=project_id,
            )
        procurement_reference = _eproc_reference(str(row["title"]))
        external_id = procurement_reference or project_id
        if not external_id:
            raise ValueError("GIZ e-procurement row has no stable project id")
        country = procedure_metadata.get("country")
        region = procedure_metadata.get("region")
        procurement_category, sector = _category(str(row["title"]))
        metadata = {
            **(row.get("source_metadata_json") or {}),
            **{key: value for key, value in procedure_metadata.items() if value},
            "source_page_url": project_url,
            "eproc_project_id": project_id,
            "procurement_reference": procurement_reference,
            "official_source_url": project_url,
            "participation_documents_url": participation_documents_url,
            "participation_documents": listed_documents,
            "giz_visibility": "visible",
        }
        return {
            "source_system": "giz",
            "external_id": external_id,
            "source_url": project_url,
            "title": row["title"],
            "description": row["title"],
            "country": country,
            "region": region,
            "sector": sector,
            "buyer": procedure_metadata.get("buyer_agency") or row.get("buyer"),
            "procurement_category": procurement_category,
            "procurement_method": procedure_metadata.get("procedure_type"),
            "notice_type": row.get("notice_type") or "Tender",
            "project_id": project_id,
            "publication_date": row.get("publication_date"),
            "deadline": _parse_giz_datetime(procedure_metadata.get("submission_deadline"))
            or row.get("deadline"),
            "attachments": [archive_attachment] if archive_attachment else [],
            "source_metadata_json": metadata,
        }

    async def fetch_contact_metadata(self, *, project_url: str) -> dict[str, Any] | None:
        import httpx

        if not project_url or not _safe_giz_url(project_url):
            return None
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            headers={"User-Agent": GIZ_USER_AGENT},
            follow_redirects=True,
        ) as client:
            project_response = await self._request(client, "GET", project_url)
            procedure_url = _discover_procedure_information_url(
                project_response.content,
                project_url=str(project_response.url),
            )
            if not procedure_url:
                return None
            procedure_response = await self._request(client, "GET", procedure_url)
        return _extract_eproc_procedure_metadata(
            procedure_response.content,
            procedure_url=str(procedure_response.url),
            project_url=str(project_response.url),
            title="",
        )

    async def discover_attachments(
        self,
        normalized_tender: NormalizedTender,
    ) -> list[NormalizedAttachment]:
        metadata = normalized_tender.source_metadata_json or {}
        attachments = metadata.get("attachments")
        if not isinstance(attachments, list):
            attachments = []
        return [
            NormalizedAttachment(
                source_document_url=str(item["source_document_url"]),
                source_document_type=item.get("source_document_type"),
                external_file_id=item.get("external_file_id"),
                file_size=item.get("file_size"),
                mime_type=item.get("mime_type"),
                source_metadata_json=item.get("source_metadata_json"),
            )
            for item in attachments
            if isinstance(item, dict) and item.get("source_document_url")
        ]

    async def discover_documents(
        self,
        normalized_tender: NormalizedTender,
    ):
        attachments = await self.discover_attachments(normalized_tender)
        return canonical_documents_from_attachments(
            source_system=self.source_system,
            attachments=attachments,
            download_status="metadata_only",
        )

    def normalize(self, raw: dict[str, Any]) -> NormalizedTender:
        metadata = dict(raw.get("source_metadata_json") or {})
        attachments = raw.get("attachments") or []
        metadata["attachments"] = attachments
        return NormalizedTender(
            source_system="giz",
            external_id=str(raw["external_id"]),
            source_url=str(raw["source_url"]),
            title=str(raw["title"]),
            description=raw.get("description"),
            budget=0.0,
            currency="EUR",
            country=raw.get("country"),
            region=raw.get("region"),
            sector=raw.get("sector"),
            buyer=raw.get("buyer"),
            procurement_category=raw.get("procurement_category"),
            procurement_method=raw.get("procurement_method"),
            notice_type=raw.get("notice_type") or "Tender",
            project_id=raw.get("project_id"),
            publication_date=raw.get("publication_date"),
            deadline=raw.get("deadline"),
            status=TenderStatus.OPEN,
            category="GIZ",
            source_metadata_json=metadata,
            scrape_status="success",
        )

    async def upsert(self, db: Any, normalized_tender: NormalizedTender) -> tuple[Any, bool]:
        return await upsert_tender(db, normalized_tender)

    async def upsert_attachments(
        self,
        db: Any,
        *,
        tender: Any,
        attachments: list[NormalizedAttachment],
    ) -> tuple[int, int]:
        return await self.upsert_documents(
            db,
            tender=tender,
            documents=canonical_documents_from_attachments(
                source_system="giz",
                attachments=attachments,
                download_status="metadata_only",
            ),
        )

    async def upsert_documents(
        self,
        db: Any,
        *,
        tender: Any,
        documents: list[Any],
    ) -> tuple[int, int]:
        from sqlalchemy import select

        assert_source_scope("giz", tender)
        created = 0
        updated = 0
        for document in documents:
            source_url = str(document.source_document_url).strip()
            if not source_url or not _safe_giz_url(source_url):
                continue
            result = await db.execute(
                select(TenderDocument).where(
                    TenderDocument.tender_id == tender.id,
                    TenderDocument.source_document_url == source_url,
                )
            )
            existing = result.scalar_one_or_none()
            file_type = (
                document.source_document_type
                or document.file_type
                or _extension_from_url(source_url)
                or "document"
            )
            if existing is None:
                db.add(
                    TenderDocument(
                        tender_id=tender.id,
                        file_url=source_url[:500],
                        file_type=file_type,
                        source_document_url=source_url,
                        source_document_type=file_type,
                        download_status=document.download_status or "metadata_only",
                        external_file_id=document.external_file_id,
                        file_size=document.file_size,
                        mime_type=document.mime_type,
                        sha256=document.sha256,
                    )
                )
                created += 1
            else:
                existing.file_url = source_url[:500]
                existing.file_type = file_type
                existing.source_document_type = file_type
                existing.download_status = existing.download_status or document.download_status or "metadata_only"
                existing.external_file_id = document.external_file_id or existing.external_file_id
                existing.file_size = document.file_size or existing.file_size
                existing.mime_type = document.mime_type or existing.mime_type
                existing.sha256 = document.sha256 or existing.sha256
                updated += 1
        return created, updated
