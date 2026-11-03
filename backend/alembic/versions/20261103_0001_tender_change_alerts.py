"""Tender-change alerts: record source changes to pursued tenders and e-mail them.

Additive and reversible: one new table and one more e-mail kind.

Revision ID: 20261103_0001_tender_change_alerts
Revises: 20261025_0001_b1_billing
Create Date: 2026-11-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261103_0001_tender_change_alerts"
down_revision: Union[str, None] = "20261025_0001_b1_billing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_EMAIL_KINDS = (
    "'TEAM_INVITATION','ANALYSIS_COMPLETED','ANALYSIS_FAILED','EOI_DRAFT_READY','DAILY_DIGEST','SIGN_IN_CODE',"
    "'ADMIN_ALERT','BILLING_INVOICE','BILLING_REMINDER','BILLING_WELCOME','BILLING_SUSPENDED'"
)
NEW_EMAIL_KINDS = OLD_EMAIL_KINDS + ",'TENDER_CHANGED'"


def upgrade() -> None:
    op.create_table(
        "tender_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tender_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_kinds", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(change_kinds) = 'array' AND jsonb_array_length(change_kinds) BETWEEN 1 AND 3",
            name="ck_tender_change_kinds",
        ),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tender_changes_tender_detected", "tender_changes", ["tender_id", "detected_at"])
    op.drop_constraint("ck_email_delivery_kind", "email_deliveries", type_="check")
    op.create_check_constraint("ck_email_delivery_kind", "email_deliveries", f"kind IN ({NEW_EMAIL_KINDS})")


def downgrade() -> None:
    op.execute("DELETE FROM email_deliveries WHERE kind = 'TENDER_CHANGED'")
    op.drop_constraint("ck_email_delivery_kind", "email_deliveries", type_="check")
    op.create_check_constraint("ck_email_delivery_kind", "email_deliveries", f"kind IN ({OLD_EMAIL_KINDS})")
    op.drop_index("ix_tender_changes_tender_detected", table_name="tender_changes")
    op.drop_table("tender_changes")
