"""
Plasma AI - Database Models

Defines all SQLAlchemy ORM models for the Autonomous Tender Officer SaaS platform.
"""

import enum
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, ProposalStatus, SubscriptionTier, TenderStatus


# ============================================================================
# Models
# ============================================================================


class TenderSyncStatus(str, enum.Enum):
    """Lifecycle status for tender document sync jobs."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class Project(Base):
    """Source-scoped canonical identity for an institution's project."""

    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    source_system: Mapped[str] = mapped_column(String(50), nullable=False)
    external_project_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    project_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    approval_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    closing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    borrower: Mapped[str | None] = mapped_column(Text, nullable=True)
    implementing_agencies: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    enrichment_status: Mapped[str] = mapped_column(
        String(30),
        default="never_attempted",
        server_default=text("'never_attempted'"),
        nullable=False,
    )
    enrichment_last_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_enriched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    enrichment_failure_class: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    enrichment_source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    enrichment_fields_obtained: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    enrichment_fields_missing: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    tender_links: Mapped[list["TenderProject"]] = relationship(
        "TenderProject",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    role_assignments: Mapped[list["ProjectRoleAssignment"]] = relationship(
        "ProjectRoleAssignment",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "source_system IN ('uzex', 'world_bank', 'adb', 'giz', 'ebrd')",
            name="ck_projects_source_system_allowed",
        ),
        UniqueConstraint(
            "source_system",
            "external_project_id",
            name="uq_projects_source_external_project_id",
        ),
        CheckConstraint(
            "enrichment_status IN ('never_attempted', 'queued', 'running', "
            "'successful', 'partial', 'source_unavailable', 'failed', 'stale')",
            name="ck_projects_enrichment_status_allowed",
        ),
        Index(
            "ix_projects_source_enrichment_status",
            "source_system",
            "enrichment_status",
            "last_enriched_at",
        ),
    )


class Tender(Base):
    """
    Public procurement tenders from UzEx/Etender.
    The core feed that users interact with.
    """
    
    __tablename__ = "tenders"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    external_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    source_system: Mapped[str] = mapped_column(
        String(50),
        default="uzex",
        nullable=False,
    )
    canonical_source_key: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Aggregated NLP-ready text compiled from scraped/parsed documents.
    compiled_master_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="UZS", nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    publication_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(500), nullable=True)
    buyer: Mapped[str | None] = mapped_column(String(300), nullable=True)
    procurement_category: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    procurement_method: Mapped[str | None] = mapped_column(String(150), nullable=True)
    notice_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    scrape_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[TenderStatus] = mapped_column(
        Enum(TenderStatus, name="tender_status"),
        default=TenderStatus.OPEN,
        nullable=False,
    )
    category: Mapped[str] = mapped_column(
        String(50),
        default="Other",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    # Relationships
    documents: Mapped[list["TenderDocument"]] = relationship(
        "TenderDocument",
        back_populates="tender",
        cascade="all, delete-orphan",
    )
    proposals: Mapped[list["Proposal"]] = relationship(
        "Proposal",
        back_populates="tender",
        cascade="all, delete-orphan",
    )
    analyses: Mapped[list["TenderAnalysis"]] = relationship(
        "TenderAnalysis",
        back_populates="tender",
        cascade="all, delete-orphan",
    )
    project_link: Mapped["TenderProject | None"] = relationship(
        "TenderProject",
        back_populates="tender",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    
    # Indexes
    __table_args__ = (
        CheckConstraint(
            "source_system IN ('uzex', 'world_bank', 'adb', 'giz', 'ebrd')",
            name="ck_tenders_source_system_allowed",
        ),
        Index("ix_tenders_external_id", "external_id"),
        Index(
            "ix_tenders_source_system_external_id",
            "source_system",
            "external_id",
            unique=True,
        ),
        Index("ix_tenders_canonical_source_key", "canonical_source_key", unique=True),
        Index("ix_tenders_source_system", "source_system"),
        Index("ix_tenders_status", "status"),
        Index("ix_tenders_deadline", "deadline"),
    )


class TenderProject(Base):
    """Auditable deterministic linkage between a tender and a Project."""

    __tablename__ = "tender_projects"

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
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    linkage_method: Mapped[str] = mapped_column(String(50), nullable=False)
    source_value: Mapped[str] = mapped_column(String(100), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    tender: Mapped["Tender"] = relationship("Tender", back_populates="project_link")
    project: Mapped["Project"] = relationship("Project", back_populates="tender_links")

    __table_args__ = (
        CheckConstraint(
            "linkage_method IN ('SOURCE_PROJECT_ID', 'SOURCE_NATIVE_LINK')",
            name="ck_tender_projects_linkage_method_allowed",
        ),
        UniqueConstraint("tender_id", name="uq_tender_projects_tender_id"),
        Index("ix_tender_projects_project_id", "project_id"),
    )


class ProjectRoleAssignment(Base):
    """Source-evidenced Project leadership assignment with retained history."""

    __tablename__ = "project_role_assignments"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_system: Mapped[str] = mapped_column(String(50), nullable=False)
    assignment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_person_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    native_role: Mapped[str] = mapped_column(String(150), nullable=False)
    canonical_role: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_document_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="role_assignments",
    )

    __table_args__ = (
        CheckConstraint(
            "source_system IN ('uzex', 'world_bank', 'adb', 'giz', 'ebrd')",
            name="ck_project_role_assignments_source_system_allowed",
        ),
        CheckConstraint(
            "canonical_role IN ('TASK_TEAM_LEADER', 'CO_TASK_TEAM_LEADER', "
            "'PROJECT_TASK_MANAGER', 'OTHER_PROJECT_ROLE')",
            name="ck_project_role_assignments_canonical_role_allowed",
        ),
        UniqueConstraint(
            "project_id",
            "source_system",
            "assignment_key",
            name="uq_project_role_assignments_identity",
        ),
        Index(
            "ix_project_role_assignments_project_current",
            "project_id",
            "is_current",
        ),
    )


class TenderSyncJob(Base):
    """
    Persistent sync job state for tender document ingestion.

    Used to provide idempotent enqueue semantics and canonical polling state.
    """

    __tablename__ = "tender_sync_jobs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    job_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
    )
    tender_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenders.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[TenderSyncStatus] = mapped_column(
        Enum(TenderSyncStatus, name="tender_sync_status"),
        default=TenderSyncStatus.PENDING,
        nullable=False,
    )
    progress: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    tender: Mapped["Tender"] = relationship("Tender")
    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_tender_sync_jobs_progress_range",
        ),
        Index("ix_tender_sync_jobs_tender_id", "tender_id"),
        Index("ix_tender_sync_jobs_user_id", "user_id"),
        Index("ix_tender_sync_jobs_status", "status"),
        Index(
            "uq_tender_sync_jobs_active_user_tender",
            "user_id",
            "tender_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'IN_PROGRESS')"),
        ),
    )


