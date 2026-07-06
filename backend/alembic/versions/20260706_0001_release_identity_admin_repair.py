"""release_identity_admin_repair

Revision ID: 20260706_0001_release_identity_admin_repair
Revises: 20260704_0001_s5_2_1_ebrd_source
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260706_0001_release_identity_admin_repair"
down_revision: Union[str, None] = "20260704_0001_s5_2_1_ebrd_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False),
    )

    op.create_table(
        "admin_activity_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_label", sa.String(length=255), nullable=True),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_email", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_admin_activity_events_actor_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_admin_activity_events_target_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admin_activity_events_action",
        "admin_activity_events",
        ["action"],
        unique=False,
    )
    op.create_index(
        "ix_admin_activity_events_target_user_id",
        "admin_activity_events",
        ["target_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_activity_events_target_email",
        "admin_activity_events",
        ["target_email"],
        unique=False,
    )
    op.create_index(
        "ix_admin_activity_events_created_at",
        "admin_activity_events",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_admin_activity_events_created_at", table_name="admin_activity_events")
    op.drop_index("ix_admin_activity_events_target_email", table_name="admin_activity_events")
    op.drop_index("ix_admin_activity_events_target_user_id", table_name="admin_activity_events")
    op.drop_index("ix_admin_activity_events_action", table_name="admin_activity_events")
    op.drop_table("admin_activity_events")
    op.drop_column("users", "auth_version")
