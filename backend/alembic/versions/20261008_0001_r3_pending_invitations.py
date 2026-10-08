"""R3 Task 1: e-mail invitations to an organization.

Additive and reversible: one new table. Only a SHA-256 of the one-time token is stored.

Revision ID: 20261008_0001_r3_pending_invitations
Revises: 20261005_0001_d2_05_eoi_drafts
Create Date: 2026-10-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261008_0001_r3_pending_invitations"
down_revision: Union[str, None] = "20261005_0001_d2_05_eoi_drafts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OPEN = sa.text("accepted_at IS NULL AND revoked_at IS NULL")


def upgrade() -> None:
    op.create_table(
        "pending_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("OWNER", "MEMBER", name="membership_role", create_type=False),
            nullable=False,
        ),
        sa.Column("invited_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True),
            server_default=sa.text("now() + interval '14 days'"), nullable=False,
        ),
        sa.Column("send_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("accepted_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "email = lower(email) AND email = btrim(email) AND email ~ '^[^@\\s]+@[^@\\s]+$'",
            name="ck_pending_invitation_email",
        ),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_pending_invitation_token_hash"),
        sa.CheckConstraint("send_count >= 1", name="ck_pending_invitation_send_count"),
        sa.CheckConstraint(
            "NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)", name="ck_pending_invitation_terminal"
        ),
        sa.CheckConstraint(
            "(accepted_at IS NULL) = (accepted_membership_id IS NULL)",
            name="ck_pending_invitation_accepted_membership",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["invited_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_pending_invitation_inviter_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["accepted_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["accepted_membership_id"], ["memberships.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "uq_pending_invitation_open_email", "pending_invitations", ["organization_id", "email"],
        unique=True, postgresql_where=OPEN,
    )
    op.create_index("ix_pending_invitations_email_open", "pending_invitations", ["email"], postgresql_where=OPEN)
    op.create_index(
        "ix_pending_invitations_organization_created", "pending_invitations", ["organization_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_pending_invitations_organization_created", table_name="pending_invitations")
    op.drop_index("ix_pending_invitations_email_open", table_name="pending_invitations")
    op.drop_index("uq_pending_invitation_open_email", table_name="pending_invitations")
    op.drop_table("pending_invitations")
