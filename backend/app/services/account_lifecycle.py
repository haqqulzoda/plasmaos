"""Strict administrative user-account lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from app.core.access import (
    USER_APPROVAL_APPROVED,
    USER_APPROVAL_DISABLED,
    USER_APPROVAL_PENDING,
    USER_APPROVAL_REJECTED,
    USER_APPROVAL_STATUSES,
    USER_RESTORABLE_APPROVAL_STATUSES,
    normalized_approval_status,
)
from app.models.all_models import User
from app.services.admin_activity import bump_auth_version

LifecycleAction = Literal["approve", "reject", "disable", "restore"]

ALLOWED_USER_LIFECYCLE_TRANSITIONS: dict[str, dict[str, str]] = {
    "approve": {
        USER_APPROVAL_PENDING: USER_APPROVAL_APPROVED,
        USER_APPROVAL_REJECTED: USER_APPROVAL_APPROVED,
    },
    "reject": {
        USER_APPROVAL_PENDING: USER_APPROVAL_REJECTED,
        USER_APPROVAL_APPROVED: USER_APPROVAL_REJECTED,
    },
    "disable": {
        USER_APPROVAL_PENDING: USER_APPROVAL_DISABLED,
        USER_APPROVAL_APPROVED: USER_APPROVAL_DISABLED,
        USER_APPROVAL_REJECTED: USER_APPROVAL_DISABLED,
    },
}


class InvalidAccountLifecycleTransition(ValueError):
    """Raised when an admin command is invalid for the current account state."""

    def __init__(self, *, action: str, current_state: str) -> None:
        self.action = action
        self.current_state = current_state
        super().__init__(f"Cannot {action} account from '{current_state}' state")


@dataclass(frozen=True)
class AccountLifecycleTransition:
    """Transition context suitable for the existing or future audit recorder."""

    actor_user_id: UUID | None
    target_user_id: UUID
    action: LifecycleAction
    previous_state: str
    new_state: str
    occurred_at: datetime


def _current_state(user: User) -> str:
    current_state = normalized_approval_status(user.approval_status)
    if current_state not in USER_APPROVAL_STATUSES:
        raise InvalidAccountLifecycleTransition(
            action="change",
            current_state=current_state or "unknown",
        )
    return current_state


def transition_user_account(
    user: User,
    *,
    action: LifecycleAction,
    actor_user: User | None,
    reason: str | None = None,
    occurred_at: datetime | None = None,
) -> AccountLifecycleTransition:
    """Apply one strict lifecycle command and monotonically revoke credentials."""
    now = occurred_at or datetime.now(timezone.utc)
    previous_state = _current_state(user)

    if action == "restore":
        if previous_state != USER_APPROVAL_DISABLED:
            raise InvalidAccountLifecycleTransition(
                action=action,
                current_state=previous_state,
            )
        preserved_state = normalized_approval_status(
            getattr(user, "pre_disabled_approval_status", None)
        )
        # Existing disabled accounts have no trustworthy provenance. Restoring
        # them to pending is deterministic and cannot elevate access.
        new_state = (
            preserved_state
            if preserved_state in USER_RESTORABLE_APPROVAL_STATUSES
            else USER_APPROVAL_PENDING
        )
    else:
        transition = ALLOWED_USER_LIFECYCLE_TRANSITIONS[action]
        new_state = transition.get(previous_state, "")
        if not new_state:
            raise InvalidAccountLifecycleTransition(
                action=action,
                current_state=previous_state,
            )

    user.approval_status = new_state
    if action == "approve":
        user.approved_at = now
        user.approved_by_user_id = actor_user.id if actor_user is not None else None
        user.rejected_at = None
        user.rejection_reason = None
    elif action == "reject":
        user.rejected_at = now
        user.rejection_reason = reason
    elif action == "disable":
        user.pre_disabled_approval_status = previous_state
        user.disabled_at = now
    else:
        user.disabled_at = None
        user.pre_disabled_approval_status = None
        if new_state != USER_APPROVAL_REJECTED:
            user.rejected_at = None
            user.rejection_reason = None

    # PlasmaOS uses auth_version as its one credential-revocation mechanism.
    # Bumping every explicit admin transition makes repeated/stale credentials
    # fail closed, and restore can never roll the version back.
    bump_auth_version(user)

    return AccountLifecycleTransition(
        actor_user_id=actor_user.id if actor_user is not None else None,
        target_user_id=user.id,
        action=action,
        previous_state=previous_state,
        new_state=new_state,
        occurred_at=now,
    )
