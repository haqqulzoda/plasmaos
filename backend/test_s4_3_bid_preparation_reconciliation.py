"""Static/contract regressions for Sprint 4.3 Bid Preparation."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def backend(path: str) -> str:
    return (BACKEND / path).read_text(encoding="utf-8")


def frontend(path: str) -> str:
    return (FRONTEND / path).read_text(encoding="utf-8")


def test_prepare_service_is_atomic_caller_transaction_and_uses_canonical_services():
    source = backend("app/services/bid_preparation.py")
    assert "async def prepare_bid(" in source
    assert "get_or_create_tender_engagement(" in source
    assert "set_tender_engagement_status(" in source
    assert 'origin=TenderEngagementOrigin.BID_PREPARATION' in source
    assert 'constraint="uq_proposals_user_tender"' in source
    assert "db.commit(" not in source
    assert "engagement.status =" not in source


def test_prepare_transition_contract_preserves_higher_states():
    source = backend("app/services/bid_preparation.py")
    for lower in ("SAVED", "EVALUATING", "DISMISSED"):
        assert f"TenderEngagementStatus.{lower}" in source
    assert "TenderEngagementStatus.PREPARING" in source
    # Higher states are deliberately absent from the mutation-set literal.
    mutation_set = re.search(r"if engagement\.status in \{(?P<body>.*?)\}:", source, re.S)
    assert mutation_set
    for higher in ("SUBMITTED", "WON", "LOST"):
        assert higher not in mutation_set.group("body")


def test_proposal_identity_is_existing_one_per_user_tender_contract():
    model = backend("app/models/all_models.py")
    service = backend("app/services/bid_preparation.py")
    assert 'UniqueConstraint(\n            "user_id",\n            "tender_id"' in model
    assert "uq_proposals_user_tender" in service
    assert not list((BACKEND / "alembic/versions").glob("*s4_3*"))


def test_prepare_and_continue_endpoints_are_explicit_posts():
    source = backend("app/api/endpoints/proposals.py")
    assert '@router.post("/prepare", response_model=PrepareBidResponse)' in source
    assert '@router.post("/{proposal_id}/continue", response_model=PrepareBidResponse)' in source
    assert "tender_id=command.tender_id" in source
    assert "proposal_id=proposal_id" in source


def test_proposal_reads_require_owned_user_and_valid_profile_context():
    source = backend("app/api/endpoints/proposals.py")
    assert "Proposal.user_id == current_user.id" in source
    assert "profile_id = await _owned_profile_id" in source
    assert "TenderEngagement.company_profile_id == profile_id" in source
    assert "CompanyProfile.user_id == user_id" in source


def test_proposal_status_and_exports_never_write_engagement_submission():
    proposal_source = backend("app/api/endpoints/proposals.py")
    assert "proposal.status = ProposalStatus.COMPLETED" in proposal_source
    assert "ProposalStatus.SUBMITTED" not in proposal_source
    assert "TenderEngagementStatus.SUBMITTED" not in proposal_source
    assert "mark_submitted" not in proposal_source


def test_customer_routes_have_unambiguous_dynamic_identifiers():
    canonical = frontend("app/dashboard/bid-preparation/[proposalId]/page.tsx")
    legacy = frontend("app/dashboard/bids/[id]/page.tsx")
    assert "proposalId" in canonical
    assert "resolvedParams.id" not in canonical
    assert "api.post" not in legacy
    assert "tender_id" not in legacy


def test_no_passive_frontend_proposal_creation_remains():
    paths = (
        "app/dashboard/bid-preparation/[proposalId]/page.tsx",
        "app/dashboard/bids/[id]/page.tsx",
        "app/dashboard/tenders/[tenderId]/compliance/page.tsx",
    )
    for path in paths:
        source = frontend(path)
        assert "await api.post('/proposals'," not in source
    button = frontend("components/bid-preparation/PrepareBidButton.tsx")
    assert "onClick={prepare}" in button
    assert "useEffect" not in button


def test_navigation_and_copy_use_bid_preparation():
    layout = frontend("app/dashboard/layout.tsx")
    navigation = frontend("messages/en/navigation.json")
    listing = frontend("app/dashboard/bid-preparation/page.tsx")
    assert "nameKey: 'bidPreparation'" in layout
    assert '"bidPreparation": "Bid Preparation"' in navigation
    assert "My Bids" not in navigation
    assert "Completed preparation" in frontend("types/bid-preparation.ts")
    assert 'useTranslations("bidPreparation")' in listing
    assert 't("title")' in listing


def test_preflight_reports_reconciliation_without_repair():
    source = backend("scripts/run_s0_3_schema_data_preflight.py")
    for metric in (
        "total_proposals",
        "valid_owner_tender_profile_relationship",
        "incomplete_ownership",
        "missing_owner",
        "missing_tender",
        "owner_without_profile",
        "proposals_with_engagement",
        "proposals_without_engagement",
    ):
        assert metric in source
    assert "UPDATE proposals" not in source
    assert "INSERT INTO tender_engagements" not in source
