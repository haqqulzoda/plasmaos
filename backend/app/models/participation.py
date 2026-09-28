"""W6 organization-private participation authority and append-only facts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


CONFIRMATION_SOURCES = (
    "DIRECT_EMAIL", "CALL", "MEETING", "SIGNED_DOCUMENT",
    "OPERATOR_RECORDED", "CUSTOMER_RECORDED", "OTHER",
)
AVAILABILITY_STATES = ("UNKNOWN", "TENTATIVE", "AVAILABLE", "PARTIALLY_AVAILABLE", "UNAVAILABLE")
INTEREST_STATES = ("UNKNOWN", "INTERESTED", "CONDITIONAL", "DECLINED")
PARTICIPATION_STATES = ("UNCONFIRMED", "TENTATIVE", "CONFIRMED", "DECLINED", "WITHDRAWN")


class CandidateParticipationRecord(Base):
    """Immutable organization-private root bound to one exact shortlisted W5 match."""

    __tablename__ = "candidate_participation_records"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pursuit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    candidate_match_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    shortlist_decision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    proposed_contribution_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("candidate_match_id", name="uq_candidate_participation_match"),
        UniqueConstraint("id", "organization_id", name="uq_participation_record_id_organization"),
        UniqueConstraint("id", "candidate_match_id", name="uq_participation_record_id_match"),
        ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_participation_record_pursuit_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_participation_record_actor_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["shortlist_decision_id", "candidate_match_id"],
            ["candidate_review_decisions.id", "candidate_review_decisions.candidate_match_id"],
            name="fk_participation_record_shortlist_match", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["candidate_match_id"], ["candidate_matches.id"],
            name="fk_participation_record_match", ondelete="RESTRICT",
        ),
        Index("ix_participation_records_pursuit_created", "organization_id", "pursuit_id", "created_at"),
    )


class CandidateAvailabilityFact(Base):
    """Immutable contextual availability observation."""

    __tablename__ = "candidate_availability_facts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    participation_record_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    window_start: Mapped[date | None] = mapped_column(Date)
    window_end: Mapped[date | None] = mapped_column(Date)
    effort_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    capacity_description: Mapped[str | None] = mapped_column(Text)
    location_travel_constraints: Mapped[str | None] = mapped_column(Text)
    confirmation_source: Mapped[str] = mapped_column(String(40), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supporting_document_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(Text)
    supersedes_fact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    actor_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "participation_record_id", name="uq_availability_fact_id_record"),
        ForeignKeyConstraint(
            ["participation_record_id", "organization_id"],
            ["candidate_participation_records.id", "candidate_participation_records.organization_id"],
            name="fk_availability_record_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_availability_actor_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["supporting_document_version_id", "organization_id"],
            ["private_document_versions.id", "private_document_versions.organization_id"],
            name="fk_availability_document_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["supersedes_fact_id", "participation_record_id"],
            ["candidate_availability_facts.id", "candidate_availability_facts.participation_record_id"],
            name="fk_availability_supersedes_same_record", ondelete="RESTRICT",
        ),
        CheckConstraint(f"status IN {AVAILABILITY_STATES!r}", name="ck_availability_status"),
        CheckConstraint(
            "(window_start IS NULL AND window_end IS NULL) OR "
            "(window_start IS NOT NULL AND window_end IS NOT NULL AND window_end >= window_start)",
            name="ck_availability_window",
        ),
        CheckConstraint("effort_percent IS NULL OR (effort_percent >= 0 AND effort_percent <= 100)", name="ck_availability_effort"),
        CheckConstraint(
            "status NOT IN ('TENTATIVE','AVAILABLE','PARTIALLY_AVAILABLE') OR valid_until IS NOT NULL",
            name="ck_availability_positive_freshness",
        ),
        CheckConstraint(f"confirmation_source IN {CONFIRMATION_SOURCES!r}", name="ck_availability_source"),
        Index("ix_availability_record_created", "participation_record_id", "created_at"),
    )


class CandidateInterestFact(Base):
    """Immutable willingness observation, separate from availability."""

    __tablename__ = "candidate_interest_facts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    participation_record_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    confirmation_source: Mapped[str] = mapped_column(String(40), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    conditions: Mapped[str | None] = mapped_column(Text)
    supporting_document_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(Text)
    supersedes_fact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    actor_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "participation_record_id", name="uq_interest_fact_id_record"),
        ForeignKeyConstraint(
            ["participation_record_id", "organization_id"],
            ["candidate_participation_records.id", "candidate_participation_records.organization_id"],
            name="fk_interest_record_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_interest_actor_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["supporting_document_version_id", "organization_id"],
            ["private_document_versions.id", "private_document_versions.organization_id"],
            name="fk_interest_document_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["supersedes_fact_id", "participation_record_id"],
            ["candidate_interest_facts.id", "candidate_interest_facts.participation_record_id"],
            name="fk_interest_supersedes_same_record", ondelete="RESTRICT",
        ),
        CheckConstraint(f"status IN {INTEREST_STATES!r}", name="ck_interest_status"),
        CheckConstraint("status <> 'CONDITIONAL' OR length(trim(conditions)) >= 3", name="ck_interest_conditions"),
        CheckConstraint(f"confirmation_source IN {CONFIRMATION_SOURCES!r}", name="ck_interest_source"),
        Index("ix_interest_record_created", "participation_record_id", "created_at"),
    )


class CandidateParticipationDecision(Base):
    """Immutable recorded participation decision and confirmation provenance."""

    __tablename__ = "candidate_participation_decisions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    participation_record_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    confirmation_source: Mapped[str] = mapped_column(String(40), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reconfirm_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    conditions_summary: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    supporting_document_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    supersedes_decision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    actor_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "participation_record_id", name="uq_participation_decision_id_record"),
        ForeignKeyConstraint(
            ["participation_record_id", "organization_id"],
            ["candidate_participation_records.id", "candidate_participation_records.organization_id"],
            name="fk_participation_decision_record_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_participation_decision_actor_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["supporting_document_version_id", "organization_id"],
            ["private_document_versions.id", "private_document_versions.organization_id"],
            name="fk_participation_decision_document_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["supersedes_decision_id", "participation_record_id"],
            ["candidate_participation_decisions.id", "candidate_participation_decisions.participation_record_id"],
            name="fk_participation_decision_supersedes_same_record", ondelete="RESTRICT",
        ),
        CheckConstraint(f"state IN {PARTICIPATION_STATES!r}", name="ck_participation_decision_state"),
        CheckConstraint("state NOT IN ('TENTATIVE','CONFIRMED') OR reconfirm_by IS NOT NULL", name="ck_participation_reconfirm"),
        CheckConstraint("state NOT IN ('DECLINED','WITHDRAWN') OR length(trim(reason)) >= 3", name="ck_participation_terminal_reason"),
        CheckConstraint(f"confirmation_source IN {CONFIRMATION_SOURCES!r}", name="ck_participation_decision_source"),
        Index("ix_participation_decisions_record_created", "participation_record_id", "created_at"),
    )
