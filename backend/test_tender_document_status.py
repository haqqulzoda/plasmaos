"""Regression checks for tender document availability derivation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parent


try:
    from app.api.endpoints import tenders as tender_endpoints
except ModuleNotFoundError as exc:  # pragma: no cover - local minimal env
    if exc.name in {
        "fastapi",
        "httpx",
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
    }:
        tender_endpoints = None
        HAS_BACKEND_DEPS = False
    else:
        raise
else:
    HAS_BACKEND_DEPS = True


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _doc(
    *,
    download_status: str | None = None,
    storage_path: str | None = None,
    file_url: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        download_status=download_status,
        storage_path=storage_path,
        file_url=file_url,
    )


class TenderDocumentStatusStaticTests(unittest.TestCase):
    def test_batched_summary_uses_explicit_document_status_policy(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")
        summary_block = tenders.split("async def _batched_tender_summaries", 1)[
            1
        ].split("async def _single_tender_summary", 1)[0]

        self.assertIn('AVAILABLE_DOCUMENT_STATUSES = {"available", "downloaded"}', tenders)
        self.assertIn('"metadata_only"', summary_block)
        self.assertIn('lowered_status == "failed"', summary_block)
        self.assertIn('lowered_status == "processing"', summary_block)
        self.assertIn('Tender.source_system == "uzex"', summary_block)
        self.assertIn("TenderDocument.file_url", summary_block)
        self.assertIn(".join(Tender, TenderDocument.tender_id == Tender.id)", summary_block)

    def test_document_metadata_response_keeps_raw_locations_private(self) -> None:
        schema = read("app/schemas/tender.py")
        document_response = schema.split("class TenderDocumentResponse", 1)[1]
        tenders = read("app/api/endpoints/tenders.py")
        documents_route = tenders.split("async def get_tender_documents", 1)[1].split(
            "@router.get", 1
        )[0]

        self.assertNotIn("file_url:", document_response)
        self.assertNotIn("source_document_url", document_response)
        self.assertNotIn("storage_path", document_response)
        self.assertNotIn("parsed_text", document_response)
        self.assertIn("download_url", document_response)
        self.assertIn("select(Tender.source_system)", documents_route)
        self.assertIn("source_system=source_system", documents_route)

    def test_metadata_only_download_is_safe_404(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")
        download_route = tenders.split("async def download_document", 1)[1].split(
            '@router.get("", response_model=list[TenderResponse])', 1
        )[0]

        self.assertIn('raw_download_status == "metadata_only"', download_route)
        self.assertIn("status_code=404", download_route)
        self.assertNotIn("RedirectResponse", download_route)

    def test_frontend_status_labels_match_int4b_copy(self) -> None:
        tender_types = (ROOT.parent / "frontend/types/tender.ts").read_text(
            encoding="utf-8"
        )

        self.assertIn("return 'Documents available'", tender_types)
        self.assertIn("return 'PDF notice discovered'", tender_types)
        self.assertIn("return 'Processing documents'", tender_types)
        self.assertIn("return 'Document processing failed'", tender_types)
        self.assertIn("return 'No documents found'", tender_types)


@unittest.skipUnless(HAS_BACKEND_DEPS, "Backend dependencies are not installed")
class TenderDocumentStatusBehaviorTests(unittest.TestCase):
    def test_uzex_stored_and_legacy_docs_are_available(self) -> None:
        assert tender_endpoints is not None

        self.assertEqual(
            tender_endpoints._document_download_status(
                _doc(storage_path="/data/documents/tender/file.pdf"),
                source_system="uzex",
            ),
            "available",
        )
        self.assertEqual(
            tender_endpoints._document_download_status(
                _doc(
                    download_status="downloaded",
                    file_url="/api/common/downloadfile?path=/files/legacy.pdf",
                ),
                source_system="uzex",
            ),
            "available",
        )

    def test_adb_metadata_only_remains_metadata_only(self) -> None:
        assert tender_endpoints is not None

        self.assertEqual(
            tender_endpoints._document_download_status(
                _doc(
                    download_status="metadata_only",
                    file_url="https://www.adb.org/file.pdf",
                ),
                source_system="adb",
            ),
            "metadata_only",
        )

    def test_world_bank_zero_docs_remains_no_documents_found(self) -> None:
        assert tender_endpoints is not None

        self.assertEqual(
            tender_endpoints._document_status_from_summary(
                tender_endpoints._empty_tender_summary()
            ),
            "no_documents_found",
        )


if __name__ == "__main__":
    unittest.main()
