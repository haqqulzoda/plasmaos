"""Add override_seal to tender_analyses

Revision ID: a8f3d1c2e5b4
 Revises: d21a4f2b7c31
Create Date: 2026-05-08 04:48:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a8f3d1c2e5b4'
down_revision: Union[str, None] = 'd21a4f2b7c31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tender_analyses
        ADD COLUMN IF NOT EXISTS override_seal VARCHAR(64)
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN tender_analyses.override_seal IS
        'SHA-256 seal incorporating override state. Null when no overrides have been applied.'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE tender_analyses
        DROP COLUMN IF EXISTS override_seal
        """
    )
