"""Sprint 1: admin product metrics. Passive read of ids, counts, timings and estimated cost."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_db
from app.services.product_analytics import product_metrics


router = APIRouter(dependencies=[Depends(require_admin)])


class WeeklyActive(BaseModel):
    week_start: date
    active_organizations: int


class FunnelStep(BaseModel):
    step: str
    organizations: int
    events: int


class AnalysisTiming(BaseModel):
    completed: int
    failed: int
    median_time_to_result_ms: int | None = None
    median_processing_ms: int | None = None
    p90_time_to_result_ms: int | None = None


class CostByKind(BaseModel):
    call_kind: str
    calls: int
    subjects: int
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    estimated_cost_usd: float | None = None
    calls_without_price: int


class CostSummary(BaseModel):
    price_table_version: str
    by_kind: list[CostByKind]
    analyses_with_cost: int
    mean_cost_per_analysis_usd: float | None = None
    median_cost_per_analysis_usd: float | None = None


class ProductMetrics(BaseModel):
    generated_at: datetime
    include_demo: bool
    excluded_demo_organizations: int
    weeks: int
    funnel_days: int
    weekly_active_organizations: list[WeeklyActive]
    funnel: list[FunnelStep]
    other_events: dict[str, int]
    analysis: AnalysisTiming
    cost: CostSummary


@router.get("", response_model=ProductMetrics)
async def admin_product_metrics(
    weeks: int = Query(default=8, ge=1, le=52),
    funnel_days: int = Query(default=28, ge=1, le=365),
    include_demo: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> ProductMetrics:
    return ProductMetrics(**await product_metrics(db, weeks=weeks, funnel_days=funnel_days, include_demo=include_demo))
