"""Unit tests for the World Bank procurement notices connector."""

from __future__ import annotations

import unittest
from datetime import date

from app.services.tender_sources.keys import canonical_source_key
from app.services.tender_sources.world_bank import (
    clean_notice_html,
    extract_world_bank_attachment_links,
    extract_world_bank_contact_info,
    is_actionable_notice,
    normalize_world_bank_notice_payload,
    parse_world_bank_deadline,
)


def _notice_fixture(**overrides):
    raw = {
        "id": "OP00434599",
        "notice_type": "Invitation for Bids",
        "notice_status": "Published",
        "noticetitle": "Package 2: HEM Works",
        "bid_description": "Hydro electro Mechanical Works",
        "notice_text": (
            "<p><strong>Specific Procurement Notice</strong></p>"
            "<p>Download <a href=\"https://example.org/docs/bid.pdf\">PDF</a>.</p>"
            "<script>alert('x')</script>"
        ),
        "noticedate": "08-Jun-2026",
        "submission_date": "2026-06-08T00:00:00Z",
        "submission_deadline_date": "2026-10-30T00:00:00Z",
        "submission_deadline_time": "10:00",
        "project_ctry_name": "Liberia",
        "regionname": "Western And Central Africa",
        "sector": [
            {"sector_description": "Renewable Energy Solar"},
            {"sector_description": "Energy Transmission and Distribution"},
        ],
        "agency_name": "Liberia Electricity Corporation",
        "contact_address": "1 Energy Way",
        "contact_city": "Monrovia",
        "contact_ctry_name": "Liberia",
        "contact_email": "jane.doe@example.org",
        "contact_job_title": "Procurement Specialist",
        "contact_name": "Jane Doe",
        "contact_organization": "Fallback Buyer",
        "contact_phone_no": "+231 555 0199",
        "procurement_group_desc": "Works",
        "procurement_method_name": "Request for Bids",
        "project_id": "P179267",
        "bid_estimate_amount": "40000000",
        "bid_currency_code": "USD",
    }
    raw.update(overrides)
    return raw


class WorldBankConnectorTests(unittest.TestCase):
    def test_json_mapping_to_normalized_payload(self) -> None:
        payload = normalize_world_bank_notice_payload(_notice_fixture())

        self.assertEqual(payload["source_system"], "world_bank")
        self.assertEqual(payload["external_id"], "OP00434599")
        self.assertEqual(
            canonical_source_key(payload["source_system"], payload["external_id"]),
            "world_bank:OP00434599",
        )
        self.assertEqual(payload["title"], "Package 2: HEM Works")
        self.assertEqual(payload["buyer"], "Liberia Electricity Corporation")
        self.assertEqual(payload["country"], "Liberia")
        self.assertEqual(payload["region"], "Western And Central Africa")
        self.assertEqual(payload["procurement_category"], "Works")
        self.assertEqual(payload["procurement_method"], "Request for Bids")
        self.assertEqual(payload["notice_type"], "Invitation for Bids")
        self.assertEqual(payload["project_id"], "P179267")
        self.assertEqual(payload["budget"], 40000000.0)
        self.assertEqual(payload["currency"], "USD")
        self.assertIn("Renewable Energy Solar", payload["sector"])
        self.assertNotIn("<strong>", payload["description"])
        self.assertNotIn("alert", payload["description"])

    def test_contact_information_extraction_from_procnotice_row(self) -> None:
        contact = extract_world_bank_contact_info(_notice_fixture())

        self.assertEqual(contact["buyer_agency"], "Fallback Buyer")
        self.assertEqual(
            contact["contact_person"],
            "Jane Doe (Procurement Specialist)",
        )
        self.assertEqual(contact["email"], "jane.doe@example.org")
        self.assertEqual(contact["phone"], "+231 555 0199")
        self.assertEqual(contact["address"], "1 Energy Way; Monrovia; Liberia")

    def test_active_notice_filtering(self) -> None:
        self.assertTrue(
            is_actionable_notice(
                _notice_fixture(),
                today=date(2026, 6, 10),
            )
        )
        self.assertFalse(
            is_actionable_notice(
                _notice_fixture(submission_deadline_date="2026-06-09T00:00:00Z"),
                today=date(2026, 6, 10),
            )
        )

    def test_contract_award_exclusion(self) -> None:
        self.assertFalse(
            is_actionable_notice(
                _notice_fixture(notice_type="Contract Award"),
                today=date(2026, 6, 10),
            )
        )

    def test_general_procurement_notice_excluded_by_default(self) -> None:
        notice = _notice_fixture(notice_type="General Procurement Notice")
        self.assertFalse(is_actionable_notice(notice, today=date(2026, 6, 10)))
        self.assertTrue(
            is_actionable_notice(
                notice,
                include_general_procurement_notice=True,
                today=date(2026, 6, 10),
            )
        )

    def test_deadline_parsing_with_time(self) -> None:
        deadline = parse_world_bank_deadline(
            _notice_fixture(
                submission_deadline_date="2026-10-30T00:00:00Z",
                submission_deadline_time="5:30 PM",
            )
        )

        self.assertIsNotNone(deadline)
        self.assertEqual(deadline.isoformat(), "2026-10-30T17:30:00+00:00")

    def test_html_cleanup_strips_tags_and_unsafe_content(self) -> None:
        cleaned = clean_notice_html(
            "<p>Hello&nbsp;<strong>World</strong></p>"
            "<style>.x{color:red}</style><script>alert(1)</script>"
        )

        self.assertEqual(cleaned, "Hello World")

    def test_attachment_link_extraction(self) -> None:
        attachments = extract_world_bank_attachment_links(
            """
            <a href="/docs/bid.docx">doc</a>
            <a href="https://example.org/file.exe">bad</a>
            <a href="https://example.org/archive.zip?download=1">zip</a>
            <a href="https://example.org/documents/123">page</a>
            """,
            base_url="https://projects.worldbank.org/base/page",
        )

        urls = [item["source_document_url"] for item in attachments]
        self.assertEqual(len(urls), 3)
        self.assertIn("https://projects.worldbank.org/docs/bid.docx", urls)
        self.assertIn("https://example.org/archive.zip?download=1", urls)
        self.assertIn("https://example.org/documents/123", urls)
        self.assertNotIn("https://example.org/file.exe", urls)


if __name__ == "__main__":
    unittest.main()
