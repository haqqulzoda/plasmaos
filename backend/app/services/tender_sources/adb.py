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
        from sqlalchemy import or_, select

        from app.models.all_models import TenderDocument

        created = 0
        updated = 0
        for attachment in attachments:
            source_url = str(attachment.source_document_url or "").strip()
            external_file_id = str(attachment.external_file_id or "").strip()
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
                        file_size=attachment.file_size,
                        mime_type=attachment.mime_type,
                    )
                )
                created += 1
            else:
                doc.file_type = "pdf"
                doc.source_document_url = source_url
                doc.source_document_type = "notice_pdf"
                doc.download_status = "metadata_only"
                doc.external_file_id = external_file_id
                doc.file_size = attachment.file_size or doc.file_size
                doc.mime_type = attachment.mime_type or doc.mime_type
                updated += 1
        return created, updated
