"""harden the canonical administrative audit trail

Revision ID: 20260828_0002_s3_4_admin_audit_hardening
Revises: 20260828_0001_s3_1_admin_account_lifecycle
Create Date: 2026-08-28 16:00:00.000000

Existing events remain untouched. Their new canonical fields are NULL and are
reported as legacy/partial because precise outcomes and state transitions
cannot be reconstructed truthfully.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260828_0002_s3_4_admin_audit_hardening"
down_revision: Union[str, None] = "20260828_0001_s3_1_admin_account_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = (
        sa.Column("actor_type", sa.String(length=30), nullable=True),
        sa.Column("actor_email_snapshot", sa.String(length=255), nullable=True),
        sa.Column("actor_role_snapshot", sa.String(length=30), nullable=True),
        sa.Column("target_resource_type", sa.String(length=50), nullable=True),
        sa.Column("target_resource_id", sa.String(length=255), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=True),
        sa.Column(
            "previous_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "new_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=True),
    )
    for column in columns:
        op.add_column("admin_activity_events", column)

    op.create_check_constraint(
        "ck_admin_activity_events_outcome_allowed",
        "admin_activity_events",
        "outcome IS NULL OR outcome IN ('SUCCESS', 'DENIED', 'FAILED')",
    )
    op.create_check_constraint(
        "ck_admin_activity_events_actor_type_allowed",
        "admin_activity_events",
        "actor_type IS NULL OR actor_type IN ('USER', 'SYSTEM', 'SERVER_COMMAND')",
    )
    op.create_index(
        "ix_admin_activity_events_actor_user_id",
        "admin_activity_events",
        ["actor_user_id"],
    )
    op.create_index(
        "ix_admin_activity_events_outcome",
        "admin_activity_events",
        ["outcome"],
    )
    op.create_index(
        "ix_admin_activity_events_created_id",
        "admin_activity_events",
        ["created_at", "id"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_admin_activity_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'admin activity events are append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_admin_activity_events_append_only
        BEFORE UPDATE OR DELETE ON admin_activity_events
        FOR EACH ROW EXECUTE FUNCTION prevent_admin_activity_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_admin_activity_events_append_only "
        "ON admin_activity_events"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_admin_activity_event_mutation()")
    op.drop_index(
        "ix_admin_activity_events_created_id",
        table_name="admin_activity_events",
    )
    op.drop_index(
        "ix_admin_activity_events_outcome",
        table_name="admin_activity_events",
    )
    op.drop_index(
        "ix_admin_activity_events_actor_user_id",
        table_name="admin_activity_events",
    )
    op.drop_constraint(
        "ck_admin_activity_events_actor_type_allowed",
        "admin_activity_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_admin_activity_events_outcome_allowed",
        "admin_activity_events",
        type_="check",
    )
    for name in (
        "source",
        "request_id",
        "reason_code",
        "new_state",
        "previous_state",
        "outcome",
        "target_resource_id",
        "target_resource_type",
        "actor_role_snapshot",
        "actor_email_snapshot",
        "actor_type",
    ):
        op.drop_column("admin_activity_events", name)
