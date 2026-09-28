"""W8 organization-private proposal workspaces, sealed evidence, and exports."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


PACK_ITEM_CATEGORIES = (
    "PURSUIT_CONTEXT",
    "REQUIREMENT",
    "GAP_ASSESSMENT",
    "FIRM",
    "PROJECT_REFERENCE",
    "EXPERT",
    "CV_FACTS",
    "PARTICIPATION_CONFIRMATION",
    "SOURCE_DOCUMENT",
    "PRIVATE_DOCUMENT",
    "LATER_STAGE_OBLIGATION",
    "FORM_OR_REQUIRED_ARTIFACT",
    "OTHER",
)
ARTIFACT_TYPES = ("PDF", "DOCX", "JSON")


class PursuitProposalWorkspace(Base):
    """Stable Organization destination for one Pursuit's proposal preparation."""

    __tablename__ = "pursuit_proposal_workspaces"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pursuit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_by_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "pursuit_id", name="uq_proposal_workspace_organization_pursuit"),
        UniqueConstraint("id", "organization_id", name="uq_proposal_workspace_id_organization"),
        ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_proposal_workspace_pursuit_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_proposal_workspace_actor_organization", ondelete="RESTRICT",
        ),
        Index("ix_proposal_workspaces_organization_created", "organization_id", "created_at"),
    )


class ProposalEvidencePack(Base):
    """Immutable evidence truth sealed from one exact approved W7 revision."""

    __tablename__ = "proposal_evidence_packs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pursuit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pack_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scenario_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scenario_revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    approval_decision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    analysis_pack_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_packs.id", ondelete="RESTRICT"), nullable=False
    )
    sealed_by_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    pack_state: Mapped[str] = mapped_column(String(20), nullable=False)
    scenario_title_snapshot: Mapped[str] = mapped_column(String(300), nullable=False)
    pursuit_title_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    matrix_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    participant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    later_stage_count: Mapped[int] = mapped_column(Integer, nullable=False)
    checklist_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "pack_version", name="uq_proposal_pack_workspace_version"),
        UniqueConstraint("id", "organization_id", name="uq_proposal_pack_id_organization"),
        ForeignKeyConstraint(
            ["workspace_id", "organization_id"],
            ["pursuit_proposal_workspaces.id", "pursuit_proposal_workspaces.organization_id"],
            name="fk_proposal_pack_workspace_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_proposal_pack_pursuit_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["scenario_id", "organization_id"],
            ["team_scenarios.id", "team_scenarios.organization_id"],
            name="fk_proposal_pack_scenario_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["scenario_revision_id", "scenario_id", "organization_id"],
            ["team_scenario_revisions.id", "team_scenario_revisions.scenario_id", "team_scenario_revisions.organization_id"],
            name="fk_proposal_pack_revision_scenario_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["approval_decision_id", "scenario_revision_id", "organization_id"],
            ["team_scenario_decisions.id", "team_scenario_decisions.revision_id", "team_scenario_decisions.organization_id"],
            name="fk_proposal_pack_approval_revision_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["sealed_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_proposal_pack_actor_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["scenario_revision_id", "analysis_run_id"],
            ["team_scenario_revisions.id", "team_scenario_revisions.analysis_run_id"],
            name="fk_proposal_pack_revision_analysis", ondelete="RESTRICT",
        ),
        CheckConstraint("pack_version >= 1", name="ck_proposal_pack_version"),
        CheckConstraint("pack_state = 'SEALED'", name="ck_proposal_pack_state"),
        CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$'", name="ck_proposal_pack_manifest_sha"),
        CheckConstraint(
            "item_count >= 0 AND matrix_row_count >= 0 AND participant_count >= 0 "
            "AND later_stage_count >= 0 AND checklist_count >= 0",
            name="ck_proposal_pack_counts",
        ),
        Index("ix_proposal_packs_workspace_created", "workspace_id", "created_at"),
        Index("ix_proposal_packs_revision", "scenario_revision_id", "created_at"),
    )


class ProposalEvidencePackItem(Base):
    """One immutable manifest entry retaining exact authority and provenance."""

    __tablename__ = "proposal_evidence_pack_items"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pack_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    source_authority_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_identity: Mapped[str] = mapped_column(String(500), nullable=False)
    provenance: Mapped[str] = mapped_column(String(80), nullable=False)
    review_state: Mapped[str | None] = mapped_column(String(50))
    evidence_state: Mapped[str | None] = mapped_column(String(50))
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_requirements.id", ondelete="RESTRICT")
    )
    position_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_positions.id", ondelete="RESTRICT")
    )
    gap_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_gaps.id", ondelete="RESTRICT")
    )
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    source_version: Mapped[str | None] = mapped_column(String(100))
    payload_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("pack_id", "ordinal", name="uq_proposal_pack_item_ordinal"),
        UniqueConstraint("id", "pack_id", name="uq_proposal_pack_item_id_pack"),
        ForeignKeyConstraint(
            ["pack_id", "organization_id"],
            ["proposal_evidence_packs.id", "proposal_evidence_packs.organization_id"],
            name="fk_proposal_pack_item_pack_organization", ondelete="RESTRICT",
        ),
        CheckConstraint(f"category IN {PACK_ITEM_CATEGORIES!r}", name="ck_proposal_pack_item_category"),
        CheckConstraint("ordinal >= 1", name="ck_proposal_pack_item_ordinal"),
        CheckConstraint("length(trim(source_authority_type)) >= 2", name="ck_proposal_pack_item_authority"),
        CheckConstraint("length(trim(source_identity)) >= 1", name="ck_proposal_pack_item_identity"),
        CheckConstraint("source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_proposal_pack_item_sha"),
        Index("ix_proposal_pack_items_pack_category", "pack_id", "category", "ordinal"),
    )


class ProposalEvidenceArtifact(Base):
    """Immutable private artifact generated solely from one sealed pack."""

    __tablename__ = "proposal_evidence_artifacts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pack_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(10), nullable=False)
    historical_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(150), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_by_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("pack_id", "artifact_type", "historical_snapshot", name="uq_proposal_artifact_pack_type_history"),
        UniqueConstraint("id", "organization_id", name="uq_proposal_artifact_id_organization"),
        ForeignKeyConstraint(
            ["pack_id", "organization_id"],
            ["proposal_evidence_packs.id", "proposal_evidence_packs.organization_id"],
            name="fk_proposal_artifact_pack_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_proposal_artifact_actor_organization", ondelete="RESTRICT",
        ),
        CheckConstraint(f"artifact_type IN {ARTIFACT_TYPES!r}", name="ck_proposal_artifact_type"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_proposal_artifact_sha"),
        CheckConstraint("byte_size > 0", name="ck_proposal_artifact_size"),
        Index("ix_proposal_artifacts_pack_created", "pack_id", "created_at"),
    )

