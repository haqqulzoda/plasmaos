"""Shared contracts and upsert helpers for tender source ingestion."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import Tender, TenderStatus
from app.services.tender_sources.keys import (
    canonical_source_key,
    normalize_source_system,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NormalizedAttachment:
    """Internal attachment metadata discovered from a source system."""

    source_document_url: str
    source_document_type: str | None = None
    external_file_id: str | None = None
    file_size: int | None = None
    mime_type: str | None = None
    sha256: str | None = None
    source_metadata_json: dict[str, Any] | None = None


@dataclass(frozen=True)
class NormalizedTender:
    """Source-neutral tender payload used by connector upserts."""

    source_system: str
    external_id: str
    source_url: str
    title: str
    description: str | None = None
    budget: float = 0.0
    currency: str = "UZS"
    country: str | None = None
    region: str | None = None
    sector: str | None = None
    buyer: str | None = None
    procurement_category: str | None = None
    procurement_method: str | None = None
    notice_type: str | None = None
    project_id: str | None = None
    publication_date: datetime | None = None
    deadline: datetime | None = None
    status: TenderStatus = TenderStatus.OPEN
    category: str = "Other"
    source_metadata_json: dict[str, Any] | None = None
    scrape_status: str | None = "success"
    last_synced_at: datetime | None = None
    attachments: tuple[NormalizedAttachment, ...] = field(default_factory=tuple)

    @property
    def normalized_source_system(self) -> str:
        return normalize_source_system(self.source_system)

    @property
    def canonical_source_key(self) -> str:
        return canonical_source_key(self.source_system, self.external_id)


class TenderSourceConnector(Protocol):
    """Lightweight connector contract for source-specific tender ingestion."""

    source_system: str

    async def list_opportunities(self) -> list[Any]:
        """Return raw opportunity payloads from the source."""
        ...

    async def fetch_detail(self, external_id: str) -> Any:
        """Fetch raw detail payload for one source tender."""
        ...

    async def discover_attachments(
        self,
        normalized_tender: NormalizedTender,
    ) -> list[NormalizedAttachment]:
        """Discover source document metadata for one normalized tender."""
        ...

    def normalize(self, raw: Any) -> NormalizedTender:
        """Convert a raw source payload into a NormalizedTender."""
        ...

    async def upsert(
        self,
        db: AsyncSession,
        normalized_tender: NormalizedTender,
    ) -> tuple[Tender, bool]:
        """Persist a normalized tender and return (tender, created)."""
        ...


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


async def upsert_tender(
    db: AsyncSession,
    normalized_tender: NormalizedTender,
) -> tuple[Tender, bool]:
    """Create or update tender metadata without touching related artifacts."""
    source_system = normalized_tender.normalized_source_system
    external_id = str(normalized_tender.external_id).strip()
    key = normalized_tender.canonical_source_key
    synced_at = normalized_tender.last_synced_at or datetime.now(timezone.utc)

    result = await db.execute(
        select(Tender).where(Tender.canonical_source_key == key)
    )
    tender = result.scalar_one_or_none()
    if tender is None:
        result = await db.execute(
            select(Tender).where(
                Tender.source_system == source_system,
                Tender.external_id == external_id,
            )
        )
        tender = result.scalar_one_or_none()
    created = tender is None

    if tender is None:
        tender = Tender(
            source_system=source_system,
            external_id=external_id,
            canonical_source_key=key,
            source_url=normalized_tender.source_url,
            title=normalized_tender.title,
            description=normalized_tender.description,
            budget=normalized_tender.budget,
            currency=normalized_tender.currency,
            deadline=normalized_tender.deadline,
            publication_date=normalized_tender.publication_date,
            country=_clean_optional(normalized_tender.country),
            region=_clean_optional(normalized_tender.region),
            sector=_clean_optional(normalized_tender.sector),
            buyer=_clean_optional(normalized_tender.buyer),
            procurement_category=_clean_optional(
                normalized_tender.procurement_category
            ),
            procurement_method=_clean_optional(normalized_tender.procurement_method),
            notice_type=_clean_optional(normalized_tender.notice_type),
            project_id=_clean_optional(normalized_tender.project_id),
            source_metadata_json=normalized_tender.source_metadata_json,
            scrape_status=_clean_optional(normalized_tender.scrape_status) or "success",
            last_synced_at=synced_at,
            status=normalized_tender.status,
            category=normalized_tender.category,
        )
        db.add(tender)
    else:
        tender.source_system = source_system
        tender.external_id = external_id
        tender.canonical_source_key = key
        tender.source_url = normalized_tender.source_url
        tender.title = normalized_tender.title
        tender.description = normalized_tender.description
        tender.budget = normalized_tender.budget
        tender.currency = normalized_tender.currency
        tender.deadline = normalized_tender.deadline
        tender.publication_date = normalized_tender.publication_date
        tender.country = _clean_optional(normalized_tender.country)
        tender.region = _clean_optional(normalized_tender.region)
        tender.sector = _clean_optional(normalized_tender.sector)
        tender.buyer = _clean_optional(normalized_tender.buyer)
        tender.procurement_category = _clean_optional(
            normalized_tender.procurement_category
        )
        tender.procurement_method = _clean_optional(normalized_tender.procurement_method)
        tender.notice_type = _clean_optional(normalized_tender.notice_type)
        tender.project_id = _clean_optional(normalized_tender.project_id)
        tender.source_metadata_json = normalized_tender.source_metadata_json
        tender.scrape_status = _clean_optional(normalized_tender.scrape_status) or "success"
        tender.last_synced_at = synced_at
        tender.status = normalized_tender.status
        tender.category = normalized_tender.category

    logger.info(
        "tender_source_upsert source_system=%s external_id=%s canonical_source_key=%s status=%s",
        source_system,
        external_id,
        key,
        "created" if created else "updated",
    )
    return tender, created
