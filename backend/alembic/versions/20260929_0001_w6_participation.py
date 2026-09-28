"""W6 organization-private availability, interest, and participation history.

Revision ID: 20260929_0001_w6_participation
Revises: 20260928_0001_w5_candidate_retrieval
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260929_0001_w6_participation"
down_revision: Union[str, None] = "20260928_0001_w5_candidate_retrieval"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_candidate_review_id_match", "candidate_review_decisions", ["id", "candidate_match_id"]
    )
    op.create_unique_constraint(
        "uq_private_document_version_id_organization", "private_document_versions", ["id", "organization_id"]
    )

    op.create_table(
        "candidate_participation_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("pursuit_id", sa.UUID(), nullable=False),
        sa.Column("candidate_match_id", sa.UUID(), nullable=False),
        sa.Column("shortlist_decision_id", sa.UUID(), nullable=False),
        sa.Column("proposed_contribution_snapshot", sa.Text(), nullable=False),
        sa.Column("created_by_membership_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_participation_record_pursuit_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_participation_record_actor_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["shortlist_decision_id", "candidate_match_id"],
            ["candidate_review_decisions.id", "candidate_review_decisions.candidate_match_id"],
            name="fk_participation_record_shortlist_match", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_match_id"], ["candidate_matches.id"],
            name="fk_participation_record_match", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_match_id", name="uq_candidate_participation_match"),
        sa.UniqueConstraint("id", "organization_id", name="uq_participation_record_id_organization"),
    )
    op.create_index(
        "ix_participation_records_pursuit_created", "candidate_participation_records",
        ["organization_id", "pursuit_id", "created_at"],
    )

    op.create_table(
        "candidate_availability_facts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("participation_record_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("effort_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("capacity_description", sa.Text(), nullable=True),
        sa.Column("location_travel_constraints", sa.Text(), nullable=True),
        sa.Column("confirmation_source", sa.String(length=40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supporting_document_version_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("supersedes_fact_id", sa.UUID(), nullable=True),
        sa.Column("actor_membership_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('UNKNOWN','TENTATIVE','AVAILABLE','PARTIALLY_AVAILABLE','UNAVAILABLE')",
            name="ck_availability_status",
        ),
        sa.CheckConstraint(
            "(window_start IS NULL AND window_end IS NULL) OR "
            "(window_start IS NOT NULL AND window_end IS NOT NULL AND window_end >= window_start)",
            name="ck_availability_window",
        ),
        sa.CheckConstraint(
            "effort_percent IS NULL OR (effort_percent >= 0 AND effort_percent <= 100)",
            name="ck_availability_effort",
        ),
        sa.CheckConstraint(
            "status NOT IN ('TENTATIVE','AVAILABLE','PARTIALLY_AVAILABLE') OR valid_until IS NOT NULL",
            name="ck_availability_positive_freshness",
        ),
        sa.CheckConstraint(
            "confirmation_source IN ('DIRECT_EMAIL','CALL','MEETING','SIGNED_DOCUMENT','OPERATOR_RECORDED','CUSTOMER_RECORDED','OTHER')",
            name="ck_availability_source",
        ),
        sa.ForeignKeyConstraint(
            ["participation_record_id", "organization_id"],
            ["candidate_participation_records.id", "candidate_participation_records.organization_id"],
            name="fk_availability_record_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_availability_actor_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supporting_document_version_id", "organization_id"],
            ["private_document_versions.id", "private_document_versions.organization_id"],
            name="fk_availability_document_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_fact_id", "participation_record_id"],
            ["candidate_availability_facts.id", "candidate_availability_facts.participation_record_id"],
            name="fk_availability_supersedes_same_record", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "participation_record_id", name="uq_availability_fact_id_record"),
    )
    op.create_index("ix_availability_record_created", "candidate_availability_facts", ["participation_record_id", "created_at"])

    op.create_table(
        "candidate_interest_facts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("participation_record_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("confirmation_source", sa.String(length=40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("conditions", sa.Text(), nullable=True),
        sa.Column("supporting_document_version_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("supersedes_fact_id", sa.UUID(), nullable=True),
        sa.Column("actor_membership_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('UNKNOWN','INTERESTED','CONDITIONAL','DECLINED')", name="ck_interest_status"),
        sa.CheckConstraint("status <> 'CONDITIONAL' OR length(trim(conditions)) >= 3", name="ck_interest_conditions"),
        sa.CheckConstraint(
            "confirmation_source IN ('DIRECT_EMAIL','CALL','MEETING','SIGNED_DOCUMENT','OPERATOR_RECORDED','CUSTOMER_RECORDED','OTHER')",
            name="ck_interest_source",
        ),
        sa.ForeignKeyConstraint(
            ["participation_record_id", "organization_id"],
            ["candidate_participation_records.id", "candidate_participation_records.organization_id"],
            name="fk_interest_record_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_interest_actor_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supporting_document_version_id", "organization_id"],
            ["private_document_versions.id", "private_document_versions.organization_id"],
            name="fk_interest_document_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_fact_id", "participation_record_id"],
            ["candidate_interest_facts.id", "candidate_interest_facts.participation_record_id"],
            name="fk_interest_supersedes_same_record", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "participation_record_id", name="uq_interest_fact_id_record"),
    )
    op.create_index("ix_interest_record_created", "candidate_interest_facts", ["participation_record_id", "created_at"])

    op.create_table(
        "candidate_participation_decisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("participation_record_id", sa.UUID(), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("confirmation_source", sa.String(length=40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reconfirm_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("conditions_summary", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("supporting_document_version_id", sa.UUID(), nullable=True),
        sa.Column("supersedes_decision_id", sa.UUID(), nullable=True),
        sa.Column("actor_membership_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "state IN ('UNCONFIRMED','TENTATIVE','CONFIRMED','DECLINED','WITHDRAWN')",
            name="ck_participation_decision_state",
        ),
        sa.CheckConstraint(
            "state NOT IN ('TENTATIVE','CONFIRMED') OR reconfirm_by IS NOT NULL",
            name="ck_participation_reconfirm",
        ),
        sa.CheckConstraint(
            "state NOT IN ('DECLINED','WITHDRAWN') OR length(trim(reason)) >= 3",
            name="ck_participation_terminal_reason",
        ),
        sa.CheckConstraint(
            "confirmation_source IN ('DIRECT_EMAIL','CALL','MEETING','SIGNED_DOCUMENT','OPERATOR_RECORDED','CUSTOMER_RECORDED','OTHER')",
            name="ck_participation_decision_source",
        ),
        sa.ForeignKeyConstraint(
            ["participation_record_id", "organization_id"],
            ["candidate_participation_records.id", "candidate_participation_records.organization_id"],
            name="fk_participation_decision_record_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_participation_decision_actor_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supporting_document_version_id", "organization_id"],
            ["private_document_versions.id", "private_document_versions.organization_id"],
            name="fk_participation_decision_document_organization", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_decision_id", "participation_record_id"],
            ["candidate_participation_decisions.id", "candidate_participation_decisions.participation_record_id"],
            name="fk_participation_decision_supersedes_same_record", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "participation_record_id", name="uq_participation_decision_id_record"),
    )
    op.create_index(
        "ix_participation_decisions_record_created", "candidate_participation_decisions",
        ["participation_record_id", "created_at"],
    )

    op.execute(
        """
        CREATE FUNCTION reject_w6_participation_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'W6 participation history is immutable';
        END;
        $$
        """
    )
    for table_name in (
        "candidate_participation_records", "candidate_availability_facts",
        "candidate_interest_facts", "candidate_participation_decisions",
    ):
        op.execute(
            f"CREATE TRIGGER {table_name}_append_only BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_w6_participation_history_mutation()"
        )


def downgrade() -> None:
    for table_name in (
        "candidate_participation_decisions", "candidate_interest_facts",
        "candidate_availability_facts", "candidate_participation_records",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table_name}_append_only ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS reject_w6_participation_history_mutation()")
    op.drop_index("ix_participation_decisions_record_created", table_name="candidate_participation_decisions")
    op.drop_table("candidate_participation_decisions")
    op.drop_index("ix_interest_record_created", table_name="candidate_interest_facts")
    op.drop_table("candidate_interest_facts")
    op.drop_index("ix_availability_record_created", table_name="candidate_availability_facts")
    op.drop_table("candidate_availability_facts")
    op.drop_index("ix_participation_records_pursuit_created", table_name="candidate_participation_records")
    op.drop_table("candidate_participation_records")
    op.drop_constraint("uq_private_document_version_id_organization", "private_document_versions", type_="unique")
    op.drop_constraint("uq_candidate_review_id_match", "candidate_review_decisions", type_="unique")
