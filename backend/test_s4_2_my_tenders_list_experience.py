"""Sprint 4.2 My Tenders API and customer-surface contracts."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.base import TenderEngagementStatus, TenderStatus
from app.services.my_tenders import MyTendersQuery, _base_list_statement, _ordered


BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
HEAD = "20260901_0001_sr2_3_connector_metrics"


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_no_migration_and_sprint_4_1_head_remains_canonical() -> None:
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [HEAD]
    assert not any(
        "s4_2" in path.name.casefold()
        for path in (BACKEND_DIR / "alembic/versions").glob("*.py")
    )


def test_list_query_is_canonical_tenant_scoped_and_engagement_only() -> None:
    service = source("backend/app/services/my_tenders.py")
    assert "TenderEngagement.user_id == user_id" in service
    assert "TenderEngagement.company_profile_id == company_profile_id" in service
    assert ".join(Tender, Tender.id == TenderEngagement.tender_id)" in service
    assert ".outerjoin(Project" in service
    assert "Proposal" not in service
    assert "TenderAnalysis" not in service
    assert "TenderRecommendation" not in service
    assert "company_name" not in service


def test_default_dismissed_policy_filters_only_engagement_status() -> None:
    statement = _base_list_statement(
        user_id=__import__("uuid").uuid4(),
        company_profile_id=__import__("uuid").uuid4(),
        query=MyTendersQuery(),
    )
    sql = str(statement)
    assert "tender_engagements.status !=" in sql
    assert TenderEngagementStatus.DISMISSED.value in statement.compile().params.values()
    assert "proposals" not in sql.casefold()


def test_sorting_is_database_backed_stable_and_null_deadlines_are_explicit() -> None:
    base = _base_list_statement(
        user_id=__import__("uuid").uuid4(),
        company_profile_id=__import__("uuid").uuid4(),
        query=MyTendersQuery(status="ALL"),
    )
    recent = str(_ordered(base, "recently_updated"))
    deadline = str(_ordered(base, "deadline_soonest"))
    assert "status_changed_at DESC" in recent
    assert "tender_engagements.id DESC" in recent
    assert "CASE WHEN (tenders.deadline IS NULL)" in deadline
    assert "tenders.deadline ASC" in deadline


def test_api_is_bounded_safe_and_uses_current_profile() -> None:
    api = source("backend/app/api/endpoints/my_tenders.py")
    assert '@router.get("/my-tenders"' in api
    assert '@router.get("/my-tenders/{engagement_id}"' in api
    assert '"/tenders/{tender_id}/engagement"' in api
    assert "le=100" in api
    assert "CompanyProfile.user_id == current_user.id" in api
    assert "require_approved_pilot_access" in api
    assert "current_user.id" in api
    assert "company_name" not in api
    schema = source("backend/app/schemas/engagement.py")
    for forbidden in (
        "user_id",
        "company_profile_id",
        "auth_version",
        "storage_reference",
        "structured_data",
        "analysis_json",
    ):
        assert forbidden not in schema


def test_save_is_explicit_idempotent_and_never_downgrades_higher_state() -> None:
    service = source("backend/app/services/tender_engagements.py")
    block = service.split("async def save_tender_to_my_tenders", 1)[1].split(
        "async def set_tender_engagement_status", 1
    )[0]
    assert "MANUAL_SAVE" in block
    assert "TenderEngagementStatus.SAVED" in block
    assert "TenderEngagementStatus.DISMISSED" in block
    assert "resolution.engagement.status !=" in block
    assert "PREPARING" not in block
    assert "SUBMITTED" not in block
    assert "WON" not in block
    assert "LOST" not in block


def test_frontend_my_tenders_has_no_legacy_data_source_or_workflow_leakage() -> None:
    page = source("frontend/app/dashboard/my-tenders/page.tsx")
    assert "'/my-tenders'" in page
    assert "My Tenders" in page
    assert "No tenders saved yet" in page
    assert "Explore Tenders" in page
    assert "Engagement:" in page
    assert "Tender:" in page
    assert "PAGE_SIZE = 25" in page
    assert "useSearchParams" in page
    for forbidden in (
        "/proposals",
        "Proposal",
        "TenderAnalysis",
        "Recommendation",
        "Hunter",
        "mark_submitted",
        "mark_won",
        "mark_lost",
    ):
        assert forbidden not in page


def test_frontend_navigation_separates_bid_preparation_and_my_tenders() -> None:
    layout = source("frontend/app/dashboard/layout.tsx")
    assert "name: 'My Tenders'" in layout
    assert "href: '/dashboard/my-tenders'" in layout
    assert "name: 'Bid Preparation'" in layout
    assert "href: '/dashboard/bid-preparation'" in layout
    bids = source("frontend/app/dashboard/bid-preparation/page.tsx")
    assert "api.get('/proposals')" in bids


def test_passive_tender_detail_only_reads_and_click_handler_is_the_only_post() -> None:
    component = source("frontend/components/tenders/TenderEngagementPanel.tsx")
    effect = component.split("const save =", 1)[0]
    save = component.split("const save =", 1)[1]
    assert "api.get<TenderScopedEngagementResponse>" in effect
    assert "api.post" not in effect
    assert "api.post<SaveToMyTendersResponse>" in save
    assert "onClick={save}" in save
    assert "Save to My Tenders" in component


def test_source_status_is_separate_in_schema_and_frontend() -> None:
    schema = source("backend/app/schemas/engagement.py")
    assert "engagement_status: TenderEngagementStatus" in schema
    assert "tender_status: TenderStatus" in schema
    page = source("frontend/app/dashboard/my-tenders/page.tsx")
    assert "Engagement: {engagementStatusLabel" in page
    assert "Tender: {tenderStatusLabel" in page
    assert TenderStatus.CANCELLED.value in page
