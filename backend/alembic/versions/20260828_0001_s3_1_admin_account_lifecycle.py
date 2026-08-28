"""preserve explicit pre-disable user lifecycle state

Revision ID: 20260828_0001_s3_1_admin_account_lifecycle
Revises: 20260827_0002_s2_2_analysis_version_foundation
Create Date: 2026-08-28 12:00:00.000000

Existing disabled accounts receive NULL because their prior state cannot be
proved. Runtime restore handles that value conservatively as pending.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260828_0001_s3_1_admin_account_lifecycle"
down_revision: Union[str, None] = "20260827_0002_s2_2_analysis_version_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "pre_disabled_approval_status",
            sa.String(length=20),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_users_pre_disabled_approval_status_allowed",
        "users",
        "pre_disabled_approval_status IS NULL OR "
        "(approval_status = 'disabled' AND "
        "pre_disabled_approval_status IN ('pending', 'approved', 'rejected'))",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_users_pre_disabled_approval_status_allowed",
        "users",
        type_="check",
    )
    op.drop_column("users", "pre_disabled_approval_status")
