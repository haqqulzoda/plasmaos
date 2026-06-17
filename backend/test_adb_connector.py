"""Unit tests for the ADB RSS tender connector."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from app.services.tender_sources.adb import (
    ADB_FEEDS,
    AdbTenderSource,
    attachment_metadata_from_response,
    is_active_adb_notice,
    normalize_adb_notice_payload,
    parse_adb_rss,
    parse_deadline_from_text,
)
from app.services.tender_sources.keys import canonical_source_key


ADB_RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Tenders - Invitation for Bids</title>
    <item>
      <title>0767-FSM: Chuuk Water Supply and Sanitation Project [02AF]</title>
      <link>https://www.adb.org/node/1142361</link>
      <guid>1142361</guid>
      <category>Date: 2026-04-24|Project Number: 53284-002|Status: Active|Countries: Micronesia, Federated States of|Sectors: Water and other urban infrastructure and services</category>
    </item>
    <item>
      <title>Closed Notice</title>
      <link>https://www.adb.org/node/1</link>
      <guid>1</guid>
      <category>Date: 2026-04-20|Project Number: 1|Status: Closed|Countries: Test|Sectors: Transport</category>
    </item>
  </channel>
</rss>
"""


class AdbConnectorTests(unittest.TestCase):
    def test_rss_fixture_parsing_and_category_fields(self) -> None:
        items = parse_adb_rss(
            ADB_RSS_FIXTURE,
            feed_url=ADB_FEEDS["invitation_for_bids"]["url"],
            notice_type="Invitation for Bids",
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first["guid"], "1142361")
        self.assertEqual(first["link"], "https://www.adb.org/node/1142361")
        self.assertEqual(first["category_fields"]["date"], "2026-04-24")
        self.assertEqual(first["category_fields"]["project_number"], "53284-002")
        self.assertEqual(first["category_fields"]["status"], "Active")
        self.assertEqual(
            first["category_fields"]["countries"],
            "Micronesia, Federated States of",
        )

    def test_normalized_mapping_and_canonical_key(self) -> None:
        raw = parse_adb_rss(
            ADB_RSS_FIXTURE,
            feed_url=ADB_FEEDS["invitation_for_bids"]["url"],
            notice_type="Invitation for Bids",
            max_items=1,
        )[0]
        payload = normalize_adb_notice_payload(raw)

        self.assertEqual(payload["source_system"], "adb")
        self.assertEqual(payload["external_id"], "1142361")
        self.assertEqual(canonical_source_key("adb", "1142361"), "adb:1142361")
        self.assertEqual(payload["source_url"], "https://www.adb.org/node/1142361")
        self.assertEqual(payload["project_id"], "53284-002")
        self.assertEqual(payload["country"], "Micronesia, Federated States of")
        self.assertEqual(
            payload["sector"],
            "Water and other urban infrastructure and services",
        )
        self.assertEqual(payload["notice_type"], "Invitation for Bids")
        self.assertEqual(
            payload["source_metadata_json"]["feed_url"],
            ADB_FEEDS["invitation_for_bids"]["url"],
        )

    def test_active_status_filtering(self) -> None:
        active, closed = parse_adb_rss(
            ADB_RSS_FIXTURE,
            feed_url=ADB_FEEDS["invitation_for_bids"]["url"],
            notice_type="Invitation for Bids",
        )

        self.assertTrue(is_active_adb_notice(active))
        self.assertFalse(is_active_adb_notice(closed))

    def test_node_redirect_final_pdf_metadata(self) -> None:
        metadata = attachment_metadata_from_response(
            node_url="https://www.adb.org/node/1142361",
            final_url="https://www.adb.org/sites/default/files/tenders/fsm0767-02af-ifb-ext.pdf",
            headers={
                "content-type": "application/pdf",
                "content-length": "180809",
                "last-modified": "Mon, 08 Jun 2026 00:15:48 GMT",
            },
            status_code=200,
        )

        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata.content_type, "application/pdf")
        self.assertEqual(metadata.content_length, 180809)
        self.assertEqual(len(metadata.final_url_hash), 64)

    def test_invalid_content_type_rejected(self) -> None:
        metadata = attachment_metadata_from_response(
            node_url="https://www.adb.org/node/1142361",
            final_url="https://www.adb.org/projects/some-html-page",
            headers={"content-type": "text/html"},
            status_code=200,
        )

        self.assertIsNone(metadata)

    def test_attachment_discovery_failure_does_not_block_tender_metadata(self) -> None:
        class FailingAdbSource(AdbTenderSource):
            async def resolve_node_redirect(self, node_url: str):  # type: ignore[override]
                raise RuntimeError("simulated redirect failure")

        source = FailingAdbSource()
        normalized = SimpleNamespace(
            external_id="1142361",
            source_url="https://www.adb.org/node/1142361",
            source_metadata_json={"node_url": "https://www.adb.org/node/1142361"},
        )

        with self.assertLogs("app.services.tender_sources.adb", level="WARNING"):
            attachments = asyncio.run(source.discover_attachments(normalized))

        self.assertEqual(attachments, [])
        self.assertEqual(
            normalized.source_metadata_json["attachment_discovery_status"],
            "failed",
        )
        self.assertEqual(
            normalized.source_metadata_json["attachment_discovery_error_type"],
            "RuntimeError",
        )

    def test_deadline_extraction_from_sample_text(self) -> None:
        deadline = parse_deadline_from_text(
            "Bids must be delivered before the submission deadline: 30 June 2026."
        )

        self.assertIsNotNone(deadline)
        assert deadline is not None
        self.assertEqual(deadline.isoformat(), "2026-06-30T00:00:00+00:00")
        self.assertIsNone(parse_deadline_from_text("This document has many dates."))


if __name__ == "__main__":
    unittest.main()
