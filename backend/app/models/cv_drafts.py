"""R3 Task 3: a reviewable CV draft proposed from one uploaded CV document version."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


CV_DRAFT_STATES = ("PROCESSING_DOCUMENT", "QUEUED", "EXTRACTING", "READY", "FAILED", "CONFIRMED")


class CVDraft(Base):
    """Proposed CV fields with verbatim quotes. Nothing here is a CV until confirmed.

    One draft per uploaded document version: a re-upload is a new version and a new
    draft. Confirming writes a new immutable CVVersion and records its id here.
    """

    __tablename__ = "candidate_cv_drafts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    # The expert the CV is for; NULL when the upload is for a new expert.
    expert_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("candidate_experts.id", ondelete="RESTRICT"), nullable=True
    )
    private_document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    proposal: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    extraction_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    confirmed_cv_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("candidate_cv_versions.id", ondelete="RESTRICT"), nullable=True
    )
    confirmed_by_membership_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["document_version_id", "organization_id"],
            ["private_document_versions.id", "private_document_versions.organization_id"],
            name="fk_cv_draft_version_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["private_document_id", "organization_id"],
            ["private_documents.id", "private_documents.organization_id"],
            name="fk_cv_draft_document_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_cv_draft_creator_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["confirmed_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_cv_draft_confirmer_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "state IN ('PROCESSING_DOCUMENT','QUEUED','EXTRACTING','READY','FAILED','CONFIRMED')",
            name="ck_cv_draft_state",
        ),
        CheckConstraint(
            "(state = 'CONFIRMED') = (confirmed_cv_version_id IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_cv_draft_confirmed",
        ),
        CheckConstraint(
            "jsonb_typeof(proposal) = 'object' AND jsonb_typeof(extraction_summary) = 'object'",
            name="ck_cv_draft_json",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_cv_draft_attempts"),
        Index("ix_cv_drafts_organization_created", "organization_id", "created_at"),
        Index("ix_cv_drafts_expert", "expert_id"),
        Index(
            "ix_cv_drafts_due",
            "next_attempt_at",
            postgresql_where=text("state IN ('QUEUED','EXTRACTING')"),
        ),
    )
