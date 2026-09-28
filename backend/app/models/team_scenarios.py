"""W7 organization-private, immutable evidence-backed team scenarios."""

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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


SCENARIO_ASSESSMENTS = ("DRAFT", "NEEDS_REVIEW", "BLOCKED", "VIABLE")
GAP_ASSESSMENTS = ("COVERED", "PARTIAL", "UNRESOLVED", "BLOCKED", "NEEDS_REVIEW")
SCENARIO_DECISIONS = ("PREFERRED", "REJECTED", "APPROVED_FOR_PROPOSAL")
ISSUE_SEVERITIES = ("REVIEW", "BLOCKING")
PARTICIPANT_TYPES = ("PARTNER_FIRM", "EXPERT")


class TeamScenario(Base):
    """Durable scenario identity; composition lives only in revisions."""

    __tablename__ = "team_scenarios"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pursuit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    created_by_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_team_scenario_id_organization"),
        ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_team_scenario_pursuit_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_team_scenario_actor_organization", ondelete="RESTRICT",
        ),
        CheckConstraint("length(trim(title)) BETWEEN 1 AND 300", name="ck_team_scenario_title"),
        Index("ix_team_scenarios_pursuit_created", "organization_id", "pursuit_id", "created_at"),
    )


class TeamScenarioRevision(Base):
    """Immutable composition and deterministic assessment snapshot."""

    __tablename__ = "team_scenario_revisions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scenario_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_runs.id", ondelete="RESTRICT"), nullable=False
    )
    analysis_pack_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_packs.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    selection_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    assessment_schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    assessment_state: Mapped[str] = mapped_column(String(30), nullable=False)
    gap_count: Mapped[int] = mapped_column(Integer, nullable=False)
    covered_gap_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unresolved_gap_count: Mapped[int] = mapped_column(Integer, nullable=False)
    participant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed_participant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    blocking_issue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unresolved_later_stage_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_provenance_count: Mapped[int] = mapped_column(Integer, nullable=False)
    private_provenance_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("scenario_id", "version_number", name="uq_team_scenario_revision_version"),
        UniqueConstraint("id", "organization_id", name="uq_team_scenario_revision_id_organization"),
        UniqueConstraint("id", "scenario_id", "organization_id", name="uq_team_revision_id_scenario_organization"),
        UniqueConstraint("id", "analysis_run_id", name="uq_team_revision_id_analysis"),
        ForeignKeyConstraint(
            ["scenario_id", "organization_id"], ["team_scenarios.id", "team_scenarios.organization_id"],
            name="fk_team_revision_scenario_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"], ["memberships.id", "memberships.organization_id"],
            name="fk_team_revision_actor_organization", ondelete="RESTRICT",
        ),
        CheckConstraint("version_number >= 1", name="ck_team_revision_version"),
        CheckConstraint("selection_sha256 ~ '^[0-9a-f]{64}$'", name="ck_team_revision_selection_sha"),
        CheckConstraint(f"assessment_state IN {SCENARIO_ASSESSMENTS!r}", name="ck_team_revision_assessment"),
        CheckConstraint(
            "gap_count >= 0 AND covered_gap_count >= 0 AND unresolved_gap_count >= 0 "
            "AND participant_count >= 0 AND confirmed_participant_count >= 0 "
            "AND issue_count >= 0 AND blocking_issue_count >= 0 AND unresolved_later_stage_count >= 0 "
            "AND source_provenance_count >= 0 AND private_provenance_count >= 0",
            name="ck_team_revision_counts",
        ),
        Index("ix_team_revisions_scenario_version", "scenario_id", "version_number"),
    )


class TeamScenarioParticipant(Base):
    """One unique Firm or Expert identity within a revision."""

    __tablename__ = "team_scenario_participants"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    participant_type: Mapped[str] = mapped_column(String(30), nullable=False)
    firm_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("candidate_firms.id", ondelete="RESTRICT"))
    expert_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("candidate_experts.id", ondelete="RESTRICT"))
    display_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "revision_id", name="uq_team_participant_id_revision"),
        UniqueConstraint("revision_id", "firm_id", name="uq_team_participant_revision_firm"),
        UniqueConstraint("revision_id", "expert_id", name="uq_team_participant_revision_expert"),
        ForeignKeyConstraint(
            ["revision_id", "organization_id"],
            ["team_scenario_revisions.id", "team_scenario_revisions.organization_id"],
            name="fk_team_participant_revision_organization", ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(participant_type = 'PARTNER_FIRM' AND firm_id IS NOT NULL AND expert_id IS NULL) OR "
            "(participant_type = 'EXPERT' AND expert_id IS NOT NULL AND firm_id IS NULL)",
            name="ck_team_participant_identity",
        ),
        Index("ix_team_participants_revision", "revision_id"),
    )


