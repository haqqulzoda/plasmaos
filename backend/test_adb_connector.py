"""Unit tests for the ADB RSS tender connector."""

from __future__ import annotations

import asyncio
import httpx
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.tender_sources.adb import (
    ADB_ACTIVE_PROJECTS_URL,
    ADB_CURRENT_TENDERS_URL,
    ADB_FEEDS,
    ADB_VIEWS_AJAX_URL,
    AdbProjectTenderView,
    AdbTenderSource,
    adb_source_health,
    adb_lifecycle_status,
    attachment_metadata_from_response,
    extract_adb_contact_info,
    is_active_adb_notice,
    normalize_adb_notice_payload,
    parse_adb_tender_html,
    parse_adb_status_index,
    parse_adb_views_ajax,
    parse_adb_rss,
    parse_deadline_from_text,
    reconcile_unresolved_adb_legacy_rows,
)
from app.models.all_models import TenderStatus
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

ADB_HTML_FIXTURE = """
<html><body>
<table>
  <thead><tr><th>Tender Title</th><th>Type</th><th>Status</th><th>Posting Date</th><th>Deadline</th></tr></thead>
  <tbody>
    <tr>
      <td><a href="/node/1200001">59001-001: Current water package [CW-01]</a></td>
      <td>Invitation for Bids</td><td>Active</td><td>18 Aug 2026</td><td>30 Sep 2026</td>
    </tr>
    <tr>
      <td><a href="https://www.adb.org/node/1200002">59001-001: Closed package [CW-00]</a></td>
      <td>Invitation for Bids</td><td>Closed</td><td>01 Jul 2026</td><td>15 Aug 2026</td>
    </tr>
    <tr><td>Malformed row</td><td>Invitation for Bids</td><td>Active</td><td>18 Aug 2026</td><td>30 Sep 2026</td></tr>
  </tbody>
</table>
<nav><a rel="next" href="?page=1">Next</a></nav>
</body></html>
"""

ADB_STATUS_INDEX_FIXTURE = """
<html><body>
<script type="application/json" data-drupal-selector="drupal-settings-json">
{"ajaxPageState":{"theme":"adb_2022","libraries":"public-libraries"},
 "views":{"ajaxViews":{
   "views_dom_id:abc":{"view_name":"projects","view_display_id":"tenders",
   "view_args":"59001-001","view_path":"/taxonomy/term/1367",
   "view_dom_id":"abc","pager_element":0},
   "views_dom_id:def":{"view_name":"projects","view_display_id":"documents",
   "view_args":"59001-001/1200/all","view_path":"/taxonomy/term/1367",
   "view_dom_id":"def","pager_element":0}
 }}}
</script>
<a href="?page=1">Next</a><a href="?page=225">Last</a>
</body></html>
"""

ADB_VIEWS_AJAX_FIXTURE = [
    {"command": "settings", "settings": {}},
    {"command": "insert", "method": "replaceWith", "data": ADB_HTML_FIXTURE},
]


