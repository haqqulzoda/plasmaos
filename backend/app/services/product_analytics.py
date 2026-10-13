"""Sprint 1: server-side product events, the AI cost ledger and the admin metrics.

Events record who (organization, user, membership), what (event name, ids) and when, plus a
few code/number properties. They never carry document content, names or free text:
``clean_properties`` keeps only short code strings, numbers and booleans.

Write-path events are staged in the action's own transaction (``stage_product_event``), so
they exist exactly when the action committed. View events (tender details, the pursuit
workspace, EOI downloads) come from a route dependency that writes in its own session after
a successful response (``track_view``): the read itself stays passive, and a failed read
records nothing.
"""

from __future__ import annotations

import logging
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable
from uuid import UUID

from fastapi import BackgroundTasks, Depends, Request
from sqlalchemy import func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_pricing import price_table
from app.core.ai_usage import AICall
from app.models.product_analytics import PRODUCT_EVENT_NAMES, AICallCost, ProductEvent
from app.models.user import User

logger = logging.getLogger(__name__)

_PROPERTY_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_PROPERTY_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
FUNNEL_STEPS = (
    "sign_in", "tender_viewed", "workspace_opened", "analysis_started", "analysis_completed",
    "review_confirmed", "eoi_generated", "eoi_downloaded",
)


def clean_properties(properties: dict[str, Any] | None) -> dict[str, Any]:
    """Codes, numbers, booleans and ids only; anything else is dropped."""
    cleaned: dict[str, Any] = {}
    for key, value in (properties or {}).items():
        if not isinstance(key, str) or not _PROPERTY_KEY.match(key) or value is None:
            continue
        if isinstance(value, bool):
            cleaned[key] = value
        elif isinstance(value, int):
            cleaned[key] = value
        elif isinstance(value, float) and math.isfinite(value):
            cleaned[key] = value
        elif isinstance(value, UUID):
            cleaned[key] = str(value)
        elif isinstance(value, str) and _PROPERTY_CODE.match(value):
            cleaned[key] = value
    return cleaned


def stage_product_event(
    db: AsyncSession,
    event_name: str,
    *,
    organization_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    actor_membership_id: UUID | None = None,
    tender_id: UUID | None = None,
    pursuit_id: UUID | None = None,
    analysis_run_id: UUID | None = None,
    subject_type: str | None = None,
    subject_id: UUID | None = None,
    properties: dict[str, Any] | None = None,
) -> ProductEvent:
    if event_name not in PRODUCT_EVENT_NAMES:
        raise ValueError(f"unknown product event {event_name!r}")
    event = ProductEvent(
        event_name=event_name, organization_id=organization_id, actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id, tender_id=tender_id, pursuit_id=pursuit_id,
        analysis_run_id=analysis_run_id, subject_type=subject_type, subject_id=subject_id,
        properties=clean_properties(properties),
    )
    db.add(event)
    return event


# ---- view events ------------------------------------------------------------------------------------

def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


async def record_view_event(
    event_name: str,
    *,
    user_id: UUID,
    selected_organization_id: UUID | None,
    tender_id: UUID | None = None,
    pursuit_id: UUID | None = None,
    subject_type: str | None = None,
    subject_id: UUID | None = None,
    session_factory: Callable[[], Any] | None = None,
) -> None:
    """Background task: resolve the organization and write one event in its own session."""
    from app.models.tenancy import Membership, OrganizationPursuit
    from app.services.organization_context import organization_profile_context

    if session_factory is None:
        from app.db.session import AsyncSessionLocal as session_factory
    try:
        async with session_factory() as db:
            organization_id = membership_id = None
            if pursuit_id is not None:
                organization_id = await db.scalar(
                    select(OrganizationPursuit.organization_id).where(OrganizationPursuit.id == pursuit_id)
                )
            if organization_id is None:
                context = await organization_profile_context(
                    db, user_id=user_id, organization_id=selected_organization_id
                )
                if context is not None:
                    organization_id, membership_id = context.organization.id, context.membership.id
            if organization_id is not None and membership_id is None:
                membership_id = await db.scalar(select(Membership.id).where(
                    Membership.organization_id == organization_id, Membership.user_id == user_id,
                ))
            stage_product_event(
                db, event_name, organization_id=organization_id, actor_user_id=user_id,
                actor_membership_id=membership_id, tender_id=tender_id, pursuit_id=pursuit_id,
                subject_type=subject_type, subject_id=subject_id,
            )
            await db.commit()
    except Exception as exc:  # analytics never breaks or retries a product read
        logger.warning("product_event_failed event=%s error=%s", event_name, type(exc).__name__)


