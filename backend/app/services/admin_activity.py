"""Canonical append-only administrative security audit helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import is_effective_admin
from app.models.all_models import AdminActivityEvent, User

AdminAuditOutcome = Literal["SUCCESS", "DENIED", "FAILED"]
AdminAuditActorType = Literal["USER", "SYSTEM", "SERVER_COMMAND"]

OUTCOME_SUCCESS: Final = "SUCCESS"
OUTCOME_DENIED: Final = "DENIED"
OUTCOME_FAILED: Final = "FAILED"
ACTOR_USER: Final = "USER"
ACTOR_SYSTEM: Final = "SYSTEM"
ACTOR_SERVER_COMMAND: Final = "SERVER_COMMAND"
SOURCE_ADMIN_API: Final = "ADMIN_API"
SOURCE_GOOGLE_ALLOWLIST: Final = "GOOGLE_ALLOWLIST"
SOURCE_ADMIN_REPAIR_COMMAND: Final = "ADMIN_REPAIR_COMMAND"

ACTION_USER_APPROVED: Final = "USER_APPROVED"
ACTION_USER_REJECTED: Final = "USER_REJECTED"
ACTION_USER_DISABLED: Final = "USER_DISABLED"
ACTION_USER_RESTORED: Final = "USER_RESTORED"
ACTION_COMPANY_APPROVED: Final = "COMPANY_APPROVED"
ACTION_COMPANY_REJECTED: Final = "COMPANY_REJECTED"
ACTION_COMPANY_DISABLED: Final = "COMPANY_DISABLED"
ACTION_ADMIN_GRANTED: Final = "ADMIN_GRANTED"
ACTION_OPERATOR_GRANTED: Final = "OPERATOR_GRANTED"
ACTION_ALLOWLIST_PRIVILEGE_RECONCILED: Final = "ALLOWLIST_PRIVILEGE_RECONCILED"
ACTION_ADMIN_REPAIR_PROMOTION: Final = "ADMIN_REPAIR_PROMOTION"

REASON_SELF_ACTION_PROHIBITED: Final = "SELF_ACTION_PROHIBITED"
REASON_LAST_EFFECTIVE_ADMIN: Final = "LAST_EFFECTIVE_ADMIN"
REASON_INVALID_LIFECYCLE_TRANSITION: Final = "INVALID_LIFECYCLE_TRANSITION"
REASON_STALE_ACTOR_AUTHORITY: Final = "STALE_ACTOR_AUTHORITY"
REASON_TRANSACTION_FAILED: Final = "TRANSACTION_FAILED"

ALLOWED_OUTCOMES: Final = frozenset(
    {OUTCOME_SUCCESS, OUTCOME_DENIED, OUTCOME_FAILED}
)
ALLOWED_ACTOR_TYPES: Final = frozenset(
    {ACTOR_USER, ACTOR_SYSTEM, ACTOR_SERVER_COMMAND}
)
ALLOWED_ACTIONS: Final = frozenset(
    {
        ACTION_USER_APPROVED,
        ACTION_USER_REJECTED,
        ACTION_USER_DISABLED,
        ACTION_USER_RESTORED,
        ACTION_COMPANY_APPROVED,
        ACTION_COMPANY_REJECTED,
        ACTION_COMPANY_DISABLED,
        ACTION_ADMIN_GRANTED,
        ACTION_OPERATOR_GRANTED,
        ACTION_ALLOWLIST_PRIVILEGE_RECONCILED,
        ACTION_ADMIN_REPAIR_PROMOTION,
    }
)
_FORBIDDEN_KEY_PARTS: Final = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "credential",
    "cookie",
    "session",
    "signed_url",
    "database_url",
    "redis_url",
)
_SAFE_SECURITY_SEMANTIC_KEYS: Final = frozenset({"credentials_invalidated"})


def _normalized_email(user: User | None) -> str | None:
    if user is None:
        return None
    return (user.email or "").strip().lower() or None


def user_role_snapshot(
    user: User,
    *,
    credentials_invalidated: bool = False,
) -> dict[str, Any]:
    """Return the stable, non-secret administrative state allowlist."""
    snapshot = {
        "platform_role": user.platform_role,
        "approval_status": user.approval_status,
        "pre_disabled_approval_status": getattr(
            user,
            "pre_disabled_approval_status",
            None,
        ),
        "is_admin": bool(user.is_admin),
        "effective_admin": bool(is_effective_admin(user)),
    }
    if credentials_invalidated:
        snapshot["credentials_invalidated"] = True
    return snapshot


def company_role_snapshot(
    *,
    company_approval_status: str,
    user: User,
    credentials_invalidated: bool = False,
) -> dict[str, Any]:
    return {
        "company_approval_status": company_approval_status,
        "user": user_role_snapshot(
            user,
            credentials_invalidated=credentials_invalidated,
        ),
    }


def bump_auth_version(user: User) -> None:
    user.auth_version = int(getattr(user, "auth_version", 0) or 0) + 1


def _validate_safe_payload(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).strip().casefold()
            if (
                key not in _SAFE_SECURITY_SEMANTIC_KEYS
                and any(part in key for part in _FORBIDDEN_KEY_PARTS)
            ):
                raise ValueError(f"sensitive administrative audit key rejected at {path}")
            _validate_safe_payload(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _validate_safe_payload(item, path=f"{path}[{index}]")
        return
    raise ValueError(f"unsupported administrative audit value at {path}")


async def record_admin_audit_event(
    db: AsyncSession,
    *,
    action: str,
    outcome: AdminAuditOutcome,
    source: str,
    target_user: User | None,
    actor_user: User | None = None,
    actor_type: AdminAuditActorType = ACTOR_USER,
    actor_label: str | None = None,
    target_email: str | None = None,
    target_resource_type: str = "USER",
    target_resource_id: str | None = None,
    previous_state: dict[str, Any] | None = None,
    new_state: dict[str, Any] | None = None,
    reason_code: str | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AdminActivityEvent:
    """Append and flush one canonical event in the caller's transaction."""
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"unsupported administrative audit action: {action}")
    if outcome not in ALLOWED_OUTCOMES:
        raise ValueError(f"unsupported administrative audit outcome: {outcome}")
    if actor_type not in ALLOWED_ACTOR_TYPES:
        raise ValueError(f"unsupported administrative audit actor type: {actor_type}")
    if actor_type == ACTOR_USER and actor_user is None:
        raise ValueError("USER administrative audit actors require actor_user")
    if actor_type != ACTOR_USER and actor_user is not None:
        raise ValueError("non-USER administrative audit actors cannot impersonate a user")

    resolved_target_email = _normalized_email(target_user) or (
        (target_email or "").strip().lower() or None
    )
    if resolved_target_email is None:
        raise ValueError("administrative audit target email is required")
    for name, value in (
        ("previous_state", previous_state),
        ("new_state", new_state),
        ("metadata", metadata),
    ):
        _validate_safe_payload(value, path=name)

    event = AdminActivityEvent(
        action=action,
        outcome=outcome,
        source=source.strip().upper(),
        actor_user_id=actor_user.id if actor_user is not None else None,
        actor_label=actor_label,
        actor_type=actor_type,
        actor_email_snapshot=_normalized_email(actor_user),
        actor_role_snapshot=actor_user.platform_role if actor_user is not None else None,
        target_user_id=target_user.id if target_user is not None else None,
        target_email=resolved_target_email,
        target_resource_type=target_resource_type,
        target_resource_id=(
            target_resource_id
            or (str(target_user.id) if target_user is not None else None)
        ),
        previous_state=previous_state,
        new_state=new_state,
        reason_code=reason_code,
        reason=reason,
        request_id=request_id,
        metadata_json=metadata,
    )
    db.add(event)
    await db.flush()
    return event


async def record_independent_user_audit_event(
    *,
    actor_user_id: UUID,
    target_user_id: UUID,
    action: str,
    outcome: AdminAuditOutcome,
    source: str,
    reason_code: str,
    reason: str,
    previous_state: dict[str, Any] | None = None,
    new_state: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AdminActivityEvent:
    """Persist a denial/failure after the mutation transaction was rolled back."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as audit_db:
        result = await audit_db.execute(
            select(User).where(User.id.in_({actor_user_id, target_user_id}))
        )
        users = {user.id: user for user in result.scalars().all()}
        target = users.get(target_user_id)
        actor = users.get(actor_user_id)
        if target is None or actor is None:
            raise LookupError("administrative audit principal no longer exists")
        event = await record_admin_audit_event(
            audit_db,
            action=action,
            outcome=outcome,
            source=source,
            actor_user=actor,
            target_user=target,
            previous_state=previous_state or user_role_snapshot(target),
            new_state=new_state,
            reason_code=reason_code,
            reason=reason,
            request_id=request_id,
        )
        await audit_db.commit()
        return event
