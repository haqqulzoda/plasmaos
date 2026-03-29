"""add_tender_sync_jobs_table

Revision ID: 9f3d2f4b6a10
Revises: 27fc6790093d
Create Date: 2026-03-29 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9f3d2f4b6a10"
down_revision: Union[str, None] = "27fc6790093d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tender_sync_status = postgresql.ENUM(
        "PENDING",
        "IN_PROGRESS",
        "SUCCESS",
        "FAILED",
        name="tender_sync_status",
    )
    tender_sync_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tender_sync_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.String(length=100), nullable=False),
        sa.Column("tender_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "PENDING",
                "IN_PROGRESS",
                "SUCCESS",
                "FAILED",
                name="tender_sync_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )

    op.create_check_constraint(
        "ck_tender_sync_jobs_progress_range",
        "tender_sync_jobs",
        "progress >= 0 AND progress <= 100",
    )
    op.create_index("ix_tender_sync_jobs_tender_id", "tender_sync_jobs", ["tender_id"], unique=False)
    op.create_index("ix_tender_sync_jobs_user_id", "tender_sync_jobs", ["user_id"], unique=False)
    op.create_index("ix_tender_sync_jobs_status", "tender_sync_jobs", ["status"], unique=False)
    op.create_index(
        "uq_tender_sync_jobs_active_user_tender",
        "tender_sync_jobs",
        ["user_id", "tender_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'IN_PROGRESS')"),
    )


def downgrade() -> None:
    op.drop_index("uq_tender_sync_jobs_active_user_tender", table_name="tender_sync_jobs")
    op.drop_index("ix_tender_sync_jobs_status", table_name="tender_sync_jobs")
    op.drop_index("ix_tender_sync_jobs_user_id", table_name="tender_sync_jobs")
    op.drop_index("ix_tender_sync_jobs_tender_id", table_name="tender_sync_jobs")
    op.drop_constraint("ck_tender_sync_jobs_progress_range", "tender_sync_jobs", type_="check")
    op.drop_table("tender_sync_jobs")

    tender_sync_status = postgresql.ENUM(
        "PENDING",
        "IN_PROGRESS",
        "SUCCESS",
        "FAILED",
        name="tender_sync_status",
    )
    tender_sync_status.drop(op.get_bind(), checkfirst=True)
