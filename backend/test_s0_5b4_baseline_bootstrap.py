from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


BACKEND_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = BACKEND_DIR / "scripts" / "bootstrap_database.py"
BASELINE_DIR = BACKEND_DIR / "db" / "baselines"
MANIFEST_PATH = BASELINE_DIR / "20260824_0002_s0_4c.manifest.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("s0_5b4_bootstrap", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_and_snapshot_hash_are_consistent() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    snapshot = BASELINE_DIR / manifest["snapshot_file"]
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == manifest["snapshot_sha256"]
    assert manifest["baseline_revision"] == "20260824_0002_s0_4c"
    assert manifest["expected_next_revision"] == "20260825_0001_s0_5b3"
    assert manifest["downgrade_floor"] == manifest["baseline_revision"]
    assert manifest["validated_postgresql_majors"] == [16]


def test_hash_mismatch_is_a_hard_refusal(tmp_path: Path) -> None:
    module = _load_module()
    changed = tmp_path / "changed.sql"
    changed.write_bytes((BASELINE_DIR / "20260824_0002_s0_4c.sql").read_bytes() + b"\n-- changed\n")
    with pytest.raises(module.BootstrapError, match="hash mismatch"):
        module.verify_snapshot_hash(changed, json.loads(MANIFEST_PATH.read_text())["snapshot_sha256"])


def test_snapshot_is_structure_only_and_portable() -> None:
    sql = (BASELINE_DIR / "20260824_0002_s0_4c.sql").read_text(encoding="utf-8")
    upper = sql.upper()
    forbidden = (
        "INSERT INTO",
        "COPY PUBLIC.",
        " OWNER TO ",
        "GRANT ",
        "REVOKE ",
        "POSTGRESQL://",
        "PASSWORD",
        "/MNT/",
        "C:\\\\",
        "\\RESTRICT",
    )
    assert not [token for token in forbidden if token in upper]
    assert upper.count("CREATE TABLE PUBLIC.") == 20
    assert upper.count("CREATE TYPE PUBLIC.") == 5
    assert "CREATE TABLE PUBLIC.ALEMBIC_VERSION" in upper


def test_manifest_inventory_is_complete_and_stable() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert len(manifest["tables"]) == 20
    assert len(manifest["views"]) == 16
    assert len(manifest["enum_types"]) == 5
    assert "tender_recommendations" in manifest["tables"]
    assert "alembic_version_pkc" in manifest["important_constraints"]
    assert "uq_tender_recommendations_tender_profile" in manifest["important_constraints"]
    assert "ix_tender_recommendations_created_at" in manifest["important_indexes"]


def test_bootstrap_has_no_create_all_call_or_orm_import() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(
        isinstance(call.func, ast.Attribute) and call.func.attr == "create_all" for call in calls
    )
    imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    ]
    assert not any(name.startswith("app.models") for name in imports)
    assert "--sql-file" not in source


def test_repository_head_is_the_approved_single_head() -> None:
    module = _load_module()
    assert module.repository_head() == "20260826_0002_s1_2_wb_project_enrichment"


def test_target_display_masks_password() -> None:
    module = _load_module()
    target = module.parse_target_url("postgresql+asyncpg://plasma:very-secret@localhost:6543/new_db")
    display = module.sanitized_target(target)
    assert "very-secret" not in display
    assert display == "postgresql://plasma:***@localhost:6543/new_db"


def test_failure_diagnostic_redacts_password() -> None:
    module = _load_module()
    result = subprocess.CompletedProcess(
        args=["alembic"],
        returncode=1,
        stdout="connection failed for very-secret",
        stderr="",
    )
    diagnostic = module._diagnostic(result, secret="very-secret")
    assert "very-secret" not in diagnostic
    assert "***" in diagnostic


def test_cli_requires_explicit_confirmation() -> None:
    module = _load_module()
    with pytest.raises(SystemExit):
        module.parser().parse_args([])
