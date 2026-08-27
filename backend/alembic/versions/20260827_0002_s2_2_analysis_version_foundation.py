"""add immutable analysis versions and evidence/document snapshots

Revision ID: 20260827_0002_s2_2_analysis_version_foundation
Revises: 20260827_0001_s2_1_compliance_ownership
Create Date: 2026-08-27 16:00:00.000000

The set-based backfill creates one truthful LEGACY_BACKFILL v1 for every
TenderAnalysis. It copies only provenance already persisted on the row, makes
no network/LLM calls, and never rewrites parent analysis data.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260827_0002_s2_2_analysis_version_foundation"
down_revision: Union[str, None] = "20260827_0001_s2_1_compliance_ownership"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "supersedes_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("origin", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("analysis_schema_version", sa.String(length=100), nullable=True),
        sa.Column("pipeline_version", sa.String(length=100), nullable=True),
        sa.Column("model_provider", sa.String(length=100), nullable=True),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("model_version", sa.String(length=200), nullable=True),
        sa.Column("prompt_template_version", sa.String(length=100), nullable=True),
        sa.Column("prompt_template_hash", sa.String(length=64), nullable=True),
        sa.Column("provenance_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("tender_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("company_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("result_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("output_hash", sa.String(length=64), nullable=True),
        sa.Column("evidence_hash", sa.String(length=64), nullable=True),
        sa.Column("document_set_hash", sa.String(length=64), nullable=True),
        sa.Column("version_hash", sa.String(length=64), nullable=True),
        sa.Column("snapshot_completeness", sa.String(length=30), nullable=False),
        sa.Column(
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "version_number >= 1",
            name="ck_analysis_versions_version_number_positive",
        ),
        sa.CheckConstraint(
            "supersedes_version_id IS NULL OR supersedes_version_id <> id",
            name="ck_analysis_versions_not_self_superseding",
        ),
        sa.CheckConstraint(
            "origin IN ('LEGACY_BACKFILL', 'RUNTIME_ANALYSIS', "
            "'RUNTIME_REANALYSIS')",
            name="ck_analysis_versions_origin_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('COMPLETED', 'NEEDS_REVIEW', 'FAILED')",
            name="ck_analysis_versions_status_allowed",
        ),
        sa.CheckConstraint(
            "snapshot_completeness IN ('COMPLETE', 'PARTIAL', "
            "'LEGACY_BACKFILL')",
            name="ck_analysis_versions_snapshot_completeness_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["tender_analyses.id"],
            name="analysis_versions_analysis_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="analysis_versions_requested_by_user_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_version_id"],
            ["analysis_versions.id"],
            name="analysis_versions_supersedes_version_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="analysis_versions_pkey"),
        sa.UniqueConstraint(
            "analysis_id",
            "version_number",
            name="uq_analysis_versions_analysis_version_number",
        ),
        sa.UniqueConstraint(
            "supersedes_version_id",
            name="uq_analysis_versions_supersedes_version_id",
        ),
    )
    op.create_index(
        "ix_analysis_versions_analysis_created",
        "analysis_versions",
        ["analysis_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_versions_requested_by_user_id",
        "analysis_versions",
        ["requested_by_user_id"],
        unique=False,
    )

    op.create_table(
        "analysis_version_document_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "analysis_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("tender_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_system", sa.String(length=50), nullable=False),
        sa.Column("source_document_key", sa.String(length=200), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column("media_type", sa.String(length=150), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("storage_reference", sa.String(length=1000), nullable=True),
        sa.Column("storage_version", sa.String(length=200), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_metadata", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["analysis_version_id"],
            ["analysis_versions.id"],
            name="analysis_version_documents_version_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tender_document_id"],
            ["tender_documents.id"],
            name="analysis_version_documents_tender_document_id_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="analysis_version_document_snapshots_pkey"
        ),
    )
    op.create_index(
        "ix_analysis_version_documents_version",
        "analysis_version_document_snapshots",
        ["analysis_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_version_documents_tender_document",
        "analysis_version_document_snapshots",
        ["tender_document_id"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO analysis_versions (
            id,
            analysis_id,
            version_number,
            supersedes_version_id,
            origin,
            status,
            analysis_schema_version,
            pipeline_version,
            model_provider,
            model_name,
            model_version,
            prompt_template_version,
            prompt_template_hash,
            provenance_snapshot,
            tender_snapshot,
            company_snapshot,
            result_snapshot,
            evidence_snapshot,
            input_hash,
            output_hash,
            evidence_hash,
            document_set_hash,
            version_hash,
            snapshot_completeness,
            requested_by_user_id,
            created_at,
            completed_at
        )
        SELECT
            analysis.id,
            analysis.id,
            1,
            NULL,
            'LEGACY_BACKFILL',
            CASE COALESCE(analysis.analysis_json->>'analysis_status', 'completed')
                WHEN 'failed' THEN 'FAILED'
                WHEN 'needs_review' THEN 'NEEDS_REVIEW'
                ELSE 'COMPLETED'
            END,
            analysis.analysis_json #>>
                '{reproducibility_snapshot,engine_metadata,extractor_schema_version}',
            NULL,
            NULL,
            analysis.analysis_json #>>
                '{reproducibility_snapshot,engine_metadata,requirement_model_name}',
            NULL,
            analysis.analysis_json #>>
                '{reproducibility_snapshot,engine_metadata,prompt_schema_version}',
            NULL,
            COALESCE(
                analysis.analysis_json->'reproducibility_snapshot',
                '{}'::jsonb
            ),
            jsonb_build_object(
                'tender_id', tender.id,
                'source_system', tender.source_system,
                'external_id', tender.external_id,
                'canonical_source_key', tender.canonical_source_key,
                'title', tender.title,
                'buyer', tender.buyer,
                'deadline', tender.deadline,
                'currency', tender.currency,
                'budget', tender.budget,
                'procurement_method', tender.procurement_method,
                'notice_type', tender.notice_type,
                'project_id', tender.project_id,
                'source_url', tender.source_url
            ),
            jsonb_build_object(
                'company_name', analysis.company_name,
                'company_profile_id', analysis.company_profile_id
            ),
            analysis.analysis_json,
            jsonb_build_object(
                'evidence_validation', analysis.analysis_json->'evidence_validation',
                'hybrid_compliance', analysis.analysis_json->'hybrid_compliance',
                'requirement_route_summary', analysis.analysis_json #>
                    '{reproducibility_snapshot,requirement_route_summary}'
            ),
            analysis.content_hash,
            NULL,
            NULL,
            analysis.analysis_json #>>
                '{reproducibility_snapshot,input_fingerprints,document_order_fingerprint}',
            NULL,
            'LEGACY_BACKFILL',
            NULL,
            analysis.created_at,
            analysis.created_at
        FROM tender_analyses AS analysis
        JOIN tenders AS tender ON tender.id = analysis.tender_id
        """
    )

    # Only materialize document snapshots that were already persisted in the
    # historical reproducibility payload. Live document fields are not copied,
    # because their migration-time values do not prove analysis-time identity.
    op.execute(
        """
        INSERT INTO analysis_version_document_snapshots (
            id,
            analysis_version_id,
            tender_document_id,
            source_system,
            source_document_key,
            source_url,
            filename,
            media_type,
            content_hash,
            storage_reference,
            storage_version,
            fetched_at,
            observed_at,
            snapshot_metadata,
            created_at
        )
        SELECT
            (
                SUBSTR(MD5(analysis.id::text || ':' || fingerprint.ordinality::text), 1, 8)
                || '-' || SUBSTR(MD5(analysis.id::text || ':' || fingerprint.ordinality::text), 9, 4)
                || '-' || SUBSTR(MD5(analysis.id::text || ':' || fingerprint.ordinality::text), 13, 4)
                || '-' || SUBSTR(MD5(analysis.id::text || ':' || fingerprint.ordinality::text), 17, 4)
                || '-' || SUBSTR(MD5(analysis.id::text || ':' || fingerprint.ordinality::text), 21, 12)
            )::uuid,
            analysis.id,
            document.id,
            tender.source_system,
            NULL,
            NULL,
            fingerprint.value->>'display_name',
            NULL,
            fingerprint.value->>'parsed_text_sha256',
            NULL,
            NULL,
            NULL,
            NULL,
            fingerprint.value,
            analysis.created_at
        FROM tender_analyses AS analysis
        JOIN tenders AS tender ON tender.id = analysis.tender_id
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN jsonb_typeof(
                    analysis.analysis_json #>
                        '{reproducibility_snapshot,input_fingerprints,document_fingerprints}'
                ) = 'array'
                THEN analysis.analysis_json #>
                    '{reproducibility_snapshot,input_fingerprints,document_fingerprints}'
                ELSE '[]'::jsonb
            END
        ) WITH ORDINALITY AS fingerprint(value, ordinality)
        LEFT JOIN tender_documents AS document
          ON document.tender_id = analysis.tender_id
         AND document.id::text = fingerprint.value->>'document_id'
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analysis_version_documents_tender_document",
        table_name="analysis_version_document_snapshots",
    )
    op.drop_index(
        "ix_analysis_version_documents_version",
        table_name="analysis_version_document_snapshots",
    )
    op.drop_table("analysis_version_document_snapshots")
    op.drop_index(
        "ix_analysis_versions_requested_by_user_id",
        table_name="analysis_versions",
    )
    op.drop_index(
        "ix_analysis_versions_analysis_created",
        table_name="analysis_versions",
    )
    op.drop_table("analysis_versions")
