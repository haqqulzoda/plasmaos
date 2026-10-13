"""Sprint 1: server-side product events and the AI cost ledger.

Additive and reversible: two append-only tables (a trigger rejects UPDATE and DELETE), ids,
codes, counts and timings only, no foreign keys.

Revision ID: 20261012_0002_s1_product_analytics
Revises: 20261012_0001_s1_award_ledger
Create Date: 2026-10-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261012_0002_s1_product_analytics"
down_revision: Union[str, None] = "20261012_0001_s1_award_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPEND_ONLY_TABLES = ("product_events", "ai_call_costs")
EVENT_NAMES = (
    "sign_in", "tender_viewed", "workspace_opened", "analysis_started", "analysis_completed", "analysis_failed",
    "review_confirmed", "eoi_generated", "eoi_downloaded", "invite_sent", "invite_accepted", "cv_uploaded",
)


def _in(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "product_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_name", sa.String(length=40), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tender_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pursuit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_type", sa.String(length=30), nullable=True),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "properties", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(f"event_name IN ({_in(EVENT_NAMES)})", name="ck_product_event_name"),
        sa.CheckConstraint("jsonb_typeof(properties) = 'object'", name="ck_product_event_properties"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_events_name_occurred", "product_events", ["event_name", "occurred_at"])
    op.create_index("ix_product_events_organization_occurred", "product_events", ["organization_id", "occurred_at"])

    op.create_table(
        "ai_call_costs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("call_kind", sa.String(length=20), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pursuit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_type", sa.String(length=30), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_provider", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("thinking_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(14, 6), nullable=True),
        sa.Column("price_table_version", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("call_kind IN ('ANALYSIS','CV_EXTRACTION','EOI_NOTE')", name="ck_ai_call_cost_kind"),
        sa.CheckConstraint("outcome IN ('SUCCEEDED','FAILED')", name="ck_ai_call_cost_outcome"),
        sa.CheckConstraint(
            "coalesce(input_tokens, 0) >= 0 AND coalesce(output_tokens, 0) >= 0 AND coalesce(thinking_tokens, 0) >= 0",
            name="ck_ai_call_cost_tokens",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_call_costs_kind_created", "ai_call_costs", ["call_kind", "created_at"])
    op.create_index("ix_ai_call_costs_subject", "ai_call_costs", ["subject_type", "subject_id"])
    op.create_index("ix_ai_call_costs_organization_created", "ai_call_costs", ["organization_id", "created_at"])

    op.execute("""
CREATE FUNCTION product_analytics_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'product_analytics_immutable' USING ERRCODE='23514';
END $$
""")
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION product_analytics_append_only()"
        )


def downgrade() -> None:
    for table in reversed(APPEND_ONLY_TABLES):
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
    op.execute("DROP FUNCTION product_analytics_append_only()")
    op.drop_index("ix_ai_call_costs_organization_created", table_name="ai_call_costs")
    op.drop_index("ix_ai_call_costs_subject", table_name="ai_call_costs")
    op.drop_index("ix_ai_call_costs_kind_created", table_name="ai_call_costs")
    op.drop_table("ai_call_costs")
    op.drop_index("ix_product_events_organization_occurred", table_name="product_events")
    op.drop_index("ix_product_events_name_occurred", table_name="product_events")
    op.drop_table("product_events")
