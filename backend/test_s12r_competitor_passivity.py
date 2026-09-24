"""Sprint 12R hard regression coverage for passive Tender Details reads."""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.api.endpoints import tenders
from app.services.competitor_cache import (
    COMPETITOR_CACHE_METADATA_KEY,
    cached_competitor_records,
    metadata_with_competitor_cache,
)
from app.services.tender_sources.base import (
    NormalizedTender,
    _normalized_source_values,
    _source_values_for_existing,
)
from app.workers import source_refresh_tasks


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


def _tender(**overrides):
    values = {
        "id": uuid4(),
        "external_id": "S12R-TARGET",
        "source_system": "world_bank",
        "source_url": "https://projects.worldbank.org/en/projects-operations/procurement-detail/OP0042",
        "title": "Road construction works",
        "description": "Civil works for road rehabilitation",
        "country": "Uzbekistan",
        "sector": "Transport",
        "buyer": "Public Buyer",
        "procurement_category": "Works",
        "procurement_method": "Open",
        "notice_type": "Invitation",
        "category": "Construction",
        "publication_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "source_metadata_json": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _winner(name: str = "Canonical Builder LLC"):
    return tenders.TenderCompetitorResponse(
        company_name=name,
        industry="Construction",
        service_category="construction",
        source="world_bank",
        participation_type="winner",
        confidence="high",
        reason="Public historical award evidence.",
        evidence_source="https://projects.worldbank.org/en/projects-operations/procurement-detail/OP0041",
        buyer="Public Buyer",
        country="Uzbekistan",
        related_tender_title="Road construction works",
        category="Works",
    )


def test_tender_gets_are_hard_wired_away_from_source_adapters() -> None:
    details_source = inspect.getsource(tenders.get_tender_details)
    base_source = inspect.getsource(tenders.get_tender)
    assert "include_live_sources=False" in details_source
    for source in (details_source, base_source):
        assert "_live_source_competitor_records" not in source
        assert "_fetch_json_payload" not in source
        assert "_fetch_text_payload" not in source


def test_details_builder_reads_canonical_cache_without_any_network() -> None:
    metadata = metadata_with_competitor_cache(
        {},
        [_winner()],
        source_system="world_bank",
        refreshed_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
    )
    target = _tender(source_metadata_json=metadata)
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarRows([]))

    with patch.object(
        tenders,
        "_live_source_competitor_records",
        new=AsyncMock(side_effect=AssertionError("GET must never call source adapters")),
    ) as live_source:
        result = asyncio.run(
            tenders._build_tender_competitor_intelligence(
                db=db,
                target_tender=target,
                include_live_sources=False,
            )
        )

    live_source.assert_not_awaited()
    assert result.groups[0].competitors[0].company_name == "Canonical Builder LLC"


def test_unclassified_tender_rejects_unrelated_canonical_cache() -> None:
    metadata = metadata_with_competitor_cache(
        {}, [_winner()], source_system="world_bank"
    )
    target = _tender(
        title="Unclassified opportunity",
        description=None,
        sector=None,
        buyer=None,
        procurement_category=None,
        procurement_method=None,
        notice_type=None,
        category=None,
        source_metadata_json=metadata,
    )
    db = MagicMock()
    db.execute = AsyncMock()

    result = asyncio.run(
        tenders._build_tender_competitor_intelligence(
            db=db,
            target_tender=target,
            include_live_sources=False,
        )
    )

    db.execute.assert_not_awaited()
    assert result.groups == []
    assert result.state == "INSUFFICIENT_EVIDENCE"


def test_source_refresh_lifecycle_populates_bounded_persisted_cache() -> None:
    targets = [_tender(id=uuid4()), _tender(id=uuid4())]
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarRows(targets))
    db.commit = AsyncMock()

    with patch.object(
        tenders,
        "_live_source_competitor_records",
        new=AsyncMock(return_value=[_winner()]),
    ) as live_source:
        result = asyncio.run(
            tenders._refresh_source_competitor_cache(
                db=db,
                source_system="world_bank",
                target_limit=2,
            )
        )

    live_source.assert_awaited_once()
    assert live_source.await_args.kwargs["use_cache"] is False
    db.commit.assert_awaited_once()
    assert result == {
        "targets_considered": 2,
        "targets_updated": 2,
        "records_cached": 2,
    }
    for target in targets:
        assert COMPETITOR_CACHE_METADATA_KEY in target.source_metadata_json
        assert cached_competitor_records(target.source_metadata_json)[0].company_name == (
            "Canonical Builder LLC"
        )


def test_empty_or_unavailable_background_result_never_erases_valid_cache() -> None:
    existing = metadata_with_competitor_cache(
        {}, [_winner()], source_system="world_bank"
    )
    target = _tender(source_metadata_json=existing)
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarRows([target]))
    db.commit = AsyncMock()

    with patch.object(
        tenders,
        "_live_source_competitor_records",
        new=AsyncMock(return_value=[]),
    ):
        result = asyncio.run(
            tenders._refresh_source_competitor_cache(
                db=db,
                source_system="world_bank",
                target_limit=1,
            )
        )

    db.commit.assert_not_awaited()
    assert result["targets_updated"] == 0
    assert cached_competitor_records(target.source_metadata_json)[0].company_name == (
        "Canonical Builder LLC"
    )


def test_source_upsert_preserves_plasma_owned_competitor_cache() -> None:
    existing = metadata_with_competitor_cache(
        {"old_source_field": "replaced"},
        [_winner()],
        source_system="world_bank",
    )
    target = SimpleNamespace(source_metadata_json=existing)
    incoming = NormalizedTender(
        source_system="world_bank",
        external_id="S12R-TARGET",
        source_url="https://example.invalid/tender",
        title="Road construction works",
        source_metadata_json={
            "new_source_field": "current",
            COMPETITOR_CACHE_METADATA_KEY: {
                "version": 1,
                "records": [{"company_name": "Untrusted Source Injection"}],
            },
        },
    )

    values = _source_values_for_existing(target, incoming)

    metadata = values["source_metadata_json"]
    assert metadata["new_source_field"] == "current"
    assert "old_source_field" not in metadata
    assert cached_competitor_records(metadata)[0].company_name == "Canonical Builder LLC"


def test_new_source_payload_cannot_create_plasma_owned_cache() -> None:
    incoming = NormalizedTender(
        source_system="world_bank",
        external_id="S12R-NEW",
        source_url="https://example.invalid/tender",
        title="Road construction works",
        source_metadata_json={
            "public_source_field": "retained",
            COMPETITOR_CACHE_METADATA_KEY: {
                "version": 1,
                "records": [{"company_name": "Untrusted Source Injection"}],
            },
        },
    )

    metadata = _normalized_source_values(incoming)["source_metadata_json"]

    assert metadata == {"public_source_field": "retained"}


def test_worker_enrichment_is_explicit_additive_and_skips_dry_runs() -> None:
    source = inspect.getsource(source_refresh_tasks._execute_source_refresh)
    assert "_refresh_source_competitor_cache" in source
    assert 'if not job_options.get("dry_run")' in source
    assert "async with AsyncSessionLocal() as cache_db" in source
