"""Sprint 1: server-side product events and the AI cost ledger.

Both tables are append-only (a trigger rejects UPDATE and DELETE) and hold ids, codes,
counts and timings only: never document text, prompts, outputs or names. Neither table
has foreign keys: an analytics row must never block deleting a user or an organization,
nor fail the product action it describes.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

PRODUCT_EVENT_NAMES = (
    "sign_in",
    "tender_viewed",
    "workspace_opened",
    "analysis_started",
    "analysis_completed",
    "analysis_failed",
    "review_confirmed",
    "eoi_generated",
    "eoi_downloaded",
    "invite_sent",
    "invite_accepted",
    "cv_uploaded",
)
AI_CALL_KINDS = ("ANALYSIS", "CV_EXTRACTION", "EOI_NOTE")
AI_CALL_OUTCOMES = ("SUCCEEDED", "FAILED")


def _in(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


class ProductEvent(Base):
    __tablename__ = "product_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_name: Mapped[str] = mapped_column(String(40), nullable=False)
    organization_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    actor_membership_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    tender_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    pursuit_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    analysis_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    subject_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    subject_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(f"event_name IN ({_in(PRODUCT_EVENT_NAMES)})", name="ck_product_event_name"),
        CheckConstraint("jsonb_typeof(properties) = 'object'", name="ck_product_event_properties"),
        Index("ix_product_events_name_occurred", "event_name", "occurred_at"),
        Index("ix_product_events_organization_occurred", "organization_id", "occurred_at"),
    )


class AICallCost(Base):
    """One provider call: model, tokens, latency and the cost estimated from the price table."""

    __tablename__ = "ai_call_costs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    call_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    organization_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    pursuit_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thinking_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    price_table_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(f"call_kind IN ({_in(AI_CALL_KINDS)})", name="ck_ai_call_cost_kind"),
        CheckConstraint(f"outcome IN ({_in(AI_CALL_OUTCOMES)})", name="ck_ai_call_cost_outcome"),
        CheckConstraint(
            "coalesce(input_tokens, 0) >= 0 AND coalesce(output_tokens, 0) >= 0 AND coalesce(thinking_tokens, 0) >= 0",
            name="ck_ai_call_cost_tokens",
        ),
        Index("ix_ai_call_costs_kind_created", "call_kind", "created_at"),
        Index("ix_ai_call_costs_subject", "subject_type", "subject_id"),
        Index("ix_ai_call_costs_organization_created", "organization_id", "created_at"),
    )
