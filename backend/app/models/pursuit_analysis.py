"""W4 sealed pursuit analysis, source evidence, gaps, and review history."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
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

from app.models.base import Base


COVERAGE_STATES = (
    "SUPPORTED",
    "PARTIAL",
    "GAP",
    "EVIDENCE_MISSING",
    "NEEDS_INTERPRETATION",
    "NOT_APPLICABLE",
    "LATER_STAGE_OBLIGATION",
)


class AnalysisPack(Base):
    """Immutable, explicitly selected input set sealed before extraction."""

    __tablename__ = "pursuit_analysis_packs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pursuit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    requested_by_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    candidate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_pack_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_language: Mapped[str] = mapped_column(String(8), nullable=False)
    admission_decision: Mapped[str] = mapped_column(String(20), nullable=False)
    total_known_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_count_known: Mapped[bool] = mapped_column(Boolean, nullable=False)
    page_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    alternate_character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alternate_character_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_disclosure: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    items: Mapped[list["AnalysisPackItem"]] = relationship(
        "AnalysisPackItem", back_populates="pack", passive_deletes=True, order_by="AnalysisPackItem.ordinal"
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_analysis_pack_pursuit_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["requested_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_analysis_pack_requester_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint("candidate_sha256 ~ '^[0-9a-f]{64}$'", name="ck_analysis_pack_candidate_sha"),
        CheckConstraint("selected_pack_sha256 ~ '^[0-9a-f]{64}$'", name="ck_analysis_pack_selected_sha"),
        CheckConstraint("analysis_language IN ('en','uz','ru')", name="ck_analysis_pack_language"),
        CheckConstraint("admission_decision = 'ADMITTED'", name="ck_analysis_pack_admitted"),
        CheckConstraint("total_known_pages >= 0 AND page_limit = 500", name="ck_analysis_pack_page_limit"),
        CheckConstraint(
            "alternate_character_count >= 0 AND alternate_character_limit > 0",
            name="ck_analysis_pack_alternate_limit",
        ),
        Index("ix_analysis_packs_pursuit_created", "pursuit_id", "created_at"),
    )


class AnalysisPackItem(Base):
    """Immutable replayable source or private input within one pack."""

    __tablename__ = "pursuit_analysis_pack_items"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    pack_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_packs.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    item_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    provenance: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(100), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(150))
    private_document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("private_documents.id", ondelete="RESTRICT")
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("private_document_versions.id", ondelete="RESTRICT")
    )
    version_number: Mapped[int | None] = mapped_column(Integer)
    processing_result_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("private_document_processing_results.id", ondelete="RESTRICT")
    )
    processing_result_sha256: Mapped[str | None] = mapped_column(String(64))
    tender_document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tender_documents.id", ondelete="RESTRICT")
    )
    identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    analyzed_text: Mapped[str] = mapped_column(Text, nullable=False)
    analyzed_text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2000))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    page_count_known: Mapped[bool] = mapped_column(Boolean, nullable=False)
    locator_type: Mapped[str] = mapped_column(String(30), nullable=False)
    locator_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    pack: Mapped[AnalysisPack] = relationship("AnalysisPack", back_populates="items")

    __table_args__ = (
        UniqueConstraint("pack_id", "ordinal", name="uq_analysis_pack_item_ordinal"),
        UniqueConstraint("pack_id", "identity_sha256", name="uq_analysis_pack_item_identity"),
        CheckConstraint("item_kind IN ('PRIVATE','SOURCE')", name="ck_analysis_pack_item_kind"),
        CheckConstraint(
            "(item_kind = 'PRIVATE' AND provenance = 'ORGANIZATION_PRIVATE_UPLOAD' "
            "AND private_document_id IS NOT NULL AND document_version_id IS NOT NULL "
            "AND version_number IS NOT NULL AND processing_result_id IS NOT NULL "
            "AND processing_result_sha256 IS NOT NULL AND tender_document_id IS NULL) OR "
            "(item_kind = 'SOURCE' AND provenance = 'SHARED_SOURCE' "
            "AND tender_document_id IS NOT NULL AND private_document_id IS NULL "
            "AND document_version_id IS NULL AND version_number IS NULL "
            "AND processing_result_id IS NULL AND processing_result_sha256 IS NULL)",
            name="ck_analysis_pack_item_identity_shape",
        ),
        CheckConstraint("identity_sha256 ~ '^[0-9a-f]{64}$'", name="ck_analysis_pack_item_identity_sha"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_analysis_pack_item_content_sha"),
        CheckConstraint("analyzed_text_sha256 ~ '^[0-9a-f]{64}$'", name="ck_analysis_pack_item_text_sha"),
        CheckConstraint("page_count IS NULL OR page_count >= 1", name="ck_analysis_pack_item_pages"),
        CheckConstraint("page_count_known = (page_count IS NOT NULL)", name="ck_analysis_pack_item_page_truth"),
        Index("ix_analysis_pack_items_pack", "pack_id", "ordinal"),
    )


class AnalysisRun(Base):
    """Mutable durable job authority whose results remain append-only."""

    __tablename__ = "pursuit_analysis_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pursuit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pack_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_packs.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    requested_by_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    analysis_language: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result_completeness: Mapped[str | None] = mapped_column(String(30))
    model_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(100), nullable=False)
    quality_state: Mapped[str | None] = mapped_column(String(30))
    extraction_diagnostics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    dispatch_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_dispatch_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_stage: Mapped[str | None] = mapped_column(String(80))
    failure_reason: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pack: Mapped[AnalysisPack] = relationship("AnalysisPack")

    __table_args__ = (
        ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_analysis_run_pursuit_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["requested_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_analysis_run_requester_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint("analysis_language IN ('en','uz','ru')", name="ck_analysis_run_language"),
        CheckConstraint("status IN ('QUEUED','RUNNING','COMPLETED','FAILED')", name="ck_analysis_run_status"),
        CheckConstraint("result_completeness IS NULL OR result_completeness = 'FULL'", name="ck_analysis_run_completeness"),
        CheckConstraint(
            "quality_state IS NULL OR quality_state IN ('READY_FOR_REVIEW','NEEDS_ATTENTION','FAILED')",
            name="ck_analysis_run_quality_state",
        ),
        CheckConstraint("jsonb_typeof(extraction_diagnostics) = 'object'", name="ck_analysis_run_diagnostics"),
        CheckConstraint("attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10 AND dispatch_attempt_count >= 0", name="ck_analysis_run_attempts"),
        CheckConstraint("prompt_sha256 ~ '^[0-9a-f]{64}$'", name="ck_analysis_run_prompt_sha"),
        Index("ix_analysis_runs_pursuit_created", "pursuit_id", "created_at"),
        Index("ix_analysis_runs_dispatch", "status", "next_dispatch_at"),
    )


class AnalysisCompanySnapshot(Base):
    """Immutable company/readiness claims observed for one run."""

    __tablename__ = "pursuit_analysis_company_snapshots"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    analysis_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_runs.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    legacy_company_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("company_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_only_count: Mapped[int] = mapped_column(Integer, nullable=False)
    file_backed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("snapshot_sha256 ~ '^[0-9a-f]{64}$'", name="ck_analysis_company_snapshot_sha"),
        CheckConstraint("metadata_only_count >= 0 AND file_backed_count >= 0", name="ck_analysis_company_snapshot_counts"),
    )


class PursuitRequirement(Base):
    """Immutable machine-extracted corporate requirement with original evidence."""

    __tablename__ = "pursuit_analysis_requirements"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    analysis_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_runs.id", ondelete="RESTRICT"), nullable=False
    )
    pack_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_pack_items.id", ondelete="RESTRICT"), nullable=False
    )
    source_span: Mapped[str] = mapped_column(Text, nullable=False)
    source_locator: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    original_quote: Mapped[str] = mapped_column(Text, nullable=False)
    source_context: Mapped[str | None] = mapped_column(Text)
    normalized_requirement: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    requirement_type: Mapped[str] = mapped_column(String(100), nullable=False)
    stage_scope: Mapped[str] = mapped_column(String(100), nullable=False)
    distinction: Mapped[str] = mapped_column(String(30), nullable=False)
    predicate_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    contribution_rule: Mapped[str | None] = mapped_column(Text)
    coverage_state: Mapped[str] = mapped_column(String(40), nullable=False)
    review_state: Mapped[str] = mapped_column(String(30), nullable=False)
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    generated_interpretation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("distinction IN ('MANDATORY','SCORED','INFORMATIONAL')", name="ck_pursuit_requirement_distinction"),
        CheckConstraint(f"coverage_state IN {COVERAGE_STATES!r}", name="ck_pursuit_requirement_coverage"),
        CheckConstraint("review_state IN ('PROVISIONAL','CONFIRMED','CORRECTED')", name="ck_pursuit_requirement_review"),
        CheckConstraint("extraction_confidence IS NULL OR (extraction_confidence >= 0 AND extraction_confidence <= 1)", name="ck_pursuit_requirement_confidence"),
        Index("ix_pursuit_requirements_run_state", "analysis_run_id", "coverage_state"),
    )


class PursuitPosition(Base):
    """Immutable required-personnel extraction, kept separate from corporate facts."""

    __tablename__ = "pursuit_analysis_positions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    analysis_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_runs.id", ondelete="RESTRICT"), nullable=False
    )
    pack_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_pack_items.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer)
    distinction: Mapped[str] = mapped_column(String(30), nullable=False)
    education_qualification: Mapped[str | None] = mapped_column(Text)
    general_experience: Mapped[str | None] = mapped_column(Text)
    specific_experience: Mapped[str | None] = mapped_column(Text)
    relevant_assignments: Mapped[str | None] = mapped_column(Text)
    languages: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    certifications: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    location_travel: Mapped[str | None] = mapped_column(Text)
    expected_effort: Mapped[str | None] = mapped_column(Text)
    assignment_dates: Mapped[str | None] = mapped_column(Text)
    qualification_criteria: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    source_span: Mapped[str] = mapped_column(Text, nullable=False)
    source_locator: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    original_quote: Mapped[str] = mapped_column(Text, nullable=False)
    source_context: Mapped[str | None] = mapped_column(Text)
    coverage_state: Mapped[str] = mapped_column(String(40), nullable=False)
    review_state: Mapped[str] = mapped_column(String(30), nullable=False)
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    generated_interpretation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("quantity IS NULL OR quantity >= 1", name="ck_pursuit_position_quantity"),
        CheckConstraint("distinction IN ('MANDATORY','SCORED')", name="ck_pursuit_position_distinction"),
        CheckConstraint(f"coverage_state IN {COVERAGE_STATES!r}", name="ck_pursuit_position_coverage"),
        CheckConstraint("review_state IN ('PROVISIONAL','CONFIRMED','CORRECTED')", name="ck_pursuit_position_review"),
        CheckConstraint("extraction_confidence IS NULL OR (extraction_confidence >= 0 AND extraction_confidence <= 1)", name="ck_pursuit_position_confidence"),
        Index("ix_pursuit_positions_run_state", "analysis_run_id", "coverage_state"),
    )


class PursuitGap(Base):
    """Immutable machine-created unresolved contribution for one extracted item."""

    __tablename__ = "pursuit_analysis_gaps"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    analysis_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_runs.id", ondelete="RESTRICT"), nullable=False
    )
    requirement_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_requirements.id", ondelete="RESTRICT")
    )
    position_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_positions.id", ondelete="RESTRICT")
    )
    source_pack_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_pack_items.id", ondelete="RESTRICT"), nullable=False
    )
    missing_contribution: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_state: Mapped[str] = mapped_column(String(40), nullable=False)
    resolution_category: Mapped[str] = mapped_column(String(40), nullable=False)
    review_state: Mapped[str] = mapped_column(String(30), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "analysis_run_id", name="uq_pursuit_gap_id_analysis"),
        CheckConstraint("(requirement_id IS NOT NULL) <> (position_id IS NOT NULL)", name="ck_pursuit_gap_single_target"),
        CheckConstraint(f"coverage_state IN {COVERAGE_STATES!r}", name="ck_pursuit_gap_coverage"),
        CheckConstraint(
            "resolution_category IN ('COMPANY_EVIDENCE','PARTNER_FIRM','EXPERT','CLARIFICATION','HUMAN_INTERPRETATION')",
            name="ck_pursuit_gap_resolution",
        ),
        CheckConstraint("review_state IN ('PROVISIONAL','CONFIRMED','CORRECTED')", name="ck_pursuit_gap_review"),
        Index("ix_pursuit_gaps_run_state", "analysis_run_id", "coverage_state"),
    )


class AnalysisReviewAssertion(Base):
    """Append-only reviewer assertion; machine rows and quotes remain untouched."""

    __tablename__ = "pursuit_analysis_review_assertions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_runs.id", ondelete="RESTRICT"), nullable=False
    )
    target_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    requirement_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_requirements.id", ondelete="RESTRICT"))
    position_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_positions.id", ondelete="RESTRICT"))
    gap_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_gaps.id", ondelete="RESTRICT"))
    actor_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    supersedes_assertion_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_review_assertions.id", ondelete="RESTRICT")
    )
    prior_coverage_state: Mapped[str | None] = mapped_column(String(40))
    new_coverage_state: Mapped[str] = mapped_column(String(40), nullable=False)
    prior_review_state: Mapped[str] = mapped_column(String(30), nullable=False)
    new_review_state: Mapped[str] = mapped_column(String(30), nullable=False)
    corrected_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["actor_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_analysis_assertion_actor_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint("target_kind IN ('REQUIREMENT','POSITION','GAP')", name="ck_analysis_assertion_kind"),
        CheckConstraint(
            "(target_kind = 'REQUIREMENT' AND requirement_id IS NOT NULL AND position_id IS NULL AND gap_id IS NULL) OR "
            "(target_kind = 'POSITION' AND position_id IS NOT NULL AND requirement_id IS NULL AND gap_id IS NULL) OR "
            "(target_kind = 'GAP' AND gap_id IS NOT NULL AND requirement_id IS NULL AND position_id IS NULL)",
            name="ck_analysis_assertion_single_target",
        ),
        CheckConstraint(f"new_coverage_state IN {COVERAGE_STATES!r}", name="ck_analysis_assertion_new_coverage"),
        CheckConstraint("prior_coverage_state IS NULL OR prior_coverage_state IN " + repr(COVERAGE_STATES), name="ck_analysis_assertion_prior_coverage"),
        CheckConstraint("prior_review_state IN ('PROVISIONAL','CONFIRMED','CORRECTED')", name="ck_analysis_assertion_prior_review"),
        CheckConstraint("new_review_state IN ('CONFIRMED','CORRECTED')", name="ck_analysis_assertion_new_review"),
        Index("ix_analysis_assertions_run_created", "analysis_run_id", "created_at"),
    )


class AnalysisItemLineage(Base):
    """Explicit reviewer-recognized identity between immutable analysis versions."""

    __tablename__ = "pursuit_analysis_item_lineage"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    prior_requirement_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_requirements.id", ondelete="RESTRICT"))
    current_requirement_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_requirements.id", ondelete="RESTRICT"))
    prior_position_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_positions.id", ondelete="RESTRICT"))
    current_position_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_positions.id", ondelete="RESTRICT"))
    actor_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["actor_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_analysis_lineage_actor_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(target_kind = 'REQUIREMENT' AND prior_requirement_id IS NOT NULL AND current_requirement_id IS NOT NULL "
            "AND prior_position_id IS NULL AND current_position_id IS NULL) OR "
            "(target_kind = 'POSITION' AND prior_position_id IS NOT NULL AND current_position_id IS NOT NULL "
            "AND prior_requirement_id IS NULL AND current_requirement_id IS NULL)",
            name="ck_analysis_lineage_shape",
        ),
        CheckConstraint(
            "(target_kind = 'REQUIREMENT' AND prior_requirement_id IS DISTINCT FROM current_requirement_id) OR "
            "(target_kind = 'POSITION' AND prior_position_id IS DISTINCT FROM current_position_id)",
            name="ck_analysis_lineage_distinct",
        ),
        UniqueConstraint("prior_requirement_id", "current_requirement_id", name="uq_analysis_requirement_lineage"),
        UniqueConstraint("prior_position_id", "current_position_id", name="uq_analysis_position_lineage"),
    )
