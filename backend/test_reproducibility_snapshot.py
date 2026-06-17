"""Focused reproducibility snapshot regression checks."""

from pathlib import Path
import unittest

from app.core.reproducibility import (
    annotate_evidence_validation,
    canonical_marker_text_sha256,
    canonicalize_source_file_markers,
    canonical_source_filename,
    marker_counts,
    requirement_fingerprint,
    sanitize_internal_requirement_diagnostics,
    sha256_text,
    stable_document_order_key,
    stable_json_sha256,
)
from scripts.diff_reproducibility import diff_exports


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

    def test_canonical_filename_strips_only_leading_storage_prefix(self) -> None:
        self.assertEqual(
            canonical_source_filename(
                "9f9b459c6be84b5195ac57f01959f05f_202605080127313776.pdf"
            ),
            "202605080127313776.pdf",
        )
        self.assertEqual(
            canonical_source_filename("202605061439940377.pdf"),
            "202605061439940377.pdf",
        )
        self.assertEqual(
            canonical_source_filename(
                "/tmp/a/b/537c55e479b941d1b2af31f3b2b6acbe_Report%20Final.PDF"
            ),
            "report final.pdf",
        )

    def test_requirement_fingerprint_ignores_32_hex_storage_prefixes(self) -> None:
        left = {
            "source_filename": "1900a7f9e29143af90aef0f62b29655f_202605080127313776.pdf",
            "source_page": 2,
            "exact_quote": "Must submit ISO certificate.",
        }
        right = {
            "source_filename": "9f9b459c6be84b5195ac57f01959f05f_202605080127313776.pdf",
            "source_page": 2,
            "exact_quote": "must submit iso certificate.",
        }

        self.assertEqual(requirement_fingerprint(left), requirement_fingerprint(right))

    def test_requirement_fingerprint_keeps_meaningful_basename_differences(self) -> None:
        left = {
            "source_filename": "1900a7f9e29143af90aef0f62b29655f_202605080127313776.pdf",
            "source_page": 2,
            "exact_quote": "Must submit ISO certificate.",
        }
        right = {
            "source_filename": "9f9b459c6be84b5195ac57f01959f05f_202605061439940377.pdf",
            "source_page": 2,
            "exact_quote": "Must submit ISO certificate.",
        }

        self.assertNotEqual(requirement_fingerprint(left), requirement_fingerprint(right))

    def test_unicode_cyrillic_filename_normalizes_safely(self) -> None:
        self.assertEqual(
            canonical_source_filename("Proform sokh 23.04.26 для ИП.docx"),
            "proform sokh 23.04.26 для ип.docx",
        )

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
                    "source_filename_display": "req.pdf",
                    "source_filename_canonical": "req.pdf",
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
            "source_filename_display",
            "source_filename_canonical",
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

    def test_document_snapshot_includes_canonical_filename_metadata(self) -> None:
        tenders_source = (
            ROOT / "app/api/endpoints/tenders.py"
        ).read_text(encoding="utf-8")

        self.assertIn("display_name_canonical", tenders_source)
        self.assertIn("parsed_source_filenames_canonical", tenders_source)
        self.assertIn("archive_inner_filenames_canonical", tenders_source)
        self.assertIn("parsed_text_canonical_marker_sha256", tenders_source)
        self.assertIn("document_order_fingerprint", tenders_source)
        self.assertIn("ordered_canonical_filenames", tenders_source)

    def test_deterministic_document_order_for_compiled_text(self) -> None:
        documents = [
            {
                "display_name": "202605080127313776.pdf",
                "file_type": "pdf",
                "file_size": 98844,
                "parsed_text": (
                    "[[FILE: 1900a7f9e29143af90aef0f62b29655f_"
                    "202605080127313776.pdf]]\n[[PAGE 1]]\npdf text"
                ),
            },
            {
                "display_name": "202605045405367256.docx",
                "file_type": "docx",
                "file_size": 55578,
                "parsed_text": (
                    "[[FILE: 202605045405367256.docx]]\n"
                    "[[PAGE 1]]\ndocx text"
                ),
            },
            {
                "display_name": "202605061439940377.pdf",
                "file_type": "pdf",
                "file_size": 4520294,
                "parsed_text": (
                    "[[FILE: 47a7598d7d734fe688e97b365a201ea6_"
                    "202605061439940377.pdf]]\n[[PAGE 1]]\nlarge pdf text"
                ),
            },
        ]
        reversed_documents = [
            {
                **item,
                "parsed_text": item["parsed_text"].replace(
                    "1900a7f9e29143af90aef0f62b29655f_",
                    "9f9b459c6be84b5195ac57f01959f05f_",
                ).replace(
                    "47a7598d7d734fe688e97b365a201ea6_",
                    "537c55e479b941d1b2af31f3b2b6acbe_",
                ),
            }
            for item in reversed(documents)
        ]

        def build_compiled_text(items: list[dict[str, object]]) -> str:
            entries = [
                (
                    stable_document_order_key(
                        source_filename=item["display_name"],
                        file_type=item["file_type"],
                        file_size=item["file_size"],
                        parsed_text=str(item["parsed_text"]),
                    ),
                    f"[{item['display_name']}]\n{item['parsed_text']}",
                )
                for item in items
            ]
            return "\n\n".join(text for _, text in sorted(entries, key=lambda item: item[0]))

        def order_fingerprint(items: list[dict[str, object]]) -> str:
            payload = [
                {
                    "display_name_canonical": canonical_source_filename(
                        item["display_name"]
                    ),
                    "file_type": item["file_type"],
                    "file_size": item["file_size"],
                    "parsed_text_canonical_marker_sha256": canonical_marker_text_sha256(
                        str(item["parsed_text"])
                    ),
                }
                for item in sorted(
                    items,
                    key=lambda item: stable_document_order_key(
                        source_filename=item["display_name"],
                        file_type=item["file_type"],
                        file_size=item["file_size"],
                        parsed_text=str(item["parsed_text"]),
                    ),
                )
            ]
            return stable_json_sha256(payload)

        left_text = build_compiled_text(documents)
        right_text = build_compiled_text(reversed_documents)

        self.assertTrue(left_text.startswith("[202605045405367256.docx]"))
        self.assertTrue(right_text.startswith("[202605045405367256.docx]"))
        self.assertEqual(
            sha256_text(canonicalize_source_file_markers(left_text)),
            sha256_text(canonicalize_source_file_markers(right_text)),
        )
        self.assertEqual(order_fingerprint(documents), order_fingerprint(reversed_documents))

    def test_diff_uses_canonical_filename_to_avoid_false_only_differences(self) -> None:
        local = {
            "latest_analyses": [
                {
                    "requirement_route_summary": [
                        {
                            "requirement_fingerprint": "local-old-fingerprint",
                            "final_bucket": "failed",
                            "source_filename": (
                                "1900a7f9e29143af90aef0f62b29655f_"
                                "202605080127313776.pdf"
                            ),
                            "source_page": 2,
                            "exact_quote": "Must submit ISO certificate.",
                        }
                    ]
                }
            ]
        }
        prod = {
            "latest_analyses": [
                {
                    "requirement_route_summary": [
                        {
                            "requirement_fingerprint": "prod-old-fingerprint",
                            "final_bucket": "failed",
                            "source_filename": (
                                "9f9b459c6be84b5195ac57f01959f05f_"
                                "202605080127313776.pdf"
                            ),
                            "source_page": 2,
                            "exact_quote": "must submit iso certificate.",
                        }
                    ]
                }
            ]
        }

        diff = diff_exports(local, prod)

        self.assertEqual(diff["local_only_fingerprint"], [])
        self.assertEqual(diff["prod_only_fingerprint"], [])


if __name__ == "__main__":
    unittest.main()
