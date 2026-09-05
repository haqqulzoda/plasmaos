"""add independent analysis language persistence

Revision ID: 20260904_0001_s8_2_analysis_language
Revises: 20260902_0001_s7_2_user_ui_locale
Create Date: 2026-09-04 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260904_0001_s8_2_analysis_language"
down_revision: Union[str, None] = "20260902_0001_s7_2_user_ui_locale"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("default_analysis_language", sa.String(length=8), nullable=True),
    )
    op.create_check_constraint(
        "ck_users_default_analysis_language_allowed",
        "users",
        "default_analysis_language IS NULL OR "
        "default_analysis_language IN ('en', 'uz', 'ru', 'ar')",
    )
    op.add_column(
        "analysis_versions",
        sa.Column("analysis_language", sa.String(length=8), nullable=True),
    )
    op.create_check_constraint(
        "ck_analysis_versions_analysis_language_allowed",
        "analysis_versions",
        "analysis_language IS NULL OR analysis_language IN ('en', 'uz', 'ru', 'ar')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_analysis_versions_analysis_language_allowed",
        "analysis_versions",
        type_="check",
    )
    op.drop_column("analysis_versions", "analysis_language")
    op.drop_constraint(
        "ck_users_default_analysis_language_allowed",
        "users",
        type_="check",
    )
    op.drop_column("users", "default_analysis_language")
