"""D2-01 the organization's own firm and non-destructive project reference edits.

Additive and reversible.

candidate_firms.organization_id marks the one firm that *is* the organization
(its "self firm"): at most one per organization, always ORGANIZATION_PRIVATE and
owned by that same organization. Every existing firm keeps NULL.

candidate_project_references gains archive and supersede columns. A reference
is cited by id from immutable candidate matches, scenario contributions and
proposal evidence packs, so an edit writes a new row that supersedes the old
one and archives it. The trigger keeps the recorded facts of a reference
immutable: only the archive columns may change, and an archive is final.

Downgrade drops the columns: a self firm becomes an ordinary private firm and
archived references become indistinguishable from current ones.

Revision ID: 20261004_0001_d2_01_own_experience
Revises: 20261003_0001_d1_03_official_notice_unique
Create Date: 2026-09-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261004_0001_d2_01_own_experience"
down_revision: Union[str, None] = "20261003_0001_d1_03_official_notice_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "candidate_firms",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_candidate_firm_self_organization", "candidate_firms", "organizations",
        ["organization_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_candidate_firm_self_private",
        "candidate_firms",
        "organization_id IS NULL OR "
        "(scope = 'ORGANIZATION_PRIVATE' AND owner_organization_id = organization_id)",
    )
    op.create_index(
        "uq_candidate_firms_self_organization",
        "candidate_firms",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NOT NULL"),
    )

    op.add_column(
        "candidate_project_references",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "candidate_project_references",
        sa.Column("archived_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "candidate_project_references",
        sa.Column("supersedes_reference_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_candidate_reference_archived_by", "candidate_project_references", "users",
        ["archived_by_user_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_candidate_reference_supersedes", "candidate_project_references",
        "candidate_project_references", ["supersedes_reference_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_candidate_reference_supersedes_other",
        "candidate_project_references",
        "supersedes_reference_id IS NULL OR supersedes_reference_id <> id",
    )
    op.create_index(
        "uq_candidate_references_supersedes",
        "candidate_project_references",
        ["supersedes_reference_id"],
        unique=True,
        postgresql_where=sa.text("supersedes_reference_id IS NOT NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION candidate_project_reference_facts_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.archived_at IS NOT NULL THEN
                RAISE EXCEPTION 'archived project references are immutable';
            END IF;
            IF (to_jsonb(NEW) - 'archived_at' - 'archived_by_user_id' - 'updated_at')
               IS DISTINCT FROM
               (to_jsonb(OLD) - 'archived_at' - 'archived_by_user_id' - 'updated_at') THEN
                RAISE EXCEPTION 'project reference facts are immutable; supersede the reference instead';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER candidate_project_references_facts_immutable "
        "BEFORE UPDATE ON candidate_project_references "
        "FOR EACH ROW EXECUTE FUNCTION candidate_project_reference_facts_immutable()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS candidate_project_references_facts_immutable ON candidate_project_references"
    )
    op.execute("DROP FUNCTION IF EXISTS candidate_project_reference_facts_immutable()")
    op.drop_index("uq_candidate_references_supersedes", table_name="candidate_project_references")
    op.drop_constraint("ck_candidate_reference_supersedes_other", "candidate_project_references", type_="check")
    op.drop_constraint("fk_candidate_reference_supersedes", "candidate_project_references", type_="foreignkey")
    op.drop_constraint("fk_candidate_reference_archived_by", "candidate_project_references", type_="foreignkey")
    op.drop_column("candidate_project_references", "supersedes_reference_id")
    op.drop_column("candidate_project_references", "archived_by_user_id")
    op.drop_column("candidate_project_references", "archived_at")

    op.drop_index("uq_candidate_firms_self_organization", table_name="candidate_firms")
    op.drop_constraint("ck_candidate_firm_self_private", "candidate_firms", type_="check")
    op.drop_constraint("fk_candidate_firm_self_organization", "candidate_firms", type_="foreignkey")
    op.drop_column("candidate_firms", "organization_id")
