"""ADB RSS tender source connector."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import fitz

logger = logging.getLogger(__name__)

ADB_CURRENT_TENDERS_URL = (
    "https://www.adb.org/projects/tenders/"
    "type/advance-notice-1536/type/general-procurement-notice-1526/"
    "type/individual-consulting-1516/type/invitation-bids-1521/"
    "type/invitation-prequalification-1611/type/other-notice-1531/"
    "type/prequalified-applicants-1616/group/goods"
)
ADB_FEEDS = {
    "invitation_for_bids": {
        "url": "https://feeds.feedburner.com/adb-invitation-for-bids",
        "notice_type": "Invitation for Bids",
    },
}
ADB_USER_AGENT = "PlasmaOS ADBConnector/1.0"
ADB_ACTIVE_PROJECTS_URL = "https://www.adb.org/status/active"
ADB_VIEWS_AJAX_URL = "https://www.adb.org/views/ajax?_wrapper_format=drupal_ajax"
ALLOWED_ADB_HOST_SUFFIXES = ("adb.org",)
MAX_REDIRECTS = 5
MAX_PDF_METADATA_BYTES = 2 * 1024
MAX_CONTACT_PDF_BYTES = 5 * 1024 * 1024
MAX_CONTACT_PDF_PAGES = 8
MAX_CONTACT_TEXT_CHARS = 50_000
ADB_FRESHNESS_MAX_AGE_DAYS = 45
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
    max_items: int = 500
    max_pages: int = 25
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


@dataclass(frozen=True)
class AdbProjectTenderView:
    """Public Drupal view metadata emitted by an official ADB project surface."""

    project_id: str
    view_name: str
    view_display_id: str
    view_path: str
    view_dom_id: str
    pager_element: int = 0


@dataclass(frozen=True)
class AdbStatusIndexPage:
    """Discovery metadata from one server-rendered official status-index page."""

    tender_views: tuple[AdbProjectTenderView, ...]
    last_page: int
    ajax_theme: str
    ajax_libraries: str


class _AdbTenderTableParser(HTMLParser):
    """Parse the official server-rendered tender table without CSS coupling."""

    def __init__(
        self,
        *,
        project_id: str | None = None,
        source_kind: str = "official_html",
        listing_url: str = ADB_CURRENT_TENDERS_URL,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.project_id = project_id
        self.source_kind = source_kind
        self.listing_url = listing_url
        self.rows: list[dict[str, Any]] = []
        self.has_next_page = False
        self._in_row = False
        self._in_cell = False
        self._cell_is_header = False
        self._cell_text: list[str] = []
        self._cell_links: list[str] = []
        self._row_cells: list[tuple[bool, str, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.casefold(): value or "" for key, value in attrs}
        normalized = tag.casefold()
        if normalized == "tr":
            self._in_row = True
            self._row_cells = []
        elif normalized in {"td", "th"} and self._in_row:
            self._in_cell = True
            self._cell_is_header = normalized == "th"
            self._cell_text = []
            self._cell_links = []
        elif normalized == "a":
            href = attrs_dict.get("href", "").strip()
            if self._in_cell and href:
                self._cell_links.append(href)
            rel = attrs_dict.get("rel", "").casefold()
            label = (
                attrs_dict.get("aria-label", "")
                or attrs_dict.get("title", "")
                or attrs_dict.get("class", "")
            ).casefold()
            if "next" in rel.split() or "next" in label:
                self.has_next_page = True

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized in {"td", "th"} and self._in_cell:
            text = _clean_whitespace(" ".join(self._cell_text)) or ""
            self._row_cells.append(
                (self._cell_is_header, text, list(self._cell_links))
            )
            self._in_cell = False
        elif normalized == "tr" and self._in_row:
            self._finish_row()
            self._in_row = False

    def handle_data(self, data: str) -> None:
        if self._in_cell and data:
            self._cell_text.append(data)

    def _finish_row(self) -> None:
        if not self._row_cells or all(cell[0] for cell in self._row_cells):
            return
        if len(self._row_cells) < 5:
            return
        title, notice_type, status, posting_date, deadline = self._row_cells[:5]
        links = [link for cell in self._row_cells for link in cell[2]]
        source_url = next(
            (urljoin("https://www.adb.org", link) for link in links if "/node/" in link),
            None,
        )
        external_id = _node_id_from_url(source_url or "")
        if not external_id:
            logger.warning(
                "adb_html_item_rejected stage=parse failure_class=MissingCanonicalId "
                "retryable=false"
            )
            return
        project_match = re.search(r"\b\d{5}-\d{3}\b", title[1])
        self.rows.append(
            {
                "guid": external_id,
                "title": title[1],
                "link": source_url,
                "notice_type": notice_type[1],
                "source_status": status[1] or None,
                "posting_date": posting_date[1] or None,
                "deadline_text": deadline[1] or None,
                "project_id": (
                    project_match.group(0) if project_match else self.project_id
                ),
                "source_kind": self.source_kind,
                "listing_url": self.listing_url,
            }
        )


def parse_adb_tender_html(
    html: str | bytes,
    *,
    project_id: str | None = None,
    source_kind: str = "official_html",
    listing_url: str = ADB_CURRENT_TENDERS_URL,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse official ADB tender rows and whether an explicit next page exists."""
    parser = _AdbTenderTableParser(
        project_id=project_id,
        source_kind=source_kind,
        listing_url=listing_url,
    )
    parser.feed(html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html)
    return parser.rows, parser.has_next_page


