"""Sprint 5.2 static and focused read-model contracts."""

from __future__ import annotations

import inspect
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.api.endpoints import tenders as tender_endpoints
from app.schemas.tender_details import (
    ComplianceSummary,
    DetailsSectionState,
    TenderDetailsResponse,
    TenderDocumentSummaryItem,
)
from app.services import tender_details


class TenderDetailsContractTests(unittest.TestCase):
    def test_endpoint_is_secondary_approved_read(self) -> None:
        source = inspect.getsource(tender_endpoints.get_tender_details)
        self.assertIn("require_approved_pilot_access", inspect.getsource(tender_endpoints))
        self.assertIn("customer_visible_tender_condition", source)
        self.assertIn("compose_tender_details", source)
        self.assertNotIn("_apply_live_uzex_dates", source)
        self.assertNotIn("_world_bank_contact_metadata_override", source)

    def test_dependency_graph_has_no_write_or_external_dispatch(self) -> None:
        source = inspect.getsource(tender_details)
        for forbidden in (
            ".commit(",
            ".flush(",
            ".add(",
            "insert(",
            "update(",
            "delete(",
            "enqueue_",
            "httpx",
            "UzExTenderSource",
            "WorldBankTenderSource",
            "sync_tender",
            "decision_snapshot",
            "asyncio.gather",
        ):
            self.assertNotIn(forbidden, source)

    def test_compliance_authority_is_analysis_version_not_parent_mirror(self) -> None:
        source = inspect.getsource(tender_details)
        self.assertIn("require_latest_analysis_version", source)
        self.assertIn("version.result_snapshot", source)
        self.assertNotIn("analysis.analysis_json", source)
        self.assertNotIn("analysis.content_hash", source)

    def test_explicit_schema_has_no_unsafe_document_or_ambiguous_root_status(self) -> None:
        schema = TenderDetailsResponse.model_json_schema()
        root_properties = schema["properties"]
        self.assertNotIn("status", root_properties)
        serialized = str(schema).casefold()
        for unsafe in (
            "storage_path",
            "filesystem",
            "signed_url",
            "download_credential",
            "parsed_text",
            "content_hash",
            "analysis_json",
            "result_snapshot",
            "evidence_snapshot",
            "final_pdf_url",
        ):
            self.assertNotIn(unsafe, serialized)

    def test_document_contract_is_metadata_only_and_bounded(self) -> None:
        item = TenderDocumentSummaryItem(
            document_id=uuid4(),
            display_name="notice.pdf",
            document_type="notice",
            metadata_classification="PUBLIC_SOURCE_METADATA",
            source_system="world_bank",
            availability="METADATA_ONLY",
            created_at=datetime.now(timezone.utc),
        )
        payload = item.model_dump()
        self.assertNotIn("download_url", payload)
        self.assertNotIn("source_url", payload)
        self.assertEqual(tender_details.DOCUMENT_LIMIT, 25)
        self.assertEqual(tender_details.PROJECT_ROLE_LIMIT, 12)
        self.assertEqual(tender_details.REQUIREMENT_LIMIT, 12)

    def test_failed_compliance_cannot_be_labeled_compliant(self) -> None:
        decision, _, _ = tender_details._compliance_values(
            {"hybrid_compliance": {"verdict_status": "COMPLIANT"}},
            failed=True,
        )
        self.assertEqual(decision, "FAILED")

    def test_requirements_are_labeled_analysis_derived(self) -> None:
        section = tender_details._requirements_section(
            {
                "requirements": [
                    {
                        "requirement": "ISO 9001",
                        "evidence": {"document_name": "notice.pdf", "page": 3},
                    }
                ]
            }
        )
        self.assertEqual(section.state, DetailsSectionState.AVAILABLE)
        assert section.data is not None
        self.assertEqual(section.data.items[0].source_type, "ANALYSIS_DERIVED")
        self.assertFalse(section.data.source_native_available)

    def test_preflight_is_count_only_and_read_only(self) -> None:
        source = (
            inspect.getsource(
                __import__(
                    "scripts.run_s0_3_schema_data_preflight",
                    fromlist=["ReadOnlyPreflight"],
                ).ReadOnlyPreflight.tender_details_composition_audit
            )
        )
        for metric in (
            "tenders_total",
            "with_project",
            "proposal_only",
            "engagement_only",
            "compliance_only",
            "all_private_domains",
            "broken_project_links",
            "zero_version_analysis_parents",
        ):
            self.assertIn(metric, source)
        for mutation in ("INSERT ", "UPDATE ", "DELETE ", "CREATE "):
            self.assertNotIn(mutation, source)


if __name__ == "__main__":
    unittest.main()
