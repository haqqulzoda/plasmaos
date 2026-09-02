"""Focused SR-2.4 catalog, activity cursor, safety, and Tender newness tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
from types import MappingProxyType
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.api.endpoints import tenders
from app.core.tender_newness import TENDER_NEWNESS_WINDOW, tender_newness
from app.main import app
from app.models.all_models import SourceRefreshJob, Tender
from app.services.source_refresh_activity import (
    decode_activity_cursor,
    encode_activity_cursor,
    source_catalog,
    terminal_summary,
)
from app.services.source_registry import SOURCE_REGISTRY


BACKEND = Path(__file__).resolve().parent


class CatalogContractTests(TestCase):
    def test_catalog_uses_registry_visibility_and_disabled_semantics(self) -> None:
        visible = replace(SOURCE_REGISTRY["adb"], key="visible", display_name="Visible")
        hidden = replace(SOURCE_REGISTRY["giz"], key="hidden", customer_visible=False)
        disabled = replace(
            SOURCE_REGISTRY["ebrd"], key="disabled", display_name="Disabled",
            refresh_enabled=False,
        )
        catalog = source_catalog(MappingProxyType({
            "visible": visible, "hidden": hidden, "disabled": disabled,
        }))
        self.assertEqual([item.source_system for item in catalog], ["disabled", "visible"])
        self.assertFalse(catalog[0].can_refresh)
        self.assertTrue(catalog[1].can_refresh)

    def test_catalog_is_zero_database_query_and_labels_are_not_duplicated(self) -> None:
        source = inspect.getsource(source_catalog)
        self.assertNotIn("db", inspect.signature(source_catalog).parameters)
        self.assertNotIn("SOURCE_LABELS", (BACKEND / "app/api/endpoints/tenders.py").read_text())

    def test_known_disabled_source_is_denied_before_job_creation(self) -> None:
        disabled = replace(SOURCE_REGISTRY["adb"], refresh_enabled=False)
        with patch("app.api.endpoints.tenders.get_source_definition", return_value=disabled):
            with self.assertRaises(HTTPException) as raised:
                __import__("asyncio").run(tenders._request_source_refresh(
                    source_system="adb", force=False, current_user=object(), db=None,
                ))
        self.assertEqual(raised.exception.status_code, 503)


class ActivityContractTests(TestCase):
    def test_cursor_round_trip_is_timezone_aware_and_exclusive_positioned(self) -> None:
        completed = datetime(2026, 9, 1, 1, 2, 3, tzinfo=timezone.utc)
        job_id = uuid4()
        self.assertEqual(decode_activity_cursor(encode_activity_cursor(completed, job_id)), (completed, job_id))

    def test_invalid_and_oversized_cursors_fail_safely(self) -> None:
        for cursor in ("not-base64", "x" * 513):
            with self.assertRaises(HTTPException) as raised:
                decode_activity_cursor(cursor)
            self.assertEqual(raised.exception.status_code, 422)

    def test_terminal_mapper_preserves_partial_counts_and_authority_boundary(self) -> None:
        job = SourceRefreshJob(
            id=uuid4(), source_system="world_bank", status="partial",
            trigger_kind="customer", force=False, completed_at=datetime.now(timezone.utc),
            fetched_count=9, created_count=4, updated_count=2, unchanged_count=1,
            skipped_count=0, rejected_count=2, failed_count=2,
            documents_discovered_count=3, documents_queued_count=0,
            fallback_used=False, message="Refresh completed with issues.",
        )
        summary = terminal_summary(job)
        self.assertEqual((summary.status, summary.created_count, summary.failed_count), ("partial", 4, 2))
        self.assertTrue(summary.counts_authoritative)
        job.trigger_kind = None
        self.assertFalse(terminal_summary(job).counts_authoritative)

    def test_customer_schemas_exclude_internal_fields(self) -> None:
        openapi = app.openapi()
        serialized = str(openapi["components"]["schemas"])
        for schema_name in (
            "SourceCatalogItem", "SourceRefreshStatusItem",
            "SourceRefreshActivityEvent", "SourceRefreshActivityResponse",
        ):
            self.assertIn(schema_name, serialized)
        customer_schema = " ".join(
            str(openapi["components"]["schemas"][name])
            for name in openapi["components"]["schemas"]
            if name.startswith("SourceCatalog") or name.startswith("SourceRefreshActive")
            or name.startswith("SourceRefreshTerminal") or name.startswith("SourceRefreshActivity")
            or name.startswith("SourceRefreshStatus")
        )
        for forbidden in ("lease_owner", "lease_expires_at", "options_json", "requested_by_user_id", "task_id"):
            self.assertNotIn(forbidden, customer_schema)

    def test_activity_authority_is_job_created_count_not_tender_query(self) -> None:
        from app.services import source_refresh_activity as activity_service

        source = inspect.getsource(activity_service.source_refresh_activity)
        mapper = inspect.getsource(activity_service.terminal_summary)
        self.assertIn("trigger_kind.is_not(None)", source)
        self.assertIn("job.created_count", mapper)
        self.assertNotIn("select(Tender", source)


class TenderNewnessTests(TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    def test_exact_boundary_matrix_and_future_safety(self) -> None:
        matrix = (
            (self.now - timedelta(hours=23, minutes=59, seconds=59), True),
            (self.now - timedelta(hours=24), False),
            (self.now - timedelta(hours=24, seconds=1), False),
            (self.now, True),
            (self.now + timedelta(seconds=1), False),
        )
        for created_at, expected in matrix:
            with self.subTest(created_at=created_at):
                result = tender_newness(created_at, server_time=self.now)
                self.assertEqual(result.is_new, expected)
                self.assertEqual(result.new_until, created_at + TENDER_NEWNESS_WINDOW)

    def test_new_only_sql_uses_created_at_and_controlled_reference(self) -> None:
        statement, _ = tenders.apply_explorer_tender_filters(
            select(Tender), new_only=True, newness_reference_time=self.now,
        )
        sql = str(statement.whereclause)
        self.assertIn("tenders.created_at", sql)
        self.assertNotIn("publication_date", sql)
        self.assertNotIn("last_synced_at", sql)

    def test_newness_implementation_has_no_other_domain_authority(self) -> None:
        source = inspect.getsource(tender_newness)
        for forbidden in ("publication_date", "last_synced_at", "Recommendation", "AnalysisVersion", "document"):
            self.assertNotIn(forbidden, source)

    def test_publication_sync_recommendation_and_document_times_cannot_change_result(self) -> None:
        old = self.now - timedelta(days=10)
        self.assertFalse(tender_newness(old, server_time=self.now).is_new)
        recent = self.now - timedelta(minutes=2)
        self.assertTrue(tender_newness(recent, server_time=self.now).is_new)


class PassiveAndOpenApiTests(TestCase):
    def test_customer_get_routes_are_registered_and_passive(self) -> None:
        paths = app.openapi()["paths"]
        for path in (
            "/api/v1/tenders/sources/catalog",
            "/api/v1/tenders/sources/refresh-status",
            "/api/v1/tenders/sources/refresh-activity",
            "/api/v1/explorer/tenders",
        ):
            self.assertIn("get", paths[path])
        region = (BACKEND / "app/api/endpoints/tenders.py").read_text().split(
            "async def get_source_catalog", 1
        )[1].split("def _serialize_sync_job", 1)[0]
        for forbidden in ("db.add(", "commit(", "apply_async(", "list_opportunities(", "claim_source_refresh_job("):
            self.assertNotIn(forbidden, region)

    def test_explorer_openapi_exposes_new_only_and_newness_fields(self) -> None:
        schema = app.openapi()
        parameters = schema["paths"]["/api/v1/explorer/tenders"]["get"]["parameters"]
        self.assertIn("new_only", {item["name"] for item in parameters})
        summary = schema["components"]["schemas"]["ExplorerTenderSummary"]["properties"]
        self.assertTrue({"created_at", "is_new", "new_until"}.issubset(summary))
        self.assertIn("server_time", schema["components"]["schemas"]["ExplorerTenderListResponse"]["properties"])


if __name__ == "__main__":
    import unittest
    unittest.main()
