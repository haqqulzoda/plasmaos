"""R3 Task 5: admin/operator panels. Reads are passive; ids, states, codes and timings only."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_operator
from app.db.session import get_db
from app.models.tenancy import Membership, Organization
from app.models.user import User
from app.services.admin_activity import (
    ACTION_ANALYSIS_RUN_RETRIED,
    OUTCOME_SUCCESS,
    SOURCE_ADMIN_API,
    record_admin_audit_event,
)
from app.schemas.plans import OrganizationPlanDetail, PlanGrantCreate
from app.services.admin_panels import (
    RUN_KINDS,
    AdminPanelError,
    analysis_run_panel,
    organization_panel,
    retry_analysis_run,
    source_panel,
)
from app.workers.pursuit_analysis_tasks import dispatch_run_ids


router = APIRouter(dependencies=[Depends(require_operator)])


class SourcePanelItem(BaseModel):
    source_system: str
    display_name: str
    status: str
    running: bool
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_success_partial: bool = False
    new_count: int | None = None
    updated_count: int | None = None
    failed_count: int | None = None
    terminal_reason: str | None = None
    scheduled_cadence_seconds: int | None = None
    next_scheduled_run_at: datetime | None = None
    stale: bool | None = None
    can_run_now: bool


class AnalysisRunPanelItem(BaseModel):
    analysis_run_id: UUID
    organization_id: UUID
    organization_name: str | None = None
    pursuit_id: UUID
    status: str
    stage: str
    failure_code: str | None = None
    model_name: str
    pipeline_version: str
    attempt_count: int
    max_attempts: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    latency_ms: int | None = None
    stuck: bool
    long: bool
    retry_allowed: bool


class AnalysisRetryResponse(BaseModel):
    retried_run_id: UUID
    analysis_run_id: UUID
    status: str


class OrganizationPanelItem(BaseModel):
    organization_id: UUID
    display_name: str | None = None
    approval_status: str | None = None
    pilot_status: str | None = None
    # P1: explore | pilot | paid | disabled and the recorded plan.
    access_state: str
    plan_started_on: date | None = None
    plan_ends_on: date | None = None
    success_criteria: str | None = None
    access_state_changed_at: datetime | None = None
    members_count: int
    pursuits_count: int
    last_activity_at: datetime | None = None
    created_at: datetime
    demo: bool
    # P3: the plan and this period's usage.
    plan: str = "explore"
    pursuit_limit_override: int | None = None
    introduction_limit_override: int | None = None
    period_start: date | None = None
    period_end: date | None = None
    pursuits_used: int = 0
    pursuit_limit: int | None = None
    pursuit_notice: str = "none"
    introductions_used: int = 0
    introduction_limit: int | None = None
    users_used: int = 0
    user_limit: int | None = None


class OrganizationAccessUpdate(BaseModel):
    """Every field is required: the form always sends the whole plan (null clears a field).

    P3: ``plan`` sets the access state (explore, pilot, or paid for the paid plans) unless
    ``access_state`` is disabled; the overrides persist across plan periods."""

    access_state: Literal["explore", "pilot", "paid", "disabled"]
    plan: Literal["explore", "pilot", "pursuit_desk", "agent", "enterprise", "per_tender"] | None = None
    pursuit_limit_override: int | None = Field(default=None, ge=0, le=100000)
    introduction_limit_override: int | None = Field(default=None, ge=0, le=100000)
    plan_started_on: date | None = None
    plan_ends_on: date | None = None
    success_criteria: str | None = Field(default=None, max_length=4000)
    reason: str | None = Field(default=None, max_length=500)


@router.get("/sources", response_model=list[SourcePanelItem])
async def sources_panel(db: AsyncSession = Depends(get_db)) -> list[SourcePanelItem]:
    """Run now uses the existing operator path: POST /tenders/sources/{source}/refresh?force=true."""
    return [SourcePanelItem(**row) for row in await source_panel(db)]


@router.get("/analysis-runs", response_model=list[AnalysisRunPanelItem])
async def analysis_runs_panel(
    kind: list[str] = Query(default=list(RUN_KINDS)),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[AnalysisRunPanelItem]:
    kinds = tuple(value for value in kind if value in RUN_KINDS)
    if not kinds:
        raise HTTPException(422, detail="kind must be failed, stuck or long")
    return [AnalysisRunPanelItem(**row) for row in await analysis_run_panel(db, kinds=kinds, limit=limit)]


@router.post("/analysis-runs/{run_id}/retry", response_model=AnalysisRetryResponse, status_code=status.HTTP_201_CREATED)
async def retry_analysis_run_endpoint(
    run_id: UUID,
    current_user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> AnalysisRetryResponse:
    try:
        created = await retry_analysis_run(db, run_id=run_id)
    except AdminPanelError as exc:
        code = status.HTTP_404_NOT_FOUND if exc.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
        raise HTTPException(code, detail={"code": exc.code, "message": str(exc)}) from exc
    requester = await db.scalar(
        select(User).join(Membership, Membership.user_id == User.id).where(Membership.id == created.requested_by_membership_id)
    )
    await record_admin_audit_event(
        db, action=ACTION_ANALYSIS_RUN_RETRIED, outcome=OUTCOME_SUCCESS, source=SOURCE_ADMIN_API,
        actor_user=current_user, target_user=requester, target_resource_type="ANALYSIS_RUN",
        target_resource_id=str(run_id),
        metadata={
            "organization_id": str(created.organization_id), "pursuit_id": str(created.pursuit_id),
            "new_analysis_run_id": str(created.id),
        },
    )
    await db.commit()
    dispatch_run_ids([created.id])
    return AnalysisRetryResponse(retried_run_id=run_id, analysis_run_id=created.id, status=created.status)


@router.get("/organizations", response_model=list[OrganizationPanelItem])
async def organizations_panel(db: AsyncSession = Depends(get_db)) -> list[OrganizationPanelItem]:
    return [OrganizationPanelItem(**row) for row in await organization_panel(db)]


@router.put("/organizations/{organization_id}/access", response_model=OrganizationPanelItem)
async def update_organization_access(
    organization_id: UUID,
    payload: OrganizationAccessUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> OrganizationPanelItem:
    """P1: set explore / pilot / paid / disabled and the plan (admins only; audited)."""
    from app.services.organization_access import OrganizationAccessError, set_organization_access

    organization = await db.get(Organization, organization_id, with_for_update=True)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organization not found")
    try:
        await set_organization_access(
            db, organization=organization, state=payload.access_state, actor_user=current_user,
            actor_label="admin/panels/organizations", reason=(payload.reason or "").strip() or None,
            plan_started_on=payload.plan_started_on, plan_ends_on=payload.plan_ends_on,
            success_criteria=payload.success_criteria, plan=payload.plan,
            pursuit_limit_override=payload.pursuit_limit_override,
            introduction_limit_override=payload.introduction_limit_override,
        )
    except OrganizationAccessError as exc:
        await db.rollback()
        raise HTTPException(422, detail=str(exc)) from exc
    await db.commit()
    row = next(item for item in await organization_panel(db) if item["organization_id"] == organization_id)
    return OrganizationPanelItem(**row)


@router.get("/organizations/{organization_id}/plan", response_model=OrganizationPlanDetail)
async def organization_plan_detail(organization_id: UUID, db: AsyncSession = Depends(get_db)) -> OrganizationPlanDetail:
    """P3: plan, usage, grants and the plan's audit trail for one organization."""
    from app.services.admin_panels import organization_plan_detail as detail

    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return OrganizationPlanDetail(**await detail(db, organization))


@router.post("/organizations/{organization_id}/plan-grants", response_model=OrganizationPlanDetail,
             status_code=status.HTTP_201_CREATED)
async def grant_organization_allowance(
    organization_id: UUID, payload: PlanGrantCreate,
    current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> OrganizationPlanDetail:
    """P3: extra pursuits or introductions for the current plan period (admins only; audited)."""
    from app.services.admin_panels import organization_plan_detail as detail
    from app.services.plans import add_grant

    organization = await db.get(Organization, organization_id, with_for_update=True)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organization not found")
    try:
        await add_grant(db, organization=organization, kind=payload.kind, quantity=payload.quantity,
                        reason=payload.reason, actor_user=current_user)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(422, detail=str(exc)) from exc
    await db.commit()
    return OrganizationPlanDetail(**await detail(db, organization))
