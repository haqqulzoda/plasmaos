"""add source refresh jobs

Revision ID: 20260709_0001_source_refresh_jobs
Revises: 20260706_0001_release_identity_admin_repair
Create Date: 2026-07-09 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260709_0001_source_refresh_jobs"
down_revision: Union[str, None] = "20260706_0001_release_identity_admin_repair"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_refresh_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.String(length=50), nullable=False),
        sa.Column(
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("force", sa.Boolean(), nullable=False),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial', "
            "'source_unavailable', 'failed')",
            name="ck_source_refresh_jobs_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_refresh_jobs_source_created",
        "source_refresh_jobs",
        ["source_system", "created_at"],
    )
    op.create_index(
        "uq_source_refresh_jobs_active_source",
        "source_refresh_jobs",
        ["source_system"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_source_refresh_jobs_active_source",
        table_name="source_refresh_jobs",
    )
    op.drop_index(
        "ix_source_refresh_jobs_source_created",
        table_name="source_refresh_jobs",
    )
    op.drop_table("source_refresh_jobs")
