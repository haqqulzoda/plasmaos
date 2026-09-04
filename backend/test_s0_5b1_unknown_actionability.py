"""Focused regression contract for Sprint 0.5B.1 UNKNOWN actionability."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.api.endpoints import proposals as proposal_endpoints
from app.api.endpoints import tenders as tender_endpoints
from app.core.tender_actionability import (
    actionable_tender_condition,
    is_tender_actionable,
)
from app.models.all_models import ProposalStatus, Tender, TenderStatus
from app.services.tender_sources.adb import AdbTenderSource, adb_lifecycle_status
from app.services.tender_sources.base import upsert_tender
from app.workers.hunter_tasks import _pending_tenders_stmt
from app.schemas.proposal import ProposalCreate


ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT.parent / "frontend"


def read_backend(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def read_frontend(path: str) -> str:
    return (FRONTEND / path).read_text(encoding="utf-8")


class _ExistingResult:
    def __init__(self, tender: Tender):
        self.tender = tender

    def scalar_one_or_none(self) -> Tender:
        return self.tender


class _ExistingTenderSession:
    def __init__(self, tender: Tender):
        self.tender = tender
        self.add_called = False

    async def execute(self, _statement):
        return _ExistingResult(self.tender)

    def add(self, _tender: Tender) -> None:
        self.add_called = True


class _SequenceSession:
    def __init__(self, *values):
        self.values = list(values)
        self.added = None

    async def execute(self, _statement):
        return _ExistingResult(self.values.pop(0))

    def add(self, value) -> None:
        self.added = value

    async def commit(self) -> None:
        return None

    async def refresh(self, proposal) -> None:
        proposal.id = uuid4()
        proposal.final_pdf_url = None
        proposal.margin_percent = 10.0
        proposal.include_vat = True
        proposal.currency = "UZS"
        proposal.created_at = datetime(2026, 8, 25, tzinfo=timezone.utc)


def _existing_adb_tender(status: TenderStatus) -> Tender:
    return Tender(
        source_system="adb",
        external_id="1205001",
        canonical_source_key="adb:1205001",
        source_url="https://www.adb.org/node/1205001",
        title="ADB lifecycle test",
        budget=0,
        currency="USD",
        status=status,
        category="Other",
    )


class ActionabilityContractTests(unittest.TestCase):
    def test_01_open_is_actionable(self) -> None:
        self.assertTrue(is_tender_actionable(Tender(status=TenderStatus.OPEN)))

    def test_02_unknown_is_not_actionable(self) -> None:
        self.assertFalse(is_tender_actionable(Tender(status=TenderStatus.UNKNOWN)))

    def test_03_closed_is_not_actionable(self) -> None:
        self.assertFalse(is_tender_actionable(Tender(status=TenderStatus.CLOSED)))

    def test_04_cancelled_is_not_actionable(self) -> None:
        self.assertFalse(is_tender_actionable(Tender(status=TenderStatus.CANCELLED)))

    def test_05_query_contract_is_open_equality(self) -> None:
        compiled = str(actionable_tender_condition(Tender))
        self.assertIn("tenders.status", compiled)
        self.assertIn("=", compiled)

    def test_06_total_corpus_can_include_unknown(self) -> None:
        corpus = [Tender(status=TenderStatus.OPEN), Tender(status=TenderStatus.UNKNOWN)]
        actionable = [tender for tender in corpus if is_tender_actionable(tender)]
        self.assertEqual(len(corpus), 2)
        self.assertEqual(len(actionable), 1)


class ExplorerAndDashboardTests(unittest.TestCase):
    def test_07_explorer_default_is_open(self) -> None:
        condition = tender_endpoints._tender_lifecycle_condition(None)
        self.assertIsNotNone(condition)
        self.assertIn("tenders.status", str(condition))

    def test_08_explorer_explicit_open_is_supported(self) -> None:
        self.assertIsNotNone(tender_endpoints._tender_lifecycle_condition("OPEN"))

    def test_09_explorer_explicit_unknown_is_supported(self) -> None:
        condition = tender_endpoints._tender_lifecycle_condition("unknown")
        self.assertEqual(condition.right.value, TenderStatus.UNKNOWN)

    def test_10_explorer_explicit_all_removes_lifecycle_predicate(self) -> None:
        self.assertIsNone(tender_endpoints._tender_lifecycle_condition("all"))

    def test_11_explorer_rejects_unsupported_status(self) -> None:
        with self.assertRaises(ValueError):
            tender_endpoints._tender_lifecycle_condition("active-ish")

    def test_12_dashboard_current_logic_uses_actionability_contract(self) -> None:
        dashboard = read_frontend("app/dashboard/page.tsx")
        block = dashboard.split("function isCurrentTender", 1)[1].split("\n}", 1)[0]
        self.assertIn("isTenderActionable(tender)", block)


class HunterTests(unittest.TestCase):
    def test_13_worker_candidates_require_open(self) -> None:
        statement = _pending_tenders_stmt(
            __import__("uuid").uuid4(),
            datetime(2026, 8, 25, tzinfo=timezone.utc),
        )
        self.assertIn("tenders.status", str(statement))

    def test_14_existing_unknown_recommendations_are_filtered_at_query_level(self) -> None:
        hunter = read_backend("app/api/endpoints/hunter.py")
        route = hunter.split("async def list_recommendations", 1)[1].split(
            '@router.post(', 1
        )[0]
        self.assertIn(".join(Tender", route)
        self.assertIn("actionable_tender_condition(Tender)", route)

    def test_15_open_recommendation_payload_path_is_preserved(self) -> None:
        hunter = read_backend("app/api/endpoints/hunter.py")
        self.assertIn('"strategic_rationale": rec.strategic_rationale', hunter)
        self.assertTrue(is_tender_actionable("OPEN"))


class ComplianceAndProposalTests(unittest.TestCase):
    def test_16_new_compliance_generation_has_nonactionable_guard(self) -> None:
        tenders = read_backend("app/api/endpoints/tenders.py")
        analyze = tenders.split("async def analyze_tender", 1)[1].split(
            '@router.get("/{tender_id}/latest-analysis"', 1
        )[0]
        self.assertIn("if not is_tender_actionable(tender)", analyze)
        self.assertIn("HTTP_409_CONFLICT", analyze)

    def test_17_historical_analysis_read_route_remains_available(self) -> None:
        tenders = read_backend("app/api/endpoints/tenders.py")
        latest = tenders.split('@router.get("/{tender_id}/latest-analysis"', 1)[1].split(
            "@router.", 1
        )[0]
        self.assertNotIn("is_tender_actionable", latest)

    def test_18_existing_proposal_is_returned_before_actionability_guard(self) -> None:
        service = read_backend("app/services/bid_preparation.py")
        artifact = service.split("async def get_or_create_proposal_artifact", 1)[1].split(
            "async def prepare_bid", 1
        )[0]
        self.assertLess(
            artifact.index("if existing is not None"),
            artifact.index("if not is_tender_actionable(tender)"),
        )

    def test_19_new_unknown_proposal_creation_is_guarded(self) -> None:
        proposals = read_backend("app/api/endpoints/proposals.py")
        create = proposals.split("async def create_proposal", 1)[1].split(
            '@router.get(""', 1
        )[0]
        self.assertIn("HTTP_409_CONFLICT", create)

    def test_20_existing_proposal_get_remains_readable(self) -> None:
        proposals = read_backend("app/api/endpoints/proposals.py")
        get_route = proposals.split("async def get_proposal", 1)[1].split(
            '@router.put(', 1
        )[0]
        self.assertNotIn("is_tender_actionable", get_route)
        self.assertIn("_proposal_with_tender_response", get_route)
        self.assertIn("tender_status=tender.status", proposals)

    def test_21_cached_ai_draft_precedes_new_generation_guard(self) -> None:
        proposals = read_backend("app/api/endpoints/proposals.py")
        ai_draft = proposals.split("async def ai_draft_proposal", 1)[1].split(
            '@router.post("/{proposal_id}/upload-tz"', 1
        )[0]
        self.assertLess(ai_draft.index("return AIDraftResponse"), ai_draft.index("if not is_tender_actionable"))

    def test_22_unknown_compliance_generation_returns_conflict(self) -> None:
        user = SimpleNamespace(id=uuid4())
        db = _SequenceSession(SimpleNamespace(status=TenderStatus.UNKNOWN))
        with patch.object(tender_endpoints, "_ensure_tender_access", new=AsyncMock()):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(tender_endpoints.analyze_tender(uuid4(), current_user=user, session=db))
        self.assertEqual(raised.exception.status_code, 409)

    def test_23_open_compliance_reaches_existing_document_validation(self) -> None:
        user = SimpleNamespace(id=uuid4())
        tender = SimpleNamespace(status=TenderStatus.OPEN, compiled_master_text="")
        db = _SequenceSession(tender)
        with patch.object(tender_endpoints, "_ensure_tender_access", new=AsyncMock()):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(tender_endpoints.analyze_tender(uuid4(), current_user=user, session=db))
        self.assertEqual(raised.exception.status_code, 400)

    def test_24_unknown_new_proposal_returns_conflict(self) -> None:
        tender_id = uuid4()
        user = SimpleNamespace(id=uuid4())
        db = _SequenceSession(SimpleNamespace(id=tender_id, status=TenderStatus.UNKNOWN))
        failure = proposal_endpoints.BidPreparationNotActionableError("not actionable")
        with patch.object(
            proposal_endpoints,
            "get_or_create_proposal_artifact",
            new=AsyncMock(side_effect=failure),
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(proposal_endpoints.create_proposal(
                    ProposalCreate(tender_id=tender_id), current_user=user, db=db
                ))
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIsNone(db.added)

    def test_25_open_new_proposal_behavior_is_unchanged(self) -> None:
        tender_id = uuid4()
        user = SimpleNamespace(id=uuid4())
        db = _SequenceSession(SimpleNamespace(id=tender_id, status=TenderStatus.OPEN))
        artifact = SimpleNamespace(
            id=uuid4(), user_id=user.id, tender_id=tender_id,
            status=ProposalStatus.DRAFT, ai_confidence_score=0,
            structured_data={}, final_pdf_url=None, margin_percent=20,
            include_vat=True, currency="UZS",
            created_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        )
        resolution = SimpleNamespace(proposal=artifact, created=True)
        with patch.object(
            proposal_endpoints,
            "get_or_create_proposal_artifact",
            new=AsyncMock(return_value=resolution),
        ):
            response = asyncio.run(proposal_endpoints.create_proposal(
                ProposalCreate(tender_id=tender_id), current_user=user, db=db
            ))
        self.assertEqual(response.tender_id, tender_id)
        self.assertIsNone(db.added)

    def test_26_new_document_sync_requires_actionable_tender(self) -> None:
        tenders = read_backend("app/api/endpoints/tenders.py")
        sync_route = tenders.split("async def sync_tender_documents", 1)[1].split(
            '@router.get("/{tender_id}/sync-status"', 1
        )[0]
        self.assertLess(sync_route.index("if existing_job is not None"), sync_route.index("if not is_tender_actionable(tender)"))
        self.assertIn("HTTP_409_CONFLICT", sync_route)


class FrontendContractTests(unittest.TestCase):
    def test_27_typescript_lifecycle_union_includes_unknown(self) -> None:
        tender_types = read_frontend("types/tender.ts")
        self.assertIn("'OPEN' | 'CLOSED' | 'CANCELLED' | 'UNKNOWN'", tender_types)

    def test_28_unknown_has_explicit_non_open_label_and_style(self) -> None:
        tender_types = read_frontend("types/tender.ts")
        self.assertIn("return 'Actionability unknown'", tender_types)
        self.assertIn("border-amber-500/30", tender_types)

    def test_29_explorer_defaults_status_filter_to_open(self) -> None:
        explorer = read_frontend("app/dashboard/tenders/page.tsx")
        self.assertIn('params.get("status") || "OPEN"', explorer)
        self.assertIn("status: query.lifecycleStatus.toLowerCase()", explorer)

    def test_30_explorer_unknown_ctas_use_actionability(self) -> None:
        explorer = read_frontend("app/dashboard/tenders/page.tsx")
        self.assertIn("const actionable = isTenderActionable(tender.status)", explorer)
        self.assertIn("disabled={!actionable || expired}", explorer)

    def test_31_details_remain_visible_with_explicit_status_badge(self) -> None:
        details = read_frontend("app/dashboard/tenders/[tenderId]/page.tsx")
        self.assertIn('tExplorer("status.open")', details)
        self.assertIn('t("status", { status: tenderStatus })', details)
        self.assertIn("const actionable = isTenderActionable(tender)", details)
        self.assertIn("canStartNew={actionable}", details)

    def test_32_compliance_guard_still_loads_cached_history(self) -> None:
        compliance = read_frontend("app/dashboard/tenders/[tenderId]/compliance/page.tsx")
        self.assertIn("!isTenderActionable(tenderData)", compliance)
        self.assertIn("setTextAccessReadyVersion", compliance)
        self.assertIn("/latest-analysis", compliance)

    def test_33_bid_route_is_passive_and_prepare_is_explicit(self) -> None:
        bid = read_frontend("app/dashboard/bid-preparation/[proposalId]/page.tsx")
        self.assertIn("api.get<Proposal>", bid)
        self.assertNotIn("api.post<{ id: string }>('/proposals'", bid)
        self.assertIn("const actionable = isTenderActionable(proposal.tender_status)", bid)
        self.assertIn("disabled={isGenerating || !actionable}", bid)
        self.assertIn("<TenderEngagementPanel tenderId={proposal.tender_id} proposalContext />", bid)
        prepare = read_frontend("components/bid-preparation/PrepareBidButton.tsx")
        self.assertIn("onClick={prepare}", prepare)
        self.assertIn('"/proposals/prepare"', prepare)


class AdbReconciliationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 25, tzinfo=timezone.utc)

    def test_34_stale_degraded_active_record_is_unknown(self) -> None:
        raw = {
            "source_kind": "legacy_rss",
            "source_status": "Active",
            "deadline_text": None,
        }
        self.assertEqual(adb_lifecycle_status(raw, now=self.now), "UNKNOWN")

    def test_35_authoritative_active_evidence_is_open(self) -> None:
        raw = {"source_kind": "official_html", "source_status": "Active"}
        self.assertEqual(adb_lifecycle_status(raw, now=self.now), "OPEN")

    def test_36_authoritative_future_deadline_evidence_is_open(self) -> None:
        raw = {"source_kind": "official_html", "deadline_text": "30 Sep 2026"}
        self.assertEqual(adb_lifecycle_status(raw, now=self.now), "OPEN")

    async def test_37_degraded_refresh_cannot_upgrade_unknown_to_open(self) -> None:
        tender = _existing_adb_tender(TenderStatus.UNKNOWN)
        session = _ExistingTenderSession(tender)
        normalized = AdbTenderSource().normalize({
            "guid": "1205001",
            "title": "ADB lifecycle test",
            "link": "https://www.adb.org/node/1205001",
            "source_kind": "legacy_rss",
            "source_status": "Active",
            "notice_type": "Invitation for Bids",
        })

        updated, created = await upsert_tender(session, normalized)

        self.assertFalse(created)
        self.assertEqual(updated.status, TenderStatus.UNKNOWN)
        self.assertFalse(session.add_called)

    async def test_38_authoritative_refresh_can_upgrade_unknown_to_open(self) -> None:
        tender = _existing_adb_tender(TenderStatus.UNKNOWN)
        session = _ExistingTenderSession(tender)
        normalized = AdbTenderSource().normalize({
            "guid": "1205001",
            "title": "ADB lifecycle test",
            "link": "https://www.adb.org/node/1205001",
            "source_kind": "official_html",
            "source_status": "Active",
            "notice_type": "Invitation for Bids",
        })

        updated, created = await upsert_tender(session, normalized)

        self.assertFalse(created)
        self.assertEqual(updated.status, TenderStatus.OPEN)
        self.assertFalse(session.add_called)


if __name__ == "__main__":
    unittest.main()
