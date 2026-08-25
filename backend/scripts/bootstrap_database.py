#!/usr/bin/env python3
"""Bootstrap a genuinely empty PostgreSQL 16 database from the immutable 0.4c baseline.

The target URL is read from an environment variable so credentials are not
placed in process arguments. This command is intentionally not an existing
database repair tool: any user object causes a fail-closed refusal.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

import asyncpg
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import URL, make_url


BACKEND_DIR = Path(__file__).resolve().parents[1]
BASELINE_DIR = BACKEND_DIR / "db" / "baselines"
MANIFEST_PATH = BASELINE_DIR / "20260824_0002_s0_4c.manifest.json"
DEFAULT_URL_ENV = "PLASMA_BOOTSTRAP_DATABASE_URL"
CONFIRMATION = "BOOTSTRAP_EMPTY_DATABASE"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
SYSTEM_SCHEMAS = {"information_schema"}


class BootstrapError(RuntimeError):
    """A deliberate, operator-facing bootstrap refusal or failure."""


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BootstrapError(f"cannot read baseline manifest: {exc}") from exc

    required = {
        "baseline_revision",
        "expected_next_revision",
        "schema_format_version",
        "snapshot_file",
        "snapshot_sha256",
        "tables",
        "views",
        "enum_types",
        "important_constraints",
        "important_indexes",
        "validated_postgresql_majors",
        "downgrade_floor",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise BootstrapError(f"baseline manifest is missing fields: {', '.join(missing)}")
    if manifest["baseline_revision"] != manifest["downgrade_floor"]:
        raise BootstrapError("manifest baseline revision and downgrade floor disagree")
    return manifest


def snapshot_path(manifest: Mapping[str, Any]) -> Path:
    name = manifest["snapshot_file"]
    if not isinstance(name, str) or Path(name).name != name:
        raise BootstrapError("manifest snapshot_file must name a repository-owned file")
    path = (BASELINE_DIR / name).resolve()
    if path.parent != BASELINE_DIR.resolve():
        raise BootstrapError("baseline snapshot resolved outside the repository baseline directory")
    return path


def verify_snapshot_hash(path: Path, expected_sha256: str) -> str:
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise BootstrapError(f"cannot read baseline snapshot: {exc}") from exc
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_sha256)):
        raise BootstrapError("manifest snapshot SHA-256 is malformed")
    if digest != expected_sha256:
        raise BootstrapError(
            "immutable baseline hash mismatch; refuse execution and use the documented "
            "maintainer review procedure"
        )
    return digest


def repository_head() -> str:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise BootstrapError(f"expected one linear Alembic head, found: {heads}")
    return heads[0]


def parse_target_url(raw_url: str) -> URL:
    try:
        target = make_url(raw_url)
    except Exception as exc:
        raise BootstrapError("invalid target database URL") from exc
    if not target.drivername.startswith("postgresql"):
        raise BootstrapError("baseline bootstrap supports PostgreSQL only")
    if not target.database or not target.host or not target.username:
        raise BootstrapError("target URL must include username, host, and database")
    return target


def sanitized_target(target: URL) -> str:
    port = f":{target.port}" if target.port else ""
    return f"postgresql://{target.username}:***@{target.host}{port}/{target.database}"


def connection_kwargs(target: URL) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "user": target.username,
        "password": target.password,
        "host": target.host,
        "port": target.port or 5432,
        "database": target.database,
    }
    ssl_mode = target.query.get("sslmode")
    if ssl_mode:
        kwargs["ssl"] = "require" if ssl_mode in {"require", "verify-ca", "verify-full"} else None
    return kwargs


async def discover_user_objects(connection: asyncpg.Connection) -> list[str]:
    rows = await connection.fetch(
        """
        WITH user_objects AS (
            SELECT 'relation' AS kind, n.nspname AS schema_name, c.relname AS object_name
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname !~ '^pg_'
              AND n.nspname <> 'information_schema'

            UNION ALL

            SELECT 'type', n.nspname, t.typname
            FROM pg_catalog.pg_type t
            JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
            WHERE n.nspname !~ '^pg_'
              AND n.nspname <> 'information_schema'
              AND t.typtype IN ('d', 'e', 'r')

            UNION ALL

            SELECT 'function', n.nspname, p.proname
            FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname !~ '^pg_'
              AND n.nspname <> 'information_schema'

            UNION ALL

            SELECT 'schema', n.nspname, n.nspname
            FROM pg_catalog.pg_namespace n
            WHERE n.nspname !~ '^pg_'
              AND n.nspname NOT IN ('information_schema', 'public')

            UNION ALL

            SELECT 'extension', n.nspname, e.extname
            FROM pg_catalog.pg_extension e
            JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace
            WHERE e.extname <> 'plpgsql'
        )
        SELECT kind, schema_name, object_name
        FROM user_objects
        ORDER BY kind, schema_name, object_name
        LIMIT 50
        """
    )
    return [f"{row['kind']}:{row['schema_name']}.{row['object_name']}" for row in rows]


async def require_genuinely_empty(connection: asyncpg.Connection) -> None:
    objects = await discover_user_objects(connection)
    if objects:
        preview = ", ".join(objects[:10])
        suffix = " ..." if len(objects) > 10 else ""
        raise BootstrapError(
            f"target is not genuinely empty; found user objects: {preview}{suffix}. "
            "No objects were changed."
        )


async def require_validated_postgresql(
    connection: asyncpg.Connection,
    manifest: Mapping[str, Any],
) -> str:
    version = await connection.fetchval("SHOW server_version")
    major = int(await connection.fetchval("SHOW server_version_num")) // 10000
    validated = {int(value) for value in manifest["validated_postgresql_majors"]}
    if major not in validated:
        raise BootstrapError(
            f"PostgreSQL major {major} is not validated for this immutable baseline; "
            f"validated majors: {sorted(validated)}"
        )
    return str(version)


async def current_revision(connection: asyncpg.Connection) -> str | None:
    exists = await connection.fetchval("SELECT to_regclass('public.alembic_version') IS NOT NULL")
    if not exists:
        return None
    return await connection.fetchval("SELECT version_num FROM public.alembic_version LIMIT 1")


async def _names(connection: asyncpg.Connection, query: str) -> set[str]:
    return {str(row[0]) for row in await connection.fetch(query)}


async def validate_schema(
    connection: asyncpg.Connection,
    manifest: Mapping[str, Any],
    *,
    expected_revision: str | None,
) -> None:
    tables = await _names(
        connection,
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """,
    )
    expected_tables = set(manifest["tables"])
    if tables != expected_tables:
        raise BootstrapError(
            f"baseline table inventory mismatch; missing={sorted(expected_tables - tables)}, "
            f"unexpected={sorted(tables - expected_tables)}"
        )

    views = await _names(
        connection,
        "SELECT table_name FROM information_schema.views WHERE table_schema = 'public'",
    )
    expected_views = set(manifest["views"])
    if views != expected_views:
        raise BootstrapError(
            f"baseline view inventory mismatch; missing={sorted(expected_views - views)}, "
            f"unexpected={sorted(views - expected_views)}"
        )

    enum_rows = await connection.fetch(
        """
        SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder) AS labels
        FROM pg_catalog.pg_type t
        JOIN pg_catalog.pg_enum e ON e.enumtypid = t.oid
        JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = 'public'
        GROUP BY t.typname
        """
    )
    enums = {str(row["typname"]): list(row["labels"]) for row in enum_rows}
    if enums != manifest["enum_types"]:
        raise BootstrapError("baseline enum inventory or label ordering mismatch")

    constraints = await _names(
        connection,
        """
        SELECT c.conname
        FROM pg_catalog.pg_constraint c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.connamespace
        WHERE n.nspname = 'public'
        """,
    )
    missing_constraints = set(manifest["important_constraints"]) - constraints
    if missing_constraints:
        raise BootstrapError(
            f"baseline is missing important constraints: {sorted(missing_constraints)}"
        )

    indexes = await _names(
        connection,
        "SELECT indexname FROM pg_catalog.pg_indexes WHERE schemaname = 'public'",
    )
    missing_indexes = set(manifest["important_indexes"]) - indexes
    if missing_indexes:
        raise BootstrapError(f"baseline is missing important indexes: {sorted(missing_indexes)}")

    width = await connection.fetchval(
        """
        SELECT character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'alembic_version'
          AND column_name = 'version_num'
        """
    )
    if width != 128:
        raise BootstrapError(f"alembic_version.version_num must be VARCHAR(128), found {width}")

    revision = await current_revision(connection)
    if revision != expected_revision:
        raise BootstrapError(
            f"unexpected Alembic revision: expected {expected_revision!r}, found {revision!r}"
        )


