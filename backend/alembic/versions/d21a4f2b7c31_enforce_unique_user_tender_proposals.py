"""enforce_unique_user_tender_proposals

Revision ID: d21a4f2b7c31
Revises: 9f3d2f4b6a10
Create Date: 2026-03-30 21:05:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d21a4f2b7c31"
down_revision: Union[str, None] = "9f3d2f4b6a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep the oldest proposal per (user_id, tender_id), remove duplicates.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY user_id, tender_id
                    ORDER BY created_at ASC, id ASC
                ) AS rn
            FROM proposals
        )
        DELETE FROM proposals p
        USING ranked r
        WHERE p.id = r.id
          AND r.rn > 1
        """
    )

    op.create_unique_constraint(
        "uq_proposals_user_tender",
        "proposals",
        ["user_id", "tender_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_proposals_user_tender", "proposals", type_="unique")
