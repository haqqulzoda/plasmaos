"""Sprint 4.4 canonical workflow API and UX contracts."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.base import TenderEngagementStatus
from app.services.tender_engagements import (
    ACTION_CORRECT_TO_LOST,
    ACTION_CORRECT_TO_PREPARING,
    ACTION_CORRECT_TO_SUBMITTED,
    ACTION_CORRECT_TO_WON,
    ACTION_DISMISS,
    ACTION_EVALUATE,
    ACTION_MARK_SUBMITTED,
    ACTION_PREPARE_BID,
    ACTION_RECORD_LOST,
    ACTION_RECORD_WON,
    ACTION_SAVE,
    allowed_actions_for_status,
)


ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
HEAD = "20260828_0003_s4_1_tender_engagement_foundation"


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_no_migration_and_locked_head() -> None:
    config = Config()
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == [HEAD]
    assert not any("s4_4" in path.name.casefold() for path in (BACKEND / "alembic/versions").glob("*.py"))


def test_backend_allowed_action_contract_is_exact() -> None:
    expected = {
        TenderEngagementStatus.SAVED: (ACTION_EVALUATE, ACTION_PREPARE_BID, ACTION_DISMISS),
        TenderEngagementStatus.EVALUATING: (ACTION_PREPARE_BID, ACTION_DISMISS),
        TenderEngagementStatus.PREPARING: (ACTION_MARK_SUBMITTED, ACTION_DISMISS),
        TenderEngagementStatus.SUBMITTED: (ACTION_RECORD_WON, ACTION_RECORD_LOST, ACTION_CORRECT_TO_PREPARING),
        TenderEngagementStatus.WON: (ACTION_CORRECT_TO_SUBMITTED, ACTION_CORRECT_TO_LOST),
        TenderEngagementStatus.LOST: (ACTION_CORRECT_TO_SUBMITTED, ACTION_CORRECT_TO_WON),
        TenderEngagementStatus.DISMISSED: (ACTION_SAVE, ACTION_EVALUATE, ACTION_PREPARE_BID),
    }
    assert {status: allowed_actions_for_status(status) for status in TenderEngagementStatus} == expected


def test_action_api_is_semantic_scoped_and_stale_safe() -> None:
    api = source("backend/app/api/endpoints/my_tenders.py")
    service = source("backend/app/services/tender_engagements.py")
    assert '"/my-tenders/{engagement_id}/actions/{action}"' in api
    for command in ("evaluate", "mark-submitted", "mark-won", "mark-lost", "dismiss", "correct-to-preparing", "correct-to-submitted", "correct-to-won", "correct-to-lost"):
        assert f'"{command}"' in api
    assert "TenderEngagement.user_id == user_id" in service
    assert "TenderEngagement.company_profile_id == company_profile_id" in service
    assert ".with_for_update()" in service
    assert "expected_status" in service
    assert "HTTP_404_NOT_FOUND" in api
    assert "HTTP_409_CONFLICT" in api


def test_only_canonical_service_writes_engagement_status() -> None:
    service = BACKEND / "app/services/tender_engagements.py"
    for path in (BACKEND / "app").rglob("*.py"):
        if path == service or path.name == "engagement.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert "engagement.status =" not in text
        assert ".status = TenderEngagementStatus" not in text


def test_submission_and_outcome_writes_are_explicit_only() -> None:
    service = source("backend/app/services/tender_engagements.py")
    assert "async def mark_submitted" in service
    assert "async def mark_won" in service
    assert "async def mark_lost" in service
    for path in (BACKEND / "app").rglob("*.py"):
        if path.as_posix().endswith("services/tender_engagements.py") or path.name in {"base.py", "engagement.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert "status=TenderEngagementStatus.SUBMITTED" not in text
        assert "status=TenderEngagementStatus.WON" not in text
        assert "status=TenderEngagementStatus.LOST" not in text


def test_shared_customer_workflow_copy_is_truthful() -> None:
    workflow = source("frontend/components/tenders/EngagementWorkflowActions.tsx")
    assert "Mark as Submitted" in workflow
    assert "You are recording that this bid was submitted." in workflow
    assert "Plasma does not transmit the bid" in workflow
    assert "Record as Won" in workflow
    assert "Record as Lost" in workflow
    assert "This records the outcome in Plasma." in workflow
    assert "Correct status to Preparing" in workflow
    assert "Any Bid Preparation work is preserved." in workflow
    assert "Submit Bid" not in workflow
    assert "Submit Tender" not in workflow


def test_all_three_surfaces_share_one_workflow_component() -> None:
    my_tenders = source("frontend/app/dashboard/my-tenders/page.tsx")
    tender = source("frontend/app/dashboard/tenders/[tenderId]/page.tsx")
    bid = source("frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx")
    assert "EngagementWorkflowActions" in my_tenders
    assert "TenderEngagementPanel" in tender
    assert "TenderEngagementPanel" in bid
    assert "proposalContext" in bid


def test_routes_remain_single_identity_and_passive_reads_are_get_only() -> None:
    bid = source("frontend/app/dashboard/bid-preparation/[proposalId]/page.tsx")
    tender = source("frontend/app/dashboard/tenders/[tenderId]/page.tsx")
    compliance = source("frontend/app/dashboard/tenders/[tenderId]/compliance/page.tsx")
    panel = source("frontend/components/tenders/TenderEngagementPanel.tsx")
    assert "Promise<{ proposalId: string }>" in bid
    assert "Promise<{ tenderId: string }>" in tender
    assert "Promise<{ tenderId: string }>" in compliance
    effect = panel.split("useEffect", 1)[1].split("const save", 1)[0]
    assert "api.post" not in effect


def test_no_schema_history_or_sprint_five_leakage() -> None:
    model = source("backend/app/models/engagement.py")
    assert "submitted_at" not in model
    assert "event" not in model.casefold()
    workflow = source("frontend/components/tenders/EngagementWorkflowActions.tsx")
    for forbidden in ("drag", "assignee", "crm", "award synchronization", "automatic submission"):
        assert forbidden not in workflow.casefold()
