"""Regression checks for UzEx document worker failure handling."""

from __future__ import annotations

import unittest
from uuid import uuid4

try:
    from app.models.all_models import TenderDocument
    from app.workers import tender_tasks
except ModuleNotFoundError as exc:  # pragma: no cover - local minimal env
    if exc.name in {
        "celery",
        "sqlalchemy",
        "fastapi",
        "httpx",
        "playwright",
        "pydantic",
        "pydantic_settings",
    }:
        TenderDocument = None
        tender_tasks = None
        HAS_BACKEND_DEPS = False
    else:
        raise
else:
    HAS_BACKEND_DEPS = True


class _FakeDb:
    def __init__(self):
        self.added = []

    def add(self, item):
        self.added.append(item)


@unittest.skipUnless(HAS_BACKEND_DEPS, "Backend dependencies are not installed")
class TenderWorkerFailureHandlingTests(unittest.TestCase):
    def test_failed_download_row_records_private_strategy_errors(self) -> None:
        assert tender_tasks is not None

        db = _FakeDb()
        tender_id = uuid4()
        doc, created = tender_tasks._mark_document_download_failed(
            db,
            doc=None,
            tender_id=tender_id,
            scraped_url="https://etender.uzex.uz/files/a.pdf",
            scraped_file_type="pdf",
            scraped_index=2,
            error=RuntimeError("downloadfile-post: 500; static-file-url: timeout"),
        )

        self.assertTrue(created)
        self.assertEqual(db.added, [doc])
        self.assertEqual(doc.tender_id, tender_id)
        self.assertEqual(doc.file_url, "https://etender.uzex.uz/files/a.pdf")
        self.assertEqual(doc.source_document_url, doc.file_url)
        self.assertEqual(doc.file_type, "pdf")
        self.assertEqual(doc.download_status, "failed")
        self.assertIsNone(doc.storage_path)
        self.assertIn("attachment_index=2", doc.download_error)
        self.assertIn("downloadfile-post: 500", doc.download_error)
        self.assertIn("static-file-url: timeout", doc.download_error)

    def test_uzex_scraped_document_is_canonicalized_before_persistence(self) -> None:
        assert tender_tasks is not None

        document = tender_tasks._canonical_document_from_scraped(
            {
                "file_url": " https://etender.uzex.uz/files/a.pdf ",
                "file_type": " PDF ",
            }
        )

        self.assertEqual(document.normalized_source_system, "uzex")
        self.assertEqual(document.source_document_url, "https://etender.uzex.uz/files/a.pdf")
        self.assertEqual(document.file_url, document.source_document_url)
        self.assertEqual(document.file_type, "pdf")

    def test_failed_download_row_is_reused_on_repeated_sync(self) -> None:
        assert tender_tasks is not None

        db = _FakeDb()
        tender_id = uuid4()
        first_doc, created = tender_tasks._mark_document_download_failed(
            db,
            doc=None,
            tender_id=tender_id,
            scraped_url="/files/retry.docx",
            scraped_file_type="docx",
            scraped_index=0,
            error=RuntimeError("first failure"),
        )
        second_doc, second_created = tender_tasks._mark_document_download_failed(
            db,
            doc=first_doc,
            tender_id=tender_id,
            scraped_url="/files/retry.docx",
            scraped_file_type="docx",
            scraped_index=0,
            error=RuntimeError("second failure"),
        )

        self.assertTrue(created)
        self.assertFalse(second_created)
        self.assertIs(first_doc, second_doc)
        self.assertEqual(len(db.added), 1)
        self.assertIn("second failure", second_doc.download_error)

    def test_failed_rows_do_not_pollute_compiled_text_from_parsed_successes(self) -> None:
        assert TenderDocument is not None
        assert tender_tasks is not None

        tender_id = uuid4()
        parsed_doc = TenderDocument(
            id=uuid4(),
            tender_id=tender_id,
            file_url="/files/parsed.pdf",
            file_type="pdf",
            file_size=123,
            parsed_text="[[FILE: parsed.pdf]]\n[[PAGE 1]]\nSource-backed requirement",
        )
        failed_doc = TenderDocument(
            id=uuid4(),
            tender_id=tender_id,
            file_url="/files/failed.pdf",
            file_type="pdf",
            download_status="failed",
            parsed_text=None,
        )
        entries = {}

        tender_tasks._store_compiled_text_entry(
            entries,
            tender_tasks._document_identity_key(parsed_doc.file_url),
            parsed_doc,
            "parsed.pdf",
        )
        tender_tasks._store_compiled_text_entry(
            entries,
            tender_tasks._document_identity_key(failed_doc.file_url),
            failed_doc,
            "failed.pdf",
        )
        compiled_text = tender_tasks._join_compiled_text_entries(entries)

        self.assertIsNotNone(compiled_text)
        self.assertIn("[[FILE: parsed.pdf]]", compiled_text)
        self.assertIn("[[PAGE 1]]", compiled_text)
        self.assertNotIn("failed.pdf", compiled_text)


if __name__ == "__main__":
    unittest.main()
