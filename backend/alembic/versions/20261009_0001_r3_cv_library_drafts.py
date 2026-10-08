"""R3 Task 3: organization-library CV documents and reviewable CV drafts.

Smallest change to reuse the existing private-document intake (25 MiB, signature checks,
ClamAV, sandboxed parse, durable jobs): a private document and its batch may have no
pursuit when ``library_kind`` is CV. Pursuit-scoped reads filter by pursuit, so they never
see library documents. One new table holds the proposed, quote-verified CV fields until a
person confirms them into an immutable CVVersion.

Downgrade refuses while library documents exist (their rows cannot regain a pursuit).

Revision ID: 20261009_0001_r3_cv_library_drafts
Revises: 20261008_0001_r3_pending_invitations
Create Date: 2026-10-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261009_0001_r3_cv_library_drafts"
down_revision: Union[str, None] = "20261008_0001_r3_pending_invitations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("private_documents", sa.Column("library_kind", sa.String(length=20), nullable=True))
    op.alter_column("private_documents", "pursuit_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.alter_column("private_document_batches", "pursuit_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.create_check_constraint(
        "ck_private_document_pursuit_or_library",
        "private_documents",
        "(pursuit_id IS NOT NULL AND library_kind IS NULL) OR (pursuit_id IS NULL AND library_kind = 'CV')",
    )
    op.create_index(
        "ix_private_documents_library", "private_documents", ["organization_id", "library_kind", "created_at"],
        postgresql_where=sa.text("library_kind IS NOT NULL"),
    )
    op.create_table(
        "candidate_cv_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expert_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("private_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("proposal", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column(
            "extraction_summary", postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"), nullable=False,
        ),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confirmed_cv_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "state IN ('PROCESSING_DOCUMENT','QUEUED','EXTRACTING','READY','FAILED','CONFIRMED')",
            name="ck_cv_draft_state",
        ),
        sa.CheckConstraint(
            "(state = 'CONFIRMED') = (confirmed_cv_version_id IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_cv_draft_confirmed",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(proposal) = 'object' AND jsonb_typeof(extraction_summary) = 'object'",
            name="ck_cv_draft_json",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_cv_draft_attempts"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["expert_id"], ["candidate_experts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["confirmed_cv_version_id"], ["candidate_cv_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["document_version_id", "organization_id"],
            ["private_document_versions.id", "private_document_versions.organization_id"],
            name="fk_cv_draft_version_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["private_document_id", "organization_id"],
            ["private_documents.id", "private_documents.organization_id"],
            name="fk_cv_draft_document_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_cv_draft_creator_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_cv_draft_confirmer_organization", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_version_id"),
    )
    op.create_index("ix_cv_drafts_organization_created", "candidate_cv_drafts", ["organization_id", "created_at"])
    op.create_index("ix_cv_drafts_expert", "candidate_cv_drafts", ["expert_id"])
    op.create_index(
        "ix_cv_drafts_due", "candidate_cv_drafts", ["next_attempt_at"],
        postgresql_where=sa.text("state IN ('QUEUED','EXTRACTING')"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM private_documents WHERE library_kind IS NOT NULL")).scalar():
        raise RuntimeError("library CV documents exist; they cannot be given a pursuit, so this downgrade refuses")
    op.drop_index("ix_cv_drafts_due", table_name="candidate_cv_drafts")
    op.drop_index("ix_cv_drafts_expert", table_name="candidate_cv_drafts")
    op.drop_index("ix_cv_drafts_organization_created", table_name="candidate_cv_drafts")
    op.drop_table("candidate_cv_drafts")
    op.drop_index("ix_private_documents_library", table_name="private_documents")
    op.drop_constraint("ck_private_document_pursuit_or_library", "private_documents", type_="check")
    op.alter_column("private_document_batches", "pursuit_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.alter_column("private_documents", "pursuit_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_column("private_documents", "library_kind")
