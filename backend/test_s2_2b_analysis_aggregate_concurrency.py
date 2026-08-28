"""Fast contracts for Sprint 2.2B aggregate concurrency hardening."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.services.analysis_aggregates import analysis_aggregate_identity


BACKEND_DIR = Path(__file__).resolve().parent
SERVICE = BACKEND_DIR / "app/services/analysis_aggregates.py"
ENDPOINT = BACKEND_DIR / "app/api/endpoints/tenders.py"
PROPOSALS = BACKEND_DIR / "app/api/endpoints/proposals.py"
PREFLIGHT = BACKEND_DIR / "scripts/report_analysis_aggregate_concurrency.py"
HEAD = "20260828_0002_s3_4_admin_audit_hardening"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_identity_uses_only_canonical_tenant_and_tender_ids() -> None:
    user_id = uuid4()
    profile_id = uuid4()
    tender_id = uuid4()
    identity = analysis_aggregate_identity(
        user_id=user_id,
        company_profile_id=profile_id,
        tender_id=tender_id,
    )
    assert str(user_id) in identity
    assert str(profile_id) in identity
    assert str(tender_id) in identity
    assert "company_name" not in identity


def test_resolution_is_database_backed_and_transaction_scoped() -> None:
    service = source(SERVICE)
    assert "pg_advisory_xact_lock" in service
    assert "hashtextextended" in service
    assert "TenderAnalysis.user_id == user_id" in service
    assert "TenderAnalysis.company_profile_id == company_profile_id" in service
    assert "TenderAnalysis.tender_id == tender_id" in service
    assert "CompanyProfile.user_id == user_id" in service
    assert ".with_for_update()" in service
    assert "TenderAnalysis.company_name" not in service
    assert "input_hash" not in service
    assert "output_hash" not in service
    assert "version_hash" not in service


def test_historical_duplicate_runtime_rule_is_explicit_and_non_mutating() -> None:
    service = source(SERVICE)
    assert "TenderAnalysis.created_at.desc()" in service
    assert "TenderAnalysis.id.desc()" in service
    assert "analysis_aggregate_historical_ambiguity" in service
    assert "runtime_rule=newest_existing" in service
    assert "delete(" not in service.casefold()
    assert ".values(" not in service


def test_endpoint_resolves_before_version_append_and_rechecks_cache() -> None:
    endpoint = source(ENDPOINT)
    resolve_at = endpoint.index(
        "aggregate = await resolve_or_create_analysis_aggregate("
    )
    append_at = endpoint.index("await append_analysis_version(", resolve_at)
    commit_at = endpoint.index("await session.commit()", append_at)
    assert resolve_at < append_at < commit_at
    concurrent_cache = endpoint[resolve_at:append_at]
    assert "not aggregate.created" in concurrent_cache
    assert "not force" in concurrent_cache
    assert "concurrent_version.input_hash == current_content_hash" in concurrent_cache
    assert "await session.rollback()" in concurrent_cache


def test_proposal_path_only_reads_canonical_compliance_version() -> None:
    proposals = source(PROPOSALS)
    assert "get_owned_analysis_parent_for_tender" in proposals
    assert "require_latest_analysis_version" in proposals
    assert "latest_analysis_version.result_snapshot" in proposals
    assert "TenderAnalysis(" not in proposals
    assert "resolve_or_create_analysis_aggregate" not in proposals


def test_read_only_preflight_reports_aggregate_counts_without_content() -> None:
    preflight = source(PREFLIGHT)
    for marker in (
        "total_tender_analyses",
        "distinct_logical_aggregate_keys",
        "keys_with_one_parent",
        "keys_with_multiple_parents",
        "max_parents_per_key",
        "owned_multi_parent_keys",
        "quarantined_multi_parent_keys",
        "invalid_canonical_keys",
    ):
        assert marker in preflight
    assert "analysis_json" not in preflight
    assert "result_snapshot" not in preflight
    assert "await db.rollback()" in preflight


def test_no_migration_and_s2_2_head_remains_single() -> None:
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [HEAD]
    assert not any(
        "s2_2b" in path.name.casefold()
        for path in (BACKEND_DIR / "alembic" / "versions").glob("*.py")
    )
