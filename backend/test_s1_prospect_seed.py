"""S1 prospect preview seed: file validation, public-records marking, matching REOI, EOI v1,
exclusive previews by default (coexisting with --keep-others), ledger-backed previews (awards only), the
"Draft — not reviewed by your team" EOI status, archive, and no contact with anyone (disposable PostgreSQL)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.access import USER_APPROVAL_APPROVED
from app.models.all_models import User
from app.models.base import MembershipRole, MembershipState
from app.models.candidate_retrieval import CVVersion, Expert, Firm, ProjectReference
from app.models.company import CompanyProfile
from app.models.eoi import EoiDraft
from app.models.pursuit_analysis import AnalysisRun
from app.models.tenancy import Membership, Organization, OrganizationPursuit
from app.services import eoi_notes
from app.services import pursuit_analysis as analysis_service
from app.services.eoi_document import document_text
from app.services.official_notice import sync_official_notices
from scripts import test_s0_5b4_baseline as support
from scripts.demo import prospect as previews
from scripts.demo import seed_demo
from scripts.demo.seed_demo import DemoSeedError, Options
from test_d3_04_demo_seed import DUTY, EXPERIENCE, HEAD, SUBMISSION, _comms, _fake_analyzer, _inline, _note, _tender

TODAY = date(2026, 10, 2)
EXAMPLE = Path(__file__).parent / "scripts" / "demo" / "prospect.example.json"


def _example(**changes) -> dict:
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    raw.update(changes)
    return raw


def _write(tmp_path, raw: dict) -> Path:
    path = tmp_path / f"prospect-{uuid4().hex[:6]}.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


# ---- pure ------------------------------------------------------------------------------------------

def test_example_file_is_valid_and_names_the_preview() -> None:
    prospect = previews.load_prospect(EXAMPLE)
    assert prospect.organization_name == "Example Water Engineering LLC — Plasma preview"
    assert 3 <= len(prospect.references) <= 8 and all(str(item.source_url).startswith("https://") for item in prospect.references)


@pytest.mark.parametrize(("change", "message"), [
    ({"contact_email": "ceo@example.org"}, "contact_email"),  # contact details are refused, not stored
    ({"references": _example()["references"][:2]}, "references"),
    ({"references": _example()["references"] * 3}, "references"),
    ({"references": [{**item, "source_url": "not a url"} for item in _example()["references"]]}, "source_url"),
    ({"references": [{k: v for k, v in item.items() if k != "source_url"} for item in _example()["references"]]}, "source_url"),
    ({"references": [{**item, "completion_date": "June 2021"} for item in _example()["references"]]}, "YYYY"),
    ({"references": [{**_example()["references"][0], "contract_value": 100000}, *_example()["references"][1:]]}, "contract_currency"),
    ({"references": [_example()["references"][0]] * 3}, "distinct"),
    ({"firm_name": "Example LLC — Plasma preview"}, "preview suffix"),
    ({"sectors": []}, "sectors"),
])
def test_invalid_prospect_files_are_refused(tmp_path, change, message) -> None:
    with pytest.raises(DemoSeedError, match=message):
        previews.load_prospect(_write(tmp_path, _example(**change)))


def test_records_are_marked_public_and_unverified() -> None:
    prospect = previews.load_prospect(EXAMPLE)
    first, second = (previews.reference_values(item, "pv20261002-1") for item in prospect.references[:2])
    for row, item in ((first, prospect.references[0]), (second, prospect.references[1])):
        url = str(item.source_url)
        assert row["evidence_state"] == "UNVERIFIED"
        assert row["evidence_provenance"] == {"demo": True, "seed": "s1-prospect", "run": "pv20261002-1", "origin": "public_records",
                                              "verification": "unverified", "note": "From public records, unverified.",
                                              "source_url": url}
        assert row["relevant_scope"].endswith(f"From public records, unverified. Source: {url}")
    # partial dates: a start takes the first day, a completion the last; values need a currency
    assert (first["start_date"], first["completion_date"]) == (date(2019, 3, 1), date(2021, 12, 31))
    assert second["completion_date"] == date(2023, 11, 30) and second["value_basis"] == "UNKNOWN"
    assert previews._partial_date("2024-02", end=True) == date(2024, 2, 29)
    firm = previews.self_firm_values(prospect, "pv20261002-1")
    assert firm["evidence_state"] == "UNVERIFIED" and firm["private_notes"].startswith("Plasma preview. From public records, unverified.")
    assert set(firm["source_provenance"]["sources"]) == {str(item.source_url) for item in prospect.references}
    expert, cv = previews.expert_values(prospect.experts[0], "pv20261002-1")
    assert expert["evidence_state"] == cv["evidence_state"] == "UNVERIFIED" and expert["source_provenance"]["origin"] == "public_records"
    # nothing the file does not state is invented for the company profile
    assert set(previews.profile_values(prospect)) == {"industry", "target_regions", "target_countries", "target_services"}


def test_prospect_matching_is_by_whole_words() -> None:
    keywords = previews.sector_keywords(previews.load_prospect(EXAMPLE))
    assert seed_demo._sectors("Ports/Waterways", keywords, whole_words=True) == ()
    assert seed_demo._sectors("Ports/Waterways", keywords) != ()  # the D3-04 substring rule is unchanged
    assert seed_demo._sectors("Rural water supplies", keywords, whole_words=True) == ("Water supply and sanitation", "Irrigation")
    services = previews.service_keywords(previews.load_prospect(EXAMPLE))
    assert services == {"Engineering design": ("design", "engineering"), "Construction supervision": ("construction", "supervision"),
                        "Feasibility studies": ("feasibility", "studies")}


def test_sector_keywords_follow_the_stated_sectors() -> None:
    keywords = previews.sector_keywords(previews.load_prospect(EXAMPLE))
    assert set(keywords) == {"Water supply and sanitation", "Irrigation"}
    assert {"water", "wastewater", "sanitation", "irrigation", "supply"} <= set(keywords["Water supply and sanitation"])
    assert "irrigation" in keywords["Irrigation"] and "substation" not in {w for words in keywords.values() for w in words}


def test_cli_options() -> None:
    parser = seed_demo.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--target", "local", "--prospect-file", "a.json", "--archive-preview", str(uuid4())])
    with pytest.raises(SystemExit):
        parser.parse_args(["--target", "local", "--archive-preview", "not-a-uuid"])
    args = parser.parse_args(["--target", "local", "--prospect-file", "a.json"])
    assert args.analysis_timeout is None  # main() applies the prospect default
    assert previews.DEFAULT_ANALYSIS_TIMEOUT < 600
    assert previews.is_prospect_label("pv20261002-1") and not previews.is_prospect_label("20261002-1")


# ---- disposable database -------------------------------------------------------------------------

async def _seed_tenders(sessions) -> dict[str, UUID]:
    body = "\n".join((EXPERIENCE, SUBMISSION, DUTY))
    rows = {
        "water_home": _tender(21, title="Design of water supply and sanitation systems", country="Uzbekistan", body=body,
                              deadline=datetime(2026, 10, 25, tzinfo=timezone.utc)),
        "water_abroad": _tender(22, title="Design of water supply and sanitation systems", country="Kazakhstan", body=body,
                                deadline=datetime(2026, 11, 25, tzinfo=timezone.utc)),
        "irrigation": _tender(23, title="Irrigation scheme rehabilitation supervision", country="Kazakhstan", body=body),
        "energy": _tender(24, title="Detailed design of substations", country="Uzbekistan", body=body),
        "water_ifb": _tender(25, title="Water supply and sanitation design services", country="Uzbekistan", body=body,
                             notice_type="Invitation for Bids"),
        # two of the firm's services in the title (feasibility, design) outrank the home country
        "feasibility": _tender(26, title="Feasibility study and detailed design of water supply", country="Kazakhstan", body=body,
                               deadline=datetime(2026, 10, 20, tzinfo=timezone.utc)),
        # "water" is a whole word: Ports/Waterways is no match
        "waterways": _tender(27, title="Port community system", country="Uzbekistan", body=body, sector="Ports/Waterways"),
        # the project-sector field counts with the notice text, after every title match
        "sector_only": _tender(28, title="Institutional framework consultancy", country="Uzbekistan", body=body,
                               sector="Irrigation and Drainage; Water Supply"),
    }
    async with sessions() as db:
        db.add_all(rows.values())
        await db.flush()
        await sync_official_notices(db, list(rows.values()))
        await db.commit()
    return {key: row.id for key, row in rows.items()}


def test_prospect_preview_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private"))
    monkeypatch.setattr(analysis_service.pursuit_analyzer, "analyze_pack_items", _fake_analyzer())

    async def no_provider(request):
        raise AssertionError("the seed passes its own note provider in tests")

    monkeypatch.setattr(eoi_notes, "gemini_note_call", no_provider)

    async def scenario() -> None:
        database = support.database_name("s1_prospect_seed")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                await _flow(sessions, tmp_path)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _flow(sessions, tmp_path) -> None:
    tenders = await _seed_tenders(sessions)
    prospect = previews.load_prospect(EXAMPLE)
    options = Options(target="local", confirm="SEED_DEMO", poll_seconds=0.05, analysis_timeout=60)

    # ---- the demo account must already exist: the prospect seed never creates or approves one ----
    with pytest.raises(DemoSeedError, match="never creates or approves"):
        await previews.seed(sessions, options, prospect, today=TODAY, process_inline=_inline, note_call=_note)
    async with sessions() as db:
        assert await db.scalar(select(func.count(User.id))) == 0 and await db.scalar(text("SELECT count(*) FROM organizations")) == 0
        db.add(User(google_id="google-subject-demo", email=seed_demo.DEMO_EMAIL, name="Plasma Support (demo)",
                    platform_role="pilot_user", approval_status=USER_APPROVAL_APPROVED))
        await db.commit()

    # ---- dry run: the matching REOI, home country first; no writes -------------------------------
    plan = await previews.plan(sessions, Options(target="local", dry_run=True), prospect, today=TODAY)
    assert plan["label"] == "pv20261002-1" and plan["organization_name"] == prospect.organization_name
    assert plan["contacts_anyone"] is False and plan["demo_user_ready"] is True
    shown = [item["tender_id"] for item in plan["candidates"]]
    # sector words in the title, then service words in the title, then project sectors/text, then the firm's
    # country, then latest deadline; energy, the IFB and Ports/Waterways never match
    assert shown == [str(tenders[key]) for key in ("feasibility", "water_home", "water_abroad", "irrigation", "sector_only")], shown
    assert plan["candidates"][0]["reasons"]["service_match_title"] == ["Engineering design", "Feasibility studies"]
    assert plan["pursuit_tender"]["tender_id"] == str(tenders["feasibility"])
    async with sessions() as db:
        assert await db.scalar(text("SELECT count(*) FROM organizations")) == 0
    pinned = await previews.plan(sessions, Options(target="local", dry_run=True, externals=("world_bank:OP00990024",)), prospect, today=TODAY)
    assert str(tenders["energy"]) not in shown
    assert pinned["pursuit_tender"]["tender_id"] == str(tenders["energy"])
    with pytest.raises(DemoSeedError, match="at most once"):
        await previews.plan(sessions, Options(target="local", dry_run=True, externals=("world_bank:OP00990021", "world_bank:OP00990022")),
                            prospect, today=TODAY)
    unmatched = previews.load_prospect(_write(tmp_path, _example(sectors=["Fisheries"])))
    with pytest.raises(DemoSeedError, match="matches the sectors"):
        await previews.plan(sessions, Options(target="local", dry_run=True), unmatched, today=TODAY)

    # ---- seed --------------------------------------------------------------------------------------
    async with sessions() as db:
        comms_before = await _comms(db)
    first = await previews.seed(sessions, options, prospect, today=TODAY, process_inline=_inline, note_call=_note)
    assert first["label"] == "pv20261002-1" and first["contacts_anyone"] is False
    assert first["counts"] == {"own_references": 3, "experts": 1, "cv_versions": 1}
    assert first["eoi_version"] == 1 and sorted(item["format"] for item in first["eoi_artifacts"]) == ["DOCX", "PDF"]
    assert first["total_seconds"] < 600 and set(first["timings_seconds"]) == {"plan", "archive_other_previews", "organization_and_records", "analysis",
                                                                  "review_and_eoi"}
    organization_id = UUID(first["organization_id"])
    async with sessions() as db:
        # nobody is contacted: no notification, delivery, outbox row or broadcast at all
        assert await _comms(db) == comms_before
        user = await db.scalar(select(User).where(User.email == seed_demo.DEMO_EMAIL))
        assert await db.scalar(select(func.count(User.id))) == 2  # the demo user and this run's steward
        organization = await db.get(Organization, organization_id)
        profile = await db.get(CompanyProfile, organization.legacy_company_profile_id)
        assert organization.display_name == "Example Water Engineering LLC — Plasma preview"
        steward = await db.scalar(select(User).where(User.email == seed_demo.steward_email("pv20261002-1")))
        assert profile.user_id == steward.id and profile.created_by_user_id == user.id
        assert '"seed": "s1-prospect"' in profile.notes and "From public records, unverified." in profile.notes
        assert profile.director_name is None and profile.phone_contact is None and profile.target_countries == ["Uzbekistan"]
        members = (await db.execute(select(Membership.role, Membership.state, Membership.user_id)
                                    .where(Membership.organization_id == organization_id))).all()
        assert sorted((str(r), str(s), str(u)) for r, s, u in members) == sorted(
            (str(MembershipRole.OWNER), str(MembershipState.ACTIVE), str(uid)) for uid in (user.id, steward.id))
        firm = await db.scalar(select(Firm).where(Firm.organization_id == organization_id))
        assert firm.display_name == "Example Water Engineering LLC" and firm.evidence_state == "UNVERIFIED"
        assert firm.source_provenance["origin"] == "public_records"
        references = (await db.scalars(select(ProjectReference).where(ProjectReference.firm_id == firm.id))).all()
        assert len(references) == 3 and all(row.evidence_state == "UNVERIFIED" for row in references)
        assert all(row.evidence_provenance["source_url"] in row.relevant_scope for row in references)
        expert = await db.scalar(select(Expert).where(Expert.owner_organization_id == organization_id))
        assert expert.source_provenance["verification"] == "unverified"
        assert await db.scalar(select(func.count(CVVersion.id)).where(CVVersion.expert_id == expert.id)) == 1
        pursuits = (await db.scalars(select(OrganizationPursuit).where(OrganizationPursuit.organization_id == organization_id))).all()
        assert [row.source_tender_id for row in pursuits] == [tenders["feasibility"]]
        run = await db.get(AnalysisRun, UUID(first["analysis"]["analysis_run_id"]))
        assert run.status == "COMPLETED"
        draft = await db.get(EoiDraft, UUID(first["eoi_draft_id"]))
        assert draft.version == 1 and draft.inputs["partners"] == []
        # the bulk review confirmation is a seed step, not a human review: the cover and status say so
        assert draft.manifest["draft_status"] == "NOT_REVIEWED_BY_TEAM" and first["eoi_draft_status"] == "NOT_REVIEWED_BY_TEAM"
        assert document_text(draft.manifest)[:2] == ["Expression of Interest", "Draft — not reviewed by your team"]

    # ---- an active preview with the same name is refused; --resume is idempotent ------------------
    with pytest.raises(DemoSeedError, match="already exists"):
        await previews.seed(sessions, options, prospect, today=TODAY, process_inline=_inline, note_call=_note)
    async with sessions() as db:
        before = await _row_counts(db)
    resumed = await previews.seed(sessions, Options(**{**options.__dict__, "resume": "pv20261002-1"}), prospect, today=TODAY,
                                  process_inline=None, note_call=_note)
    assert resumed["organization_id"] == first["organization_id"] and resumed["eoi_reused"] is True
    async with sessions() as db:
        assert await _row_counts(db) == before
    with pytest.raises(DemoSeedError, match="no prospect preview"):
        await previews.seed(sessions, Options(**{**options.__dict__, "resume": "pv20261002-9"}), prospect, today=TODAY)

    # ---- a second prospect with --keep-others: previews coexist for the demo user ------------------
    other = previews.load_prospect(_write(tmp_path, _example(firm_name="Second Example Hydro LLC")))
    second = await previews.seed(sessions, Options(**{**options.__dict__, "keep_others": True}), other, today=TODAY,
                                 process_inline=_inline, note_call=_note)
    assert second["archived_other_previews"] == []
    assert second["label"] == "pv20261002-2"
    async with sessions() as db:
        active = (await db.scalars(select(Membership.organization_id).where(
            Membership.user_id == user.id, Membership.state == MembershipState.ACTIVE))).all()
        assert set(active) == {organization_id, UUID(second["organization_id"])}
    listed = await previews.list_previews(sessions)
    assert [(row["name"], row["archived"]) for row in listed] == [
        ("Example Water Engineering LLC — Plasma preview", False), ("Second Example Hydro LLC — Plasma preview", False)]

    # ---- archive ------------------------------------------------------------------------------------
    with pytest.raises(DemoSeedError, match="--confirm"):
        await previews.archive(sessions, organization_id=organization_id, confirm="", today=TODAY)
    with pytest.raises(DemoSeedError, match="not a prospect preview"):
        await previews.archive(sessions, organization_id=uuid4(), confirm="SEED_DEMO", today=TODAY)
    archived = await previews.archive(sessions, organization_id=organization_id, confirm="SEED_DEMO", today=TODAY)
    assert archived["name"] == "Example Water Engineering LLC — Plasma preview (archived 2026-10-02)"
    assert archived["revoked_user_ids"] == [str(user.id)] and archived["already_archived"] is False
    again = await previews.archive(sessions, organization_id=organization_id, confirm="SEED_DEMO", today=TODAY)
    assert again["already_archived"] is True and again["revoked_user_ids"] == []
    async with sessions() as db:
        assert (await db.scalars(select(Membership.organization_id).where(
            Membership.user_id == user.id, Membership.state == MembershipState.ACTIVE))).all() == [UUID(second["organization_id"])]
        assert await db.scalar(select(func.count(ProjectReference.id)).where(ProjectReference.firm_id == firm.id)) == 3  # records kept
        assert await _comms(db) == comms_before
    assert [row["archived"] for row in await previews.list_previews(sessions)] == [True, False]
    # once archived, the same firm can be previewed again; exclusive by default: the second preview is archived
    third = await previews.seed(sessions, options, prospect, today=TODAY, process_inline=_inline, note_call=_note)
    assert third["label"] == "pv20261002-3" and third["organization_id"] != first["organization_id"]
    assert [item["organization_id"] for item in third["archived_other_previews"]] == [second["organization_id"]]
    async with sessions() as db:
        assert (await db.scalars(select(Membership.organization_id).where(
            Membership.user_id == user.id, Membership.state == MembershipState.ACTIVE))).all() == [UUID(third["organization_id"])]


async def _row_counts(db) -> dict[str, int]:
    tables = ("users", "organizations", "memberships", "company_profiles", "candidate_firms", "candidate_project_references",
              "candidate_experts", "candidate_cv_versions", "organization_pursuits", "pursuit_analysis_runs",
              "pursuit_analysis_review_assertions", "eoi_drafts")
    return {table: await db.scalar(text(f"SELECT count(*) FROM {table}")) for table in tables}