class AdbConnectorTests(unittest.TestCase):
    def test_authoritative_html_parsing_and_canonical_identity(self) -> None:
        with self.assertLogs("app.services.tender_sources.adb", level="WARNING"):
            rows, has_next = parse_adb_tender_html(ADB_HTML_FIXTURE)

        self.assertTrue(has_next)
        self.assertEqual([row["guid"] for row in rows], ["1200001", "1200002"])
        self.assertEqual(rows[0]["project_id"], "59001-001")
        self.assertEqual(rows[0]["source_status"], "Active")
        self.assertEqual(rows[0]["deadline_text"], "30 Sep 2026")
        self.assertEqual(rows[0]["source_kind"], "official_html")
        self.assertEqual(rows[0]["link"], "https://www.adb.org/node/1200001")

    def test_status_index_exposes_deterministic_project_view_and_page_count(self) -> None:
        index = parse_adb_status_index(ADB_STATUS_INDEX_FIXTURE)

        self.assertEqual(index.last_page, 225)
        self.assertEqual(index.ajax_theme, "adb_2022")
        self.assertEqual(index.ajax_libraries, "public-libraries")
        self.assertEqual(len(index.tender_views), 1)
        self.assertEqual(index.tender_views[0].project_id, "59001-001")
        self.assertEqual(index.tender_views[0].view_display_id, "tenders")

    def test_public_views_ajax_preserves_project_identity_and_current_fields(self) -> None:
        rows, has_next = parse_adb_views_ajax(
            ADB_VIEWS_AJAX_FIXTURE,
            project_id="59001-001",
        )

        self.assertTrue(has_next)
        self.assertEqual(rows[0]["guid"], "1200001")
        self.assertEqual(rows[0]["project_id"], "59001-001")
        self.assertEqual(rows[0]["posting_date"], "18 Aug 2026")
        self.assertEqual(rows[0]["deadline_text"], "30 Sep 2026")
        self.assertEqual(rows[0]["source_status"], "Active")
        self.assertEqual(rows[0]["source_kind"], "official_views_ajax")
        self.assertEqual(rows[0]["listing_url"], ADB_VIEWS_AJAX_URL)
        self.assertEqual(normalize_adb_notice_payload(rows[0])["scrape_status"], "success")

    def test_public_project_view_call_uses_only_ordinary_frontend_fields(self) -> None:
        response = SimpleNamespace(content=__import__("json").dumps(ADB_VIEWS_AJAX_FIXTURE).encode())
        source = AdbTenderSource(max_retries=0)
        source._request = AsyncMock(return_value=response)  # type: ignore[method-assign]
        client = SimpleNamespace()
        view = AdbProjectTenderView(
            project_id="59001-001",
            view_name="projects",
            view_display_id="tenders",
            view_path="/taxonomy/term/1367",
            view_dom_id="abc",
        )

        rows, _ = asyncio.run(
            source.fetch_project_tender_rows(
                client,
                view=view,
                ajax_theme="adb_2022",
                ajax_libraries="public-libraries",
            )
        )

        self.assertEqual(rows[0]["project_id"], "59001-001")
        request = source._request.await_args
        self.assertEqual(request.args[:3], (client, "POST", ADB_VIEWS_AJAX_URL))
        self.assertEqual(request.kwargs["data"]["view_args"], "59001-001")
        self.assertEqual(request.kwargs["headers"]["Referer"], ADB_ACTIVE_PROJECTS_URL)
        self.assertNotIn("Cookie", request.kwargs["headers"])

    def test_authoritative_deadline_and_explicit_status_drive_lifecycle(self) -> None:
        rows, _ = parse_adb_tender_html(ADB_HTML_FIXTURE)

        self.assertEqual(
            adb_lifecycle_status(rows[0], now=datetime(2026, 8, 24, tzinfo=timezone.utc)),
            "OPEN",
        )
        self.assertEqual(
            adb_lifecycle_status(rows[1], now=datetime(2026, 8, 24, tzinfo=timezone.utc)),
            "CLOSED",
        )
        normalized = normalize_adb_notice_payload(rows[0])
        self.assertEqual(normalized["deadline"].isoformat(), "2026-09-30T00:00:00+00:00")
        expired_active = {**rows[0], "deadline_text": "20 Aug 2026"}
        self.assertEqual(
            adb_lifecycle_status(
                expired_active,
                now=datetime(2026, 8, 24, tzinfo=timezone.utc),
            ),
            "CLOSED",
        )

    def test_no_deadline_and_no_authoritative_status_is_unknown(self) -> None:
        raw = {
            "guid": "1200003",
            "title": "Undated notice",
            "link": "https://www.adb.org/node/1200003",
            "notice_type": "Invitation for Bids",
            "source_kind": "official_html",
        }
        self.assertEqual(adb_lifecycle_status(raw), "UNKNOWN")
        self.assertEqual(AdbTenderSource().normalize(raw).status, TenderStatus.UNKNOWN)

    def test_stale_rss_active_status_is_not_treated_as_authoritative_open(self) -> None:
        raw = parse_adb_rss(
            ADB_RSS_FIXTURE,
            feed_url=ADB_FEEDS["invitation_for_bids"]["url"],
            max_items=1,
        )[0]
        self.assertEqual(adb_lifecycle_status(raw), "UNKNOWN")
        self.assertEqual(AdbTenderSource().normalize(raw).status, TenderStatus.UNKNOWN)

    def test_source_health_detects_stale_primary_independently_of_execution(self) -> None:
        self.assertEqual(
            adb_source_health(
                fallback_used=False,
                truncated=False,
                newest_published_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
                now=datetime(2026, 8, 24, tzinfo=timezone.utc),
            ),
            ("PASS", "STALE", "COMPLETE"),
        )
        self.assertEqual(
            adb_source_health(
                fallback_used=False,
                truncated=True,
                newest_published_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
                now=datetime(2026, 8, 24, tzinfo=timezone.utc),
            ),
            ("PASS", "CURRENT", "PARTIAL"),
        )

    def test_primary_html_paginates_and_deduplicates_node_identity(self) -> None:
        page_two = ADB_HTML_FIXTURE.replace(
            "/node/1200001",
            "/node/1200003",
            1,
        ).replace('<nav><a rel="next" href="?page=1">Next</a></nav>', "")
        first_response = SimpleNamespace(content=ADB_HTML_FIXTURE.encode())
        second_response = SimpleNamespace(content=page_two.encode())
        source = AdbTenderSource(max_items=20, max_pages=3, request_delay_seconds=0)
        source._request = AsyncMock(side_effect=[first_response, second_response])  # type: ignore[method-assign]

        rows = asyncio.run(source.list_opportunities())

        self.assertFalse(source.fallback_used)
        self.assertEqual(source.execution_health, "PASS")
        self.assertEqual(source.coverage_health, "COMPLETE")
        self.assertEqual(source.last_pages_fetched, 2)
        self.assertEqual({row["guid"] for row in rows}, {"1200001", "1200002", "1200003"})
        self.assertEqual(source.last_duplicate_count, 1)

    def test_primary_failure_uses_degraded_rss_with_freshness(self) -> None:
        primary_failure = httpx.HTTPStatusError(
            "blocked",
            request=httpx.Request("GET", ADB_CURRENT_TENDERS_URL),
            response=httpx.Response(403),
        )
        rss_response = SimpleNamespace(content=ADB_RSS_FIXTURE.encode())
        source = AdbTenderSource(max_retries=0)
        source._request = AsyncMock(side_effect=[primary_failure, rss_response])  # type: ignore[method-assign]

        with self.assertLogs("app.services.tender_sources.adb", level="WARNING"):
            rows = asyncio.run(source.list_opportunities())

        self.assertTrue(source.fallback_used)
        self.assertEqual(source.execution_health, "PASS")
        self.assertEqual(source.freshness_health, "STALE")
        self.assertEqual(source.coverage_health, "PARTIAL")
        self.assertEqual(source.primary_failure_class, "HTTPStatusError")
        self.assertEqual(len(rows), 2)
        self.assertEqual(source.source_newest_published_at.isoformat(), "2026-04-24T00:00:00+00:00")

    def test_unmatched_legacy_row_reconciles_to_unknown_without_deletion(self) -> None:
        legacy = SimpleNamespace(
            external_id="1142361",
            source_metadata_json={"feed_url": ADB_FEEDS["invitation_for_bids"]["url"]},
            status=TenderStatus.OPEN,
            scrape_status="success",
            last_synced_at=None,
        )
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [legacy]))
        db = SimpleNamespace(execute=AsyncMock(return_value=result))

        changed = asyncio.run(
            reconcile_unresolved_adb_legacy_rows(db, authoritative_ids=set())
        )

        self.assertEqual(changed, 1)
        self.assertEqual(legacy.status, TenderStatus.UNKNOWN)
        self.assertEqual(legacy.scrape_status, "legacy_unresolved")

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

    def test_malformed_rss_item_isolated_without_losing_valid_rows(self) -> None:
        malformed = "<item><title>Missing stable identity</title></item>"
        xml = ADB_RSS_FIXTURE.replace("<item>", f"{malformed}<item>", 1)

        with self.assertLogs("app.services.tender_sources.adb", level="WARNING"):
            items = parse_adb_rss(
                xml,
                feed_url=ADB_FEEDS["invitation_for_bids"]["url"],
                notice_type="Invitation for Bids",
            )

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["guid"], "1142361")

    def test_transient_request_failure_is_retried_once(self) -> None:
        response = SimpleNamespace(raise_for_status=lambda: None)
        client = SimpleNamespace(
            request=AsyncMock(side_effect=[TimeoutError("transient"), response])
        )
        source = AdbTenderSource(max_retries=1)

        with patch(
            "app.services.tender_sources.adb.asyncio.sleep",
            new=AsyncMock(),
        ):
            result = asyncio.run(source._request(client, "GET", "https://example.test"))

        self.assertIs(result, response)
        self.assertEqual(client.request.await_count, 2)

    def test_permanent_http_failure_is_not_retried(self) -> None:
        response = httpx.Response(
            404,
            request=httpx.Request("GET", "https://feeds.feedburner.com/missing"),
        )
        client = SimpleNamespace(request=AsyncMock(return_value=response))
        source = AdbTenderSource(max_retries=2)

        with self.assertRaises(httpx.HTTPStatusError):
            asyncio.run(source._request(client, "GET", str(response.request.url)))

        self.assertEqual(client.request.await_count, 1)

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

        attachments = asyncio.run(source.discover_attachments(normalized))

        self.assertEqual(len(attachments), 1)
        self.assertEqual(
            normalized.source_metadata_json["attachment_discovery_status"],
            "metadata_only",
        )

    def test_attachment_discovery_stores_pdf_contact_metadata(self) -> None:
        class ContactAdbSource(AdbTenderSource):
            async def resolve_node_redirect(self, node_url: str):  # type: ignore[override]
                return attachment_metadata_from_response(
                    node_url=node_url,
                    final_url="https://www.adb.org/sites/default/files/tenders/sample.pdf",
                    headers={"content-type": "application/pdf"},
                    status_code=200,
                )

            async def fetch_contact_metadata(self, **kwargs):  # type: ignore[override]
                return {
                    "contact_person": "PAG Manager, Mr. Bobokhon Abdulmajid",
                    "email": "istem.taj@gmail.com",
                    "phone": "(+992) 44 600 4809",
                    "submission_method": "Physical submission to the address specified in the ADB notice",
                }

        source = ContactAdbSource()
        normalized = SimpleNamespace(
            external_id="1140436",
            source_url="https://www.adb.org/node/1140436",
            source_metadata_json={"node_url": "https://www.adb.org/node/1140436"},
        )

        attachments = asyncio.run(source.discover_attachments(normalized))

        self.assertEqual(len(attachments), 1)
        self.assertNotIn("contact_person", normalized.source_metadata_json)
        self.assertEqual(
            normalized.source_metadata_json["attachment_discovery_status"],
            "metadata_only",
        )

    def test_deadline_extraction_from_sample_text(self) -> None:
        deadline = parse_deadline_from_text(
            "Bids must be delivered before the submission deadline: 30 June 2026."
        )

        self.assertIsNotNone(deadline)
        assert deadline is not None
        self.assertEqual(deadline.isoformat(), "2026-06-30T00:00:00+00:00")
        self.assertIsNone(parse_deadline_from_text("This document has many dates."))

    def test_contact_extraction_from_structured_adb_notice_text(self) -> None:
        text = """
        To obtain further information and inspect the Bidding Documents, Bidders should contact
        (during working days from Monday to Friday from 8:00 AM to 5:00 PM):

        Project Administration Group (PAG)
        Attention: PAG Manager, Mr. Bobokhon Abdulmajid
        Street Address: 101 Karamov str.
        Floor/Room Number: 2nd Floor, Room No.1
        City: Dushanbe
        Country: Tajikistan
        Telephone No.: (+992) 44 600 4809
        E-mail Address: istem.taj@gmail.com

        7. To purchase the Bidding Documents in English, eligible Bidders should
        write to the address above.
        8. Deliver your bid
        to the address above on or before the deadline: 30 June 2026 at 10:00 hours.
        """

        contact = extract_adb_contact_info(text)

        self.assertEqual(contact["buyer_agency"], "Project Administration Group (PAG)")
        self.assertEqual(
            contact["contact_person"],
            "PAG Manager, Mr. Bobokhon Abdulmajid",
        )
        self.assertEqual(contact["email"], "istem.taj@gmail.com")
        self.assertEqual(contact["phone"], "(+992) 44 600 4809")
        self.assertEqual(
            contact["address"],
            "101 Karamov str.; 2nd Floor, Room No.1; Dushanbe; Tajikistan",
        )
        self.assertEqual(
            contact["submission_deadline"],
            "2026-06-30T00:00:00+00:00",
        )

    def test_contact_extraction_from_tenderlink_adb_notice_text(self) -> None:
        text = """
        To obtain further information and inspect the bidding documents, Bidders should contact:
        Any request for clarification shall be submitted through the TenderLink portal
        https://portal.tenderlink.com/cpuc no later than 14 days before the bid submission deadline.

        6. To purchase the bidding documents in English, eligible Bidders should:
        Electronic Bid Documents can also be obtained from Mr. Kembo Mida, CPUC CEO,
        email: kembo.mida@cpuc.fm.

        7. Deliver your bid
        Bidders shall submit their Bids electronically through the TenderLink portal
        https://portal.tenderlink.com/cpuc.
        Should assistance be required please contact the email address supplied above 6,
        or clayton.eliam@cpuc.fm.
        on or before the deadline: 19 June 2026 at 10:00 hours Chuuk time.
        """

        contact = extract_adb_contact_info(text)

        self.assertEqual(contact["contact_person"], "Mr. Kembo Mida, CPUC CEO")
        self.assertEqual(contact["email"], "kembo.mida@cpuc.fm")
        self.assertEqual(
            contact["submission_method"],
            "TenderLink portal: https://portal.tenderlink.com/cpuc",
        )
        self.assertIn("clayton.eliam@cpuc.fm", contact["document_access_notes"])


if __name__ == "__main__":
    unittest.main()
