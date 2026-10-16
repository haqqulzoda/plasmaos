"""P1: e-mail one-time sign-in codes and rotating refresh tokens.

Neither table stores a secret: a code is kept as a keyed hash (HMAC-SHA256 with a key
derived from SECRET_KEY and the challenge id), a refresh token as its SHA-256.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

CHALLENGE_CLOSE_REASONS = ("CONSUMED", "SUPERSEDED", "LOCKED", "EXPIRED")
SIGN_IN_METHODS = ("GOOGLE", "EMAIL_CODE")
REFRESH_REVOKE_REASONS = ("LOGOUT", "REUSE_DETECTED", "ACCOUNT_STATE", "EXPIRED")


class EmailSignInChallenge(Base):
    """One requested sign-in code. At most one is open per e-mail address."""

    __tablename__ = "email_sign_in_challenges"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Whether an e-mail was staged: blocked and privileged accounts get a challenge but no e-mail,
    # so every request behaves the same from the outside.
    delivery: Mapped[str] = mapped_column(String(20), nullable=False)
    requester_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("attempt_count >= 0 AND attempt_count <= 5", name="ck_email_sign_in_attempts"),
        CheckConstraint(
            "delivery IN ('STAGED','NO_CHANNEL','ACCOUNT_BLOCKED','PRIVILEGED')", name="ck_email_sign_in_delivery"
        ),
        CheckConstraint(
            "(closed_at IS NULL AND close_reason IS NULL) OR "
            "(closed_at IS NOT NULL AND close_reason IN ('CONSUMED','SUPERSEDED','LOCKED','EXPIRED'))",
            name="ck_email_sign_in_closed",
        ),
        CheckConstraint("email = lower(email)", name="ck_email_sign_in_email_lower"),
        Index("uq_email_sign_in_open_email", "email", unique=True, postgresql_where=text("closed_at IS NULL")),
        Index("ix_email_sign_in_email_created", "email", "created_at"),
    )


class AuthRefreshToken(Base):
    """One refresh token. A sign-in starts a family; each rotation replaces the row with a child.

    Presenting a rotated token again (outside a short grace window for concurrent requests)
    revokes the whole family. A family dies with the account's ``auth_version``.
    """

    __tablename__ = "auth_refresh_tokens"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False)
    sign_in_method: Mapped[str] = mapped_column(String(20), nullable=False)
    family_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("sign_in_method IN ('GOOGLE','EMAIL_CODE')", name="ck_auth_refresh_method"),
        CheckConstraint(
            "(revoked_at IS NULL AND revoke_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoke_reason IN ('LOGOUT','REUSE_DETECTED','ACCOUNT_STATE','EXPIRED'))",
            name="ck_auth_refresh_revoked",
        ),
        CheckConstraint("expires_at > created_at", name="ck_auth_refresh_expiry"),
        Index("ix_auth_refresh_tokens_family", "family_id"),
        Index("ix_auth_refresh_tokens_user", "user_id", "created_at"),
    )
