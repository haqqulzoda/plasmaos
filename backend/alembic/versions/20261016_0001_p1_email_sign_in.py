"""P1: e-mail one-time-code sign-in, rotating refresh tokens, no manual user approval.

Additive: two tables (``email_sign_in_challenges``, ``auth_refresh_tokens``) and two more
values in the e-mail outbox checks (kind ``SIGN_IN_CODE``, category ``AUTH``). Data: every
``pending`` user becomes ``approved`` (one ``USER_APPROVED`` audit event each, actor SYSTEM),
a disabled user who was pending before the disable will be restored as approved, and new rows
default to ``approved``. Downgrade drops the tables and restores the checks and the default;
the approvals stay (an approved account is not made pending again).

Revision ID: 20261016_0001_p1_email_sign_in
Revises: 20261012_0002_s1_product_analytics
Create Date: 2026-10-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261016_0001_p1_email_sign_in"
down_revision: Union[str, None] = "20261012_0002_s1_product_analytics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_KINDS = "'TEAM_INVITATION','ANALYSIS_COMPLETED','ANALYSIS_FAILED','EOI_DRAFT_READY','DAILY_DIGEST'"
NEW_KINDS = OLD_KINDS + ",'SIGN_IN_CODE'"
OLD_CATEGORIES = "'TEAM','ANALYSIS','EOI','DIGEST'"
NEW_CATEGORIES = OLD_CATEGORIES + ",'AUTH'"


def upgrade() -> None:
    op.create_table(
        "email_sign_in_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery", sa.String(length=20), nullable=False),
        sa.Column("requester_ip_hash", sa.String(length=64), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("attempt_count >= 0 AND attempt_count <= 5", name="ck_email_sign_in_attempts"),
        sa.CheckConstraint(
            "delivery IN ('STAGED','NO_CHANNEL','ACCOUNT_BLOCKED','PRIVILEGED')", name="ck_email_sign_in_delivery"
        ),
        sa.CheckConstraint(
            "(closed_at IS NULL AND close_reason IS NULL) OR "
            "(closed_at IS NOT NULL AND close_reason IN ('CONSUMED','SUPERSEDED','LOCKED','EXPIRED'))",
            name="ck_email_sign_in_closed",
        ),
        sa.CheckConstraint("email = lower(email)", name="ck_email_sign_in_email_lower"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_email_sign_in_open_email", "email_sign_in_challenges", ["email"], unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    op.create_index("ix_email_sign_in_email_created", "email_sign_in_challenges", ["email", "created_at"])

    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("sign_in_method", sa.String(length=20), nullable=False),
        sa.Column("family_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("sign_in_method IN ('GOOGLE','EMAIL_CODE')", name="ck_auth_refresh_method"),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoke_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoke_reason IN ('LOGOUT','REUSE_DETECTED','ACCOUNT_STATE','EXPIRED'))",
            name="ck_auth_refresh_revoked",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_auth_refresh_expiry"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_auth_refresh_tokens_family", "auth_refresh_tokens", ["family_id"])
    op.create_index("ix_auth_refresh_tokens_user", "auth_refresh_tokens", ["user_id", "created_at"])

    op.drop_constraint("ck_email_delivery_kind", "email_deliveries", type_="check")
    op.create_check_constraint("ck_email_delivery_kind", "email_deliveries", f"kind IN ({NEW_KINDS})")
    op.drop_constraint("ck_email_delivery_category", "email_deliveries", type_="check")
    op.create_check_constraint("ck_email_delivery_category", "email_deliveries", f"category IN ({NEW_CATEGORIES})")

    # No manual user approval: a verified e-mail approves the account (the organization gate stays).
    op.execute(
        """
        INSERT INTO admin_activity_events (
            id, action, actor_label, actor_type, target_user_id, target_email, target_resource_type,
            target_resource_id, outcome, previous_state, new_state, reason, source, metadata_json
        )
        SELECT gen_random_uuid(), 'USER_APPROVED', 'migration 20261016_0001_p1_email_sign_in', 'SYSTEM', u.id,
               lower(u.email), 'USER', u.id::text, 'SUCCESS',
               jsonb_build_object('approval_status', u.approval_status),
               jsonb_build_object('approval_status', 'approved'),
               'P1: manual user approval removed; every pending account is approved (verified e-mail).',
               'P1_MIGRATION', jsonb_build_object('pre_disabled_status_only', u.approval_status = 'disabled')
        FROM users u
        WHERE u.approval_status = 'pending'
           OR (u.approval_status = 'disabled' AND u.pre_disabled_approval_status = 'pending')
        """
    )
    op.execute(
        "UPDATE users SET approval_status = 'approved', approved_at = coalesce(approved_at, now()) "
        "WHERE approval_status = 'pending'"
    )
    op.execute(
        "UPDATE users SET pre_disabled_approval_status = 'approved' "
        "WHERE approval_status = 'disabled' AND pre_disabled_approval_status = 'pending'"
    )
    op.alter_column("users", "approval_status", server_default=sa.text("'approved'"))


def downgrade() -> None:
    op.alter_column("users", "approval_status", server_default=sa.text("'pending'"))
    op.execute("DELETE FROM email_deliveries WHERE kind = 'SIGN_IN_CODE' OR category = 'AUTH'")
    op.drop_constraint("ck_email_delivery_category", "email_deliveries", type_="check")
    op.create_check_constraint("ck_email_delivery_category", "email_deliveries", f"category IN ({OLD_CATEGORIES})")
    op.drop_constraint("ck_email_delivery_kind", "email_deliveries", type_="check")
    op.create_check_constraint("ck_email_delivery_kind", "email_deliveries", f"kind IN ({OLD_KINDS})")
    op.drop_index("ix_auth_refresh_tokens_user", table_name="auth_refresh_tokens")
    op.drop_index("ix_auth_refresh_tokens_family", table_name="auth_refresh_tokens")
    op.drop_table("auth_refresh_tokens")
    op.drop_index("ix_email_sign_in_email_created", table_name="email_sign_in_challenges")
    op.drop_index("uq_email_sign_in_open_email", table_name="email_sign_in_challenges")
    op.drop_table("email_sign_in_challenges")
