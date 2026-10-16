"""P1: organization access state (explore | pilot | paid | disabled), the plan, admin alerts.

Additive: six nullable/defaulted columns on ``organizations``, the ``admin_alerts`` table, and
one more e-mail kind/category (``ADMIN_ALERT`` / ``ADMIN``). Backfill from the company approval
that stays the enforced gate: approved -> pilot, pending -> explore, rejected/disabled ->
disabled. No other row changes. Downgrade drops the columns, the table and the e-mail values.

Revision ID: 20261016_0002_p1_organization_access
Revises: 20261016_0001_p1_email_sign_in
Create Date: 2026-10-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261016_0002_p1_organization_access"
down_revision: Union[str, None] = "20261016_0001_p1_email_sign_in"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_KINDS = "'TEAM_INVITATION','ANALYSIS_COMPLETED','ANALYSIS_FAILED','EOI_DRAFT_READY','DAILY_DIGEST','SIGN_IN_CODE'"
NEW_KINDS = OLD_KINDS + ",'ADMIN_ALERT'"
OLD_CATEGORIES = "'TEAM','ANALYSIS','EOI','DIGEST','AUTH'"
NEW_CATEGORIES = OLD_CATEGORIES + ",'ADMIN'"


def upgrade() -> None:
    op.add_column("organizations", sa.Column(
        "access_state", sa.String(length=20), server_default=sa.text("'explore'"), nullable=False))
    op.add_column("organizations", sa.Column("access_state_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("access_state_changed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("organizations", sa.Column("plan_started_on", sa.Date(), nullable=True))
    op.add_column("organizations", sa.Column("plan_ends_on", sa.Date(), nullable=True))
    op.add_column("organizations", sa.Column("success_criteria", sa.Text(), nullable=True))
    op.create_foreign_key(
        "organizations_access_state_changed_by_user_id_fkey", "organizations", "users",
        ["access_state_changed_by_user_id"], ["id"], ondelete="SET NULL",
    )
    op.execute(
        """
        UPDATE organizations o SET access_state = CASE cp.approval_status
            WHEN 'approved' THEN 'pilot'
            WHEN 'pending' THEN 'explore'
            ELSE 'disabled' END
        FROM company_profiles cp
        WHERE cp.id = o.legacy_company_profile_id
        """
    )
    op.create_check_constraint(
        "ck_organizations_access_state", "organizations", "access_state IN ('explore', 'pilot', 'paid', 'disabled')"
    )
    op.create_check_constraint(
        "ck_organizations_plan_dates", "organizations",
        "plan_ends_on IS NULL OR plan_started_on IS NULL OR plan_ends_on >= plan_started_on",
    )
    op.create_check_constraint(
        "ck_organizations_success_criteria_length", "organizations",
        "success_criteria IS NULL OR char_length(success_criteria) <= 4000",
    )
    op.create_index("ix_organizations_access_state", "organizations", ["access_state"])

    op.create_table(
        "admin_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("state", sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('NEW_SIGNUP','PILOT_REQUEST','ANALYSIS_PROVIDER_ERROR')", name="ck_admin_alert_kind"),
        sa.CheckConstraint("state IN ('PENDING','SENT','FAILED')", name="ck_admin_alert_state"),
        sa.CheckConstraint("channel IS NULL OR channel IN ('TELEGRAM','EMAIL')", name="ck_admin_alert_channel"),
        sa.CheckConstraint("(state = 'SENT') = (sent_at IS NOT NULL)", name="ck_admin_alert_sent"),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 8192", name="ck_admin_alert_payload"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index(
        "ix_admin_alerts_due", "admin_alerts", ["next_attempt_at"], postgresql_where=sa.text("state = 'PENDING'")
    )
    op.create_index("ix_admin_alerts_kind_created", "admin_alerts", ["kind", "created_at"])

    op.drop_constraint("ck_email_delivery_kind", "email_deliveries", type_="check")
    op.create_check_constraint("ck_email_delivery_kind", "email_deliveries", f"kind IN ({NEW_KINDS})")
    op.drop_constraint("ck_email_delivery_category", "email_deliveries", type_="check")
    op.create_check_constraint("ck_email_delivery_category", "email_deliveries", f"category IN ({NEW_CATEGORIES})")


def downgrade() -> None:
    op.execute("DELETE FROM email_deliveries WHERE kind = 'ADMIN_ALERT' OR category = 'ADMIN'")
    op.drop_constraint("ck_email_delivery_category", "email_deliveries", type_="check")
    op.create_check_constraint("ck_email_delivery_category", "email_deliveries", f"category IN ({OLD_CATEGORIES})")
    op.drop_constraint("ck_email_delivery_kind", "email_deliveries", type_="check")
    op.create_check_constraint("ck_email_delivery_kind", "email_deliveries", f"kind IN ({OLD_KINDS})")
    op.drop_index("ix_admin_alerts_kind_created", table_name="admin_alerts")
    op.drop_index("ix_admin_alerts_due", table_name="admin_alerts")
    op.drop_table("admin_alerts")
    op.drop_index("ix_organizations_access_state", table_name="organizations")
    op.drop_constraint("ck_organizations_success_criteria_length", "organizations", type_="check")
    op.drop_constraint("ck_organizations_plan_dates", "organizations", type_="check")
    op.drop_constraint("ck_organizations_access_state", "organizations", type_="check")
    op.drop_constraint("organizations_access_state_changed_by_user_id_fkey", "organizations", type_="foreignkey")
    for column in ("success_criteria", "plan_ends_on", "plan_started_on", "access_state_changed_by_user_id",
                   "access_state_changed_at", "access_state"):
        op.drop_column("organizations", column)
