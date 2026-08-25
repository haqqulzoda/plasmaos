"""Unit tests for the World Bank procurement notices connector."""

from __future__ import annotations

import asyncio
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.endpoints.tenders import sync_world_bank_tenders
from app.models.all_models import TenderStatus
from app.services.tender_sources.base import reconcile_past_deadline_open_tenders
from app.services.tender_sources.keys import canonical_source_key
from app.services.tender_sources.world_bank import (
    WORLD_BANK_ACTIONABLE_NOTICE_TYPES,
    WorldBankTenderSource,
    clean_notice_html,
    extract_world_bank_attachment_links,
    extract_world_bank_contact_info,
    is_actionable_notice,
    normalize_world_bank_notice_payload,
    parse_world_bank_deadline,
    world_bank_current_date,
    world_bank_skip_reason,
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
    def test_official_current_opportunity_filters_and_exhaustive_pagination(self) -> None:
        fixed_now = datetime(2026, 8, 24, 20, 30, tzinfo=timezone.utc)
        late = _notice_fixture(id="OP-LATE")
        pages = {
            0: [_notice_fixture(id=f"AWARD-{index}", notice_type="Contract Award") for index in range(100)],
            100: [_notice_fixture(id=f"AWARD-{index}", notice_type="Contract Award") for index in range(100, 200)],
            200: [_notice_fixture(id=f"AWARD-{index}", notice_type="Contract Award") for index in range(200, 300)],
            300: [late],
        }

        class FixtureSource(WorldBankTenderSource):
            def __init__(self):
                super().__init__(
                    rows=100,
                    max_pages=10,
                    request_delay_seconds=0,
                    clock=lambda: fixed_now,
                )
                self.params = []

            async def _get_json(self, _client, params):  # type: ignore[override]
                self.params.append(params)
                return {"total": 301, "procnotices": pages.get(params["os"], [])}

        source = FixtureSource()
        rows = asyncio.run(source.list_opportunities())

        self.assertEqual(len(rows), 301)
        self.assertEqual(source.last_pages_fetched, 4)
        self.assertFalse(source.last_truncated)
        self.assertFalse(any(source.should_import(row) for row in rows[:300]))
        self.assertTrue(source.should_import(rows[300]))
        self.assertEqual(
            source.params[0]["notice_type_exact"],
            "^".join(WORLD_BANK_ACTIONABLE_NOTICE_TYPES),
        )
        self.assertEqual(
            source.params[0]["deadline_strdate"],
            world_bank_current_date(fixed_now).isoformat(),
        )

    def test_current_query_date_uses_utc_calendar_across_offset_boundaries(self) -> None:
        fixed_utc = datetime(2026, 8, 24, 20, 30, tzinfo=timezone.utc)
        tashkent = fixed_utc.astimezone(timezone(timedelta(hours=5)))
        new_york = fixed_utc.astimezone(timezone(timedelta(hours=-4)))
        western_boundary_utc = datetime(2026, 8, 25, 2, 30, tzinfo=timezone.utc)
        western_previous_date = western_boundary_utc.astimezone(
            timezone(timedelta(hours=-4))
        )

        self.assertEqual(tashkent.date(), date(2026, 8, 25))
        self.assertEqual(new_york.date(), date(2026, 8, 24))
        self.assertEqual(world_bank_current_date(fixed_utc), fixed_utc.date())
        self.assertEqual(world_bank_current_date(tashkent), fixed_utc.date())
        self.assertEqual(world_bank_current_date(new_york), fixed_utc.date())
        self.assertEqual(western_previous_date.date(), date(2026, 8, 24))
        self.assertEqual(
            world_bank_current_date(western_previous_date),
            western_boundary_utc.date(),
        )

    def test_pagination_captures_one_query_date_across_utc_midnight(self) -> None:
        clock_values = iter(
            [
                datetime(2026, 8, 24, 23, 59, tzinfo=timezone.utc),
                datetime(2026, 8, 25, 0, 1, tzinfo=timezone.utc),
            ]
        )

        class MidnightSource(WorldBankTenderSource):
            def __init__(self):
                super().__init__(
                    rows=1,
                    max_pages=2,
                    request_delay_seconds=0,
                    clock=lambda: next(clock_values),
                )
                self.params = []

            async def _get_json(self, _client, params):  # type: ignore[override]
                self.params.append(params)
                return {
                    "total": 2,
                    "procnotices": [_notice_fixture(id=f"OP-{params['os']}")],
                }

        source = MidnightSource()
        rows = asyncio.run(source.list_opportunities())

        self.assertEqual(len(rows), 2)
        self.assertEqual(len(source.params), 2)
        self.assertEqual(
            {params["deadline_strdate"] for params in source.params},
            {source.last_query_date.isoformat()},
        )

    def test_safety_cap_sets_truncation_instead_of_silent_completion(self) -> None:
        class CappedSource(WorldBankTenderSource):
            async def _get_json(self, _client, params):  # type: ignore[override]
                rows = [_notice_fixture(id=f"OP-{params['os'] + i}") for i in range(100)]
                return {"total": 400, "procnotices": rows}

        source = CappedSource(rows=100, max_pages=3, request_delay_seconds=0)
        rows = asyncio.run(source.list_opportunities())

        self.assertEqual(len(rows), 300)
        self.assertTrue(source.last_truncated)

    def test_duplicate_ids_are_isolated_across_pages(self) -> None:
        class DuplicateSource(WorldBankTenderSource):
            async def _get_json(self, _client, params):  # type: ignore[override]
                rows = {
                    0: [_notice_fixture(id="OP-1"), _notice_fixture(id="OP-X")],
                    2: [_notice_fixture(id="OP-1"), _notice_fixture(id="OP-2")],
                }.get(params["os"], [])
                return {"total": 4, "procnotices": rows}

        source = DuplicateSource(rows=2, max_pages=5, request_delay_seconds=0)
        rows = asyncio.run(source.list_opportunities())
        self.assertEqual({row["id"] for row in rows}, {"OP-1", "OP-X", "OP-2"})
        self.assertEqual(source.last_duplicate_count, 1)

    def test_structured_skip_reasons(self) -> None:
        self.assertEqual(
            world_bank_skip_reason(_notice_fixture(notice_type="Contract Award")),
            "contract_award",
        )
        self.assertEqual(
            world_bank_skip_reason(_notice_fixture(notice_type="General Procurement Notice")),
            "general_procurement_notice",
        )
        self.assertEqual(
            world_bank_skip_reason(_notice_fixture(submission_deadline_date="2020-01-01")),
            "expired",
        )

    def test_past_deadline_open_row_becomes_closed_without_overwriting_cancelled(self) -> None:
        open_tender = SimpleNamespace(
            status=TenderStatus.OPEN,
            last_synced_at=None,
        )
        result = SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: [open_tender])
        )
        db = SimpleNamespace(execute=AsyncMock(return_value=result))
        changed = asyncio.run(
            reconcile_past_deadline_open_tenders(
                db,
                source_system="world_bank",
                now=datetime(2026, 8, 24, tzinfo=timezone.utc),
            )
        )
        self.assertEqual(changed, 1)
        self.assertEqual(open_tender.status, TenderStatus.CLOSED)

    def test_truncated_sync_reports_partial(self) -> None:
        source = SimpleNamespace(
            source_system="world_bank",
            last_duplicate_count=0,
            last_truncated=True,
            last_pages_fetched=3,
            source_newest_published_at=None,
            source_oldest_published_at=None,
            list_opportunities=AsyncMock(return_value=[]),
        )
        db = SimpleNamespace(rollback=AsyncMock())
        with (
            patch("app.api.endpoints.tenders.WorldBankTenderSource", return_value=source),
            patch(
                "app.api.endpoints.tenders.reconcile_past_deadline_open_tenders",
                new=AsyncMock(return_value=0),
            ),
        ):
            response = asyncio.run(
                sync_world_bank_tenders(
                    max_pages=3,
                    rows=100,
                    active_only=True,
                    dry_run=True,
                    db=db,
                )
            )
        self.assertEqual(response.status, "partial")
        self.assertIn("pagination", response.errors[0])

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

    def test_date_only_deadline_remains_open_through_end_of_utc_day(self) -> None:
        deadline = parse_world_bank_deadline(
            _notice_fixture(
                submission_deadline_date="2026-08-24T00:00:00Z",
                submission_deadline_time=None,
            )
        )
        self.assertIsNotNone(deadline)
        self.assertEqual(deadline.isoformat(), "2026-08-24T23:59:59.999999+00:00")

        before_end_of_day = WorldBankTenderSource(
            clock=lambda: datetime(2026, 8, 24, 23, 59, 59, tzinfo=timezone.utc)
        )
        after_end_of_day = WorldBankTenderSource(
            clock=lambda: datetime(2026, 8, 25, 0, 0, tzinfo=timezone.utc)
        )
        raw = _notice_fixture(
            submission_deadline_date="2026-08-24T00:00:00Z",
            submission_deadline_time=None,
        )
        self.assertEqual(before_end_of_day.normalize(raw).status, TenderStatus.OPEN)
        self.assertEqual(after_end_of_day.normalize(raw).status, TenderStatus.CLOSED)

    def test_timestamp_deadline_uses_aware_utc_instant(self) -> None:
        raw = _notice_fixture(
            submission_deadline_date="2026-08-24T00:00:00Z",
            submission_deadline_time="20:30",
        )
        before_deadline = WorldBankTenderSource(
            clock=lambda: datetime(2026, 8, 24, 20, 29, 59, tzinfo=timezone.utc)
        )
        after_deadline = WorldBankTenderSource(
            clock=lambda: datetime(2026, 8, 24, 20, 30, 1, tzinfo=timezone.utc)
        )

        self.assertEqual(before_deadline.normalize(raw).status, TenderStatus.OPEN)
        self.assertEqual(after_deadline.normalize(raw).status, TenderStatus.CLOSED)

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
