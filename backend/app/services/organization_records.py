"""R3 Task 6: the company profile and readiness records belong to the organization.

Any ACTIVE member may edit them (the same rule as the Partners & Experts library);
approval and pilot status stay admin-only because no member schema carries them. Every
change is recorded with the actor and the changed field names (never their values).
"""

from __future__ import annotations

from typing import Any, Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization_records import OrganizationRecordEvent
from app.services.organization_context import ProfileContext

# Never writable through a member endpoint.
ADMIN_ONLY_PROFILE_FIELDS = frozenset({"approval_status", "pilot_status", "approved_at", "approved_by_user_id",
                                       "rejected_at", "rejection_reason", "disabled_at", "user_id"})


def changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(key for key in after if before.get(key) != after.get(key))


def snapshot(row: Any, fields: Iterable[str]) -> dict[str, Any]:
    return {field: getattr(row, field, None) for field in fields}


async def record_organization_change(
    db: AsyncSession,
    *,
    organization_id: UUID,
    company_profile_id: UUID,
    actor_user_id: UUID,
    actor_membership_id: UUID | None,
    record_type: str,
    action: str,
    fields: list[str],
    record_id: UUID | None = None,
) -> OrganizationRecordEvent | None:
    """Append one event in the caller's transaction; an UPDATE that changed nothing is not recorded."""
    if action == "UPDATE" and not fields:
        return None
    event = OrganizationRecordEvent(
        organization_id=organization_id, company_profile_id=company_profile_id,
        actor_user_id=actor_user_id, actor_membership_id=actor_membership_id,
        record_type=record_type, record_id=record_id, action=action, changed_fields=sorted(set(fields)),
    )
    db.add(event)
    await db.flush()
    return event


async def record_for_context(
    db: AsyncSession, context: ProfileContext | None, *, actor_user_id: UUID, record_type: str, action: str,
    fields: list[str], record_id: UUID | None = None,
) -> OrganizationRecordEvent | None:
    if context is None:  # a legacy account whose profile was never mapped to an organization
        return None
    return await record_organization_change(
        db, organization_id=context.organization.id, company_profile_id=context.profile.id,
        actor_user_id=actor_user_id, actor_membership_id=context.membership.id,
        record_type=record_type, action=action, fields=fields, record_id=record_id,
    )
