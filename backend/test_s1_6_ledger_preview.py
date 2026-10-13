"""S1-6: ledger-backed prospect previews: references from AWARDS only, the REOI pick (>= 5,000-character
notice, distinctive words of the awards, a printed reason), exclusive previews, the not-reviewed EOI status."""

from __future__ import annotations

import asyncio
from datetime import date
from uuid import UUID
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.access import USER_APPROVAL_APPROVED
from app.models.all_models import User
from app.models.base import MembershipState
from app.models.candidate_retrieval import Firm, ProjectReference
from app.models.eoi import EoiDraft
from app.models.tenancy import Membership
from app.services import eoi_notes
from app.services import pursuit_analysis as analysis_service
from app.services.award_ledger import ingest_world_bank_awards
from app.services.official_notice import sync_official_notices
from scripts import test_s0_5b4_baseline as support
from scripts.demo import prospect as previews
from scripts.demo import seed_demo
from scripts.demo.seed_demo import DemoSeedError, Options
from test_d3_04_demo_seed import DUTY, EXPERIENCE, SUBMISSION, _fake_analyzer, _inline, _note, _tender
from test_s1_award_ledger import HEAD, NOW, _html, _pages, _row

TODAY = date(2026, 10, 2)


def _award(notice_id: str, *, title: str, agency: str, status: str = "Awarded", country: str = "Uzbekistan",
           bidder: str = "SAMARQAND AUDIT LLC (111)", bidder_country: str = "Uzbekistan", price: str = "USD 50000.00",
           group: str = "Consultant Services", noticedate: str = "01-Sep-2026") -> dict:
    row = _row(notice_id, country=country, noticedate=noticedate, group=group,
               text_html=_html((status, [([(bidder, bidder_country)], price, None)])), sector="Water Supply")
    return dict(row, bid_description=title, agency_name=agency)


LEDGER = [
    _award("AUD-1", title="Audit of project financial statements, water supply project", agency="Ministry of Water Resources"),
    _award("AUD-2", title="External audit of financial statements, energy project", agency="National Electric Grid",
           bidder="SAMARQAND AUDIT (111)", price="UZS 1184657000.00", noticedate="01-Aug-2026"),
    # an evaluated bid and a works award never become references
    _award("AUD-3", title="Procurement audit of the health project", agency="Ministry of Health", status="Evaluated"),
    _award("AUD-W", title="Rehabilitation of the audit office building", agency="Ministry of Finance", group="Works"),
    # the same normalized name published in another country
    _award("AUD-K", title="Audit of financial statements, roads project", agency="KazAvtoZhol", country="Kazakhstan",
           bidder="SAMARQAND AUDIT (112)", bidder_country="Kazakhstan"),
]
BODY = "\n".join((EXPERIENCE, SUBMISSION, DUTY))
LONG = BODY + "\n" + "Further information is available at the address below. " * 100  # >= 5,000 characters


def _reoi(number: int, title: str, *, long: bool = True, **values):
    return _tender(number, title=title, country=values.pop("country", "Tajikistan"), body=BODY,
                   description=LONG if long else BODY + "\n" + "Short notice. " * 40, **values)


def test_award_keywords_drop_generic_words() -> None:
    words = previews.award_keywords(["Audit of project financial statements for the Water Supply Project, Phase 2"])
    assert {"audit", "financial", "statements", "water", "supply"} <= set(words)
    assert not {"project", "phase", "services", "consulting"} & set(words)


