"""EBRD ECEPP public procurement notice connector."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from lxml import html
from sqlalchemy import select

from app.core.geography import CENTRAL_ASIA_COUNTRIES, CENTRAL_ASIA_REGION
from app.models.all_models import TenderDocument, TenderStatus
from app.services.tender_sources.base import (
    CanonicalDocument,
    NormalizedTender,
    assert_source_scope,
    upsert_tender,
)

logger = logging.getLogger(__name__)

EBRD_BASE_URL = "https://ecepp.ebrd.com"
EBRD_NOTICE_SEARCH_URL = f"{EBRD_BASE_URL}/delta/noticeSearchResults.html"
EBRD_USER_AGENT = "PlasmaOS EBRDConnector/1.0"
EBRD_ALLOWED_HOSTS = {"ecepp.ebrd.com"}
ACTIONABLE_NOTICE_PREFIXES = (
    "invitation for tenders",
    "invitation for prequalification",
    "invitation for expression",
    "request for proposals",
)
EXCLUDED_NOTICE_TYPES = {"contract award notice", "addendum notice"}
CENTRAL_ASIA_ALIASES: dict[str, str] = {
    "kyrgyz republic": "Kyrgyzstan",
}


@dataclass(frozen=True)
class EbrdSyncConfig:
    max_items: int = 50
    detail_items: int = 25
    active_only: bool = True
    timeout_seconds: float = 15.0
    request_delay_seconds: float = 0.25
    max_retries: int = 0
    allow_bootstrap_fallback: bool = True


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


EBRD_BOOTSTRAP_FALLBACK_ROWS: tuple[dict[str, Any], ...] = (
    {
        "source_system": "ebrd",
        "external_id": "44054880",
        "source_url": f"{EBRD_BASE_URL}/delta/viewNotice.html?displayNoticeId=44055079",
        "title": "Serbia: RC Duboko Sanitation, remediation, reclamation and closure and stabilization of utilized landfill body",
        "description": "RC Duboko Sanitation, remediation, reclamation and closure and stabilization of utilized landfill body",
        "country": "Serbia",
        "region": None,
        "sector": "Municipal and Environmental Infrastructure",
        "buyer": "Republic of Serbia",
        "procurement_category": "Works",
        "procurement_method": "Open Tender Two Stage",
        "notice_type": "Invitation For Tenders Two Stage",
        "project_id": "52642",
        "project_name": "Serbian Solid Waste Programme",
        "publication_date": _dt(2026, 7, 3, 6, 13),
        "deadline": _dt(2026, 8, 17, 10, 0),
        "state": "Open",
        "source_metadata_json": {
            "official_source_url": f"{EBRD_BASE_URL}/delta/viewNotice.html?displayNoticeId=44055079",
            "document_access_url": f"{EBRD_BASE_URL}/respond/72U482A786",
            "document_status_hint": "access_required",
            "participation_instructions": (
                "Participation documents require ECEPP registration and expressing interest; "
                "PlasmaOS does not automate ECEPP login or download restricted documents."
            ),
            "document_access_notes": (
                "Participation documents require ECEPP registration and expressing interest; "
                "PlasmaOS does not automate ECEPP login or download restricted documents."
            ),
        },
    },
    {
        "source_system": "ebrd",
        "external_id": "45514355",
        "source_url": f"{EBRD_BASE_URL}/delta/viewNotice.html?displayNoticeId=45514355",
        "title": "Kyrgyz Republic: Kyrgyzstan Climate Resilience Water Supply Project",
        "description": "Kyrgyzstan Climate Resilience Water Supply Project",
        "country": "Kyrgyzstan",
        "region": CENTRAL_ASIA_REGION,
        "sector": "Natural Resources",
        "buyer": "State Water Resources Agency (SWRA)",
        "procurement_category": None,
        "procurement_method": None,
        "notice_type": "General Procurement Notice",
        "project_id": None,
        "project_name": "Kyrgyzstan Climate Resilience Water Supply Project",
        "publication_date": _dt(2026, 7, 4, 8, 0),
        "deadline": None,
        "state": "Information Only",
        "source_metadata_json": {
            "official_source_url": f"{EBRD_BASE_URL}/delta/viewNotice.html?displayNoticeId=45514355",
            "document_status_hint": "no_documents_found",
            "document_access_notes": (
                "General Procurement Notice is for information only; no participation documents "
                "were found on the public notice."
            ),
        },
    },
    {
        "source_system": "ebrd",
        "external_id": "45376134",
        "source_url": f"{EBRD_BASE_URL}/delta/viewNotice.html?displayNoticeId=45376255",
        "title": "Tajikistan: Water network and installation water meters",
        "description": "Water network and installation water meters",
        "country": "Tajikistan",
        "region": CENTRAL_ASIA_REGION,
        "sector": "Infra Eurasia",
        "buyer": "The Republic of Tajikistan",
        "procurement_category": "Works",
        "procurement_method": "Open Tender Single Stage",
        "notice_type": "Invitation For Tenders Single",
        "project_id": "55400",
        "project_name": "Dushanbe Water Supply",
        "publication_date": _dt(2026, 7, 3, 6, 13),
        "deadline": _dt(2026, 8, 14, 11, 0),
        "state": "Open",
        "source_metadata_json": {
            "official_source_url": f"{EBRD_BASE_URL}/delta/viewNotice.html?displayNoticeId=45376255",
            "document_status_hint": "no_documents_found",
            "document_access_notes": "Open the ECEPP source notice for document access instructions.",
        },
    },
)


def _clean_whitespace(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or None


def _bootstrap_fallback_rows(max_items: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in EBRD_BOOTSTRAP_FALLBACK_ROWS[:max_items]:
        row = {**item}
        metadata = dict(item.get("source_metadata_json") or {})
        metadata.update(
            {
                "ebrd_bootstrap_fallback": True,
                "ebrd_bootstrap_snapshot_date": "2026-07-04",
                "ebrd_bootstrap_reason": "Live ECEPP listing fetch was unavailable from the runtime environment.",
                "source_terms_note": (
                    "ECEPP Terms and Conditions restrict exporting or extracting BiP data "
                    "into other databases; connector is public-page metadata only."
                ),
            }
        )
        row["source_metadata_json"] = metadata
        rows.append(row)
    return rows


def _node_text(node: Any) -> str | None:
    return _clean_whitespace(node.text_content() if node is not None else None)


def _safe_ebrd_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").casefold() in EBRD_ALLOWED_HOSTS


def _parse_uk_datetime(value: Any) -> datetime | None:
    text = _clean_whitespace(value)
    if not text or text.casefold() in {"n/a", "na"}:
        return None
    text = re.sub(r"UK\s*Time", "", text, flags=re.IGNORECASE).strip()
    for fmt in ("%Y%m%d%H%M", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _listing_metadata(value: str | None) -> dict[str, str]:
    text = _clean_whitespace(value)
    if not text or not text.startswith("[") or not text.endswith("]"):
        return {}
    parts = [part.strip() for part in text[1:-1].split(",")]
    if len(parts) < 10:
        return {}
    ecepp_index = next(
        (
            index
            for index in range(3, len(parts) - 4)
            if re.fullmatch(r"\d{5,}", parts[index] or "")
        ),
        None,
    )
    if ecepp_index is None:
        return {}
    return {
        "project_name": parts[0],
        "project_id": parts[1],
        "country": parts[2],
        "title": ", ".join(parts[3:ecepp_index]).strip(),
        "ecepp_id": parts[ecepp_index],
        "procurement_category": parts[ecepp_index + 1],
        "procurement_method": parts[ecepp_index + 2],
        "buyer": ", ".join(parts[ecepp_index + 3 : -2]).strip(),
        "sector": parts[-2],
        "notice_type": parts[-1],
    }


def _normalize_country(value: str | None) -> str | None:
    country = _clean_whitespace(value)
    if not country:
        return None
    return CENTRAL_ASIA_ALIASES.get(country.casefold(), country)


def _region_for_country(country: str | None) -> str | None:
    if country in CENTRAL_ASIA_COUNTRIES:
        return CENTRAL_ASIA_REGION
    return None


def _field_values(root: Any) -> dict[str, str]:
    fields: dict[str, str] = {}
    for row in root.xpath('//table[@id="oppoverviewtable"]//tr'):
        cells = row.xpath("./td")
        if len(cells) < 2:
            continue
        label = _node_text(cells[0])
        value = _node_text(cells[1])
        if label and value:
            fields[label.rstrip(":")] = value
    return fields


def _detail_body_text(root: Any) -> str | None:
    parts = [
        _node_text(node)
        for node in root.xpath(
            '//*[contains(concat(" ", normalize-space(@class), " "), " notice_content ")]'
            '|//*[@id="noticepreviewtable"]/following-sibling::*'
        )
    ]
    values = [part for part in parts if part]
    if values:
        return _clean_whitespace(" ".join(values))
    body = root.xpath("//body")
    return _node_text(body[0]) if body else None


def _response_url(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"https://ecepp\.ebrd\.com/respond/[A-Za-z0-9]+", text)
    return match.group(0) if match else None


def _extract_client_address(text: str | None) -> str | None:
    if not text:
        return None
    marker = re.search(r"Client Address:\s*(.+)$", text, flags=re.IGNORECASE | re.DOTALL)
    if not marker:
        return None
    value = marker.group(1)
    value = re.split(r"\b(?:Access Opportunity|Back to Results)\b", value, maxsplit=1)[0]
    return _clean_whitespace(value)


def _extract_email(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+", text)
    return match.group(0) if match else None


def _extract_phone(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(
        r"(?:tel\.?|telephone|phone)\s*:?\s*(\+?[0-9][0-9\s()./\-]{5,})",
        text,
        flags=re.IGNORECASE,
    )
    return _clean_whitespace(match.group(1)) if match else None


def _extract_contact_person(address: str | None) -> str | None:
    if not address:
        return None
    first = re.split(r";|\b[A-Z][A-Z\s]{4,}\b|Tel\.?|Email:", address, maxsplit=1)
    return _clean_whitespace(first[0]) if first else None


def _access_instructions(*, response_url: str | None, notice_type: str | None) -> str:
    base = (
        "Participation documents require ECEPP registration and expressing interest "
        "in the opportunity; PlasmaOS does not automate ECEPP login or download "
        "restricted documents."
    )
    if response_url:
        return f"{base} Use the ECEPP response link from the public notice: {response_url}"
    if notice_type and notice_type.casefold() == "general procurement notice":
        return "General Procurement Notice is for information only; no participation documents were found on the public notice."
    return base


def parse_ebrd_search_page(html_text: str | bytes, *, page_url: str = EBRD_NOTICE_SEARCH_URL) -> list[dict[str, Any]]:
    """Parse public ECEPP notice-search result rows."""
    root = html.fromstring(html_text)
    rows: list[dict[str, Any]] = []
    for tr in root.xpath("//tbody/tr"):
        cells = tr.xpath("./td")
        if len(cells) < 6:
            continue
        link = tr.xpath('.//a[contains(@href, "viewNotice.html")]/@href')
        title = _node_text(cells[0])
        notice_type = _node_text(cells[1])
        exercise_title = _node_text(cells[2]) or title
        metadata = _listing_metadata(_node_text(cells[9]) if len(cells) > 9 else None)
        publication_date = _parse_uk_datetime(_node_text(cells[7]) if len(cells) > 7 else None) or _parse_uk_datetime(_node_text(cells[3]))
        closing_date = _parse_uk_datetime(_node_text(cells[8]) if len(cells) > 8 else None) or _parse_uk_datetime(_node_text(cells[4]))
        state = _node_text(cells[5])
        if not title or not link:
            continue
        source_url = urljoin(page_url, link[0])
        parsed = urlparse(source_url)
        query = parsed.query
        display_match = re.search(r"(?:^|&)displayNoticeId=([^&]+)", query)
        access_match = re.search(r"(?:^|&)accessCode=([^&]+)", query)
        external_id = metadata.get("ecepp_id") or (
            display_match.group(1)
            if display_match
            else access_match.group(1) if access_match else None
        )
        if not external_id or not _safe_ebrd_url(source_url):
            continue
        country = _normalize_country(metadata.get("country") or (title.split(":", 1)[0] if ":" in title else None))
        rows.append(
            {
                "source_system": "ebrd",
                "external_id": external_id,
                "source_url": source_url,
                "title": title,
                "description": exercise_title,
                "country": country,
                "region": _region_for_country(country),
                "sector": metadata.get("sector"),
                "buyer": metadata.get("buyer"),
                "procurement_category": metadata.get("procurement_category"),
                "procurement_method": metadata.get("procurement_method"),
                "notice_type": metadata.get("notice_type") or notice_type,
                "project_id": metadata.get("project_id"),
                "project_name": metadata.get("project_name"),
                "publication_date": publication_date,
                "deadline": closing_date,
                "state": state,
                "source_metadata_json": {
                    "official_source_url": source_url,
                    "listing_url": page_url,
                    "listing_display_notice_id": display_match.group(1) if display_match else None,
                    "listing_metadata": metadata,
                    "listing_state": state,
                    "listing_notice_type": metadata.get("notice_type") or notice_type,
                    "listing_publication_date": publication_date.isoformat() if publication_date else None,
                    "listing_closing_date": closing_date.isoformat() if closing_date else None,
                },
            }
        )
    return rows


def parse_ebrd_notice_detail(html_text: str | bytes, *, source_url: str) -> dict[str, Any]:
    """Parse public ECEPP notice-detail metadata."""
    root = html.fromstring(html_text)
    fields = _field_values(root)
    heading = _node_text(root.xpath("//h1")[0]) if root.xpath("//h1") else None
    notice_type = _node_text(root.xpath("//h2")[0]) if root.xpath("//h2") else None
    body_text = _detail_body_text(root)
    response_url = _response_url(body_text)
    client_address = _extract_client_address(body_text)
    country = _normalize_country(fields.get("Country"))
    query = urlparse(source_url).query
    display_match = re.search(r"(?:^|&)displayNoticeId=([^&]+)", query)
    access_match = re.search(r"(?:^|&)accessCode=([^&]+)", query)
    fallback_external_id = (
        display_match.group(1)
        if display_match
        else access_match.group(1) if access_match else query
    )
    return {
        "source_system": "ebrd",
        "external_id": fields.get("ECEPP ID") or fallback_external_id,
        "source_url": source_url,
        "title": heading or fields.get("Procurement Exercise Name") or "EBRD procurement notice",
        "description": fields.get("Procurement Exercise Description") or body_text,
        "country": country,
        "region": _region_for_country(country),
        "sector": fields.get("Business Sector"),
        "buyer": fields.get("Client Name"),
        "procurement_category": fields.get("Type of Procurement"),
        "procurement_method": fields.get("Procurement Method"),
        "notice_type": fields.get("Notice Type") or notice_type,
        "project_id": fields.get("EBRD Project ID"),
        "project_name": fields.get("Project Name"),
        "publication_date": _parse_uk_datetime(fields.get("Publication Date")),
        "deadline": _parse_uk_datetime(fields.get("Closing Date")),
        "response_url": response_url,
        "access_required": bool(response_url),
        "contact_person": _extract_contact_person(client_address),
        "email": _extract_email(client_address or body_text),
        "phone": _extract_phone(client_address or body_text),
        "address": client_address,
        "source_metadata_json": {
            "official_source_url": source_url,
            "notice_fields": fields,
            "project_name": fields.get("Project Name"),
            "buyer_agency": fields.get("Client Name"),
            "contact_person": _extract_contact_person(client_address),
            "email": _extract_email(client_address or body_text),
            "phone": _extract_phone(client_address or body_text),
            "address": client_address,
            "submission_method": "Electronic submission through ECEPP where the notice requires a response.",
            "procedure_type": fields.get("Procurement Method"),
            "participation_instructions": _access_instructions(
                response_url=response_url,
                notice_type=fields.get("Notice Type") or notice_type,
            ),
            "document_access_notes": _access_instructions(
                response_url=response_url,
                notice_type=fields.get("Notice Type") or notice_type,
            ),
            "document_access_url": response_url,
            "document_status_hint": "access_required" if response_url else "no_documents_found",
            "source_terms_note": (
                "ECEPP Terms and Conditions restrict exporting or extracting BiP data "
                "into other databases; connector is public-page metadata only."
            ),
        },
    }


def _is_actionable(raw: dict[str, Any], *, active_only: bool = True) -> bool:
    notice_type = (_clean_whitespace(raw.get("notice_type")) or "").casefold()
    if notice_type in EXCLUDED_NOTICE_TYPES:
        return False
    if notice_type == "general procurement notice":
        return True
    if not notice_type.startswith(ACTIONABLE_NOTICE_PREFIXES):
        return False
    if not active_only:
        return True
    state = (_clean_whitespace(raw.get("state")) or "").casefold()
    if state and state != "open":
        return False
    deadline = raw.get("deadline")
    if isinstance(deadline, datetime):
        comparable = deadline if deadline.tzinfo else deadline.replace(tzinfo=timezone.utc)
        return comparable >= datetime.now(timezone.utc)
    return True


class EbrdTenderSource:
    source_system = "ebrd"

    def __init__(
        self,
        *,
        max_items: int = 50,
        detail_items: int = 25,
        active_only: bool = True,
        timeout_seconds: float = 15.0,
        request_delay_seconds: float = 0.25,
        max_retries: int = 0,
        allow_bootstrap_fallback: bool = True,
    ) -> None:
        self.config = EbrdSyncConfig(
            max_items=max(1, min(int(max_items or 50), 200)),
            detail_items=max(0, min(int(detail_items or 0), int(max_items or 50))),
            active_only=active_only,
            timeout_seconds=max(1.0, float(timeout_seconds)),
            request_delay_seconds=max(0.0, float(request_delay_seconds)),
            max_retries=max(0, int(max_retries)),
            allow_bootstrap_fallback=allow_bootstrap_fallback,
        )
        self.last_used_bootstrap_fallback = False
        self.last_fetch_error_type: str | None = None
        self.last_fetch_http_status: int | None = None
        self.last_fetch_retryable: bool | None = None
        self.last_rows_accepted = 0
        self.last_rows_rejected = 0

    async def _request(self, client: Any, url: str) -> Any:
        from app.services.tender_sources.diagnostics import (
            connector_failure_details,
            retry_after_seconds,
        )

        for attempt in range(self.config.max_retries + 1):
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response
            except Exception as exc:
                details = connector_failure_details(exc)
                if attempt >= self.config.max_retries or not details.retryable:
                    raise
                delay = retry_after_seconds(exc, attempt=attempt)
                logger.warning(
                    "ebrd_request_retry stage=network attempt=%s failure_class=%s "
                    "http_status=%s retryable=true delay_seconds=%.2f",
                    attempt + 1,
                    details.failure_class,
                    details.http_status,
                    delay,
                )
                await asyncio.sleep(delay)
        raise RuntimeError("EBRD request failed")

    async def list_opportunities(self) -> list[dict[str, Any]]:
        import httpx

        self.last_used_bootstrap_fallback = False
        self.last_fetch_error_type = None
        self.last_fetch_http_status = None
        self.last_fetch_retryable = None
        self.last_rows_accepted = 0
        self.last_rows_rejected = 0
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            headers={"User-Agent": EBRD_USER_AGENT},
            follow_redirects=True,
        ) as client:
            try:
                response = await self._request(client, EBRD_NOTICE_SEARCH_URL)
            except Exception as exc:
                from app.services.tender_sources.diagnostics import connector_failure_details

                failure = connector_failure_details(exc)
                self.last_fetch_error_type = failure.failure_class
                self.last_fetch_http_status = failure.http_status
                self.last_fetch_retryable = failure.retryable
                if not self.config.allow_bootstrap_fallback:
                    raise
                self.last_used_bootstrap_fallback = True
                logger.warning(
                    "ebrd_live_listing_unavailable using_bootstrap_fallback "
                    "failure_class=%s http_status=%s retryable=%s",
                    self.last_fetch_error_type,
                    self.last_fetch_http_status,
                    str(self.last_fetch_retryable).lower(),
                )
                fallback_candidates = _bootstrap_fallback_rows(self.config.max_items)
                accepted = [
                    row
                    for row in fallback_candidates
                    if self.should_import(row)
                ]
                self.last_rows_accepted = len(accepted)
                self.last_rows_rejected = len(fallback_candidates) - len(accepted)
                return accepted
            listing_rows = parse_ebrd_search_page(response.content, page_url=str(response.url))
            candidates = [
                row for row in listing_rows if self.should_import(row)
            ][: self.config.max_items]
            detail_limit = min(self.config.detail_items, len(candidates))
            enriched: list[dict[str, Any]] = []
            for index, row in enumerate(candidates):
                if index >= detail_limit:
                    enriched.append(row)
                    continue
                if index > 0:
                    await asyncio.sleep(self.config.request_delay_seconds)
                try:
                    detail = await self.fetch_detail_by_url(str(row["source_url"]), client=client)
                    enriched.append(_merge_listing_detail(row, detail))
                except Exception:
                    logger.exception(
                        "ebrd_detail_fetch_failed external_id=%s",
                        row.get("external_id"),
                    )
                    enriched.append(row)
        deduped: dict[str, dict[str, Any]] = {}
        for opportunity in enriched:
            external_id = str(opportunity.get("external_id") or "").strip()
            if external_id and external_id not in deduped:
                deduped[external_id] = opportunity
        self.last_rows_accepted = len(deduped)
        self.last_rows_rejected = max(0, len(listing_rows) - len(deduped))
        return list(deduped.values())

    async def fetch_detail_by_url(self, source_url: str, *, client: Any | None = None) -> dict[str, Any]:
        if not _safe_ebrd_url(source_url):
            raise ValueError("Unsafe EBRD source URL")
        if client is not None:
            response = await self._request(client, source_url)
            return parse_ebrd_notice_detail(response.content, source_url=str(response.url))

        import httpx

        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            headers={"User-Agent": EBRD_USER_AGENT},
            follow_redirects=True,
        ) as owned_client:
            response = await self._request(owned_client, source_url)
        return parse_ebrd_notice_detail(response.content, source_url=str(response.url))

    async def fetch_detail(self, external_id: str) -> dict[str, Any] | None:
        external_id = str(external_id or "").strip()
        if not external_id:
            return None
        return await self.fetch_detail_by_url(
            f"{EBRD_BASE_URL}/delta/viewNotice.html?displayNoticeId={external_id}"
        )

    def should_import(self, raw: dict[str, Any]) -> bool:
        return _is_actionable(raw, active_only=self.config.active_only)

    async def discover_documents(self, normalized_tender: NormalizedTender) -> list[CanonicalDocument]:
        metadata = normalized_tender.source_metadata_json or {}
        response_url = _clean_whitespace(metadata.get("document_access_url"))
        if not response_url or not _safe_ebrd_url(response_url):
            return []
        external_file_id = hashlib.sha256(
            f"{normalized_tender.canonical_source_key}|{response_url}|access-required".encode("utf-8")
        ).hexdigest()[:32]
        return [
            CanonicalDocument(
                source_system=self.source_system,
                source_document_url=response_url,
                file_type="access_required",
                title="EBRD participation documents",
                source_document_type="access_required",
                external_file_id=external_file_id,
                download_status="access_required",
                source_metadata_json={
                    "document_bundle": "participation_documents",
                    "access_required_reason": (
                        "ECEPP requires registration and expressing interest before documents are available."
                    ),
                },
            )
        ]

    async def discover_attachments(self, normalized_tender: NormalizedTender) -> list[Any]:
        return []

    def normalize(self, raw: dict[str, Any]) -> NormalizedTender:
        metadata = dict(raw.get("source_metadata_json") or {})
        if raw.get("project_name"):
            metadata["project_name"] = raw.get("project_name")
        return NormalizedTender(
            source_system=self.source_system,
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
            notice_type=raw.get("notice_type"),
            project_id=raw.get("project_id"),
            publication_date=raw.get("publication_date"),
            deadline=raw.get("deadline"),
            status=TenderStatus.OPEN,
            category="EBRD",
            source_metadata_json=metadata,
            scrape_status="success",
        )

    async def upsert(self, db: Any, normalized_tender: NormalizedTender) -> tuple[Any, bool]:
        return await upsert_tender(db, normalized_tender)

    async def upsert_documents(
        self,
        db: Any,
        *,
        tender: Any,
        documents: list[CanonicalDocument],
    ) -> tuple[int, int]:
        assert_source_scope(self.source_system, tender)
        created = 0
        updated = 0
        for document in documents:
            source_url = str(document.source_document_url or "").strip()
            if not source_url or not _safe_ebrd_url(source_url):
                continue
            result = await db.execute(
                select(TenderDocument).where(
                    TenderDocument.tender_id == tender.id,
                    TenderDocument.source_document_url == source_url,
                )
            )
            existing = result.scalar_one_or_none()
            file_type = document.source_document_type or document.file_type or "access_required"
            if existing is None:
                db.add(
                    TenderDocument(
                        tender_id=tender.id,
                        file_url=source_url[:500],
                        file_type=file_type,
                        source_document_url=source_url,
                        source_document_type=file_type,
                        download_status=document.download_status or "access_required",
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
                existing.download_status = "access_required"
                existing.external_file_id = document.external_file_id or existing.external_file_id
                existing.file_size = document.file_size or existing.file_size
                existing.mime_type = document.mime_type or existing.mime_type
                existing.sha256 = document.sha256 or existing.sha256
                updated += 1
        return created, updated


def _merge_listing_detail(listing: dict[str, Any], detail: dict[str, Any] | None) -> dict[str, Any]:
    if not detail:
        return listing
    merged = {**listing}
    for key, value in detail.items():
        if key == "source_metadata_json":
            continue
        if key == "title" and value == "EBRD procurement notice":
            continue
        if value not in (None, ""):
            merged[key] = value
    merged_metadata = {
        **(listing.get("source_metadata_json") or {}),
        **(detail.get("source_metadata_json") or {}),
    }
    merged["source_metadata_json"] = merged_metadata
    return merged
