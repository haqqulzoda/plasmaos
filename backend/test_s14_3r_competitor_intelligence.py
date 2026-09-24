"""Sprint 14.3R: source-local, evidence-backed competitor qualification."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.api.endpoints import tenders
from app.services.competitor_cache import (
    cached_competitor_records,
    competitor_cache_was_evaluated,
    metadata_with_competitor_cache,
)


OFFICIAL = {
    "world_bank": "https://projects.worldbank.org/en/projects-operations/procurement-detail/OP100",
    "uzex": "https://etender.uzex.uz/lot/100",
    "adb": "https://www.adb.org/node/100",
    "giz": "https://www.giz.de/en/100",
    "ebrd": "https://ecepp.ebrd.com/100",
}


def tender(source="world_bank", **values):
    row = dict(
        id=uuid4(), external_id="TARGET-100", source_system=source,
        source_url=OFFICIAL[source], title="Hospital diagnostic equipment supply",
        description="Diagnostic equipment for public hospitals", country="Uzbekistan",
        sector="Health", buyer="Health Procurement Agency", procurement_category="Goods",
        procurement_method="Open", notice_type="Invitation", category="Medical",
        project_id="P-100", publication_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), source_metadata_json={},
    )
    row.update(values)
    return SimpleNamespace(**row)


def history(source="world_bank", name="Medical Supplier LLC", **values):
    fields = dict(
        id=uuid4(), external_id="HISTORY-101", project_id="P-101",
        source_metadata_json={"awarded_supplier_name": name},
    )
    fields.update(values)
    return tender(source, **fields)


def extracted(target, related):
    return tenders._extract_public_competitor_records(
        target_tender=target, related_tender=related,
        target_service_category=tenders._infer_tender_service_category(target),
    )


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


def builder(target, related=()):
    db = MagicMock()
    db.execute = AsyncMock(return_value=Rows(list(related)))
    with patch.object(tenders, "_live_source_competitor_records", new=AsyncMock(
        side_effect=AssertionError("customer GET must be stored-only"),
    )) as source:
        result = asyncio.run(tenders._build_tender_competitor_intelligence(
            db=db, target_tender=target, include_live_sources=False,
        ))
    source.assert_not_awaited()
    assert db.execute.await_count <= 1
    if db.execute.await_count:
        assert db.execute.await_args.args[0]._limit_clause.value == tenders.COMPETITOR_MAX_RELATED_TENDERS
    return result


def test_direct_same_buyer_service_and_project_are_specific():
    target = tender()
    record = extracted(target, history())
    assert len(record) == 1
    assert record[0].relevance_tier == "DIRECT"
    assert "Health Procurement Agency" in record[0].reason
    assert record[0].evidence_source == OFFICIAL["world_bank"]
    assert record[0].source_reference == "HISTORY-101"
    assert record[0].related_tender_title == target.title
    assert builder(target, [history()]).state == "AVAILABLE"


def test_strong_recent_same_market_service_procurement_and_sector():
    target = tender(project_id="OTHER")
    record = extracted(target, history(
        buyer="Different Agency", project_id="P-101",
        source_url="https://projects.worldbank.org/en/projects-operations/procurement-detail/OP101",
    ))
    assert len(record) == 1
    assert record[0].relevance_tier == "STRONG"
    assert "recent" in record[0].reason


@pytest.mark.parametrize("change", [
    {"country": "Tanzania"},
    {"category": "Construction", "procurement_category": "Works", "sector": "Transport", "buyer": "Different Agency", "title": "Road works", "description": "Road works"},
    {"buyer": "Different Agency", "country": None, "sector": "Transport"},
    {"buyer": "Different Agency", "publication_date": datetime(2018, 1, 1, tzinfo=timezone.utc)},
])
def test_unrelated_wrong_market_or_old_history_is_rejected(change):
    target = tender()
    related = history(**change)
    assert extracted(target, related) == []
    assert builder(target, [related]).state == "INSUFFICIENT_EVIDENCE"


def test_broad_market_actor_labels_are_not_evidence_even_when_repeated():
    target = tender()
    rows = [history(source_metadata_json={"similar_market_actors": ["Generic Actor"]}) for _ in range(2)]
    assert all(extracted(target, row) == [] for row in rows)
    assert builder(target, rows).state == "UNAVAILABLE"


def test_invalid_or_wrong_source_evidence_url_is_rejected():
    target = tender()
    for url in ("javascript:alert(1)", "https://other.example/notice", "https://user:pass@projects.worldbank.org/x", "http://projects.worldbank.org/x", "https://[invalid"):
        assert extracted(target, history(source_url=url)) == []


def test_duplicate_company_names_collapse_without_fuzzy_cross_source_merges():
    target = tender()
    first = extracted(target, history(name="Med Supply LLC"))[0]
    second = extracted(target, history(name="MED SUPPLY LLC."))[0]
    groups = tenders._group_competitor_records([first, second])
    assert sum(len(group.competitors) for group in groups) == 1
    assert extracted(target, history("adb", name="Med Supply LLC")) == []


@pytest.mark.parametrize("source", ["world_bank", "uzex", "adb"])
def test_verified_source_local_award_metadata_can_qualify(source):
    target = tender(source)
    record = extracted(target, history(source))
    assert len(record) == 1
    assert record[0].source == source
    assert record[0].evidence_source == OFFICIAL[source]


@pytest.mark.parametrize("source", ["giz", "ebrd"])
def test_unsupported_award_authority_is_unavailable_not_fabricated(source):
    target = tender(source)
    related = history(source)
    assert extracted(target, related) == []
    assert builder(target, [related]).state == "UNAVAILABLE"


def test_evaluated_empty_cache_differs_from_never_evaluated():
    target = tender()
    assert builder(target).state == "UNAVAILABLE"
    target.source_metadata_json = metadata_with_competitor_cache({}, [], source_system="world_bank")
    assert competitor_cache_was_evaluated(target.source_metadata_json)
    assert builder(target).state == "INSUFFICIENT_EVIDENCE"


def test_adb_named_award_rss_needs_sector_country_and_date_for_strong_match():
    target = tender(
        "adb", title="Road rehabilitation works", description="Road civil works",
        category="Construction", procurement_category="Works", sector="Transport",
        buyer="Different Agency", project_id="P-900",
    )
    rss = """<rss><channel><item>
      <title>Road rehabilitation contract awarded to Verified Roads Ltd</title>
      <link>https://www.adb.org/node/101</link>
      <pubDate>Tue, 15 Sep 2026 10:00:00 GMT</pubDate>
      <category>Countries: Uzbekistan|Sectors: Transport|Status: Awarded</category>
    </item></channel></rss>"""
    with patch.object(tenders, "_fetch_text_payload", new=AsyncMock(return_value=rss)):
        records = asyncio.run(tenders._live_adb_competitor_records(
            target_tender=target, target_service_category="construction",
        ))
    assert len(records) == 1
    item = tenders._qualified_competitor_record(
        target_tender=target, record=records[0], target_service_category="construction",
    )
    assert item is not None
    assert item.relevance_tier == "STRONG"
    assert item.evidence_source == "https://www.adb.org/node/101"


def test_adb_named_award_without_market_context_is_rejected():
    target = tender("adb", title="Road rehabilitation works", category="Construction", sector="Transport")
    record = tenders._live_competitor_record(
        company_name="Road Actor", source_system="adb", service_category="construction",
        participation_type="winner", confidence="high", reason="Generic award",
        evidence_source="https://www.adb.org/node/101", related_tender_title="Road rehabilitation",
    )
    assert tenders._qualified_competitor_record(
        target_tender=target, record=record, target_service_category="construction",
    ) is None


def test_legacy_generic_cache_is_requalified_before_read():
    target = tender()
    broad = tenders.TenderCompetitorResponse(
        company_name="Broad Actor", industry="Medical", service_category="medical",
        source="world_bank", participation_type="participant", confidence="high",
        reason="Participated in previous tenders.", evidence_source=OFFICIAL["world_bank"],
    )
    target.source_metadata_json = metadata_with_competitor_cache({}, [broad], source_system="world_bank")
    assert len(cached_competitor_records(target.source_metadata_json)) == 1
    result = builder(target)
    assert result.state == "INSUFFICIENT_EVIDENCE"
    assert result.groups == []


@pytest.mark.parametrize("source", ["giz", "ebrd"])
def test_unverified_source_remains_unavailable_despite_legacy_cache_marker(source):
    target = tender(source)
    legacy = tenders._live_competitor_record(
        company_name="Unverified Supplier", source_system=source,
        service_category="medical", participation_type="winner", confidence="high",
        reason="Old unverified cache", evidence_source=OFFICIAL[source],
        buyer="Health Procurement Agency", country="Uzbekistan",
        related_tender_title="Hospital equipment",
    )
    target.source_metadata_json = metadata_with_competitor_cache(
        {}, [legacy], source_system=source,
    )
    db = MagicMock()
    db.execute = AsyncMock(side_effect=AssertionError("unverified source must not be queried"))
    result = asyncio.run(tenders._build_tender_competitor_intelligence(
        db=db, target_tender=target, include_live_sources=True,
    ))
    assert result.state == "UNAVAILABLE"
    assert result.groups == []
    db.execute.assert_not_awaited()


def test_source_refresh_per_tender_qualification_and_idempotence():
    direct = tender("uzex")
    unrelated = tender("uzex", buyer="Other Agency", country="Tanzania", project_id="OTHER")
    db = MagicMock()
    db.execute = AsyncMock(return_value=Rows([direct, unrelated]))
    db.commit = AsyncMock()
    evidence = tenders._live_competitor_record(
        company_name="Verified Supplier", source_system="uzex", service_category="medical",
        participation_type="winner", confidence="high", reason="Legacy broad copy",
        evidence_source=OFFICIAL["uzex"], buyer="Health Procurement Agency",
        country="Uzbekistan", category="Goods", related_tender_title="Hospital equipment",
    )
    with patch.object(tenders, "_live_source_competitor_records", new=AsyncMock(return_value=[evidence])):
        first = asyncio.run(tenders._refresh_source_competitor_cache(db=db, source_system="uzex", target_limit=2))
        second = asyncio.run(tenders._refresh_source_competitor_cache(db=db, source_system="uzex", target_limit=2))
    assert first == {"targets_considered": 2, "targets_updated": 2, "records_cached": 1}
    assert second == {"targets_considered": 2, "targets_updated": 0, "records_cached": 0}
    assert cached_competitor_records(direct.source_metadata_json)[0].relevance_tier == "DIRECT"
    assert cached_competitor_records(unrelated.source_metadata_json) == []
    assert competitor_cache_was_evaluated(unrelated.source_metadata_json)
    assert db.commit.await_count == 1


def test_uzex_source_retains_candidates_after_thirtieth_result():
    target = tender("uzex")
    rows = [
        {
            "trade_id": index,
            "provider_name": f"Supplier {index}",
            "customer_name": "Health Procurement Agency",
            "category_name": "Medical equipment",
        }
        for index in range(1, 32)
    ]
    with patch.object(tenders, "_fetch_json_payload", new=AsyncMock(return_value=rows)):
        records = asyncio.run(tenders._live_uzex_competitor_records(
            target_tender=target, target_service_category="medical",
        ))
    assert len(records) == 31
    assert records[-1].company_name == "Supplier 31"


def test_source_refresh_qualifies_candidate_after_first_thirty():
    target = tender("uzex")
    db = MagicMock()
    db.execute = AsyncMock(return_value=Rows([target]))
    db.commit = AsyncMock()
    unrelated = [
        tenders._live_competitor_record(
            company_name=f"Unrelated Supplier {index}", source_system="uzex",
            service_category="medical", participation_type="winner", confidence="high",
            reason="Unrelated historical award", evidence_source=OFFICIAL["uzex"],
            buyer="Other Agency", country="Tanzania", category="Goods",
            related_tender_title="Unrelated equipment",
        )
        for index in range(30)
    ]
    relevant = tenders._live_competitor_record(
        company_name="Relevant Supplier", source_system="uzex", service_category="medical",
        participation_type="winner", confidence="high", reason="Historical award",
        evidence_source=OFFICIAL["uzex"], buyer="Health Procurement Agency",
        country="Uzbekistan", category="Goods", related_tender_title="Hospital equipment",
    )
    with patch.object(
        tenders, "_live_source_competitor_records",
        new=AsyncMock(return_value=[*unrelated, relevant]),
    ):
        result = asyncio.run(tenders._refresh_source_competitor_cache(db=db, source_system="uzex"))
    assert result == {"targets_considered": 1, "targets_updated": 1, "records_cached": 1}
    assert cached_competitor_records(target.source_metadata_json)[0].company_name == "Relevant Supplier"


def test_source_outage_does_not_erase_cache_or_write():
    target = tender("world_bank")
    target.source_metadata_json = metadata_with_competitor_cache({}, [], source_system="world_bank")
    before = target.source_metadata_json
    db = MagicMock()
    db.execute = AsyncMock(return_value=Rows([target]))
    db.commit = AsyncMock()
    with patch.object(tenders, "_live_source_competitor_records", new=AsyncMock(side_effect=RuntimeError("outage"))):
        with pytest.raises(RuntimeError, match="outage"):
            asyncio.run(tenders._refresh_source_competitor_cache(db=db, source_system="world_bank"))
    assert target.source_metadata_json == before
    db.commit.assert_not_awaited()