def test_ledger_preview_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private"))
    monkeypatch.setattr(analysis_service.pursuit_analyzer, "analyze_pack_items", _fake_analyzer())

    async def no_provider(request):
        raise AssertionError("the seed passes its own note provider in tests")

    monkeypatch.setattr(eoi_notes, "gemini_note_call", no_provider)

    async def scenario() -> None:
        database = support.database_name("s1_6_ledger_preview")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                await _flow(sessions)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _flow(sessions) -> None:
    async with sessions() as db:
        await ingest_world_bank_awards(db, fetch=_pages(LEDGER)[0], countries=("Uzbekistan", "Kazakhstan"),
                                       since=date(2024, 10, 10), now=NOW, request_delay_seconds=0)
        tenders = {
            "audit": _reoi(41, "Audit of project financial statements for the irrigation project"),
            "audit_short": _reoi(42, "Financial statements audit services", long=False),  # notice under 5,000 characters
            "roads": _reoi(43, "Design of rural roads"),
        }
        db.add_all(tenders.values())
        await db.flush()
        await sync_official_notices(db, list(tenders.values()))
        db.add(User(google_id="google-subject-demo", email=seed_demo.DEMO_EMAIL, name="Plasma Support (demo)",
                    platform_role="pilot_user", approval_status=USER_APPROVAL_APPROVED))
        await db.commit()
        ids = {key: row.id for key, row in tenders.items()}
        from app.models.all_models import TenderDocument
        lengths = {key: await db.scalar(select(func.max(func.length(TenderDocument.parsed_text))).where(
            TenderDocument.tender_id == value)) for key, value in ids.items()}
        assert lengths["audit"] >= 5_000 > lengths["audit_short"], lengths

    # ---- the prospect from the ledger: consulting AWARDS only ------------------------------------------
    async with sessions() as db:
        with pytest.raises(DemoSeedError, match="several countries"):
            await previews.prospect_from_ledger(db, "Samarqand Audit")
        with pytest.raises(DemoSeedError, match="only awards become references"):
            await previews.prospect_from_ledger(db, "Unknown Firm")
        prospect = await previews.prospect_from_ledger(db, "SAMARQAND AUDIT", country="Uzbekistan")
    # newest award first (same award date: notice id descending); the firm name is the first such award's
    assert prospect.organization_name == "SAMARQAND AUDIT — Plasma preview" and prospect.country == "Uzbekistan"
    assert prospect.award_notice_ids == ["AUD-2", "AUD-1"]  # AUD-3 (evaluated) and AUD-W (works) are out
    second, first = prospect.references
    assert first.project_name == "Audit of project financial statements, water supply project"
    assert first.client_name == "Ministry of Water Resources" and first.country == "Uzbekistan" and first.role == "LEAD"
    assert str(first.source_url).endswith("/procurement-detail/AUD-1") and first.start_date == "2026-05-01"
    assert (first.contract_value, first.contract_currency) == (50000.0, "USD") and "AUD-1" in first.scope
    assert (second.contract_value, second.contract_currency) == (1184657000.0, "UZS")
    values = previews.reference_values(first, "pv20261002-1")
    assert values["relevant_scope"].endswith("From public records, unverified. Source: " + str(first.source_url))
    assert values["evidence_state"] == "UNVERIFIED" and values["contract_value"] == Decimal("50000")

    # ---- the REOI pick: >= 5,000 characters, distinctive award words in the title, a printed reason ----
    plan = await previews.plan(sessions, Options(target="local", dry_run=True), prospect, today=TODAY)
    assert plan["source"] == "award ledger (awards only)"
    assert plan["pursuit_tender"]["tender_id"] == str(ids["audit"])
    assert str(ids["audit_short"]) not in [item["tender_id"] for item in plan["candidates"]]
    assert "audit" in plan["pick_reason"] and "5,000" not in plan["pick_reason"] and "characters" in plan["pick_reason"]
    # (REOIs outside Central Asia must share a word with the awards: test_s1_7_loom_previews)

    # ---- exclusive by default: an earlier preview is archived first ----------------------------------
    options = Options(target="local", confirm="SEED_DEMO", poll_seconds=0.05, analysis_timeout=60)
    earlier = previews.load_prospect(Path(__file__).parent / "scripts" / "demo" / "prospect.example.json")
    old = await previews.seed(sessions, options, earlier, today=TODAY, process_inline=_inline, note_call=_note)
    result = await previews.seed(sessions, options, prospect, today=TODAY, process_inline=_inline, note_call=_note)
    assert [item["organization_id"] for item in result["archived_other_previews"]] == [old["organization_id"]]
    assert result["eoi_draft_status"] == "NOT_REVIEWED_BY_TEAM" and result["pick_reason"] == plan["pick_reason"]
    assert set(result["timings_seconds"]) >= {"plan", "archive_other_previews", "analysis", "review_and_eoi"}
    async with sessions() as db:
        user = await db.scalar(select(User).where(User.email == seed_demo.DEMO_EMAIL))
        active = (await db.scalars(select(Membership.organization_id).where(
            Membership.user_id == user.id, Membership.state == MembershipState.ACTIVE))).all()
        assert [str(value) for value in active] == [result["organization_id"]]
        firm = await db.scalar(select(Firm).where(Firm.organization_id == UUID(result["organization_id"])))
        references = (await db.scalars(select(ProjectReference).where(ProjectReference.firm_id == firm.id))).all()
        assert sorted(row.evidence_provenance["source_url"].rsplit("/", 1)[1] for row in references) == ["AUD-1", "AUD-2"]
        assert all(row.evidence_state == "UNVERIFIED" for row in references)
        draft = await db.get(EoiDraft, UUID(result["eoi_draft_id"]))
        assert draft.manifest["draft_status"] == "NOT_REVIEWED_BY_TEAM"
        assert await db.scalar(select(func.count(EoiDraft.id))) == 2

