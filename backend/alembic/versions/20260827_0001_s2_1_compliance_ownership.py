"""add explicit TenderAnalysis ownership and quarantine legacy rows

Revision ID: 20260827_0001_s2_1_compliance_ownership
Revises: 20260826_0002_s1_2_wb_project_enrichment
Create Date: 2026-08-27 12:00:00.000000

Only the repository's historical ``<user UUID>:<profile UUID>`` encoding is
authoritative enough to backfill. Display names, including currently unique
ones, are never used to assign ownership. No analysis content is modified.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260827_0001_s2_1_compliance_ownership"
down_revision: Union[str, None] = "20260826_0002_s1_2_wb_project_enrichment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


UUID_PATTERN = (
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
ENCODED_OWNER_PATTERN = rf"^(?:{UUID_PATTERN}):(?:(?:{UUID_PATTERN})|no-profile)$"


def upgrade() -> None:
    op.add_column(
        "tender_analyses",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tender_analyses",
        sa.Column("company_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tender_analyses",
        sa.Column("ownership_state", sa.String(length=30), nullable=True),
    )

    op.create_foreign_key(
        "tender_analyses_user_id_fkey",
        "tender_analyses",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "tender_analyses_company_profile_id_fkey",
        "tender_analyses",
        "company_profiles",
        ["company_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_tender_analyses_user_id",
        "tender_analyses",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_tender_analyses_company_profile_id",
        "tender_analyses",
        ["company_profile_id"],
        unique=False,
    )

    # Start from the conservative state. The following update promotes only
    # rows proven by both UUID tokens and the canonical profile relationship.
    op.execute(
        """
        UPDATE tender_analyses
        SET user_id = NULL,
            company_profile_id = NULL,
            ownership_state = 'QUARANTINED_LEGACY'
        """
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE tender_analyses AS analysis
            SET user_id = app_user.id,
                company_profile_id = profile.id,
                ownership_state = 'OWNED'
            FROM users AS app_user
            JOIN company_profiles AS profile
              ON profile.user_id = app_user.id
            WHERE analysis.company_name ~* :encoded_owner_pattern
              AND app_user.id::text = LOWER(SPLIT_PART(analysis.company_name, ':', 1))
              AND profile.id::text = LOWER(SPLIT_PART(analysis.company_name, ':', 2))
            """
        ),
        {"encoded_owner_pattern": ENCODED_OWNER_PATTERN},
    )

    op.alter_column(
        "tender_analyses",
        "ownership_state",
        existing_type=sa.String(length=30),
        nullable=False,
        server_default=sa.text("'QUARANTINED_LEGACY'"),
    )
    op.create_check_constraint(
        "ck_tender_analyses_ownership_tuple",
        "tender_analyses",
        "(ownership_state = 'OWNED' AND user_id IS NOT NULL "
        "AND company_profile_id IS NOT NULL) OR "
        "(ownership_state = 'QUARANTINED_LEGACY' AND user_id IS NULL "
        "AND company_profile_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tender_analyses_ownership_tuple",
        "tender_analyses",
        type_="check",
    )
    op.drop_index(
        "ix_tender_analyses_company_profile_id",
        table_name="tender_analyses",
    )
    op.drop_index("ix_tender_analyses_user_id", table_name="tender_analyses")
    op.drop_constraint(
        "tender_analyses_company_profile_id_fkey",
        "tender_analyses",
        type_="foreignkey",
    )
    op.drop_constraint(
        "tender_analyses_user_id_fkey",
        "tender_analyses",
        type_="foreignkey",
    )
    op.drop_column("tender_analyses", "ownership_state")
    op.drop_column("tender_analyses", "company_profile_id")
    op.drop_column("tender_analyses", "user_id")
