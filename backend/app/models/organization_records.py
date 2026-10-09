"""R3 Task 6: who changed which organization company-profile and readiness records."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OrganizationRecordEvent(Base):
    """Append-only: one change by one member. Field names only, never their values."""

    __tablename__ = "organization_record_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    company_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("company_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_membership_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL"), nullable=True
    )
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    record_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_fields: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "record_type IN ('COMPANY_PROFILE','COMPANY_VAULT','READINESS_DOCUMENT')",
            name="ck_organization_record_event_type",
        ),
        CheckConstraint("action IN ('CREATE','UPDATE','DELETE')", name="ck_organization_record_event_action"),
        CheckConstraint("jsonb_typeof(changed_fields) = 'array'", name="ck_organization_record_event_fields"),
        Index("ix_organization_record_events_organization_created", "organization_id", "created_at"),
    )
