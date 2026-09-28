"""W8 proposal evidence pack and pursuit proposal workspace.

Revision ID: 20261001_0001_w8_proposal_evidence_pack
Revises: 20260930_0001_w7_team_scenarios
Create Date: 2026-09-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261001_0001_w8_proposal_evidence_pack"
down_revision: Union[str, None] = "20260930_0001_w7_team_scenarios"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_team_decision_id_revision_organization",
        "team_scenario_decisions",
        ["id", "revision_id", "organization_id"],
    )
    op.create_table(
        "pursuit_proposal_workspaces",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("pursuit_id", sa.UUID(), nullable=False),
        sa.Column("created_by_membership_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_proposal_workspace_actor_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_proposal_workspace_pursuit_organization", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_proposal_workspace_id_organization"),
        sa.UniqueConstraint("organization_id", "pursuit_id", name="uq_proposal_workspace_organization_pursuit"),
    )
    op.create_index(
        "ix_proposal_workspaces_organization_created", "pursuit_proposal_workspaces",
        ["organization_id", "created_at"], unique=False,
    )
    op.create_table(
        "proposal_evidence_packs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("pursuit_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("pack_version", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.UUID(), nullable=False),
        sa.Column("scenario_revision_id", sa.UUID(), nullable=False),
        sa.Column("approval_decision_id", sa.UUID(), nullable=False),
        sa.Column("analysis_run_id", sa.UUID(), nullable=False),
        sa.Column("analysis_pack_id", sa.UUID(), nullable=False),
        sa.Column("sealed_by_membership_id", sa.UUID(), nullable=False),
        sa.Column("schema_version", sa.String(length=100), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("pack_state", sa.String(length=20), nullable=False),
        sa.Column("scenario_title_snapshot", sa.String(length=300), nullable=False),
        sa.Column("pursuit_title_snapshot", sa.String(length=500), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("matrix_row_count", sa.Integer(), nullable=False),
        sa.Column("participant_count", sa.Integer(), nullable=False),
        sa.Column("later_stage_count", sa.Integer(), nullable=False),
        sa.Column("checklist_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("pack_version >= 1", name="ck_proposal_pack_version"),
        sa.CheckConstraint("pack_state = 'SEALED'", name="ck_proposal_pack_state"),
        sa.CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$'", name="ck_proposal_pack_manifest_sha"),
        sa.CheckConstraint(
            "item_count >= 0 AND matrix_row_count >= 0 AND participant_count >= 0 "
            "AND later_stage_count >= 0 AND checklist_count >= 0",
            name="ck_proposal_pack_counts",
        ),
        sa.ForeignKeyConstraint(["analysis_pack_id"], ["pursuit_analysis_packs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["approval_decision_id", "scenario_revision_id", "organization_id"],
            ["team_scenario_decisions.id", "team_scenario_decisions.revision_id", "team_scenario_decisions.organization_id"],
            name="fk_proposal_pack_approval_revision_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_proposal_pack_pursuit_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id", "organization_id"],
            ["team_scenarios.id", "team_scenarios.organization_id"],
            name="fk_proposal_pack_scenario_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_revision_id", "analysis_run_id"],
            ["team_scenario_revisions.id", "team_scenario_revisions.analysis_run_id"],
            name="fk_proposal_pack_revision_analysis", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_revision_id", "scenario_id", "organization_id"],
            ["team_scenario_revisions.id", "team_scenario_revisions.scenario_id", "team_scenario_revisions.organization_id"],
            name="fk_proposal_pack_revision_scenario_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sealed_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_proposal_pack_actor_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "organization_id"],
            ["pursuit_proposal_workspaces.id", "pursuit_proposal_workspaces.organization_id"],
            name="fk_proposal_pack_workspace_organization", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_proposal_pack_id_organization"),
        sa.UniqueConstraint("workspace_id", "pack_version", name="uq_proposal_pack_workspace_version"),
    )
    op.create_index("ix_proposal_packs_revision", "proposal_evidence_packs", ["scenario_revision_id", "created_at"], unique=False)
    op.create_index("ix_proposal_packs_workspace_created", "proposal_evidence_packs", ["workspace_id", "created_at"], unique=False)
    op.create_table(
        "proposal_evidence_pack_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("pack_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("source_authority_type", sa.String(length=80), nullable=False),
        sa.Column("source_identity", sa.String(length=500), nullable=False),
        sa.Column("provenance", sa.String(length=80), nullable=False),
        sa.Column("review_state", sa.String(length=50), nullable=True),
        sa.Column("evidence_state", sa.String(length=50), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("requirement_id", sa.UUID(), nullable=True),
        sa.Column("position_id", sa.UUID(), nullable=True),
        sa.Column("gap_id", sa.UUID(), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_version", sa.String(length=100), nullable=True),
        sa.Column("payload_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "category IN ('PURSUIT_CONTEXT','REQUIREMENT','GAP_ASSESSMENT','FIRM','PROJECT_REFERENCE',"
            "'EXPERT','CV_FACTS','PARTICIPATION_CONFIRMATION','SOURCE_DOCUMENT','PRIVATE_DOCUMENT',"
            "'LATER_STAGE_OBLIGATION','FORM_OR_REQUIRED_ARTIFACT','OTHER')",
            name="ck_proposal_pack_item_category",
        ),
        sa.CheckConstraint("ordinal >= 1", name="ck_proposal_pack_item_ordinal"),
        sa.CheckConstraint("length(trim(source_authority_type)) >= 2", name="ck_proposal_pack_item_authority"),
        sa.CheckConstraint("length(trim(source_identity)) >= 1", name="ck_proposal_pack_item_identity"),
        sa.CheckConstraint("source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_proposal_pack_item_sha"),
        sa.ForeignKeyConstraint(["gap_id"], ["pursuit_analysis_gaps.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["pack_id", "organization_id"],
            ["proposal_evidence_packs.id", "proposal_evidence_packs.organization_id"],
            name="fk_proposal_pack_item_pack_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["position_id"], ["pursuit_analysis_positions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requirement_id"], ["pursuit_analysis_requirements.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "pack_id", name="uq_proposal_pack_item_id_pack"),
        sa.UniqueConstraint("pack_id", "ordinal", name="uq_proposal_pack_item_ordinal"),
    )
    op.create_index(
        "ix_proposal_pack_items_pack_category", "proposal_evidence_pack_items",
        ["pack_id", "category", "ordinal"], unique=False,
    )
    op.create_table(
        "proposal_evidence_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("pack_id", sa.UUID(), nullable=False),
        sa.Column("artifact_type", sa.String(length=10), nullable=False),
        sa.Column("historical_snapshot", sa.Boolean(), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(length=150), nullable=False),
        sa.Column("generator_version", sa.String(length=100), nullable=False),
        sa.Column("created_by_membership_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("artifact_type IN ('PDF','DOCX','JSON')", name="ck_proposal_artifact_type"),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_proposal_artifact_sha"),
        sa.CheckConstraint("byte_size > 0", name="ck_proposal_artifact_size"),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_proposal_artifact_actor_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pack_id", "organization_id"],
            ["proposal_evidence_packs.id", "proposal_evidence_packs.organization_id"],
            name="fk_proposal_artifact_pack_organization", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_proposal_artifact_id_organization"),
        sa.UniqueConstraint("pack_id", "artifact_type", "historical_snapshot", name="uq_proposal_artifact_pack_type_history"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_proposal_artifacts_pack_created", "proposal_evidence_artifacts", ["pack_id", "created_at"], unique=False)

    op.execute("""
        CREATE OR REPLACE FUNCTION reject_w8_immutable_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'W8 evidence history is immutable';
        END;
        $$
    """)
    for table in ("proposal_evidence_packs", "proposal_evidence_pack_items", "proposal_evidence_artifacts"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_w8_immutable_mutation()"
        )
    op.execute(
        "CREATE TRIGGER trg_pursuit_proposal_workspaces_no_delete "
        "BEFORE DELETE ON pursuit_proposal_workspaces FOR EACH ROW "
        "EXECUTE FUNCTION reject_w8_immutable_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_pursuit_proposal_workspaces_no_delete ON pursuit_proposal_workspaces")
    for table in ("proposal_evidence_artifacts", "proposal_evidence_pack_items", "proposal_evidence_packs"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.drop_index("ix_proposal_artifacts_pack_created", table_name="proposal_evidence_artifacts")
    op.drop_table("proposal_evidence_artifacts")
    op.drop_index("ix_proposal_pack_items_pack_category", table_name="proposal_evidence_pack_items")
    op.drop_table("proposal_evidence_pack_items")
    op.drop_index("ix_proposal_packs_workspace_created", table_name="proposal_evidence_packs")
    op.drop_index("ix_proposal_packs_revision", table_name="proposal_evidence_packs")
    op.drop_table("proposal_evidence_packs")
    op.drop_index("ix_proposal_workspaces_organization_created", table_name="pursuit_proposal_workspaces")
    op.drop_table("pursuit_proposal_workspaces")
    op.drop_constraint(
        "uq_team_decision_id_revision_organization", "team_scenario_decisions", type_="unique"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_w8_immutable_mutation()")

