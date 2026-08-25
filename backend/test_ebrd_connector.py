"""Unit tests for the EBRD ECEPP metadata-only connector."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.services.tender_sources.base import NormalizedTender
from app.services.tender_sources.ebrd import (
    EBRD_NOTICE_SEARCH_URL,
    EbrdTenderSource,
    parse_ebrd_notice_detail,
    parse_ebrd_search_page,
)
from app.services.tender_sources.keys import canonical_source_key


EBRD_LISTING_FIXTURE = """
<html><body>
<table>
  <thead><tr>
    <th>Title</th><th>Notice Type</th><th>Procurement Exercise Title</th>
    <th>Published</th><th>Closing Date</th><th>Current State</th>
  </tr></thead>
  <tbody>
    <tr>
      <td><a href="viewNotice.html?displayNoticeId=45376255">Tajikistan: Water network and installation water meters</a></td>
      <td>Invitation For Tenders Single</td>
      <td>Water network and installation water meters</td>
      <td>03/07/2026 06:13<br/><span>UK Time</span></td>
      <td>14/08/2026 11:00<br/><span>UK Time</span></td>
      <td>Open</td>
      <td>03/07/2026</td>
      <td>202607030613</td>
      <td>202608141100</td>
      <td>[Dushanbe Water Supply, 55400, Tajikistan, Water network and installation water meters, 45376134, Works, Open Tender Single Stage, The Republic of Tajikistan, Infra Eurasia, Invitation For Tenders Single]</td>
    </tr>
    <tr>
      <td><a href="viewNotice.html?displayNoticeId=45514355">Kyrgyz Republic: Kyrgyzstan Climate Resilience Water Supply Project</a></td>
      <td>General Procurement Notice</td>
      <td>N/A</td>
      <td>04/07/2026 08:00UK Time</td>
      <td>N/A</td>
      <td>Information Only</td>
      <td>04/07/2026</td>
      <td>202607040800</td>
      <td></td>
      <td>[Kyrgyzstan Climate Resilience Water Supply Project, 49793, Kyrgyz Republic, Goods,Works,Consultancy, State Water Resources Agency, Natural Resources, General Procurement Notice]</td>
    </tr>
  </tbody>
</table>
</body></html>
"""


EBRD_DETAIL_FIXTURE = """
<html><body>
  <h1 class="entry-title">Tajikistan: Water network and installation water meters</h1>
  <div class="noticestatusbuttons"><h2>Invitation For Tenders Single</h2></div>
  <div id="noticepreviewtable">
    <table id="oppoverviewtable">
      <tr><td><strong>Project Name:</strong></td><td>Dushanbe Water Supply</td></tr>
      <tr><td><strong>EBRD Project ID:</strong></td><td>55400</td></tr>
      <tr><td><strong>Country:</strong></td><td>Tajikistan</td></tr>
      <tr><td><strong>Client Name:</strong></td><td>The Republic of Tajikistan</td></tr>
      <tr><td><strong>ECEPP ID:</strong></td><td>45376134</td></tr>
      <tr><td><strong>Procurement Exercise Name:</strong></td><td>Water network and installation water meters</td></tr>
      <tr><td><strong>Procurement Exercise Description:</strong></td><td>Construction works and meters.</td></tr>
      <tr><td><strong>Type of Procurement:</strong></td><td>Works</td></tr>
      <tr><td><strong>Procurement Method:</strong></td><td>Open Tender Single Stage</td></tr>
      <tr><td><strong>Business Sector:</strong></td><td>Infra Eurasia</td></tr>
      <tr><td><strong>Notice Type:</strong></td><td>Invitation For Tenders Single</td></tr>
      <tr><td><strong>Publication Date:</strong></td><td>03/07/2026 06:13</td></tr>
      <tr><td><strong>Closing Date:</strong></td><td>14/08/2026 11:00</td></tr>
    </table>
  </div>
  <div class="notice_content">
    Prospective participants who have registered in ECEPP and expressed an interest
    may access the documents through ECEPP.
    <a href="https://ecepp.ebrd.com/respond/7ABC123XYZ">https://ecepp.ebrd.com/respond/7ABC123XYZ</a>
    Client Address:<br/>Ms Amina Karimova<br/>The Republic of Tajikistan<br/>
    Tel. +992 44 123 4567, Email: procurement@example.tj
  </div>
