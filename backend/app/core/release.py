"""Release identity helpers exposed through safe health endpoints."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents.requirement_extractor import EXTRACTOR_SCHEMA_VERSION

VERSION = "0.2.0"

MODULE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = MODULE_DIR.parent.parent
ALEMBIC_VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"


def _env_value(name: str, default: str = "unknown") -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _literal_assignment(tree: ast.Module, name: str) -> Any:
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                return ast.literal_eval(node.value)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    return None


def alembic_repository_heads() -> list[str]:
    revisions: set[str] = set()
    down_revisions: set[str] = set()

    for version_file in ALEMBIC_VERSIONS_DIR.glob("*.py"):
        tree = ast.parse(version_file.read_text(encoding="utf-8"))
        revision = _literal_assignment(tree, "revision")
        down_revision = _literal_assignment(tree, "down_revision")
        if isinstance(revision, str):
            revisions.add(revision)
        if isinstance(down_revision, str):
            down_revisions.add(down_revision)
        elif isinstance(down_revision, (tuple, list)):
            down_revisions.update(value for value in down_revision if isinstance(value, str))

    return sorted(revisions - down_revisions)


async def get_database_alembic_revision(db: AsyncSession) -> str | None:
    try:
        result = await db.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except Exception:
        return None
    value = result.scalar_one_or_none()
    return str(value) if value else None


def public_release_metadata() -> dict[str, Any]:
    return {
        "status": "ok",
        "project": "Plasma AI",
        "version": VERSION,
        "service": _env_value("PLASMA_SERVICE_NAME", "backend"),
        "build_sha": _env_value("PLASMA_BUILD_SHA"),
        "build_time": _env_value("PLASMA_BUILD_TIME"),
    }


def detailed_release_metadata() -> dict[str, Any]:
    heads = alembic_repository_heads()
    payload = public_release_metadata()
    payload.update(
        {
            "extractor_schema_version": EXTRACTOR_SCHEMA_VERSION,
            "alembic_head": heads[0] if len(heads) == 1 else None,
            "alembic_heads": heads,
        }
    )
    return payload


async def release_metadata_with_database(db: AsyncSession) -> dict[str, Any]:
    payload = detailed_release_metadata()
    payload["alembic_revision"] = await get_database_alembic_revision(db)
    payload["alembic_at_head"] = (
        payload["alembic_revision"] is not None
        and len(payload["alembic_heads"]) == 1
        and payload["alembic_revision"] == payload["alembic_heads"][0]
    )
    return payload
