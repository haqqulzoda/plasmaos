"""Focused non-destructive regression tests for SR-2.1 contracts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from app.api.endpoints.tenders import _sync_uzex_tenders
from app.models.all_models import Tender, TenderStatus
from app.services.tender_sources.base import (
    NormalizedTender,
    TenderBatchPersistenceResult,
    TenderPersistenceItem,
    TenderPersistenceOutcome,
    persist_tender_batch,
    source_owned_tender_snapshot,
)


BACKEND_DIR = Path(__file__).resolve().parent


def _normalized(**overrides: object) -> NormalizedTender:
    values: dict[str, object] = {
        "source_system": "uzex",
        "external_id": "sr21-unit-1",
        "source_url": "https://example.test/sr21-unit-1",
        "title": "Semantic tender",
        "description": "Source description",
        "budget": 123.0,
        "currency": "USD",
        "deadline": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "status": TenderStatus.OPEN,
        "category": "Other",
        "source_metadata_json": {
            "nested": {"b": 2, "a": 1},
            "facts": [{"id": 2}, {"id": 1}],
        },
    }
    values.update(overrides)
    return NormalizedTender(**values)  # type: ignore[arg-type]


class SemanticSnapshotTests(unittest.TestCase):
    def test_snapshot_excludes_observation_time_and_normalizes_json_order(self) -> None:
        first = _normalized(last_synced_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
        second = _normalized(
            last_synced_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
            source_metadata_json={
                "facts": [{"id": 1}, {"id": 2}],
                "nested": {"a": 1, "b": 2},
            },
        )

        self.assertEqual(
            source_owned_tender_snapshot(first),
            source_owned_tender_snapshot(second),
        )

    def test_snapshot_normalizes_equivalent_timezones(self) -> None:
        utc = _normalized(deadline=datetime(2026, 9, 1, tzinfo=timezone.utc))
        plus_five = _normalized(
            deadline=datetime(
                2026,
                9,
                1,
                5,
                tzinfo=timezone(timedelta(hours=5)),
            )
        )
        self.assertEqual(
            source_owned_tender_snapshot(utc),
            source_owned_tender_snapshot(plus_five),
        )

    def test_source_field_change_is_semantic(self) -> None:
        self.assertNotEqual(
            source_owned_tender_snapshot(_normalized()),
            source_owned_tender_snapshot(_normalized(title="Changed")),
        )

    def test_result_outcomes_are_mutually_exclusive_and_counted(self) -> None:
        tender = Tender(
            source_system="uzex",
            external_id="unit",
            canonical_source_key="uzex:unit",
            source_url="https://example.test/unit",
            title="Unit",
            budget=0,
            currency="USD",
            status=TenderStatus.OPEN,
            category="Other",
        )
        result = TenderBatchPersistenceResult(
            items=(
                TenderPersistenceItem(
                    canonical_source_key="uzex:unit",
                    tender=tender,
                    outcome=TenderPersistenceOutcome.UNCHANGED,
                ),
            )
        )
        self.assertEqual(
            (result.created_count, result.updated_count, result.unchanged_count),
            (0, 0, 1),
        )


class OrchestrationTruthTests(unittest.TestCase):
    def test_uzex_commit_failure_publishes_zero_successful_write_counts(self) -> None:
        normalized = _normalized()
        tender = Tender(
            source_system="uzex",
            external_id=normalized.external_id,
            canonical_source_key=normalized.canonical_source_key,
            source_url=normalized.source_url,
            title=normalized.title,
            budget=normalized.budget,
            currency=normalized.currency,
            status=normalized.status,
            category=normalized.category,
        )
        persistence = TenderBatchPersistenceResult(
            items=(
                TenderPersistenceItem(
                    canonical_source_key=normalized.canonical_source_key,
                    tender=tender,
                    outcome=TenderPersistenceOutcome.CREATED,
                ),
            )
        )
        db = SimpleNamespace(
            commit=AsyncMock(side_effect=RuntimeError("forced commit failure")),
            rollback=AsyncMock(),
        )
        scraper = SimpleNamespace(fetch_latest_tenders=AsyncMock(return_value=[object()]))
        source = SimpleNamespace(normalize=lambda _raw: normalized)
        with (
            patch("app.api.endpoints.tenders.UzExScraper", return_value=scraper),
            patch("app.api.endpoints.tenders.UzExTenderSource", return_value=source),
            patch(
                "app.api.endpoints.tenders.persist_tender_batch",
                AsyncMock(return_value=persistence),
            ),
        ):
            response = asyncio.run(_sync_uzex_tenders(db=db))

        self.assertEqual(response.status, "source_unavailable")
        self.assertEqual(
            (response.new_count, response.updated_count, response.unchanged_count),
            (0, 0, 0),
        )
        db.rollback.assert_awaited_once()


class StaticIngestionAuditTests(unittest.TestCase):
    def test_normal_runtime_routes_do_not_call_single_row_upsert(self) -> None:
        source = (BACKEND_DIR / "app/api/endpoints/tenders.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("await source.upsert(db, normalized)", source)
        self.assertEqual(source.count("await persist_tender_batch("), 6)

    def test_unchanged_branch_does_not_assign_tender_fields(self) -> None:
        source = inspect.getsource(persist_tender_batch)
        unchanged_branch = source.split("if not changed_fields:", 1)[1].split(
            "for field_name in changed_fields:",
            1,
        )[0]
        self.assertNotIn("setattr(", unchanged_branch)
        self.assertNotIn("last_synced_at =", unchanged_branch)

    def test_conflict_safe_insert_is_the_created_authority(self) -> None:
        source = inspect.getsource(persist_tender_batch)
        self.assertIn(".on_conflict_do_nothing()", source)
        self.assertIn(".returning(Tender)", source)
        self.assertIn("if key in created:", source)


if __name__ == "__main__":
    unittest.main()
