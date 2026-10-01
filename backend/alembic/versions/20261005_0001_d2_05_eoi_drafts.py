"""D2-05 Expression of Interest drafts and their rendered artifacts.

Additive and reversible. Both tables are append-only: a trigger rejects every
UPDATE and DELETE, so a draft and its files always describe what was generated.

Revision ID: 20261005_0001_d2_05_eoi_drafts
Revises: 20261004_0001_d2_01_own_experience
Create Date: 2026-10-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261005_0001_d2_05_eoi_drafts"
down_revision: Union[str, None] = "20261004_0001_d2_01_own_experience"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("eoi_drafts", "eoi_draft_artifacts")


def upgrade() -> None:
    op.create_table(
        "eoi_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pursuit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_eoi_draft_version"),
        sa.CheckConstraint("language IN ('en', 'ru')", name="ck_eoi_draft_language"),
        sa.CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$'", name="ck_eoi_draft_manifest_sha"),
        sa.CheckConstraint(
            "jsonb_typeof(inputs) = 'object' AND jsonb_typeof(manifest) = 'object'", name="ck_eoi_draft_json"
        ),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["pursuit_analysis_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_eoi_draft_pursuit_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_eoi_draft_actor_organization", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pursuit_id", "version", name="uq_eoi_draft_pursuit_version"),
        sa.UniqueConstraint("id", "organization_id", name="uq_eoi_draft_id_organization"),
    )
    op.create_index("ix_eoi_drafts_pursuit_created", "eoi_drafts", ["organization_id", "pursuit_id", "created_at"])
    op.create_table(
        "eoi_draft_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(length=150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("format IN ('DOCX', 'PDF')", name="ck_eoi_artifact_format"),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_eoi_artifact_sha"),
        sa.CheckConstraint("byte_size > 0", name="ck_eoi_artifact_size"),
        sa.ForeignKeyConstraint(
            ["draft_id", "organization_id"], ["eoi_drafts.id", "eoi_drafts.organization_id"],
            name="fk_eoi_artifact_draft_organization", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", "format", name="uq_eoi_artifact_draft_format"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_eoi_artifacts_draft", "eoi_draft_artifacts", ["draft_id"])
    op.execute(
        """
        CREATE FUNCTION reject_eoi_immutable_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'EOI drafts are immutable';
        END;
        $$;
        """
    )
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_eoi_immutable_mutation()"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_eoi_immutable_mutation()")
    op.drop_index("ix_eoi_artifacts_draft", table_name="eoi_draft_artifacts")
    op.drop_table("eoi_draft_artifacts")
    op.drop_index("ix_eoi_drafts_pursuit_created", table_name="eoi_drafts")
    op.drop_table("eoi_drafts")
