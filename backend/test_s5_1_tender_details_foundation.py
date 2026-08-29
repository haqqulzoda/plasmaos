"""Sprint 5.1 contracts for passive canonical Tender Details reads."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.api.endpoints import tenders as tender_endpoints
from app.models.all_models import TenderStatus


def _tender(**overrides):
    values = {
        "id": uuid4(),
        "external_id": "S51-UZEX-1",
        "source_system": "uzex",
        "canonical_source_key": "uzex:S51-UZEX-1",
        "source_url": "https://etender.uzex.uz/lot/S51-UZEX-1",
        "title": "Sprint 5.1 passive Tender",
        "description": "Source opportunity facts",
        "budget": 1000.0,
        "currency": "UZS",
        "deadline": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "publication_date": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "country": "Uzbekistan",
        "region": "Central Asia",
        "sector": "Technology",
        "buyer": "Example buyer",
        "procurement_category": "Services",
        "procurement_method": "Open tender",
        "notice_type": "Invitation",
        "project_id": None,
        "status": TenderStatus.OPEN,
        "category": "Technology",
        "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "source_metadata_json": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class PassiveTenderReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_uzex_dates_are_response_overrides_not_orm_mutations(self) -> None:
        tender = _tender()
        stored_publication = tender.publication_date
        stored_deadline = tender.deadline
        live_publication = datetime(2026, 8, 15, tzinfo=timezone.utc)
        live_deadline = datetime(2026, 9, 15, tzinfo=timezone.utc)

        with patch.object(
            tender_endpoints,
            "_uzex_trade_list_date_map",
            AsyncMock(return_value={tender.external_id: (live_publication, live_deadline)}),
        ):
            overrides = await tender_endpoints._apply_live_uzex_dates([tender])

        self.assertEqual(tender.publication_date, stored_publication)
        self.assertEqual(tender.deadline, stored_deadline)
        self.assertEqual(overrides[tender.id], (live_publication, live_deadline))

        response = tender_endpoints._serialize_tender(
            tender,
            summary=tender_endpoints._empty_tender_summary(),
            include_contact_metadata=True,
            live_dates=overrides[tender.id],
        )
        self.assertEqual(response.publication_date, live_publication)
        self.assertEqual(response.deadline, live_deadline)
        self.assertEqual(response.contact_submission.submission_deadline, live_deadline)

    async def test_non_uzex_tender_has_no_live_date_lookup_or_override(self) -> None:
        tender = _tender(
            source_system="world_bank",
            canonical_source_key="world_bank:S51-WB-1",
        )
        lookup = AsyncMock()

        with patch.object(tender_endpoints, "_uzex_trade_list_date_map", lookup):
            overrides = await tender_endpoints._apply_live_uzex_dates([tender])

        lookup.assert_not_awaited()
        self.assertEqual(overrides, {})


if __name__ == "__main__":
    unittest.main()
