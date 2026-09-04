"""Regression checks for tender document availability derivation."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
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
        self.assertIn("_document_download_status(", summary_block)
        self.assertIn('"downloadable_document_count"', summary_block)
        self.assertIn('"missing_file_document_count"', summary_block)
        self.assertIn('"parsed_document_count"', summary_block)
        self.assertIn("TenderDocument.storage_path", summary_block)
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

    def test_frontend_status_labels_are_source_neutral(self) -> None:
        tender_types = (ROOT.parent / "frontend/types/tender.ts").read_text(
            encoding="utf-8"
        )
        tender_detail_page = (
            ROOT.parent / "frontend/app/dashboard/tenders/[tenderId]/page.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("return 'Ready for analysis'", tender_types)
        self.assertIn("return 'Document discovered'", tender_types)
        self.assertIn("return 'Partial coverage'", tender_types)
        self.assertIn("return 'Preparation failed'", tender_types)
        self.assertIn("return 'Prepare documents for analysis'", tender_types)
        # Sprint 5.3 consumes the bounded details DTO, whose coarse document
        # availability contract is deliberately source-neutral and does not
        # expose format/parser-specific preparation state.
        self.assertIn('item.availability === "AVAILABLE"', tender_detail_page)
        self.assertIn('item.availability === "UNAVAILABLE"', tender_detail_page)
        self.assertIn('t("sectionState.available")', tender_detail_page)
        self.assertIn('t("sectionState.unavailable")', tender_detail_page)
        self.assertIn('t("metadataOnly")', tender_detail_page)
        self.assertNotIn("Unsupported format", tender_detail_page)
        self.assertIn("return 'Documents unavailable'", tender_types)

    def test_failed_extraction_response_does_not_claim_compliance(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")
        analyze_route = tenders.split("async def analyze_tender", 1)[1].split(
            '@router.post("/test-scrape"',
            1,
        )[0]

        self.assertIn("analysis_status = \"failed\"", analyze_route)
        self.assertIn("is_eligible=False", analyze_route)
        self.assertIn("FAILED_EXTRACTION_STATUS_MESSAGE", analyze_route)
        self.assertIn("_public_coverage_metadata_payload(", analyze_route)


@unittest.skipUnless(HAS_BACKEND_DEPS, "Backend dependencies are not installed")
class TenderDocumentStatusBehaviorTests(unittest.TestCase):
    def test_uzex_stored_and_legacy_docs_are_available(self) -> None:
        assert tender_endpoints is not None

        with TemporaryDirectory() as temp_dir:
            stored_file = Path(temp_dir) / "file.pdf"
            stored_file.write_bytes(b"%PDF-1.4")
            self.assertEqual(
                tender_endpoints._document_download_status(
                    _doc(storage_path=str(stored_file)),
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

    def test_missing_stored_file_is_not_listed_as_available(self) -> None:
        assert tender_endpoints is not None

        self.assertEqual(
            tender_endpoints._document_download_status(
                _doc(storage_path="/data/documents/tender/missing-file.pdf"),
                source_system="uzex",
            ),
            "missing_file",
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

    def test_missing_file_aggregate_is_not_documents_available(self) -> None:
        assert tender_endpoints is not None

        summary = tender_endpoints._empty_tender_summary(has_compiled_text=True)
        summary.update(
            document_count=1,
            missing_file_document_count=1,
            parsed_document_count=1,
        )

        self.assertEqual(
            tender_endpoints._document_status_from_summary(summary),
            "files_missing",
        )
        self.assertIsNone(
            tender_endpoints._compliance_unavailable_reason(
                source_system="uzex",
                has_compiled_text=True,
                document_status="files_missing",
            )
        )

    def test_downloadable_aggregate_means_documents_available(self) -> None:
        assert tender_endpoints is not None

        summary = tender_endpoints._empty_tender_summary()
        summary.update(
            document_count=1,
            downloadable_document_count=1,
            available_document_count=1,
        )

        self.assertEqual(
            tender_endpoints._document_status_from_summary(summary),
            "documents_available",
        )

    def test_access_required_aggregate_remains_access_required(self) -> None:
        assert tender_endpoints is not None

        summary = tender_endpoints._empty_tender_summary()
        summary.update(
            document_count=1,
            access_required=True,
        )

        self.assertEqual(
            tender_endpoints._document_status_from_summary(summary),
            "access_required",
        )

    def test_failed_aggregate_wins_over_available_and_blocks_compliance(self) -> None:
        assert tender_endpoints is not None

        summary = tender_endpoints._empty_tender_summary(has_compiled_text=True)
        summary.update(
            document_count=2,
            downloadable_document_count=1,
            available_document_count=1,
            failed_document_count=1,
        )
        document_status = tender_endpoints._document_status_from_summary(summary)

        self.assertEqual(document_status, "failed")
        self.assertEqual(
            tender_endpoints._compliance_unavailable_reason(
                source_system="uzex",
                has_compiled_text=True,
                document_status=document_status,
            ),
            "Preparation failed",
        )

    def test_explicit_failed_status_is_not_legacy_uzex_available(self) -> None:
        assert tender_endpoints is not None

        self.assertEqual(
            tender_endpoints._document_download_status(
                _doc(
                    download_status="failed",
                    file_url="https://etender.uzex.uz/files/failed.pdf",
                ),
                source_system="uzex",
            ),
            "failed",
        )

    def test_public_coverage_metadata_hides_provider_technical_warnings(self) -> None:
        assert tender_endpoints is not None

        coverage = {
            "coverage_status": "failed",
            "chunk_count": 3,
            "technical_warnings": ["provider project permission detail"],
        }

        public_payload = tender_endpoints._public_coverage_metadata_payload(
            coverage,
            include_debug=False,
        )
        debug_payload = tender_endpoints._public_coverage_metadata_payload(
            coverage,
            include_debug=True,
        )

        self.assertNotIn("technical_warnings", public_payload)
        self.assertEqual(
            debug_payload["technical_warnings"],
            ["provider project permission detail"],
        )

    def test_failed_analysis_public_payloads_do_not_claim_success(self) -> None:
        assert tender_endpoints is not None

        evaluation = {
            "is_compliant": True,
            "status_message": "Compliant: all mapped requirements are satisfied.",
        }
        hybrid = {
            "is_eligible": True,
            "verdict_status": "COMPLIANT",
            "status_message": "Compliant.",
        }

        public_evaluation = tender_endpoints._failed_analysis_evaluation_payload(
            evaluation
        )
        public_hybrid = tender_endpoints._failed_analysis_hybrid_payload(hybrid)

        self.assertFalse(public_evaluation["is_compliant"])
        self.assertFalse(public_hybrid["is_eligible"])
        self.assertEqual(public_hybrid["verdict_status"], "NEEDS_REVIEW")
        self.assertIn("ANALYSIS FAILED", public_evaluation["status_message"])
        self.assertIn("ANALYSIS FAILED", public_hybrid["status_message"])


if __name__ == "__main__":
    unittest.main()
