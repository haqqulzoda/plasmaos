"""Focused reproducibility snapshot regression checks."""

from pathlib import Path
import unittest

from app.core.reproducibility import (
    annotate_evidence_validation,
    marker_counts,
    requirement_fingerprint,
    sanitize_internal_requirement_diagnostics,
    sha256_text,
    stable_json_sha256,
)


ROOT = Path(__file__).resolve().parent


class ReproducibilitySnapshotTests(unittest.TestCase):
    def test_requirement_fingerprint_is_stable(self) -> None:
        left = {
            "source_filename": " Tender.PDF ",
            "source_page": 3,
            "exact_quote": "Must   hold ISO 9001",
        }
        right = {
            "source_filename": "tender.pdf",
            "source_page": 3,
            "exact_quote": "must hold iso 9001",
        }

        self.assertEqual(requirement_fingerprint(left), requirement_fingerprint(right))

    def test_sanitizer_preserves_customer_fields_only_removing_diagnostics(self) -> None:
        payload = {
            "failed_dealbreakers": [
                {
                    "source_filename": "req.pdf",
                    "source_page": 4,
                    "exact_quote": "valid license required",
                    "validation_status": "accepted",
                    "source_verified": True,
                    "requirement_scope": "eligibility",
                    "scope_review_status": "accepted",
                    "affects_bid_eligibility": True,
                    "eligibility_reason": "Explicit bid-stage requirement.",
                    "vault_match_type": "license",
                    "vault_match_source": "Company Vault",
                    "vault_match_confidence": 0.0,
                    "vault_missing_reason": "No matching license.",
                    "requirement_fingerprint": "internal",
                    "final_bucket": "failed",
                    "source_key": "internal",
                    "source_chunk_index": 1,
                }
            ]
        }

        sanitized = sanitize_internal_requirement_diagnostics(payload)
        detail = sanitized["failed_dealbreakers"][0]

        for field in (
            "source_filename",
            "source_page",
            "exact_quote",
            "validation_status",
            "source_verified",
            "requirement_scope",
            "scope_review_status",
            "affects_bid_eligibility",
            "eligibility_reason",
            "vault_match_type",
            "vault_match_source",
            "vault_match_confidence",
            "vault_missing_reason",
        ):
            self.assertIn(field, detail)

        for field in (
            "requirement_fingerprint",
            "final_bucket",
            "source_key",
            "source_chunk_index",
        ):
            self.assertNotIn(field, detail)

    def test_hashes_are_stable_and_vault_changes_are_detected(self) -> None:
        text = "[[FILE: a.pdf]]\n[[PAGE 1]]\nhello"
        self.assertEqual(sha256_text(text), sha256_text(text))
        self.assertEqual(
            marker_counts(text),
            {"file_marker_count": 1, "page_marker_count": 1},
        )

        vault = {
            "certifications": [{"cert_type": "ISO 9001", "expiry_date": "2029-01-01"}],
            "licenses": [],
            "financial_history": [],
        }
        changed_vault = {
            "certifications": [{"cert_type": "ISO 9001", "expiry_date": "2030-01-01"}],
            "licenses": [],
            "financial_history": [],
        }
        self.assertNotEqual(stable_json_sha256(vault), stable_json_sha256(changed_vault))

    def test_evidence_validation_final_buckets_include_skipped_and_rejected(self) -> None:
        evidence_validation = {
            "accepted_requirements": [
                {
                    "source_filename": "accepted.pdf",
                    "source_page": 1,
                    "exact_quote": "accepted quote",
                }
            ],
            "needs_review_requirements": [],
            "rejected_requirements": [
                {
                    "source_filename": "rejected.pdf",
                    "source_page": 2,
                    "exact_quote": "rejected quote",
                }
            ],
        }

        annotated = annotate_evidence_validation(evidence_validation)

        self.assertEqual(
            annotated["accepted_requirements"][0]["final_bucket"],
            "skipped",
        )
        self.assertEqual(
            annotated["rejected_requirements"][0]["final_bucket"],
            "rejected_internal",
        )

    def test_admin_endpoint_is_gated_and_no_raw_text_fields_are_returned(self) -> None:
        admin_source = (ROOT / "app/api/endpoints/admin.py").read_text(encoding="utf-8")

        self.assertIn('"/tenders/{source_system}/{external_id}/reproducibility"', admin_source)
        self.assertIn("Depends(require_admin)", admin_source)
        self.assertNotIn("compiled_master_text", admin_source)
        self.assertNotIn("parsed_text", admin_source)
        self.assertNotIn("raw_extracted_text", admin_source)
        self.assertNotIn("storage_path", admin_source)

    def test_extraction_artifact_metadata_has_no_raw_chunk_text_field(self) -> None:
        extractor_source = (
            ROOT / "app/core/agents/requirement_extractor.py"
        ).read_text(encoding="utf-8")
        class_block = extractor_source.split(
            "class ExtractionChunkArtifactMetadata", 1
        )[1].split("class RequirementExtractionResult", 1)[0]

        self.assertIn("class ExtractionChunkArtifactMetadata", extractor_source)
        self.assertIn("chunk_input_sha256", class_block)
        self.assertIn("extraction_status", class_block)
        self.assertNotIn("chunk_text", class_block)


if __name__ == "__main__":
    unittest.main()
