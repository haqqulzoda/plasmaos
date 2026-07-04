"""ADB RSS tender source connector."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import fitz

logger = logging.getLogger(__name__)

ADB_FEEDS = {
    "invitation_for_bids": {
        "url": "http://feeds.feedburner.com/adb-invitation-for-bids",
        "notice_type": "Invitation for Bids",
    },
}
ADB_USER_AGENT = "PlasmaOS ADBConnector/1.0"
ALLOWED_ADB_HOST_SUFFIXES = ("adb.org",)
MAX_REDIRECTS = 5
MAX_PDF_METADATA_BYTES = 2 * 1024
MAX_CONTACT_PDF_BYTES = 5 * 1024 * 1024
MAX_CONTACT_PDF_PAGES = 8
MAX_CONTACT_TEXT_CHARS = 50_000
EMAIL_RE = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+")
URL_RE = re.compile(r"https?://[^\s),;]+|www\.[^\s),;]+", re.IGNORECASE)
PHONE_RE = re.compile(
    r"\b(?:telephone\s+no\.?|telephone\s+number|telephone|tel\.?|phone)\s*:?\s*"
    r"(\+?[0-9][0-9\s().,;/–-]{5,})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AdbSyncConfig:
    feed_type: str = "invitation_for_bids"
    max_items: int = 50
    timeout_seconds: float = 30.0
    request_delay_seconds: float = 0.25
    max_retries: int = 2
    max_redirects: int = MAX_REDIRECTS


@dataclass(frozen=True)
class AdbAttachmentMetadata:
    node_url: str
    final_url: str
    content_type: str | None
    content_length: int | None
    last_modified: str | None
    final_url_hash: str
    status_code: int | None = None


def _clean_whitespace(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or None


def _clean_label_value(value: Any) -> str | None:
    cleaned = _clean_whitespace(value)
    if not cleaned:
        return None
    cleaned = re.sub(r"^[•\-\u2022]+\s*", "", cleaned)
    cleaned = re.sub(r"^\(?[ivx]+\)\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([:;,])", r"\1", cleaned)
    cleaned = cleaned.strip(" :;,-")
    if not cleaned or not re.search(r"[A-Za-z0-9]", cleaned):
        return None
    return cleaned


def _looks_like_address_line(value: str | None) -> bool:
    text = (value or "").casefold()
    return any(
        marker in text
        for marker in (
            "address",
            "street",
            "building",
            "floor",
            "room",
            "district",
            "khoroo",
            "avenue",
            "sector",
            "city",
            "country",
            "zip",
            "ulaanbaatar",
            "dushanbe",
            "bishkek",
        )
    )


def _parse_category_blob(value: str | None) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in (value or "").split("|"):
        if ":" not in part:
            continue
        key, raw_value = part.split(":", 1)
        normalized_key = key.strip().casefold().replace(" ", "_")
        cleaned_value = _clean_whitespace(raw_value)
        if normalized_key and cleaned_value is not None:
            fields[normalized_key] = cleaned_value
    return fields


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _xml_text(item: ET.Element, tag_name: str) -> str | None:
    element = item.find(tag_name)
    if element is None:
        return None
    return _clean_whitespace(element.text)


def _rss_item_to_payload(
    item: ET.Element,
    *,
    feed_url: str,
    feed_type: str,
    notice_type: str,
) -> dict[str, Any]:
    categories = [
        _clean_whitespace(category.text)
        for category in item.findall("category")
        if _clean_whitespace(category.text)
    ]
    category_fields: dict[str, str] = {}
    for category in categories:
        category_fields.update(_parse_category_blob(category))

    guid = _xml_text(item, "guid")
    link = _xml_text(item, "link")
    title = _xml_text(item, "title")
    if not guid:
        raise ValueError("ADB RSS item guid is required")
    if not link:
        link = f"https://www.adb.org/node/{guid}"

    return {
        "guid": guid,
        "title": title or f"ADB tender notice {guid}",
        "link": link,
        "description": _xml_text(item, "description"),
        "pub_date": _xml_text(item, "pubDate"),
        "categories": categories,
        "category_fields": category_fields,
        "feed_url": feed_url,
        "feed_type": feed_type,
        "notice_type": notice_type,
    }


def parse_adb_rss(
    rss_xml: str | bytes,
    *,
    feed_url: str,
    feed_type: str = "invitation_for_bids",
    notice_type: str = "Invitation for Bids",
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    root = ET.fromstring(rss_xml)
    channel = root.find("channel")
    if channel is None:
        return []
    items = channel.findall("item")
    if max_items is not None:
        items = items[:max_items]
    payloads: list[dict[str, Any]] = []
    for item in items:
        payloads.append(
            _rss_item_to_payload(
                item,
                feed_url=feed_url,
                feed_type=feed_type,
                notice_type=notice_type,
            )
        )
    return payloads


def is_active_adb_notice(raw: dict[str, Any]) -> bool:
    status = (raw.get("category_fields") or {}).get("status")
    return (status or "").strip().casefold() == "active"


def _node_id_from_url(url: str) -> str | None:
    match = re.search(r"/node/(\d+)", urlparse(url).path)
    return match.group(1) if match else None


def _safe_adb_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    hostname = (parsed.hostname or "").casefold()
    return any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in ALLOWED_ADB_HOST_SUFFIXES
    )


def _is_pdf_response(url: str, content_type: str | None) -> bool:
    content_type_value = (content_type or "").split(";", 1)[0].strip().casefold()
    return content_type_value == "application/pdf" or urlparse(url).path.casefold().endswith(".pdf")


def _int_header(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _pdf_text(pdf_bytes: bytes) -> str | None:
    if not pdf_bytes or len(pdf_bytes) > MAX_CONTACT_PDF_BYTES:
        return None
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            pages = []
            for page in document[:MAX_CONTACT_PDF_PAGES]:
                pages.append(page.get_text("text"))
    except Exception:
        logger.exception("adb_pdf_text_extraction_failed")
        return None
    text = "\n".join(pages)
    return text[:MAX_CONTACT_TEXT_CHARS] if text.strip() else None


def _dedupe(items: list[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = _clean_label_value(item)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        values.append(cleaned)
        seen.add(key)
    return values


def _lines(text: str | None) -> list[str]:
    return [
        cleaned
        for line in (text or "").splitlines()
        if (cleaned := _clean_label_value(line))
    ]


def _strip_label(line: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        pattern = rf"^{re.escape(label)}\s*:?\s*(.*)$"
        match = re.match(pattern, line, flags=re.IGNORECASE)
        if not match:
            continue
        return _clean_label_value(match.group(1))
    return None


def _label_value(lines: list[str], labels: tuple[str, ...]) -> str | None:
    for index, line in enumerate(lines):
        value = _strip_label(line, labels)
        if value:
            return value
        if value is None and any(line.casefold() == label.casefold() for label in labels):
            for next_line in lines[index + 1 : index + 4]:
                if not next_line:
                    continue
                return _clean_label_value(next_line)
    return None


def _section_between(
    text: str | None,
    *,
    start_patterns: tuple[str, ...],
    end_patterns: tuple[str, ...],
    max_chars: int = 3_500,
) -> str | None:
    if not text:
        return None
    start_match = None
    for pattern in start_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match and (start_match is None or match.start() < start_match.start()):
            start_match = match
    if start_match is None:
        return None

    section = text[start_match.start() : start_match.start() + max_chars]
    for pattern in end_patterns:
        match = re.search(pattern, section[120:], flags=re.IGNORECASE)
        if match:
            section = section[: 120 + match.start()]
            break
    return section.strip() or None


def _contact_section(text: str | None) -> str | None:
    return _section_between(
        text,
        start_patterns=(
            r"to obtain further information",
            r"bidders should contact",
            r"bidders should\s+contact",
        ),
        end_patterns=(
            r"\n\s*\d+\.\s*to purchase",
            r"\n\s*to purchase",
            r"\n\s*\d+\.\s*to obtain the bidding documents",
            r"\n\s*to obtain the bidding documents",
            r"\n\s*\d+\.\s*deliver your bid",
            r"\n\s*deliver your bid",
            r"\n\s*for bid submission",
        ),
    )


def _purchase_section(text: str | None) -> str | None:
    return _section_between(
        text,
        start_patterns=(r"to purchase", r"to obtain the bidding documents"),
        end_patterns=(
            r"\n\s*\d+\.\s*deliver your bid",
            r"\n\s*deliver your bid",
            r"\n\s*for bid submission",
        ),
        max_chars=2_800,
    )


def _submission_section(text: str | None) -> str | None:
    return _section_between(
        text,
        start_patterns=(r"deliver your bid", r"for bid submission"),
        end_patterns=(r"\n\s*\d+\.\s*bids will be opened", r"\n\s*bids will be opened"),
        max_chars=2_600,
    )


def _emails(*sections: str | None) -> list[str]:
    found: list[str] = []
    for section in sections:
        if section:
            found.extend(EMAIL_RE.findall(section))
    return _dedupe(found)


def _urls(*sections: str | None) -> list[str]:
    found: list[str] = []
    for section in sections:
        if section:
            found.extend(url.rstrip(".") for url in URL_RE.findall(section))
    return _dedupe(found)


def _phone(section: str | None) -> str | None:
    if not section:
        return None
    for match in PHONE_RE.finditer(section):
        value = re.split(r"\b(?:fax|e-?mail|email|website)\b", match.group(1), flags=re.IGNORECASE)[0]
        cleaned = _clean_label_value(value)
        if cleaned:
            return cleaned
    lines = _lines(section)
    return _label_value(
        lines,
        ("Telephone No.", "Telephone number", "Telephone", "Tel", "Phone"),
    )


def _contact_person(section: str | None, purchase: str | None) -> str | None:
    combined_lines = _lines("\n".join(part for part in (section, purchase) if part))
    labeled = _label_value(
        combined_lines,
        ("Attention", "Name of Officer", "Contact Person", "Contact"),
    )
    if labeled:
        return labeled

    combined = "\n".join(part for part in (section, purchase) if part)
    from_match = re.search(
        r"obtained from\s+([^,\n]+(?:,\s*[^\n]+)?)\s*,?\s*email\s*:",
        combined,
        flags=re.IGNORECASE,
    )
    if from_match:
        return _clean_label_value(from_match.group(1))

    for line in combined_lines[:14]:
        if _looks_like_address_line(line):
            continue
        if re.search(r"\b(?:procurement|project|pag|ceo|director|officer|specialist|manager|assistance)\b", line, re.IGNORECASE):
            return line

    email_match = EMAIL_RE.search(combined)
    if email_match:
        before = combined[: email_match.start()]
        for line in reversed(_lines(before)[-5:]):
            if _looks_like_address_line(line):
                continue
            if re.search(r"\b(?:e-?mail|address|telephone|tel|portal|website)\b", line, re.IGNORECASE):
                continue
            if "," in line or re.search(r"\b(?:mr\.|mrs\.|ms\.|director|officer|specialist|manager|assistance)\b", line, re.IGNORECASE):
                return line

    for line in combined_lines[:8]:
        if re.search(r"\b(?:director|officer|specialist|manager|assistance)\b", line, re.IGNORECASE):
            return line
    return None


def _buyer_agency(section: str | None) -> str | None:
    lines = _lines(section)
    labeled = _label_value(
        lines,
        ("Employer", "Purchaser's Office", "Purchaser’s Office", "Purchaser", "Agency"),
    )
    if labeled:
        return labeled
    for line in lines[:10]:
        if _looks_like_address_line(line):
            continue
        if re.search(r"\b(?:ministry|department|project|program|programme|corporation|board|office|unit|agency)\b", line, re.IGNORECASE):
            if not re.search(r"\b(?:attention|director|officer|specialist|manager|telephone|email|address|date|loan|contract|deadline)\b", line, re.IGNORECASE):
                return line
    for line in lines[:10]:
        if _looks_like_address_line(line):
            continue
        parts = [part.strip() for part in line.split(",") if part.strip()]
        if len(parts) >= 3 and re.search(r"\b(?:procurement|specialist|manager|officer)\b", line, re.IGNORECASE):
            return parts[-1]
    return None


def _address(section: str | None) -> str | None:
    lines = _lines(section)
    if not lines:
        return None

    parts: list[str] = []
    for index, line in enumerate(lines):
        value = _strip_label(line, ("Address",))
        if value:
            parts.append(value)
            for next_line in lines[index + 1 : index + 7]:
                if re.search(r"\b(?:telephone|tel|e-?mail|website|to purchase)\b", next_line, re.IGNORECASE):
                    break
                parts.append(next_line)
            return "; ".join(_dedupe(parts)) if parts else None

    label_groups = (
        ("Street Address", "Street address", "Address"),
        ("Floor/Room Number", "Floor/Room number", "Floor/Room No."),
        ("City",),
        ("ZIP code", "ZIP Code", "Postal Code"),
        ("Country",),
    )
    for labels in label_groups:
        value = _label_value(lines, labels)
        if value:
            parts.append(value)
    if parts:
        return "; ".join(_dedupe(parts))

    start_index = None
    for index, line in enumerate(lines):
        if re.match(r"^address\s*:?", line, flags=re.IGNORECASE):
            start_index = index
            break
    if start_index is not None:
        for line in lines[start_index : start_index + 8]:
            if re.search(r"\b(?:telephone|tel|e-?mail|website|to purchase)\b", line, re.IGNORECASE):
                break
            value = _strip_label(line, ("Address",)) or line
            if value:
                parts.append(value)
        return "; ".join(_dedupe(parts)) if parts else None

    stop_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.search(r"\b(?:telephone|tel|e-?mail|email|website)\b", line, re.IGNORECASE)
        ),
        None,
    )
    if stop_index is not None:
        for line in lines[max(0, stop_index - 8) : stop_index]:
            if _looks_like_address_line(line) or re.search(r"\d", line):
                if not re.search(r"\b(?:attention|date|loan|contract|deadline)\b", line, re.IGNORECASE):
                    parts.append(line)
    return "; ".join(_dedupe(parts)) if parts else None



def _submission_method(text: str | None, submission: str | None) -> str | None:
    combined = "\n".join(part for part in (submission, text) if part)
    urls = _urls(combined)
    tenderlink = next((url for url in urls if "tenderlink" in url.casefold()), None)
    if tenderlink:
        return f"TenderLink portal: {tenderlink}"
    procurement_portal = next(
        (url for url in urls if "tender" in url.casefold() or "procure" in url.casefold()),
        None,
    )
    if procurement_portal:
        return f"E-procurement portal: {procurement_portal}"
    if re.search(r"\bsubmit(?:ted)?\s+online|electronically\b", combined, re.IGNORECASE):
        return "Electronic submission as specified in the ADB notice"
    if re.search(r"\bto the address\b", combined, re.IGNORECASE):
        return "Physical submission to the address specified in the ADB notice"
    return None


def _document_access_notes(purchase: str | None, submission: str | None) -> str | None:
    purchase_lines = _lines(purchase)
    if purchase_lines:
        return " ".join(purchase_lines[:4])[:500]
    urls = _urls(submission)
    if urls:
        return f"Open the ADB notice or portal for bidding documents: {urls[0]}"
    return None


def extract_adb_contact_info(text: str | None) -> dict[str, str | None]:
    """Extract explicit contact/submission details from ADB tender notice text."""
    if not text or not text.strip():
        return {}

    contact = _contact_section(text)
    purchase = _purchase_section(text)
    submission = _submission_section(text)
    contact_emails = _emails(contact)
    purchase_emails = _emails(purchase)
    submission_emails = _emails(submission)
    primary_email = (
        contact_emails[:1] or purchase_emails[:1] or submission_emails[:1]
    )
    all_emails = _dedupe([*contact_emails, *purchase_emails, *submission_emails])
    notes = _document_access_notes(purchase, submission)
    extra_emails = [email for email in all_emails if email not in primary_email]
    if extra_emails:
        suffix = f"Additional contact email(s): {'; '.join(extra_emails)}"
        notes = f"{notes}. {suffix}" if notes else suffix

    deadline = parse_deadline_from_text(text)

    return {
        "buyer_agency": _buyer_agency(contact),
        "contact_person": _contact_person(contact, purchase),
        "email": primary_email[0] if primary_email else None,
        "phone": _phone(contact),
        "address": _address(contact),
        "submission_method": _submission_method(text, submission),
        "submission_deadline": deadline.isoformat() if deadline else None,
        "document_access_notes": notes,
    }


def final_url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def attachment_metadata_from_response(
    *,
    node_url: str,
    final_url: str,
    headers: dict[str, str],
    status_code: int | None = None,
) -> AdbAttachmentMetadata | None:
    if not _safe_adb_url(node_url) or not _safe_adb_url(final_url):
        return None
    content_type = headers.get("content-type") or headers.get("Content-Type")
    if not _is_pdf_response(final_url, content_type):
        return None
    return AdbAttachmentMetadata(
        node_url=node_url,
        final_url=final_url,
        content_type=content_type,
        content_length=_int_header(
            headers.get("content-length") or headers.get("Content-Length")
        ),
        last_modified=headers.get("last-modified") or headers.get("Last-Modified"),
        final_url_hash=final_url_hash(final_url),
        status_code=status_code,
    )


def parse_deadline_from_text(text: str | None) -> datetime | None:
    """Best-effort English deadline extraction for future PDF parsing."""
    if not text:
        return None
    patterns = [
        r"(?:deadline\s+for\s+submission\s+of\s+bids|on\s+or\s+before\s+the\s+deadline)\D{0,100}"
        r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})",
        r"(?:deadline|closing date|submission deadline|bids? must be.*?before)\D{0,80}"
        r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})",
        r"(?:deadline|closing date|submission deadline)\D{0,80}"
        r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        parsed = _parse_date(match.group(1))
        if parsed is not None:
            return parsed
    return None


def normalize_adb_notice_payload(raw: dict[str, Any]) -> dict[str, Any]:
    guid = _clean_whitespace(raw.get("guid"))
    if not guid:
        raise ValueError("ADB guid is required")
    fields = raw.get("category_fields") or {}
    node_url = _clean_whitespace(raw.get("link")) or f"https://www.adb.org/node/{guid}"
    project_id = _clean_whitespace(fields.get("project_number"))
    publication_date = _parse_date(fields.get("date")) or _parse_date(raw.get("pub_date"))
    title = _clean_whitespace(raw.get("title")) or f"ADB tender notice {guid}"
    country = _clean_whitespace(fields.get("countries"))
    sector = _clean_whitespace(fields.get("sectors"))
    description_parts = [
        title,
        f"Project Number: {project_id}" if project_id else None,
        f"Countries: {country}" if country else None,
        f"Sectors: {sector}" if sector else None,
    ]
    description = " | ".join(part for part in description_parts if part)

    return {
        "source_system": "adb",
        "external_id": guid,
        "source_url": node_url,
        "title": title,
        "description": description,
        "budget": 0.0,
        "currency": "USD",
        "country": country,
        "region": None,
        "sector": sector,
        "buyer": None,
        "procurement_category": None,
        "procurement_method": None,
        "notice_type": _clean_whitespace(raw.get("notice_type")) or "Invitation for Bids",
        "project_id": project_id,
        "publication_date": publication_date,
        "deadline": None,
        "source_metadata_json": {
            "feed_url": raw.get("feed_url"),
            "feed_type": raw.get("feed_type"),
            "node_url": node_url,
            "rss_categories": raw.get("categories") or [],
            "rss_category_fields": fields,
        },
        "scrape_status": "success",
    }


class AdbTenderSource:
    source_system = "adb"

    def __init__(
        self,
        *,
        feed_type: str = "invitation_for_bids",
        max_items: int = 50,
        timeout_seconds: float = 30.0,
        request_delay_seconds: float = 0.25,
        max_retries: int = 2,
        max_redirects: int = MAX_REDIRECTS,
    ) -> None:
        if feed_type not in ADB_FEEDS:
            raise ValueError(f"Unsupported ADB feed_type: {feed_type}")
        self.config = AdbSyncConfig(
            feed_type=feed_type,
            max_items=max(1, min(int(max_items or 50), 100)),
            timeout_seconds=max(1.0, float(timeout_seconds)),
            request_delay_seconds=max(0.0, float(request_delay_seconds)),
            max_retries=max(0, int(max_retries)),
            max_redirects=max(0, int(max_redirects)),
        )
        self.feed_info = ADB_FEEDS[feed_type]

    async def _request(
        self,
        client: Any,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> Any:
        for attempt in range(self.config.max_retries + 1):
            try:
                return await client.request(
                    method,
                    url,
                    follow_redirects=True,
                    headers=headers,
                )
            except Exception:
                if attempt >= self.config.max_retries:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))
        raise RuntimeError("ADB request failed")

    async def list_opportunities(self) -> list[dict[str, Any]]:
        import httpx

        feed_url = self.feed_info["url"]
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            max_redirects=self.config.max_redirects,
            headers={"User-Agent": ADB_USER_AGENT},
        ) as client:
            response = await self._request(
                client,
                "GET",
                feed_url,
                headers={"Accept": "application/rss+xml, application/xml, text/xml"},
            )
            response.raise_for_status()
        payloads = parse_adb_rss(
            response.content,
            feed_url=feed_url,
            feed_type=self.config.feed_type,
            notice_type=self.feed_info["notice_type"],
            max_items=self.config.max_items,
        )
        logger.info(
            "adb_rss_fetch feed_type=%s fetched=%s",
            self.config.feed_type,
            len(payloads),
        )
        return payloads

    async def fetch_detail(self, external_id: str) -> AdbAttachmentMetadata | None:
        node_url = f"https://www.adb.org/node/{str(external_id).strip()}"
        return await self.resolve_node_redirect(node_url)

    async def resolve_node_redirect(self, node_url: str) -> AdbAttachmentMetadata | None:
        import httpx

        if not _safe_adb_url(node_url):
            return None

        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            max_redirects=self.config.max_redirects,
            headers={"User-Agent": ADB_USER_AGENT},
        ) as client:
            response = None
            try:
                response = await self._request(
                    client,
                    "HEAD",
                    node_url,
                    headers={"Accept": "application/pdf,text/html,*/*"},
                )
                response.raise_for_status()
            except Exception:
                response = await self._request(
                    client,
                    "GET",
                    node_url,
                    headers={
                        "Accept": "application/pdf,text/html,*/*",
                        "Range": f"bytes=0-{MAX_PDF_METADATA_BYTES - 1}",
                    },
                )
                response.raise_for_status()

        final_url = str(response.url)
        return attachment_metadata_from_response(
            node_url=node_url,
            final_url=final_url,
            headers=dict(response.headers),
            status_code=response.status_code,
        )

    async def fetch_notice_pdf_bytes(self, pdf_url: str) -> bytes | None:
        import httpx

        if not _safe_adb_url(pdf_url):
            return None
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            max_redirects=self.config.max_redirects,
            headers={"User-Agent": ADB_USER_AGENT},
        ) as client:
            response = await self._request(
                client,
                "GET",
                pdf_url,
                headers={"Accept": "application/pdf"},
            )
            response.raise_for_status()
        content_type = response.headers.get("content-type")
        if not _is_pdf_response(str(response.url), content_type):
            return None
        pdf_bytes = response.content
        if not pdf_bytes or len(pdf_bytes) > MAX_CONTACT_PDF_BYTES:
            return None
        return pdf_bytes

    async def fetch_contact_metadata(
        self,
        *,
        node_url: str | None = None,
        final_pdf_url: str | None = None,
    ) -> dict[str, Any] | None:
        pdf_url = _clean_whitespace(final_pdf_url)
        attachment: AdbAttachmentMetadata | None = None
        if not pdf_url:
            if not node_url:
                return None
            attachment = await self.resolve_node_redirect(node_url)
            if attachment is None:
                return None
            pdf_url = attachment.final_url

        pdf_bytes = await self.fetch_notice_pdf_bytes(pdf_url)
        text = _pdf_text(pdf_bytes or b"")
        contact_info = extract_adb_contact_info(text)
        safe_contact_info = {
            key: value
            for key, value in contact_info.items()
            if _clean_whitespace(value)
        }
        if not safe_contact_info:
            return None
        return {
            **safe_contact_info,
            "adb_contact_extraction_status": "success",
            "adb_contact_source": "notice_pdf",
            "final_pdf_url": pdf_url,
            "final_pdf_url_hash": (
                attachment.final_url_hash if attachment else final_url_hash(pdf_url)
            ),
        }

    def should_import(self, raw: dict[str, Any]) -> bool:
        return is_active_adb_notice(raw)

    async def discover_attachments(self, normalized_tender: Any) -> list[Any]:
        metadata = normalized_tender.source_metadata_json or {}
        node_url = metadata.get("node_url") or normalized_tender.source_url
        try:
            attachment = await self.resolve_node_redirect(str(node_url))
        except Exception as exc:
            metadata["attachment_discovery_status"] = "failed"
            metadata["attachment_discovery_error_type"] = type(exc).__name__
            logger.warning(
                "adb_attachment_discovery_failed source_system=%s external_id=%s status=failed error_type=%s",
                self.source_system,
                getattr(normalized_tender, "external_id", None),
                type(exc).__name__,
            )
            return []
        if attachment is None:
            metadata["attachment_discovery_status"] = "metadata_only"
            return []
        metadata["attachment_discovery_status"] = "success"
        metadata["final_pdf_url"] = attachment.final_url
        metadata["final_pdf_url_hash"] = attachment.final_url_hash
        metadata["final_pdf_content_type"] = attachment.content_type
        metadata["final_pdf_content_length"] = attachment.content_length
        metadata["final_pdf_last_modified"] = attachment.last_modified
        metadata["final_pdf_status_code"] = attachment.status_code
        try:
            contact_metadata = await self.fetch_contact_metadata(
                final_pdf_url=attachment.final_url,
            )
        except Exception as exc:
            contact_metadata = None
            metadata["adb_contact_extraction_status"] = "failed"
            metadata["adb_contact_extraction_error_type"] = type(exc).__name__
            logger.warning(
                "adb_contact_extraction_failed source_system=%s external_id=%s status=failed error_type=%s",
                self.source_system,
                getattr(normalized_tender, "external_id", None),
                type(exc).__name__,
            )
        if contact_metadata:
            metadata.update(contact_metadata)
        from app.services.tender_sources.base import NormalizedAttachment

        return [
            NormalizedAttachment(
                source_document_url=attachment.final_url,
                source_document_type="notice_pdf",
                external_file_id=attachment.final_url_hash,
                file_size=attachment.content_length,
                mime_type=attachment.content_type,
                source_metadata_json={
                    "node_url": attachment.node_url,
                    "final_url_hash": attachment.final_url_hash,
                    "last_modified": attachment.last_modified,
                    "status_code": attachment.status_code,
                },
            )
        ]

    async def discover_documents(self, normalized_tender: Any) -> list[Any]:
        from app.services.tender_sources.base import canonical_documents_from_attachments

        attachments = await self.discover_attachments(normalized_tender)
        return canonical_documents_from_attachments(
            source_system=self.source_system,
            attachments=attachments,
            download_status="metadata_only",
        )

    def normalize(self, raw: dict[str, Any]) -> Any:
        from app.models.all_models import TenderStatus
        from app.services.tender_sources.base import NormalizedTender

        payload = normalize_adb_notice_payload(raw)
        return NormalizedTender(
            source_system=payload["source_system"],
            external_id=payload["external_id"],
            source_url=payload["source_url"],
            title=payload["title"],
            description=payload["description"],
            budget=payload["budget"],
            currency=payload["currency"],
            country=payload["country"],
            region=payload["region"],
            sector=payload["sector"],
            buyer=payload["buyer"],
            procurement_category=payload["procurement_category"],
            procurement_method=payload["procurement_method"],
            notice_type=payload["notice_type"],
            project_id=payload["project_id"],
            publication_date=payload["publication_date"],
            deadline=payload["deadline"],
            status=TenderStatus.OPEN,
            category="ADB",
            source_metadata_json=payload["source_metadata_json"],
            scrape_status=payload["scrape_status"],
        )

    async def upsert(self, db: Any, normalized_tender: Any) -> tuple[Any, bool]:
        from app.services.tender_sources.base import upsert_tender

        return await upsert_tender(db, normalized_tender)

    async def upsert_attachments(
        self,
        db: Any,
        *,
        tender: Any,
        attachments: list[Any],
    ) -> tuple[int, int]:
        from app.services.tender_sources.base import canonical_documents_from_attachments

        return await self.upsert_documents(
            db,
            tender=tender,
            documents=canonical_documents_from_attachments(
                source_system=self.source_system,
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
        from sqlalchemy import or_, select

        from app.models.all_models import TenderDocument
        from app.services.tender_sources.base import assert_source_scope

        assert_source_scope(self.source_system, tender)
        created = 0
        updated = 0
        for document in documents:
            source_url = str(document.source_document_url or "").strip()
            external_file_id = str(document.external_file_id or "").strip()
            if not source_url or not external_file_id:
                continue
            result = await db.execute(
                select(TenderDocument).where(
                    TenderDocument.tender_id == tender.id,
                    or_(
                        TenderDocument.external_file_id == external_file_id,
                        TenderDocument.source_document_url == source_url,
                    ),
                )
            )
            doc = result.scalar_one_or_none()
            if doc is None:
                db.add(
                    TenderDocument(
                        tender_id=tender.id,
                        file_url=source_url[:500],
                        file_type="pdf",
                        source_document_url=source_url,
                        source_document_type="notice_pdf",
                        download_status="metadata_only",
                        external_file_id=external_file_id,
                        file_size=document.file_size,
                        mime_type=document.mime_type,
                    )
                )
                created += 1
            else:
                doc.file_type = "pdf"
                doc.source_document_url = source_url
                doc.source_document_type = "notice_pdf"
                doc.download_status = "metadata_only"
                doc.external_file_id = external_file_id
                doc.file_size = document.file_size or doc.file_size
                doc.mime_type = document.mime_type or doc.mime_type
                updated += 1
        return created, updated