def track_view(
    event_name: str,
    *,
    tender_param: str | None = None,
    pursuit_param: str | None = None,
    subject_type: str | None = None,
    subject_param: str | None = None,
):
    """Route dependency: after a successful response, record ``event_name`` for the caller."""
    from app.api.deps import get_current_user

    async def dependency(
        request: Request, background: BackgroundTasks, current_user: User = Depends(get_current_user),
    ) -> None:
        from app.services.organization_context import SELECTED_ORGANIZATION

        params = request.path_params
        background.add_task(
            record_view_event, event_name, user_id=current_user.id,
            selected_organization_id=SELECTED_ORGANIZATION.get(),
            tender_id=_uuid(params.get(tender_param)) if tender_param else None,
            pursuit_id=_uuid(params.get(pursuit_param)) if pursuit_param else None,
            subject_type=subject_type,
            subject_id=_uuid(params.get(subject_param)) if subject_param else None,
        )

    return dependency


# ---- AI cost ledger ---------------------------------------------------------------------------------

def stage_ai_costs(
    db: AsyncSession,
    calls: Iterable[AICall],
    *,
    call_kind: str,
    subject_type: str,
    subject_id: UUID,
    organization_id: UUID | None = None,
    pursuit_id: UUID | None = None,
    model_provider: str = "google-gemini",
) -> int:
    table = price_table()
    count = 0
    for call in calls:
        db.add(AICallCost(
            call_kind=call_kind, organization_id=organization_id, pursuit_id=pursuit_id,
            subject_type=subject_type, subject_id=subject_id, model_provider=model_provider,
            model_name=call.model_name, outcome=call.outcome, input_tokens=call.input_tokens,
            output_tokens=call.output_tokens, thinking_tokens=call.thinking_tokens, latency_ms=call.latency_ms,
            estimated_cost_usd=table.estimate(
                call.model_name, call.input_tokens, call.output_tokens, call.thinking_tokens
            ),
            price_table_version=table.version,
        ))
        count += 1
    return count


# ---- admin metrics ----------------------------------------------------------------------------------

async def _demo_organization_ids(db: AsyncSession) -> set[UUID]:
    from app.models.company import CompanyProfile
    from app.models.tenancy import Organization
    from app.services.admin_panels import DEMO_PROFILE_MARKER

    rows = await db.execute(
        select(Organization.id).join(CompanyProfile, CompanyProfile.id == Organization.legacy_company_profile_id)
        .where(CompanyProfile.notes.like(DEMO_PROFILE_MARKER + "%"))
    )
    return {row[0] for row in rows}


