"""s1_2_company_onboarding_notes

Revision ID: 20260624_0002_s1_2_company_onboarding_notes
Revises: 20260624_0001_s1_1_access_foundation
Create Date: 2026-06-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260624_0002_s1_2_company_onboarding_notes"
down_revision: Union[str, None] = "20260624_0001_s1_1_access_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("company_profiles", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("company_profiles", "notes")
