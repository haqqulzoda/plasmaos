"""Sprint 1: award ledger admin view, CSV export, firm export and market sizing.

Reads are passive. The ledger view and its CSV are operator reads; the firm export (an
outreach list) and the market sizing are admin downloads only. Public notice data only.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_operator
from app.db.session import get_db
from app.models.award_ledger import AWARD_OUTCOME_STATUSES
from app.services.award_ledger_reports import (
    OutcomeFilters,
    firm_export_csv,
    ledger_summary,
    list_outcomes,
    market_sizing,
    market_sizing_csv,
    market_sizing_markdown,
    outcome_values,
    outcomes_csv,
)


router = APIRouter(dependencies=[Depends(require_operator)])


class LedgerCountrySummary(BaseModel):
    country: str
    notices: int
    notices_without_bidders: int
    rows: dict[str, int]


class LedgerSummary(BaseModel):
    countries: list[LedgerCountrySummary]
    notice_count: int
    row_count: int
    stored_snapshot_count: int
    first_notice_date: date | None = None
    last_notice_date: date | None = None
    last_retrieved_at: datetime | None = None


class AwardOutcomeItem(BaseModel):
    id: UUID
    lender: str
    country: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    notice_id: str
    notice_url: str
    notice_date: date | None = None
    award_date: date | None = None
    package_reference: str | None = None
    package_title: str | None = None
    procurement_group: str | None = None
    procurement_method: str | None = None
    bid_ordinal: int
    member_ordinal: int
    member_count: int
    bidder_name: str
    bidder_source_id: str | None = None
    bidder_country: str | None = None
    bidder_kind: str
    status: str
    evaluated_price_text: str | None = None
    evaluated_price_currency: str | None = None
    evaluated_price_amount: Decimal | None = None
    signed_contract_price_text: str | None = None
    rejection_reason: str | None = None
    retrieved_at: datetime
    content_hash: str


class AwardOutcomePage(BaseModel):
    items: list[AwardOutcomeItem]
    total: int
    limit: int
    offset: int


def _filters(
    country: str | None = Query(default=None, max_length=120),
    status: str | None = Query(default=None, pattern="^(" + "|".join(AWARD_OUTCOME_STATUSES) + ")$"),
    procurement_group: str | None = Query(default=None, max_length=80),
    lender: str | None = Query(default=None, pattern="^(WORLD_BANK|ADB|EBRD)$"),
    q: str | None = Query(default=None, max_length=200),
) -> OutcomeFilters:
    return OutcomeFilters(country=country, status=status, procurement_group=procurement_group, lender=lender, q=q)


def _download(content: str, filename: str, media_type: str = "text/csv; charset=utf-8") -> Response:
    return Response(
        content=content, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"},
    )


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


@router.get("/summary", response_model=LedgerSummary)
async def award_ledger_summary(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await ledger_summary(db)


@router.get("/outcomes", response_model=AwardOutcomePage)
async def award_ledger_outcomes(
    filters: OutcomeFilters = Depends(_filters),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> AwardOutcomePage:
    rows, total = await list_outcomes(db, filters=filters, limit=limit, offset=offset)
    return AwardOutcomePage(
        items=[AwardOutcomeItem(**outcome_values(row, AwardOutcomeItem.model_fields)) for row in rows],
        total=total, limit=limit, offset=offset,
    )


@router.get("/outcomes.csv")
async def award_ledger_outcomes_csv(
    filters: OutcomeFilters = Depends(_filters), db: AsyncSession = Depends(get_db)
) -> Response:
    return _download(await outcomes_csv(db, filters=filters), f"award-ledger-{_stamp()}.csv")


@router.get("/firms.csv", dependencies=[Depends(require_admin)])
async def award_ledger_firms_csv(db: AsyncSession = Depends(get_db)) -> Response:
    content, _count = await firm_export_csv(db)
    return _download(content, f"award-ledger-firms-{_stamp()}.csv")


@router.get("/market-sizing.csv", dependencies=[Depends(require_admin)])
async def award_ledger_market_sizing_csv(db: AsyncSession = Depends(get_db)) -> Response:
    return _download(market_sizing_csv(await market_sizing(db)), f"market-sizing-central-asia-{_stamp()}.csv")


@router.get("/market-sizing.md", dependencies=[Depends(require_admin)])
async def award_ledger_market_sizing_markdown(db: AsyncSession = Depends(get_db)) -> Response:
    return _download(
        market_sizing_markdown(await market_sizing(db)), f"market-sizing-central-asia-{_stamp()}.md",
        media_type="text/markdown; charset=utf-8",
    )