async def assert_zero_business_rows(
    connection: asyncpg.Connection,
    tables: Sequence[str],
) -> None:
    for table in tables:
        if table == "alembic_version":
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_]*", table):
            raise BootstrapError(f"unsafe table name in manifest: {table!r}")
        count = await connection.fetchval(f'SELECT count(*) FROM public."{table}"')
        if count:
            raise BootstrapError(f"baseline unexpectedly created {count} row(s) in {table}")


async def apply_baseline_transaction(
    connection: asyncpg.Connection,
    sql: str,
    manifest: Mapping[str, Any],
) -> None:
    async with connection.transaction():
        await connection.execute(sql)
        await validate_schema(connection, manifest, expected_revision=None)
        await assert_zero_business_rows(connection, manifest["tables"])


def _alembic_environment(target: URL) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "POSTGRES_SERVER": str(target.host),
            "POSTGRES_PORT": str(target.port or 5432),
            "POSTGRES_USER": str(target.username),
            "POSTGRES_PASSWORD": str(target.password or ""),
            "POSTGRES_DB": str(target.database),
            "AUTO_CREATE_TABLES": "false",
        }
    )
    return environment


def run_alembic(target: URL, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=_alembic_environment(target),
        text=True,
        capture_output=True,
        check=False,
    )


