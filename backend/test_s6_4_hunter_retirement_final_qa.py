"""Static and OpenAPI contracts for Sprint 6.4 Hunter retirement."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]
HEAD = "20260904_0001_s8_2_analysis_language"


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_hunter_customer_route_is_redirect_only() -> None:
    page = source("frontend/app/dashboard/hunter/page.tsx")
    assert "redirect('/dashboard/tenders?view=recommended')" in page
    for forbidden in ("'use client'", "api.", "fetch(", "useEffect", "useState", "HunterRecommendation"):
        assert forbidden not in page


def test_dead_hunter_frontend_type_is_removed() -> None:
    assert not (ROOT / "frontend/types/hunter.ts").exists()


def test_customer_runtime_has_no_hunter_product_surface() -> None:
    layout = source("frontend/app/dashboard/layout.tsx")
    explorer = source("frontend/app/dashboard/tenders/page.tsx")
    assert "Hunter" not in layout
    assert "Hunter" not in explorer
    assert "href: '/dashboard/tenders'" in layout


def test_unified_explorer_remains_only_canonical_frontend_client() -> None:
    client = source("frontend/lib/explorer.ts")
    explorer = source("frontend/app/dashboard/tenders/page.tsx")
    assert "api.get<ExplorerResponse>('/explorer/tenders'" in client
    assert "/hunter" not in explorer
    assert "api.get<Tender[]>('/tenders'" not in explorer


def test_legacy_backend_dismiss_delegates_canonical_service() -> None:
    endpoint = source("backend/app/api/endpoints/hunter.py")
    assert "dismiss_recommendation as dismiss_owned_recommendation" in endpoint
    assert "await dismiss_owned_recommendation(" in endpoint
    assert "Recommendation not found or access denied." in endpoint
    assert "restore" not in endpoint


def test_legacy_list_is_owned_and_read_only() -> None:
    endpoint = source("backend/app/api/endpoints/hunter.py")
    list_block = endpoint.split("async def list_recommendations", 1)[1].split("@router.post", 1)[0]
    assert "CompanyProfile.user_id == current_user.id" in list_block
    assert "TenderRecommendation.company_profile_id == profile_id" in list_block
    for forbidden in ("db.add(", "db.commit(", "evaluate_tenders_batch", "process_tender_docs"):
        assert forbidden not in list_block


def test_generation_worker_contract_is_preserved() -> None:
    worker = source("backend/app/workers/hunter_tasks.py")
    celery = source("backend/app/core/celery_app.py")
    for contract in ("MIN_MATCH_SCORE = 10", "evaluate_tenders_batch", "process_tender_docs.delay", "TenderRecommendation("):
        assert contract in worker
    assert "run-hunter-sweep-every-30-minutes" in celery
    assert '"app.workers.hunter_tasks.*": {"queue": "ai_fast_queue"}' in celery


def test_canonical_and_legacy_openapi_routes_remain_registered() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    assert "get" in paths["/api/v1/explorer/tenders"]
    assert "post" in paths["/api/v1/recommendations/{recommendation_id}/dismiss"]
    assert "post" in paths["/api/v1/recommendations/{recommendation_id}/restore"]
    assert "get" in paths["/api/v1/hunter"]
    assert "post" in paths["/api/v1/hunter/{recommendation_id}/dismiss"]


def test_navigation_and_customer_copy_are_converged() -> None:
    layout = source("frontend/app/dashboard/layout.tsx")
    navigation = source("frontend/messages/en/navigation.json")
    recommendation = source("frontend/components/tenders/RecommendationSummary.tsx")
    explorer_messages = source("frontend/messages/en/explorer.json")
    for key in ("tenders", "myTenders", "bidPreparation"):
        assert f"nameKey: '{key}'" in layout
    for label in ("Tenders", "My Tenders", "Bid Preparation"):
        assert label in navigation
    for key in ("matchScore", "why", "recommendedOn", "dismiss", "restore"):
        assert f't("{key}"' in recommendation
    for copy in ("Match score", "Why this may match", "Recommended on", "Dismiss recommendation", "Restore recommendation"):
        assert copy in explorer_messages
    for forbidden in ("Win probability", "Guaranteed fit", "Last refreshed", "Dismiss Tender"):
        assert forbidden not in recommendation


def test_no_migration_and_single_head() -> None:
    config = Config()
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == [HEAD]


def test_documentation_has_exact_required_sections() -> None:
    document = source("docs/S6_4_HUNTER_RETIREMENT_FINAL_QA.md")
    headings = [line for line in document.splitlines() if line.startswith("## ")]
    assert len(headings) == 28
    assert headings[0] == "## 1. Hunter Surface Inventory"
    assert headings[-1] == "## 28. Deferred Sprint 7 Work"
