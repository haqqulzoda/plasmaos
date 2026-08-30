"""Sprint 6.2 unified Explorer backend contracts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException

from app.api.deps import require_explorer_access
from app.main import app
from app.schemas.explorer import ExplorerView, RecommendationAvailability
from app.services.explorer import (
    ExplorerQuery,
    _all_order,
    _recommendation_order,
    recommendation_summary,
)


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
HEAD = "20260828_0003_s4_1_tender_engagement_foundation"


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_openapi_exposes_unified_read_and_canonical_commands() -> None:
    schema = app.openapi()
    assert "get" in schema["paths"]["/api/v1/explorer/tenders"]
    assert "post" in schema["paths"]["/api/v1/recommendations/{recommendation_id}/dismiss"]
    assert "post" in schema["paths"]["/api/v1/recommendations/{recommendation_id}/restore"]
    view_parameter = next(
        parameter
        for parameter in schema["paths"]["/api/v1/explorer/tenders"]["get"]["parameters"]
        if parameter["name"] == "view"
    )
    enum_schema = schema["components"]["schemas"][view_parameter["schema"]["$ref"].rsplit("/", 1)[1]]
    assert enum_schema["enum"] == ["all", "recommended", "dismissed"]


def test_explicit_view_and_availability_domains_are_truthful() -> None:
    assert [view.value for view in ExplorerView] == ["all", "recommended", "dismissed"]
    assert {value.value for value in RecommendationAvailability} == {
        "AVAILABLE",
        "PROFILE_REQUIRED",
    }


def test_shared_filter_contract_is_used_by_both_endpoints() -> None:
    legacy = source("backend/app/api/endpoints/tenders.py")
    unified = source("backend/app/services/explorer.py")
    legacy_route = legacy.split("async def list_tenders", 1)[1].split(
        '@router.get("/{tender_id}/details"', 1
    )[0]
    assert "apply_explorer_tender_filters(" in legacy_route
    assert "apply_explorer_tender_filters(" in unified
    assert legacy_route.count("serialized_tenders = [") == 1
    assert "if tender.document_status" not in legacy_route


def test_document_membership_is_resolved_before_count_and_page() -> None:
    service = source("backend/app/services/explorer.py")
    start = service.index("async def list_explorer_tenders")
    block = service[start:]
    resolve_at = block.index("resolve_filesystem_document_filter_tender_ids(")
    count_at = block.index("_filtered_counts(")
    page_at = block.index("_page_rows(")
    assert resolve_at < count_at < page_at
    tender_api = source("backend/app/api/endpoints/tenders.py")
    assert "Tender.id.in_(document_tender_ids)" in tender_api
    assert "_document_status_predicate(normalized_document_status)" in tender_api


def test_recommendation_and_tender_orders_have_unique_tie_breakers() -> None:
    recommendation_sql = str(_recommendation_order(__import__("sqlalchemy").select(1), None))
    assert "match_score DESC" in recommendation_sql
    assert "created_at DESC" in recommendation_sql
    assert "tender_recommendations.id ASC" in recommendation_sql
    all_sql = str(_all_order(__import__("sqlalchemy").select(1), "newest"))
    assert "tenders.id ASC" in all_sql
    with pytest.raises(HTTPException) as exc_info:
        _all_order(__import__("sqlalchemy").select(1), "best_match")
    assert exc_info.value.status_code == 400


def test_rationale_summary_is_unicode_bounded_without_mutating_source() -> None:
    rationale = "界" * 281
    recommendation = SimpleNamespace(
        id=uuid4(),
        match_score=87,
        strategic_rationale=rationale,
        is_dismissed=False,
        created_at=datetime.now(timezone.utc),
    )
    result = recommendation_summary(recommendation)
    assert result is not None
    assert len(result.rationale_summary) == 280
    assert recommendation.strategic_rationale == rationale


def test_response_schema_is_explicit_and_has_no_private_owner_or_llm_fields() -> None:
    schema = source("backend/app/schemas/explorer.py")
    for required in (
        "all_tenders",
        "active_recommendations",
        "dismissed_recommendations",
        "recommendation_availability",
        "rationale_summary",
        "allowed_actions",
    ):
        assert required in schema
    for forbidden in (
        "company_profile_id",
        "user_id",
        "prompt_content",
        "model_credentials",
        "is_stale",
        "win_probability",
        "eligibility_score",
    ):
        assert forbidden not in schema


def test_unified_get_dependency_graph_is_passive() -> None:
    endpoint = source("backend/app/api/endpoints/explorer.py").split(
        "async def get_explorer_tenders", 1
    )[1].split("async def _recommendation_command", 1)[0]
    service = source("backend/app/services/explorer.py")
    for writer in (
        "db.add(",
        "db.delete(",
        "db.flush(",
        "db.commit(",
        ".delay(",
        "Gemini",
        "evaluate_tenders_batch",
    ):
        assert writer not in endpoint
        assert writer not in service


def test_canonical_mutations_lock_owned_row_and_change_only_boolean() -> None:
    service = source("backend/app/services/recommendations.py")
    assert ".with_for_update()" in service
    assert "CompanyProfile.user_id == user_id" in service
    assert "TenderRecommendation.id == recommendation_id" in service
    assert "recommendation.is_dismissed = dismissed" in service
    for forbidden in (
        "TenderEngagement",
        "Proposal",
        "TenderAnalysis",
        "AnalysisVersion",
        "match_score =",
        "strategic_rationale =",
        "created_at =",
        "db.add(",
        "db.delete(",
    ):
        assert forbidden not in service


def test_legacy_hunter_dismiss_delegates_to_canonical_service() -> None:
    hunter = source("backend/app/api/endpoints/hunter.py")
    dismiss_block = hunter.split("async def dismiss_recommendation", 1)[1]
    assert "dismiss_owned_recommendation(" in dismiss_block
    assert "rec.is_dismissed" not in dismiss_block
    assert '@router.get(""' in hunter


def test_queries_use_uuid_authority_and_independent_pursuit_overlay() -> None:
    service = source("backend/app/services/explorer.py")
    for authority in (
        "CompanyProfile.user_id == user_id",
        "TenderRecommendation.company_profile_id == profile_id",
        "TenderEngagement.user_id == user_id",
        "TenderEngagement.company_profile_id == profile_id",
        "TenderEngagement.tender_id == Tender.id",
        "customer_visible_tender_condition(Tender)",
    ):
        assert authority in service
    for forbidden in ("company_name ==", "email ==", "strategic_rationale.ilike"):
        assert forbidden not in service


def test_sprint_6_4_frontend_consumes_contract_with_passive_compatibility_redirect() -> None:
    explorer_page = source("frontend/app/dashboard/tenders/page.tsx")
    hunter_page = source("frontend/app/dashboard/hunter/page.tsx")
    navigation = source("frontend/app/dashboard/layout.tsx")
    assert "listExplorer({" in explorer_page
    assert "'recommended', 'Recommended'" in explorer_page
    assert "permanentRedirect" not in hunter_page
    assert "redirect('/dashboard/tenders?view=recommended')" in hunter_page
    assert "href: '/dashboard/hunter'" not in navigation
    assert "href: '/dashboard/tenders'" in navigation


def test_no_migration_or_backfill_and_head_is_unchanged() -> None:
    config = Config()
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [HEAD]
    explorer = source("backend/app/services/explorer.py")
    assert "TenderRecommendation(" not in explorer
    assert "insert(" not in explorer.casefold()


def test_query_contract_is_bounded() -> None:
    endpoint = source("backend/app/api/endpoints/explorer.py")
    assert "limit: int = Query(default=25, ge=1, le=100)" in endpoint
    assert "offset: int = Query(default=0, ge=0)" in endpoint
    assert ExplorerQuery().limit == 25
    assert ExplorerQuery().offset == 0


def test_explorer_access_allows_approved_no_profile_but_not_pending_states() -> None:
    class FakeDB:
        def __init__(self, profile_approval):
            self.profile_approval = profile_approval

        async def scalar(self, _statement):
            return self.profile_approval

    def user(approval_status: str):
        return SimpleNamespace(
            id=uuid4(),
            email="explorer@s62.invalid",
            approval_status=approval_status,
            platform_role="pilot_user",
            is_admin=False,
        )

    approved = user("approved")
    assert asyncio.run(require_explorer_access(approved, FakeDB(None))) is approved
    for account_state, profile_state in (
        ("pending", None),
        ("rejected", None),
        ("disabled", None),
        ("approved", "pending"),
        ("approved", "rejected"),
        ("approved", "disabled"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                require_explorer_access(
                    user(account_state),
                    FakeDB(profile_state),
                )
            )
        assert exc_info.value.status_code == 403
