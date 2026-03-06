"""add_tender_document_storage_fields

Revision ID: 27fc6790093d
Revises: 14c7b4cac4ea
Create Date: 2026-03-07 03:18:37.023070

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '27fc6790093d'
down_revision: Union[str, None] = '14c7b4cac4ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tender_documents",
        sa.Column("storage_path", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "tender_documents",
        sa.Column("file_size", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tender_documents", "file_size")
    op.drop_column("tender_documents", "storage_path")
