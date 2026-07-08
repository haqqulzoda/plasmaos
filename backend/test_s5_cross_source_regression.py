"""S5.0.4 cross-source document ingestion regression gate."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


ROOT = Path(__file__).resolve().parent


try:
    from app.models.all_models import TenderDocument
    from app.services.tender_sources.adb import AdbTenderSource
    from app.services.tender_sources.base import CanonicalDocument, NormalizedTender
    from app.services.tender_sources.ebrd import EbrdTenderSource
    from app.services.tender_sources.giz import GizTenderSource
    from app.services.tender_sources.world_bank import WorldBankTenderSource
    from app.workers import tender_tasks
except ModuleNotFoundError as exc:  # pragma: no cover - local minimal env
    if exc.name in {
        "celery",
        "fastapi",
        "httpx",
        "playwright",
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
    }:
        HAS_BACKEND_DEPS = False
        TenderDocument = None
        AdbTenderSource = None
        CanonicalDocument = None
        EbrdTenderSource = None
        NormalizedTender = None
        GizTenderSource = None
        WorldBankTenderSource = None
        tender_tasks = None
    else:
        raise
else:
    HAS_BACKEND_DEPS = True


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeDocumentSession:
    def __init__(self):
        self.docs = []
        self.execute_count = 0
        self.add_count = 0

    async def execute(self, statement):
        self.execute_count += 1
        values = {}

        def visit(criterion) -> None:
            clauses = getattr(criterion, "clauses", None)
            if clauses is not None:
                for clause in clauses:
                    visit(clause)
                return

            left = str(getattr(criterion, "left", ""))
            right = getattr(criterion, "right", None)
            value = getattr(right, "value", None)
            if left.endswith("tender_id"):
                values["tender_id"] = value
            elif left.endswith("source_document_url"):
                values["source_document_url"] = value
            elif left.endswith("external_file_id"):
                values["external_file_id"] = value

        for criterion in getattr(statement, "_where_criteria", ()):
            visit(criterion)

        for doc in self.docs:
            if values.get("tender_id") is not None and doc.tender_id != values["tender_id"]:
                continue
            if values.get("source_document_url") and doc.source_document_url == values["source_document_url"]:
                return _FakeResult(doc)
            if values.get("external_file_id") and doc.external_file_id == values["external_file_id"]:
                return _FakeResult(doc)
        return _FakeResult(None)

    def add(self, doc):
        self.add_count += 1
        self.docs.append(doc)


def _tender(source_system: str):
    external_id = "same-external-id"
    return SimpleNamespace(
        id=uuid4(),
        source_system=source_system,
        external_id=external_id,
        canonical_source_key=f"{source_system}:{external_id}",
    )


class CrossSourceStaticGateTests(unittest.TestCase):
    def test_active_sync_routes_use_canonical_document_flow(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")
        world_bank_block = tenders.split("async def sync_world_bank_tenders", 1)[1].split(
            "@router.post",
            1,
        )[0]
        giz_block = tenders.split("async def sync_giz_tenders", 1)[1].split(
            '"/sources/adb/sync"',
            1,
        )[0]
        adb_block = tenders.split("async def sync_adb_tenders", 1)[1].split(
            "async def _count_parsed_documents",
            1,
        )[0]
        ebrd_block = tenders.split("async def sync_ebrd_tenders", 1)[1].split(
            '"/sources/adb/sync"',
            1,
        )[0]

        for block in (world_bank_block, giz_block, adb_block, ebrd_block):
            self.assertIn("discover_documents", block)
            self.assertIn("upsert_documents", block)
            self.assertNotIn("discover_attachments", block)
            self.assertNotIn("upsert_attachments", block)

    def test_document_write_paths_are_source_guarded(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")
        worker = read("app/workers/tender_tasks.py")
        hunter = read("app/workers/hunter_tasks.py")
        giz_hydration = read("app/services/giz_document_hydration.py")
        world_bank = read("app/services/tender_sources/world_bank.py")
        adb = read("app/services/tender_sources/adb.py")
        ebrd = read("app/services/tender_sources/ebrd.py")
        giz = read("app/services/tender_sources/giz.py")

        self.assertIn('assert_source_scope("uzex", tender)', worker)
        self.assertIn('assert_source_scope("giz", tender)', worker)
        self.assertIn('assert_source_scope("giz", tender)', giz_hydration)
        self.assertIn('assert_source_scope("giz", tender)', tenders)
        self.assertIn("assert_source_scope(self.source_system, tender)", world_bank)
        self.assertIn("assert_source_scope(self.source_system, tender)", adb)
        self.assertIn("assert_source_scope(self.source_system, tender)", ebrd)
        self.assertIn('assert_source_scope("giz", tender)', giz)
        self.assertIn('source_system != "uzex"', tenders)
        self.assertIn("Document sync worker is UzEx-only", tenders)
        self.assertIn('tender.source_system != "uzex"', hunter)
        self.assertIn("hydrate_giz_documents", worker)
        self.assertIn("hydrate_giz_documents.apply_async", tenders)
        self.assertIn('queue="heavy_dl_queue"', tenders)
        self.assertIn('routing_key="heavy_dl_queue"', tenders)

    def test_source_sync_does_not_touch_analysis_rows(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")
        source_sync_region = tenders.split("async def sync_world_bank_tenders", 1)[1].split(
            "def _serialize_sync_job",
            1,
        )[0]

        self.assertNotIn("TenderAnalysis", source_sync_region)
        self.assertNotIn(".analyses", source_sync_region)

    def test_tender_model_keeps_source_unique_indexes(self) -> None:
        model = read("app/models/all_models.py")

        self.assertIn('"source_system",', model)
        self.assertIn('"external_id",', model)
        self.assertIn("unique=True", model)
        self.assertIn('"ix_tenders_canonical_source_key"', model)


@unittest.skipUnless(HAS_BACKEND_DEPS, "Backend dependencies are not installed")
class CrossSourceBehaviorTests(unittest.TestCase):
    def test_world_bank_document_upsert_is_source_scoped_and_idempotent(self) -> None:
        session = _FakeDocumentSession()
        source = WorldBankTenderSource()
        tender = _tender("world_bank")
        document = CanonicalDocument(
            source_system="world_bank",
            source_document_url="https://projects.worldbank.org/docs/bid.docx",
            file_type="docx",
            source_document_type="docx",
            external_file_id="wb-doc",
            download_status="metadata_only",
        )

        first = asyncio.run(source.upsert_documents(session, tender=tender, documents=[document]))
        second = asyncio.run(source.upsert_documents(session, tender=tender, documents=[document]))

        self.assertEqual(first, (1, 0))
        self.assertEqual(second, (0, 1))
        self.assertEqual(len(session.docs), 1)
        self.assertEqual(session.docs[0].download_status, "metadata_only")

        with self.assertRaises(ValueError):
            asyncio.run(source.upsert_documents(session, tender=_tender("giz"), documents=[document]))

    def test_adb_metadata_only_document_is_source_scoped_and_not_fabricated(self) -> None:
        session = _FakeDocumentSession()
        source = AdbTenderSource()
        tender = _tender("adb")
        document = CanonicalDocument(
            source_system="adb",
            source_document_url="https://www.adb.org/sites/default/files/tenders/a.pdf",
            file_type="pdf",
            source_document_type="notice_pdf",
            external_file_id="adb-hash",
            file_size=1234,
            mime_type="application/pdf",
            download_status="metadata_only",
        )

        created, updated = asyncio.run(
            source.upsert_documents(session, tender=tender, documents=[document])
        )

        self.assertEqual((created, updated), (1, 0))
        self.assertEqual(len(session.docs), 1)
        doc = session.docs[0]
        self.assertEqual(doc.download_status, "metadata_only")
        self.assertIsNone(doc.storage_path)
        self.assertIsNone(doc.parsed_text)

        with self.assertRaises(ValueError):
            asyncio.run(source.upsert_documents(session, tender=_tender("uzex"), documents=[document]))

    def test_giz_canonical_documents_are_metadata_only_and_cross_source_guarded(self) -> None:
        source = GizTenderSource(source_pages=[])
        normalized = NormalizedTender(
            source_system="giz",
            external_id="7000012992",
            source_url="https://www.giz.de/en/regions/africa/south-africa/tenders",
            title="GIZ tender",
            source_metadata_json={
                "attachments": [
                    {
                        "source_document_url": "https://www.giz.de/sites/default/files/a.pdf",
                        "source_document_type": "pdf",
                    }
                ]
            },
        )
        documents = asyncio.run(source.discover_documents(normalized))

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].normalized_source_system, "giz")
        self.assertEqual(documents[0].download_status, "metadata_only")

        for source_system in ("uzex", "world_bank", "adb"):
            with self.assertRaises(ValueError):
                asyncio.run(
                    source.upsert_documents(
                        _FakeDocumentSession(),
                        tender=_tender(source_system),
                        documents=documents,
                    )
                )

    def test_ebrd_documents_are_access_required_and_cross_source_guarded(self) -> None:
        source = EbrdTenderSource()
        normalized = NormalizedTender(
            source_system="ebrd",
            external_id="45376134",
            source_url="https://ecepp.ebrd.com/delta/viewNotice.html?displayNoticeId=45376255",
            title="EBRD notice",
            source_metadata_json={
                "document_access_url": "https://ecepp.ebrd.com/respond/7ABC123XYZ"
            },
        )
        documents = asyncio.run(source.discover_documents(normalized))

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].normalized_source_system, "ebrd")
        self.assertEqual(documents[0].download_status, "access_required")

        session = _FakeDocumentSession()
        self.assertEqual(
            asyncio.run(source.upsert_documents(session, tender=_tender("ebrd"), documents=documents)),
            (1, 0),
        )
        self.assertIsNone(session.docs[0].storage_path)
        self.assertIsNone(session.docs[0].parsed_text)

        for source_system in ("uzex", "world_bank", "adb", "giz"):
            with self.assertRaises(ValueError):
                asyncio.run(
                    source.upsert_documents(
                        _FakeDocumentSession(),
                        tender=_tender(source_system),
                        documents=documents,
                    )
                )

    def test_failed_refresh_preserves_existing_parsed_text(self) -> None:
        db = _FakeDocumentSession()
        tender_id = uuid4()
        existing = TenderDocument(
            id=uuid4(),
            tender_id=tender_id,
            file_url="/files/old.pdf",
            file_type="pdf",
            source_document_url="/files/old.pdf",
            download_status="downloaded",
            parsed_text="[[FILE: old.pdf]]\n[[PAGE 1]]\nStill usable.",
        )

        failed_doc, created = tender_tasks._mark_document_download_failed(
            db,
            doc=existing,
            tender_id=tender_id,
            scraped_url="/files/old.pdf",
            scraped_file_type="pdf",
            scraped_index=0,
            error=RuntimeError("simulated outage"),
        )

        self.assertFalse(created)
        self.assertIs(failed_doc, existing)
        self.assertIn("[[FILE: old.pdf]]", failed_doc.parsed_text)
        self.assertEqual(failed_doc.download_status, "failed")


if __name__ == "__main__":
    unittest.main()
