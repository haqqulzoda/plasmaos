"""P3: plans and limits. Organization plan and overrides, pursuit usage, admin grants, PLAN_USAGE alerts.

Additive. Backfill: plan from the P1 access state (explore -> explore, pilot -> pilot, paid ->
pursuit_desk, disabled -> explore), and one usage row per pursuit that already has an analysis run,
counted at its first run (the counting rule: a pursuit counts once, when its first analysis starts).
Downgrade drops the columns, tables and the alert kind (and its alerts).

Revision ID: 20261024_0001_p3_plans_limits
Revises: 20261023_0001_p2_partner_finder
Create Date: 2026-10-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261024_0001_p3_plans_limits"
down_revision: Union[str, None] = "20261023_0001_p2_partner_finder"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_ALERT_KINDS = "'NEW_SIGNUP','PILOT_REQUEST','ANALYSIS_PROVIDER_ERROR','PARTNER_REQUEST'"
NEW_ALERT_KINDS = OLD_ALERT_KINDS + ",'PLAN_USAGE'"


def upgrade() -> None:
    op.add_column("organizations", sa.Column("plan", sa.String(length=20), server_default=sa.text("'explore'"), nullable=False))
    op.add_column("organizations", sa.Column("pursuit_limit_override", sa.Integer(), nullable=True))
    op.add_column("organizations", sa.Column("introduction_limit_override", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE organizations SET plan = CASE access_state WHEN 'pilot' THEN 'pilot' "
        "WHEN 'paid' THEN 'pursuit_desk' ELSE 'explore' END"
    )
    op.create_check_constraint(
        "ck_organizations_plan", "organizations",
        "plan IN ('explore','pilot','pursuit_desk','agent','enterprise','per_tender')",
    )
    op.create_check_constraint(
        "ck_organizations_plan_overrides", "organizations",
        "(pursuit_limit_override IS NULL OR pursuit_limit_override >= 0) AND "
        "(introduction_limit_override IS NULL OR introduction_limit_override >= 0)",
    )

    op.create_table(
        "organization_pursuit_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pursuit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("plan", sa.String(length=20), nullable=False),
        sa.Column("counted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["pursuit_analysis_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["pursuit_id", "organization_id"], ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_pursuit_usage_pursuit_organization", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "pursuit_id", name="uq_pursuit_usage_pursuit"),
    )
    op.create_index(
        "ix_pursuit_usage_organization_counted", "organization_pursuit_usage", ["organization_id", "counted_at"]
    )
    op.execute(
        """
        INSERT INTO organization_pursuit_usage (id, organization_id, pursuit_id, analysis_run_id, plan, counted_at)
        SELECT DISTINCT ON (r.organization_id, r.pursuit_id)
               md5('plasma:p3:usage:' || r.organization_id::text || ':' || r.pursuit_id::text)::uuid,
               r.organization_id, r.pursuit_id, r.id, o.plan, r.created_at
        FROM pursuit_analysis_runs r JOIN organizations o ON o.id = r.organization_id
        ORDER BY r.organization_id, r.pursuit_id, r.created_at, r.id
        """
    )

    op.create_table(
        "organization_plan_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("granted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("kind IN ('PURSUITS','INTRODUCTIONS')", name="ck_plan_grant_kind"),
        sa.CheckConstraint("quantity BETWEEN 1 AND 1000", name="ck_plan_grant_quantity"),
        sa.CheckConstraint("length(trim(reason)) >= 3", name="ck_plan_grant_reason"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_plan_grants_organization_period", "organization_plan_grants", ["organization_id", "period_start"]
    )

    op.drop_constraint("ck_admin_alert_kind", "admin_alerts", type_="check")
    op.create_check_constraint("ck_admin_alert_kind", "admin_alerts", f"kind IN ({NEW_ALERT_KINDS})")


def downgrade() -> None:
    op.execute("DELETE FROM admin_alerts WHERE kind = 'PLAN_USAGE'")
    op.drop_constraint("ck_admin_alert_kind", "admin_alerts", type_="check")
    op.create_check_constraint("ck_admin_alert_kind", "admin_alerts", f"kind IN ({OLD_ALERT_KINDS})")
    op.drop_index("ix_plan_grants_organization_period", table_name="organization_plan_grants")
    op.drop_table("organization_plan_grants")
    op.drop_index("ix_pursuit_usage_organization_counted", table_name="organization_pursuit_usage")
    op.drop_table("organization_pursuit_usage")
    op.drop_constraint("ck_organizations_plan_overrides", "organizations", type_="check")
    op.drop_constraint("ck_organizations_plan", "organizations", type_="check")
    for column in ("introduction_limit_override", "pursuit_limit_override", "plan"):
        op.drop_column("organizations", column)
