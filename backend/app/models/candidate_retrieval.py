"""W5 reusable candidate authorities and immutable gap retrieval history."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


DATA_SCOPES = ("ORGANIZATION_PRIVATE", "NETWORK_SHARED")
EVIDENCE_STATES = ("VERIFIED", "REVIEWED", "UNVERIFIED", "EVIDENCE_MISSING")
QUALIFICATION_STATES = (
    "SUPPORTED_BY_EVIDENCE",
    "PARTIAL",
    "EVIDENCE_MISSING",
    "NEEDS_REVIEW",
    "NOT_RELEVANT",
)


class Firm(Base):
    """Reusable candidate firm, deliberately separate from tenant Organization."""

    __tablename__ = "candidate_firms"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(30), nullable=False)
    owner_organization_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    # Set only on the organization's own firm (its "self firm"); NULL on every candidate.
    organization_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_candidate_firm_self_organization", ondelete="RESTRICT"),
    )
    canonical_name: Mapped[str] = mapped_column(String(500), nullable=False)
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(500))
    country: Mapped[str | None] = mapped_column(String(150))
    regions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    services: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    capabilities: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    sectors: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_state: Mapped[str] = mapped_column(String(30), nullable=False)
    network_permission_basis: Mapped[str | None] = mapped_column(Text)
    private_notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    references: Mapped[list["ProjectReference"]] = relationship(
        "ProjectReference", back_populates="firm", passive_deletes=True, order_by="ProjectReference.created_at"
    )

    __table_args__ = (
        CheckConstraint(f"scope IN {DATA_SCOPES!r}", name="ck_candidate_firm_scope"),
        CheckConstraint(f"evidence_state IN {EVIDENCE_STATES!r}", name="ck_candidate_firm_evidence"),
        CheckConstraint("source_type IN ('MANUAL','EXPLICIT_IMPORT')", name="ck_candidate_firm_source"),
        CheckConstraint(
            "(scope = 'ORGANIZATION_PRIVATE' AND owner_organization_id IS NOT NULL) OR "
            "(scope = 'NETWORK_SHARED' AND owner_organization_id IS NULL "
            "AND length(trim(network_permission_basis)) >= 3)",
            name="ck_candidate_firm_scope_owner",
        ),
        CheckConstraint(
            "organization_id IS NULL OR "
            "(scope = 'ORGANIZATION_PRIVATE' AND owner_organization_id = organization_id)",
            name="ck_candidate_firm_self_private",
        ),
        Index("ix_candidate_firms_visibility", "scope", "owner_organization_id", "updated_at"),
        Index(
            "uq_candidate_firms_self_organization", "organization_id", unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
        ),
    )


class ProjectReference(Base):
    """Evidence-bearing project or contract fact for one Firm.

    The recorded facts are immutable (database trigger): an edit writes a new row
    whose supersedes_reference_id names the old one and archives the old row, so
    matches, scenarios and evidence packs that cite a reference id keep their facts.
    """

    __tablename__ = "candidate_project_references"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    firm_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("candidate_firms.id", ondelete="RESTRICT"), nullable=False
    )
    project_name: Mapped[str] = mapped_column(String(700), nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(500))
    country: Mapped[str | None] = mapped_column(String(150))
    service: Mapped[str | None] = mapped_column(String(300))
    sector: Mapped[str | None] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    contract_share_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    contract_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    contract_currency: Mapped[str | None] = mapped_column(String(3))
    value_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    completion_date: Mapped[date | None] = mapped_column(Date)
    completion_state: Mapped[str] = mapped_column(String(20), nullable=False)
    relevant_scope: Mapped[str | None] = mapped_column(Text)
    evidence_provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_state: Mapped[str] = mapped_column(String(30), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_candidate_reference_archived_by", ondelete="RESTRICT"),
    )
    supersedes_reference_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "candidate_project_references.id", name="fk_candidate_reference_supersedes", ondelete="RESTRICT"
        ),
    )

    firm: Mapped[Firm] = relationship("Firm", back_populates="references")

    __table_args__ = (
        CheckConstraint(
            "supersedes_reference_id IS NULL OR supersedes_reference_id <> id",
            name="ck_candidate_reference_supersedes_other",
        ),
        Index(
            "uq_candidate_references_supersedes", "supersedes_reference_id", unique=True,
            postgresql_where=text("supersedes_reference_id IS NOT NULL"),
        ),
        CheckConstraint(
            "role IN ('LEAD','JV_MEMBER','CONSORTIUM_MEMBER','SUBCONSULTANT','SUBCONTRACTOR','OTHER','UNKNOWN')",
            name="ck_candidate_reference_role",
        ),
        CheckConstraint(
            "contract_share_percent IS NULL OR (contract_share_percent >= 0 AND contract_share_percent <= 100)",
            name="ck_candidate_reference_share",
        ),
        CheckConstraint("contract_value IS NULL OR contract_value >= 0", name="ck_candidate_reference_value"),
        CheckConstraint(
            "value_basis IN ('FIRM_SHARE','CONSORTIUM_TOTAL','CONTRACT_TOTAL','UNKNOWN')",
            name="ck_candidate_reference_value_basis",
        ),
        CheckConstraint(
            "(contract_value IS NULL AND contract_currency IS NULL) OR "
            "(contract_value IS NOT NULL AND contract_currency IS NOT NULL AND value_basis <> 'UNKNOWN')",
            name="ck_candidate_reference_value_truth",
        ),
        CheckConstraint(
            "completion_state IN ('COMPLETED','ONGOING','NOT_COMPLETED','UNKNOWN')",
            name="ck_candidate_reference_completion",
        ),
        CheckConstraint(
            "completion_date IS NULL OR start_date IS NULL OR completion_date >= start_date",
            name="ck_candidate_reference_dates",
        ),
        CheckConstraint(f"evidence_state IN {EVIDENCE_STATES!r}", name="ck_candidate_reference_evidence"),
        Index("ix_candidate_references_firm_evidence", "firm_id", "evidence_state", "completion_state"),
    )


class Expert(Base):
    """Reusable candidate expert; never inferred from generic contacts or project leadership."""

    __tablename__ = "candidate_experts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(30), nullable=False)
    owner_organization_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    qualifications: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    languages: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    specializations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    consent_state: Mapped[str] = mapped_column(String(40), nullable=False)
    network_permission_basis: Mapped[str | None] = mapped_column(Text)
    evidence_state: Mapped[str] = mapped_column(String(30), nullable=False)
    source_provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    private_notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    cv_versions: Mapped[list["CVVersion"]] = relationship(
        "CVVersion", back_populates="expert", passive_deletes=True, order_by="CVVersion.version_number"
    )

    __table_args__ = (
        CheckConstraint(f"scope IN {DATA_SCOPES!r}", name="ck_candidate_expert_scope"),
        CheckConstraint(f"evidence_state IN {EVIDENCE_STATES!r}", name="ck_candidate_expert_evidence"),
        CheckConstraint(
            "consent_state IN ('NOT_REQUIRED_PRIVATE','EXPLICIT_CONSENT','CONTRACTUAL_BASIS','WITHDRAWN','UNKNOWN')",
            name="ck_candidate_expert_consent",
        ),
        CheckConstraint(
            "(scope = 'ORGANIZATION_PRIVATE' AND owner_organization_id IS NOT NULL) OR "
            "(scope = 'NETWORK_SHARED' AND owner_organization_id IS NULL "
            "AND consent_state IN ('EXPLICIT_CONSENT','CONTRACTUAL_BASIS') "
            "AND length(trim(network_permission_basis)) >= 3)",
            name="ck_candidate_expert_scope_consent",
        ),
        Index("ix_candidate_experts_visibility", "scope", "owner_organization_id", "updated_at"),
    )


class CVVersion(Base):
    """Immutable structured CV facts and provenance; no reusable CV bytes live here."""

    __tablename__ = "candidate_cv_versions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    expert_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("candidate_experts.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    education: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    qualifications: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    certifications: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    assignments: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    languages: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_state: Mapped[str] = mapped_column(String(30), nullable=False)
    structured_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    expert: Mapped[Expert] = relationship("Expert", back_populates="cv_versions")

    __table_args__ = (
        UniqueConstraint("expert_id", "version_number", name="uq_candidate_cv_version_number"),
        CheckConstraint("version_number >= 1", name="ck_candidate_cv_version_positive"),
        CheckConstraint(f"evidence_state IN {EVIDENCE_STATES!r}", name="ck_candidate_cv_evidence"),
        CheckConstraint("structured_sha256 ~ '^[0-9a-f]{64}$'", name="ck_candidate_cv_sha"),
        Index("ix_candidate_cv_expert_created", "expert_id", "created_at"),
    )


class CandidateSearchRun(Base):
    """Immutable completed retrieval bound to one effective reviewed W4 Gap."""

    __tablename__ = "candidate_search_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pursuit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_runs.id", ondelete="RESTRICT"), nullable=False
    )
    gap_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_gaps.id", ondelete="RESTRICT"), nullable=False
    )
    target_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    requirement_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_requirements.id", ondelete="RESTRICT")
    )
    position_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_positions.id", ondelete="RESTRICT")
    )
    review_assertion_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_review_assertions.id", ondelete="RESTRICT"), nullable=False
    )
    effective_coverage_state: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_review_state: Mapped[str] = mapped_column(String(30), nullable=False)
    resolution_category: Mapped[str] = mapped_column(String(40), nullable=False)
    contribution_rule: Mapped[str] = mapped_column(Text, nullable=False)
    search_version: Mapped[str] = mapped_column(String(100), nullable=False)
    search_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    matches: Mapped[list["CandidateMatch"]] = relationship(
        "CandidateMatch", back_populates="search_run", passive_deletes=True, order_by="CandidateMatch.retrieval_rank"
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_candidate_search_pursuit_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_candidate_search_actor_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(target_kind = 'FIRM' AND requirement_id IS NOT NULL AND position_id IS NULL "
            "AND resolution_category = 'PARTNER_FIRM') OR "
            "(target_kind = 'EXPERT' AND position_id IS NOT NULL AND requirement_id IS NULL "
            "AND resolution_category = 'EXPERT')",
            name="ck_candidate_search_target",
        ),
        CheckConstraint("effective_review_state IN ('CONFIRMED','CORRECTED')", name="ck_candidate_search_reviewed"),
        CheckConstraint("effective_coverage_state <> 'NEEDS_INTERPRETATION'", name="ck_candidate_search_interpreted"),
        CheckConstraint("status = 'COMPLETED'", name="ck_candidate_search_completed"),
        CheckConstraint("result_limit BETWEEN 1 AND 20", name="ck_candidate_search_limit"),
        Index("ix_candidate_search_pursuit_created", "organization_id", "pursuit_id", "created_at"),
        Index("ix_candidate_search_gap_created", "gap_id", "created_at"),
    )


class CandidateMatch(Base):
    """Immutable qualification assessment for one retrieved Firm or Expert."""

    __tablename__ = "candidate_matches"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    candidate_search_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("candidate_search_runs.id", ondelete="RESTRICT"), nullable=False
    )
    gap_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_gaps.id", ondelete="RESTRICT"), nullable=False
    )
    firm_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("candidate_firms.id", ondelete="RESTRICT")
    )
    expert_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("candidate_experts.id", ondelete="RESTRICT")
    )
    proposed_contribution: Mapped[str] = mapped_column(Text, nullable=False)
    strongest_evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    relevant_evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    missing_or_weak_evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    qualification_state: Mapped[str] = mapped_column(String(40), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    retrieval_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    search_run: Mapped[CandidateSearchRun] = relationship("CandidateSearchRun", back_populates="matches")

    __table_args__ = (
        CheckConstraint("(firm_id IS NOT NULL) <> (expert_id IS NOT NULL)", name="ck_candidate_match_single_candidate"),
        CheckConstraint(f"qualification_state IN {QUALIFICATION_STATES!r}", name="ck_candidate_match_qualification"),
        CheckConstraint("retrieval_rank BETWEEN 1 AND 20", name="ck_candidate_match_rank"),
        UniqueConstraint("candidate_search_run_id", "firm_id", name="uq_candidate_match_run_firm"),
        UniqueConstraint("candidate_search_run_id", "expert_id", name="uq_candidate_match_run_expert"),
        UniqueConstraint("id", "gap_id", name="uq_candidate_match_id_gap"),
        Index("ix_candidate_matches_run_rank", "candidate_search_run_id", "retrieval_rank"),
    )


class CandidateReviewDecision(Base):
    """Append-only human decision about a CandidateMatch."""

    __tablename__ = "candidate_review_decisions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    candidate_search_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("candidate_search_runs.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_match_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("candidate_matches.id", ondelete="RESTRICT"), nullable=False
    )
    actor_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    supersedes_decision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("candidate_review_decisions.id", ondelete="RESTRICT")
    )
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    corrected_contribution: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "candidate_match_id", name="uq_candidate_review_id_match"),
        ForeignKeyConstraint(
            ["actor_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_candidate_review_actor_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "decision IN ('SHORTLISTED','REJECTED','MORE_EVIDENCE_REQUESTED','IRRELEVANT','CONTRIBUTION_CORRECTED')",
            name="ck_candidate_review_decision",
        ),
        CheckConstraint(
            "(decision = 'CONTRIBUTION_CORRECTED' AND length(trim(corrected_contribution)) >= 3) OR "
            "(decision <> 'CONTRIBUTION_CORRECTED' AND corrected_contribution IS NULL)",
            name="ck_candidate_review_correction",
        ),
        Index("ix_candidate_reviews_match_created", "candidate_match_id", "created_at"),
    )

