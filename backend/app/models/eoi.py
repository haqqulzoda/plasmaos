"""D2-05 Expression of Interest drafts: immutable inputs, manifest and rendered artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


EOI_LANGUAGES = ("en", "ru")
EOI_ARTIFACT_FORMATS = ("DOCX", "PDF")


class EoiDraft(Base):
    """One generated EOI package. The manifest holds every rendered fact with its source id."""

    __tablename__ = "eoi_drafts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pursuit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_runs.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("pursuit_id", "version", name="uq_eoi_draft_pursuit_version"),
        UniqueConstraint("id", "organization_id", name="uq_eoi_draft_id_organization"),
        ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_eoi_draft_pursuit_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_eoi_draft_actor_organization", ondelete="RESTRICT",
        ),
        CheckConstraint("version >= 1", name="ck_eoi_draft_version"),
        CheckConstraint(f"language IN {EOI_LANGUAGES!r}", name="ck_eoi_draft_language"),
        CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$'", name="ck_eoi_draft_manifest_sha"),
        CheckConstraint("jsonb_typeof(inputs) = 'object' AND jsonb_typeof(manifest) = 'object'", name="ck_eoi_draft_json"),
        Index("ix_eoi_drafts_pursuit_created", "organization_id", "pursuit_id", "created_at"),
    )


class EoiDraftArtifact(Base):
    """A rendered DOCX or PDF of one draft, kept in private storage."""

    __tablename__ = "eoi_draft_artifacts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    draft_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(150), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("draft_id", "format", name="uq_eoi_artifact_draft_format"),
        ForeignKeyConstraint(
            ["draft_id", "organization_id"], ["eoi_drafts.id", "eoi_drafts.organization_id"],
            name="fk_eoi_artifact_draft_organization", ondelete="RESTRICT",
        ),
        CheckConstraint(f"format IN {EOI_ARTIFACT_FORMATS!r}", name="ck_eoi_artifact_format"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_eoi_artifact_sha"),
        CheckConstraint("byte_size > 0", name="ck_eoi_artifact_size"),
        Index("ix_eoi_artifacts_draft", "draft_id"),
    )
