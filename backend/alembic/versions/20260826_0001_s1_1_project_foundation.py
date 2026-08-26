"""add canonical Project identity and deterministic TenderProject linkage

Revision ID: 20260826_0001_s1_1_project_foundation
Revises: 20260825_0001_s0_5b3
Create Date: 2026-08-26 00:00:00.000000
"""

from __future__ import annotations

import logging
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260826_0001_s1_1_project_foundation"
down_revision: Union[str, None] = "20260825_0001_s0_5b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


logger = logging.getLogger("alembic.runtime.migration")
VALID_WORLD_BANK_PROJECT_ID_SQL = r"BTRIM(project_id) ~ '^P[0-9]{6}$'"


def _scalar(bind: Any, sql: str) -> int:
    return int(bind.execute(sa.text(sql)).scalar_one())


def _backfill_world_bank_projects(bind: Any) -> dict[str, int]:
    """Idempotently backfill only strict World Bank P###### source evidence."""
    counts = {
        "world_bank_tenders_with_project_id": _scalar(
            bind,
            """
            SELECT COUNT(*) FROM tenders
            WHERE source_system = 'world_bank' AND project_id IS NOT NULL
            """,
        ),
        "valid_ids": _scalar(
            bind,
            f"""
            SELECT COUNT(*) FROM tenders
            WHERE source_system = 'world_bank'
              AND project_id IS NOT NULL
              AND {VALID_WORLD_BANK_PROJECT_ID_SQL}
            """,
        ),
        "invalid_skipped_ids": _scalar(
            bind,
            f"""
            SELECT COUNT(*) FROM tenders
            WHERE source_system = 'world_bank'
              AND project_id IS NOT NULL
              AND NOT ({VALID_WORLD_BANK_PROJECT_ID_SQL})
            """,
        ),
        "distinct_project_ids": _scalar(
            bind,
            f"""
            SELECT COUNT(DISTINCT BTRIM(project_id)) FROM tenders
            WHERE source_system = 'world_bank'
              AND project_id IS NOT NULL
              AND {VALID_WORLD_BANK_PROJECT_ID_SQL}
            """,
        ),
        "normalization_changes": _scalar(
            bind,
            f"""
            SELECT COUNT(*) FROM tenders
            WHERE source_system = 'world_bank'
              AND project_id IS NOT NULL
              AND {VALID_WORLD_BANK_PROJECT_ID_SQL}
              AND project_id <> BTRIM(project_id)
            """,
        ),
    }
    projects_before = _scalar(bind, "SELECT COUNT(*) FROM projects")
    links_before = _scalar(bind, "SELECT COUNT(*) FROM tender_projects")
    counts["links_already_present"] = _scalar(
        bind,
        f"""
        SELECT COUNT(*)
        FROM tender_projects tp
        JOIN tenders t ON t.id = tp.tender_id
        WHERE t.source_system = 'world_bank'
          AND t.project_id IS NOT NULL
          AND BTRIM(t.project_id) ~ '^P[0-9]{{6}}$'
        """,
    )

    bind.execute(
        sa.text(
            f"""
            WITH candidates AS (
                SELECT DISTINCT ON (BTRIM(t.project_id))
                    BTRIM(t.project_id) AS normalized_project_id,
                    t.project_id AS raw_project_id,
                    NULLIF(BTRIM(t.country), '') AS country,
                    t.source_url,
                    COALESCE(t.last_synced_at, t.created_at, NOW()) AS observed_at
                FROM tenders t
                WHERE t.source_system = 'world_bank'
                  AND t.project_id IS NOT NULL
                  AND {VALID_WORLD_BANK_PROJECT_ID_SQL}
                ORDER BY BTRIM(t.project_id),
                         (NULLIF(BTRIM(t.country), '') IS NOT NULL) DESC,
                         (t.project_id = BTRIM(t.project_id)) DESC,
                         t.created_at,
                         t.id
            )
            INSERT INTO projects (
                id, source_system, external_project_id, name, country,
                source_url, raw_provenance, created_at, updated_at
            )
            SELECT
                MD5('plasmaos:project:world_bank:' || normalized_project_id)::uuid,
                'world_bank',
                normalized_project_id,
                NULL,
                country,
                NULL,
                json_build_object(
                    'source_system', 'world_bank',
                    'source_field', 'tenders.project_id',
                    'source_value', raw_project_id,
                    'normalized_value', normalized_project_id,
                    'normalization_changed', raw_project_id <> normalized_project_id,
                    'source_url', source_url,
                    'observed_at', observed_at
                ),
                NOW(),
                NOW()
            FROM candidates
            ON CONFLICT (source_system, external_project_id) DO NOTHING
            """
        )
    )

    bind.execute(
        sa.text(
            f"""
            INSERT INTO tender_projects (
                id, tender_id, project_id, linkage_method,
                source_value, provenance, created_at
            )
            SELECT
                MD5('plasmaos:tender-project:' || t.id::text)::uuid,
                t.id,
                p.id,
                'SOURCE_PROJECT_ID',
                t.project_id,
                json_build_object(
                    'source_system', 'world_bank',
                    'source_field', 'tenders.project_id',
                    'source_value', t.project_id,
                    'normalized_value', BTRIM(t.project_id),
                    'normalization_changed', t.project_id <> BTRIM(t.project_id),
                    'source_url', t.source_url,
                    'observed_at', COALESCE(t.last_synced_at, t.created_at, NOW())
                ),
                NOW()
            FROM tenders t
            JOIN projects p
              ON p.source_system = 'world_bank'
             AND p.external_project_id = BTRIM(t.project_id)
            WHERE t.source_system = 'world_bank'
              AND t.project_id IS NOT NULL
              AND {VALID_WORLD_BANK_PROJECT_ID_SQL}
            ON CONFLICT (tender_id) DO NOTHING
            """
        )
    )

    projects_after = _scalar(bind, "SELECT COUNT(*) FROM projects")
    links_after = _scalar(bind, "SELECT COUNT(*) FROM tender_projects")
    counts["projects_created"] = projects_after - projects_before
    counts["projects_reused"] = counts["valid_ids"] - counts["projects_created"]
    counts["tenderproject_links_created"] = links_after - links_before
    counts["errors"] = 0
    logger.info(
        "s1_1_world_bank_project_backfill "
        "world_bank_tenders_with_project_id=%d valid_ids=%d "
        "invalid_skipped_ids=%d distinct_project_ids=%d projects_created=%d "
        "projects_reused=%d tenderproject_links_created=%d "
        "links_already_present=%d normalization_changes=%d errors=%d",
        counts["world_bank_tenders_with_project_id"],
        counts["valid_ids"],
        counts["invalid_skipped_ids"],
        counts["distinct_project_ids"],
        counts["projects_created"],
        counts["projects_reused"],
        counts["tenderproject_links_created"],
        counts["links_already_present"],
        counts["normalization_changes"],
        counts["errors"],
    )
    return counts


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.String(length=50), nullable=False),
        sa.Column("external_project_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("raw_provenance", sa.JSON(), nullable=True),
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
            name="ck_projects_source_system_allowed",
        ),
        sa.PrimaryKeyConstraint("id", name="projects_pkey"),
        sa.UniqueConstraint(
            "source_system",
            "external_project_id",
            name="uq_projects_source_external_project_id",
        ),
    )
    op.create_table(
        "tender_projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tender_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("linkage_method", sa.String(length=50), nullable=False),
        sa.Column("source_value", sa.String(length=100), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "linkage_method IN ('SOURCE_PROJECT_ID', 'SOURCE_NATIVE_LINK')",
            name="ck_tender_projects_linkage_method_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="tender_projects_project_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name="tender_projects_tender_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="tender_projects_pkey"),
        sa.UniqueConstraint("tender_id", name="uq_tender_projects_tender_id"),
    )
    op.create_index(
        "ix_tender_projects_project_id",
        "tender_projects",
        ["project_id"],
        unique=False,
    )
    _backfill_world_bank_projects(op.get_bind())


def downgrade() -> None:
    op.drop_index("ix_tender_projects_project_id", table_name="tender_projects")
    op.drop_table("tender_projects")
    op.drop_table("projects")
