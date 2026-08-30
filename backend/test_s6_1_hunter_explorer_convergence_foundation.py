from __future__ import annotations

from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.all_models import Base


ROOT = Path(__file__).resolve().parents[1]


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_recommendation_schema_has_canonical_profile_tender_identity() -> None:
    table = Base.metadata.tables["tender_recommendations"]
    assert {column.name for column in table.columns} == {
        "id",
        "tender_id",
        "company_profile_id",
        "match_score",
        "strategic_rationale",
        "is_dismissed",
        "created_at",
    }
    assert "user_id" not in table.columns
    assert "updated_at" not in table.columns
    assert any(
        isinstance(constraint, UniqueConstraint)
        and tuple(column.name for column in constraint.columns)
        == ("tender_id", "company_profile_id")
        for constraint in table.constraints
    )
    assert any(
        isinstance(constraint, CheckConstraint)
        and "match_score >= 0" in str(constraint.sqltext)
        and "match_score <= 100" in str(constraint.sqltext)
        for constraint in table.constraints
    )


def test_hunter_list_is_owned_ranked_and_passive() -> None:
    hunter = source("backend/app/api/endpoints/hunter.py")
    list_route = hunter.split("async def list_recommendations", 1)[1].split(
        "async def dismiss_recommendation", 1
    )[0]
    assert "CompanyProfile.user_id == current_user.id" in list_route
    assert "TenderRecommendation.company_profile_id == profile_id" in list_route
    assert "TenderRecommendation.is_dismissed == False" in list_route
    assert "actionable_tender_condition(Tender)" in list_route
    assert ".order_by(TenderRecommendation.match_score.desc())" in list_route
    for writer in ("db.add(", "db.delete(", "db.flush(", ".delay(", "rec.is_dismissed ="):
        assert writer not in list_route


def test_dismissal_mutates_only_the_owned_recommendation() -> None:
    hunter = source("backend/app/api/endpoints/hunter.py")
    service = source("backend/app/services/recommendations.py")
    dismiss_route = hunter.split("async def dismiss_recommendation", 1)[1]
    assert "dismiss_owned_recommendation(" in dismiss_route
    assert "CompanyProfile.user_id == user_id" in service
    assert "TenderRecommendation.id == recommendation_id" in service
    assert "recommendation.is_dismissed = dismissed" in service
    assert "status.HTTP_404_NOT_FOUND" in dismiss_route
    for foreign_authority in (
        "TenderEngagement",
        "Proposal",
        "TenderAnalysis",
        "AnalysisVersion",
        "Tender.status =",
    ):
        assert foreign_authority not in hunter


def test_restore_is_safe_in_schema_and_canonical_service() -> None:
    hunter = source("backend/app/api/endpoints/hunter.py")
    explorer = source("backend/app/api/endpoints/explorer.py")
    service = source("backend/app/services/recommendations.py")
    assert "is_dismissed" in Base.metadata.tables["tender_recommendations"].columns
    assert "/restore" not in hunter
    assert '"/recommendations/{recommendation_id}/restore"' in explorer
    assert "async def restore_recommendation" in service


def test_generation_is_scheduled_background_work_not_a_read_side_effect() -> None:
    celery = source("backend/app/core/celery_app.py")
    worker = source("backend/app/workers/hunter_tasks.py")
    hunter = source("backend/app/api/endpoints/hunter.py")
    assert '"run-hunter-sweep-every-30-minutes"' in celery
    assert 'crontab(minute="*/30")' in celery
    assert "datetime.now(timezone.utc) - timedelta(hours=24)" in worker
    assert "actionable_tender_condition(Tender)" in worker
    assert "~exists(recommendation_exists)" in worker
    assert "TenderRecommendation(" in worker
    assert "MIN_MATCH_SCORE = 10" in worker
    assert "process_tender_docs.delay" in worker
    assert "run_hunter_sweep" not in hunter


