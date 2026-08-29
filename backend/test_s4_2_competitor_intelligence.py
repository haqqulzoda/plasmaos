"""Regression checks for S4.2 competitor intelligence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
FRONTEND_ROOT = ROOT.parent / "frontend"


try:
    from app.api.endpoints import tenders as tender_endpoints
    from app.schemas.tender import (
        TenderCompetitorIntelligenceResponse,
        TenderCompetitorResponse,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - local minimal env
    if exc.name in {
        "fastapi",
        "httpx",
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
    }:
        tender_endpoints = None
        TenderCompetitorIntelligenceResponse = None
        TenderCompetitorResponse = None
        HAS_BACKEND_DEPS = False
    else:
        raise
else:
    HAS_BACKEND_DEPS = True


def read_backend(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def read_frontend(path: str) -> str:
    return (FRONTEND_ROOT / path).read_text(encoding="utf-8")


def function_block(source: str, name: str) -> str:
    marker = f"async def {name}"
    start = source.index(marker)
    next_func = source.find("\nasync def ", start + len(marker))
    next_route = source.find("\n@router.", start + len(marker))
    candidates = [idx for idx in (next_func, next_route) if idx != -1]
    end = min(candidates) if candidates else len(source)
    return source[start:end]


def _tender(**overrides):
    values = {
        "id": uuid4(),
        "external_id": "OP0042",
        "source_system": "world_bank",
        "source_url": "https://projects.worldbank.org/procurement/OP0042",
        "title": "Hospital equipment supply",
        "description": "Supply of hospital diagnostic equipment",
        "country": "Uzbekistan",
        "sector": "Health",
        "buyer": "Ministry Procurement Center",
        "procurement_category": "Goods",
        "procurement_method": "Request for Bids",
        "notice_type": "Invitation for Bids",
        "category": "Medical",
        "publication_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "source_metadata_json": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class S42CompetitorIntelligenceStaticTests(unittest.TestCase):
    def test_endpoint_is_protected_and_uses_visible_corpus_guard(self) -> None:
        tenders = read_backend("app/api/endpoints/tenders.py")
        block = function_block(tenders, "get_tender_competitors")

        self.assertIn('"/{tender_id}/competitors"', tenders)
        self.assertIn(
            "current_user: User = Depends(require_approved_pilot_access)",
            block,
        )
        self.assertIn("customer_visible_tender_condition(Tender)", block)
        self.assertNotIn("await _ensure_tender_access(", block)

    def test_live_source_fetches_have_timeout_and_ttl_cache(self) -> None:
        tenders = read_backend("app/api/endpoints/tenders.py")

        self.assertIn("COMPETITOR_SOURCE_FETCH_TIMEOUT_SECONDS = 8.0", tenders)
        self.assertIn("COMPETITOR_LIVE_CACHE_TTL_SECONDS = 15 * 60", tenders)
        self.assertIn("_COMPETITOR_LIVE_CACHE", tenders)
        self.assertIn("timeout=COMPETITOR_SOURCE_FETCH_TIMEOUT_SECONDS", tenders)
        self.assertIn("allow_stale=True", tenders)

    def test_schema_is_whitelisted_and_grouped(self) -> None:
        schema = read_backend("app/schemas/tender.py")
        competitor_schema = schema.split("class TenderCompetitorResponse", 1)[1]

        for expected in (
            "company_name",
            "industry",
            "service_category",
            "participation_type",
            "confidence",
            "reason",
            "evidence_source",
            "class TenderCompetitorGroup",
            "class TenderCompetitorIntelligenceResponse",
        ):
            self.assertIn(expected, schema)

        self.assertNotIn("source_metadata_json", competitor_schema)
        self.assertNotIn("raw_metadata", competitor_schema)

    def test_consolidated_frontend_does_not_reintroduce_unsafe_wording(self) -> None:
        page = read_frontend("app/dashboard/tenders/[tenderId]/page.tsx")

        # Sprint 5.3 intentionally removes the redundant per-section competitor
        # request from Tender Details. The Sprint 4 API contract remains intact,
        # while the consolidated page must not imply current participation.
        self.assertNotIn("/competitors", page)

        forbidden_phrases = (
            "Participants" + " in this tender",
            "Current " + "bidders",
            "Companies " + "applying",
        )
        for forbidden in forbidden_phrases:
            self.assertNotIn(forbidden, page)


@unittest.skipUnless(HAS_BACKEND_DEPS, "Backend dependencies are not installed")
class S42CompetitorIntelligenceBehaviorTests(unittest.TestCase):
    def test_public_winner_metadata_is_high_confidence(self) -> None:
        assert tender_endpoints is not None

        target = _tender()
        related = _tender(
            id=uuid4(),
            external_id="OP0041",
            source_metadata_json={
                "awarded_supplier_name": "Med Supply LLC",
                "contact_organization": "Ministry Procurement Center",
            },
        )
        service = tender_endpoints._infer_tender_service_category(target)
        records = tender_endpoints._extract_public_competitor_records(
            target_tender=target,
            related_tender=related,
            target_service_category=service,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].company_name, "Med Supply LLC")
        self.assertEqual(records[0].participation_type, "winner")
        self.assertEqual(records[0].confidence, "high")
        self.assertTrue(records[0].reason)
        self.assertNotIn("source_metadata_json", records[0].model_dump())

    def test_generic_metadata_does_not_create_competitors(self) -> None:
        assert tender_endpoints is not None

        target = _tender()
        related = _tender(
            source_metadata_json={
                "contact_organization": "Buyer Agency",
                "notice_text": "ACME appears in a plain notice paragraph.",
            },
        )
        records = tender_endpoints._extract_public_competitor_records(
            target_tender=target,
            related_tender=related,
            target_service_category="medical",
        )

        self.assertEqual(records, [])

    def test_repeated_similar_market_actor_is_medium_confidence(self) -> None:
        assert tender_endpoints is not None

        target = _tender()
        first = _tender(
            id=uuid4(),
            source_metadata_json={"similar_market_actors": ["Clinic Systems LLC"]},
        )
        second = _tender(
            id=uuid4(),
            source_metadata_json={"similar_market_actors": ["Clinic Systems LLC"]},
        )
        records = []
        for related in (first, second):
            records.extend(
                tender_endpoints._extract_public_competitor_records(
                    target_tender=target,
                    related_tender=related,
                    target_service_category="medical",
                )
            )

        groups = tender_endpoints._group_competitor_records(records)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].service_category, "medical")
        self.assertEqual(len(groups[0].competitors), 1)
        competitor = groups[0].competitors[0]
        self.assertEqual(competitor.company_name, "Clinic Systems LLC")
        self.assertEqual(competitor.participation_type, "similar_market_actor")
        self.assertEqual(competitor.confidence, "medium")
        self.assertTrue(competitor.reason)

    def test_empty_response_message_is_clean(self) -> None:
        assert TenderCompetitorIntelligenceResponse is not None

        response = TenderCompetitorIntelligenceResponse(
            tender_id=uuid4(),
            message=tender_endpoints.COMPETITOR_EMPTY_MESSAGE,
            groups=[],
        )

        self.assertEqual(response.groups, [])
        self.assertEqual(
            response.message,
            "No historical competitor intelligence available yet.",
        )


@unittest.skipUnless(HAS_BACKEND_DEPS, "Backend dependencies are not installed")
class S42LiveSourceCompetitorBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_uzex_deals_list_provider_is_historical_winner(self) -> None:
        assert tender_endpoints is not None

        target = _tender(
            source_system="uzex",
            source_url="https://etender.uzex.uz/lot/496369",
            title="Тиббий жиҳозлар хариди",
            description="Тиббий жиҳозлар хариди",
            country="Uzbekistan",
            category="Medical",
        )

        async def fake_fetch_json_payload(**kwargs):
            self.assertEqual(kwargs["url"], tender_endpoints.UZEX_DEALS_LIST_URL)
            return [
                {
                    "trade_id": 488105,
                    "provider_name": '"Best Electric Technologies" XK',
                    "customer_name": "Public Buyer",
                    "category_name": "Тиббий жиҳозлар хариди",
                }
            ]

        with patch.object(
            tender_endpoints,
            "_fetch_json_payload",
            side_effect=fake_fetch_json_payload,
        ):
            records = await tender_endpoints._live_uzex_competitor_records(
                target_tender=target,
                target_service_category="medical",
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].company_name, "Best Electric Technologies XK")
        self.assertEqual(records[0].participation_type, "winner")
        self.assertEqual(records[0].confidence, "high")
        self.assertIn("UzEx historical award/deal data", records[0].reason)
        self.assertEqual(records[0].service_category, "medical")

    async def test_uzex_service_specific_tender_discards_unrelated_deals(self) -> None:
        assert tender_endpoints is not None

        target = _tender(
            source_system="uzex",
            source_url="https://etender.uzex.uz/lot/496369",
            title="Қурилиш ишлари",
            description="Қурилиш ишлари",
            country="Uzbekistan",
            category="Construction",
        )

        async def fake_fetch_json_payload(**kwargs):
            return [
                {
                    "trade_id": 488105,
                    "provider_name": "Medical Winner MCHJ",
                    "customer_name": "Public Buyer",
                    "category_name": "Тиббий жиҳозлар хариди",
                }
            ]

        with patch.object(
            tender_endpoints,
            "_fetch_json_payload",
            side_effect=fake_fetch_json_payload,
        ):
            records = await tender_endpoints._live_uzex_competitor_records(
                target_tender=target,
                target_service_category="construction",
            )

        self.assertEqual(records, [])

    def test_world_bank_award_parser_extracts_winners_and_evaluated_bidders(self) -> None:
        assert tender_endpoints is not None

        notice_text = """
        <div><u><b>Awarded Bidder(s):</b></u></div>
        <div><b>ENGINEERING PLUS (T) LTD (1077096)</b><br/>Country: Tanzania<br/></div>
        <div><u><b>Evaluated Bidder(s):</b></u></div>
        <div><b>LUKOLO COMPANY LIMITED (1074239)</b><br/>Country: Tanzania<br/></div>
        <div><u><b>Rejected Bidder(s):</b></u></div>
        <div><b>JLD STROY (835758)</b><br/>Country: Kyrgyz Republic<br/></div>
        """

        self.assertEqual(
            tender_endpoints._world_bank_award_names(
                notice_text,
                participation_type="winner",
            ),
            ["ENGINEERING PLUS (T) LTD"],
        )
        self.assertEqual(
            tender_endpoints._world_bank_award_names(
                notice_text,
                participation_type="participant",
            ),
            ["LUKOLO COMPANY LIMITED", "JLD STROY"],
        )

    async def test_world_bank_contract_awards_return_groupable_records(self) -> None:
        assert tender_endpoints is not None

        target = _tender(
            source_system="world_bank",
            title="Road construction works",
            description="Civil works for road rehabilitation",
            country="Tanzania",
            procurement_category="Works",
            category="Construction",
        )

        async def fake_fetch_json_payload(**kwargs):
            self.assertEqual(kwargs["url"], tender_endpoints.WORLD_BANK_PROC_NOTICES_URL)
            return {
                "procnotices": [
                    {
                        "id": "OP00454761",
                        "notice_type": "Contract Award",
                        "noticetitle": "District court construction",
                        "bid_description": "Construction works",
                        "project_ctry_name": "Tanzania",
                        "agency_name": "Public Agency",
                        "procurement_group_desc": "Works",
                        "notice_text": (
                            "<div><u><b>Awarded Bidder(s):</b></u></div>"
                            "<div><b>ENGINEERING PLUS (T) LTD (1077096)</b><br/>"
                            "Country: Tanzania<br/></div>"
                        ),
                    }
                ]
            }

        with patch.object(
            tender_endpoints,
            "_fetch_json_payload",
            side_effect=fake_fetch_json_payload,
        ):
            records = await tender_endpoints._live_world_bank_competitor_records(
                target_tender=target,
                target_service_category="construction",
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].company_name, "ENGINEERING PLUS (T) LTD")
        self.assertEqual(records[0].participation_type, "winner")
        self.assertEqual(records[0].confidence, "high")
        self.assertEqual(records[0].service_category, "construction")

    async def test_world_bank_service_specific_tender_discards_same_country_wrong_field(self) -> None:
        assert tender_endpoints is not None

        target = _tender(
            source_system="world_bank",
            title="Road construction works",
            description="Civil works for road rehabilitation",
            country="Tanzania",
            procurement_category="Works",
            category="Construction",
        )

        async def fake_fetch_json_payload(**kwargs):
            return {
                "procnotices": [
                    {
                        "id": "OP00450000",
                        "notice_type": "Contract Award",
                        "noticetitle": "Hospital diagnostic equipment",
                        "bid_description": "Supply of medical equipment",
                        "project_ctry_name": "Tanzania",
                        "agency_name": "Public Agency",
                        "procurement_group_desc": "Goods",
                        "notice_text": (
                            "<div><u><b>Awarded Bidder(s):</b></u></div>"
                            "<div><b>MEDICAL EQUIPMENT LTD (1077096)</b><br/>"
                            "Country: Tanzania<br/></div>"
                        ),
                    }
                ]
            }

        with patch.object(
            tender_endpoints,
            "_fetch_json_payload",
            side_effect=fake_fetch_json_payload,
        ):
            records = await tender_endpoints._live_world_bank_competitor_records(
                target_tender=target,
                target_service_category="construction",
            )

        self.assertEqual(records, [])

    async def test_adb_awarded_rss_does_not_invent_company_from_contract_title(self) -> None:
        assert tender_endpoints is not None

        target = _tender(
            source_system="adb",
            title="Road rehabilitation",
            description="Road rehabilitation",
            country="Sri Lanka",
            sector="Transport",
            category="ADB",
        )
        rss = """
        <rss><channel>
            <item>
                <title>Rehabilitation and Improvement of rural roads</title>
                <link>https://www.adb.org/node/1141721</link>
                <category>Date: 2026-03-31|Status: Awarded|Countries: Sri Lanka|Sectors: Transport</category>
            </item>
        </channel></rss>
        """

        async def fake_fetch_text_payload(**kwargs):
            self.assertEqual(kwargs["url"], tender_endpoints.ADB_CONTRACTS_AWARDED_RSS_URL)
            return rss

        with patch.object(
            tender_endpoints,
            "_fetch_text_payload",
            side_effect=fake_fetch_text_payload,
        ):
            records = await tender_endpoints._live_adb_competitor_records(
                target_tender=target,
                target_service_category="construction",
            )

        self.assertEqual(records, [])

    async def test_live_source_cache_returns_fresh_cached_records(self) -> None:
        assert tender_endpoints is not None

        target = _tender(
            source_system="uzex",
            title="Тиббий жиҳозлар хариди",
            description="Тиббий жиҳозлар хариди",
            country="Uzbekistan",
            category="Medical",
        )
        record = tender_endpoints._live_competitor_record(
            company_name="Cached Provider MCHJ",
            source_system="uzex",
            service_category="medical",
            participation_type="winner",
            confidence="high",
            reason="Public UzEx historical award/deal data names this company.",
            evidence_source="https://etender.uzex.uz/lot/1",
            country="Uzbekistan",
        )
        tender_endpoints._COMPETITOR_LIVE_CACHE.clear()

        async def fake_live_uzex(**kwargs):
            return [record]

        with patch.object(
            tender_endpoints,
            "_live_uzex_competitor_records",
            side_effect=fake_live_uzex,
        ) as fetch_mock:
            first = await tender_endpoints._live_source_competitor_records(
                target_tender=target,
                target_service_category="medical",
            )
            second = await tender_endpoints._live_source_competitor_records(
                target_tender=target,
                target_service_category="medical",
            )

        self.assertEqual(fetch_mock.call_count, 1)
        self.assertEqual(first[0].company_name, "Cached Provider MCHJ")
        self.assertEqual(second[0].company_name, "Cached Provider MCHJ")
        self.assertIsNot(first[0], second[0])

    async def test_live_source_returns_stale_cache_when_refresh_is_empty(self) -> None:
        assert tender_endpoints is not None

        target = _tender(
            source_system="world_bank",
            title="Road construction works",
            description="Civil works",
            country="Tanzania",
            category="Construction",
        )
        record = tender_endpoints._live_competitor_record(
            company_name="Stale Civil Works Ltd",
            source_system="world_bank",
            service_category="construction",
            participation_type="winner",
            confidence="high",
            reason="Public World Bank historical award/deal data names this company.",
            evidence_source="https://projects.worldbank.org/en/projects-operations/procurement-detail/OP1",
            country="Tanzania",
        )
        cache_key = tender_endpoints._competitor_live_cache_key(
            target_tender=target,
            target_service_category="construction",
        )
        tender_endpoints._COMPETITOR_LIVE_CACHE.clear()
        tender_endpoints._COMPETITOR_LIVE_CACHE[cache_key] = (
            tender_endpoints.monotonic()
            - tender_endpoints.COMPETITOR_LIVE_CACHE_TTL_SECONDS
            - 1,
            [record],
        )

        async def fake_live_world_bank(**kwargs):
            return []

        with patch.object(
            tender_endpoints,
            "_live_world_bank_competitor_records",
            side_effect=fake_live_world_bank,
        ):
            records = await tender_endpoints._live_source_competitor_records(
                target_tender=target,
                target_service_category="construction",
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].company_name, "Stale Civil Works Ltd")

    async def test_live_source_failure_without_cache_is_clean_empty(self) -> None:
        assert tender_endpoints is not None

        target = _tender(
            source_system="uzex",
            title="Тиббий жиҳозлар хариди",
            description="Тиббий жиҳозлар хариди",
            country="Uzbekistan",
            category="Medical",
        )
        tender_endpoints._COMPETITOR_LIVE_CACHE.clear()

        async def fake_live_uzex(**kwargs):
            raise RuntimeError("source unavailable")

        with patch.object(
            tender_endpoints,
            "_live_uzex_competitor_records",
            side_effect=fake_live_uzex,
        ), patch.object(tender_endpoints.logger, "exception"):
            records = await tender_endpoints._live_source_competitor_records(
                target_tender=target,
                target_service_category="medical",
            )

        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
