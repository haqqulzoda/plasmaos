"""R3 Task 4: the e-mail channel of the notification outbox and per-user preferences.

Additive and reversible: two new tables.

Revision ID: 20261010_0001_r3_email_notifications
Revises: 20261009_0001_r3_cv_library_drafts
Create Date: 2026-10-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261010_0001_r3_email_notifications"
down_revision: Union[str, None] = "20261009_0001_r3_cv_library_drafts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_email", sa.String(length=255), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('TEAM_INVITATION','ANALYSIS_COMPLETED','ANALYSIS_FAILED','EOI_DRAFT_READY','DAILY_DIGEST')",
            name="ck_email_delivery_kind",
        ),
        sa.CheckConstraint("category IN ('TEAM','ANALYSIS','EOI','DIGEST')", name="ck_email_delivery_category"),
        sa.CheckConstraint("state IN ('PENDING','SENDING','SENT','FAILED','BOUNCED')", name="ck_email_delivery_state"),
        sa.CheckConstraint("locale IN ('en','ru','uz','ar')", name="ck_email_delivery_locale"),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 16384", name="ck_email_delivery_payload"
        ),
        sa.CheckConstraint(
            "secret_ciphertext IS NULL OR state IN ('PENDING','SENDING')", name="ck_email_delivery_secret_until_terminal"
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_email_delivery_attempts"),
        sa.CheckConstraint("(state = 'SENT') = (sent_at IS NOT NULL)", name="ck_email_delivery_sent"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index(
        "ix_email_deliveries_due", "email_deliveries", ["next_attempt_at"],
        postgresql_where=sa.text("state IN ('PENDING','SENDING')"),
    )
    op.create_index("ix_email_deliveries_user_created", "email_deliveries", ["user_id", "created_at"])
    op.create_index("ix_email_deliveries_state_created", "email_deliveries", ["state", "created_at"])
    op.create_table(
        "email_notification_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_enabled", sa.Boolean(), nullable=True),
        sa.Column("eoi_enabled", sa.Boolean(), nullable=True),
        sa.Column("digest_enabled", sa.Boolean(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("email_notification_preferences")
    op.drop_index("ix_email_deliveries_state_created", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_user_created", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_due", table_name="email_deliveries")
    op.drop_table("email_deliveries")
