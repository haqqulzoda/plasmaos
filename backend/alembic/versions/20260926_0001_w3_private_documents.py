"""W3 private document authority and uploaded pursuit context.

Revision ID: 20260926_0001_w3_private_documents
Revises: 20260925_0002_w2_organization_pursuit
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260926_0001_w3_private_documents"
down_revision: Union[str, None] = "20260925_0002_w2_organization_pursuit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


document_role = postgresql.ENUM(
    "RFP", "TOR", "NOTICE", "ADDENDUM", "CLARIFICATION", "FORM", "ANNEX", "OTHER",
    name="private_document_role",
    create_type=False,
)
document_state = postgresql.ENUM("ACTIVE", "ARCHIVED", name="private_document_state", create_type=False)
processing_state = postgresql.ENUM(
    "UPLOADING", "QUEUED", "CHECKING", "EXTRACTING", "READY", "PARTIAL", "FAILED",
    name="document_processing_state",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(
        "RFP", "TOR", "NOTICE", "ADDENDUM", "CLARIFICATION", "FORM", "ANNEX", "OTHER",
        name="private_document_role",
    ).create(bind, checkfirst=True)
    postgresql.ENUM("ACTIVE", "ARCHIVED", name="private_document_state").create(bind, checkfirst=True)
    postgresql.ENUM(
        "UPLOADING", "QUEUED", "CHECKING", "EXTRACTING", "READY", "PARTIAL", "FAILED",
        name="document_processing_state",
    ).create(bind, checkfirst=True)

    op.create_unique_constraint(
        "uq_organization_pursuits_id_organization",
        "organization_pursuits",
        ["id", "organization_id"],
    )

    op.create_table(
        "private_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pursuit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", document_role, nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("state", document_state, nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_private_document_pursuit_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_private_document_creator_organization",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "organization_id", name="uq_private_documents_id_organization"),
        sa.CheckConstraint(
            "(state = 'ACTIVE' AND archived_at IS NULL) OR "
            "(state = 'ARCHIVED' AND archived_at IS NOT NULL)",
            name="ck_private_document_archive_state",
        ),
    )
    op.create_index("ix_private_documents_pursuit_state", "private_documents", ["pursuit_id", "state"])

    op.create_table(
        "private_document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("private_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("safe_display_filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(150), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("uploader_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["private_document_id", "organization_id"],
            ["private_documents.id", "private_documents.organization_id"],
            name="fk_private_document_version_document_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uploader_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_private_document_version_uploader_organization",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("private_document_id", "version_number", name="uq_private_document_version_number"),
        sa.UniqueConstraint("id", "private_document_id", name="uq_private_document_version_document"),
        sa.UniqueConstraint("storage_key", name="uq_private_document_versions_storage_key"),
        sa.CheckConstraint("version_number >= 1", name="ck_private_document_version_positive"),
        sa.CheckConstraint("byte_size > 0", name="ck_private_document_version_size_positive"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_private_document_version_sha256"),
    )
    op.create_index(
        "ix_private_document_versions_organization_hash",
        "private_document_versions",
        ["organization_id", "sha256"],
    )
    op.create_foreign_key(
        "fk_private_document_current_version",
        "private_documents",
        "private_document_versions",
        ["current_version_id", "id"],
        ["id", "private_document_id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "private_document_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pursuit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", processing_state, nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_private_document_batch_pursuit_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_private_document_batch_requester_organization",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "file_count > 0 AND processed_count >= 0 AND failed_count >= 0 "
            "AND processed_count <= file_count AND failed_count <= file_count",
            name="ck_private_document_batch_counts",
        ),
    )
    op.create_index(
        "ix_private_document_batches_pursuit_created", "private_document_batches", ["pursuit_id", "created_at"]
    )

    op.create_table(
        "private_document_processing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", processing_state, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dispatch_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_dispatch_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("last_error_detail", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["private_document_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_version_id"], ["private_document_versions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("document_version_id", name="uq_private_document_processing_job_version"),
        sa.CheckConstraint("attempt_count >= 0 AND dispatch_attempt_count >= 0", name="ck_private_document_job_attempts"),
    )
    op.create_index(
        "ix_private_document_jobs_dispatch",
        "private_document_processing_jobs",
        ["next_dispatch_at"],
        postgresql_where=sa.text("state IN ('QUEUED','CHECKING','EXTRACTING')"),
    )

    op.create_table(
        "private_document_processing_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("malware_scan_status", sa.String(20), nullable=False),
        sa.Column("malware_scanner", sa.String(100), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("page_count_status", sa.String(20), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extracted_sha256", sa.String(64), nullable=True),
        sa.Column("extraction_error_code", sa.String(80), nullable=True),
        sa.Column("extraction_error_detail", sa.String(500), nullable=True),
        sa.Column("parser_name", sa.String(100), nullable=True),
        sa.Column("parser_version", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["job_id"], ["private_document_processing_jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_version_id"], ["private_document_versions.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("malware_scan_status IN ('PENDING','CLEAN','INFECTED','ERROR')", name="ck_private_document_result_scan"),
        sa.CheckConstraint("page_count IS NULL OR page_count >= 1", name="ck_private_document_result_pages"),
        sa.CheckConstraint("page_count_status IN ('KNOWN','UNKNOWN')", name="ck_private_document_result_page_status"),
    )

    op.create_table(
        "pursuit_tender_contexts",
        sa.Column("pursuit_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(500)),
        sa.Column("buyer", sa.String(500)),
        sa.Column("declared_funder", sa.String(255)),
        sa.Column("country", sa.String(255)),
        sa.Column("reference", sa.String(255)),
        sa.Column("procurement_stage", sa.String(255)),
        sa.Column("external_deadline", sa.DateTime(timezone=True)),
        sa.Column("deadline_timezone", sa.String(100)),
        sa.Column("source_url", sa.String(2000)),
        sa.Column("confirmed_fields", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("confirmed_by_membership_id", postgresql.UUID(as_uuid=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_pursuit_context_pursuit_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_pursuit_context_confirmer_organization",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("jsonb_typeof(confirmed_fields) = 'object'", name="ck_pursuit_context_confirmed_fields"),
    )
    op.create_index("ix_pursuit_context_organization", "pursuit_tender_contexts", ["organization_id", "updated_at"])

    op.create_table(
        "pursuit_context_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pursuit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field_name", sa.String(40), nullable=False),
        sa.Column("suggested_value", sa.String(2000), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("evidence_span", sa.String(1000)),
        sa.Column("confidence", sa.Float()),
        sa.Column("review_state", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_version_id"], ["private_document_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_pursuit_context_suggestion_organization",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "field_name IN ('title','buyer','declared_funder','country','reference',"
            "'procurement_stage','external_deadline','deadline_timezone','source_url')",
            name="ck_pursuit_context_suggestion_field",
        ),
        sa.CheckConstraint("page_number IS NULL OR page_number >= 1", name="ck_pursuit_context_suggestion_page"),
        sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_pursuit_context_suggestion_confidence"),
        sa.CheckConstraint("review_state IN ('PROVISIONAL','ACCEPTED','REJECTED')", name="ck_pursuit_context_suggestion_review"),
    )
    op.create_index("ix_pursuit_context_suggestions_pursuit", "pursuit_context_suggestions", ["pursuit_id", "created_at"])

    op.create_table(
        "membership_lifecycle_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("actor_membership_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("previous_role", sa.String(20)),
        sa.Column("new_role", sa.String(20)),
        sa.Column("previous_state", sa.String(20)),
        sa.Column("new_state", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_membership_id"], ["memberships.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "action IN ('W2_BACKFILL','INVITE','REINVITE','ACTIVATE','ROLE_CHANGE','REVOKE')",
            name="ck_membership_lifecycle_event_action",
        ),
    )
    op.create_index("ix_membership_lifecycle_events_membership_created", "membership_lifecycle_events", ["membership_id", "created_at"])
    op.create_index("ix_membership_lifecycle_events_organization_created", "membership_lifecycle_events", ["organization_id", "created_at"])

    op.execute(
        """
        INSERT INTO membership_lifecycle_events (
            id, organization_id, membership_id, action,
            new_role, new_state, created_at
        )
        SELECT
            md5('plasma:w3:membership-event:' || m.id::text)::uuid,
            m.organization_id, m.id, 'W2_BACKFILL',
            m.role::text, m.state::text, m.created_at
        FROM memberships m
        ON CONFLICT (id) DO NOTHING
        """
    )

    op.execute(
        """
        CREATE FUNCTION reject_private_document_version_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'private document versions are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER private_document_versions_immutable
        BEFORE UPDATE OR DELETE ON private_document_versions
        FOR EACH ROW EXECUTE FUNCTION reject_private_document_version_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_membership_lifecycle_event_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'membership lifecycle events are append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER membership_lifecycle_events_append_only
        BEFORE UPDATE OR DELETE ON membership_lifecycle_events
        FOR EACH ROW EXECUTE FUNCTION reject_membership_lifecycle_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS membership_lifecycle_events_append_only ON membership_lifecycle_events")
    op.execute("DROP FUNCTION IF EXISTS reject_membership_lifecycle_event_mutation()")
    op.execute("DROP TRIGGER IF EXISTS private_document_versions_immutable ON private_document_versions")
    op.execute("DROP FUNCTION IF EXISTS reject_private_document_version_mutation()")
    op.drop_table("membership_lifecycle_events")
    op.drop_table("pursuit_context_suggestions")
    op.drop_table("pursuit_tender_contexts")
    op.drop_table("private_document_processing_results")
    op.drop_table("private_document_processing_jobs")
    op.drop_table("private_document_batches")
    op.drop_constraint("fk_private_document_current_version", "private_documents", type_="foreignkey")
    op.drop_table("private_document_versions")
    op.drop_table("private_documents")
    op.drop_constraint(
        "uq_organization_pursuits_id_organization", "organization_pursuits", type_="unique"
    )
    bind = op.get_bind()
    postgresql.ENUM(name="document_processing_state").drop(bind, checkfirst=True)
    postgresql.ENUM(name="private_document_state").drop(bind, checkfirst=True)
    postgresql.ENUM(name="private_document_role").drop(bind, checkfirst=True)
