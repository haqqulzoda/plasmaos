"""Helpers for auditable account-management changes."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import AdminActivityEvent, User


def user_role_snapshot(user: User) -> dict[str, Any]:
    return {
        "platform_role": user.platform_role,
        "approval_status": user.approval_status,
        "is_admin": bool(user.is_admin),
        "approved_at": user.approved_at.isoformat() if user.approved_at else None,
        "auth_version": int(getattr(user, "auth_version", 0) or 0),
    }


def bump_auth_version(user: User) -> None:
    user.auth_version = int(getattr(user, "auth_version", 0) or 0) + 1


async def record_admin_activity(
    db: AsyncSession,
    *,
    action: str,
    target_user: User,
    actor_user: User | None = None,
    actor_label: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AdminActivityEvent:
    event = AdminActivityEvent(
        action=action,
        actor_user_id=actor_user.id if actor_user is not None else None,
        actor_label=actor_label,
        target_user_id=target_user.id,
        target_email=(target_user.email or "").strip().lower(),
        reason=reason,
        metadata_json=metadata,
    )
    db.add(event)
    await db.flush()
    return event
