"""Permanent regression coverage for the S12 Tender Details restoration."""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.api.endpoints import tenders
from app.schemas.tender import TenderCompetitorIntelligenceResponse
from app.schemas import tender_details as schemas
from app.services import tender_details


def _tender(**overrides):
    values = {
        "id": uuid4(),
        "external_id": "S12-TARGET",
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


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


def _empty(section_type):
    return section_type(state="EMPTY")


def test_details_endpoint_reuses_stored_authority_without_source_network() -> None:
    source = inspect.getsource(tenders.get_tender_details)
    builder_source = inspect.getsource(tenders._build_tender_competitor_intelligence)
    assert "_build_tender_competitor_intelligence" in source
    assert "include_live_sources=False" in source
    assert "competitor_intelligence=competitor_intelligence" in source
    assert "customer_visible_tender_condition(Tender)" in source
    assert "customer_visible_tender_condition(Tender)" in builder_source


def test_stored_projection_is_bounded_and_never_calls_source_network() -> None:
    target = _tender()
    related = _tender(
        id=uuid4(),
        external_id="S12-HISTORY",
        source_url="https://projects.worldbank.org/en/projects-operations/procurement-detail/OP0041",
        source_metadata_json={"awarded_supplier_name": "Canonical Builder LLC"},
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarRows([related]))

    with patch.object(
        tenders,
        "_live_source_competitor_records",
        new=AsyncMock(side_effect=AssertionError("passive details must not fetch sources")),
    ) as live_source:
        result = asyncio.run(
            tenders._build_tender_competitor_intelligence(
                db=db,
                target_tender=target,
                include_live_sources=False,
            )
        )

    live_source.assert_not_awaited()
    assert len(result.groups) == 1
    competitor = result.groups[0].competitors[0]
    assert competitor.company_name == "Canonical Builder LLC"
    assert competitor.participation_type == "winner"
    assert competitor.confidence == "high"
    assert competitor.evidence_source == related.source_url
    statement = db.execute.await_args.args[0]
    assert statement._limit_clause.value == tenders.COMPETITOR_MAX_RELATED_TENDERS


def test_details_composition_distinguishes_available_empty_and_unavailable() -> None:
    user_id = uuid4()
    target = _tender()
    profile = SimpleNamespace(id=uuid4(), user_id=user_id)
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=[profile, None])
    common_patches = (
        patch.object(
            tender_details,
            "_project_sections",
            new=AsyncMock(
                return_value=(
                    _empty(schemas.ProjectContextSection),
                    _empty(schemas.ProjectLeadershipSection),
                )
            ),
        ),
        patch.object(
            tender_details,
            "_documents_section",
            new=AsyncMock(return_value=_empty(schemas.TenderDocumentsSection)),
        ),
        patch.object(
            tender_details,
            "_private_sections",
            new=AsyncMock(
                return_value=tuple(
                    _empty(section_type)
                    for section_type in (
                        schemas.ComplianceSection,
                        schemas.RequirementsSection,
                        schemas.CompanyReadinessSection,
                        schemas.PursuitSection,
                        schemas.BidPreparationSection,
                    )
                )
            ),
        ),
    )

    available = TenderCompetitorIntelligenceResponse(
        tender_id=target.id,
        message=tenders.COMPETITOR_AVAILABLE_MESSAGE,
        state="AVAILABLE",
        groups=[
            tenders.TenderCompetitorGroup(
                industry="Construction",
                service_category="construction",
                competitors=[
                    tenders.TenderCompetitorResponse(
                        company_name="Canonical Builder LLC",
                        industry="Construction",
                        service_category="construction",
                        source="world_bank",
                        participation_type="winner",
                        confidence="high",
                        reason="Historical public award evidence.",
                    )
                ],
            )
        ],
    )
    with common_patches[0], common_patches[1], common_patches[2]:
        response = asyncio.run(
            tender_details.compose_tender_details(
                db,
                tender=target,
                user_id=user_id,
                procurement_contacts=None,
                competitor_intelligence=available,
            )
        )
    assert response.competitor_intelligence.state.value == "AVAILABLE"
    assert response.competitor_intelligence.data is available

    empty = available.model_copy(update={"groups": [], "state": "INSUFFICIENT_EVIDENCE"})
    db.scalar = AsyncMock(side_effect=[profile, None])
    with common_patches[0], common_patches[1], common_patches[2]:
        response = asyncio.run(
            tender_details.compose_tender_details(
                db,
                tender=target,
                user_id=user_id,
                procurement_contacts=None,
                competitor_intelligence=empty,
            )
        )
    assert response.competitor_intelligence.state.value == "INSUFFICIENT_EVIDENCE"

    db.scalar = AsyncMock(side_effect=[profile, None])
    with common_patches[0], common_patches[1], common_patches[2]:
        response = asyncio.run(
            tender_details.compose_tender_details(
                db,
                tender=target,
                user_id=user_id,
                procurement_contacts=None,
            )
        )
    assert response.competitor_intelligence.state.value == "UNAVAILABLE"


def test_restoration_adds_no_competitor_persistence_model() -> None:
    schema_source = inspect.getsource(schemas)
    service_source = inspect.getsource(tender_details)
    assert "class CompetitorIntelligenceSection" in schema_source
    for forbidden in ("class Competitor(", ".add(", ".flush(", ".commit(", "httpx"):
        assert forbidden not in service_source
