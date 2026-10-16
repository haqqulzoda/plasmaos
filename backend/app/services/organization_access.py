"""P1: organization access state (explore | pilot | paid | disabled) and the recorded plan.

The legacy company approval remains the enforced gate everywhere (require_approved_pilot_access,
the organization context, invitations); this module is the one writer that keeps the two in
step: pilot/paid = approved, explore = pending, disabled = disabled. Admin company approve,
reject and disable call ``sync_access_from_company`` so that path stays consistent too.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import (
    COMPANY_APPROVAL_APPROVED,
    COMPANY_APPROVAL_DISABLED,
    COMPANY_APPROVAL_PENDING,
    COMPANY_APPROVAL_REJECTED,
    COMPANY_PILOT_ACTIVE,
    COMPANY_PILOT_CONVERTED,
    COMPANY_PILOT_PAUSED,
    COMPANY_PILOT_SCOPED,
    ORG_ACCESS_DISABLED,
    ORG_ACCESS_EXPLORE,
    ORG_ACCESS_PAID,
    ORG_ACCESS_PILOT,
    ORG_ACCESS_STATES,
    ORG_FULL_ACCESS_STATES,
)
from app.models.company import CompanyProfile
from app.models.tenancy import Organization
from app.models.user import User
from app.services.admin_activity import (
    ACTION_ORGANIZATION_ACCESS_CHANGED,
    ACTOR_SERVER_COMMAND,
    ACTOR_USER,
    OUTCOME_SUCCESS,
    SOURCE_ADMIN_API,
    record_admin_audit_event,
)

MAX_SUCCESS_CRITERIA = 4000
_UNSET = object()

COMPANY_STATUS_FOR_STATE = {
    ORG_ACCESS_EXPLORE: COMPANY_APPROVAL_PENDING,
    ORG_ACCESS_PILOT: COMPANY_APPROVAL_APPROVED,
    ORG_ACCESS_PAID: COMPANY_APPROVAL_APPROVED,
    ORG_ACCESS_DISABLED: COMPANY_APPROVAL_DISABLED,
}
# The CRM-style pilot status follows the plan where the plan says something definite.
PILOT_STATUS_FOR_STATE = {
    ORG_ACCESS_EXPLORE: COMPANY_PILOT_SCOPED,
    ORG_ACCESS_PILOT: COMPANY_PILOT_ACTIVE,
    ORG_ACCESS_PAID: COMPANY_PILOT_CONVERTED,
    ORG_ACCESS_DISABLED: COMPANY_PILOT_PAUSED,
}


class OrganizationAccessError(ValueError):
    pass


def state_for_company_status(company_status: str | None, current: str | None = None) -> str:
    """The access state a company approval implies, keeping pilot vs paid when still approved."""
    if company_status == COMPANY_APPROVAL_APPROVED:
        return current if current in ORG_FULL_ACCESS_STATES else ORG_ACCESS_PILOT
    if company_status in {COMPANY_APPROVAL_REJECTED, COMPANY_APPROVAL_DISABLED}:
        return ORG_ACCESS_DISABLED
    return ORG_ACCESS_EXPLORE


def has_full_access(state: str | None) -> bool:
    return state in ORG_FULL_ACCESS_STATES


@dataclass(frozen=True)
class AccessSnapshot:
    access_state: str
    plan_started_on: date | None
    plan_ends_on: date | None
    success_criteria: str | None

    def as_audit(self) -> dict:
        return {
            "access_state": self.access_state,
            "plan_started_on": self.plan_started_on.isoformat() if self.plan_started_on else None,
            "plan_ends_on": self.plan_ends_on.isoformat() if self.plan_ends_on else None,
            "success_criteria_set": bool(self.success_criteria),
        }


def snapshot(organization: Organization) -> AccessSnapshot:
    return AccessSnapshot(
        organization.access_state, organization.plan_started_on, organization.plan_ends_on, organization.success_criteria,
    )


async def set_organization_access(
    db: AsyncSession,
    *,
    organization: Organization,
    state: str,
    actor_user: User | None,
    actor_label: str,
    reason: str | None = None,
    plan_started_on: date | None | object = _UNSET,
    plan_ends_on: date | None | object = _UNSET,
    success_criteria: str | None | object = _UNSET,
    now: datetime | None = None,
) -> Organization:
    """Change the state and/or plan, sync the company approval, audit. The caller commits."""
    if state not in ORG_ACCESS_STATES:
        raise OrganizationAccessError(f"access_state must be one of {', '.join(ORG_ACCESS_STATES)}")
    moment = now or datetime.now(timezone.utc)
    before = snapshot(organization)
    if plan_started_on is not _UNSET:
        organization.plan_started_on = plan_started_on  # type: ignore[assignment]
    if plan_ends_on is not _UNSET:
        organization.plan_ends_on = plan_ends_on  # type: ignore[assignment]
    if success_criteria is not _UNSET:
        text = (success_criteria or "").strip() if isinstance(success_criteria, str) or success_criteria is None else None
        if text is not None and len(text) > MAX_SUCCESS_CRITERIA:
            raise OrganizationAccessError(f"success criteria are limited to {MAX_SUCCESS_CRITERIA} characters")
        organization.success_criteria = text or None
    if organization.plan_started_on and organization.plan_ends_on and organization.plan_ends_on < organization.plan_started_on:
        raise OrganizationAccessError("the plan cannot end before it starts")
    if state != organization.access_state:
        organization.access_state = state
        organization.access_state_changed_at = moment
        organization.access_state_changed_by_user_id = actor_user.id if actor_user is not None else None

    profile = await db.get(CompanyProfile, organization.legacy_company_profile_id)
    if profile is not None:
        wanted = COMPANY_STATUS_FOR_STATE[state]
        if profile.approval_status != wanted:
            profile.approval_status = wanted
            if wanted == COMPANY_APPROVAL_APPROVED:
                profile.approved_at = moment
                profile.approved_by_user_id = actor_user.id if actor_user is not None else None
                profile.rejected_at = None
                profile.rejection_reason = None
            elif wanted == COMPANY_APPROVAL_DISABLED and reason:
                profile.rejection_reason = reason[:500]
        profile.pilot_status = PILOT_STATUS_FOR_STATE[state]
    await db.flush()

    after = snapshot(organization)
    if after != before:
        target_user = await db.get(User, profile.user_id) if profile is not None else None
        await record_admin_audit_event(
            db, action=ACTION_ORGANIZATION_ACCESS_CHANGED, outcome=OUTCOME_SUCCESS, source=SOURCE_ADMIN_API,
            actor_user=actor_user, actor_type=ACTOR_USER if actor_user is not None else ACTOR_SERVER_COMMAND,
            actor_label=None if actor_user is not None else actor_label,
            target_user=target_user, target_email=None if target_user is not None else "organization@plasma.invalid",
            target_resource_type="ORGANIZATION", target_resource_id=str(organization.id),
            previous_state=before.as_audit(), new_state=after.as_audit(),
            reason=reason or f"Organization access set to {state}.",
            metadata={"company_approval_status": profile.approval_status if profile is not None else None},
        )
    return organization


async def sync_access_from_company(db: AsyncSession, *, profile: CompanyProfile, actor_user: User | None) -> None:
    """After a legacy company approve/reject/disable: move the organization's state to match."""
    organization = await db.scalar(select(Organization).where(Organization.legacy_company_profile_id == profile.id))
    if organization is None:
        return
    wanted = state_for_company_status(profile.approval_status, organization.access_state)
    if wanted != organization.access_state:
        organization.access_state = wanted
        organization.access_state_changed_at = datetime.now(timezone.utc)
        organization.access_state_changed_by_user_id = actor_user.id if actor_user is not None else None
        await db.flush()


async def organization_access_for(db: AsyncSession, organization_id: UUID) -> str | None:
    return await db.scalar(select(Organization.access_state).where(Organization.id == organization_id))
