"""multi_source_tender_foundation

Revision ID: 20260610_0001_multi_source_tender_foundation
Revises: a8f3d1c2e5b4
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = "20260610_0001_multi_source_tender_foundation"
down_revision: Union[str, None] = "a8f3d1c2e5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _print_existing_external_id_constraints() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    try:
        unique_constraints = inspector.get_unique_constraints("tenders")
        indexes = inspector.get_indexes("tenders")
    except Exception as exc:  # pragma: no cover - migration diagnostics only
        print(f"[INT-1] Could not inspect tenders constraints/indexes: {exc}")
        return

    external_constraints = [
        item
        for item in unique_constraints
        if item.get("column_names") == ["external_id"]
    ]
    external_indexes = [
        item for item in indexes if item.get("column_names") == ["external_id"]
    ]
    print(f"[INT-1] external_id unique constraints before migration: {external_constraints}")
    print(f"[INT-1] external_id indexes before migration: {external_indexes}")


def _ensure_alembic_version_column_width() -> None:
    """Let this long migration revision stamp into older Alembic tables."""
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('alembic_version') IS NOT NULL THEN
                ALTER TABLE alembic_version
                ALTER COLUMN version_num TYPE VARCHAR(128);
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    _ensure_alembic_version_column_width()
    _print_existing_external_id_constraints()

    op.execute("ALTER TABLE tenders ADD COLUMN IF NOT EXISTS source_system VARCHAR(50)")
    op.execute(
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS canonical_source_key VARCHAR(200)"
    )
    op.execute("ALTER TABLE tenders ADD COLUMN IF NOT EXISTS country VARCHAR(100)")
    op.execute("ALTER TABLE tenders ADD COLUMN IF NOT EXISTS sector VARCHAR(500)")
    op.execute("ALTER TABLE tenders ADD COLUMN IF NOT EXISTS buyer VARCHAR(300)")
    op.execute(
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS procurement_category VARCHAR(100)"
    )
    op.execute(
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS procurement_method VARCHAR(150)"
    )
    op.execute("ALTER TABLE tenders ADD COLUMN IF NOT EXISTS notice_type VARCHAR(150)")
    op.execute("ALTER TABLE tenders ADD COLUMN IF NOT EXISTS project_id VARCHAR(100)")
    op.execute(
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS publication_date TIMESTAMP WITH TIME ZONE"
    )
    op.execute("ALTER TABLE tenders ADD COLUMN IF NOT EXISTS source_metadata_json JSON")
    op.execute("ALTER TABLE tenders ADD COLUMN IF NOT EXISTS scrape_status VARCHAR(50)")
    op.execute(
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP WITH TIME ZONE"
    )

    op.execute(
        "ALTER TABLE tender_documents ADD COLUMN IF NOT EXISTS source_document_url VARCHAR(1000)"
    )
    op.execute(
        "ALTER TABLE tender_documents ADD COLUMN IF NOT EXISTS source_document_type VARCHAR(100)"
    )
    op.execute(
        "ALTER TABLE tender_documents ADD COLUMN IF NOT EXISTS download_status VARCHAR(50)"
    )
    op.execute("ALTER TABLE tender_documents ADD COLUMN IF NOT EXISTS download_error TEXT")
    op.execute(
        "ALTER TABLE tender_documents ADD COLUMN IF NOT EXISTS external_file_id VARCHAR(200)"
    )
    op.execute("ALTER TABLE tender_documents ADD COLUMN IF NOT EXISTS mime_type VARCHAR(150)")
    op.execute("ALTER TABLE tender_documents ADD COLUMN IF NOT EXISTS sha256 VARCHAR(64)")

    bind = op.get_bind()
    fallback_count = bind.execute(
        text(
            """
            SELECT count(*)
            FROM tenders
            WHERE external_id IS NULL OR btrim(external_id) = ''
            """
        )
    ).scalar_one()

    op.execute(
        """
        UPDATE tenders
        SET source_system = 'uzex'
        WHERE source_system IS NULL OR btrim(source_system) = ''
        """
    )
    op.execute(
        """
        UPDATE tenders
        SET source_system = lower(btrim(source_system))
        WHERE source_system IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE tenders
        SET source_system = 'uzex'
        WHERE source_system NOT IN ('uzex', 'world_bank', 'adb')
        """
    )
    op.execute(
        """
        UPDATE tenders
        SET canonical_source_key =
            CASE
                WHEN external_id IS NULL OR btrim(external_id) = ''
                    THEN source_system || ':legacy:' || id::text
                ELSE source_system || ':' || btrim(external_id)
            END
        WHERE canonical_source_key IS NULL OR btrim(canonical_source_key) = ''
        """
    )

    print(
        "[INT-1] Backfilled existing tenders with source_system='uzex'; "
        f"legacy fallback canonical_source_key count={fallback_count}"
    )

    op.execute("ALTER TABLE tenders ALTER COLUMN source_system SET DEFAULT 'uzex'")
    op.execute("ALTER TABLE tenders ALTER COLUMN source_system SET NOT NULL")
    op.execute("ALTER TABLE tenders ALTER COLUMN canonical_source_key SET NOT NULL")

    op.execute(
        """
        DO $$
        DECLARE
            constraint_name text;
        BEGIN
            FOR constraint_name IN
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                WHERE rel.relname = 'tenders'
                  AND nsp.nspname = current_schema()
                  AND con.contype = 'u'
                  AND (
                      SELECT array_agg(att.attname::text ORDER BY att.attnum)
                      FROM unnest(con.conkey) AS cols(attnum)
                      JOIN pg_attribute att
                        ON att.attrelid = con.conrelid
                       AND att.attnum = cols.attnum
                  ) = ARRAY['external_id']::text[]
            LOOP
                EXECUTE format('ALTER TABLE tenders DROP CONSTRAINT %I', constraint_name);
            END LOOP;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        DECLARE
            index_name text;
        BEGIN
            FOR index_name IN
                SELECT idx.relname
                FROM pg_index ind
                JOIN pg_class idx ON idx.oid = ind.indexrelid
                JOIN pg_class tbl ON tbl.oid = ind.indrelid
                JOIN pg_namespace nsp ON nsp.oid = tbl.relnamespace
                WHERE tbl.relname = 'tenders'
                  AND nsp.nspname = current_schema()
                  AND ind.indisunique
                  AND NOT EXISTS (
                      SELECT 1
                      FROM pg_constraint con
                      WHERE con.conindid = ind.indexrelid
                  )
                  AND (
                      SELECT array_agg(att.attname::text ORDER BY att.attnum)
                      FROM unnest(ind.indkey) AS cols(attnum)
                      JOIN pg_attribute att
                        ON att.attrelid = ind.indrelid
                       AND att.attnum = cols.attnum
                  ) = ARRAY['external_id']::text[]
            LOOP
                EXECUTE format('DROP INDEX IF EXISTS %I', index_name);
            END LOOP;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_tenders_source_system_allowed'
            ) THEN
                ALTER TABLE tenders
                ADD CONSTRAINT ck_tenders_source_system_allowed
                CHECK (source_system IN ('uzex', 'world_bank', 'adb'));
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_tenders_canonical_source_key
        ON tenders (canonical_source_key)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_tenders_source_system_external_id
        ON tenders (source_system, external_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenders_source_system
        ON tenders (source_system)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tenders_source_system")
    op.execute("DROP INDEX IF EXISTS ix_tenders_source_system_external_id")
    op.execute("DROP INDEX IF EXISTS ix_tenders_canonical_source_key")
    op.execute(
        "ALTER TABLE tenders DROP CONSTRAINT IF EXISTS ck_tenders_source_system_allowed"
    )
    op.create_unique_constraint(
        "tenders_external_id_key",
        "tenders",
        ["external_id"],
    )

    op.drop_column("tender_documents", "sha256")
    op.drop_column("tender_documents", "mime_type")
    op.drop_column("tender_documents", "external_file_id")
    op.drop_column("tender_documents", "download_error")
    op.drop_column("tender_documents", "download_status")
    op.drop_column("tender_documents", "source_document_type")
    op.drop_column("tender_documents", "source_document_url")

    op.drop_column("tenders", "last_synced_at")
    op.drop_column("tenders", "scrape_status")
    op.drop_column("tenders", "source_metadata_json")
    op.drop_column("tenders", "publication_date")
    op.drop_column("tenders", "project_id")
    op.drop_column("tenders", "notice_type")
    op.drop_column("tenders", "procurement_method")
    op.drop_column("tenders", "procurement_category")
    op.drop_column("tenders", "buyer")
    op.drop_column("tenders", "sector")
    op.drop_column("tenders", "country")
    op.drop_column("tenders", "canonical_source_key")
    op.drop_column("tenders", "source_system")
