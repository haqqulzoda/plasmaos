"""Tender-change alerts: a pursued tender's source changed after the firm analyzed it."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TenderChange(Base):
    """One detected source change (DEADLINE, AMENDMENT and/or DOCUMENT); kinds only, no content."""

    __tablename__ = "tender_changes"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tender_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False
    )
    change_kinds: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(change_kinds) = 'array' AND jsonb_array_length(change_kinds) BETWEEN 1 AND 3",
            name="ck_tender_change_kinds",
        ),
        Index("ix_tender_changes_tender_detected", "tender_id", "detected_at"),
    )
