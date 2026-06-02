"""Add override_seal to tender_analyses

Revision ID: a8f3d1c2e5b4
Revises: 619f79030fe7
Create Date: 2026-05-08 04:48:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a8f3d1c2e5b4'
down_revision: Union[str, None] = 'd21a4f2b7c31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tender_analyses',
        sa.Column(
            'override_seal',
            sa.String(64),
            nullable=True,
            comment=(
                'SHA-256 seal incorporating override state. '
                'Null when no overrides have been applied.'
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column('tender_analyses', 'override_seal')
