"""
Sovereign Audit Trail models.

These models store:
1) The tender analysis snapshot.
2) The immutable audit ledger entries chained by hashes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.all_models import Base


class TenderAnalysis(Base):
    """
    Stores one raw tender analysis transaction.

    `analysis_json` contains the exact structured AI output persisted for traceability.
    """

    __tablename__ = "tender_analyses"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tender_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    tender_file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Parent tender analyzed by this record.
    tender: Mapped["Tender"] = relationship(
        "Tender",
        back_populates="analyses",
    )

    # Bidirectional relation to ledger records.
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="analysis",
        cascade="all, delete-orphan",
    )


class AuditLog(Base):
    """
    Immutable ledger entry.

    `current_hash` is SHA-256(payload + previous_hash_or_GENESIS), enabling chain integrity.
    """

    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tender_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_type: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # Null only for the first genesis entry.
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    analysis: Mapped["TenderAnalysis"] = relationship(
        "TenderAnalysis",
        back_populates="audit_logs",
    )

    __table_args__ = (
        Index("ix_audit_logs_current_hash", "current_hash", unique=True),
        Index("ix_audit_logs_timestamp", "timestamp"),
    )
