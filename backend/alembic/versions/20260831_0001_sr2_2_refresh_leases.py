"""add durable source refresh triggers, counters, options, and leases

Revision ID: 20260831_0001_sr2_2_refresh_leases
Revises: 20260828_0003_s4_1_tender_engagement_foundation
Create Date: 2026-08-31 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260831_0001_sr2_2_refresh_leases"
down_revision: Union[str, None] = (
    "20260828_0003_s4_1_tender_engagement_foundation"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_refresh_jobs",
        sa.Column("trigger_kind", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "source_refresh_jobs",
        sa.Column(
            "options_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    for column_name in (
        "unchanged_count",
        "documents_discovered_count",
        "documents_queued_count",
    ):
        op.add_column(
            "source_refresh_jobs",
            sa.Column(
                column_name,
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
    op.add_column(
        "source_refresh_jobs",
        sa.Column(
            "lease_owner",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "source_refresh_jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "source_refresh_jobs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_source_refresh_jobs_trigger_kind_allowed",
        "source_refresh_jobs",
        "trigger_kind IS NULL OR trigger_kind IN "
        "('customer', 'operator', 'scheduled')",
    )
    op.create_index(
        "ix_source_refresh_jobs_source_status_completed",
        "source_refresh_jobs",
        ["source_system", "status", "completed_at"],
    )
    op.create_index(
        "ix_source_refresh_jobs_running_lease_expiry",
        "source_refresh_jobs",
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_refresh_jobs_running_lease_expiry",
        table_name="source_refresh_jobs",
    )
    op.drop_index(
        "ix_source_refresh_jobs_source_status_completed",
        table_name="source_refresh_jobs",
    )
    op.drop_constraint(
        "ck_source_refresh_jobs_trigger_kind_allowed",
        "source_refresh_jobs",
        type_="check",
    )
    for column_name in (
        "heartbeat_at",
        "lease_expires_at",
        "lease_owner",
        "documents_queued_count",
        "documents_discovered_count",
        "unchanged_count",
        "options_json",
        "trigger_kind",
    ):
        op.drop_column("source_refresh_jobs", column_name)
