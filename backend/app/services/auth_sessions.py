"""P1: about 30-day sessions through rotating refresh tokens.

A sign-in (Google or e-mail code) starts a family and returns an opaque 256-bit refresh
token; only its SHA-256 is stored. ``rotate`` exchanges a live token for a fresh access token
and a new refresh token, and marks the old one rotated. Presenting a rotated token again
revokes the whole family (theft detection), except within ``REUSE_GRACE`` of its rotation:
two tabs refreshing at once get a sibling instead of a lock-out.

The idle lifetime is 30 days and slides with each rotation; a family never outlives 90 days
from its sign-in. Every family dies with the account's ``auth_version`` (approval, disable,
role and membership changes still force a fresh sign-in), and logout revokes the family.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import is_disabled_account, is_rejected_account
from app.models.auth_sessions import AuthRefreshToken
from app.models.user import User
from app.services.admin_activity import (
    ACTION_REFRESH_REUSE_DETECTED,
    ACTOR_SYSTEM,
    OUTCOME_DENIED,
    SOURCE_SESSION_ROTATION,
    record_admin_audit_event,
)

REFRESH_IDLE_TTL = timedelta(days=30)
FAMILY_MAX_AGE = timedelta(days=90)
REUSE_GRACE = timedelta(seconds=60)
METHOD_GOOGLE = "GOOGLE"
METHOD_EMAIL_CODE = "EMAIL_CODE"


class RefreshTokenError(RuntimeError):
    """The refresh token cannot be used; the client must sign in again."""


@dataclass(frozen=True)
class IssuedRefreshToken:
    token: str
    family_id: UUID
    expires_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def _new_row(*, user: User, family_id: UUID, method: str, started: datetime, now: datetime) -> tuple[AuthRefreshToken, str]:
    token = secrets.token_urlsafe(32)
    expires_at = min(now + REFRESH_IDLE_TTL, started + FAMILY_MAX_AGE)
    row = AuthRefreshToken(
        id=uuid4(), family_id=family_id, user_id=user.id, token_hash=hash_refresh_token(token),
        auth_version=int(user.auth_version or 0), sign_in_method=method, family_started_at=started,
        created_at=now, expires_at=expires_at,
    )
    return row, token


async def start_family(db: AsyncSession, *, user: User, method: str, now: datetime | None = None) -> IssuedRefreshToken:
    """A new family at sign-in. The caller commits."""
    moment = now or _now()
    row, token = _new_row(user=user, family_id=uuid4(), method=method, started=moment, now=moment)
    db.add(row)
    await db.flush()
    return IssuedRefreshToken(token=token, family_id=row.family_id, expires_at=row.expires_at)


async def revoke_family(db: AsyncSession, *, family_id: UUID, reason: str, now: datetime | None = None) -> int:
    result = await db.execute(
        update(AuthRefreshToken)
        .where(AuthRefreshToken.family_id == family_id, AuthRefreshToken.revoked_at.is_(None))
        .values(revoked_at=now or _now(), revoke_reason=reason)
    )
    return int(result.rowcount or 0)


async def rotate(db: AsyncSession, *, token: str, now: datetime | None = None) -> tuple[User, IssuedRefreshToken]:
    """Exchange a refresh token. Raises RefreshTokenError; the caller commits either way."""
    moment = now or _now()
    row = await db.scalar(
        select(AuthRefreshToken).where(AuthRefreshToken.token_hash == hash_refresh_token(token)).with_for_update()
    )
    if row is None:
        raise RefreshTokenError("unknown refresh token")
    if row.revoked_at is not None:
        raise RefreshTokenError("revoked refresh token")
    user = await db.get(User, row.user_id)
    if user is None:
        raise RefreshTokenError("unknown user")
    if row.rotated_at is not None and moment - row.rotated_at > REUSE_GRACE:
        await revoke_family(db, family_id=row.family_id, reason="REUSE_DETECTED", now=moment)
        await record_admin_audit_event(
            db, action=ACTION_REFRESH_REUSE_DETECTED, outcome=OUTCOME_DENIED, source=SOURCE_SESSION_ROTATION,
            target_user=user, actor_type=ACTOR_SYSTEM, actor_label="auth/session/rotate",
            reason="A rotated refresh token was presented again: every session of this sign-in was ended.",
            metadata={"family_id": str(row.family_id), "sign_in_method": row.sign_in_method},
        )
        raise RefreshTokenError("refresh token reuse")
    if row.expires_at <= moment:
        await revoke_family(db, family_id=row.family_id, reason="EXPIRED", now=moment)
        raise RefreshTokenError("expired refresh token")
    if (
        is_disabled_account(user) or is_rejected_account(user)
        or int(user.auth_version or 0) != row.auth_version
    ):
        await revoke_family(db, family_id=row.family_id, reason="ACCOUNT_STATE", now=moment)
        raise RefreshTokenError("account state changed")
    child, child_token = _new_row(
        user=user, family_id=row.family_id, method=row.sign_in_method, started=row.family_started_at, now=moment,
    )
    if child.expires_at <= moment:
        await revoke_family(db, family_id=row.family_id, reason="EXPIRED", now=moment)
        raise RefreshTokenError("session reached its maximum age")
    db.add(child)
    if row.rotated_at is None:
        row.rotated_at = moment
        row.replaced_by_id = child.id
    await db.flush()
    return user, IssuedRefreshToken(token=child_token, family_id=child.family_id, expires_at=child.expires_at)