def _week_start(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    monday = value - timedelta(days=value.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def _money(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


async def product_metrics(
    db: AsyncSession, *, weeks: int = 8, funnel_days: int = 28, include_demo: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Weekly active organizations, the funnel, analysis time and AI cost. Ids and counts only."""
    from app.models.pursuit_analysis import AnalysisRun

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    excluded = set() if include_demo else await _demo_organization_ids(db)
    first_week = _week_start(now) - timedelta(weeks=weeks - 1)

    def visible(column):
        return or_(column.is_(None), column.notin_(excluded)) if excluded else true()

    # Weekly active organizations: any event by a member of the organization that week.
    rows = await db.execute(
        select(ProductEvent.organization_id, ProductEvent.occurred_at).where(
            ProductEvent.organization_id.is_not(None), ProductEvent.occurred_at >= first_week,
            visible(ProductEvent.organization_id),
        )
    )
    weekly: dict[datetime, set[UUID]] = defaultdict(set)
    for organization_id, occurred_at in rows:
        weekly[_week_start(occurred_at)].add(organization_id)
    weekly_active = [
        {"week_start": (first_week + timedelta(weeks=index)).date(),
         "active_organizations": len(weekly.get(first_week + timedelta(weeks=index), set()))}
        for index in range(weeks)
    ]

    # Funnel: organizations (and events) reaching each step in the window.
    since = now - timedelta(days=funnel_days)
    counts = {name: (0, 0) for name in FUNNEL_STEPS}
    for name, organizations, events in await db.execute(
        select(ProductEvent.event_name, func.count(func.distinct(ProductEvent.organization_id)), func.count())
        .where(ProductEvent.occurred_at >= since, ProductEvent.event_name.in_(FUNNEL_STEPS),
               visible(ProductEvent.organization_id))
        .group_by(ProductEvent.event_name)
    ):
        counts[name] = (int(organizations), int(events))
    other = {name: int(count) for name, count in await db.execute(
        select(ProductEvent.event_name, func.count())
        .where(ProductEvent.occurred_at >= since, ProductEvent.event_name.notin_(FUNNEL_STEPS),
               visible(ProductEvent.organization_id))
        .group_by(ProductEvent.event_name)
    )}
    funnel = [{"step": name, "organizations": counts[name][0], "events": counts[name][1]} for name in FUNNEL_STEPS]

    # Analysis time: completed runs in the window, from request to result and processing only.
    runs = (await db.execute(
        select(AnalysisRun.id, AnalysisRun.created_at, AnalysisRun.started_at, AnalysisRun.completed_at)
        .where(AnalysisRun.status == "COMPLETED", AnalysisRun.completed_at >= since, visible(AnalysisRun.organization_id))
    )).all()
    to_result = [(completed - created).total_seconds() * 1000 for _, created, _, completed in runs if created and completed]
    processing = [(completed - started).total_seconds() * 1000 for _, _, started, completed in runs if started and completed]
    failed_runs = int(await db.scalar(select(func.count()).select_from(AnalysisRun).where(
        AnalysisRun.status == "FAILED", AnalysisRun.completed_at >= since, visible(AnalysisRun.organization_id),
    )) or 0)

    # AI cost: per call kind, and per completed analysis (every call of the run, failed attempts included).
    cost_rows = (await db.execute(
        select(AICallCost.call_kind, func.count(), func.count(func.distinct(AICallCost.subject_id)),
               func.coalesce(func.sum(AICallCost.input_tokens), 0), func.coalesce(func.sum(AICallCost.output_tokens), 0),
               func.coalesce(func.sum(AICallCost.thinking_tokens), 0), func.sum(AICallCost.estimated_cost_usd),
               func.count().filter(AICallCost.estimated_cost_usd.is_(None)))
        .where(AICallCost.created_at >= since, visible(AICallCost.organization_id))
        .group_by(AICallCost.call_kind)
    )).all()
    by_kind = [{
        "call_kind": kind, "calls": int(calls), "subjects": int(subjects), "input_tokens": int(tokens_in),
        "output_tokens": int(tokens_out), "thinking_tokens": int(thinking), "estimated_cost_usd": _money(cost),
        "calls_without_price": int(unpriced),
    } for kind, calls, subjects, tokens_in, tokens_out, thinking, cost, unpriced in cost_rows]
    completed_ids = [run_id for run_id, *_ in runs]
    per_run: list[float] = []
    if completed_ids:
        per_run = [float(value or 0) for (value,) in (await db.execute(
            select(func.sum(AICallCost.estimated_cost_usd)).where(
                AICallCost.call_kind == "ANALYSIS", AICallCost.subject_id.in_(completed_ids),
            ).group_by(AICallCost.subject_id)
        )).all()]
    return {
        "generated_at": now,
        "include_demo": include_demo,
        "excluded_demo_organizations": len(excluded),
        "weeks": weeks,
        "funnel_days": funnel_days,
        "weekly_active_organizations": weekly_active,
        "funnel": funnel,
        "other_events": other,
        "analysis": {
            "completed": len(runs),
            "failed": failed_runs,
            "median_time_to_result_ms": int(statistics.median(to_result)) if to_result else None,
            "median_processing_ms": int(statistics.median(processing)) if processing else None,
            "p90_time_to_result_ms": int(sorted(to_result)[max(0, math.ceil(len(to_result) * 0.9) - 1)]) if to_result else None,
        },
        "cost": {
            "price_table_version": price_table().version,
            "by_kind": by_kind,
            "analyses_with_cost": len(per_run),
            "mean_cost_per_analysis_usd": round(sum(per_run) / len(per_run), 6) if per_run else None,
            "median_cost_per_analysis_usd": round(statistics.median(per_run), 6) if per_run else None,
        },
    }
