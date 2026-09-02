"""add nullable source refresh stage and HTTP metrics

Revision ID: 20260901_0001_sr2_3_connector_metrics
Revises: 20260831_0001_sr2_2_refresh_leases
Create Date: 2026-09-01 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_0001_sr2_3_connector_metrics"
down_revision: Union[str, None] = "20260831_0001_sr2_2_refresh_leases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

METRIC_COLUMNS = (
    "fetch_elapsed_ms",
    "normalize_elapsed_ms",
    "persist_elapsed_ms",
    "document_dispatch_elapsed_ms",
    "http_request_count",
    "http_retry_count",
    "http_failure_count",
)


def upgrade() -> None:
    for column_name in METRIC_COLUMNS:
        op.add_column(
            "source_refresh_jobs",
            sa.Column(column_name, sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    for column_name in reversed(METRIC_COLUMNS):
        op.drop_column("source_refresh_jobs", column_name)
