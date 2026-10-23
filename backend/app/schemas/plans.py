"""P3: plan, usage and limits as the app and the admin page read them."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.billing import BillingSummary

Notice = Literal["none", "near_limit", "limit_reached"]


class PlanCounter(BaseModel):
    used: int
    limit: int | None = None
    extra_granted: int = 0
    override: int | None = None
    remaining: int | None = None
    notice: Notice = "none"


class PlanUsers(BaseModel):
    used: int
    limit: int | None = None


class PlanFeatures(BaseModel):
    tender_check: bool
    eoi: bool
    own_evidence: bool
    partner_search: bool
    competitor_intelligence: bool


class PlanStatusResponse(BaseModel):
    organization_id: UUID
    plan: str
    access_state: str
    period_kind: str
    period_start: date
    period_end: date | None = None
    plan_started_on: date | None = None
    plan_ends_on: date | None = None
    pursuits: PlanCounter
    introductions: PlanCounter
    users: PlanUsers
    features: PlanFeatures
    intelligence: str
    billing: BillingSummary | None = None  # B1: payment status, an open invoice, the annual offer


class PlanGrantCreate(BaseModel):
    kind: Literal["PURSUITS", "INTRODUCTIONS"]
    quantity: int = Field(ge=1, le=1000)
    reason: str = Field(min_length=3, max_length=1000)


class PlanGrantResponse(BaseModel):
    grant_id: UUID
    kind: str
    quantity: int
    period_start: date
    reason: str
    granted_by_email: str | None = None
    created_at: datetime


class PlanAuditEvent(BaseModel):
    event_id: UUID
    action: str
    actor_email: str | None = None
    previous_state: dict | None = None
    new_state: dict | None = None
    reason: str | None = None
    created_at: datetime


class OrganizationPlanDetail(BaseModel):
    status: PlanStatusResponse
    success_criteria: str | None = None
    grants: list[PlanGrantResponse] = Field(default_factory=list)
    audit_events: list[PlanAuditEvent] = Field(default_factory=list)
