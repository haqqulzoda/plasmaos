"""S1-7: previews fit for a Loom: Central Asian REOIs only (own bid countries first) unless --allow-global, no
fallback, best of N candidates with the AI cost per candidate, references described from the ledger only."""

from __future__ import annotations

import asyncio
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.access import USER_APPROVAL_APPROVED
from app.models.all_models import User
from app.models.base import MembershipState
from app.models.tenancy import Membership
from app.services import eoi_notes
from app.services import pursuit_analysis as analysis_service
from app.services.award_ledger import ingest_world_bank_awards
from app.services.official_notice import sync_official_notices
from scripts import test_s0_5b4_baseline as support
from scripts.demo import prospect as previews
from scripts.demo import seed_demo
from scripts.demo.seed_demo import DemoSeedError, Options
from test_d3_04_demo_seed import _fake_analyzer, _inline, _note
from test_s1_6_ledger_preview import LEDGER, TODAY, _reoi
from test_s1_award_ledger import HEAD, NOW, _pages


def test_scope_tiers() -> None:
    prospect = previews.LedgerProspect(
        firm_name="Samarqand Audit", country="Uzbekistan", services=["Consulting services"], sectors=["Water"],
        references=[previews.ProspectReference(project_name="Audit", country="Uzbekistan", service="Consulting services",
                                               source_url="https://projects.worldbank.org/en/projects-operations/procurement-detail/AUD-1")],
        award_keywords=["audit"], bid_countries=["Uzbekistan", "Kyrgyz Republic"])
    assert previews.scope_tier("Kyrgyz Republic", prospect, False) == 0
    assert previews.scope_tier("Tajikistan", prospect, False) == 1
    assert previews.scope_tier("Central Asia", prospect, False) == 1
    assert previews.scope_tier("Kenya", prospect, False) is None
    assert previews.scope_tier("Kenya", prospect, True) == 2


def test_loom_previews(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private"))
    monkeypatch.setattr(analysis_service.pursuit_analyzer, "analyze_pack_items", _fake_analyzer())

    async def no_provider(request):
        raise AssertionError("the seed passes its own note provider in tests")

    monkeypatch.setattr(eoi_notes, "gemini_note_call", no_provider)

    async def scenario() -> None:
        database = support.database_name("s1_7_loom")
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


async def _add(sessions, tenders: dict) -> dict[str, UUID]:
    async with sessions() as db:
        db.add_all(tenders.values())
        await db.flush()
        await sync_official_notices(db, list(tenders.values()))
        await db.commit()
        return {key: row.id for key, row in tenders.items()}


async def _flow(sessions) -> None:
    async with sessions() as db:
        await ingest_world_bank_awards(db, fetch=_pages(LEDGER)[0], countries=("Uzbekistan", "Kazakhstan"),
                                       since=date(2024, 10, 10), now=NOW, request_delay_seconds=0)
        db.add(User(google_id="google-subject-demo", email=seed_demo.DEMO_EMAIL, name="Plasma Support (demo)",
                    platform_role="pilot_user", approval_status=USER_APPROVAL_APPROVED))
        await db.commit()
    async with sessions() as db:
        prospect = await previews.prospect_from_ledger(db, "SAMARQAND AUDIT", country="Uzbekistan")
    # bid countries from every row of the firm with the same bidder country (the Kazakh-registered namesake is out)
    assert prospect.bid_countries == ["Uzbekistan"]
    # references: what the award notice says, field by field
    scope = prospect.references[-1].scope
    assert scope.startswith("Assignment: Audit of project financial statements, water supply project.")
    for part in ("Client: Ministry of Water Resources.", "Sectors (project tags): Water Supply.", "Awarded 2026.",
                 "Contract value as published: USD 50,000.00.", "World Bank contract award notice AUD-1."):
        assert part in scope

    # ---- no Central Asian REOI: no fallback ----------------------------------------------------------
    ids = await _add(sessions, {"kenya": _reoi(51, "Audit of financial statements of the health project", country="Kenya"),
                                "chile": _reoi(52, "Design of rural roads", country="Chile")})
    with pytest.raises(DemoSeedError, match="no Central Asian World Bank REOI is open for .*No fallback"):
        await previews.plan(sessions, Options(target="local", dry_run=True), prospect, today=TODAY)
    wide = await previews.plan(sessions, Options(target="local", dry_run=True, allow_global=True), prospect, today=TODAY)
    assert wide["pursuit_tender"]["tender_id"] == str(ids["kenya"]) and wide["scope"] == "global (--allow-global)"
    # outside Central Asia a REOI must share a word with the awards (the Chilean roads REOI is not a candidate)
    assert [item["tender_id"] for item in wide["candidates"]] == [str(ids["kenya"])]
    assert wide["pick_reason"].startswith("outside Central Asia; ")
    unrelated = previews.LedgerProspect(**{**prospect.model_dump(), "award_keywords": ["zoology"],
                                           "award_keyword_weights": {"zoology": 1.0}})
    with pytest.raises(DemoSeedError, match="shares a word"):
        await previews.plan(sessions, Options(target="local", dry_run=True, allow_global=True), unrelated, today=TODAY)

    # ---- Central Asia: own bid countries first, then the rest of Central Asia, each open REOI a candidate ----
    ids |= await _add(sessions, {"tj_audit": _reoi(53, "Audit of the irrigation project accounts", country="Tajikistan"),
                                 "uz_roads": _reoi(54, "Design of urban roads", country="Uzbekistan"),
                                 "uz_short": _reoi(55, "Audit of the energy project", country="Uzbekistan", long=False)})
    narrow = await previews.plan(sessions, Options(target="local", dry_run=True), prospect, today=TODAY)
    order = [item["tender_id"] for item in narrow["candidates"]]
    assert order == [str(ids["uz_roads"]), str(ids["tj_audit"])]  # under 5,000 characters and outside CA are out
    assert [item["scope_tier"] for item in narrow["candidates"]] == [0, 1]
    assert narrow["pick_reason"].startswith("one of the firm's own bid countries; ")
    wide = await previews.plan(sessions, Options(target="local", dry_run=True, allow_global=True), prospect, today=TODAY)
    # S1-8: pools in order (open Central Asia, replay, then outside): an open Central Asian REOI keeps Kenya out
    assert [item["tender_id"] for item in wide["candidates"]] == order and wide["pool"] == "open"

    # ---- best of N: one kept, the others archived, a table with criteria and AI cost -------------------
    options = Options(target="local", confirm="SEED_DEMO", poll_seconds=0.05, analysis_timeout=60, candidates=2)
    result = await previews.seed_best_of(sessions, options, prospect, candidates=2, today=TODAY,
                                         process_inline=_inline, note_call=_note)
    runs = result["candidates"]
    assert [run["tender"] for run in runs] == [narrow["candidates"][0]["external_id"], narrow["candidates"][1]["external_id"]]
    assert sum(run["kept"] for run in runs) == 1
    kept = next(run for run in runs if run["kept"])
    assert all(run["criteria_matched"] <= kept["criteria_matched"] for run in runs)
    assert all(isinstance(run["ai_cost"]["calls"], int) for run in runs)
    table = previews.candidates_table(result)
    assert all(run["tender"] in table for run in runs) and "criteria" in table and "AI cost USD" in table
    async with sessions() as db:
        user = await db.scalar(select(User).where(User.email == seed_demo.DEMO_EMAIL))
        active = (await db.scalars(select(Membership.organization_id).where(
            Membership.user_id == user.id, Membership.state == MembershipState.ACTIVE))).all()
        assert [str(value) for value in active] == [kept["organization_id"]]
