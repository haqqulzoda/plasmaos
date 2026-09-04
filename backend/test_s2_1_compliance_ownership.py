"""Sprint 2.1 explicit compliance ownership security contracts."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, ForeignKeyConstraint

from app.models.all_models import Base
from app.models.audit import (
    ANALYSIS_OWNERSHIP_OWNED,
    ANALYSIS_OWNERSHIP_QUARANTINED_LEGACY,
)


BACKEND_DIR = Path(__file__).resolve().parent


def source(path: str) -> str:
    return (BACKEND_DIR / path).read_text(encoding="utf-8")


def function_block(text: str, name: str) -> str:
    start = text.index(f"async def {name}")
    end = text.find("\n\n@", start + 1)
    return text[start:] if end == -1 else text[start:end]


def test_orm_declares_canonical_ownership_tuple() -> None:
    table = Base.metadata.tables["tender_analyses"]
    assert table.c.user_id.nullable
    assert table.c.company_profile_id.nullable
    assert not table.c.ownership_state.nullable
    assert table.c.ownership_state.server_default.arg.text == "'QUARANTINED_LEGACY'"
    assert ANALYSIS_OWNERSHIP_OWNED == "OWNED"
    assert ANALYSIS_OWNERSHIP_QUARANTINED_LEGACY == "QUARANTINED_LEGACY"

    foreign_keys = {
        tuple(element.parent.name for element in constraint.elements): constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert foreign_keys[("user_id",)].elements[0].target_fullname == "users.id"
    assert foreign_keys[("company_profile_id",)].elements[0].target_fullname == (
        "company_profiles.id"
    )
    assert foreign_keys[("user_id",)].ondelete == "RESTRICT"
    assert foreign_keys[("company_profile_id",)].ondelete == "RESTRICT"

    ownership_check = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_tender_analyses_ownership_tuple"
    )
    check_sql = str(ownership_check.sqltext)
    assert "ownership_state = 'OWNED'" in check_sql
    assert "user_id IS NOT NULL" in check_sql
    assert "company_profile_id IS NOT NULL" in check_sql
    assert "ownership_state = 'QUARANTINED_LEGACY'" in check_sql
    assert "user_id IS NULL" in check_sql
    assert {index.name for index in table.indexes} >= {
        "ix_tender_analyses_user_id",
        "ix_tender_analyses_company_profile_id",
    }


def test_migration_is_single_additive_head_and_never_guesses_names() -> None:
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["20260902_0001_s7_2_user_ui_locale"]
    migration = source(
        "alembic/versions/20260827_0001_s2_1_compliance_ownership.py"
    )
    assert "20260826_0002_s1_2_wb_project_enrichment" in migration
    assert "ENCODED_OWNER_PATTERN" in migration
    assert "profile.user_id = app_user.id" in migration
    assert "ownership_state = 'QUARANTINED_LEGACY'" in migration
    assert "BTRIM(profile.company_name)" not in migration
    assert "DELETE FROM tender_analyses" not in migration.upper()
    assert "http" not in migration.casefold()


def test_new_write_has_explicit_authenticated_owner_and_display_snapshot() -> None:
    tenders = source("app/api/endpoints/tenders.py")
    analyze = function_block(tenders, "analyze_tender")
    creation = analyze.split("candidate_parent = TenderAnalysis(", 1)[1]
    assert "user_id=current_user.id" in creation
    assert "company_profile_id=profile.id" in creation
    assert "ownership_state=ANALYSIS_OWNERSHIP_OWNED" in creation
    assert "company_name=display_company_name" in creation
    assert "company_name=analysis_owner" not in creation
    assert "resolve_or_create_analysis_aggregate" in analyze
    assert "get_profile_for_compliance_match" in analyze
    assert "user_id=current_user.id" in analyze


def test_customer_analysis_paths_use_only_explicit_owner_identity() -> None:
    tenders = source("app/api/endpoints/tenders.py")
    aggregates = source("app/services/analysis_aggregates.py")
    for name in ("_get_owned_analysis",):
        block = function_block(tenders, name)
        assert "TenderAnalysis.user_id" in block, name
        assert "TenderAnalysis.company_profile_id" in block, name
        assert "TenderAnalysis.ownership_state" in block, name
        assert "TenderAnalysis.company_name" not in block, name
    for name in (
        "get_owned_analysis_parent_for_tender",
        "get_owned_analysis_parent_by_id",
    ):
        block = function_block(aggregates, name)
        assert "TenderAnalysis.user_id" in block, name
        assert "TenderAnalysis.company_profile_id" in block, name
        assert "TenderAnalysis.ownership_state" in block, name
        assert "TenderAnalysis.company_name" not in block, name
    for name in ("analyze_tender", "get_latest_analysis", "export_compliance_pdf"):
        block = function_block(tenders, name)
        assert "get_owned_analysis_parent_" in block, name

    audit = function_block(source("app/api/routers/audit.py"), "authorize_risk")
    proposal = function_block(source("app/api/endpoints/proposals.py"), "ai_draft_proposal")
    assert "TenderAnalysis.user_id" in audit
    assert "TenderAnalysis.company_profile_id" in audit
    assert "TenderAnalysis.ownership_state" in audit
    assert "get_owned_analysis_parent_for_tender" in proposal
    assert "TenderAnalysis.company_name" not in audit + proposal


def test_override_direct_id_and_export_share_owned_analysis_gate() -> None:
    tenders = source("app/api/endpoints/tenders.py")
    for name in ("override_risk", "get_risk_overrides"):
        block = function_block(tenders, name)
        assert "_get_owned_analysis" in block
    export = function_block(tenders, "export_compliance_pdf")
    assert "get_owned_analysis_parent_by_id" in export


def test_runtime_contains_no_legacy_name_claim_or_name_authorization() -> None:
    runtime = "\n".join(
        source(path)
        for path in (
            "app/api/endpoints/tenders.py",
            "app/api/endpoints/proposals.py",
            "app/api/routers/audit.py",
        )
    )
    assert "_claim_legacy_analysis_owner" not in runtime
    assert "_analysis_owner_candidates" not in runtime
    assert "TenderAnalysis.company_name" not in runtime


def test_customer_analysis_schema_does_not_expose_owner_ids_or_state() -> None:
    tenders = source("app/api/endpoints/tenders.py")
    response_schema = tenders.split("class AnalyzeTenderResponse", 1)[1].split(
        "class RiskOverrideRequest", 1
    )[0]
    assert "user_id" not in response_schema
    assert "company_profile_id" not in response_schema
    assert "ownership_state" not in response_schema


def test_preflight_reports_canonical_health_read_only() -> None:
    preflight = source("scripts/run_s0_3_schema_data_preflight.py")
    assert 'data["canonical_ownership"]' in preflight
    for field in (
        "owned",
        "quarantined",
        "invalid_fk",
        "user_profile_mismatch",
        "invalid_ownership_tuple",
        "quarantined_encoded_remnants",
    ):
        assert field in preflight
    assert "0::bigint AS safe_legacy_rows" in preflight
    assert "connection.transaction(readonly=True)" in preflight
    assert "await transaction.rollback()" in preflight
