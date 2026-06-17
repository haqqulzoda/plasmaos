"""Focused tests for the multi-source tender foundation."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.services.tender_sources.keys import (
    canonical_source_key,
    normalize_source_system,
)

try:
    from app.models.all_models import Tender, TenderStatus
    from app.services.tender_sources.base import (
        NormalizedTender,
        upsert_tender,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - local minimal env
    if exc.name == "sqlalchemy":
        Tender = None
        TenderStatus = None
        NormalizedTender = None
        upsert_tender = None
        HAS_BACKEND_DEPS = False
    else:
        raise
else:
    HAS_BACKEND_DEPS = True


class TenderSourceKeyTests(unittest.TestCase):
    def test_canonical_source_key_generation(self) -> None:
        self.assertEqual(
            canonical_source_key("world_bank", "OP00434599"),
            "world_bank:OP00434599",
        )
        self.assertEqual(canonical_source_key("adb", "1142361"), "adb:1142361")
        self.assertEqual(canonical_source_key(" UzEx ", "488105"), "uzex:488105")

    def test_source_system_normalization_rejects_unknown_values(self) -> None:
        self.assertEqual(normalize_source_system(" WORLD_BANK "), "world_bank")
        with self.assertRaises(ValueError):
            normalize_source_system("unknown")


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeSession:
    def __init__(self):
        self.items = {}
        self.items_by_pair = {}
        self.add_count = 0

    async def execute(self, statement):
        criteria = statement._where_criteria
        if len(criteria) == 1:
            criterion = criteria[0]
            left = str(getattr(criterion, "left", ""))
            if left.endswith("canonical_source_key"):
                key = criterion.right.value
                return _FakeResult(self.items.get(key))

        values = {}
        for criterion in criteria:
            left = str(getattr(criterion, "left", ""))
            if left.endswith("source_system"):
                values["source_system"] = criterion.right.value
            elif left.endswith("external_id"):
                values["external_id"] = criterion.right.value
        pair = (values.get("source_system"), values.get("external_id"))
        return _FakeResult(self.items_by_pair.get(pair))

    def add(self, tender):
        self.add_count += 1
        if tender.id is None:
            tender.id = uuid4()
        self.items[tender.canonical_source_key] = tender
        self.items_by_pair[(tender.source_system, tender.external_id)] = tender

    def add_existing_pair_only(self, tender):
        if tender.id is None:
            tender.id = uuid4()
        self.items_by_pair[(tender.source_system, tender.external_id)] = tender


def _normalized(
    *,
    source_system: str = "uzex",
    external_id: str = "488105",
    title: str = "Test tender",
) -> NormalizedTender:
    return NormalizedTender(
        source_system=source_system,
        external_id=external_id,
        source_url=f"https://example.test/{external_id}",
        title=title,
        description="Description",
        budget=100.0,
        currency="UZS",
        region="Tashkent",
        deadline=datetime(2026, 6, 20, tzinfo=timezone.utc),
        status=TenderStatus.OPEN,
        category="Other",
    )


@unittest.skipUnless(HAS_BACKEND_DEPS, "SQLAlchemy is not installed")
class TenderSourceFoundationTests(unittest.IsolatedAsyncioTestCase):
    async def test_upsert_prevents_duplicate_canonical_source_key(self) -> None:
        session = _FakeSession()

        first, first_created = await upsert_tender(
            session,
            _normalized(title="Original"),
        )
        second, second_created = await upsert_tender(
            session,
            _normalized(title="Updated"),
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.id, second.id)
        self.assertEqual(session.add_count, 1)
        self.assertEqual(second.title, "Updated")

    async def test_same_external_id_can_exist_across_sources(self) -> None:
        session = _FakeSession()

        wb, wb_created = await upsert_tender(
            session,
            _normalized(source_system="world_bank", external_id="123"),
        )
        adb, adb_created = await upsert_tender(
            session,
            _normalized(source_system="adb", external_id="123"),
        )

        self.assertTrue(wb_created)
        self.assertTrue(adb_created)
        self.assertNotEqual(wb.canonical_source_key, adb.canonical_source_key)
        self.assertEqual(set(session.items), {"world_bank:123", "adb:123"})

    async def test_upsert_falls_back_to_source_system_external_id(self) -> None:
        session = _FakeSession()
        existing = Tender(
            source_system="uzex",
            external_id="488105",
            canonical_source_key="uzex:legacy:placeholder",
            source_url="https://example.test/old",
            title="Existing",
            budget=10.0,
            currency="UZS",
            status=TenderStatus.OPEN,
            category="Other",
        )
        session.add_existing_pair_only(existing)

        tender, created = await upsert_tender(
            session,
            _normalized(external_id="488105", title="Updated by source pair"),
        )

        self.assertFalse(created)
        self.assertEqual(tender.id, existing.id)
        self.assertEqual(tender.canonical_source_key, "uzex:488105")
        self.assertEqual(tender.title, "Updated by source pair")
        self.assertEqual(session.add_count, 0)


if __name__ == "__main__":
    unittest.main()
