"""s5_1_giz_source

Revision ID: 20260702_0001_s5_1_giz_source
Revises: 20260629_0001_s2_1_readiness_vault
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260702_0001_s5_1_giz_source"
down_revision: Union[str, None] = "20260629_0001_s2_1_readiness_vault"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenders DROP CONSTRAINT IF EXISTS ck_tenders_source_system_allowed")
    op.execute(
        """
        ALTER TABLE tenders
        ADD CONSTRAINT ck_tenders_source_system_allowed
        CHECK (source_system IN ('uzex', 'world_bank', 'adb', 'giz'))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM tender_documents
        WHERE tender_id IN (
            SELECT id FROM tenders WHERE source_system = 'giz'
        )
        """
    )
    op.execute("DELETE FROM tenders WHERE source_system = 'giz'")
    op.execute("ALTER TABLE tenders DROP CONSTRAINT IF EXISTS ck_tenders_source_system_allowed")
    op.execute(
        """
        ALTER TABLE tenders
        ADD CONSTRAINT ck_tenders_source_system_allowed
        CHECK (source_system IN ('uzex', 'world_bank', 'adb'))
        """
    )