class SourceRefreshJob(Base):
    """Persistent, source-wide refresh state used for cooldown and deduplication."""

    __tablename__ = "source_refresh_jobs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    source_system: Mapped[str] = mapped_column(String(50), nullable=False)
    requested_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    force: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    skip_reasons: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    failure_class: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    retryable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_newest_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    source_oldest_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    execution_health: Mapped[str | None] = mapped_column(String(30), nullable=True)
    freshness_health: Mapped[str | None] = mapped_column(String(30), nullable=True)
    coverage_health: Mapped[str | None] = mapped_column(String(30), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    requested_by: Mapped["User | None"] = relationship("User")

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial', "
            "'source_unavailable', 'failed')",
            name="ck_source_refresh_jobs_status_allowed",
        ),
        Index("ix_source_refresh_jobs_source_created", "source_system", "created_at"),
        Index(
            "uq_source_refresh_jobs_active_source",
            "source_system",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )


class TenderDocument(Base):
    """
    Documents attached to tenders.
    Contains parsed text for AI processing.
    """
    
    __tablename__ = "tender_documents"
    
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
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_document_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_document_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    download_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    download_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_file_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parsed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    # Relationships
    tender: Mapped["Tender"] = relationship(
        "Tender",
        back_populates="documents",
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_tender_documents_tender_id", "tender_id"),
    )


class Proposal(Base):
    """
    AI-generated proposals for tenders.
    The core value proposition of the platform.
    """
    
    __tablename__ = "proposals"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    tender_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenders.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus, name="proposal_status"),
        default=ProposalStatus.DRAFT,
        nullable=False,
    )
    ai_confidence_score: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    structured_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    final_pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    # Financial fields
    margin_percent: Mapped[float] = mapped_column(
        Float,
        default=20.0,
        nullable=False,
    )
    include_vat: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(10),
        default="UZS",
        nullable=False,
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="proposals",
    )
    tender: Mapped["Tender"] = relationship(
        "Tender",
        back_populates="proposals",
    )
    
    # Indexes
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "tender_id",
            name="uq_proposals_user_tender",
        ),
        Index("ix_proposals_user_id", "user_id"),
        Index("ix_proposals_tender_id", "tender_id"),
        Index("ix_proposals_status", "status"),
    )


# Import modular models so Alembic autogenerate sees the full metadata graph.
from app.models.audit import AdminActivityEvent, AuditLog, TenderAnalysis, TenderRecommendation  # noqa: E402,F401
from app.models.company import (  # noqa: E402,F401
    Certification,
    CompanyProfile,
    FinancialHistory,
    License,
    ReadinessDocument,
)
from app.models.taxonomy import (  # noqa: E402,F401
    CompanyCredential,
    RiskOverrideLog,
    TaxonomyCategory,
    TaxonomyNode,
    TenderRequirement,
)
from app.models.user import User  # noqa: E402,F401


__all__ = [
    "Base",
    "SubscriptionTier",
    "TenderStatus",
    "ProposalStatus",
    "TenderSyncStatus",
    "User",
    "Project",
    "ProjectRoleAssignment",
    "Tender",
    "TenderProject",
    "TenderSyncJob",
    "SourceRefreshJob",
    "TenderDocument",
    "Proposal",
    "CompanyProfile",
    "Certification",
    "License",
    "FinancialHistory",
    "ReadinessDocument",
    "TaxonomyCategory",
    "TaxonomyNode",
    "CompanyCredential",
    "TenderRequirement",
    "RiskOverrideLog",
    "TenderAnalysis",
    "TenderRecommendation",
    "AuditLog",
    "AdminActivityEvent",
]
