#!/usr/bin/env python3
"""Read-only Sprint 0.3 PostgreSQL schema and data preflight.

The script deliberately avoids the application ORM and all application helpers.
It executes only SELECT/SHOW statements inside an explicit READ ONLY transaction,
rolls the transaction back unconditionally, and never includes connection secrets
or customer names in its JSON output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
from alembic.config import Config
from alembic.script import ScriptDirectory


SCRIPT_PATH = Path(__file__).resolve()
BACKEND_ROOT = SCRIPT_PATH.parents[1]
PROJECT_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
TABLES = (
    "users",
    "company_profiles",
    "tenders",
    "tender_documents",
    "tender_analyses",
    "analysis_versions",
    "analysis_version_document_snapshots",
    "proposals",
    "tender_recommendations",
    "risk_override_logs",
    "readiness_documents",
)
UUID_PATTERN = (
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
ENCODED_OWNER_PATTERN = rf"^(?:{UUID_PATTERN}):(?:(?:{UUID_PATTERN})|no-profile)$"
READ_ONLY_SQL_PATTERN = re.compile(r"^\s*(?:SELECT|SHOW|WITH)\b", re.IGNORECASE)
FORBIDDEN_SQL_PATTERN = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|"
    r"CALL|DO|COPY|VACUUM|ANALYZE|REFRESH|REINDEX|CLUSTER|COMMENT|LOCK)\b",
    re.IGNORECASE,
)


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name.strip()] = value
    return values


def _setting(name: str, file_values: dict[str, str]) -> str | None:
    return os.getenv(name) or file_values.get(name)


def _connection_kwargs(env_path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    file_values = _parse_env_file(env_path)
    source = "process environment" if any(
        os.getenv(name)
        for name in (
            "DATABASE_URL",
            "POSTGRES_SERVER",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_DB",
        )
    ) else str(env_path)

    database_url = _setting("DATABASE_URL", file_values)
    if database_url:
        dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        parsed = urlsplit(dsn)
        host = parsed.hostname or ""
        kwargs: dict[str, Any] = {"dsn": dsn}
    else:
        host = _setting("POSTGRES_SERVER", file_values) or ""
        required = {
            "host": host,
            "user": _setting("POSTGRES_USER", file_values),
            "password": _setting("POSTGRES_PASSWORD", file_values),
            "database": _setting("POSTGRES_DB", file_values),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError("database configuration is incomplete")
        port_raw = _setting("POSTGRES_PORT", file_values) or "5432"
        kwargs = {**required, "port": int(port_raw)}

    declared_environment = next(
        (
            value.strip().casefold()
            for name in ("PLASMA_ENV", "APP_ENV", "ENVIRONMENT")
            if (value := _setting(name, file_values))
        ),
        None,
    )
    host_is_loopback = host.casefold() in {"127.0.0.1", "localhost", "::1"}
    if host_is_loopback:
        descriptor = "local development PostgreSQL"
    elif declared_environment in {"prod", "production"}:
        descriptor = "PostgreSQL production (declared environment)"
    elif declared_environment in {"stage", "staging"}:
        descriptor = "PostgreSQL staging (declared environment)"
    else:
        descriptor = "remote PostgreSQL; environment identity unproven"

    return kwargs, {
        "engine": "PostgreSQL",
        "descriptor": descriptor,
        "configuration_source": source,
        "host_class": "loopback" if host_is_loopback else "remote-or-service",
    }


def _repository_heads() -> list[str]:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return sorted(ScriptDirectory.from_config(config).get_heads())


def _json_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, asyncpg.Record):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


class ReadOnlyPreflight:
    def __init__(self, connection: asyncpg.Connection, *, timeout: float) -> None:
        self.connection = connection
        self.timeout = timeout
        self.tables: set[str] = set()
        self.columns: dict[str, set[str]] = {}

    @staticmethod
    def _assert_read_only_sql(query: str) -> None:
        if (
            not READ_ONLY_SQL_PATTERN.match(query)
            or FORBIDDEN_SQL_PATTERN.search(query)
        ):
            raise RuntimeError("preflight attempted a non-read-only SQL statement")

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        self._assert_read_only_sql(query)
        return list(await self.connection.fetch(query, *args, timeout=self.timeout))

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        self._assert_read_only_sql(query)
        return await self.connection.fetchrow(query, *args, timeout=self.timeout)

    async def fetchval(self, query: str, *args: Any) -> Any:
        self._assert_read_only_sql(query)
        return await self.connection.fetchval(query, *args, timeout=self.timeout)

    def has_table(self, table: str) -> bool:
        return table in self.tables

    def has_columns(self, table: str, *columns: str) -> bool:
        return self.has_table(table) and set(columns).issubset(self.columns.get(table, set()))

    async def load_catalog(self) -> None:
        rows = await self.fetch(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
            """
        )
        for row in rows:
            table = str(row["table_name"])
            self.tables.add(table)
            self.columns.setdefault(table, set()).add(str(row["column_name"]))

    async def schema_snapshot(self, table: str) -> dict[str, Any] | None:
        if not self.has_table(table):
            return None
        columns = await self.fetch(
            """
            SELECT column_name, data_type, udt_name, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = $1
            ORDER BY ordinal_position
            """,
            table,
        )
        constraints = await self.fetch(
            """
            SELECT c.conname AS name, c.contype AS type,
                   pg_get_constraintdef(c.oid, true) AS definition
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'public' AND t.relname = $1
            ORDER BY c.contype, c.conname
            """,
            table,
        )
        indexes = await self.fetch(
            """
            SELECT indexname AS name, indexdef AS definition
            FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = $1
            ORDER BY indexname
            """,
            table,
        )
        return {
            "columns": _json_value(columns),
            "constraints": _json_value(constraints),
            "indexes": _json_value(indexes),
        }

    async def row_counts(self) -> dict[str, int | None]:
        counts: dict[str, int | None] = {}
        for table in TABLES:
            if not self.has_table(table):
                counts[table] = None
                continue
            counts[table] = int(await self.fetchval(f'SELECT COUNT(*) FROM "{table}"'))
        return counts

    async def recommendation_audit(self) -> dict[str, Any]:
        table = "tender_recommendations"
        snapshot = await self.schema_snapshot(table)
        if snapshot is None:
            return {"table_exists": False, "schema": None, "data": None}

        data: dict[str, Any] = {
            "rows": int(await self.fetchval(f"SELECT COUNT(*) FROM {table}")),
        }
        if self.has_columns(table, "is_dismissed"):
            data["dismissal_counts"] = _json_value(
                await self.fetch(
                    f"""
                    SELECT is_dismissed, COUNT(*) AS rows
                    FROM {table}
                    GROUP BY is_dismissed
                    ORDER BY is_dismissed
                    """
                )
            )
        if self.has_columns(table, "company_profile_id", "tender_id"):
            data["distinct_company_profiles"] = int(
                await self.fetchval(
                    f"SELECT COUNT(DISTINCT company_profile_id) FROM {table}"
                )
            )
            data["distinct_tenders"] = int(
                await self.fetchval(f"SELECT COUNT(DISTINCT tender_id) FROM {table}")
            )
            data["duplicate_tender_profile_groups"] = int(
                await self.fetchval(
                    f"""
                    SELECT COUNT(*) FROM (
                        SELECT tender_id, company_profile_id
                        FROM {table}
                        GROUP BY tender_id, company_profile_id
                        HAVING COUNT(*) > 1
                    ) duplicates
                    """
                )
            )
            if self.has_table("company_profiles"):
                data["orphaned_company_profiles"] = int(
                    await self.fetchval(
                        f"""
                        SELECT COUNT(*)
                        FROM {table} r
                        LEFT JOIN company_profiles c ON c.id = r.company_profile_id
                        WHERE c.id IS NULL
                        """
                    )
                )
            if self.has_table("tenders"):
                data["orphaned_tenders"] = int(
                    await self.fetchval(
                        f"""
                        SELECT COUNT(*)
                        FROM {table} r
                        LEFT JOIN tenders t ON t.id = r.tender_id
                        WHERE t.id IS NULL
                        """
                    )
                )
        return {"table_exists": True, "schema": snapshot, "data": data}

    async def proposal_audit(self) -> dict[str, Any]:
        table = "proposals"
        snapshot = await self.schema_snapshot(table)
        if snapshot is None:
            return {"table_exists": False, "schema": None, "data": None}

        data: dict[str, Any] = {
            "rows": int(await self.fetchval("SELECT COUNT(*) FROM proposals")),
        }
        if self.has_columns(table, "status"):
            data["status_counts"] = _json_value(
                await self.fetch(
                    """
                    SELECT status::text AS status, COUNT(*) AS rows
                    FROM proposals
                    GROUP BY status::text
                    ORDER BY status::text
                    """
                )
            )
        for column in ("user_id", "tender_id"):
            if self.has_columns(table, column):
                data[f"null_{column}"] = int(
                    await self.fetchval(
                        f"SELECT COUNT(*) FROM proposals WHERE {column} IS NULL"
                    )
                )
        if self.has_columns(table, "user_id", "tender_id"):
            duplicate = await self.fetchrow(
                """
                SELECT COUNT(*) AS duplicate_groups,
                       COALESCE(SUM(group_rows - 1), 0)::bigint AS excess_rows
                FROM (
                    SELECT COUNT(*)::bigint AS group_rows
                    FROM proposals
                    GROUP BY user_id, tender_id
                    HAVING COUNT(*) > 1
                ) groups
                """
            )
            data["duplicate_user_tender"] = _json_value(duplicate)
        if self.has_columns(table, "final_pdf_url"):
            data["final_pdf_url_populated"] = int(
                await self.fetchval(
                    """
                    SELECT COUNT(*) FROM proposals
                    WHERE NULLIF(BTRIM(final_pdf_url), '') IS NOT NULL
                    """
                )
            )
        if self.has_columns(table, "structured_data"):
            structured = await self.fetchrow(
                """
                SELECT COUNT(*) FILTER (WHERE structured_data IS NULL) AS null_rows,
                       COUNT(*) FILTER (
                           WHERE structured_data IS NOT NULL
                             AND structured_data::jsonb = '{}'::jsonb
                       ) AS empty_object_rows,
                       COUNT(*) FILTER (
                           WHERE structured_data IS NOT NULL
                             AND structured_data::jsonb <> '{}'::jsonb
                       ) AS populated_rows
                FROM proposals
                """
            )
            data["structured_data"] = _json_value(structured)
        timestamp_columns = [
            column for column in ("created_at", "updated_at") if self.has_columns(table, column)
        ]
        if timestamp_columns:
            expressions = ", ".join(
                f"MIN({column}) AS min_{column}, MAX({column}) AS max_{column}"
                for column in timestamp_columns
            )
            data["timestamp_ranges"] = _json_value(
                await self.fetchrow(f"SELECT {expressions} FROM proposals")
            )
        if self.has_table("users") and self.has_columns(table, "user_id"):
            data["orphaned_users"] = int(
                await self.fetchval(
                    """
                    SELECT COUNT(*) FROM proposals p
                    LEFT JOIN users u ON u.id = p.user_id
                    WHERE u.id IS NULL
                    """
                )
            )
        if self.has_table("tenders") and self.has_columns(table, "tender_id"):
            data["orphaned_tenders"] = int(
                await self.fetchval(
                    """
                    SELECT COUNT(*) FROM proposals p
                    LEFT JOIN tenders t ON t.id = p.tender_id
                    WHERE t.id IS NULL
                    """
                )
            )
        return {"table_exists": True, "schema": snapshot, "data": data}

    def _legacy_candidate_sql(self) -> str:
        candidates: list[str] = []
        if self.has_columns("company_profiles", "company_name"):
            candidates.append(
                "SELECT BTRIM(company_name) AS owner_name FROM company_profiles"
            )
        if self.has_columns("users", "company_name"):
            candidates.append("SELECT BTRIM(company_name) AS owner_name FROM users")
        if self.has_columns("users", "name"):
            candidates.append("SELECT BTRIM(name) AS owner_name FROM users")
        if not candidates:
            return "SELECT NULL::text AS owner_name WHERE false"
        return " UNION ".join(candidates)

    async def analysis_audit(self) -> dict[str, Any]:
        table = "tender_analyses"
        snapshot = await self.schema_snapshot(table)
        if snapshot is None:
            return {"table_exists": False, "schema": None, "data": None}
        if not self.has_columns(table, "company_name"):
            return {
                "table_exists": True,
                "schema": snapshot,
                "data": {"ownership_classification": "company_name column unavailable"},
            }

        candidates = self._legacy_candidate_sql()
        classification_cte = f"""
            WITH legacy_candidates AS (
                SELECT DISTINCT owner_name
                FROM ({candidates}) source
                WHERE NULLIF(owner_name, '') IS NOT NULL
            ), classified AS (
                SELECT a.*,
                    CASE
                        WHEN a.company_name IS NULL OR a.company_name = '' THEN 'C_null_or_empty'
                        WHEN a.company_name ~* $1 THEN 'A_encoded_uuid'
                        WHEN EXISTS (
                            SELECT 1 FROM legacy_candidates c
                            WHERE c.owner_name = a.company_name
                        ) OR POSITION(':' IN a.company_name) = 0
                            THEN 'B_legacy_display_name'
                        ELSE 'D_malformed_or_unknown'
                    END AS owner_category
                FROM tender_analyses a
            )
        """
        category_rows = await self.fetch(
            classification_cte
            + """
            SELECT owner_category, COUNT(*) AS rows
            FROM classified
            GROUP BY owner_category
            ORDER BY owner_category
            """,
            ENCODED_OWNER_PATTERN,
        )

        data: dict[str, Any] = {
            "rows": int(await self.fetchval("SELECT COUNT(*) FROM tender_analyses")),
            "ownership_categories": _json_value(category_rows),
        }

        if self.has_columns(
            table,
            "user_id",
            "company_profile_id",
            "ownership_state",
        ) and self.has_table("users") and self.has_table("company_profiles"):
            canonical_ownership = await self.fetchrow(
                """
                SELECT
                    COUNT(*) AS total_analyses,
                    COUNT(*) FILTER (
                        WHERE a.ownership_state = 'OWNED'
                    ) AS owned,
                    COUNT(*) FILTER (
                        WHERE a.ownership_state = 'QUARANTINED_LEGACY'
                    ) AS quarantined,
                    COUNT(*) FILTER (
                        WHERE a.ownership_state = 'OWNED'
                          AND (u.id IS NULL OR cp.id IS NULL)
                    ) AS invalid_fk,
                    COUNT(*) FILTER (
                        WHERE a.ownership_state = 'OWNED'
                          AND u.id IS NOT NULL
                          AND cp.id IS NOT NULL
                          AND cp.user_id <> u.id
                    ) AS user_profile_mismatch,
                    COUNT(*) FILTER (
                        WHERE NOT (
                            (a.ownership_state = 'OWNED'
                             AND a.user_id IS NOT NULL
                             AND a.company_profile_id IS NOT NULL)
                            OR
                            (a.ownership_state = 'QUARANTINED_LEGACY'
                             AND a.user_id IS NULL
                             AND a.company_profile_id IS NULL)
                        )
                    ) AS invalid_ownership_tuple,
                    COUNT(*) FILTER (
                        WHERE a.ownership_state = 'QUARANTINED_LEGACY'
                          AND a.company_name ~* $1
                    ) AS quarantined_encoded_remnants,
                    COUNT(*) FILTER (
                        WHERE a.ownership_state = 'QUARANTINED_LEGACY'
                          AND NULLIF(BTRIM(a.company_name), '') IS NOT NULL
                          AND NOT (a.company_name ~* $1)
                    ) AS quarantined_legacy_name_or_malformed_remnants
                FROM tender_analyses a
                LEFT JOIN users u ON u.id = a.user_id
                LEFT JOIN company_profiles cp ON cp.id = a.company_profile_id
                """,
                ENCODED_OWNER_PATTERN,
            )
            data["canonical_ownership"] = _json_value(canonical_ownership)

        if self.has_table("users") and self.has_table("company_profiles"):
            encoded_rows = await self.fetch(
                """
                WITH encoded AS (
                    SELECT a.id,
                           SPLIT_PART(a.company_name, ':', 1) AS user_token,
                           SPLIT_PART(a.company_name, ':', 2) AS profile_token
                    FROM tender_analyses a
                    WHERE a.company_name ~* $1
                ), mapped AS (
                    SELECT e.*,
                           u.id AS existing_user_id,
                           token_profile.id AS token_profile_id,
                           token_profile.user_id AS token_profile_user_id,
                           current_profile.id AS current_profile_id,
                           CASE
                               WHEN u.id IS NULL THEN 'missing_user'
                               WHEN e.profile_token = 'no-profile'
                                    AND current_profile.id IS NULL
                                   THEN 'existing_user_missing_profile'
                               WHEN e.profile_token = 'no-profile'
                                    AND current_profile.id IS NOT NULL
                                   THEN 'inconsistent_relationship'
                               WHEN token_profile.id IS NULL THEN 'missing_company_profile'
                               WHEN token_profile.user_id <> u.id
                                   THEN 'inconsistent_relationship'
                               ELSE 'valid_user_and_profile'
                           END AS mapping_status
                    FROM encoded e
                    LEFT JOIN users u ON u.id::text = LOWER(e.user_token)
                    LEFT JOIN company_profiles token_profile
                        ON e.profile_token <> 'no-profile'
                       AND token_profile.id::text = LOWER(e.profile_token)
                    LEFT JOIN company_profiles current_profile
                        ON current_profile.user_id::text = LOWER(e.user_token)
                )
                SELECT mapping_status, COUNT(*) AS rows
                FROM mapped
                GROUP BY mapping_status
                ORDER BY mapping_status
                """,
                ENCODED_OWNER_PATTERN,
            )
            data["encoded_mapping"] = _json_value(encoded_rows)

            legacy_mapping = await self.fetch(
                classification_cte
                + """
                , legacy_names AS (
                    SELECT company_name AS owner_name, COUNT(*) AS analysis_rows
                    FROM classified
                    WHERE owner_category = 'B_legacy_display_name'
                    GROUP BY company_name
                ), profile_matches AS (
                    SELECT l.owner_name, l.analysis_rows,
                           COUNT(cp.id) AS profile_count,
                           COUNT(u.id) AS valid_profile_user_count
                    FROM legacy_names l
                    LEFT JOIN company_profiles cp
                        ON BTRIM(cp.company_name) = l.owner_name
                    LEFT JOIN users u ON u.id = cp.user_id
                    GROUP BY l.owner_name, l.analysis_rows
                ), categorized AS (
                    SELECT *,
                        CASE
                            WHEN profile_count = 1 AND valid_profile_user_count = 1
                                THEN 'unique_valid_profile'
                            WHEN profile_count = 1 AND valid_profile_user_count = 0
                                THEN 'unique_profile_missing_user'
                            WHEN profile_count > 1 THEN 'multiple_profiles'
                            ELSE 'no_profile'
                        END AS mapping_status
                    FROM profile_matches
                )
                SELECT mapping_status,
                       COUNT(*) AS unique_owner_names,
                       COALESCE(SUM(analysis_rows), 0)::bigint AS analysis_rows
                FROM categorized
                GROUP BY mapping_status
                ORDER BY mapping_status
                """,
                ENCODED_OWNER_PATTERN,
            )
            data["legacy_mapping"] = _json_value(legacy_mapping)

            quarantine = await self.fetchrow(
                classification_cte
                + """
                , encoded AS (
                    SELECT a.id,
                           SPLIT_PART(a.company_name, ':', 1) AS user_token,
                           SPLIT_PART(a.company_name, ':', 2) AS profile_token
                    FROM tender_analyses a
                    WHERE a.company_name ~* $1
                ), valid_encoded AS (
                    SELECT e.id
                    FROM encoded e
                    JOIN users u ON u.id::text = LOWER(e.user_token)
                    JOIN company_profiles cp
                      ON e.profile_token <> 'no-profile'
                     AND cp.id::text = LOWER(e.profile_token)
                     AND cp.user_id = u.id
                )
                SELECT
                    COUNT(*) FILTER (
                        WHERE c.owner_category = 'A_encoded_uuid'
                          AND ve.id IS NOT NULL
                    ) AS safe_encoded_rows,
                    0::bigint AS safe_legacy_rows,
                    COUNT(*) FILTER (
                        WHERE NOT (
                            (c.owner_category = 'A_encoded_uuid' AND ve.id IS NOT NULL)
                        )
                    ) AS quarantine_or_manual_review_rows
                FROM classified c
                LEFT JOIN valid_encoded ve ON ve.id = c.id
                """,
                ENCODED_OWNER_PATTERN,
            )
            data["conservative_backfill_safety"] = _json_value(quarantine)

            resolved = await self.fetchrow(
                """
                WITH valid AS (
                    SELECT a.id, a.tender_id,
                           SPLIT_PART(a.company_name, ':', 1) AS user_token,
                           SPLIT_PART(a.company_name, ':', 2) AS profile_token
                    FROM tender_analyses a
                    JOIN users u
                      ON u.id::text = LOWER(SPLIT_PART(a.company_name, ':', 1))
                    JOIN company_profiles cp
                      ON cp.id::text = LOWER(SPLIT_PART(a.company_name, ':', 2))
                     AND cp.user_id = u.id
                    WHERE a.company_name ~* $1
                ), user_counts AS (
                    SELECT user_token, COUNT(*) AS rows FROM valid GROUP BY user_token
                ), company_counts AS (
                    SELECT profile_token, COUNT(*) AS rows FROM valid GROUP BY profile_token
                )
                SELECT
                    (SELECT COUNT(DISTINCT tender_id) FROM valid) AS resolved_tenders,
                    (SELECT COUNT(*) FROM user_counts) AS resolved_users,
                    (SELECT COALESCE(MAX(rows), 0) FROM user_counts) AS max_analyses_per_user,
                    (SELECT COUNT(*) FROM company_counts) AS resolved_companies,
                    (SELECT COALESCE(MAX(rows), 0) FROM company_counts)
                        AS max_analyses_per_company
                """,
                ENCODED_OWNER_PATTERN,
            )
            data["resolved_encoded_distribution"] = _json_value(resolved)

        summary_expressions = [
            "COUNT(DISTINCT tender_id) AS distinct_tenders"
            if self.has_columns(table, "tender_id")
            else "NULL::bigint AS distinct_tenders",
            "MIN(created_at) AS min_created_at, MAX(created_at) AS max_created_at"
            if self.has_columns(table, "created_at")
            else "NULL::timestamptz AS min_created_at, NULL::timestamptz AS max_created_at",
            "COUNT(*) FILTER (WHERE analysis_json IS NULL) AS null_analysis_json"
            if self.has_columns(table, "analysis_json")
            else "NULL::bigint AS null_analysis_json",
            "COUNT(*) FILTER (WHERE content_hash IS NULL OR content_hash = '') AS missing_content_hash"
            if self.has_columns(table, "content_hash")
            else "NULL::bigint AS missing_content_hash",
        ]
        data["analysis_summary"] = _json_value(
            await self.fetchrow(
                "SELECT " + ", ".join(summary_expressions) + " FROM tender_analyses"
            )
        )
        if self.has_columns(table, "content_hash"):
            data["duplicate_content_hash"] = _json_value(
                await self.fetchrow(
                    """
                    SELECT COUNT(*) AS duplicate_hash_groups,
                           COALESCE(SUM(rows - 1), 0)::bigint AS repeated_rows
                    FROM (
                        SELECT content_hash, COUNT(*)::bigint AS rows
                        FROM tender_analyses
                        WHERE NULLIF(content_hash, '') IS NOT NULL
                        GROUP BY content_hash
                        HAVING COUNT(*) > 1
                    ) duplicate_hashes
                    """
                )
            )
        if self.has_columns(table, "analysis_json"):
            data["provenance_presence"] = _json_value(
                await self.fetchrow(
                    """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE analysis_json::jsonb ? 'evidence_validation'
                        ) AS with_evidence_validation,
                        COUNT(*) FILTER (
                            WHERE analysis_json::jsonb ? 'reproducibility_snapshot'
                        ) AS with_reproducibility_snapshot,
                        COUNT(*) FILTER (
                            WHERE analysis_json::jsonb ? 'extraction_artifacts_metadata'
                        ) AS with_extraction_artifacts_metadata
                    FROM tender_analyses
                    """
                )
            )
        if self.has_table("tenders") and self.has_columns(table, "tender_id"):
            data["orphaned_tenders"] = int(
                await self.fetchval(
                    """
                    SELECT COUNT(*) FROM tender_analyses a
                    LEFT JOIN tenders t ON t.id = a.tender_id
                    WHERE t.id IS NULL
                    """
                )
            )
        return {"table_exists": True, "schema": snapshot, "data": data}

    async def analysis_version_audit(self) -> dict[str, Any]:
        """Report version-history invariants without exposing snapshot content."""
        version_table = "analysis_versions"
        document_table = "analysis_version_document_snapshots"
        if not self.has_table(version_table):
            return {
                "table_exists": False,
                "document_snapshot_table_exists": self.has_table(document_table),
                "data": None,
            }

        required = {
            "analysis_id",
            "version_number",
            "supersedes_version_id",
            "snapshot_completeness",
            "input_hash",
            "output_hash",
            "evidence_hash",
            "document_set_hash",
            "version_hash",
        }
        if not required.issubset(self.columns.get(version_table, set())):
            return {
                "table_exists": True,
                "document_snapshot_table_exists": self.has_table(document_table),
                "data": {"audit_available": False},
            }

        parent_distribution = await self.fetchrow(
            """
            WITH version_counts AS (
                SELECT a.id, COUNT(v.id)::bigint AS version_count
                FROM tender_analyses a
                LEFT JOIN analysis_versions v ON v.analysis_id = a.id
                GROUP BY a.id
            )
            SELECT
                COUNT(*) AS total_tender_analyses,
                COUNT(*) FILTER (WHERE version_count = 0) AS analyses_with_zero_versions,
                COUNT(*) FILTER (WHERE version_count = 1) AS analyses_with_one_version,
                COUNT(*) FILTER (WHERE version_count > 1) AS analyses_with_multiple_versions
            FROM version_counts
            """
        )
        version_integrity = await self.fetchrow(
            """
            SELECT
                COUNT(*) AS total_analysis_versions,
                COUNT(*) FILTER (WHERE parent.id IS NULL) AS version_parent_orphans,
                COUNT(*) FILTER (
                    WHERE (
                        v.version_number = 1
                        AND v.supersedes_version_id IS NOT NULL
                    ) OR (
                        v.version_number > 1
                        AND (
                            v.supersedes_version_id IS NULL
                            OR predecessor.id IS NULL
                            OR predecessor.analysis_id <> v.analysis_id
                            OR predecessor.version_number <> v.version_number - 1
                        )
                    )
                ) AS broken_supersedes_references,
                COUNT(DISTINCT v.analysis_id) FILTER (
                    WHERE parent.ownership_state = 'QUARANTINED_LEGACY'
                ) AS quarantined_analyses_with_versions,
                COUNT(*) FILTER (WHERE v.snapshot_completeness = 'COMPLETE')
                    AS snapshot_complete,
                COUNT(*) FILTER (WHERE v.snapshot_completeness = 'PARTIAL')
                    AS snapshot_partial,
                COUNT(*) FILTER (WHERE v.snapshot_completeness = 'LEGACY_BACKFILL')
                    AS snapshot_legacy_backfill,
                COUNT(*) FILTER (WHERE NULLIF(v.input_hash, '') IS NULL)
                    AS missing_input_hash,
                COUNT(*) FILTER (WHERE NULLIF(v.output_hash, '') IS NULL)
                    AS missing_output_hash,
                COUNT(*) FILTER (WHERE NULLIF(v.evidence_hash, '') IS NULL)
                    AS missing_evidence_hash,
                COUNT(*) FILTER (WHERE NULLIF(v.document_set_hash, '') IS NULL)
                    AS missing_document_set_hash,
                COUNT(*) FILTER (WHERE NULLIF(v.version_hash, '') IS NULL)
                    AS missing_version_hash
            FROM analysis_versions v
            LEFT JOIN tender_analyses parent ON parent.id = v.analysis_id
            LEFT JOIN analysis_versions predecessor
              ON predecessor.id = v.supersedes_version_id
            """
        )
        duplicate_versions = await self.fetchrow(
            """
            SELECT COUNT(*) AS duplicate_version_number_groups,
                   COALESCE(SUM(rows - 1), 0)::bigint AS duplicate_version_number_rows
            FROM (
                SELECT analysis_id, version_number, COUNT(*)::bigint AS rows
                FROM analysis_versions
                GROUP BY analysis_id, version_number
                HAVING COUNT(*) > 1
            ) duplicates
            """
        )

        document_hashes: dict[str, Any] | None = None
        if self.has_columns(
            document_table,
            "analysis_version_id",
            "content_hash",
            "snapshot_metadata",
        ):
            document_hashes = _json_value(
                await self.fetchrow(
                    """
                    SELECT
                        COUNT(*) AS total_document_snapshots,
                        COUNT(*) FILTER (WHERE version.id IS NULL)
                            AS document_snapshot_version_orphans,
                        COUNT(*) FILTER (WHERE NULLIF(d.content_hash, '') IS NULL)
                            AS missing_document_hash,
                        COUNT(*) FILTER (
                            WHERE NULLIF(d.content_hash, '') IS NULL
                              AND NULLIF(
                                  d.snapshot_metadata->>'parsed_text_sha256', ''
                              ) IS NULL
                        ) AS missing_all_known_document_hashes
                    FROM analysis_version_document_snapshots d
                    LEFT JOIN analysis_versions version
                      ON version.id = d.analysis_version_id
                    """
                )
            )

        return {
            "table_exists": True,
            "document_snapshot_table_exists": self.has_table(document_table),
            "data": {
                "parent_distribution": _json_value(parent_distribution),
                "version_integrity": _json_value(version_integrity),
                "duplicate_version_numbers": _json_value(duplicate_versions),
                "document_hashes": document_hashes,
            },
        }

    async def identity_audit(self, privileged_emails: list[str]) -> dict[str, Any]:
        if not self.has_table("users") or not self.has_table("company_profiles"):
            return {"available": False}
        data: dict[str, Any] = {
            "available": True,
            "total_users": int(await self.fetchval("SELECT COUNT(*) FROM users")),
            "total_company_profiles": int(
                await self.fetchval("SELECT COUNT(*) FROM company_profiles")
            ),
            "users_without_profile": int(
                await self.fetchval(
                    """
                    SELECT COUNT(*) FROM users u
                    LEFT JOIN company_profiles cp ON cp.user_id = u.id
                    WHERE cp.id IS NULL
                    """
                )
            ),
            "profiles_without_valid_user": int(
                await self.fetchval(
                    """
                    SELECT COUNT(*) FROM company_profiles cp
                    LEFT JOIN users u ON u.id = cp.user_id
                    WHERE u.id IS NULL
                    """
                )
            ),
        }
        if self.has_columns("company_profiles", "company_name"):
            data["duplicate_exact_company_names"] = int(
                await self.fetchval(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT BTRIM(company_name)
                        FROM company_profiles
                        WHERE NULLIF(BTRIM(company_name), '') IS NOT NULL
                        GROUP BY BTRIM(company_name)
                        HAVING COUNT(*) > 1
                    ) collisions
                    """
                )
            )
            data["duplicate_normalized_company_names"] = int(
                await self.fetchval(
                    r"""
                    SELECT COUNT(*) FROM (
                        SELECT LOWER(REGEXP_REPLACE(BTRIM(company_name), '\s+', ' ', 'g'))
                        FROM company_profiles
                        WHERE NULLIF(BTRIM(company_name), '') IS NOT NULL
                        GROUP BY LOWER(REGEXP_REPLACE(BTRIM(company_name), '\s+', ' ', 'g'))
                        HAVING COUNT(*) > 1
                    ) collisions
                    """
                )
            )
        if self.has_columns("users", "approval_status"):
            data["user_approval_statuses"] = _json_value(
                await self.fetch(
                    """
                    SELECT approval_status, COUNT(*) AS rows
                    FROM users GROUP BY approval_status ORDER BY approval_status
                    """
                )
            )
        if self.has_columns("company_profiles", "approval_status"):
            data["company_approval_statuses"] = _json_value(
                await self.fetch(
                    """
                    SELECT approval_status, COUNT(*) AS rows
                    FROM company_profiles GROUP BY approval_status ORDER BY approval_status
                    """
                )
            )
        if self.has_columns("users", "platform_role"):
            data["platform_roles"] = _json_value(
                await self.fetch(
                    """
                    SELECT platform_role, COUNT(*) AS rows
                    FROM users GROUP BY platform_role ORDER BY platform_role
                    """
                )
            )
        if self.has_columns("users", "approval_status", "platform_role", "is_admin", "email"):
            data["disabled_privileged_accounts"] = int(
                await self.fetchval(
                    """
                    SELECT COUNT(*) FROM users
                    WHERE LOWER(BTRIM(approval_status)) = 'disabled'
                      AND (
                          is_admin IS TRUE
                          OR platform_role IN ('admin', 'operator')
                          OR LOWER(BTRIM(email)) = ANY($1::text[])
                      )
                    """,
                    privileged_emails,
                )
            )
        return data

    async def project_id_audit(self) -> dict[str, Any]:
        if not self.has_columns("tenders", "source_system", "project_id"):
            return {"available": False}
        output: dict[str, Any] = {"available": True, "sources": {}}
        for source in ("world_bank", "adb"):
            summary = await self.fetchrow(
                """
                WITH scoped AS (
                    SELECT project_id
                    FROM tenders
                    WHERE LOWER(BTRIM(source_system)) = $1
                ), present AS (
                    SELECT project_id, BTRIM(project_id) AS normalized_id
                    FROM scoped
                    WHERE NULLIF(BTRIM(project_id), '') IS NOT NULL
                ), reused AS (
                    SELECT normalized_id, COUNT(*) AS rows
                    FROM present GROUP BY normalized_id HAVING COUNT(*) > 1
                ), case_variants AS (
                    SELECT LOWER(normalized_id)
                    FROM present
                    GROUP BY LOWER(normalized_id)
                    HAVING COUNT(DISTINCT normalized_id) > 1
                )
                SELECT
                    (SELECT COUNT(*) FROM scoped) AS total_tenders,
                    (SELECT COUNT(*) FROM present) AS with_project_id,
                    (SELECT COUNT(*) FROM scoped)
                        - (SELECT COUNT(*) FROM present) AS without_project_id,
                    (SELECT COUNT(DISTINCT normalized_id) FROM present)
                        AS distinct_project_ids,
                    (SELECT COUNT(*) FROM reused) AS reused_project_id_groups,
                    (SELECT COALESCE(SUM(rows), 0) FROM reused)
                        AS tenders_in_reused_groups,
                    (SELECT COUNT(*) FROM present
                        WHERE project_id <> normalized_id) AS leading_trailing_whitespace,
                    (SELECT COUNT(*) FROM present
                        WHERE normalized_id ~ '\\s') AS internal_whitespace,
                    (SELECT COUNT(*) FROM present
                        WHERE LOWER(normalized_id) IN
                            ('n/a', 'na', 'none', 'null', 'unknown', '-', '0', 'tbd'))
                        AS obvious_placeholders,
                    (SELECT COUNT(*) FROM present
                        WHERE LENGTH(normalized_id) > 100
                           OR normalized_id !~ '^[[:alnum:]][[:alnum:]._/-]*$')
                        AS suspicious_generic_format,
                    (SELECT COUNT(*) FROM case_variants) AS casing_variant_groups
                """,
                source,
            )
            output["sources"][source] = _json_value(summary)
        output["cross_source_project_id_collisions"] = int(
            await self.fetchval(
                """
                WITH scoped AS (
                    SELECT LOWER(BTRIM(source_system)) AS source,
                           LOWER(BTRIM(project_id)) AS project_id
                    FROM tenders
                    WHERE LOWER(BTRIM(source_system)) IN ('world_bank', 'adb')
                      AND NULLIF(BTRIM(project_id), '') IS NOT NULL
                )
                SELECT COUNT(*) FROM (
                    SELECT project_id
                    FROM scoped
                    GROUP BY project_id
                    HAVING COUNT(DISTINCT source) > 1
                ) collisions
                """
            )
        )
        return output

    async def referential_integrity(self) -> dict[str, int | None]:
        relationships = (
            ("tender_documents", "tender_id", "tenders", "id"),
            ("proposals", "tender_id", "tenders", "id"),
            ("proposals", "user_id", "users", "id"),
            ("tender_analyses", "tender_id", "tenders", "id"),
            ("tender_recommendations", "tender_id", "tenders", "id"),
            (
                "tender_recommendations",
                "company_profile_id",
                "company_profiles",
                "id",
            ),
            ("risk_override_logs", "user_id", "users", "id"),
            ("risk_override_logs", "tender_id", "tenders", "id"),
            ("risk_override_logs", "analysis_id", "tender_analyses", "id"),
            (
                "readiness_documents",
                "company_profile_id",
                "company_profiles",
                "id",
            ),
        )
        output: dict[str, int | None] = {}
        for child, child_key, parent, parent_key in relationships:
            label = f"{child}.{child_key}_to_{parent}.{parent_key}"
            if not (
                self.has_columns(child, child_key)
                and self.has_columns(parent, parent_key)
            ):
                output[label] = None
                continue
            nullable_filter = f"c.{child_key} IS NOT NULL AND "
            output[label] = int(
                await self.fetchval(
                    f"""
                    SELECT COUNT(*)
                    FROM {child} c
                    LEFT JOIN {parent} p ON p.{parent_key} = c.{child_key}
                    WHERE {nullable_filter}p.{parent_key} IS NULL
                    """
                )
            )
        return output


def _allowlisted_privileged_emails(env_path: Path) -> list[str]:
    file_values = _parse_env_file(env_path)
    emails: set[str] = set()
    for name in ("PLASMA_ADMIN_EMAILS", "PLASMA_OPERATOR_EMAILS"):
        raw = _setting(name, file_values) or ""
        emails.update(
            email.strip().casefold() for email in raw.split(",") if email.strip()
        )
    return sorted(emails)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    env_path = Path(args.env_file).resolve()
    connection_kwargs, environment = _connection_kwargs(env_path)
    connection = await asyncpg.connect(**connection_kwargs, timeout=args.connect_timeout)
    transaction = connection.transaction(readonly=True)
    await transaction.start()
    try:
        runner = ReadOnlyPreflight(connection, timeout=args.query_timeout)
        transaction_read_only = await runner.fetchval("SHOW transaction_read_only")
        if str(transaction_read_only).casefold() != "on":
            raise RuntimeError("database transaction is not read-only")
        await runner.load_catalog()

        current_revisions: list[str] | None
        if runner.has_columns("alembic_version", "version_num"):
            current_revisions = sorted(
                str(row["version_num"])
                for row in await runner.fetch(
                    "SELECT version_num FROM alembic_version ORDER BY version_num"
                )
            )
        else:
            current_revisions = None

        schema = {
            table: await runner.schema_snapshot(table)
            for table in TABLES
        }
        return {
            "environment": environment,
            "safety": {
                "transaction_read_only": True,
                "orm_used": False,
                "application_helpers_used": False,
                "commit_called": False,
                "transaction_completion": "rollback in finally",
            },
            "database": {
                "server_version": str(
                    await runner.fetchval("SHOW server_version")
                ),
                "current_alembic_revisions": current_revisions,
                "repository_heads": _repository_heads(),
            },
            "data_volume": await runner.row_counts(),
            "schema": schema,
            "tender_recommendations": await runner.recommendation_audit(),
            "proposals": await runner.proposal_audit(),
            "tender_analyses": await runner.analysis_audit(),
            "analysis_versions": await runner.analysis_version_audit(),
            "identity": await runner.identity_audit(
                _allowlisted_privileged_emails(env_path)
            ),
            "project_ids": await runner.project_id_audit(),
            "referential_integrity": await runner.referential_integrity(),
        }
    finally:
        await transaction.rollback()
        await connection.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the read-only Sprint 0.3 PostgreSQL preflight."
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_PATH),
        help="Environment file used only when process variables are absent.",
    )
    parser.add_argument("--connect-timeout", type=float, default=5.0)
    parser.add_argument("--query-timeout", type=float, default=60.0)
    parser.add_argument("--compact", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = asyncio.run(_run(args))
    except Exception as exc:  # noqa: BLE001 - redact all connection/query details.
        print(
            json.dumps(
                {
                    "status": "execution_error",
                    "error_type": type(exc).__name__,
                    "details_redacted": True,
                },
                sort_keys=True,
            )
        )
        return 2

    print(
        json.dumps(
            {"status": "ok", **_json_value(result)},
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
