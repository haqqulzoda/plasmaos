"""UzEx adapter for the shared tender source abstraction."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scraper import ScrapedTender
from app.models.all_models import Tender
from app.services.tender_sources.base import (
    NormalizedAttachment,
    NormalizedTender,
    upsert_tender,
)
from app.services.tender_sources.uzex_scope import uzex_source_metadata


class UzExTenderSource:
    source_system = "uzex"

    async def list_opportunities(self) -> list[Any]:
        raise NotImplementedError("Use UzExScraper for live scraping in INT-1.")

    async def fetch_detail(self, external_id: str) -> Any:
        raise NotImplementedError("UzEx detail fetch is handled by existing scraper.")

    async def discover_attachments(
        self,
        normalized_tender: NormalizedTender,
    ) -> list[NormalizedAttachment]:
        raise NotImplementedError("UzEx attachment sync is handled by existing worker.")

    def normalize(self, raw: ScrapedTender) -> NormalizedTender:
        return NormalizedTender(
            source_system=self.source_system,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=raw.title,
            budget=raw.budget,
            currency=raw.currency,
            publication_date=raw.publication_date,
            deadline=raw.deadline,
            region=raw.region,
            category=raw.category,
            source_metadata_json=uzex_source_metadata(),
            scrape_status="success",
        )

    async def upsert(
        self,
        db: AsyncSession,
        normalized_tender: NormalizedTender,
    ) -> tuple[Tender, bool]:
        return await upsert_tender(db, normalized_tender)
