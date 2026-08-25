"""separate source execution freshness and coverage health

Revision ID: 20260824_0002_s0_4c
Revises: 20260824_0001_s0_4b
Create Date: 2026-08-24 00:00:01.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260824_0002_s0_4c"
down_revision: Union[str, None] = "20260824_0001_s0_4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_refresh_jobs",
        sa.Column("execution_health", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "source_refresh_jobs",
        sa.Column("freshness_health", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "source_refresh_jobs",
        sa.Column("coverage_health", sa.String(length=30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_refresh_jobs", "coverage_health")
    op.drop_column("source_refresh_jobs", "freshness_health")
    op.drop_column("source_refresh_jobs", "execution_health")
