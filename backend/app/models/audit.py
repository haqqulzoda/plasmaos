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

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.all_models import Base


ANALYSIS_OWNERSHIP_OWNED = "OWNED"
ANALYSIS_OWNERSHIP_QUARANTINED_LEGACY = "QUARANTINED_LEGACY"
ANALYSIS_OWNERSHIP_STATES = (
    ANALYSIS_OWNERSHIP_OWNED,
    ANALYSIS_OWNERSHIP_QUARANTINED_LEGACY,
)


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
    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    company_profile_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("company_profiles.id", ondelete="RESTRICT"),
        nullable=True,
    )
    ownership_state: Mapped[str] = mapped_column(
        String(30),
        default=ANALYSIS_OWNERSHIP_QUARANTINED_LEGACY,
        server_default=text(f"'{ANALYSIS_OWNERSHIP_QUARANTINED_LEGACY}'"),
        nullable=False,
    )
    # Snapshot/display metadata only. Authorization never depends on this value.
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    override_seal: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment=(
            "SHA-256 seal incorporating override state. "
            "Null when no overrides have been applied."
        ),
        doc=(
            "SHA-256 seal incorporating override state. "
            "Computed as SHA-256(content_hash | sorted_override_node_ids | sorted_override_timestamps). "
            "Null when no overrides have been applied."
        ),
    )
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

    __table_args__ = (
        CheckConstraint(
            "(ownership_state = 'OWNED' AND user_id IS NOT NULL "
            "AND company_profile_id IS NOT NULL) OR "
            "(ownership_state = 'QUARANTINED_LEGACY' AND user_id IS NULL "
            "AND company_profile_id IS NULL)",
            name="ck_tender_analyses_ownership_tuple",
        ),
        Index("ix_tender_analyses_user_id", "user_id"),
        Index("ix_tender_analyses_company_profile_id", "company_profile_id"),
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


class AdminActivityEvent(Base):
    """Administrative account-management event log."""

    __tablename__ = "admin_activity_events"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_email: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_admin_activity_events_action", "action"),
        Index("ix_admin_activity_events_target_user_id", "target_user_id"),
        Index("ix_admin_activity_events_target_email", "target_email"),
        Index("ix_admin_activity_events_created_at", "created_at"),
    )


class TenderRecommendation(Base):
    """
    Stores AI-generated tender opportunities for each company profile.
    """

    __tablename__ = "tender_recommendations"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tender_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenders.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("company_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    match_score: Mapped[int] = mapped_column(Integer, nullable=False)
    strategic_rationale: Mapped[str] = mapped_column(Text, nullable=False)
    is_dismissed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    tender: Mapped["Tender"] = relationship("Tender")
    company_profile: Mapped["CompanyProfile"] = relationship("CompanyProfile")

    __table_args__ = (
        CheckConstraint(
            "match_score >= 0 AND match_score <= 100",
            name="ck_tender_recommendations_match_score_range",
        ),
        UniqueConstraint(
            "tender_id",
            "company_profile_id",
            name="uq_tender_recommendations_tender_profile",
        ),
        Index("ix_tender_recommendations_tender_id", "tender_id"),
        Index("ix_tender_recommendations_company_profile_id", "company_profile_id"),
        Index("ix_tender_recommendations_created_at", "created_at"),
    )
