"""Deterministic contracts for Sprint 1.1 canonical Project foundation."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.all_models import Base
from app.schemas.tender import TenderResponse
from app.services.projects import (
    ProjectIdClassification,
    normalize_project_identifier,
)
from app.services.tender_sources.world_bank import WorldBankTenderSource


BACKEND_DIR = Path(__file__).resolve().parent
MIGRATION_PATH = (
    BACKEND_DIR
    / "alembic/versions/20260826_0001_s1_1_project_foundation.py"
)
HEAD = "20260827_0002_s2_2_analysis_version_foundation"


def _load_migration():
    spec = importlib.util.spec_from_file_location("s1_1_migration", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _unique_columns(table_name: str) -> dict[str | None, tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_project_identity_is_source_scoped_and_not_globally_unique() -> None:
    table = Base.metadata.tables["projects"]
    assert _unique_columns("projects") == {
        "uq_projects_source_external_project_id": (
            "source_system",
            "external_project_id",
        )
    }
    assert not table.c.external_project_id.unique


def test_tender_project_cardinality_indexes_and_delete_behavior() -> None:
    table = Base.metadata.tables["tender_projects"]
    assert _unique_columns("tender_projects") == {
        "uq_tender_projects_tender_id": ("tender_id",)
    }
    assert {index.name for index in table.indexes} == {
        "ix_tender_projects_project_id"
    }
    foreign_keys = {foreign_key.parent.name: foreign_key for foreign_key in table.foreign_keys}
    assert foreign_keys["tender_id"].target_fullname == "tenders.id"
    assert foreign_keys["project_id"].target_fullname == "projects.id"
    assert foreign_keys["tender_id"].ondelete == "CASCADE"
    assert foreign_keys["project_id"].ondelete == "CASCADE"
    # Link deletion is isolated: neither FK can cascade into a Tender row.


def test_only_deterministic_linkage_methods_are_allowed() -> None:
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in Base.metadata.tables["tender_projects"].constraints
        if isinstance(constraint, CheckConstraint)
    }
    method_check = checks["ck_tender_projects_linkage_method_allowed"]
    assert "SOURCE_PROJECT_ID" in method_check
    assert "SOURCE_NATIVE_LINK" in method_check
    for forbidden in ("FUZZY", "TITLE_MATCH", "LLM_MATCH", "INFERRED_EMAIL"):
        assert forbidden not in method_check


def test_world_bank_identifier_normalization_and_quarantine() -> None:
    unchanged = normalize_project_identifier("world_bank", "P179267")
    trimmed = normalize_project_identifier("world_bank", "  P179267\t")
    empty = normalize_project_identifier("world_bank", "   ")
    malformed = normalize_project_identifier("world_bank", "P17\n9267")
    suspicious = normalize_project_identifier("world_bank", "179267")

    assert unchanged.classification is ProjectIdClassification.VALID
    assert unchanged.raw_value == unchanged.normalized_value == "P179267"
    assert trimmed.classification is ProjectIdClassification.VALID
    assert trimmed.raw_value == "  P179267\t"
    assert trimmed.normalized_value == "P179267"
    assert empty.classification is ProjectIdClassification.EMPTY
    assert malformed.classification is ProjectIdClassification.MALFORMED
    assert suspicious.classification is ProjectIdClassification.SUSPICIOUS


def test_same_identifier_shape_is_valid_in_separate_source_namespaces() -> None:
    world_bank = normalize_project_identifier("world_bank", "P123456")
    adb = normalize_project_identifier("adb", "P123456")
    assert world_bank.is_valid and adb.is_valid
    assert ("world_bank", world_bank.normalized_value) != (
        "adb",
        adb.normalized_value,
    )


def test_world_bank_connector_maintains_project_linkage_on_every_upsert() -> None:
    normalized = SimpleNamespace(
        project_id="P179267",
        source_metadata_json={"project_id": " P179267 "},
        source_url="https://projects.worldbank.org/procurement/notice/OP1",
        country="Liberia",
    )
    tender = SimpleNamespace(last_synced_at=None)
    upsert_tender = AsyncMock(return_value=(tender, True))
    link_project = AsyncMock()
    with (
        patch("app.services.tender_sources.base.upsert_tender", upsert_tender),
        patch("app.services.projects.link_tender_to_project", link_project),
    ):
        result = asyncio.run(WorldBankTenderSource().upsert(SimpleNamespace(), normalized))
        asyncio.run(WorldBankTenderSource().upsert(SimpleNamespace(), normalized))

    assert result == (tender, True)
    assert upsert_tender.await_count == 2
    assert link_project.await_count == 2
    assert link_project.await_args.kwargs["external_project_id"] == " P179267 "
    assert link_project.await_args.kwargs["authoritative_metadata"] == {
        "country": "Liberia"
    }


def test_existing_tender_api_contract_keeps_source_project_id() -> None:
    assert "project_id" in TenderResponse.model_fields
    assert "canonical_project" not in TenderResponse.model_fields


def test_migration_is_the_single_head_after_sprint_zero_b3() -> None:
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [HEAD]
    assert script.get_revision(HEAD).down_revision == (
        "20260827_0001_s2_1_compliance_ownership"
    )
    assert script.get_revision(
        "20260827_0001_s2_1_compliance_ownership"
    ).down_revision == "20260826_0002_s1_2_wb_project_enrichment"
    assert script.get_revision("20260826_0002_s1_2_wb_project_enrichment").down_revision == (
        "20260826_0001_s1_1_project_foundation"
    )
    assert script.get_revision("20260826_0001_s1_1_project_foundation").down_revision == (
        "20260825_0001_s0_5b3"
    )


def test_migration_backfill_is_world_bank_only_and_strict() -> None:
    migration = _load_migration()
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert migration.VALID_WORLD_BANK_PROJECT_ID_SQL == (
        r"BTRIM(project_id) ~ '^P[0-9]{6}$'"
    )
    assert "WHERE t.source_system = 'world_bank'" in source
    assert "source_system = 'adb'" not in source
    assert "ON CONFLICT (source_system, external_project_id) DO NOTHING" in source
    assert "ON CONFLICT (tender_id) DO NOTHING" in source
    assert "DROP COLUMN" not in source.upper()
