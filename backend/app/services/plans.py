"""P3: plan periods, usage, limits, feature gates and admin grants for one organization.

Counting rule: a pursuit counts once, when its first analysis starts (``admit_pursuit`` before the
run is created, ``record_pursuit`` in the same transaction). A pursuit that already counted never
counts again: re-analysis after an amendment, an admin retry, a new run on another document set.
The check and the insert hold a per-organization advisory lock, so two analyses started together
cannot both take the last pursuit.

Periods (app.core.plans): Explore the calendar month; Pilot its term from plan_started_on (every
pursuit since the start counts, also after plan_ends_on); paid plans the plan year from
plan_started_on; per-tender everything since plan_started_on. At 80% and 100% of a limit the team
gets one alert per period and threshold; the organization sees the notice in the app.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import (
    NEAR_LIMIT_SHARE,
    PERIOD_CALENDAR_MONTH,
    PERIOD_LIFETIME,
    PERIOD_PLAN_TERM,
    PERIOD_PLAN_YEAR,
    PLAN_EXPLORE,
    Plan,
    plan_for,
)
from app.models.base import MembershipState
from app.models.invitations import PendingInvitation
from app.models.partner_finder import PartnerRequest
from app.models.plans import OrganizationPlanGrant, OrganizationPursuitUsage
from app.models.tenancy import Membership, Organization

GRANT_PURSUITS = "PURSUITS"
GRANT_INTRODUCTIONS = "INTRODUCTIONS"


class PlanError(ValueError):
    status_code = 402
    code = "PLAN_LIMIT"

    def __init__(self, message: str, plan: str | None = None):
        super().__init__(message)
        self.plan = plan

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "plan": self.plan}


class PlanPursuitLimitError(PlanError):
    code = "PLAN_PURSUIT_LIMIT"


class PlanIntroductionLimitError(PlanError):
    code = "PLAN_INTRODUCTION_LIMIT"


class PlanUserLimitError(PlanError):
    code = "PLAN_USER_LIMIT"


class PlanFeatureError(PlanError):
    status_code = 403
    code = "PLAN_FEATURE"

    def __init__(self, feature: str, plan: str):
        super().__init__(f"The {plan} plan does not include {feature.replace('_', ' ')}", plan)
        self.feature = feature

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "feature": self.feature, "plan": self.plan}


class Period(NamedTuple):
    start: date
    end: date | None  # inclusive; None when the window is open
    count_until: date | None  # inclusive upper bound for counting (None: everything since start)


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:  # 29 February
        return value.replace(year=value.year + years, day=28)


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year, month = value.year + month // 12, month % 12 + 1
    for day in (value.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError(value)


def _anchor(organization: Organization) -> date:
    if organization.plan_started_on:
        return organization.plan_started_on
    created = organization.created_at or datetime.now(timezone.utc)
    return created.astimezone(timezone.utc).date()


def plan_period(organization: Organization, today: date) -> Period:
    plan = plan_for(organization.plan)
    if plan.period == PERIOD_CALENDAR_MONTH:
        start = today.replace(day=1)
        end = _add_months(start, 1) - timedelta(days=1)
        return Period(start, end, end)
    anchor = _anchor(organization)
    if plan.period == PERIOD_PLAN_TERM:
        end = organization.plan_ends_on or (_add_months(anchor, 3) - timedelta(days=1))
        return Period(anchor, end, None)
    if plan.period == PERIOD_PLAN_YEAR:
        years = today.year - anchor.year
        start = _add_years(anchor, years)
        if start > today:
            start = _add_years(anchor, years - 1)
        end = _add_years(start, 1) - timedelta(days=1)
        return Period(start, end, end)
    if plan.period == PERIOD_LIFETIME:
        return Period(anchor, None, None)
    raise ValueError(plan.period)


def _bounds(period: Period) -> tuple[datetime, datetime | None]:
    lower = datetime.combine(period.start, time.min, tzinfo=timezone.utc)
    upper = datetime.combine(period.count_until + timedelta(days=1), time.min, tzinfo=timezone.utc) if period.count_until else None
    return lower, upper


async def _grants(db: AsyncSession, organization_id: UUID, kind: str, period: Period) -> int:
    return int(await db.scalar(select(func.coalesce(func.sum(OrganizationPlanGrant.quantity), 0)).where(
        OrganizationPlanGrant.organization_id == organization_id, OrganizationPlanGrant.kind == kind,
        OrganizationPlanGrant.period_start == period.start,
    )) or 0)


async def pursuits_used(db: AsyncSession, organization_id: UUID, period: Period) -> int:
    lower, upper = _bounds(period)
    statement = select(func.count(OrganizationPursuitUsage.id)).where(
        OrganizationPursuitUsage.organization_id == organization_id, OrganizationPursuitUsage.counted_at >= lower,
    )
    if upper is not None:
        statement = statement.where(OrganizationPursuitUsage.counted_at < upper)
    return int(await db.scalar(statement) or 0)


async def introductions_used(db: AsyncSession, organization_id: UUID, period: Period) -> int:
    """Requests made in the period that were not declined (a declined introduction gives the quota back)."""
    lower, upper = _bounds(period)
    statement = select(func.count(PartnerRequest.id)).where(
        PartnerRequest.organization_id == organization_id, PartnerRequest.created_at >= lower,
        PartnerRequest.status != "DECLINED",
    )
    if upper is not None:
        statement = statement.where(PartnerRequest.created_at < upper)
    return int(await db.scalar(statement) or 0)


async def seats_used(db: AsyncSession, organization_id: UUID) -> int:
    """Active and invited members plus open e-mail invitations."""
    members = await db.scalar(select(func.count(Membership.id)).where(
        Membership.organization_id == organization_id,
        Membership.state.in_([MembershipState.ACTIVE, MembershipState.INVITED]),
    ))
    invitations = await db.scalar(select(func.count(PendingInvitation.id)).where(
        PendingInvitation.organization_id == organization_id, PendingInvitation.accepted_at.is_(None),
        PendingInvitation.revoked_at.is_(None), PendingInvitation.expires_at > datetime.now(timezone.utc),
    ))
    return int(members or 0) + int(invitations or 0)


def _limit(base: int | None, override: int | None, extra: int) -> int | None:
    value = override if override is not None else base
    return None if value is None else value + extra


def notice_for(used: int, limit: int | None) -> str:
    if limit is None:
        return "none"
    if used >= limit:
        return "limit_reached"
    if limit > 0 and used / limit >= NEAR_LIMIT_SHARE:
        return "near_limit"
    return "none"


async def plan_status(db: AsyncSession, organization: Organization, *, today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    plan = plan_for(organization.plan)
    period = plan_period(organization, today)
    extra_pursuits = await _grants(db, organization.id, GRANT_PURSUITS, period)
    extra_introductions = await _grants(db, organization.id, GRANT_INTRODUCTIONS, period)
    pursuit_limit = _limit(plan.pursuit_limit, organization.pursuit_limit_override, extra_pursuits)
    introduction_limit = _limit(plan.introduction_limit, organization.introduction_limit_override, extra_introductions)
    used = await pursuits_used(db, organization.id, period)
    introductions = await introductions_used(db, organization.id, period)
    return {
        "organization_id": organization.id,
        "plan": plan.code,
        "access_state": organization.access_state,
        "period_kind": plan.period,
        "period_start": period.start,
        "period_end": period.end,
        "plan_started_on": organization.plan_started_on,
        "plan_ends_on": organization.plan_ends_on,
        "pursuits": {
            "used": used, "limit": pursuit_limit, "extra_granted": extra_pursuits,
            "override": organization.pursuit_limit_override,
            "remaining": None if pursuit_limit is None else max(0, pursuit_limit - used),
            "notice": notice_for(used, pursuit_limit),
        },
        "introductions": {
            "used": introductions, "limit": introduction_limit, "extra_granted": extra_introductions,
            "override": organization.introduction_limit_override,
            "remaining": None if introduction_limit is None else max(0, introduction_limit - introductions),
            "notice": notice_for(introductions, introduction_limit) if introduction_limit else "none",
        },
        "users": {"used": await seats_used(db, organization.id), "limit": plan.user_limit},
        "features": {
            "tender_check": True, "eoi": plan.eoi, "own_evidence": plan.own_evidence,
            "partner_search": plan.partner_search, "competitor_intelligence": plan.has("competitor_intelligence"),
        },
        "intelligence": plan.intelligence,
    }


async def _lock(db: AsyncSession, organization_id: UUID) -> None:
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                     {"key": f"plasma:plan:{organization_id}"})


async def admit_pursuit(db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID) -> bool:
    """True when starting an analysis would count this pursuit; raises at the limit. Locks the organization."""
    await _lock(db, organization_id)
    counted = await db.scalar(select(OrganizationPursuitUsage.id).where(
        OrganizationPursuitUsage.organization_id == organization_id, OrganizationPursuitUsage.pursuit_id == pursuit_id,
    ))
    if counted is not None:
        return False
    organization = await db.get(Organization, organization_id)
    status = await plan_status(db, organization)
    limit, used = status["pursuits"]["limit"], status["pursuits"]["used"]
    if limit is not None and used >= limit:
        if organization.plan == PLAN_EXPLORE:
            raise PlanPursuitLimitError(
                "This month's free tender check is used. Start a pilot, or check another tender next month",
                organization.plan,
            )
        raise PlanPursuitLimitError(
            f"All {limit} pursuits of this plan period are used. Upgrade or add pursuits to analyse a new tender",
            organization.plan,
        )
    return True


async def record_pursuit(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, analysis_run_id: UUID,
) -> None:
    """Count the pursuit (after ``admit_pursuit`` returned True) and alert the team at 80% and 100%."""
    from app.services.admin_alerts import stage_admin_alert

    organization = await db.get(Organization, organization_id)
    db.add(OrganizationPursuitUsage(
        organization_id=organization_id, pursuit_id=pursuit_id, analysis_run_id=analysis_run_id,
        plan=organization.plan,
    ))
    await db.flush()
    status = await plan_status(db, organization)
    pursuits = status["pursuits"]
    if pursuits["notice"] == "none":
        return
    threshold = 100 if pursuits["notice"] == "limit_reached" else 80
    await stage_admin_alert(
        db, kind="PLAN_USAGE",
        dedupe_key=f"admin-alert:plan-usage:{organization_id}:{status['period_start']}:{threshold}",
        payload={
            "organization_id": str(organization_id), "organization_name": (organization.display_name or "")[:200],
            "plan": organization.plan, "threshold": threshold, "used": pursuits["used"], "limit": pursuits["limit"],
            "period_start": str(status["period_start"]), "period_end": str(status["period_end"] or ""),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )


async def require_feature(db: AsyncSession, organization: Organization | UUID | None, feature: str) -> Plan:
    """The organization's plan, once it includes ``feature`` (no organization: the Explore plan)."""
    if organization is not None and not isinstance(organization, Organization):
        organization = await db.get(Organization, organization)
    plan = plan_for(organization.plan if organization is not None else None)
    if not plan.has(feature):
        raise PlanFeatureError(feature, plan.code)
    return plan