</body></html>
"""


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeDocumentSession:
    def __init__(self):
        self.docs = []

    async def execute(self, statement):
        values = {}

        def visit(criterion) -> None:
            clauses = getattr(criterion, "clauses", None)
            if clauses is not None:
                for clause in clauses:
                    visit(clause)
                return
            left = str(getattr(criterion, "left", ""))
            value = getattr(getattr(criterion, "right", None), "value", None)
            if left.endswith("tender_id"):
                values["tender_id"] = value
            if left.endswith("source_document_url"):
                values["source_document_url"] = value

        for criterion in getattr(statement, "_where_criteria", ()):
            visit(criterion)
        for doc in self.docs:
            if doc.tender_id == values.get("tender_id") and doc.source_document_url == values.get("source_document_url"):
                return _FakeResult(doc)
        return _FakeResult(None)

    def add(self, doc):
        self.docs.append(doc)


def _tender(source_system: str = "ebrd"):
    return SimpleNamespace(
        id=uuid4(),
        source_system=source_system,
        external_id="45376134",
        canonical_source_key=f"{source_system}:45376134",
    )


class EbrdConnectorTests(unittest.TestCase):
    def test_listing_parser_uses_stable_ecepp_metadata(self) -> None:
        rows = parse_ebrd_search_page(EBRD_LISTING_FIXTURE, page_url=EBRD_NOTICE_SEARCH_URL)

        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["external_id"], "45376134")
        self.assertEqual(canonical_source_key("ebrd", "45376134"), "ebrd:45376134")
        self.assertEqual(first["country"], "Tajikistan")
        self.assertEqual(first["region"], "Central Asia")
        self.assertEqual(first["sector"], "Infra Eurasia")
        self.assertEqual(first["buyer"], "The Republic of Tajikistan")
        self.assertEqual(first["procurement_category"], "Works")
        self.assertEqual(first["procurement_method"], "Open Tender Single Stage")
        self.assertEqual(first["deadline"].isoformat(), "2026-08-14T11:00:00+00:00")
        self.assertIn("displayNoticeId=45376255", first["source_url"])

    def test_detail_parser_maps_contact_and_access_guidance(self) -> None:
        detail = parse_ebrd_notice_detail(
            EBRD_DETAIL_FIXTURE,
            source_url="https://ecepp.ebrd.com/delta/viewNotice.html?displayNoticeId=45376255",
        )

        self.assertEqual(detail["external_id"], "45376134")
        self.assertEqual(detail["project_id"], "55400")
        self.assertEqual(detail["project_name"], "Dushanbe Water Supply")
        self.assertEqual(detail["buyer"], "The Republic of Tajikistan")
        self.assertEqual(detail["response_url"], "https://ecepp.ebrd.com/respond/7ABC123XYZ")
        self.assertEqual(detail["email"], "procurement@example.tj")
        self.assertEqual(detail["phone"], "+992 44 123 4567")
        self.assertEqual(
            detail["source_metadata_json"]["document_status_hint"],
            "access_required",
        )
        self.assertIn(
            "does not automate ECEPP login",
            detail["source_metadata_json"]["document_access_notes"],
        )

    def test_normalize_and_discover_documents_are_access_required_only(self) -> None:
        source = EbrdTenderSource(max_items=2, detail_items=0)
        raw = parse_ebrd_search_page(EBRD_LISTING_FIXTURE)[0]
        detail = parse_ebrd_notice_detail(EBRD_DETAIL_FIXTURE, source_url=raw["source_url"])
        raw = {**raw, **detail, "source_metadata_json": {**raw["source_metadata_json"], **detail["source_metadata_json"]}}
        normalized = source.normalize(raw)
        documents = asyncio.run(source.discover_documents(normalized))

        self.assertIsInstance(normalized, NormalizedTender)
        self.assertEqual(normalized.source_system, "ebrd")
        self.assertEqual(normalized.category, "EBRD")
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].normalized_source_system, "ebrd")
        self.assertEqual(documents[0].source_document_type, "access_required")
        self.assertEqual(documents[0].download_status, "access_required")

    def test_document_upsert_is_source_scoped_and_idempotent(self) -> None:
        source = EbrdTenderSource()
        session = _FakeDocumentSession()
        normalized = NormalizedTender(
            source_system="ebrd",
            external_id="45376134",
            source_url="https://ecepp.ebrd.com/delta/viewNotice.html?displayNoticeId=45376255",
            title="EBRD notice",
            source_metadata_json={
                "document_access_url": "https://ecepp.ebrd.com/respond/7ABC123XYZ"
            },
        )
        documents = asyncio.run(source.discover_documents(normalized))

        tender = _tender()
        first = asyncio.run(source.upsert_documents(session, tender=tender, documents=documents))
        second = asyncio.run(source.upsert_documents(session, tender=tender, documents=documents))

        self.assertEqual(first, (1, 0))
        self.assertEqual(second, (0, 1))
        self.assertEqual(len(session.docs), 1)
        self.assertEqual(session.docs[0].download_status, "access_required")
        self.assertIsNone(session.docs[0].storage_path)

        with self.assertRaises(ValueError):
            asyncio.run(source.upsert_documents(session, tender=_tender("giz"), documents=documents))

    def test_live_listing_failure_uses_bootstrap_fallback(self) -> None:
        class TimeoutEbrdSource(EbrdTenderSource):
            async def _request(self, client, url):  # type: ignore[override]
                raise TimeoutError("simulated ECEPP timeout")

        # This test covers fallback selection, not wall-clock active filtering.
        # The snapshot's first notice has since closed, so disable active_only
        # to keep the fallback contract deterministic without fabricating rows.
        source = TimeoutEbrdSource(max_items=2, detail_items=0, active_only=False)
        rows = asyncio.run(source.list_opportunities())

        self.assertTrue(source.last_used_bootstrap_fallback)
        self.assertEqual(source.last_fetch_error_type, "TimeoutError")
        self.assertTrue(source.last_fetch_retryable)
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]["source_metadata_json"]["ebrd_bootstrap_fallback"])
        self.assertEqual(rows[1]["region"], "Central Asia")

    def test_active_fallback_does_not_reintroduce_expired_notices(self) -> None:
        class TimeoutEbrdSource(EbrdTenderSource):
            async def _request(self, client, url):  # type: ignore[override]
                raise TimeoutError("simulated ECEPP timeout")

        source = TimeoutEbrdSource(max_items=2, detail_items=0, active_only=True)
        rows = asyncio.run(source.list_opportunities())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["notice_type"], "General Procurement Notice")
        self.assertEqual(source.last_rows_rejected, 1)

    def test_live_listing_failure_can_disable_bootstrap_fallback(self) -> None:
        class TimeoutEbrdSource(EbrdTenderSource):
            async def _request(self, client, url):  # type: ignore[override]
                raise TimeoutError("simulated ECEPP timeout")

        source = TimeoutEbrdSource(max_items=2, detail_items=0, allow_bootstrap_fallback=False)

        with self.assertRaises(TimeoutError):
            asyncio.run(source.list_opportunities())


if __name__ == "__main__":
    unittest.main()
