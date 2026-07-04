"""s5_2_1_ebrd_source

Revision ID: 20260704_0001_s5_2_1_ebrd_source
Revises: 20260702_0001_s5_1_giz_source
Create Date: 2026-07-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260704_0001_s5_2_1_ebrd_source"
down_revision: Union[str, None] = "20260702_0001_s5_1_giz_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenders DROP CONSTRAINT IF EXISTS ck_tenders_source_system_allowed")
    op.execute(
        """
        ALTER TABLE tenders
        ADD CONSTRAINT ck_tenders_source_system_allowed
        CHECK (source_system IN ('uzex', 'world_bank', 'adb', 'giz', 'ebrd'))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM tender_documents
        WHERE tender_id IN (
            SELECT id FROM tenders WHERE source_system = 'ebrd'
        )
        """
    )
    op.execute("DELETE FROM tenders WHERE source_system = 'ebrd'")
    op.execute("ALTER TABLE tenders DROP CONSTRAINT IF EXISTS ck_tenders_source_system_allowed")
    op.execute(
        """
        ALTER TABLE tenders
        ADD CONSTRAINT ck_tenders_source_system_allowed
        CHECK (source_system IN ('uzex', 'world_bank', 'adb', 'giz'))
        """
    )
