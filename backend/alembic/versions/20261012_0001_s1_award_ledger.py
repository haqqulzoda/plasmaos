"""Sprint 1: award ledger v0 (public award notices and one row per bidder).

Additive and reversible: two append-only tables (a trigger rejects UPDATE and DELETE).

Revision ID: 20261012_0001_s1_award_ledger
Revises: 20261011_0001_r3_organization_record_events
Create Date: 2026-10-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261012_0001_s1_award_ledger"
down_revision: Union[str, None] = "20261011_0001_r3_organization_record_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPEND_ONLY_TABLES = ("award_notice_snapshots", "award_outcomes")


def upgrade() -> None:
    op.create_table(
        "award_notice_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lender", sa.String(length=20), nullable=False),
        sa.Column("notice_id", sa.String(length=64), nullable=False),
        sa.Column("notice_url", sa.String(length=500), nullable=False),
        sa.Column("notice_type", sa.String(length=80), nullable=True),
        sa.Column("notice_version", sa.String(length=20), nullable=True),
        sa.Column("notice_date", sa.Date(), nullable=True),
        sa.Column("award_date", sa.Date(), nullable=True),
        sa.Column("country", sa.String(length=120), nullable=True),
        sa.Column("project_id", sa.String(length=40), nullable=True),
        sa.Column("project_name", sa.String(length=500), nullable=True),
        sa.Column("package_reference", sa.String(length=200), nullable=True),
        sa.Column("package_title", sa.Text(), nullable=True),
        sa.Column("procurement_group", sa.String(length=80), nullable=True),
        sa.Column("procurement_method", sa.String(length=120), nullable=True),
        sa.Column("market_approach", sa.String(length=80), nullable=True),
        sa.Column("contract_duration", sa.String(length=60), nullable=True),
        sa.Column("sectors", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column(
            "raw_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=40), nullable=False),
        sa.Column("parse_status", sa.String(length=20), nullable=False),
        sa.Column("bidder_row_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("lender IN ('WORLD_BANK','ADB','EBRD')", name="ck_award_notice_snapshot_lender"),
        sa.CheckConstraint("parse_status IN ('PARSED','NO_BIDDERS')", name="ck_award_notice_snapshot_parse_status"),
        sa.CheckConstraint("jsonb_typeof(sectors) = 'array'", name="ck_award_notice_snapshot_sectors"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lender", "notice_id", "content_hash", name="uq_award_notice_snapshot_content"),
    )
    op.create_index(
        "ix_award_notice_snapshots_lender_notice", "award_notice_snapshots",
        ["lender", "notice_id", "retrieved_at", "id"],
    )
    op.create_index("ix_award_notice_snapshots_country_date", "award_notice_snapshots", ["country", "notice_date"])

    op.create_table(
        "award_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lender", sa.String(length=20), nullable=False),
        sa.Column("country", sa.String(length=120), nullable=True),
        sa.Column("project_id", sa.String(length=40), nullable=True),
        sa.Column("project_name", sa.String(length=500), nullable=True),
        sa.Column("notice_id", sa.String(length=64), nullable=False),
        sa.Column("notice_url", sa.String(length=500), nullable=False),
        sa.Column("notice_date", sa.Date(), nullable=True),
        sa.Column("award_date", sa.Date(), nullable=True),
        sa.Column("package_reference", sa.String(length=200), nullable=True),
        sa.Column("package_title", sa.Text(), nullable=True),
        sa.Column("procurement_group", sa.String(length=80), nullable=True),
        sa.Column("procurement_method", sa.String(length=120), nullable=True),
        sa.Column("bid_ordinal", sa.Integer(), nullable=False),
        sa.Column("member_ordinal", sa.Integer(), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("bidder_name", sa.String(length=500), nullable=False),
        sa.Column("bidder_name_normalized", sa.String(length=500), nullable=False),
        sa.Column("bidder_source_id", sa.String(length=40), nullable=True),
        sa.Column("bidder_country", sa.String(length=120), nullable=True),
        sa.Column("bidder_kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("evaluated_price_text", sa.String(length=200), nullable=True),
        sa.Column("evaluated_price_currency", sa.String(length=3), nullable=True),
        sa.Column("evaluated_price_amount", sa.Numeric(24, 2), nullable=True),
        sa.Column("signed_contract_price_text", sa.String(length=200), nullable=True),
        sa.Column("signed_contract_currency", sa.String(length=3), nullable=True),
        sa.Column("signed_contract_amount", sa.Numeric(24, 2), nullable=True),
        sa.Column("bid_price_at_opening_text", sa.String(length=200), nullable=True),
        sa.Column("scores", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=40), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("lender IN ('WORLD_BANK','ADB','EBRD')", name="ck_award_outcome_lender"),
        sa.CheckConstraint(
            "status IN ('AWARDED','EVALUATED','REJECTED','NOT_EVALUATED')", name="ck_award_outcome_status"
        ),
        sa.CheckConstraint("bidder_kind IN ('FIRM','INDIVIDUAL')", name="ck_award_outcome_bidder_kind"),
        sa.CheckConstraint(
            "bid_ordinal >= 1 AND member_ordinal >= 1 AND member_ordinal <= member_count",
            name="ck_award_outcome_ordinals",
        ),
        sa.CheckConstraint("jsonb_typeof(scores) = 'object'", name="ck_award_outcome_scores"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["award_notice_snapshots.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "bid_ordinal", "member_ordinal", name="uq_award_outcome_member"),
    )
    op.create_index("ix_award_outcomes_snapshot", "award_outcomes", ["snapshot_id"])
    op.create_index("ix_award_outcomes_country_status", "award_outcomes", ["country", "status"])
    op.create_index("ix_award_outcomes_bidder_source_id", "award_outcomes", ["bidder_source_id"])
    op.create_index("ix_award_outcomes_bidder_name_normalized", "award_outcomes", ["bidder_name_normalized"])

    op.execute("""
CREATE FUNCTION award_ledger_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'award_ledger_immutable' USING ERRCODE='23514';
END $$
""")
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION award_ledger_append_only()"
        )


def downgrade() -> None:
    for table in reversed(APPEND_ONLY_TABLES):
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
    op.execute("DROP FUNCTION award_ledger_append_only()")
    op.drop_index("ix_award_outcomes_bidder_name_normalized", table_name="award_outcomes")
    op.drop_index("ix_award_outcomes_bidder_source_id", table_name="award_outcomes")
    op.drop_index("ix_award_outcomes_country_status", table_name="award_outcomes")
    op.drop_index("ix_award_outcomes_snapshot", table_name="award_outcomes")
    op.drop_table("award_outcomes")
    op.drop_index("ix_award_notice_snapshots_country_date", table_name="award_notice_snapshots")
    op.drop_index("ix_award_notice_snapshots_lender_notice", table_name="award_notice_snapshots")
    op.drop_table("award_notice_snapshots")
