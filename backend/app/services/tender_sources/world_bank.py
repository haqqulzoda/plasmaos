"""World Bank procurement notices connector."""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

WORLD_BANK_PROC_NOTICES_URL = "https://search.worldbank.org/api/v2/procnotices"
WORLD_BANK_PROC_DETAIL_URL = (
    "https://projects.worldbank.org/en/projects-operations/procurement-detail/{id}"
)
WORLD_BANK_ACTIONABLE_NOTICE_TYPES = (
    "Invitation for Bids",
    "Invitation for Prequalification",
    "Request for Expression of Interest",
)
ALLOWED_ATTACHMENT_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "zip"}
EXCLUDED_NOTICE_TYPES = {"contract award"}
GENERAL_PROCUREMENT_NOTICE_TYPES = {"general procurement notice"}


def world_bank_utc_instant(now: datetime | None = None) -> datetime:
    """Return an aware UTC instant for World Bank source-time decisions."""
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def world_bank_current_date(now: datetime | None = None) -> date:
    """Return the UTC calendar date used by the current-opportunities API."""
    return world_bank_utc_instant(now).date()


@dataclass(frozen=True)
class WorldBankSyncConfig:
    rows: int = 100
    max_pages: int = 25
    active_only: bool = True
    include_general_procurement_notice: bool = False
    request_delay_seconds: float = 0.25
    timeout_seconds: float = 30.0
    max_retries: int = 2


class _NoticeHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self._skip_text_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in {"script", "style"}:
            self._skip_text_depth += 1
            return
        if normalized_tag != "a":
            return
        attrs_dict = {key.casefold(): value for key, value in attrs}
        href = (attrs_dict.get("href") or "").strip()
        if href:
            self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"} and self._skip_text_depth:
            self._skip_text_depth -= 1

    def handle_data(self, data: str) -> None:
        if data and not self._skip_text_depth:
            self.text_parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._skip_text_depth:
            self.text_parts.append(html.unescape(f"&{name};"))


