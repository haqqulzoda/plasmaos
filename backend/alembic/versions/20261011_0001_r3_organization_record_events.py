"""R3 Task 6: audit of member changes to the organization's company profile and readiness.

Additive and reversible: one append-only table (a trigger rejects UPDATE and DELETE).

Revision ID: 20261011_0001_r3_organization_record_events
Revises: 20261010_0001_r3_email_notifications
Create Date: 2026-10-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261011_0001_r3_organization_record_events"
down_revision: Union[str, None] = "20261010_0001_r3_email_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organization_record_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("record_type", sa.String(length=30), nullable=False),
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column(
            "changed_fields", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "record_type IN ('COMPANY_PROFILE','COMPANY_VAULT','READINESS_DOCUMENT')",
            name="ck_organization_record_event_type",
        ),
        sa.CheckConstraint("action IN ('CREATE','UPDATE','DELETE')", name="ck_organization_record_event_action"),
        sa.CheckConstraint("jsonb_typeof(changed_fields) = 'array'", name="ck_organization_record_event_fields"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_profile_id"], ["company_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_membership_id"], ["memberships.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_organization_record_events_organization_created", "organization_record_events",
        ["organization_id", "created_at"],
    )
    op.execute("""
CREATE FUNCTION organization_record_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- SET NULL from a deleted user or membership is the only allowed change.
  IF TG_OP = 'UPDATE' AND (NEW.id, NEW.organization_id, NEW.company_profile_id, NEW.record_type, NEW.record_id,
      NEW.action, NEW.changed_fields, NEW.created_at) IS NOT DISTINCT FROM (OLD.id, OLD.organization_id,
      OLD.company_profile_id, OLD.record_type, OLD.record_id, OLD.action, OLD.changed_fields, OLD.created_at)
  THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'organization_record_event_immutable' USING ERRCODE='23514';
END $$
""")
    op.execute("""
CREATE TRIGGER organization_record_events_immutable BEFORE UPDATE OR DELETE ON organization_record_events
FOR EACH ROW EXECUTE FUNCTION organization_record_events_append_only()
""")


def downgrade() -> None:
    op.execute("DROP TRIGGER organization_record_events_immutable ON organization_record_events")
    op.execute("DROP FUNCTION organization_record_events_append_only()")
    op.drop_index("ix_organization_record_events_organization_created", table_name="organization_record_events")
    op.drop_table("organization_record_events")
