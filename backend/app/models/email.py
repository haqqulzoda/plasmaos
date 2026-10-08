"""R3 Task 4: the e-mail channel of the notification outbox, and per-user preferences."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


EMAIL_KINDS = ("TEAM_INVITATION", "ANALYSIS_COMPLETED", "ANALYSIS_FAILED", "EOI_DRAFT_READY", "DAILY_DIGEST")
EMAIL_CATEGORIES = ("TEAM", "ANALYSIS", "EOI", "DIGEST")
EMAIL_STATES = ("PENDING", "SENDING", "SENT", "FAILED", "BOUNCED")


class EmailDelivery(Base):
    """One idempotent e-mail. The body is rendered at send time from kind, locale and
    ids; nothing private is stored. ``secret_ciphertext`` holds an encrypted one-time
    link token (invitations) only until the delivery is terminal."""

    __tablename__ = "email_deliveries"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    locale: Mapped[str] = mapped_column(String(8), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('TEAM_INVITATION','ANALYSIS_COMPLETED','ANALYSIS_FAILED','EOI_DRAFT_READY','DAILY_DIGEST')",
            name="ck_email_delivery_kind",
        ),
        CheckConstraint("category IN ('TEAM','ANALYSIS','EOI','DIGEST')", name="ck_email_delivery_category"),
        CheckConstraint("state IN ('PENDING','SENDING','SENT','FAILED','BOUNCED')", name="ck_email_delivery_state"),
        CheckConstraint("locale IN ('en','ru','uz','ar')", name="ck_email_delivery_locale"),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 16384",
            name="ck_email_delivery_payload",
        ),
        CheckConstraint(
            "secret_ciphertext IS NULL OR state IN ('PENDING','SENDING')",
            name="ck_email_delivery_secret_until_terminal",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_email_delivery_attempts"),
        CheckConstraint("(state = 'SENT') = (sent_at IS NOT NULL)", name="ck_email_delivery_sent"),
        Index("ix_email_deliveries_due", "next_attempt_at", postgresql_where=text("state IN ('PENDING','SENDING')")),
        Index("ix_email_deliveries_user_created", "user_id", "created_at"),
        Index("ix_email_deliveries_state_created", "state", "created_at"),
    )


class EmailNotificationPreference(Base):
    """Per-user e-mail switches; NULL means the default (see app.services.email_notifications)."""

    __tablename__ = "email_notification_preferences"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    analysis_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    eoi_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    digest_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
