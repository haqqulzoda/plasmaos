"""s2_1_readiness_vault

Revision ID: 20260629_0001_s2_1_readiness_vault
Revises: 20260624_0002_s1_2_company_onboarding_notes
Create Date: 2026-06-29 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260629_0001_s2_1_readiness_vault"
down_revision: Union[str, None] = "20260624_0002_s1_2_company_onboarding_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "readiness_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("document_name", sa.String(length=255), nullable=False),
        sa.Column("document_number", sa.String(length=100), nullable=True),
        sa.Column("issuer", sa.String(length=255), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="unknown", nullable=False),
        sa.Column("related_service", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("optional_file_url", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "document_type IN ("
            "'license', 'certificate', 'tax_clearance', 'financial_statement', "
            "'registration_document', 'power_of_attorney', 'personnel_document', 'other'"
            ")",
            name="ck_readiness_documents_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('available', 'missing', 'expired', 'unknown')",
            name="ck_readiness_documents_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["company_profile_id"],
            ["company_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_readiness_documents_company_profile_id",
        "readiness_documents",
        ["company_profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_readiness_documents_document_type",
        "readiness_documents",
        ["document_type"],
        unique=False,
    )
    op.create_index(
        "ix_readiness_documents_status",
        "readiness_documents",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_readiness_documents_status", table_name="readiness_documents")
    op.drop_index("ix_readiness_documents_document_type", table_name="readiness_documents")
    op.drop_index(
        "ix_readiness_documents_company_profile_id",
        table_name="readiness_documents",
    )
    op.drop_table("readiness_documents")
