"""add World Bank Project enrichment and source-neutral leadership history

Revision ID: 20260826_0002_s1_2_wb_project_enrichment
Revises: 20260826_0001_s1_1_project_foundation
Create Date: 2026-08-26 12:00:00.000000

This migration is database-only. It performs no network requests and creates
no ProjectRoleAssignment rows.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260826_0002_s1_2_wb_project_enrichment"
down_revision: Union[str, None] = "20260826_0001_s1_1_project_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("region", sa.String(length=100), nullable=True))
    op.add_column(
        "projects",
        sa.Column("project_status", sa.String(length=50), nullable=True),
    )
    op.add_column("projects", sa.Column("approval_date", sa.Date(), nullable=True))
    op.add_column("projects", sa.Column("closing_date", sa.Date(), nullable=True))
    op.add_column("projects", sa.Column("borrower", sa.Text(), nullable=True))
    op.add_column(
        "projects",
        sa.Column("implementing_agencies", sa.JSON(), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column(
            "enrichment_status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'never_attempted'"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "enrichment_last_attempted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "projects",
        sa.Column("last_enriched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("enrichment_failure_class", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column(
            "enrichment_source_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "projects",
        sa.Column("enrichment_fields_obtained", sa.JSON(), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("enrichment_fields_missing", sa.JSON(), nullable=True),
    )
    op.create_check_constraint(
        "ck_projects_enrichment_status_allowed",
        "projects",
        "enrichment_status IN ('never_attempted', 'queued', 'running', "
        "'successful', 'partial', 'source_unavailable', 'failed', 'stale')",
    )
    op.create_index(
        "ix_projects_source_enrichment_status",
        "projects",
        ["source_system", "enrichment_status", "last_enriched_at"],
        unique=False,
    )

    op.create_table(
        "project_role_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.String(length=50), nullable=False),
        sa.Column("assignment_key", sa.String(length=64), nullable=False),
        sa.Column("source_person_id", sa.String(length=200), nullable=True),
        sa.Column("display_name", sa.String(length=300), nullable=False),
        sa.Column("native_role", sa.String(length=150), nullable=False),
        sa.Column("canonical_role", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=100), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("source_document_id", sa.String(length=200), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source_system IN ('uzex', 'world_bank', 'adb', 'giz', 'ebrd')",
            name="ck_project_role_assignments_source_system_allowed",
        ),
        sa.CheckConstraint(
            "canonical_role IN ('TASK_TEAM_LEADER', 'CO_TASK_TEAM_LEADER', "
            "'PROJECT_TASK_MANAGER', 'OTHER_PROJECT_ROLE')",
            name="ck_project_role_assignments_canonical_role_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="project_role_assignments_project_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="project_role_assignments_pkey"),
        sa.UniqueConstraint(
            "project_id",
            "source_system",
            "assignment_key",
            name="uq_project_role_assignments_identity",
        ),
    )
    op.create_index(
        "ix_project_role_assignments_project_current",
        "project_role_assignments",
        ["project_id", "is_current"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_role_assignments_project_current",
        table_name="project_role_assignments",
    )
    op.drop_table("project_role_assignments")
    op.drop_index("ix_projects_source_enrichment_status", table_name="projects")
    op.drop_constraint(
        "ck_projects_enrichment_status_allowed",
        "projects",
        type_="check",
    )
    op.drop_column("projects", "enrichment_fields_missing")
    op.drop_column("projects", "enrichment_fields_obtained")
    op.drop_column("projects", "enrichment_source_updated_at")
    op.drop_column("projects", "enrichment_failure_class")
    op.drop_column("projects", "last_enriched_at")
    op.drop_column("projects", "enrichment_last_attempted_at")
    op.drop_column("projects", "enrichment_status")
    op.drop_column("projects", "implementing_agencies")
    op.drop_column("projects", "borrower")
    op.drop_column("projects", "closing_date")
    op.drop_column("projects", "approval_date")
    op.drop_column("projects", "project_status")
    op.drop_column("projects", "region")