def _clean_whitespace(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or None


def clean_notice_html(notice_text: str | None) -> str | None:
    """Return safe, plain-text notice content for customer descriptions."""
    if not notice_text:
        return None
    parser = _NoticeHtmlParser()
    parser.feed(str(notice_text))
    text = " ".join(parser.text_parts)
    return _clean_whitespace(html.unescape(text))


def _notice_links(notice_text: str | None) -> list[str]:
    if not notice_text:
        return []
    parser = _NoticeHtmlParser()
    parser.feed(str(notice_text))
    return parser.links


def _safe_join(items: list[str]) -> str | None:
    cleaned = [_clean_whitespace(item) for item in items]
    values = [item for item in cleaned if item]
    return "; ".join(values) if values else None


def _first_text(raw: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        cleaned = _clean_whitespace(raw.get(key))
        if cleaned:
            return cleaned
    return None


def extract_world_bank_contact_info(raw: dict[str, Any] | None) -> dict[str, str | None]:
    """Extract the public CONTACT INFORMATION block from a procnotice row."""
    if not isinstance(raw, dict):
        return {}

    contact_name = _first_text(
        raw,
        (
            "contact_name",
            "contact_person",
            "contact_person_name",
            "procurement_contact_name",
        ),
    )
    contact_title = _first_text(raw, ("contact_job_title", "contact_title"))
    contact_person = (
        f"{contact_name} ({contact_title})"
        if contact_name and contact_title
        else contact_name
    )
    address = _safe_join(
        [
            _first_text(raw, ("contact_address", "agency_address")),
            _first_text(raw, ("contact_city", "contact_municipality")),
            _first_text(raw, ("contact_state", "contact_province", "contact_region")),
            _first_text(raw, ("contact_postal_code", "contact_zip")),
            _first_text(raw, ("contact_ctry_name", "contact_country")),
        ]
    )

    return {
        "buyer_agency": _first_text(
            raw,
            ("contact_organization", "agency_name", "buyer", "buyer_name"),
        ),
        "contact_person": contact_person,
        "email": _first_text(raw, ("contact_email", "email")),
        "phone": _first_text(
            raw,
            ("contact_phone_no", "contact_phone", "phone", "telephone"),
        ),
        "address": address,
    }


def _sector_text(raw: dict[str, Any]) -> str | None:
    sectors = raw.get("sector")
    if not isinstance(sectors, list):
        return None
    return _safe_join(
        [
            str(item.get("sector_description", ""))
            for item in sectors
            if isinstance(item, dict)
        ]
    )


def _parse_amount(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_world_bank_deadline(raw: dict[str, Any]) -> datetime | None:
    deadline = _parse_date(raw.get("submission_deadline_date"))
    if deadline is None:
        return None

    time_text = _clean_whitespace(raw.get("submission_deadline_time"))
    if not time_text:
        # The official current-opportunities API treats deadline dates as active
        # for the whole UTC date. Preserve that semantic when no time is supplied.
        return datetime.combine(deadline.date(), time.max, tzinfo=timezone.utc)

    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p"):
        try:
            parsed_time = datetime.strptime(time_text.upper(), fmt).time()
            return datetime.combine(
                deadline.date(),
                parsed_time,
                tzinfo=timezone.utc,
            )
        except ValueError:
            pass
    return datetime.combine(deadline.date(), time.max, tzinfo=timezone.utc)


def parse_world_bank_publication_date(raw: dict[str, Any]) -> datetime | None:
    return _parse_date(raw.get("noticedate")) or _parse_date(raw.get("submission_date"))


def _notice_type(raw: dict[str, Any]) -> str:
    return _clean_whitespace(raw.get("notice_type")) or ""


def is_actionable_notice(
    raw: dict[str, Any],
    *,
    active_only: bool = True,
    include_general_procurement_notice: bool = False,
    today: date | None = None,
) -> bool:
    status = (_clean_whitespace(raw.get("notice_status")) or "").casefold()
    if status != "published":
        return False

    notice_type = _notice_type(raw).casefold()
    if notice_type in EXCLUDED_NOTICE_TYPES:
        return False
    if (
        not include_general_procurement_notice
        and notice_type in GENERAL_PROCUREMENT_NOTICE_TYPES
    ):
        return False

    if not active_only:
        return True

    deadline = parse_world_bank_deadline(raw)
    if deadline is None:
        return False
    comparison_date = today or world_bank_current_date()
    return deadline.date() >= comparison_date


def world_bank_skip_reason(
    raw: dict[str, Any],
    *,
    active_only: bool = True,
    include_general_procurement_notice: bool = False,
    today: date | None = None,
) -> str | None:
    """Return a stable diagnostic reason, or None when a row is actionable."""
    status = (_clean_whitespace(raw.get("notice_status")) or "").casefold()
    if status != "published":
        return "not_published"
    notice_type = _notice_type(raw).casefold()
    if notice_type in EXCLUDED_NOTICE_TYPES or notice_type.endswith(" award"):
        return "contract_award"
    if (
        not include_general_procurement_notice
        and notice_type in GENERAL_PROCUREMENT_NOTICE_TYPES
    ):
        return "general_procurement_notice"
    if not active_only:
        return None
    deadline = parse_world_bank_deadline(raw)
    if deadline is None:
        return "missing_deadline"
    comparison_date = today or world_bank_current_date()
    if deadline.date() < comparison_date:
        return "expired"
    return None


def _source_url(external_id: str) -> str:
    return WORLD_BANK_PROC_DETAIL_URL.format(id=external_id)


def _title(raw: dict[str, Any]) -> str:
    return (
        _clean_whitespace(raw.get("noticetitle"))
        or _clean_whitespace(raw.get("bid_description"))
        or f"World Bank procurement notice {raw.get('id')}"
    )


def normalize_world_bank_notice_payload(raw: dict[str, Any]) -> dict[str, Any]:
    external_id = _clean_whitespace(raw.get("id"))
    if not external_id:
        raise ValueError("World Bank notice id is required")

    description = (
        clean_notice_html(raw.get("notice_text"))
        or _clean_whitespace(raw.get("bid_description"))
        or _title(raw)
    )

    return {
        "source_system": "world_bank",
        "external_id": external_id,
        "source_url": _source_url(external_id),
        "title": _title(raw),
        "description": description,
        "budget": _parse_amount(raw.get("bid_estimate_amount")),
        "currency": _clean_whitespace(raw.get("bid_currency_code")) or "USD",
        "country": _clean_whitespace(raw.get("project_ctry_name")),
        "region": _clean_whitespace(raw.get("regionname")),
        "sector": _sector_text(raw),
        "buyer": (
            _clean_whitespace(raw.get("agency_name"))
            or _clean_whitespace(raw.get("contact_organization"))
        ),
        "procurement_category": _clean_whitespace(raw.get("procurement_group_desc")),
        "procurement_method": _clean_whitespace(raw.get("procurement_method_name")),
        "notice_type": _clean_whitespace(raw.get("notice_type")),
        "project_id": _clean_whitespace(raw.get("project_id")),
        "publication_date": parse_world_bank_publication_date(raw),
        "deadline": parse_world_bank_deadline(raw),
        "source_metadata_json": raw,
        "scrape_status": "success",
    }


def _attachment_extension(url: str) -> str | None:
    path = urlparse(url).path
    suffix = path.rsplit(".", 1)[-1].casefold() if "." in path else ""
    return suffix if suffix in ALLOWED_ATTACHMENT_EXTENSIONS else None


def _is_safe_attachment_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if _attachment_extension(url):
        return True
    path = parsed.path.casefold()
    return any(marker in path for marker in ("/download", "/documents", "/document"))


def extract_world_bank_attachment_links(
    notice_text: str | None,
    *,
    base_url: str | None = None,
) -> list[dict[str, str]]:
    base = base_url or "https://projects.worldbank.org/"
    seen: set[str] = set()
    attachments: list[dict[str, str]] = []
    for href in _notice_links(notice_text):
        absolute_url = urljoin(base, href.strip())
        if absolute_url in seen or not _is_safe_attachment_url(absolute_url):
            continue
        seen.add(absolute_url)
        extension = _attachment_extension(absolute_url)
        attachments.append(
            {
                "source_document_url": absolute_url,
                "source_document_type": extension or "document_page",
                "external_file_id": hashlib.sha256(
                    absolute_url.encode("utf-8")
                ).hexdigest()[:32],
            }
        )
    return attachments


def _response_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("procnotices")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _response_total(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    try:
        return int(payload.get("total"))
    except (TypeError, ValueError):
        return None


class WorldBankTenderSource:
    source_system = "world_bank"

    def __init__(
        self,
        *,
        rows: int = 100,
        max_pages: int = 25,
        active_only: bool = True,
        include_general_procurement_notice: bool = False,
        request_delay_seconds: float = 0.25,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = WorldBankSyncConfig(
            rows=max(1, min(int(rows or 100), 100)),
            max_pages=max(1, int(max_pages or 1)),
            active_only=active_only,
            include_general_procurement_notice=include_general_procurement_notice,
            request_delay_seconds=max(0.0, float(request_delay_seconds)),
            timeout_seconds=max(1.0, float(timeout_seconds)),
            max_retries=max(0, int(max_retries)),
        )
        self.last_total: int | None = None
        self.last_pages_fetched = 0
        self.last_truncated = False
        self.last_duplicate_count = 0
        self.source_newest_published_at: datetime | None = None
        self.source_oldest_published_at: datetime | None = None
        self.last_query_date: date | None = None
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _utc_now(self) -> datetime:
        return world_bank_utc_instant(self._clock())

    async def _get_json(self, client: Any, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self.config.max_retries + 1):
            try:
                response = await client.get(WORLD_BANK_PROC_NOTICES_URL, params=params)
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, dict) else {}
            except Exception:
                if attempt >= self.config.max_retries:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))
        return {}

    async def list_opportunities(self) -> list[dict[str, Any]]:
        import httpx

        notices: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_page_fingerprints: set[tuple[str, ...]] = set()
        self.last_pages_fetched = 0
        self.last_truncated = False
        self.last_duplicate_count = 0
        self.last_query_date = (
            world_bank_current_date(self._utc_now())
            if self.config.active_only
            else None
        )
        notice_types = list(WORLD_BANK_ACTIONABLE_NOTICE_TYPES)
        if self.config.include_general_procurement_notice:
            notice_types.append("General Procurement Notice")
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            headers={"User-Agent": "PlasmaOS WorldBankConnector/1.0"},
        ) as client:
            for page_index in range(self.config.max_pages):
                offset = page_index * self.config.rows
                payload = await self._get_json(
                    client,
                    {
                        "format": "json",
                        "apilang": "en",
                        "fl": "*",
                        "rows": self.config.rows,
                        "os": offset,
                        "srt": "submission_deadline_date",
                        "order": "asc",
                        "notice_type_exact": "^".join(notice_types),
                        **(
                            {"deadline_strdate": self.last_query_date.isoformat()}
                            if self.last_query_date is not None
                            else {}
                        ),
                    },
                )
                rows = _response_rows(payload)
                self.last_total = _response_total(payload)
                self.last_pages_fetched += 1
                page_ids = tuple(str(row.get("id") or "").strip() for row in rows)
                if rows and page_ids in seen_page_fingerprints:
                    self.last_truncated = True
                    logger.error(
                        "world_bank_repeated_page os=%s returned=%s total=%s",
                        offset,
                        len(rows),
                        self.last_total,
                    )
                    break
                seen_page_fingerprints.add(page_ids)
                logger.info(
                    "world_bank_list_page os=%s rows=%s returned=%s total=%s",
                    offset,
                    self.config.rows,
                    len(rows),
                    self.last_total,
                )
                for row in rows:
                    external_id = str(row.get("id") or "").strip()
                    if not external_id:
                        continue
                    if external_id in seen_ids:
                        self.last_duplicate_count += 1
                        continue
                    seen_ids.add(external_id)
                    notices.append(row)
                if not rows:
                    break
                if self.last_total is not None and offset + self.config.rows >= self.last_total:
                    break
                if len(rows) < self.config.rows:
                    break
                if page_index + 1 < self.config.max_pages:
                    await asyncio.sleep(self.config.request_delay_seconds)
            else:
                if self.last_total is None or len(seen_ids) < self.last_total:
                    self.last_truncated = True

        publication_dates = [
            value
            for value in (parse_world_bank_publication_date(row) for row in notices)
            if value is not None
        ]
        self.source_newest_published_at = max(publication_dates, default=None)
        self.source_oldest_published_at = min(publication_dates, default=None)
        return notices

    async def fetch_detail(self, external_id: str) -> dict[str, Any] | None:
        import httpx

        external_id = str(external_id).strip()
        if not external_id:
            return None
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            headers={"User-Agent": "PlasmaOS WorldBankConnector/1.0"},
        ) as client:
            payload = await self._get_json(
                client,
                {
                    "format": "json",
                    "apilang": "en",
                    "fl": "*",
                    "id": external_id,
                },
            )
        rows = _response_rows(payload)
        return rows[0] if rows else None

    def should_import(self, raw: dict[str, Any]) -> bool:
        return self.skip_reason(raw) is None

    def skip_reason(self, raw: dict[str, Any]) -> str | None:
        return world_bank_skip_reason(
            raw,
            active_only=self.config.active_only,
            include_general_procurement_notice=(
                self.config.include_general_procurement_notice
            ),
            today=self.last_query_date or world_bank_current_date(self._utc_now()),
        )

    async def discover_attachments(self, normalized_tender: Any) -> list[Any]:
        from app.services.tender_sources.base import NormalizedAttachment

        source_payload = normalized_tender.source_metadata_json or {}
        attachment_payloads = extract_world_bank_attachment_links(
            source_payload.get("notice_text"),
            base_url=normalized_tender.source_url,
        )
        return [
            NormalizedAttachment(
                source_document_url=item["source_document_url"],
                source_document_type=item["source_document_type"],
                external_file_id=item["external_file_id"],
            )
            for item in attachment_payloads
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

        payload = normalize_world_bank_notice_payload(raw)
        deadline = payload["deadline"]
        lifecycle_status = (
            TenderStatus.CLOSED
            if deadline is not None and deadline < self._utc_now()
            else TenderStatus.OPEN
        )
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
            deadline=deadline,
            status=lifecycle_status,
            category="World Bank",
            source_metadata_json=payload["source_metadata_json"],
            scrape_status=payload["scrape_status"],
        )

    async def upsert(self, db: Any, normalized_tender: Any) -> tuple[Any, bool]:
        from app.services.tender_sources.base import upsert_tender

        tender, created = await upsert_tender(db, normalized_tender)
        await self.link_project(
            db,
            tender=tender,
            normalized_tender=normalized_tender,
        )
        return tender, created

    async def link_project(
        self,
        db: Any,
        *,
        tender: Any,
        normalized_tender: Any,
    ) -> None:
        """Preserve World Bank Project/TenderProject ownership after batch persist."""
        from app.services.projects import link_tender_to_project

        source_metadata = normalized_tender.source_metadata_json or {}
        raw_project_id = source_metadata.get(
            "project_id",
            normalized_tender.project_id,
        )
        await link_tender_to_project(
            db,
            tender=tender,
            external_project_id=raw_project_id,
            source_field="project_id",
            source_url=normalized_tender.source_url,
            observed_at=tender.last_synced_at,
            authoritative_metadata={"country": normalized_tender.country},
        )

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
            documents=documents, default_status="metadata_only",
        )
        return result.created_count, result.updated_count