def test_score_and_rationale_are_stored_llm_advisory_snapshots() -> None:
    agent = source("backend/app/core/agents/hunter.py")
    model = source("backend/app/models/audit.py").split("class TenderRecommendation", 1)[1]
    assert 'MODEL_NAME = "gemini-2.5-flash-lite"' in agent
    assert "score strategic fit from 0-100" in agent
    assert "temperature=0.1" in agent
    assert "strategic_rationale must be concise and specific" in agent
    assert "match_score: Mapped[int]" in model
    assert "strategic_rationale: Mapped[str]" in model
    assert "model_version" not in model
    assert "profile_hash" not in model


def test_explorer_and_hunter_current_routes_are_distinct_and_tender_canonical() -> None:
    explorer_page = source("frontend/app/dashboard/tenders/page.tsx")
    explorer_client = source("frontend/lib/explorer.ts")
    hunter_page = source("frontend/app/dashboard/hunter/page.tsx")
    tender_api = source("backend/app/api/endpoints/tenders.py")
    assert "listExplorer({" in explorer_page
    assert "api.get<ExplorerResponse>('/explorer/tenders'" in explorer_client
    assert "api.get<Tender[]>('/tenders'" not in explorer_page
    assert "TenderRecommendation" not in tender_api
    assert "redirect('/dashboard/tenders?view=recommended')" in hunter_page
    assert "api.get" not in hunter_page
    assert "HunterRecommendation" not in hunter_page


def test_recommendation_authority_is_independent_across_domain_matrix() -> None:
    fixtures = (
        # Tender-only; active/dismissed recommendations; every pursuit state;
        # closed/cancelled source state; same-name tenants; no rationale/profile.
        ("OPEN", None, None, True, False),
        ("OPEN", "ACTIVE", None, True, True),
        ("OPEN", "DISMISSED", None, True, False),
        ("OPEN", "ACTIVE", "SAVED", True, True),
        ("OPEN", "ACTIVE", "PREPARING", True, True),
        ("OPEN", "ACTIVE", "WON", True, True),
        ("OPEN", "ACTIVE", "DISMISSED", True, True),
        ("CLOSED", "ACTIVE", None, True, True),
        ("CANCELLED", "ACTIVE", None, True, True),
        ("OPEN", "ACTIVE:TENANT_A", None, True, True),
        ("OPEN", "ACTIVE:NO_RATIONALE", None, True, True),
        ("OPEN", None, "NO_PROFILE", True, False),
    )
    for tender_status, recommendation, pursuit, in_all, has_active_recommendation in fixtures:
        assert in_all is True
        assert has_active_recommendation == (
            recommendation is not None and recommendation.startswith("ACTIVE")
        )
        # Neither source status nor pursuit state changes Recommendation membership.
        if recommendation and recommendation.startswith("ACTIVE"):
            assert tender_status in {"OPEN", "CLOSED", "CANCELLED"}
            assert pursuit in {None, "SAVED", "PREPARING", "WON", "DISMISSED"}


def test_preflight_exposes_count_only_recommendation_foundation_metrics() -> None:
    preflight = source("backend/scripts/run_s0_3_schema_data_preflight.py")
    for metric in (
        "duplicate_tender_profile_groups",
        "invalid_user_or_profile",
        "broken_tender",
        "null_score",
        "score_min",
        "score_max",
        "with_rationale",
        "without_rationale",
        "recommendations_with_engagement",
        "recommendations_without_engagement",
    ):
        assert metric in preflight


def test_s6_4_frontend_converges_with_passive_route_retirement() -> None:
    explorer_page = source("frontend/app/dashboard/tenders/page.tsx")
    hunter_page = source("frontend/app/dashboard/hunter/page.tsx")
    layout = source("frontend/app/dashboard/layout.tsx")
    assert "'recommended', 'Recommended'" in explorer_page
    assert "permanentRedirect" not in hunter_page
    assert "redirect('/dashboard/tenders?view=recommended')" in hunter_page
    assert "href: '/dashboard/hunter'" not in layout
    assert "href: '/dashboard/tenders'" in layout
