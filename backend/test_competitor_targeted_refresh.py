"""Regression coverage for project- and buyer-targeted competitor evidence."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.api.endpoints import tenders
from app.services.competitor_cache import cached_competitor_records, metadata_with_competitor_cache


def target(source: str, **changes):
    values = dict(
        id=uuid4(), external_id="100", source_system=source,
        source_url=f"https://{'etender.uzex.uz' if source == 'uzex' else 'projects.worldbank.org'}/lot/100",
        title="Hospital equipment", description="Medical equipment", country="Uzbekistan",
        sector="Health", buyer="Health Procurement Agency", category="Medical",
        procurement_category="Goods", procurement_method="Open", notice_type="Invitation",
        project_id="P100", publication_date=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc), source_metadata_json={},
    )
    values.update(changes)
    return SimpleNamespace(**values)


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


def test_world_bank_awards_are_queried_by_project_and_mismatched_rows_are_rejected():
    record = {
        "id": "OP100", "project_id": "P100", "project_ctry_name": "Uzbekistan",
        "agency_name": "Health Procurement Agency", "procurement_group_desc": "Goods",
        "noticetitle": "Hospital equipment", "noticedate": "15-Sep-2026",
        "notice_text": "<b>Awarded Bidder(s):</b><div><b>Medical Supplier LLC</b><br/>Country: Uzbekistan<br/></div>",
    }
    fetch = AsyncMock(return_value={"procnotices": [{**record, "project_id": "P999"}, record]})
    with patch.object(tenders, "_fetch_json_payload", new=fetch):
        records = asyncio.run(tenders._live_world_bank_competitor_records(
            target_tender=target("world_bank"), target_service_category="medical",
        ))
    assert fetch.await_args.kwargs["params"]["project_id"] == "P100"
    assert len(records) == 1
    assert records[0].related_project_id == "P100"
    assert records[0].evidence_date == datetime(2026, 9, 15, tzinfo=timezone.utc)


def test_uzex_deals_are_queried_by_customer():
    fetch = AsyncMock(return_value=[{
        "trade_id": 99, "provider_name": "Medical Supplier LLC",
        "customer_name": "Health Procurement Agency", "category_name": "Medical equipment",
    }])
    with patch.object(tenders, "_fetch_json_payload", new=fetch):
        records = asyncio.run(tenders._live_uzex_competitor_records(
            target_tender=target("uzex"), target_service_category="medical",
        ))
    assert fetch.await_args.kwargs["json_payload"]["CustomerName"] == "Health Procurement Agency"
    assert len(records) == 1
    assert records[0].evidence_source == "https://etender.uzex.uz/lot/99"


def test_uzex_missing_buyer_is_hydrated_before_award_grouping():
    tender = target("uzex", buyer=None, project_id=None)
    db = MagicMock()
    db.execute = AsyncMock(return_value=Rows([tender]))
    db.commit = AsyncMock()
    fetch = AsyncMock(return_value={"customer_name": "Health Procurement Agency"})
    award = tenders._live_competitor_record(
        company_name="Medical Supplier LLC", source_system="uzex",
        service_category="medical", participation_type="winner", confidence="high",
        reason="Official historical award", evidence_source="https://etender.uzex.uz/lot/99",
        buyer="Health Procurement Agency", country="Uzbekistan",
        category="Goods", related_tender_title="Hospital equipment",
    )
    source = AsyncMock(return_value=[award])
    with patch.object(tenders, "_fetch_json_payload", new=fetch), patch.object(
        tenders, "_live_source_competitor_records", new=source,
    ):
        result = asyncio.run(tenders._refresh_source_competitor_cache(
            db=db, source_system="uzex", target_limit=1,
        ))
    assert fetch.await_args.kwargs["url"].endswith("/GetTrade/100/0")
    assert source.await_args.kwargs["target_tender"].buyer == "Health Procurement Agency"
    assert source.await_args.kwargs["target_service_category"] == "other"
    assert result["records_cached"] == 1
    assert cached_competitor_records(tender.source_metadata_json)[0].company_name == "Medical Supplier LLC"
    db.commit.assert_awaited_once()


def test_refresh_groups_world_bank_targets_by_project_not_global_service():
    first = target("world_bank", project_id="P100")
    second = target("world_bank", project_id="P200")
    db = MagicMock()
    db.execute = AsyncMock(return_value=Rows([first, second]))
    db.commit = AsyncMock()
    source = AsyncMock(return_value=[])
    with patch.object(tenders, "_live_source_competitor_records", new=source):
        asyncio.run(tenders._refresh_source_competitor_cache(
            db=db, source_system="world_bank", target_limit=2,
        ))
    assert source.await_count == 2
    assert {call.kwargs["target_tender"].project_id for call in source.await_args_list} == {"P100", "P200"}
    assert all(call.kwargs["target_service_category"] == "other" for call in source.await_args_list)


def test_fresh_targeted_cache_skips_network_unless_backfill_is_forced():
    tender = target("uzex")
    tender.source_metadata_json = metadata_with_competitor_cache(
        {}, [], source_system="uzex",
        lookup_strategy=tenders.COMPETITOR_TARGETED_LOOKUP_STRATEGY,
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=Rows([tender]))
    db.commit = AsyncMock()
    source = AsyncMock(return_value=[])
    with patch.object(tenders, "_live_source_competitor_records", new=source):
        asyncio.run(tenders._refresh_source_competitor_cache(db=db, source_system="uzex"))
        source.assert_not_awaited()
        asyncio.run(tenders._refresh_source_competitor_cache(db=db, source_system="uzex", force=True))
    source.assert_awaited_once()


def test_world_bank_award_parser_rejects_non_company_headings():
    notice = (
        "<b>Awarded Bidder(s):</b><div><b>Real Supplier LLC</b><br/>Country: Uzbekistan<br/></div>"
        "<div><b>Beneficial Ownership Details</b><br/>Form Date: 15-JUN-26</div>"
        "<div><b>Final Evaluation Price</b><br/>USD 10,000</div>"
    )
    assert tenders._world_bank_award_names(notice, participation_type="winner") == ["Real Supplier LLC"]


def test_same_buyer_and_distinctive_work_can_match_uncategorized_uzex_history():
    open_lot = target(
        "uzex", project_id=None, category="Other", procurement_category=None,
        sector=None, description=None, title="Gas compressor rotor refurbishment",
    )
    prior_award = tenders._live_competitor_record(
        company_name="Verified Repairer", source_system="uzex", service_category="other",
        participation_type="winner", confidence="high", reason="Official deal",
        evidence_source="https://etender.uzex.uz/lot/99",
        buyer="Health Procurement Agency", country="Uzbekistan",
        related_tender_title="Gas compressor rotor refurbishment services",
        evidence_date=datetime.now(timezone.utc),
    )
    service = tenders._infer_tender_service_category(open_lot)
    assert service == "other"
    assert tenders._qualified_competitor_record(
        target_tender=open_lot, record=prior_award, target_service_category=service,
    ) is not None
    unrelated = prior_award.model_copy(update={"related_tender_title": "Hospital linen laundry services"})
    assert tenders._qualified_competitor_record(
        target_tender=open_lot, record=unrelated, target_service_category=service,
    ) is None


def test_uzex_other_bucket_uses_specific_title_terms_but_not_generic_purchase():
    medical = target(
        "uzex", category="Other", procurement_category=None, description=None, sector=None,
        title='Lot 17 "Antitimotsitar immunoglobulin" Gematologiya PQ-4592',
    )
    generic = target(
        "uzex", category="Other", procurement_category=None, description=None, sector=None,
        title="SHNGQCHB ehtiyoji uchun Adsorber xarid qilish",
    )
    assert tenders._infer_tender_service_category(medical) == "medical"
    assert tenders._infer_tender_service_category(generic) == "other"