def _diagnostic(result: subprocess.CompletedProcess[str], *, secret: str | None = None) -> str:
    lines = (result.stderr or result.stdout).splitlines()
    safe_lines = [line for line in lines if "POSTGRES_PASSWORD" not in line][-12:]
    diagnostic = "\n".join(safe_lines)
    return diagnostic.replace(secret, "***") if secret else diagnostic


async def bootstrap(args: argparse.Namespace) -> dict[str, Any]:
    if args.confirm != CONFIRMATION:
        raise BootstrapError(f"confirmation must be exactly {CONFIRMATION}")
    raw_url = os.environ.get(args.database_url_env)
    if not raw_url:
        raise BootstrapError(
            f"environment variable {args.database_url_env!r} must contain the explicit target URL"
        )
    target = parse_target_url(raw_url)
    if target.host.casefold() not in LOCAL_HOSTS and not args.allow_remote_target:
        raise BootstrapError(
            "remote database target refused; inspect the target and pass --allow-remote-target "
            "only for an explicitly authorized empty environment"
        )

    manifest = load_manifest()
    sql_path = snapshot_path(manifest)
    digest = verify_snapshot_hash(sql_path, manifest["snapshot_sha256"])
    head = repository_head()
    if head != manifest["expected_next_revision"]:
        raise BootstrapError(
            f"repository head changed from the approved strategy: expected "
            f"{manifest['expected_next_revision']}, found {head}"
        )

    print(f"Target: {sanitized_target(target)}")
    print(f"Baseline SHA-256 verified: {digest}")
    connection = await asyncpg.connect(**connection_kwargs(target), timeout=args.connect_timeout)
    try:
        server_version = await require_validated_postgresql(connection, manifest)
        await require_genuinely_empty(connection)
        print(f"Empty-database guard passed on PostgreSQL {server_version}.")
        await apply_baseline_transaction(
            connection,
            sql_path.read_text(encoding="utf-8"),
            manifest,
        )
    except Exception:
        # The transaction context rolls back every baseline statement. Stamp is
        # intentionally unreachable until this block completes successfully.
        raise
    finally:
        await connection.close()

    stamp = await asyncio.to_thread(
        run_alembic,
        target,
        "stamp",
        manifest["baseline_revision"],
    )
    if stamp.returncode:
        raise BootstrapError(
            "baseline schema succeeded but Alembic stamp failed; database is unversioned and "
            f"requires operator review:\n{_diagnostic(stamp, secret=target.password)}"
        )

    connection = await asyncpg.connect(**connection_kwargs(target), timeout=args.connect_timeout)
    try:
        await validate_schema(
            connection,
            manifest,
            expected_revision=manifest["baseline_revision"],
        )
    finally:
        await connection.close()

    upgrade = await asyncio.to_thread(run_alembic, target, "upgrade", "head")
    if upgrade.returncode:
        connection = await asyncpg.connect(**connection_kwargs(target), timeout=args.connect_timeout)
        try:
            revision = await current_revision(connection)
        finally:
            await connection.close()
        raise BootstrapError(
            "baseline was stamped successfully but forward upgrade failed; no historical "
            f"rollback was attempted. Current revision: {revision!r}.\n"
            f"{_diagnostic(upgrade, secret=target.password)}"
        )

    connection = await asyncpg.connect(**connection_kwargs(target), timeout=args.connect_timeout)
    try:
        await validate_schema(
            connection,
            manifest,
            expected_revision=manifest["expected_next_revision"],
        )
        await assert_zero_business_rows(connection, manifest["tables"])
    finally:
        await connection.close()

    return {
        "status": "completed",
        "baseline_revision": manifest["baseline_revision"],
        "final_revision": manifest["expected_next_revision"],
        "snapshot_sha256": digest,
        "downgrade_floor": manifest["downgrade_floor"],
        "target": sanitized_target(target),
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Bootstrap an explicitly selected, genuinely empty PostgreSQL database.",
    )
    value.add_argument(
        "--database-url-env",
        default=DEFAULT_URL_ENV,
        help=f"environment variable holding the URL (default: {DEFAULT_URL_ENV})",
    )
    value.add_argument(
        "--confirm",
        required=True,
        help=f"required exact acknowledgement: {CONFIRMATION}",
    )
    value.add_argument(
        "--allow-remote-target",
        action="store_true",
        help="allow a non-loopback host after separate authorization and target inspection",
    )
    value.add_argument("--connect-timeout", type=float, default=10.0)
    return value


def main() -> int:
    try:
        result = asyncio.run(bootstrap(parser().parse_args()))
    except (BootstrapError, asyncpg.PostgresError, OSError) as exc:
        print(f"BOOTSTRAP REFUSED/FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