async def check_introduction_allowed(db: AsyncSession, organization_id: UUID) -> None:
    await _lock(db, organization_id)
    organization = await db.get(Organization, organization_id)
    await require_feature(db, organization, "partner_search")
    introductions = (await plan_status(db, organization))["introductions"]
    if introductions["limit"] is not None and introductions["used"] >= introductions["limit"]:
        raise PlanIntroductionLimitError(
            f"All {introductions['limit']} introductions of this plan period are used. "
            "Upgrade, or ask Plasma to add introductions", organization.plan,
        )


async def check_seat_available(db: AsyncSession, organization_id: UUID) -> None:
    organization = await db.get(Organization, organization_id)
    limit = plan_for(organization.plan).user_limit
    if limit is not None and await seats_used(db, organization_id) >= limit:
        raise PlanUserLimitError(
            f"The {organization.plan} plan has {limit} users. Start a pilot for unlimited users", organization.plan,
        )


async def add_grant(
    db: AsyncSession, *, organization: Organization, kind: str, quantity: int, reason: str, actor_user,
    actor_label: str | None = None, source: str | None = None, today: date | None = None,
) -> OrganizationPlanGrant:
    """Extra pursuits or introductions for the current period; audited. The caller commits.

    ``actor_user`` None (B1: a purchased extra pursuit) records a SYSTEM actor with ``actor_label``."""
    from app.services.admin_activity import (
        ACTION_ORGANIZATION_PLAN_GRANTED, ACTOR_SYSTEM, ACTOR_USER, OUTCOME_SUCCESS, SOURCE_ADMIN_API,
        record_admin_audit_event,
    )
    from app.models.company import CompanyProfile
    from app.models.user import User

    if kind not in {GRANT_PURSUITS, GRANT_INTRODUCTIONS}:
        raise ValueError("kind must be PURSUITS or INTRODUCTIONS")
    reason = " ".join((reason or "").split())
    if len(reason) < 3:
        raise ValueError("a reason is required")
    period = plan_period(organization, today or datetime.now(timezone.utc).date())
    grant = OrganizationPlanGrant(
        organization_id=organization.id, kind=kind, quantity=quantity, period_start=period.start,
        reason=reason[:1000], granted_by_user_id=actor_user.id if actor_user is not None else None,
    )
    db.add(grant)
    await db.flush()
    profile = await db.get(CompanyProfile, organization.legacy_company_profile_id)
    target = await db.get(User, profile.user_id) if profile is not None else None
    await record_admin_audit_event(
        db, action=ACTION_ORGANIZATION_PLAN_GRANTED, outcome=OUTCOME_SUCCESS, source=source or SOURCE_ADMIN_API,
        actor_user=actor_user, actor_type=ACTOR_USER if actor_user is not None else ACTOR_SYSTEM,
        actor_label=None if actor_user is not None else (actor_label or "billing"), target_user=target,
        target_email=None if target is not None else "organization@plasma.invalid",
        target_resource_type="ORGANIZATION", target_resource_id=str(organization.id),
        new_state={"kind": kind, "quantity": quantity, "period_start": str(period.start), "plan": organization.plan},
        reason=reason[:500],
    )
    return grant
