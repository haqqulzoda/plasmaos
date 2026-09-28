"""P0 extraction quality diagnostics and position qualification distinctions.

Revision ID: 20261002_0001_p0_extraction_trust_gate
Revises: 20261001_0001_w8_proposal_evidence_pack
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261002_0001_p0_extraction_trust_gate"
down_revision: Union[str, None] = "20261001_0001_w8_proposal_evidence_pack"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pursuit_analysis_runs",
        sa.Column("quality_state", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "pursuit_analysis_runs",
        sa.Column(
            "extraction_diagnostics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_analysis_run_quality_state",
        "pursuit_analysis_runs",
        "quality_state IS NULL OR quality_state IN ('READY_FOR_REVIEW','NEEDS_ATTENTION','FAILED')",
    )
    op.create_check_constraint(
        "ck_analysis_run_diagnostics",
        "pursuit_analysis_runs",
        "jsonb_typeof(extraction_diagnostics) = 'object'",
    )
    op.add_column(
        "pursuit_analysis_positions",
        sa.Column(
            "qualification_criteria",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_pursuit_position_qualification_criteria",
        "pursuit_analysis_positions",
        "jsonb_typeof(qualification_criteria) = 'array'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_pursuit_position_qualification_criteria",
        "pursuit_analysis_positions",
        type_="check",
    )
    op.drop_column("pursuit_analysis_positions", "qualification_criteria")
    op.drop_constraint("ck_analysis_run_diagnostics", "pursuit_analysis_runs", type_="check")
    op.drop_constraint("ck_analysis_run_quality_state", "pursuit_analysis_runs", type_="check")
    op.drop_column("pursuit_analysis_runs", "extraction_diagnostics")
    op.drop_column("pursuit_analysis_runs", "quality_state")
