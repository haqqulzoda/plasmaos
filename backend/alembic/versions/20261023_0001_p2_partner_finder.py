"""P2: partner finder. Introduction requests, their status events, prospective scenario members.

Additive: three new tables and one more admin alert kind (``PARTNER_REQUEST``). No existing row
changes. Downgrade drops the tables and the alert kind (and its alerts).

Revision ID: 20261023_0001_p2_partner_finder
Revises: 20261016_0002_p1_organization_access
Create Date: 2026-10-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261023_0001_p2_partner_finder"
down_revision: Union[str, None] = "20261016_0002_p1_organization_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_ALERT_KINDS = "'NEW_SIGNUP','PILOT_REQUEST','ANALYSIS_PROVIDER_ERROR'"
NEW_ALERT_KINDS = OLD_ALERT_KINDS + ",'PARTNER_REQUEST'"
KINDS = "('INTRODUCTION', 'EXPERT_SOURCING')"
STATUSES = "('REQUESTED', 'CONTACTED', 'ACCEPTED', 'DECLINED', 'INTRODUCED')"


def upgrade() -> None:
    op.create_table(
        "partner_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pursuit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gap_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("gap_category", sa.String(length=20), nullable=False),
        sa.Column("gap_summary", sa.Text(), nullable=False),
        sa.Column("firm_key", sa.String(length=700), nullable=True),
        sa.Column("firm_name", sa.String(length=500), nullable=True),
        sa.Column("firm_country", sa.String(length=120), nullable=True),
        sa.Column("suggestion_snapshot", postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("requester_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requester_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["pursuit_analysis_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["gap_id"], ["pursuit_analysis_gaps.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requester_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["pursuit_id", "organization_id"], ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_partner_request_pursuit_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requester_membership_id", "organization_id"], ["memberships.id", "memberships.organization_id"],
            name="fk_partner_request_requester_organization", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"kind IN {KINDS}", name="ck_partner_request_kind"),
        sa.CheckConstraint("gap_category IN ('PARTNER_FIRM','EXPERT')", name="ck_partner_request_gap_category"),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_partner_request_status"),
        sa.CheckConstraint(
            "(kind = 'INTRODUCTION' AND firm_key IS NOT NULL AND length(trim(firm_name)) >= 2) OR "
            "(kind = 'EXPERT_SOURCING' AND firm_key IS NULL AND firm_name IS NULL AND gap_category = 'EXPERT')",
            name="ck_partner_request_target",
        ),
        sa.CheckConstraint("note IS NULL OR char_length(note) <= 2000", name="ck_partner_request_note"),
        sa.CheckConstraint("jsonb_typeof(suggestion_snapshot) = 'object'", name="ck_partner_request_snapshot"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_partner_request_id_organization"),
    )
    op.create_index(
        "uq_partner_request_gap_firm", "partner_requests", ["organization_id", "gap_id", "firm_key"], unique=True,
        postgresql_where=sa.text("kind = 'INTRODUCTION'"),
    )
    op.create_index(
        "uq_partner_request_gap_sourcing", "partner_requests", ["organization_id", "gap_id"], unique=True,
        postgresql_where=sa.text("kind = 'EXPERT_SOURCING'"),
    )
    op.create_index("ix_partner_requests_pursuit", "partner_requests", ["organization_id", "pursuit_id", "created_at"])
    op.create_index("ix_partner_requests_status", "partner_requests", ["status", "created_at"])

    op.create_table(
        "partner_request_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["request_id", "organization_id"], ["partner_requests.id", "partner_requests.organization_id"],
            name="fk_partner_request_event_request", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"to_status IN {STATUSES}", name="ck_partner_request_event_to"),
        sa.CheckConstraint("message IS NULL OR char_length(message) <= 2000", name="ck_partner_request_event_message"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_partner_request_events_request", "partner_request_events", ["request_id", "created_at"])

    op.create_table(
        "team_scenario_prospective_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("partner_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name_snapshot", sa.String(length=500), nullable=False),
        sa.Column("added_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["scenario_id", "organization_id"], ["team_scenarios.id", "team_scenarios.organization_id"],
            name="fk_prospective_member_scenario", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["partner_request_id", "organization_id"], ["partner_requests.id", "partner_requests.organization_id"],
            name="fk_prospective_member_request", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["added_by_membership_id", "organization_id"], ["memberships.id", "memberships.organization_id"],
            name="fk_prospective_member_actor", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_prospective_member_active", "team_scenario_prospective_members", ["scenario_id", "partner_request_id"],
        unique=True, postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index(
        "ix_prospective_members_scenario", "team_scenario_prospective_members", ["scenario_id", "created_at"]
    )

    op.drop_constraint("ck_admin_alert_kind", "admin_alerts", type_="check")
    op.create_check_constraint("ck_admin_alert_kind", "admin_alerts", f"kind IN ({NEW_ALERT_KINDS})")


def downgrade() -> None:
    op.execute("DELETE FROM admin_alerts WHERE kind = 'PARTNER_REQUEST'")
    op.drop_constraint("ck_admin_alert_kind", "admin_alerts", type_="check")
    op.create_check_constraint("ck_admin_alert_kind", "admin_alerts", f"kind IN ({OLD_ALERT_KINDS})")
    op.drop_index("ix_prospective_members_scenario", table_name="team_scenario_prospective_members")
    op.drop_index("uq_prospective_member_active", table_name="team_scenario_prospective_members")
    op.drop_table("team_scenario_prospective_members")
    op.drop_index("ix_partner_request_events_request", table_name="partner_request_events")
    op.drop_table("partner_request_events")
    op.drop_index("ix_partner_requests_status", table_name="partner_requests")
    op.drop_index("ix_partner_requests_pursuit", table_name="partner_requests")
    op.drop_index("uq_partner_request_gap_sourcing", table_name="partner_requests")
    op.drop_index("uq_partner_request_gap_firm", table_name="partner_requests")
    op.drop_table("partner_requests")
