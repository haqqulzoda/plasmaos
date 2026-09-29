"""D1-03 one system-generated official notice per tender.

Additive and reversible: a partial unique index only. It constrains rows whose
source_document_type is OFFICIAL_NOTICE, which no earlier release wrote, so it
cannot conflict with existing data.

Revision ID: 20261003_0001_d1_03_official_notice_unique
Revises: 20261002_0001_p0_extraction_trust_gate
Create Date: 2026-09-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261003_0001_d1_03_official_notice_unique"
down_revision: Union[str, None] = "20261002_0001_p0_extraction_trust_gate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_tender_documents_official_notice",
        "tender_documents",
        ["tender_id"],
        unique=True,
        postgresql_where=sa.text("source_document_type = 'OFFICIAL_NOTICE'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_tender_documents_official_notice",
        table_name="tender_documents",
    )
