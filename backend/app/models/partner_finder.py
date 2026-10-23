"""P2 partner finder: introduction requests and prospective scenario members.

A request names a firm suggested from public award records (or asks Plasma to source an
expert) for one analysis Gap. The Plasma team works it by hand; nothing here holds contact
data for the suggested firm and nothing is ever sent to it. Every status change appends an
event the requesting organization can read (and an admin audit event).
"""

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
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

PARTNER_REQUEST_KINDS = ("INTRODUCTION", "EXPERT_SOURCING")
PARTNER_REQUEST_STATUSES = ("REQUESTED", "CONTACTED", "ACCEPTED", "DECLINED", "INTRODUCED")


class PartnerRequest(Base):
    __tablename__ = "partner_requests"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    pursuit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_runs.id", ondelete="RESTRICT"), nullable=False
    )
    gap_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_gaps.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    gap_category: Mapped[str] = mapped_column(String(20), nullable=False)
    gap_summary: Mapped[str] = mapped_column(Text, nullable=False)
    # The suggested firm as the award notices publish it; NULL for an expert-sourcing request.
    firm_key: Mapped[str | None] = mapped_column(String(700))
    firm_name: Mapped[str | None] = mapped_column(String(500))
    firm_country: Mapped[str | None] = mapped_column(String(120))
    # The suggestion as shown (rank, match, awards with notice links): public notice data only.
    suggestion_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    requester_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    requester_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="REQUESTED")
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_partner_request_id_organization"),
        ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_partner_request_pursuit_organization", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["requester_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_partner_request_requester_organization", ondelete="RESTRICT",
        ),
        CheckConstraint(f"kind IN {PARTNER_REQUEST_KINDS!r}", name="ck_partner_request_kind"),
        CheckConstraint("gap_category IN ('PARTNER_FIRM','EXPERT')", name="ck_partner_request_gap_category"),
        CheckConstraint(f"status IN {PARTNER_REQUEST_STATUSES!r}", name="ck_partner_request_status"),
        CheckConstraint(
            "(kind = 'INTRODUCTION' AND firm_key IS NOT NULL AND length(trim(firm_name)) >= 2) OR "
            "(kind = 'EXPERT_SOURCING' AND firm_key IS NULL AND firm_name IS NULL AND gap_category = 'EXPERT')",
            name="ck_partner_request_target",
        ),
        CheckConstraint("note IS NULL OR char_length(note) <= 2000", name="ck_partner_request_note"),
        CheckConstraint("jsonb_typeof(suggestion_snapshot) = 'object'", name="ck_partner_request_snapshot"),
        Index(
            "uq_partner_request_gap_firm", "organization_id", "gap_id", "firm_key", unique=True,
            postgresql_where=text("kind = 'INTRODUCTION'"),
        ),
        Index(
            "uq_partner_request_gap_sourcing", "organization_id", "gap_id", unique=True,
            postgresql_where=text("kind = 'EXPERT_SOURCING'"),
        ),
        Index("ix_partner_requests_pursuit", "organization_id", "pursuit_id", "created_at"),
        Index("ix_partner_requests_status", "status", "created_at"),
    )


class PartnerRequestEvent(Base):
    """Append-only status history, readable by the requesting organization."""

    __tablename__ = "partner_request_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Shown to the requesting organization ("Spoke to their director; they will reply by Friday").
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "organization_id"], ["partner_requests.id", "partner_requests.organization_id"],
            name="fk_partner_request_event_request", ondelete="RESTRICT",
        ),
        CheckConstraint(f"to_status IN {PARTNER_REQUEST_STATUSES!r}", name="ck_partner_request_event_to"),
        CheckConstraint("message IS NULL OR char_length(message) <= 2000", name="ck_partner_request_event_message"),
        Index("ix_partner_request_events_request", "request_id", "created_at"),
    )


class TeamScenarioProspectiveMember(Base):
    """An accepted introduction added to a team scenario as a JV member not yet confirmed.

    Kept beside the sealed revisions: it never counts as evidence or coverage in an
    assessment, it only shows which Gaps the firm would close if it joins.
    """

    __tablename__ = "team_scenario_prospective_members"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scenario_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    partner_request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    display_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    added_by_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["scenario_id", "organization_id"], ["team_scenarios.id", "team_scenarios.organization_id"],
            name="fk_prospective_member_scenario", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["partner_request_id", "organization_id"], ["partner_requests.id", "partner_requests.organization_id"],
            name="fk_prospective_member_request", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["added_by_membership_id", "organization_id"], ["memberships.id", "memberships.organization_id"],
            name="fk_prospective_member_actor", ondelete="RESTRICT",
        ),
        Index(
            "uq_prospective_member_active", "scenario_id", "partner_request_id", unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index("ix_prospective_members_scenario", "scenario_id", "created_at"),
    )
