"""add_tender_sync_jobs_table

Revision ID: 9f3d2f4b6a10
Revises: 27fc6790093d
Create Date: 2026-03-29 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9f3d2f4b6a10"
down_revision: Union[str, None] = "27fc6790093d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'tender_sync_status'
            ) THEN
                CREATE TYPE tender_sync_status AS ENUM (
                    'PENDING',
                    'IN_PROGRESS',
                    'SUCCESS',
                    'FAILED'
                );
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tender_sync_jobs (
            id UUID PRIMARY KEY,
            job_id VARCHAR(100) NOT NULL UNIQUE,
            tender_id UUID NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status tender_sync_status NOT NULL,
            progress INTEGER DEFAULT 0 NOT NULL,
            error_message TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_tender_sync_jobs_progress_range'
            ) THEN
                ALTER TABLE tender_sync_jobs
                ADD CONSTRAINT ck_tender_sync_jobs_progress_range
                CHECK (progress >= 0 AND progress <= 100);
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tender_sync_jobs_tender_id
        ON tender_sync_jobs (tender_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tender_sync_jobs_user_id
        ON tender_sync_jobs (user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tender_sync_jobs_status
        ON tender_sync_jobs (status)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_tender_sync_jobs_active_user_tender
        ON tender_sync_jobs (user_id, tender_id)
        WHERE status IN ('PENDING', 'IN_PROGRESS')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_tender_sync_jobs_active_user_tender")
    op.execute("DROP INDEX IF EXISTS ix_tender_sync_jobs_status")
    op.execute("DROP INDEX IF EXISTS ix_tender_sync_jobs_user_id")
    op.execute("DROP INDEX IF EXISTS ix_tender_sync_jobs_tender_id")
    op.execute(
        """
        ALTER TABLE tender_sync_jobs
        DROP CONSTRAINT IF EXISTS ck_tender_sync_jobs_progress_range
        """
    )
    op.execute("DROP TABLE IF EXISTS tender_sync_jobs")
    op.execute("DROP TYPE IF EXISTS tender_sync_status")
