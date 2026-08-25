"""add source freshness diagnostics and unknown tender lifecycle state

Revision ID: 20260824_0001_s0_4b
Revises: 20260709_0001_source_refresh_jobs
Create Date: 2026-08-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260824_0001_s0_4b"
down_revision: Union[str, None] = "20260709_0001_source_refresh_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL enum values are additive. UNKNOWN is required so a stale source
    # without a trustworthy deadline/status is not mislabeled OPEN or CLOSED.
    op.execute("ALTER TYPE tender_status ADD VALUE IF NOT EXISTS 'UNKNOWN'")
    op.add_column(
        "source_refresh_jobs",
        sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "source_refresh_jobs",
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "source_refresh_jobs",
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "source_refresh_jobs",
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("source_refresh_jobs", sa.Column("skip_reasons", sa.JSON(), nullable=True))
    op.add_column("source_refresh_jobs", sa.Column("failure_class", sa.String(length=100), nullable=True))
    op.add_column("source_refresh_jobs", sa.Column("failure_stage", sa.String(length=100), nullable=True))
    op.add_column("source_refresh_jobs", sa.Column("retryable", sa.Boolean(), nullable=True))
    op.add_column("source_refresh_jobs", sa.Column("elapsed_ms", sa.Integer(), nullable=True))
    op.add_column(
        "source_refresh_jobs",
        sa.Column("source_newest_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "source_refresh_jobs",
        sa.Column("source_oldest_published_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_refresh_jobs", "source_oldest_published_at")
    op.drop_column("source_refresh_jobs", "source_newest_published_at")
    op.drop_column("source_refresh_jobs", "elapsed_ms")
    op.drop_column("source_refresh_jobs", "retryable")
    op.drop_column("source_refresh_jobs", "failure_stage")
    op.drop_column("source_refresh_jobs", "failure_class")
    op.drop_column("source_refresh_jobs", "skip_reasons")
    op.drop_column("source_refresh_jobs", "fallback_used")
    op.drop_column("source_refresh_jobs", "rejected_count")
    op.drop_column("source_refresh_jobs", "skipped_count")
    op.drop_column("source_refresh_jobs", "fetched_count")
    # PostgreSQL cannot safely remove an enum value while rows may use it.
