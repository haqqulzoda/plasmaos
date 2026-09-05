"""Focused SR-2.3 registry, document, ADB, and metrics contracts."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
import inspect
from pathlib import Path
from unittest import TestCase
from unittest.mock import AsyncMock, patch

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.api.endpoints import tenders
from app.models.all_models import SourceRefreshJob, Tender, TenderStatus
from app.services.source_registry import (
    DocumentPolicy,
    SOURCE_REGISTRY,
    SourceExecutionResult,
    get_source_definition,
    validate_source_refresh_options,
)
from app.services.tender_sources import base
from app.services.tender_sources.adb import AdbTenderSource


BACKEND = Path(__file__).resolve().parent


class RegistryContractTests(TestCase):
    def test_registry_is_complete_immutable_and_truthful(self) -> None:
        self.assertEqual(
            set(SOURCE_REGISTRY), {"uzex", "world_bank", "giz", "adb", "ebrd"}
        )
        self.assertTrue(all(item.refresh_enabled for item in SOURCE_REGISTRY.values()))
        self.assertTrue(all(not item.supports_checkpoint for item in SOURCE_REGISTRY.values()))
        self.assertEqual(get_source_definition("world-bank").display_name, "World Bank")
        self.assertEqual(SOURCE_REGISTRY["adb"].document_policy, DocumentPolicy.ASYNC_ENRICHMENT)
        self.assertEqual(SOURCE_REGISTRY["ebrd"].document_policy, DocumentPolicy.ACCESS_REQUIRED)
        with self.assertRaises(TypeError):
            SOURCE_REGISTRY["fake"] = SOURCE_REGISTRY["adb"]  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            SOURCE_REGISTRY["adb"].refresh_enabled = False  # type: ignore[misc]

    def test_option_validation_is_registry_driven(self) -> None:
        self.assertEqual(
            validate_source_refresh_options("world_bank", {"max_pages": 3}),
            {"max_pages": 3},
        )
        with self.assertRaisesRegex(ValueError, "download_documents"):
            validate_source_refresh_options("adb", {"download_documents": True})
        with self.assertRaises(KeyError):
            get_source_definition("invented")

    def test_generic_orchestrator_has_no_source_dispatch_branch(self) -> None:
        source = inspect.getsource(tenders._run_source_refresh)
        self.assertNotIn("if source_system", source)
        self.assertNotIn("elif", source)
        self.assertIn("execute_source_refresh", source)

    def test_canonical_result_carries_truthful_optional_metrics(self) -> None:
        result = SourceExecutionResult("adb", "completed", "ok")
        self.assertIsNone(result.http_request_count)
        self.assertIsNone(result.checkpoint)


class AdbDecouplingTests(TestCase):
    def _normalized(self):
        return AdbTenderSource().normalize(
            {
                "guid": "12345",
                "link": "https://www.adb.org/node/12345",
                "title": "ADB notice",
                "source_kind": "official_current_listing",
            }
        )

    def test_metadata_discovery_performs_no_remote_or_pdf_work(self) -> None:
        source = AdbTenderSource()
        normalized = self._normalized()
        with (
            patch.object(source, "resolve_node_redirect", AsyncMock(side_effect=AssertionError)),
            patch.object(source, "fetch_notice_pdf_bytes", AsyncMock(side_effect=AssertionError)),
            patch.object(source, "fetch_contact_metadata", AsyncMock(side_effect=AssertionError)),
        ):
            documents = asyncio.run(source.discover_documents(normalized))
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].download_status, "metadata_only")
        self.assertEqual(
            documents[0].external_file_id,
            normalized.source_metadata_json["adb_document_candidate_id"],
        )

    def test_contact_keys_are_preserved_only_by_explicit_connector_contract(self) -> None:
        normalized = self._normalized()
        tender = Tender(
            source_system="adb", external_id="12345", canonical_source_key="adb:12345",
            source_url=normalized.source_url, title="old", budget=0, currency="USD",
            status=TenderStatus.OPEN, category="ADB",
            source_metadata_json={"email": "kept@example.test", "obsolete": "removed"},
        )
        values = base._source_values_for_existing(tender, normalized)
        self.assertEqual(values["source_metadata_json"]["email"], "kept@example.test")
        self.assertNotIn("obsolete", values["source_metadata_json"])

    def test_status_progression_is_monotonic(self) -> None:
        self.assertEqual(base._monotonic_document_status("processed", "metadata_only"), "processed")
        self.assertEqual(base._monotonic_document_status("failed", "metadata_only"), "metadata_only")
        self.assertEqual(base._monotonic_document_status("queued", "failed"), "queued")

    def test_commit_precedes_adb_dispatch_and_publish_count_is_success_only(self) -> None:
        source = inspect.getsource(tenders.sync_adb_tenders)
        self.assertLess(source.index("await db.commit()"), source.index("enrich_adb_document.apply_async"))
        publish_block = source.split("enrich_adb_document.apply_async", 1)[1]
        self.assertIn("documents_queued_count += 1", publish_block)
        self.assertIn("except Exception", publish_block)

    def test_async_writer_is_identity_fenced_and_non_destructive(self) -> None:
        worker = (BACKEND / "app/workers/tender_tasks.py").read_text(encoding="utf-8")
        self.assertIn("adb_document_candidate_id", worker)
        self.assertIn("expected_external_file_id", worker)
        self.assertNotIn('current_metadata[key] = contact.get(key)', worker)
        self.assertIn('contact.get(key) not in (None, "")', worker)


class DocumentAndMigrationTests(TestCase):
    def test_all_metadata_adapters_use_shared_batch_persistence(self) -> None:
        for name in ("world_bank.py", "giz.py", "adb.py", "ebrd.py"):
            source = (BACKEND / "app/services/tender_sources" / name).read_text(encoding="utf-8")
            body = source.split("async def upsert_documents", 1)[1]
            self.assertIn("persist_document_descriptors", body, name)
        helper = inspect.getsource(base.persist_document_descriptors)
        runtime = helper.split("urls = [", 1)[1]
        self.assertEqual(runtime.count("await db.execute("), 1)

    def test_ebrd_restricted_policy_never_dispatches(self) -> None:
        source = (BACKEND / "app/services/tender_sources/ebrd.py").read_text(encoding="utf-8")
        self.assertIn('download_status="access_required"', source)
        self.assertNotIn("apply_async", source)

    def test_additive_nullable_metrics_and_single_head(self) -> None:
        annotations = SourceRefreshJob.__annotations__
        for name in (
            "fetch_elapsed_ms", "normalize_elapsed_ms", "persist_elapsed_ms",
            "document_dispatch_elapsed_ms", "http_request_count",
            "http_retry_count", "http_failure_count",
        ):
            self.assertIn(name, annotations)
            self.assertTrue(SourceRefreshJob.__table__.c[name].nullable)
        config = Config(str(BACKEND / "alembic.ini"))
        script = ScriptDirectory.from_config(config)
        self.assertEqual(script.get_heads(), ["20260904_0001_s8_2_analysis_language"])


if __name__ == "__main__":
    import unittest
    unittest.main()
