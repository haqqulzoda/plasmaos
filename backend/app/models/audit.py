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

ANALYSIS_VERSION_ORIGIN_LEGACY_BACKFILL = "LEGACY_BACKFILL"
ANALYSIS_VERSION_ORIGIN_RUNTIME_ANALYSIS = "RUNTIME_ANALYSIS"
ANALYSIS_VERSION_ORIGIN_RUNTIME_REANALYSIS = "RUNTIME_REANALYSIS"
ANALYSIS_VERSION_STATUS_COMPLETED = "COMPLETED"
ANALYSIS_VERSION_STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
ANALYSIS_VERSION_STATUS_FAILED = "FAILED"
ANALYSIS_SNAPSHOT_COMPLETE = "COMPLETE"
ANALYSIS_SNAPSHOT_PARTIAL = "PARTIAL"
ANALYSIS_SNAPSHOT_LEGACY_BACKFILL = "LEGACY_BACKFILL"


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
    versions: Mapped[list["AnalysisVersion"]] = relationship(
        "AnalysisVersion",
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="AnalysisVersion.version_number",
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


class AnalysisVersion(Base):
    """Immutable completed analysis execution beneath a logical analysis."""

    __tablename__ = "analysis_versions"

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
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analysis_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    origin: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    analysis_schema_version: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    pipeline_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_template_version: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    prompt_template_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    provenance_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    tender_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    company_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_set_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_completeness: Mapped[str] = mapped_column(String(30), nullable=False)
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    analysis: Mapped["TenderAnalysis"] = relationship(
        "TenderAnalysis", back_populates="versions"
    )
    supersedes: Mapped["AnalysisVersion | None"] = relationship(
        "AnalysisVersion", remote_side=[id], uselist=False
    )
    document_snapshots: Mapped[list["AnalysisVersionDocumentSnapshot"]] = relationship(
        "AnalysisVersionDocumentSnapshot",
        back_populates="analysis_version",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "version_number",
            name="uq_analysis_versions_analysis_version_number",
        ),
        UniqueConstraint(
            "supersedes_version_id",
            name="uq_analysis_versions_supersedes_version_id",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="ck_analysis_versions_version_number_positive",
        ),
        CheckConstraint(
            "supersedes_version_id IS NULL OR supersedes_version_id <> id",
            name="ck_analysis_versions_not_self_superseding",
        ),
        CheckConstraint(
            "origin IN ('LEGACY_BACKFILL', 'RUNTIME_ANALYSIS', "
            "'RUNTIME_REANALYSIS')",
            name="ck_analysis_versions_origin_allowed",
        ),
        CheckConstraint(
            "status IN ('COMPLETED', 'NEEDS_REVIEW', 'FAILED')",
            name="ck_analysis_versions_status_allowed",
        ),
        CheckConstraint(
            "snapshot_completeness IN ('COMPLETE', 'PARTIAL', 'LEGACY_BACKFILL')",
            name="ck_analysis_versions_snapshot_completeness_allowed",
        ),
        Index(
            "ix_analysis_versions_analysis_created",
            "analysis_id",
            "created_at",
        ),
        Index("ix_analysis_versions_requested_by_user_id", "requested_by_user_id"),
    )


class AnalysisVersionDocumentSnapshot(Base):
    """Document identity and hashes as observed by one analysis version."""

    __tablename__ = "analysis_version_document_snapshots"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    analysis_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analysis_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    tender_document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tender_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_system: Mapped[str] = mapped_column(String(50), nullable=False)
    source_document_key: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_reference: Mapped[str | None] = mapped_column(
        String(1000), nullable=True
    )
    storage_version: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    snapshot_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    analysis_version: Mapped["AnalysisVersion"] = relationship(
        "AnalysisVersion", back_populates="document_snapshots"
    )

    __table_args__ = (
        Index(
            "ix_analysis_version_documents_version",
            "analysis_version_id",
        ),
        Index(
            "ix_analysis_version_documents_tender_document",
            "tender_document_id",
        ),
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
