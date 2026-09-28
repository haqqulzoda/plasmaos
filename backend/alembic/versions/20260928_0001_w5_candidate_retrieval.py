"""W5 reusable Firm/Expert authorities and evidence-backed candidate retrieval.

Revision ID: 20260928_0001_w5_candidate_retrieval
Revises: 20260927_0001_w4_pursuit_analysis
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260928_0001_w5_candidate_retrieval"
down_revision: Union[str, None] = "20260927_0001_w4_pursuit_analysis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candidate_firms",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(length=30), nullable=False),
        sa.Column("owner_organization_id", sa.UUID(), nullable=True),
        sa.Column("canonical_name", sa.String(length=500), nullable=False),
        sa.Column("display_name", sa.String(length=500), nullable=False),
        sa.Column("legal_name", sa.String(length=500), nullable=True),
        sa.Column("country", sa.String(length=150), nullable=True),
        sa.Column("regions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("services", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sectors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_state", sa.String(length=30), nullable=False),
        sa.Column("network_permission_basis", sa.Text(), nullable=True),
        sa.Column("private_notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("scope IN ('ORGANIZATION_PRIVATE', 'NETWORK_SHARED')", name="ck_candidate_firm_scope"),
        sa.CheckConstraint("evidence_state IN ('VERIFIED', 'REVIEWED', 'UNVERIFIED', 'EVIDENCE_MISSING')", name="ck_candidate_firm_evidence"),
        sa.CheckConstraint("source_type IN ('MANUAL','EXPLICIT_IMPORT')", name="ck_candidate_firm_source"),
        sa.CheckConstraint(
            "(scope = 'ORGANIZATION_PRIVATE' AND owner_organization_id IS NOT NULL) OR "
            "(scope = 'NETWORK_SHARED' AND owner_organization_id IS NULL AND length(trim(network_permission_basis)) >= 3)",
            name="ck_candidate_firm_scope_owner",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_firms_visibility", "candidate_firms", ["scope", "owner_organization_id", "updated_at"])

    op.create_table(
        "candidate_experts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(length=30), nullable=False),
        sa.Column("owner_organization_id", sa.UUID(), nullable=True),
        sa.Column("display_name", sa.String(length=500), nullable=False),
        sa.Column("qualifications", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("languages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("specializations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("consent_state", sa.String(length=40), nullable=False),
        sa.Column("network_permission_basis", sa.Text(), nullable=True),
        sa.Column("evidence_state", sa.String(length=30), nullable=False),
        sa.Column("source_provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("private_notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("scope IN ('ORGANIZATION_PRIVATE', 'NETWORK_SHARED')", name="ck_candidate_expert_scope"),
        sa.CheckConstraint("evidence_state IN ('VERIFIED', 'REVIEWED', 'UNVERIFIED', 'EVIDENCE_MISSING')", name="ck_candidate_expert_evidence"),
        sa.CheckConstraint(
            "consent_state IN ('NOT_REQUIRED_PRIVATE','EXPLICIT_CONSENT','CONTRACTUAL_BASIS','WITHDRAWN','UNKNOWN')",
            name="ck_candidate_expert_consent",
        ),
        sa.CheckConstraint(
            "(scope = 'ORGANIZATION_PRIVATE' AND owner_organization_id IS NOT NULL) OR "
            "(scope = 'NETWORK_SHARED' AND owner_organization_id IS NULL "
            "AND consent_state IN ('EXPLICIT_CONSENT','CONTRACTUAL_BASIS') "
            "AND length(trim(network_permission_basis)) >= 3)",
            name="ck_candidate_expert_scope_consent",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_experts_visibility", "candidate_experts", ["scope", "owner_organization_id", "updated_at"])

    op.create_table(
        "candidate_project_references",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("firm_id", sa.UUID(), nullable=False),
        sa.Column("project_name", sa.String(length=700), nullable=False),
        sa.Column("client_name", sa.String(length=500), nullable=True),
        sa.Column("country", sa.String(length=150), nullable=True),
        sa.Column("service", sa.String(length=300), nullable=True),
        sa.Column("sector", sa.String(length=300), nullable=True),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("contract_share_percent", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("contract_value", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("contract_currency", sa.String(length=3), nullable=True),
        sa.Column("value_basis", sa.String(length=30), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("completion_date", sa.Date(), nullable=True),
        sa.Column("completion_state", sa.String(length=20), nullable=False),
        sa.Column("relevant_scope", sa.Text(), nullable=True),
        sa.Column("evidence_provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_state", sa.String(length=30), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('LEAD','JV_MEMBER','CONSORTIUM_MEMBER','SUBCONSULTANT','SUBCONTRACTOR','OTHER','UNKNOWN')", name="ck_candidate_reference_role"),
        sa.CheckConstraint("contract_share_percent IS NULL OR (contract_share_percent >= 0 AND contract_share_percent <= 100)", name="ck_candidate_reference_share"),
        sa.CheckConstraint("contract_value IS NULL OR contract_value >= 0", name="ck_candidate_reference_value"),
        sa.CheckConstraint("value_basis IN ('FIRM_SHARE','CONSORTIUM_TOTAL','CONTRACT_TOTAL','UNKNOWN')", name="ck_candidate_reference_value_basis"),
        sa.CheckConstraint(
            "(contract_value IS NULL AND contract_currency IS NULL) OR "
            "(contract_value IS NOT NULL AND contract_currency IS NOT NULL AND value_basis <> 'UNKNOWN')",
            name="ck_candidate_reference_value_truth",
        ),
        sa.CheckConstraint("completion_state IN ('COMPLETED','ONGOING','NOT_COMPLETED','UNKNOWN')", name="ck_candidate_reference_completion"),
        sa.CheckConstraint("completion_date IS NULL OR start_date IS NULL OR completion_date >= start_date", name="ck_candidate_reference_dates"),
        sa.CheckConstraint("evidence_state IN ('VERIFIED', 'REVIEWED', 'UNVERIFIED', 'EVIDENCE_MISSING')", name="ck_candidate_reference_evidence"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["firm_id"], ["candidate_firms.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_references_firm_evidence", "candidate_project_references", ["firm_id", "evidence_state", "completion_state"])

    op.create_table(
        "candidate_cv_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("expert_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("education", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("qualifications", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("certifications", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assignments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("languages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_state", sa.String(length=30), nullable=False),
        sa.Column("structured_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("version_number >= 1", name="ck_candidate_cv_version_positive"),
        sa.CheckConstraint("evidence_state IN ('VERIFIED', 'REVIEWED', 'UNVERIFIED', 'EVIDENCE_MISSING')", name="ck_candidate_cv_evidence"),
        sa.CheckConstraint("structured_sha256 ~ '^[0-9a-f]{64}$'", name="ck_candidate_cv_sha"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["expert_id"], ["candidate_experts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("expert_id", "version_number", name="uq_candidate_cv_version_number"),
    )
    op.create_index("ix_candidate_cv_expert_created", "candidate_cv_versions", ["expert_id", "created_at"])

    op.create_table(
        "candidate_search_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("pursuit_id", sa.UUID(), nullable=False),
        sa.Column("analysis_run_id", sa.UUID(), nullable=False),
        sa.Column("gap_id", sa.UUID(), nullable=False),
        sa.Column("target_kind", sa.String(length=20), nullable=False),
        sa.Column("requirement_id", sa.UUID(), nullable=True),
        sa.Column("position_id", sa.UUID(), nullable=True),
        sa.Column("review_assertion_id", sa.UUID(), nullable=False),
        sa.Column("effective_coverage_state", sa.String(length=40), nullable=False),
        sa.Column("effective_review_state", sa.String(length=30), nullable=False),
        sa.Column("resolution_category", sa.String(length=40), nullable=False),
        sa.Column("contribution_rule", sa.Text(), nullable=False),
        sa.Column("search_version", sa.String(length=100), nullable=False),
        sa.Column("search_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result_limit", sa.Integer(), nullable=False),
        sa.Column("actor_membership_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(target_kind = 'FIRM' AND requirement_id IS NOT NULL AND position_id IS NULL AND resolution_category = 'PARTNER_FIRM') OR "
            "(target_kind = 'EXPERT' AND position_id IS NOT NULL AND requirement_id IS NULL AND resolution_category = 'EXPERT')",
            name="ck_candidate_search_target",
        ),
        sa.CheckConstraint("effective_review_state IN ('CONFIRMED','CORRECTED')", name="ck_candidate_search_reviewed"),
        sa.CheckConstraint("effective_coverage_state <> 'NEEDS_INTERPRETATION'", name="ck_candidate_search_interpreted"),
        sa.CheckConstraint("status = 'COMPLETED'", name="ck_candidate_search_completed"),
        sa.CheckConstraint("result_limit BETWEEN 1 AND 20", name="ck_candidate_search_limit"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["pursuit_analysis_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["gap_id"], ["pursuit_analysis_gaps.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["position_id"], ["pursuit_analysis_positions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requirement_id"], ["pursuit_analysis_requirements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["review_assertion_id"], ["pursuit_analysis_review_assertions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pursuit_id", "organization_id"], ["organization_pursuits.id", "organization_pursuits.organization_id"], name="fk_candidate_search_pursuit_organization", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_membership_id", "organization_id"], ["memberships.id", "memberships.organization_id"], name="fk_candidate_search_actor_organization", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_search_pursuit_created", "candidate_search_runs", ["organization_id", "pursuit_id", "created_at"])
    op.create_index("ix_candidate_search_gap_created", "candidate_search_runs", ["gap_id", "created_at"])

    op.create_table(
        "candidate_matches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("candidate_search_run_id", sa.UUID(), nullable=False),
        sa.Column("gap_id", sa.UUID(), nullable=False),
        sa.Column("firm_id", sa.UUID(), nullable=True),
        sa.Column("expert_id", sa.UUID(), nullable=True),
        sa.Column("proposed_contribution", sa.Text(), nullable=False),
        sa.Column("strongest_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("relevant_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("missing_or_weak_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("qualification_state", sa.String(length=40), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("retrieval_rank", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("(firm_id IS NOT NULL) <> (expert_id IS NOT NULL)", name="ck_candidate_match_single_candidate"),
        sa.CheckConstraint("qualification_state IN ('SUPPORTED_BY_EVIDENCE','PARTIAL','EVIDENCE_MISSING','NEEDS_REVIEW','NOT_RELEVANT')", name="ck_candidate_match_qualification"),
        sa.CheckConstraint("retrieval_rank BETWEEN 1 AND 20", name="ck_candidate_match_rank"),
        sa.ForeignKeyConstraint(["candidate_search_run_id"], ["candidate_search_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["expert_id"], ["candidate_experts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["firm_id"], ["candidate_firms.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["gap_id"], ["pursuit_analysis_gaps.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_search_run_id", "expert_id", name="uq_candidate_match_run_expert"),
        sa.UniqueConstraint("candidate_search_run_id", "firm_id", name="uq_candidate_match_run_firm"),
    )
    op.create_index("ix_candidate_matches_run_rank", "candidate_matches", ["candidate_search_run_id", "retrieval_rank"])

    op.create_table(
        "candidate_review_decisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("candidate_search_run_id", sa.UUID(), nullable=False),
        sa.Column("candidate_match_id", sa.UUID(), nullable=False),
        sa.Column("actor_membership_id", sa.UUID(), nullable=False),
        sa.Column("supersedes_decision_id", sa.UUID(), nullable=True),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("corrected_contribution", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("decision IN ('SHORTLISTED','REJECTED','MORE_EVIDENCE_REQUESTED','IRRELEVANT','CONTRIBUTION_CORRECTED')", name="ck_candidate_review_decision"),
        sa.CheckConstraint(
            "(decision = 'CONTRIBUTION_CORRECTED' AND length(trim(corrected_contribution)) >= 3) OR "
            "(decision <> 'CONTRIBUTION_CORRECTED' AND corrected_contribution IS NULL)",
            name="ck_candidate_review_correction",
        ),
        sa.ForeignKeyConstraint(["actor_membership_id", "organization_id"], ["memberships.id", "memberships.organization_id"], name="fk_candidate_review_actor_organization", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["candidate_match_id"], ["candidate_matches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["candidate_search_run_id"], ["candidate_search_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_decision_id"], ["candidate_review_decisions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_reviews_match_created", "candidate_review_decisions", ["candidate_match_id", "created_at"])

    op.execute(
        """
        CREATE FUNCTION reject_w5_candidate_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'W5 candidate search history is immutable';
        END;
        $$
        """
    )
    for table_name in (
        "candidate_cv_versions",
        "candidate_search_runs",
        "candidate_matches",
        "candidate_review_decisions",
    ):
        op.execute(
            f"CREATE TRIGGER {table_name}_append_only BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_w5_candidate_history_mutation()"
        )


def downgrade() -> None:
    for table_name in (
        "candidate_review_decisions",
        "candidate_matches",
        "candidate_search_runs",
        "candidate_cv_versions",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table_name}_append_only ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS reject_w5_candidate_history_mutation()")
    op.drop_index("ix_candidate_reviews_match_created", table_name="candidate_review_decisions")
    op.drop_table("candidate_review_decisions")
    op.drop_index("ix_candidate_matches_run_rank", table_name="candidate_matches")
    op.drop_table("candidate_matches")
    op.drop_index("ix_candidate_search_gap_created", table_name="candidate_search_runs")
    op.drop_index("ix_candidate_search_pursuit_created", table_name="candidate_search_runs")
    op.drop_table("candidate_search_runs")
    op.drop_index("ix_candidate_cv_expert_created", table_name="candidate_cv_versions")
    op.drop_table("candidate_cv_versions")
    op.drop_index("ix_candidate_references_firm_evidence", table_name="candidate_project_references")
    op.drop_table("candidate_project_references")
    op.drop_index("ix_candidate_experts_visibility", table_name="candidate_experts")
    op.drop_table("candidate_experts")
    op.drop_index("ix_candidate_firms_visibility", table_name="candidate_firms")
    op.drop_table("candidate_firms")