class TeamScenarioContribution(Base):
    """Exact W4/W5/W6 lineage and facts used for one proposed contribution."""

    __tablename__ = "team_scenario_contributions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    participant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    candidate_match_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    participation_record_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    gap_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_gaps.id", ondelete="RESTRICT"), nullable=False)
    requirement_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_requirements.id", ondelete="RESTRICT"))
    position_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_positions.id", ondelete="RESTRICT"))
    shortlist_decision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    shortlist_decision_state_snapshot: Mapped[str] = mapped_column(String(30), nullable=False)
    proposed_contribution_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    contribution_rule_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    qualification_state_snapshot: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_evidence_state_snapshot: Mapped[str] = mapped_column(String(30), nullable=False)
    evidence_identities_snapshot: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    strongest_evidence_snapshot: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    availability_fact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    availability_recorded_state: Mapped[str | None] = mapped_column(String(30))
    availability_effective_state: Mapped[str | None] = mapped_column(String(30))
    availability_window_start: Mapped[date | None] = mapped_column(Date)
    availability_window_end: Mapped[date | None] = mapped_column(Date)
    availability_effort_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    availability_capacity_snapshot: Mapped[str | None] = mapped_column(Text)
    availability_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interest_fact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    interest_recorded_state: Mapped[str | None] = mapped_column(String(30))
    interest_effective_state: Mapped[str | None] = mapped_column(String(30))
    interest_conditions_snapshot: Mapped[str | None] = mapped_column(Text)
    participation_decision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    participation_recorded_state: Mapped[str | None] = mapped_column(String(30))
    participation_effective_state: Mapped[str | None] = mapped_column(String(30))
    confirmation_source_snapshot: Mapped[str | None] = mapped_column(String(40))
    confirmation_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconfirm_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_conditions_snapshot: Mapped[str | None] = mapped_column(Text)
    assignment_dates_snapshot: Mapped[str | None] = mapped_column(Text)
    assignment_window_result: Mapped[str] = mapped_column(String(30), nullable=False)
    upstream_stale_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("revision_id", "candidate_match_id", name="uq_team_contribution_revision_match"),
        UniqueConstraint("id", "revision_id", name="uq_team_contribution_id_revision"),
        ForeignKeyConstraint(
            ["revision_id", "organization_id"],
            ["team_scenario_revisions.id", "team_scenario_revisions.organization_id"],
            name="fk_team_contribution_revision_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["revision_id", "analysis_run_id"],
            ["team_scenario_revisions.id", "team_scenario_revisions.analysis_run_id"],
            name="fk_team_contribution_revision_analysis", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["participant_id", "revision_id"],
            ["team_scenario_participants.id", "team_scenario_participants.revision_id"],
            name="fk_team_contribution_participant_revision", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["participation_record_id", "candidate_match_id"],
            ["candidate_participation_records.id", "candidate_participation_records.candidate_match_id"],
            name="fk_team_contribution_participation_match", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["candidate_match_id", "gap_id"],
            ["candidate_matches.id", "candidate_matches.gap_id"],
            name="fk_team_contribution_match_gap", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["gap_id", "analysis_run_id"],
            ["pursuit_analysis_gaps.id", "pursuit_analysis_gaps.analysis_run_id"],
            name="fk_team_contribution_gap_analysis", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["shortlist_decision_id", "candidate_match_id"],
            ["candidate_review_decisions.id", "candidate_review_decisions.candidate_match_id"],
            name="fk_team_contribution_shortlist_match", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["availability_fact_id", "participation_record_id"],
            ["candidate_availability_facts.id", "candidate_availability_facts.participation_record_id"],
            name="fk_team_contribution_availability_record", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["interest_fact_id", "participation_record_id"],
            ["candidate_interest_facts.id", "candidate_interest_facts.participation_record_id"],
            name="fk_team_contribution_interest_record", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["participation_decision_id", "participation_record_id"],
            ["candidate_participation_decisions.id", "candidate_participation_decisions.participation_record_id"],
            name="fk_team_contribution_decision_record", ondelete="RESTRICT",
        ),
        CheckConstraint("(requirement_id IS NOT NULL) <> (position_id IS NOT NULL)", name="ck_team_contribution_target"),
        CheckConstraint("assignment_window_result IN ('FULL_WINDOW','PARTIAL_WINDOW','NO_OVERLAP','UNKNOWN_DATES')", name="ck_team_contribution_window"),
        CheckConstraint("availability_effort_percent IS NULL OR (availability_effort_percent >= 0 AND availability_effort_percent <= 100)", name="ck_team_contribution_effort"),
        Index("ix_team_contributions_revision_gap", "revision_id", "gap_id"),
    )


