"""P1: durable alerts to the Plasma team (a new self sign-up, a pilot or call request, the
analysis provider rejecting the key or billing).

Delivered by a Beat task: Telegram when ADMIN_ALERT_TELEGRAM_CHAT_ID is configured, else one
e-mail per PLASMA_ADMIN_EMAILS address through the e-mail outbox.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

ADMIN_ALERT_KINDS = ("NEW_SIGNUP", "PILOT_REQUEST", "ANALYSIS_PROVIDER_ERROR")
ADMIN_ALERT_STATES = ("PENDING", "SENT", "FAILED")
ADMIN_ALERT_CHANNELS = ("TELEGRAM", "EMAIL")


class AdminAlert(Base):
    __tablename__ = "admin_alerts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("kind IN ('NEW_SIGNUP','PILOT_REQUEST','ANALYSIS_PROVIDER_ERROR')", name="ck_admin_alert_kind"),
        CheckConstraint("state IN ('PENDING','SENT','FAILED')", name="ck_admin_alert_state"),
        CheckConstraint("channel IS NULL OR channel IN ('TELEGRAM','EMAIL')", name="ck_admin_alert_channel"),
        CheckConstraint("(state = 'SENT') = (sent_at IS NOT NULL)", name="ck_admin_alert_sent"),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 8192", name="ck_admin_alert_payload"
        ),
        Index("ix_admin_alerts_due", "next_attempt_at", postgresql_where=text("state = 'PENDING'")),
        Index("ix_admin_alerts_kind_created", "kind", "created_at"),
    )
