"""Database-serialized safety for privileged account lifecycle mutations."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import (
    PLATFORM_ROLE_ADMIN,
    USER_APPROVAL_APPROVED,
    is_effective_admin,
)
from app.models.all_models import User
from app.services.account_lifecycle import (
    AccountLifecycleTransition,
    LifecycleAction,
    transition_user_account,
)
from app.services.admin_activity import user_role_snapshot
from app.services.admin_activity import (
    REASON_LAST_EFFECTIVE_ADMIN,
    REASON_SELF_ACTION_PROHIBITED,
    REASON_STALE_ACTOR_AUTHORITY,
)

# Stable, dedicated two-int32 PostgreSQL advisory-lock namespace. Transaction
# scope releases it on commit/rollback and works across every API instance.
ADMIN_SURVIVABILITY_LOCK_NAMESPACE = 0x504C4153  # "PLAS"
ADMIN_SURVIVABILITY_LOCK_KEY = 0x5333  # "S3"


class AdminSurvivabilityViolation(ValueError):
    """Raised when a lifecycle command would violate admin safety policy."""

    def __init__(
        self,
        reason: str,
        *,
        reason_code: str = REASON_LAST_EFFECTIVE_ADMIN,
    ) -> None:
        self.reason = reason
        self.reason_code = reason_code
        super().__init__(reason)


class AdminActorAuthorityLost(PermissionError):
    """Raised when the actor is no longer an effective admin under the lock."""

    reason_code = REASON_STALE_ACTOR_AUTHORITY


@dataclass(frozen=True)
class LockedLifecycleMutation:
    actor: User
    target: User
    before: dict[str, object]
    transition: AccountLifecycleTransition


def effective_admin_sql_condition():
    """Return the SQL equivalent of ``is_effective_admin``."""
    return (
        (User.approval_status == USER_APPROVAL_APPROVED)
        & or_(User.is_admin.is_(True), User.platform_role == PLATFORM_ROLE_ADMIN)
    )


async def acquire_admin_survivability_lock(db: AsyncSession) -> None:
    """Serialize admin-survivability-sensitive changes until transaction end."""
    await db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            ":admin_survivability_namespace, :admin_survivability_key)"
        ),
        {
            "admin_survivability_namespace": ADMIN_SURVIVABILITY_LOCK_NAMESPACE,
            "admin_survivability_key": ADMIN_SURVIVABILITY_LOCK_KEY,
        },
    )


async def _load_actor_and_target_under_lock(
    db: AsyncSession,
    *,
    actor_user_id: UUID,
    target_user_id: UUID,
) -> tuple[User | None, User | None]:
    result = await db.execute(
        select(User)
        .where(User.id.in_({actor_user_id, target_user_id}))
        .order_by(User.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    users = {user.id: user for user in result.scalars().all()}
    return users.get(actor_user_id), users.get(target_user_id)


async def count_effective_admins(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).select_from(User).where(effective_admin_sql_condition())
    )
    return int(result.scalar_one() or 0)


async def apply_locked_user_lifecycle_mutation(
    db: AsyncSession,
    *,
    actor_user_id: UUID,
    target_user_id: UUID,
    action: LifecycleAction,
    reason: str | None = None,
) -> LockedLifecycleMutation:
    """Revalidate actor/target and apply one lifecycle mutation under DB lock."""
    await acquire_admin_survivability_lock(db)
    actor, target = await _load_actor_and_target_under_lock(
        db,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
    )
    if actor is None or not is_effective_admin(actor):
        raise AdminActorAuthorityLost("Admin authority is no longer current")
    if target is None:
        raise LookupError("User not found")

    removes_lifecycle_access = action in {"disable", "reject"}
    if removes_lifecycle_access and actor.id == target.id:
        raise AdminSurvivabilityViolation(
            f"Effective administrators cannot {action} their own account",
            reason_code=REASON_SELF_ACTION_PROHIBITED,
        )

    if removes_lifecycle_access and is_effective_admin(target):
        if await count_effective_admins(db) <= 1:
            raise AdminSurvivabilityViolation(
                "At least one effective administrator must remain",
                reason_code=REASON_LAST_EFFECTIVE_ADMIN,
            )

    before = user_role_snapshot(target)
    transition = transition_user_account(
        target,
        action=action,
        actor_user=actor,
        reason=reason,
    )
    return LockedLifecycleMutation(
        actor=actor,
        target=target,
        before=before,
        transition=transition,
    )
