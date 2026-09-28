"""Organization-private documents, immutable versions, and durable processing."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    DocumentProcessingState,
    PrivateDocumentRole,
    PrivateDocumentState,
)


class PrivateDocument(Base):
    """Logical private file identity beneath one pursuit."""

    __tablename__ = "private_documents"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    pursuit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    role: Mapped[PrivateDocumentRole] = mapped_column(
        Enum(PrivateDocumentRole, name="private_document_role"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    state: Mapped[PrivateDocumentState] = mapped_column(
        Enum(PrivateDocumentState, name="private_document_state"),
        nullable=False,
        default=PrivateDocumentState.ACTIVE,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["DocumentVersion"]] = relationship(
        "DocumentVersion",
        back_populates="document",
        foreign_keys="DocumentVersion.private_document_id",
        order_by="DocumentVersion.version_number",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_private_documents_id_organization"),
        ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_private_document_pursuit_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_private_document_creator_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["current_version_id", "id"],
            ["private_document_versions.id", "private_document_versions.private_document_id"],
            name="fk_private_document_current_version",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        CheckConstraint(
            "(state = 'ACTIVE' AND archived_at IS NULL) OR "
            "(state = 'ARCHIVED' AND archived_at IS NOT NULL)",
            name="ck_private_document_archive_state",
        ),
        Index("ix_private_documents_pursuit_state", "pursuit_id", "state"),
    )


class DocumentVersion(Base):
    """Immutable bytes and content facts for one private document version."""

    __tablename__ = "private_document_versions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    private_document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_display_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(150), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    uploader_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[PrivateDocument] = relationship(
        "PrivateDocument",
        back_populates="versions",
        foreign_keys=[private_document_id],
        primaryjoin="DocumentVersion.private_document_id == PrivateDocument.id",
    )

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_private_document_version_id_organization"),
        UniqueConstraint(
            "private_document_id", "version_number", name="uq_private_document_version_number"
        ),
        UniqueConstraint("id", "private_document_id", name="uq_private_document_version_document"),
        ForeignKeyConstraint(
            ["private_document_id", "organization_id"],
            ["private_documents.id", "private_documents.organization_id"],
            name="fk_private_document_version_document_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["uploader_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_private_document_version_uploader_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version_number >= 1", name="ck_private_document_version_positive"),
        CheckConstraint("byte_size > 0", name="ck_private_document_version_size_positive"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_private_document_version_sha256"),
        Index("ix_private_document_versions_organization_hash", "organization_id", "sha256"),
    )


class PrivateDocumentBatch(Base):
    """One customer-visible multi-file processing outcome."""

    __tablename__ = "private_document_batches"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pursuit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    requested_by_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    state: Mapped[DocumentProcessingState] = mapped_column(
        Enum(DocumentProcessingState, name="document_processing_state"), nullable=False
    )
    file_count: Mapped[int] = mapped_column(Integer, nullable=False)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    jobs: Mapped[list["DocumentProcessingJob"]] = relationship(
        "DocumentProcessingJob", back_populates="batch", passive_deletes=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_private_document_batch_pursuit_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["requested_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_private_document_batch_requester_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "file_count > 0 AND processed_count >= 0 AND failed_count >= 0 "
            "AND processed_count <= file_count AND failed_count <= file_count",
            name="ck_private_document_batch_counts",
        ),
        Index("ix_private_document_batches_pursuit_created", "pursuit_id", "created_at"),
    )


class DocumentProcessingJob(Base):
    """Durable, recoverable work item for one immutable version."""

    __tablename__ = "private_document_processing_jobs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("private_document_batches.id", ondelete="RESTRICT"), nullable=False
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("private_document_versions.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    state: Mapped[DocumentProcessingState] = mapped_column(
        Enum(DocumentProcessingState, name="document_processing_state", create_type=False),
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dispatch_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_dispatch_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_detail: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    batch: Mapped[PrivateDocumentBatch] = relationship("PrivateDocumentBatch", back_populates="jobs")
    result: Mapped["DocumentProcessingResult | None"] = relationship(
        "DocumentProcessingResult", back_populates="job", uselist=False, passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("attempt_count >= 0 AND dispatch_attempt_count >= 0", name="ck_private_document_job_attempts"),
        Index(
            "ix_private_document_jobs_dispatch",
            "next_dispatch_at",
            postgresql_where=text("state IN ('QUEUED','CHECKING','EXTRACTING')"),
        ),
    )


class DocumentProcessingResult(Base):
    """Mutable processing output kept separate from immutable content facts."""

    __tablename__ = "private_document_processing_results"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("private_document_processing_jobs.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("private_document_versions.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    malware_scan_status: Mapped[str] = mapped_column(String(20), nullable=False)
    malware_scanner: Mapped[str | None] = mapped_column(String(100))
    page_count: Mapped[int | None] = mapped_column(Integer)
    page_count_status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN")
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extracted_sha256: Mapped[str | None] = mapped_column(String(64))
    extraction_error_code: Mapped[str | None] = mapped_column(String(80))
    extraction_error_detail: Mapped[str | None] = mapped_column(String(500))
    parser_name: Mapped[str | None] = mapped_column(String(100))
    parser_version: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    job: Mapped[DocumentProcessingJob] = relationship("DocumentProcessingJob", back_populates="result")

    __table_args__ = (
        CheckConstraint("malware_scan_status IN ('PENDING','CLEAN','INFECTED','ERROR')", name="ck_private_document_result_scan"),
        CheckConstraint("page_count IS NULL OR page_count >= 1", name="ck_private_document_result_pages"),
        CheckConstraint("page_count_status IN ('KNOWN','UNKNOWN')", name="ck_private_document_result_page_status"),
    )


class PursuitTenderContext(Base):
    """Organization-private tender metadata for an uploaded pursuit."""

    __tablename__ = "pursuit_tender_contexts"

    pursuit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    buyer: Mapped[str | None] = mapped_column(String(500))
    declared_funder: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(255))
    reference: Mapped[str | None] = mapped_column(String(255))
    procurement_stage: Mapped[str | None] = mapped_column(String(255))
    external_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_timezone: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(String(2000))
    confirmed_fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    confirmed_by_membership_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_pursuit_context_pursuit_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["confirmed_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_pursuit_context_confirmer_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint("jsonb_typeof(confirmed_fields) = 'object'", name="ck_pursuit_context_confirmed_fields"),
        Index("ix_pursuit_context_organization", "organization_id", "updated_at"),
    )


class PursuitContextSuggestion(Base):
    """Evidence-backed provisional field suggestion from one exact version."""

    __tablename__ = "pursuit_context_suggestions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pursuit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("private_document_versions.id", ondelete="RESTRICT"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(String(40), nullable=False)
    suggested_value: Mapped[str] = mapped_column(String(2000), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    evidence_span: Mapped[str | None] = mapped_column(String(1000))
    confidence: Mapped[float | None] = mapped_column(Float)
    review_state: Mapped[str] = mapped_column(String(20), nullable=False, default="PROVISIONAL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_pursuit_context_suggestion_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "field_name IN ('title','buyer','declared_funder','country','reference',"
            "'procurement_stage','external_deadline','deadline_timezone','source_url')",
            name="ck_pursuit_context_suggestion_field",
        ),
        CheckConstraint("page_number IS NULL OR page_number >= 1", name="ck_pursuit_context_suggestion_page"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_pursuit_context_suggestion_confidence"),
        CheckConstraint("review_state IN ('PROVISIONAL','ACCEPTED','REJECTED')", name="ck_pursuit_context_suggestion_review"),
        Index("ix_pursuit_context_suggestions_pursuit", "pursuit_id", "created_at"),
    )


class MembershipLifecycleEvent(Base):
    """Append-only organization access history from the W3 boundary onward."""

    __tablename__ = "membership_lifecycle_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    membership_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("memberships.id", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_membership_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    previous_role: Mapped[str | None] = mapped_column(String(20))
    new_role: Mapped[str | None] = mapped_column(String(20))
    previous_state: Mapped[str | None] = mapped_column(String(20))
    new_state: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "action IN ('W2_BACKFILL','INVITE','REINVITE','ACTIVATE','ROLE_CHANGE','REVOKE')",
            name="ck_membership_lifecycle_event_action",
        ),
        Index("ix_membership_lifecycle_events_membership_created", "membership_id", "created_at"),
        Index("ix_membership_lifecycle_events_organization_created", "organization_id", "created_at"),
    )