class ScenarioGapAssessment(Base):
    """Immutable W7 outcome for one exact W4 Gap."""

    __tablename__ = "team_scenario_gap_assessments"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    gap_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_gaps.id", ondelete="RESTRICT"), nullable=False)
    requirement_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_requirements.id", ondelete="RESTRICT"))
    position_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_positions.id", ondelete="RESTRICT"))
    review_assertion_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_review_assertions.id", ondelete="RESTRICT")
    )
    w4_coverage_state_snapshot: Mapped[str] = mapped_column(String(40), nullable=False)
    w4_review_state_snapshot: Mapped[str] = mapped_column(String(30), nullable=False)
    resolution_category_snapshot: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    is_current_stage: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_blocking: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rationale_code: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("revision_id", "gap_id", name="uq_team_gap_assessment_revision_gap"),
        ForeignKeyConstraint(
            ["revision_id", "organization_id"],
            ["team_scenario_revisions.id", "team_scenario_revisions.organization_id"],
            name="fk_team_gap_revision_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["revision_id", "analysis_run_id"],
            ["team_scenario_revisions.id", "team_scenario_revisions.analysis_run_id"],
            name="fk_team_gap_revision_analysis", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["gap_id", "analysis_run_id"],
            ["pursuit_analysis_gaps.id", "pursuit_analysis_gaps.analysis_run_id"],
            name="fk_team_gap_analysis", ondelete="RESTRICT",
        ),
        CheckConstraint("(requirement_id IS NOT NULL) <> (position_id IS NOT NULL)", name="ck_team_gap_target"),
        CheckConstraint(f"state IN {GAP_ASSESSMENTS!r}", name="ck_team_gap_state"),
        Index("ix_team_gap_assessments_revision", "revision_id", "state"),
    )


class ScenarioIssue(Base):
    """Structured immutable assessment finding."""

    __tablename__ = "team_scenario_issues"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    issue_code: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    gap_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_gaps.id", ondelete="RESTRICT"))
    participant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    contribution_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "organization_id"],
            ["team_scenario_revisions.id", "team_scenario_revisions.organization_id"],
            name="fk_team_issue_revision_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["participant_id", "revision_id"],
            ["team_scenario_participants.id", "team_scenario_participants.revision_id"],
            name="fk_team_issue_participant_revision", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["contribution_id", "revision_id"],
            ["team_scenario_contributions.id", "team_scenario_contributions.revision_id"],
            name="fk_team_issue_contribution_revision", ondelete="RESTRICT",
        ),
        CheckConstraint(f"severity IN {ISSUE_SEVERITIES!r}", name="ck_team_issue_severity"),
        CheckConstraint("length(trim(issue_code)) >= 3", name="ck_team_issue_code"),
        Index("ix_team_issues_revision", "revision_id", "severity", "issue_code"),
    )


class TeamScenarioDecision(Base):
    """Append-only human decision about one exact scenario revision."""

    __tablename__ = "team_scenario_decisions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scenario_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    explicit_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "id", "revision_id", "organization_id",
            name="uq_team_decision_id_revision_organization",
        ),
        ForeignKeyConstraint(
            ["scenario_id", "organization_id"], ["team_scenarios.id", "team_scenarios.organization_id"],
            name="fk_team_decision_scenario_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["revision_id", "scenario_id", "organization_id"],
            ["team_scenario_revisions.id", "team_scenario_revisions.scenario_id", "team_scenario_revisions.organization_id"],
            name="fk_team_decision_revision_scenario_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_membership_id", "organization_id"], ["memberships.id", "memberships.organization_id"],
            name="fk_team_decision_actor_organization", ondelete="RESTRICT",
        ),
        CheckConstraint(f"decision IN {SCENARIO_DECISIONS!r}", name="ck_team_decision_value"),
        CheckConstraint("length(trim(reason)) >= 3", name="ck_team_decision_reason"),
        CheckConstraint("decision <> 'APPROVED_FOR_PROPOSAL' OR explicit_confirmation", name="ck_team_decision_approval_confirmation"),
        Index("ix_team_decisions_scenario_created", "scenario_id", "created_at"),
    )
