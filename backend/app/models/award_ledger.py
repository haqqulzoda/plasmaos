"""Sprint 1: award ledger v0. Public contract-award notices and one row per bidder.

Both tables are append-only (a trigger rejects UPDATE and DELETE). A notice is stored once
per content hash: a re-published notice with changed text is a new snapshot with its own
rows, and reads use the newest snapshot of each notice.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

AWARD_LENDERS = ("WORLD_BANK", "ADB", "EBRD")
AWARD_OUTCOME_STATUSES = ("AWARDED", "EVALUATED", "REJECTED", "NOT_EVALUATED")


class AwardNoticeSnapshot(Base):
    """One retrieved version of a public award notice: raw text kept verbatim."""

    __tablename__ = "award_notice_snapshots"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    lender: Mapped[str] = mapped_column(String(20), nullable=False)
    notice_id: Mapped[str] = mapped_column(String(64), nullable=False)
    notice_url: Mapped[str] = mapped_column(String(500), nullable=False)
    notice_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notice_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    award_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    package_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    package_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    procurement_group: Mapped[str | None] = mapped_column(String(80), nullable=True)
    procurement_method: Mapped[str | None] = mapped_column(String(120), nullable=True)
    market_approach: Mapped[str | None] = mapped_column(String(80), nullable=True)
    contract_duration: Mapped[str | None] = mapped_column(String(60), nullable=True)
    sectors: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False)
    bidder_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("lender", "notice_id", "content_hash", name="uq_award_notice_snapshot_content"),
        CheckConstraint("lender IN ('WORLD_BANK','ADB','EBRD')", name="ck_award_notice_snapshot_lender"),
        CheckConstraint("parse_status IN ('PARSED','NO_BIDDERS')", name="ck_award_notice_snapshot_parse_status"),
        CheckConstraint("jsonb_typeof(sectors) = 'array'", name="ck_award_notice_snapshot_sectors"),
        Index("ix_award_notice_snapshots_lender_notice", "lender", "notice_id", "retrieved_at"),
        Index("ix_award_notice_snapshots_country_date", "country", "notice_date"),
    )


class AwardOutcome(Base):
    """One bidder in one bid of one notice snapshot. Joint-venture members share a bid."""

    __tablename__ = "award_outcomes"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("award_notice_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    lender: Mapped[str] = mapped_column(String(20), nullable=False)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notice_id: Mapped[str] = mapped_column(String(64), nullable=False)
    notice_url: Mapped[str] = mapped_column(String(500), nullable=False)
    notice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    award_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    package_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    package_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    procurement_group: Mapped[str | None] = mapped_column(String(80), nullable=True)
    procurement_method: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bid_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    member_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    bidder_name: Mapped[str] = mapped_column(String(500), nullable=False)
    bidder_name_normalized: Mapped[str] = mapped_column(String(500), nullable=False)
    bidder_source_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    bidder_country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bidder_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    evaluated_price_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    evaluated_price_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    evaluated_price_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), nullable=True)
    signed_contract_price_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signed_contract_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    signed_contract_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), nullable=True)
    bid_price_at_opening_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("snapshot_id", "bid_ordinal", "member_ordinal", name="uq_award_outcome_member"),
        CheckConstraint("lender IN ('WORLD_BANK','ADB','EBRD')", name="ck_award_outcome_lender"),
        CheckConstraint(
            "status IN ('AWARDED','EVALUATED','REJECTED','NOT_EVALUATED')", name="ck_award_outcome_status"
        ),
        CheckConstraint("bidder_kind IN ('FIRM','INDIVIDUAL')", name="ck_award_outcome_bidder_kind"),
        CheckConstraint(
            "bid_ordinal >= 1 AND member_ordinal >= 1 AND member_ordinal <= member_count",
            name="ck_award_outcome_ordinals",
        ),
        CheckConstraint("jsonb_typeof(scores) = 'object'", name="ck_award_outcome_scores"),
        Index("ix_award_outcomes_snapshot", "snapshot_id"),
        Index("ix_award_outcomes_country_status", "country", "status"),
        Index("ix_award_outcomes_bidder_source_id", "bidder_source_id"),
        Index("ix_award_outcomes_bidder_name_normalized", "bidder_name_normalized"),
    )
