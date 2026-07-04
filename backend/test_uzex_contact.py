"""Regression checks for UzEx contact metadata extraction."""

from __future__ import annotations

import unittest

from app.services.tender_sources.uzex_contact import (
    extract_uzex_contact_info,
    extract_uzex_trade_list_contact_metadata,
)


class UzExContactExtractionTests(unittest.TestCase):
    def test_extracts_get_trade_contact_submission_fields(self) -> None:
        metadata = extract_uzex_contact_info(
            {
                "customer_name": "Ministry Procurement Center",
                "customer_tin": "311894188",
                "customer_region_name": "Tashkent city",
                "customer_district_name": "Mirzo-Ulugbek district",
                "customer_street": "17-B Turkiston street",
                "delivering_phone": "977304478",
                "consider_procedure": "Electronic procedure",
                "end_date": "2026-07-01T20:03:30",
                "clarific_date": "2026-07-01T20:03:30",
                "contacts": (
                    '[{"Job_title":"Director ","Fullname":"Hikmat Usmanov"},'
                    '{"Job_title":"Department head","Fullname":"Tolqin Kushimov"}]'
                ),
            }
        )

        self.assertEqual(metadata["buyer_agency"], "Ministry Procurement Center")
        self.assertEqual(metadata["customer_tin"], "311894188")
        self.assertEqual(metadata["phone"], "977304478")
        self.assertEqual(metadata["submission_method"], "Electronic procedure")
        self.assertEqual(metadata["submission_deadline"], "2026-07-01T20:03:30")
        self.assertEqual(metadata["question_deadline"], "2026-07-01T20:03:30")
        self.assertIn("Hikmat Usmanov (Director)", metadata["contact_person"])
        self.assertIn("Tolqin Kushimov (Department head)", metadata["contact_person"])
        self.assertEqual(
            metadata["address"],
            "17-B Turkiston street; Mirzo-Ulugbek district; Tashkent city",
        )
        self.assertEqual(metadata["uzex_contact_source"], "GetTrade")

    def test_trade_list_metadata_is_safe_fallback_only(self) -> None:
        metadata = extract_uzex_trade_list_contact_metadata(
            {
                "seller_name": "Tender Buyer",
                "seller_tin": "123456789",
                "display_no": "26111006496369",
                "end_date": "2026-07-01T20:03:30",
                "clarific_date": "2026-06-30T20:03:30",
                "contacts": [{"Fullname": "Should not be copied from list"}],
            }
        )

        self.assertEqual(metadata["buyer_agency"], "Tender Buyer")
        self.assertEqual(metadata["customer_tin"], "123456789")
        self.assertEqual(metadata["uzex_display_no"], "26111006496369")
        self.assertNotIn("contact_person", metadata)


if __name__ == "__main__":
    unittest.main()
