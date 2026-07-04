"""Regression checks for S4.3 tender decision snapshots."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import unittest


ROOT = Path(__file__).resolve().parent


try:
    from app.api.endpoints import tenders as tender_endpoints
    from app.models.all_models import TenderStatus
    from app.schemas.tender import (
        TenderCompetitorGroup,
        TenderCompetitorIntelligenceResponse,
        TenderDecisionSnapshotResponse,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - local minimal env
    if exc.name in {
        "fastapi",
        "httpx",
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
    }:
        tender_endpoints = None
        TenderStatus = None
        TenderCompetitorGroup = None
        TenderCompetitorIntelligenceResponse = None
        TenderDecisionSnapshotResponse = None
        HAS_BACKEND_DEPS = False
    else:
        raise
else:
    HAS_BACKEND_DEPS = True


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _tender(**overrides):
    values = {
        "id": uuid4(),
        "external_id": "SNAP-1",
        "source_system": "world_bank",
        "canonical_source_key": "world_bank:SNAP-1",
        "source_url": "https://projects.worldbank.org/en/projects-operations/procurement-detail/SNAP-1",
        "title": "Hospital equipment procurement",
        "description": "Supply of diagnostic equipment",
        "budget": 125000.0,
        "currency": "USD",
        "deadline": datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc),
        "publication_date": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "country": "Uzbekistan",
        "region": "Central Asia",
        "sector": "Medical equipment",
        "buyer": "Ministry of Health",
        "procurement_category": "Goods",
        "procurement_method": "Request for Bids",
        "notice_type": "Invitation for Bids",
        "project_id": "P-SNAP",
        "status": TenderStatus.OPEN if TenderStatus is not None else "OPEN",
        "category": "Medical",
        "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "source_metadata_json": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TenderDecisionSnapshotStaticTests(unittest.TestCase):
    def test_snapshot_schema_is_whitelisted(self) -> None:
        schema = read("app/schemas/tender.py")
        snapshot_schema = schema.split("class TenderDecisionSnapshotResponse", 1)[
            1
        ].split("class TenderCompetitorResponse", 1)[0]

        for field in (
            "source",
            "country",
            "region",
            "service_category",
            "deadline",
            "deadline_urgency",
            "price_amount",
            "price_currency",
            "price_display",
            "document_status",
            "document_count",
            "downloadable_document_count",
            "missing_file_document_count",
            "parsed_document_count",
            "contact_availability",
            "competitor_intelligence_status",
            "compliance_availability",
            "source_notice_available",
        ):
            self.assertIn(field, snapshot_schema)

        self.assertNotIn("source_metadata_json", snapshot_schema)
        self.assertNotIn("raw_metadata", snapshot_schema)
        self.assertNotIn("compiled_master_text", snapshot_schema)

    def test_snapshot_endpoint_is_approved_pilot_guarded(self) -> None:
        tenders_source = read("app/api/endpoints/tenders.py")
        route_block = tenders_source.split('"/{tender_id}/decision-snapshot"', 1)[
            1
        ].split('"/{tender_id}/competitors"', 1)[0]

        self.assertIn("TenderDecisionSnapshotResponse", route_block)
        self.assertIn("require_approved_pilot_access", route_block)
        self.assertIn("_build_tender_competitor_intelligence", route_block)


@unittest.skipUnless(HAS_BACKEND_DEPS, "Backend dependencies are not installed")
class TenderDecisionSnapshotBehaviorTests(unittest.TestCase):
    def _empty_competitors(self, tender_id):
        assert TenderCompetitorIntelligenceResponse is not None
        return TenderCompetitorIntelligenceResponse(
            tender_id=tender_id,
            message="No historical competitor intelligence available yet.",
            groups=[],
        )

    def _available_competitors(self, tender_id):
        assert TenderCompetitorGroup is not None
        assert TenderCompetitorIntelligenceResponse is not None
        return TenderCompetitorIntelligenceResponse(
            tender_id=tender_id,
            message="Historical competitor intelligence is available.",
            groups=[
                TenderCompetitorGroup(
                    industry="Medical",
                    service_category="medical",
                    competitors=[],
                )
            ],
        )

    def test_deadline_urgency_buckets(self) -> None:
        assert tender_endpoints is not None

        now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(tender_endpoints._deadline_urgency(None, now=now), "unknown")
        self.assertEqual(
            tender_endpoints._deadline_urgency(now - timedelta(seconds=1), now=now),
            "expired",
        )
        self.assertEqual(tender_endpoints._deadline_urgency(now, now=now), "urgent")
        self.assertEqual(
            tender_endpoints._deadline_urgency(now + timedelta(days=7), now=now),
            "urgent",
        )
        self.assertEqual(
            tender_endpoints._deadline_urgency(now + timedelta(days=8), now=now),
            "soon",
        )
        self.assertEqual(
            tender_endpoints._deadline_urgency(now + timedelta(days=31), now=now),
            "normal",
        )

    def test_snapshot_availability_fields_are_derived_from_existing_signals(self) -> None:
        assert tender_endpoints is not None

        summary = {
            "has_compiled_text": True,
            "document_status": "documents_available",
            "document_count": 1,
            "available_document_count": 1,
            "downloadable_document_count": 1,
            "missing_file_document_count": 0,
            "parsed_document_count": 1,
            "metadata_only_document_count": 0,
            "failed_document_count": 0,
            "processing": False,
        }
        tender = tender_endpoints._serialize_tender(
            _tender(
                source_metadata_json={
                    "contact_name": "Jane Doe",
                    "contact_email": "jane@example.org",
                },
            ),
            summary=summary,
            include_contact_metadata=True,
        )

        snapshot = tender_endpoints._decision_snapshot_response(
            tender,
            competitor_intelligence=self._available_competitors(tender.id),
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertIsInstance(snapshot, TenderDecisionSnapshotResponse)
        self.assertEqual(snapshot.source, "world_bank")
        self.assertEqual(snapshot.contact_availability, "available")
        self.assertEqual(snapshot.downloadable_document_count, 1)
        self.assertEqual(snapshot.missing_file_document_count, 0)
        self.assertEqual(snapshot.parsed_document_count, 1)
        self.assertEqual(snapshot.competitor_intelligence_status, "available")
        self.assertEqual(snapshot.compliance_availability, "available")
        self.assertTrue(snapshot.source_notice_available)
        self.assertNotIn("source_metadata_json", snapshot.model_dump())

    def test_snapshot_serializes_supported_sources(self) -> None:
        assert tender_endpoints is not None

        cases = [
            (
                "uzex",
                "uzex:496369",
                "https://etender.uzex.uz/lot/496369",
                "Medical",
            ),
            (
                "world_bank",
                "world_bank:OP00434599",
                "https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00434599",
                "World Bank",
            ),
            (
                "adb",
                "adb:1140436",
                "https://www.adb.org/node/1140436",
                "ADB",
            ),
            (
                "ebrd",
                "ebrd:45376134",
                "https://ecepp.ebrd.com/delta/viewNotice.html?displayNoticeId=45376255",
                "EBRD",
            ),
        ]

        for source_system, canonical_key, source_url, category in cases:
            with self.subTest(source_system=source_system):
                tender = tender_endpoints._serialize_tender(
                    _tender(
                        source_system=source_system,
                        canonical_source_key=canonical_key,
                        source_url=source_url,
                        category=category,
                    ),
                    summary=tender_endpoints._empty_tender_summary(),
                    include_contact_metadata=True,
                )
                snapshot = tender_endpoints._decision_snapshot_response(
                    tender,
                    competitor_intelligence=self._empty_competitors(tender.id),
                    now=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )

                self.assertEqual(snapshot.source, source_system)
                self.assertTrue(snapshot.source_notice_available)
                self.assertIn(
                    snapshot.compliance_availability,
                    {"available", "unavailable"},
                )

    def test_missing_and_partial_empty_states_do_not_invent_values(self) -> None:
        assert tender_endpoints is not None

        partial = tender_endpoints._serialize_tender(
            _tender(source_metadata_json={}),
            summary=tender_endpoints._empty_tender_summary(),
            include_contact_metadata=True,
        )
        partial_snapshot = tender_endpoints._decision_snapshot_response(
            partial,
            competitor_intelligence=self._empty_competitors(partial.id),
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(partial_snapshot.contact_availability, "partial")
        self.assertEqual(partial_snapshot.competitor_intelligence_status, "unavailable")
        self.assertEqual(partial_snapshot.compliance_availability, "unavailable")

        missing = tender_endpoints._serialize_tender(
            _tender(source_url=None, buyer=None, source_metadata_json={}),
            summary=tender_endpoints._empty_tender_summary(),
            include_contact_metadata=True,
        )
        missing_snapshot = tender_endpoints._decision_snapshot_response(
            missing,
            competitor_intelligence=self._empty_competitors(missing.id),
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(missing_snapshot.contact_availability, "missing")
        self.assertFalse(missing_snapshot.source_notice_available)


if __name__ == "__main__":
    unittest.main()
