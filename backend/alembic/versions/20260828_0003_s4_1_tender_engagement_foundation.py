"""add canonical tender engagement foundation

Revision ID: 20260828_0003_s4_1_tender_engagement_foundation
Revises: 20260828_0002_s3_4_admin_audit_hardening
Create Date: 2026-08-28 17:00:00.000000

This migration is schema-only. Existing proposals are not deterministic proof
of company engagement or submission, so no engagement rows are fabricated.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260828_0003_s4_1_tender_engagement_foundation"
down_revision: Union[str, None] = "20260828_0002_s3_4_admin_audit_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ENGAGEMENT_STATUSES = (
    "SAVED",
    "EVALUATING",
    "PREPARING",
    "SUBMITTED",
    "WON",
    "LOST",
    "DISMISSED",
)
ENGAGEMENT_ORIGINS = (
    "MANUAL_SAVE",
    "MANUAL_EVALUATION",
    "BID_PREPARATION",
    "LEGACY_PROPOSAL",
    "OTHER_EXPLICIT_USER_ACTION",
)


def upgrade() -> None:
    # Required by PostgreSQL for the composite profile/user ownership FK. The
    # pair is already unique in practice because id is the primary key.
    op.create_unique_constraint(
        "uq_company_profiles_id_user_id",
        "company_profiles",
        ["id", "user_id"],
    )

    engagement_status = postgresql.ENUM(
        *ENGAGEMENT_STATUSES,
        name="tender_engagement_status",
        create_type=False,
    )
    engagement_origin = postgresql.ENUM(
        *ENGAGEMENT_ORIGINS,
        name="tender_engagement_origin",
        create_type=False,
    )
    engagement_status.create(op.get_bind(), checkfirst=True)
    engagement_origin.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tender_engagements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "company_profile_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "tender_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("status", engagement_status, nullable=False),
        sa.Column("origin", engagement_origin, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "status_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="tender_engagements_user_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_profile_id", "user_id"],
            ["company_profiles.id", "company_profiles.user_id"],
            name="fk_tender_engagements_profile_user",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name="tender_engagements_tender_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="tender_engagements_pkey"),
        sa.UniqueConstraint(
            "user_id",
            "company_profile_id",
            "tender_id",
            name="uq_tender_engagements_owner_tender",
        ),
    )
    op.create_index(
        "ix_tender_engagements_user_id",
        "tender_engagements",
        ["user_id"],
    )
    op.create_index(
        "ix_tender_engagements_company_profile_id",
        "tender_engagements",
        ["company_profile_id"],
    )
    op.create_index(
        "ix_tender_engagements_tender_id",
        "tender_engagements",
        ["tender_id"],
    )
    op.create_index(
        "ix_tender_engagements_status",
        "tender_engagements",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tender_engagements_status",
        table_name="tender_engagements",
    )
    op.drop_index(
        "ix_tender_engagements_tender_id",
        table_name="tender_engagements",
    )
    op.drop_index(
        "ix_tender_engagements_company_profile_id",
        table_name="tender_engagements",
    )
    op.drop_index(
        "ix_tender_engagements_user_id",
        table_name="tender_engagements",
    )
    op.drop_table("tender_engagements")
    postgresql.ENUM(name="tender_engagement_origin").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(name="tender_engagement_status").drop(
        op.get_bind(), checkfirst=True
    )
    op.drop_constraint(
        "uq_company_profiles_id_user_id",
        "company_profiles",
        type_="unique",
    )