def parse_adb_status_index(html: str | bytes) -> AdbStatusIndexPage:
    """Extract public project-tender view metadata from an ADB status index."""
    text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    settings_match = re.search(
        r'<script[^>]+data-drupal-selector=["\']drupal-settings-json["\'][^>]*>'
        r"(.*?)</script>",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not settings_match:
        raise ValueError("ADB status index does not expose Drupal view settings")
    try:
        settings = json.loads(settings_match.group(1))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("ADB status index contains malformed Drupal settings") from exc

    ajax_state = settings.get("ajaxPageState") or {}
    ajax_views = ((settings.get("views") or {}).get("ajaxViews") or {}).values()
    tender_views: list[AdbProjectTenderView] = []
    seen_projects: set[str] = set()
    for view in ajax_views:
        if not isinstance(view, dict) or view.get("view_display_id") != "tenders":
            continue
        project_id = _clean_whitespace(view.get("view_args"))
        if not project_id or not re.fullmatch(r"\d{5}-\d{3}", project_id):
            continue
        if project_id in seen_projects:
            continue
        seen_projects.add(project_id)
        tender_views.append(
            AdbProjectTenderView(
                project_id=project_id,
                view_name=str(view.get("view_name") or "projects"),
                view_display_id="tenders",
                view_path=str(view.get("view_path") or "/taxonomy/term/1367"),
                view_dom_id=str(view.get("view_dom_id") or ""),
                pager_element=int(view.get("pager_element") or 0),
            )
        )
    page_numbers = [
        int(value)
        for value in re.findall(r"(?:[?&]|&amp;)page=(\d+)", text)
    ]
    return AdbStatusIndexPage(
        tender_views=tuple(tender_views),
        last_page=max(page_numbers, default=0),
        ajax_theme=str(ajax_state.get("theme") or "adb_2022"),
        ajax_libraries=str(ajax_state.get("libraries") or ""),
    )


def parse_adb_views_ajax(
    payload: str | bytes | list[dict[str, Any]],
    *,
    project_id: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse an ordinary ADB Drupal Views AJAX response for one project."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            commands = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("ADB Views AJAX returned malformed JSON") from exc
    else:
        commands = payload
    if not isinstance(commands, list):
        raise ValueError("ADB Views AJAX response must be a command list")
    fragments = [
        command.get("data")
        for command in commands
        if isinstance(command, dict)
        and command.get("command") == "insert"
        and isinstance(command.get("data"), str)
    ]
    if not fragments:
        raise ValueError("ADB Views AJAX response contains no tender HTML")
    return parse_adb_tender_html(
        "\n".join(fragments),
        project_id=project_id,
        source_kind="official_views_ajax",
        listing_url=ADB_VIEWS_AJAX_URL,
    )


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
    for fmt in (
        "%Y-%m-%d",
        "%d-%b-%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%B %d, %Y",
        "%d %b %Y %H:%M",
        "%d %B %Y %H:%M",
    ):
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


def adb_source_health(
    *,
    fallback_used: bool,
    truncated: bool,
    newest_published_at: datetime | None,
    now: datetime | None = None,
) -> tuple[str, str, str]:
    """Return independent execution, freshness, and coverage health."""
    if fallback_used:
        return "PASS", "STALE", "PARTIAL"
    coverage = "PARTIAL" if truncated else "COMPLETE"
    if newest_published_at is None:
        return "PASS", "UNKNOWN", coverage
    comparison_time = now or datetime.now(timezone.utc)
    newest = newest_published_at
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    age_days = max(0, (comparison_time.date() - newest.date()).days)
    freshness = "CURRENT" if age_days <= ADB_FRESHNESS_MAX_AGE_DAYS else "STALE"
    return "PASS", freshness, coverage


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
        "source_kind": "legacy_rss",
        "source_status": category_fields.get("status"),
        "posting_date": category_fields.get("date"),
        "deadline_text": None,
        "project_id": category_fields.get("project_number"),
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
    for index, item in enumerate(items):
        try:
            payloads.append(
                _rss_item_to_payload(
                    item,
                    feed_url=feed_url,
                    feed_type=feed_type,
                    notice_type=notice_type,
                )
            )
        except (TypeError, ValueError) as exc:
            logger.warning(
                "adb_rss_item_rejected stage=parse item_index=%s "
                "failure_class=%s retryable=false",
                index,
                type(exc).__name__,
            )
    return payloads


def is_active_adb_notice(raw: dict[str, Any]) -> bool:
    status = raw.get("source_status") or (raw.get("category_fields") or {}).get("status")
    return (status or "").strip().casefold() == "active"


def adb_lifecycle_status(raw: dict[str, Any], *, now: datetime | None = None) -> str:
    """Return OPEN/CLOSED/CANCELLED/UNKNOWN from authoritative evidence."""
    status = _clean_whitespace(
        raw.get("source_status") or (raw.get("category_fields") or {}).get("status")
    )
    normalized_status = (status or "").casefold()
    deadline = _parse_date(_clean_whitespace(raw.get("deadline_text")))
    comparison_time = now or datetime.now(timezone.utc)
    if comparison_time.tzinfo is None:
        comparison_time = comparison_time.replace(tzinfo=timezone.utc)
    else:
        comparison_time = comparison_time.astimezone(timezone.utc)

    if normalized_status in {"cancelled", "canceled"}:
        return "CANCELLED"
    if normalized_status in {"closed", "expired"}:
        return "CLOSED"
    if deadline is not None and deadline < comparison_time:
        return "CLOSED"
    if raw.get("source_kind") == "legacy_rss":
        # The FeedBurner snapshot is stale and therefore cannot establish that
        # an undated legacy notice is still open, even if its cached status says Active.
        return "UNKNOWN"
    if normalized_status in {"active", "open"}:
        return "OPEN"
    if deadline is not None and deadline >= comparison_time:
        return "OPEN"
    return "UNKNOWN"


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
    project_id = _clean_whitespace(raw.get("project_id") or fields.get("project_number"))
    publication_date = (
        _parse_date(_clean_whitespace(raw.get("posting_date")))
        or _parse_date(fields.get("date"))
        or _parse_date(raw.get("pub_date"))
    )
    deadline = _parse_date(_clean_whitespace(raw.get("deadline_text")))
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
    document_candidate_id = hashlib.sha256(
        f"adb:{guid}:notice_pdf:{node_url}".encode("utf-8")
    ).hexdigest()

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
        "deadline": deadline,
        "lifecycle_status": adb_lifecycle_status(raw),
        "source_metadata_json": {
            "source_kind": raw.get("source_kind") or "legacy_rss",
            "source_status": raw.get("source_status") or fields.get("status"),
            "deadline_text": raw.get("deadline_text"),
            "listing_url": raw.get("listing_url"),
            "feed_url": raw.get("feed_url"),
            "feed_type": raw.get("feed_type"),
            "node_url": node_url,
            "adb_document_candidate_id": document_candidate_id,
            "rss_categories": raw.get("categories") or [],
            "rss_category_fields": fields,
        },
        "scrape_status": (
            "success"
            if str(raw.get("source_kind") or "").startswith("official_")
            else "legacy_fallback"
        ),
    }


async def reconcile_unresolved_adb_legacy_rows(
    db: Any,
    *,
    authoritative_ids: set[str],
    now: datetime | None = None,
) -> int:
    """Mark unmatched, undated RSS rows UNKNOWN without deleting history."""
    from sqlalchemy import select

    from app.models.all_models import Tender, TenderStatus

    comparison_time = now or datetime.now(timezone.utc)
    result = await db.execute(
        select(Tender).where(
            Tender.source_system == "adb",
            Tender.status == TenderStatus.OPEN,
            Tender.deadline.is_(None),
        )
    )
    changed = 0
    for tender in result.scalars().all():
        metadata = tender.source_metadata_json or {}
        is_legacy = bool(metadata.get("feed_url")) or metadata.get("source_kind") == "legacy_rss"
        if not is_legacy or tender.external_id in authoritative_ids:
            continue
        tender.status = TenderStatus.UNKNOWN
        tender.scrape_status = "legacy_unresolved"
        tender.last_synced_at = comparison_time
        changed += 1
    if changed:
        logger.info(
            "adb_legacy_reconciled source_system=adb transitioned_to_unknown=%s",
            changed,
        )
    return changed


class AdbTenderSource:
    source_system = "adb"

    def __init__(
        self,
        *,
        feed_type: str = "invitation_for_bids",
        max_items: int = 500,
        max_pages: int = 25,
        timeout_seconds: float = 30.0,
        request_delay_seconds: float = 0.25,
        max_retries: int = 2,
        max_redirects: int = MAX_REDIRECTS,
    ) -> None:
        if feed_type not in ADB_FEEDS:
            raise ValueError(f"Unsupported ADB feed_type: {feed_type}")
        self.config = AdbSyncConfig(
            feed_type=feed_type,
            max_items=max(1, min(int(max_items or 500), 2000)),
            max_pages=max(1, min(int(max_pages or 25), 100)),
            timeout_seconds=max(1.0, float(timeout_seconds)),
            request_delay_seconds=max(0.0, float(request_delay_seconds)),
            max_retries=max(0, int(max_retries)),
            max_redirects=max(0, int(max_redirects)),
        )
        self.feed_info = ADB_FEEDS[feed_type]
        self.fallback_used = False
        self.primary_failure_class: str | None = None
        self.primary_failure_retryable: bool | None = None
        self.last_truncated = False
        self.last_pages_fetched = 0
        self.last_duplicate_count = 0
        self.source_newest_published_at: datetime | None = None
        self.source_oldest_published_at: datetime | None = None
        self.execution_health = "NOT_RUN"
        self.freshness_health = "UNKNOWN"
        self.coverage_health = "NONE"
        self.http_request_count = 0
        self.http_retry_count = 0
        self.http_failure_count = 0

    @staticmethod
    def _listing_page_url(page: int) -> str:
        parsed = urlparse(ADB_CURRENT_TENDERS_URL)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if page:
            query["page"] = str(page)
        return urlunparse(parsed._replace(query=urlencode(query)))

    async def _request(
        self,
        client: Any,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> Any:
        from app.services.tender_sources.diagnostics import (
            connector_failure_details,
            retry_after_seconds,
        )

        for attempt in range(self.config.max_retries + 1):
            try:
                self.http_request_count += 1
                response = await client.request(
                    method,
                    url,
                    follow_redirects=True,
                    headers=headers,
                    data=data,
                )
                response.raise_for_status()
                return response
            except Exception as exc:
                self.http_failure_count += 1
                details = connector_failure_details(exc)
                if attempt >= self.config.max_retries or not details.retryable:
                    raise
                delay = retry_after_seconds(exc, attempt=attempt)
                self.http_retry_count += 1
                logger.warning(
                    "adb_request_retry stage=network attempt=%s failure_class=%s "
                    "http_status=%s retryable=true delay_seconds=%.2f",
                    attempt + 1,
                    details.failure_class,
                    details.http_status,
                    delay,
                )
                await asyncio.sleep(delay)
        raise RuntimeError("ADB request failed")

    async def fetch_project_tender_rows(
        self,
        client: Any,
        *,
        view: AdbProjectTenderView,
        ajax_theme: str,
        ajax_libraries: str,
        page: int = 0,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Call the same public per-project Drupal view used by ADB's frontend."""
        form_data = {
            "view_name": view.view_name,
            "view_display_id": view.view_display_id,
            "view_args": view.project_id,
            "view_path": view.view_path,
            "view_dom_id": view.view_dom_id,
            "pager_element": str(view.pager_element),
            "page": str(max(0, int(page))),
            "_drupal_ajax": "1",
            "ajax_page_state[theme]": ajax_theme,
            "ajax_page_state[theme_token]": "",
            "ajax_page_state[libraries]": ajax_libraries,
        }
        response = await self._request(
            client,
            "POST",
            ADB_VIEWS_AJAX_URL,
            headers={
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": ADB_ACTIVE_PROJECTS_URL,
            },
            data=form_data,
        )
        return parse_adb_views_ajax(response.content, project_id=view.project_id)

    async def list_opportunities(self) -> list[dict[str, Any]]:
        import httpx

        self.fallback_used = False
        self.primary_failure_class = None
        self.primary_failure_retryable = None
        self.last_truncated = False
        self.last_pages_fetched = 0
        self.last_duplicate_count = 0
        self.execution_health = "FAIL"
        self.freshness_health = "UNKNOWN"
        self.coverage_health = "NONE"
        primary_rows: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            max_redirects=self.config.max_redirects,
            headers={"User-Agent": ADB_USER_AGENT},
        ) as client:
            try:
                for page in range(self.config.max_pages):
                    response = await self._request(
                        client,
                        "GET",
                        self._listing_page_url(page),
                        headers={"Accept": "text/html,application/xhtml+xml"},
                    )
                    rows, has_next = parse_adb_tender_html(response.content)
                    self.last_pages_fetched += 1
                    new_on_page = 0
                    for row in rows:
                        if row.get("notice_type", "").casefold() != "invitation for bids":
                            continue
                        external_id = str(row.get("guid") or "").strip()
                        if external_id in seen_ids:
                            self.last_duplicate_count += 1
                            continue
                        seen_ids.add(external_id)
                        primary_rows.append(row)
                        new_on_page += 1
                        if len(primary_rows) >= self.config.max_items:
                            self.last_truncated = has_next or new_on_page < len(rows)
                            break
                    if len(primary_rows) >= self.config.max_items:
                        break
                    if not has_next:
                        break
                    if page + 1 < self.config.max_pages:
                        await asyncio.sleep(self.config.request_delay_seconds)
                else:
                    self.last_truncated = True
                if not primary_rows:
                    raise ValueError("Official ADB tender listing returned no parseable rows")
            except Exception as exc:
                from app.services.tender_sources.diagnostics import connector_failure_details

                failure = connector_failure_details(exc)
                self.primary_failure_class = failure.failure_class
                self.primary_failure_retryable = failure.retryable
                self.fallback_used = True
                logger.warning(
                    "adb_primary_source_unavailable stage=listing failure_class=%s "
                    "fallback_used=true",
                    self.primary_failure_class,
                )
                feed_url = self.feed_info["url"]
                response = await self._request(
                    client,
                    "GET",
                    feed_url,
                    headers={"Accept": "application/rss+xml, application/xml, text/xml"},
                )
                primary_rows = parse_adb_rss(
                    response.content,
                    feed_url=feed_url,
                    feed_type=self.config.feed_type,
                    notice_type=self.feed_info["notice_type"],
                    max_items=self.config.max_items,
                )

        publication_dates = [
            parsed
            for parsed in (
                _parse_date(_clean_whitespace(row.get("posting_date")))
                or _parse_date((row.get("category_fields") or {}).get("date"))
                for row in primary_rows
            )
            if parsed is not None
        ]
        self.source_newest_published_at = max(publication_dates, default=None)
        self.source_oldest_published_at = min(publication_dates, default=None)
        (
            self.execution_health,
            self.freshness_health,
            self.coverage_health,
        ) = adb_source_health(
            fallback_used=self.fallback_used,
            truncated=self.last_truncated,
            newest_published_at=self.source_newest_published_at,
        )
        logger.info(
            "adb_listing_fetch feed_type=%s fetched=%s fallback_used=%s "
            "newest_source_publication_at=%s",
            self.config.feed_type,
            len(primary_rows),
            str(self.fallback_used).lower(),
            self.source_newest_published_at,
        )
        return primary_rows

    async def fetch_detail(self, external_id: str) -> AdbAttachmentMetadata | None:
        node_url = f"https://www.adb.org/node/{str(external_id).strip()}"
        return await self.resolve_node_redirect(node_url)

    async def resolve_node_redirect(self, node_url: str, *, client: Any | None = None) -> AdbAttachmentMetadata | None:
        import httpx

        if not _safe_adb_url(node_url):
            return None

        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                max_redirects=self.config.max_redirects,
                headers={"User-Agent": ADB_USER_AGENT},
            )
        try:
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
        finally:
            if owns_client:
                await client.aclose()

        final_url = str(response.url)
        return attachment_metadata_from_response(
            node_url=node_url,
            final_url=final_url,
            headers=dict(response.headers),
            status_code=response.status_code,
        )

    async def fetch_notice_pdf_bytes(self, pdf_url: str, *, client: Any | None = None) -> bytes | None:
        import httpx

        if not _safe_adb_url(pdf_url):
            return None
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                max_redirects=self.config.max_redirects,
                headers={"User-Agent": ADB_USER_AGENT},
            )
        try:
            response = await self._request(
                client,
                "GET",
                pdf_url,
                headers={"Accept": "application/pdf"},
            )
            response.raise_for_status()
        finally:
            if owns_client:
                await client.aclose()
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
        client: Any | None = None,
    ) -> dict[str, Any] | None:
        pdf_url = _clean_whitespace(final_pdf_url)
        attachment: AdbAttachmentMetadata | None = None
        if not pdf_url:
            if not node_url:
                return None
            attachment = await self.resolve_node_redirect(node_url, client=client)
            if attachment is None:
                return None
            pdf_url = attachment.final_url

        pdf_bytes = await self.fetch_notice_pdf_bytes(pdf_url, client=client)
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
        return bool(str(raw.get("guid") or "").strip())

    def skip_reason(self, raw: dict[str, Any]) -> str | None:
        return None if self.should_import(raw) else "missing_canonical_id"

    async def discover_attachments(self, normalized_tender: Any) -> list[Any]:
        metadata = normalized_tender.source_metadata_json or {}
        node_url = str(metadata.get("node_url") or normalized_tender.source_url).strip()
        if not _safe_adb_url(node_url):
            return []
        candidate_id = str(metadata.get("adb_document_candidate_id") or "").strip()
        if not candidate_id:
            candidate_id = hashlib.sha256(
                f"adb:{normalized_tender.external_id}:notice_pdf:{node_url}".encode("utf-8")
            ).hexdigest()
            metadata["adb_document_candidate_id"] = candidate_id
        metadata["attachment_discovery_status"] = "metadata_only"
        from app.services.tender_sources.base import NormalizedAttachment

        return [
            NormalizedAttachment(
                source_document_url=node_url,
                source_document_type="notice_pdf",
                external_file_id=candidate_id,
                source_metadata_json={"node_url": node_url, "candidate_id": candidate_id},
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
        lifecycle_status = TenderStatus(payload["lifecycle_status"])
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
            status=lifecycle_status,
            category="ADB",
            source_metadata_json=payload["source_metadata_json"],
            scrape_status=payload["scrape_status"],
            preserve_source_metadata_keys=(
                "buyer_agency", "contact_person", "email", "phone", "address",
                "submission_method", "submission_instructions",
                "adb_contact_extraction_status", "adb_contact_source",
                "adb_contact_document_external_file_id",
                "adb_contact_evidence_url_hash", "adb_contact_enriched_at",
                "final_pdf_url", "final_pdf_url_hash",
            ),
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
        from app.services.tender_sources.base import persist_document_descriptors

        result = await persist_document_descriptors(
            db, source_system=self.source_system, tender=tender,
            documents=documents, url_validator=_safe_adb_url,
            default_status="metadata_only",
        )
        return result.created_count, result.updated_count
