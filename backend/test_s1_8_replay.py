"""S1-8: Loom previews replayed on a CLOSED Central Asian REOI when no open one qualifies, labelled on the
preview, the pursuit and the EOI cover; Central Asian notices of 2,500-5,000 characters kept only when the
analysis extracts at least 4 requirements."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.endpoints.pursuits import get_pursuit
from app.core.access import USER_APPROVAL_APPROVED
from app.models.all_models import Tender, TenderDocument, User
from app.models.base import MembershipState
from app.models.eoi import EoiDraft
from app.models.tenancy import Membership, Organization
from app.services import eoi_notes
from app.services import pursuit_analysis as analysis_service
from app.services.award_ledger import ingest_world_bank_awards
from app.services.eoi_document import document_text
from app.services.official_notice import sync_official_notices
from app.services.preview_replay import parse_replays, replay_marker, replay_text
from scripts import test_s0_5b4_baseline as support
from scripts.demo import prospect as previews
from scripts.demo import seed_demo
from scripts.demo.seed_demo import DemoSeedError, Options
from test_d3_04_demo_seed import DUTY, EXPERIENCE, SUBMISSION, _fake_analyzer, _inline, _note, _tender
from test_s1_6_ledger_preview import LEDGER, TODAY
from test_s1_award_ledger import HEAD, NOW, _pages

BODY = "\n".join((EXPERIENCE, SUBMISSION, DUTY))
FILLER = "Further information is available at the address below. "


def _notice(characters: int) -> str:
    return BODY + "\n" + FILLER * (characters // len(FILLER))


def test_replay_marker_round_trip() -> None:
    notes = f"[pv20261002-1] {replay_marker('world_bank:OP00460001', date(2026, 9, 20))} Plasma preview for X."
    assert parse_replays(notes) == {"world_bank:OP00460001": date(2026, 9, 20)}
    assert parse_replays(None) == {} and parse_replays("[pv20261002-1] Plasma preview") == {}
    assert replay_text(date(2026, 9, 20)) == "Replay on a closed notice (closed 2026-09-20) — for illustration"


def test_replay(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private"))
    monkeypatch.setattr(analysis_service.pursuit_analyzer, "analyze_pack_items", _fake_analyzer())

    async def no_provider(request):
        raise AssertionError("the seed passes its own note provider in tests")

    monkeypatch.setattr(eoi_notes, "gemini_note_call", no_provider)

    async def scenario() -> None:
        database = support.database_name("s1_8_replay")
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
    closed = datetime(2026, 9, 20, 17, 0, tzinfo=timezone.utc)
    tenders = {
        # open, Central Asian, 2,500-5,000 characters: analysed, kept only with >= 4 requirements (the fake extracts fewer)
        "open_short": _tender(61, title="Audit of the irrigation project accounts", country="Tajikistan", body=BODY,
                              description=_notice(3_500)),
        # closed 2026-09-20, published within 120 days, no stored official notice (it predates the sync)
        "closed": _tender(62, title="Audit of financial statements of the water project", country="Uzbekistan", body=BODY,
                          description=_notice(6_000), publication_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
                          deadline=closed),
        # published more than 120 days before the demo date
        "closed_old": _tender(63, title="Audit of the energy project", country="Uzbekistan", body=BODY,
                              description=_notice(6_000), publication_date=datetime(2026, 4, 1, tzinfo=timezone.utc),
                              deadline=datetime(2026, 5, 1, tzinfo=timezone.utc)),
        # closed, recent, but under 2,500 characters
        "closed_short": _tender(64, title="Audit of the roads project", country="Kazakhstan", body=BODY,
                                description=_notice(1_200), publication_date=datetime(2026, 9, 5, tzinfo=timezone.utc),
                                deadline=datetime(2026, 9, 25, tzinfo=timezone.utc)),
    }
    async with sessions() as db:
        await ingest_world_bank_awards(db, fetch=_pages(LEDGER)[0], countries=("Uzbekistan", "Kazakhstan"),
                                       since=date(2024, 10, 10), now=NOW, request_delay_seconds=0)
        db.add_all(tenders.values())
        await db.flush()
        await sync_official_notices(db, [tenders["open_short"], tenders["closed_old"], tenders["closed_short"]])
        db.add(User(google_id="google-subject-demo", email=seed_demo.DEMO_EMAIL, name="Plasma Support (demo)",
                    platform_role="pilot_user", approval_status=USER_APPROVAL_APPROVED))
        await db.commit()
        ids = {key: row.id for key, row in tenders.items()}
        assert await db.scalar(select(func.count(TenderDocument.id)).where(TenderDocument.tender_id == ids["closed"])) == 0
        prospect = await previews.prospect_from_ledger(db, "SAMARQAND AUDIT", country="Uzbekistan")

    # ---- pools: the open short notice first; the replay pool holds only the recent, long-enough closed REOI ----
    async with sessions() as db:
        pools = dict(await previews.candidate_pools(db, prospect, demo_date=TODAY, exclude=set(), replay_days=120))
        assert [item.tender.id for item in pools["open"]] == [ids["open_short"]]
        assert [item.tender.id for item in pools["replay"]] == [ids["closed"]]
        assert pools["replay"][0].__dict__["_closed_on"] == date(2026, 9, 20)
        assert (await previews.candidate_pools(db, prospect, demo_date=TODAY, exclude=set()))[1] == ("replay", [])
    plan = await previews.plan(sessions, Options(target="local", dry_run=True, replay_days=120), prospect, today=TODAY)
    assert plan["pool"] == "open" and plan["pursuit_tender"]["tender_id"] == str(ids["open_short"]) and plan["replay"] is None
    # a closed tender can be pinned only with replay on
    with pytest.raises(DemoSeedError, match="can no longer be seeded"):
        await previews.plan(sessions, Options(target="local", dry_run=True, externals=("world_bank:OP00990062",)),
                            prospect, today=TODAY)

    # ---- best of: the open short notice is analysed and refused (< 4 requirements), the replay is kept ----
    options = Options(target="local", confirm="SEED_DEMO", poll_seconds=0.05, analysis_timeout=60, candidates=3,
                      replay_days=120)
    result = await previews.seed_best_of(sessions, options, prospect, candidates=3, today=TODAY,
                                         process_inline=_inline, note_call=_note)
    first, second = result["candidates"]
    assert (first["pool"], first["status"], first["acceptable"], first["kept"]) == ("open", "open", False, False)
    assert first["notice_characters"] < 5_000 and first["requirements_extracted"] < 4
    assert (second["pool"], second["status"], second["acceptable"], second["kept"]) == ("replay", "closed 2026-09-20", True, True)
    label = replay_text(date(2026, 9, 20))
    assert result["kept"]["organization_name"] == f"SAMARQAND AUDIT — Plasma preview · {label}"
    table = previews.candidates_table(result)
    assert "closed 2026-09-20" in table and "no*" in table
    async with sessions() as db:
        # the replayed tender's official notice is stored now, as a refresh would
        assert await db.scalar(select(func.count(TenderDocument.id)).where(TenderDocument.tender_id == ids["closed"])) == 1
        user = await db.scalar(select(User).where(User.email == seed_demo.DEMO_EMAIL))
        active = (await db.scalars(select(Membership.organization_id).where(
            Membership.user_id == user.id, Membership.state == MembershipState.ACTIVE))).all()
        assert [str(value) for value in active] == [second["organization_id"]]  # the refused run is archived
        organization = await db.get(Organization, UUID(second["organization_id"]))
        assert organization.display_name.endswith(label)
        # the pursuit says it
        pursuit = await get_pursuit(UUID(second["pursuit_id"]), x_organization_id=organization.id, current_user=user, db=db)
        assert pursuit.replay_closed_on == date(2026, 9, 20)
        # and the EOI cover
        draft = await db.scalar(select(EoiDraft).where(EoiDraft.pursuit_id == UUID(second["pursuit_id"])))
        assert draft.manifest["replay_closed_on"] == "2026-09-20"
        text = document_text(draft.manifest)
        assert text[1] == label and "Draft — not reviewed by your team" in text
        # an open preview's pursuit carries no replay
        refused = await get_pursuit(UUID(first["pursuit_id"]), x_organization_id=UUID(first["organization_id"]),
                                    current_user=await _steward(db, UUID(first["organization_id"])), db=db)
        assert refused.replay_closed_on is None

    # ---- replay off: the open short notice is refused and nothing else qualifies ----
    with pytest.raises(previews.BestOfRefused, match="none of the 1 analysed candidates is acceptable"):
        await previews.seed_best_of(sessions, Options(target="local", confirm="SEED_DEMO", poll_seconds=0.05,
                                                      analysis_timeout=60, candidates=3), prospect, candidates=3,
                                    today=TODAY, process_inline=_inline, note_call=_note)


async def _steward(db, organization_id: UUID) -> User:
    from scripts.demo.seed_demo import _steward_membership

    membership = await _steward_membership(db, organization_id)
    return await db.get(User, membership.user_id)
