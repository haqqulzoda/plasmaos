"""add nullable per-user UI locale preference

Revision ID: 20260902_0001_s7_2_user_ui_locale
Revises: 20260901_0001_sr2_3_connector_metrics
Create Date: 2026-09-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260902_0001_s7_2_user_ui_locale"
down_revision: Union[str, None] = "20260901_0001_sr2_3_connector_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("ui_locale", sa.String(length=8), nullable=True),
    )
    op.create_check_constraint(
        "ck_users_ui_locale_allowed",
        "users",
        "ui_locale IS NULL OR ui_locale IN ('en', 'uz', 'ru', 'ar')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_ui_locale_allowed", "users", type_="check")
    op.drop_column("users", "ui_locale")
