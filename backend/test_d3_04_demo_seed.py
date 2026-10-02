"""D3-04 demo seed: safety, reset model, content, idempotency (disposable PostgreSQL)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.endpoints.auth import PREPROVISIONED_GOOGLE_ID_PREFIX, _bound_google_id
from app.core.agents.pursuit_analyzer import ExtractedFact, NumericPredicate, VerifiedFact
from app.core.access import COMPANY_APPROVAL_APPROVED, USER_APPROVAL_APPROVED
from app.models.all_models import Tender, User
from app.models.base import MembershipRole, MembershipState, TenderStatus
from app.models.candidate_retrieval import CVVersion, Expert, Firm, ProjectReference
from app.models.company import CompanyProfile
from app.models.eoi import EoiDraft
from app.models.pursuit_analysis import AnalysisReviewAssertion, AnalysisRun
from app.models.tenancy import Membership, Organization, OrganizationPursuit
from app.services import eoi_notes
from app.services import pursuit_analysis as analysis_service
from app.services.eoi_notes import NoteRequest
from app.services.official_notice import sync_official_notices
from app.services.pursuit_analysis import get_analysis_run, process_analysis_run
from scripts import test_s0_5b4_baseline as support
from scripts.demo import demo_data, seed_demo
from scripts.demo.seed_demo import DemoSeedError, Options


HEAD = "20261005_0001_d2_05_eoi_drafts"
TODAY = date(2026, 10, 2)
EXPERIENCE = "The Consultant should have at least two completed contracts within the last 10 years involving detailed engineering design of substations."
SUBMISSION = "Expressions of interest must be delivered in written form by e-mail no later than 30 October 2026."
DUTY = "The Consultant shall prepare detailed engineering designs for 12 identified sub-projects."
COMMS_TABLES = ("notification_events", "notification_deliveries", "notification_outbox", "broadcasts", "broadcast_recipients")


# ---- pure ------------------------------------------------------------------------------------------

def test_target_must_match_the_environment_and_writes_need_confirmation() -> None:
    seed_demo.check_target("local", "development")
    seed_demo.check_target("production", "production")
    for target, environment in (("local", "production"), ("production", "development"), ("production", "release"), ("staging", "development")):
        with pytest.raises(DemoSeedError):
            seed_demo.check_target(target, environment)
    parser = seed_demo.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--dry-run"])  # --target is required
    with pytest.raises(DemoSeedError, match="SEED_DEMO"):
        asyncio.run(seed_demo.seed(None, Options(target="local", confirm="yes")))


def test_preprovisioned_record_is_bound_by_the_first_google_sign_in() -> None:
    assert _bound_google_id(SimpleNamespace(google_id=PREPROVISIONED_GOOGLE_ID_PREFIX + "support.plasma@gmail.com")) is None
    assert _bound_google_id(SimpleNamespace(google_id="1234567890")) == "1234567890"
    assert _bound_google_id(SimpleNamespace(google_id="plasma-demo-steward:20261002-1:not-a-google-account")) is not None


def test_demo_content_matches_the_brief() -> None:
    own = demo_data.OWN_REFERENCES
    assert len(own) == 18 and sum(item["evidence_state"] == "REVIEWED" for item in own) == 6
    assert {item["role"] for item in own} == {"LEAD", "JV_MEMBER", "SUBCONSULTANT"}
    assert min(item["start_date"] for item in own).year == 2012
    assert max(item["completion_date"] or item["start_date"] for item in own).year == 2025
    assert all(item["value_basis"] != "UNKNOWN" for item in own if item["contract_value"] is not None)
    assert {"Energy", "Water", "Transport", "Urban development"} <= {item["sector"] for item in own}
    assert all(any(bank in item["client_name"] for bank in ("World Bank", "ADB", "EBRD", "AIIB")) for item in own)
    assert len(demo_data.PARTNERS) == 6 and all(3 <= len(item["references"]) <= 5 for item in demo_data.PARTNERS)
    assert len(demo_data.EXPERTS) == 12 and len({item["display_name"] for item in demo_data.EXPERTS}) == 12


# ---- disposable database -------------------------------------------------------------------------

def _tender(number: int, *, title: str, country: str, body: str, **values) -> Tender:
    base = dict(
        source_system="world_bank", external_id=f"OP0099{number:04d}", canonical_source_key=f"world_bank:OP0099{number:04d}",
        source_url=f"https://projects.worldbank.org/notice/OP0099{number:04d}", title=title,
        description=body + "\n" + "Further information is available at the address below. " * 6,
        notice_type="Request for Expression of Interest", procurement_category="Consultant Services",
        buyer="Ministry of Energy", country=country, publication_date=datetime(2026, 9, 20, tzinfo=timezone.utc),
        deadline=datetime(2026, 10, 30, 17, 0, tzinfo=timezone.utc), budget=0, currency="USD",
        status=TenderStatus.OPEN, category="Other", source_metadata_json=None,
    )
    base.update(values)
    return Tender(**base)


async def _seed_tenders(sessions) -> dict[str, UUID]:
    body = "\n".join((EXPERIENCE, SUBMISSION, DUTY))
    rows = {
        "energy": _tender(1, title="Detailed design of substations for grid reinforcement", country="Mongolia", body=body),
        "water": _tender(2, title="Feasibility study for urban water supply", country="Uzbekistan", body=body,
                         deadline=datetime(2026, 11, 20, tzinfo=timezone.utc)),
        "goods": _tender(3, title="Supply of substation transformers", country="Uzbekistan", body=body, procurement_category="Goods"),
        "early": _tender(4, title="Transmission line design", country="Kazakhstan", body=body,
                         deadline=datetime(2026, 10, 5, tzinfo=timezone.utc)),
        "elsewhere": _tender(5, title="Power grid design", country="Georgia", body=body),
        "no_notice": _tender(6, title="Substation design", country="Tajikistan", body="Short.", description="Short."),
        "not_reoi": _tender(7, title="Substation supervision", country="Kyrgyz Republic", body=body, notice_type="Contract Award"),
    }
    async with sessions() as db:
        db.add_all(rows.values())
        await db.flush()
        await sync_official_notices(db, list(rows.values()))
        await db.commit()
    return {key: row.id for key, row in rows.items()}


async def _comms(db) -> dict[str, int]:
    return {table: await db.scalar(text(f"SELECT count(*) FROM {table}")) for table in COMMS_TABLES}


def _fake_analyzer():
    async def extracted(sealed, language):
        item = sealed[0]

        def fact(quote, **values):
            start = item.text.index(quote)
            base = dict(kind="CORPORATE_REQUIREMENT", original_quote=quote, normalized_text=quote, category="EXPERIENCE",
                        requirement_type="QUALIFICATION", stage_scope="EXPRESSION_OF_INTEREST", distinction="MANDATORY",
                        predicate=None)
            base.update(values)
            return VerifiedFact(item.pack_item_id, ExtractedFact(**base), start, start + len(quote), None,
                                item.text[:start].count("\n") + 1)

        return [
            fact(EXPERIENCE, predicate=NumericPredicate(operator=">=", threshold=2, unit="contracts")),
            fact(SUBMISSION, category="SUBMISSION", requirement_type="SUBMISSION_INSTRUCTION", stage_scope="SUBMISSION"),
            fact(DUTY, category="TECHNICAL", requirement_type="TECHNICAL", stage_scope="CONTRACT_EXECUTION"),
        ]

    return extracted


async def _note(request: NoteRequest) -> str:
    return f"The {request.reference['project_name']} assignment is recorded in the firm's experience."


async def _inline(db, run_id: UUID) -> None:
    await process_analysis_run(db, run_id, worker_id="d3-04-test")


async def _active_memberships(db, user_id: UUID) -> list[Membership]:
    return list((await db.scalars(select(Membership).where(
        Membership.user_id == user_id, Membership.state == MembershipState.ACTIVE))).all())


def test_demo_seed_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private"))
    monkeypatch.setattr(analysis_service.pursuit_analyzer, "analyze_pack_items", _fake_analyzer())

    async def no_provider(request):
        raise AssertionError("the seed passes its own note provider in tests")

    monkeypatch.setattr(eoi_notes, "gemini_note_call", no_provider)

    async def scenario() -> None:
        database = support.database_name("d3_04_demo_seed")
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
    tenders = await _seed_tenders(sessions)
    options = Options(target="local", confirm="SEED_DEMO", poll_seconds=0.05, analysis_timeout=60)

    # ---- dry run: the plan, no writes -----------------------------------------------------------
    async with sessions() as db:
        before = await db.scalar(text("SELECT count(*) FROM organizations")), await db.scalar(text("SELECT count(*) FROM users"))
    plan = await seed_demo.plan(sessions, Options(target="local", dry_run=True), today=TODAY)
    assert plan["label"] == "20261002-1" and plan["organization_name"] == "Demo Consulting LLC — 20261002-1"
    assert plan["demo_user_action"] == "create_preprovisioned" and plan["profile_mode"] == "OWN"
    assert plan["pursuit_b_tender"]["tender_id"] == str(tenders["energy"])  # most relevant first
    assert plan["pursuit_a_tender"]["tender_id"] == str(tenders["water"])
    async with sessions() as db:
        assert (await db.scalar(text("SELECT count(*) FROM organizations")), await db.scalar(text("SELECT count(*) FROM users"))) == before
    with pytest.raises(DemoSeedError, match="REOI"):
        await seed_demo.plan(sessions, Options(target="local", dry_run=True, tenders=(tenders["energy"], tenders["goods"])), today=TODAY)

    # ---- run 1 ------------------------------------------------------------------------------------
    async with sessions() as db:
        comms_before = await _comms(db)
    first = await seed_demo.seed(sessions, options, today=TODAY, process_inline=_inline, note_call=_note)
    assert first["label"] == "20261002-1" and first["profile_mode"] == "OWN" and first["revoked_in_older_organizations"] == []
    assert first["counts"] == {"own_references": 18, "own_references_reviewed": 6, "partner_firms": 6,
                               "partner_references": sum(len(item["references"]) for item in demo_data.PARTNERS),
                               "experts": 12, "cv_versions": 12}
    organization_id = UUID(first["organization_id"])
    async with sessions() as db:
        user = await db.scalar(select(User).where(User.email == seed_demo.DEMO_EMAIL))
        comms_after = await _comms(db)
        # No broadcasts; the only notification is the demo user's own account approval.
        unchanged = [key for key in COMMS_TABLES if key != "notification_outbox"]
        assert [comms_after[key] for key in unchanged] == [comms_before[key] for key in unchanged]
        outbox = (await db.execute(text("SELECT user_id, event_type FROM notification_outbox"))).all()
        assert [(row.user_id, row.event_type) for row in outbox] == [(user.id, "ACCOUNT_APPROVED")]
        assert user.google_id.startswith(PREPROVISIONED_GOOGLE_ID_PREFIX) and user.approval_status == USER_APPROVAL_APPROVED
        profile = await db.scalar(select(CompanyProfile).where(CompanyProfile.user_id == user.id))
        organization = await db.get(Organization, organization_id)
        assert organization.legacy_company_profile_id == profile.id and profile.approval_status == COMPANY_APPROVAL_APPROVED
        assert profile.notes.startswith(seed_demo.PROFILE_MARKER) and profile.target_countries == demo_data.PROFILE["target_countries"]
        members = (await db.execute(select(Membership.role, Membership.state, User.email).join(User, User.id == Membership.user_id)
                                    .where(Membership.organization_id == organization_id))).all()
        assert sorted((role, state, email) for role, state, email in members) == sorted([
            (MembershipRole.OWNER, MembershipState.ACTIVE, seed_demo.DEMO_EMAIL),
            (MembershipRole.OWNER, MembershipState.ACTIVE, seed_demo.steward_email("20261002-1")),
        ])
        # every record with a provenance field is tagged as demo
        firms = (await db.scalars(select(Firm).where(or_owner(organization_id)))).all()
        assert len(firms) == 7 and all(firm.source_provenance.get("demo") is True for firm in firms)
        references = (await db.scalars(select(ProjectReference).where(ProjectReference.firm_id.in_([firm.id for firm in firms])))).all()
        assert all(row.evidence_provenance.get("demo") is True for row in references)
        experts = (await db.scalars(select(Expert).where(Expert.owner_organization_id == organization_id))).all()
        assert all(row.source_provenance.get("demo") is True for row in experts)
        cvs = (await db.scalars(select(CVVersion).where(CVVersion.expert_id.in_([row.id for row in experts])))).all()
        assert len(cvs) == 12 and all(row.evidence_provenance.get("demo") is True for row in cvs)
        pursuits = (await db.scalars(select(OrganizationPursuit).where(OrganizationPursuit.organization_id == organization_id))).all()
        assert {row.source_tender_id for row in pursuits} == {tenders["energy"], tenders["water"]}
        # pursuit A untouched: no analysis
        assert await db.scalar(select(func.count(AnalysisRun.id)).where(AnalysisRun.pursuit_id == UUID(first["pursuit_a_id"]))) == 0
        analysis = await get_analysis_run(db, organization_id=organization_id, pursuit_id=UUID(first["pursuit_b_id"]),
                                          run_id=UUID(first["analysis"]["analysis_run_id"]))
        reviewed = [*analysis.requirements, *analysis.submission_and_notes]
        assert reviewed and all(item.effective_review_state == "CONFIRMED" for item in reviewed)
        assert all(gap.effective_review_state == "CONFIRMED" for gap in analysis.gaps if gap.requirement_id)
        reasons = set((await db.scalars(select(AnalysisReviewAssertion.reason).where(
            AnalysisReviewAssertion.analysis_run_id == analysis.analysis_run_id))).all())
        assert reasons == {f"Reviewed in bulk by {user.name}"}
        draft = await db.get(EoiDraft, UUID(first["eoi_draft_id"]))
        assert draft.language == "en" and draft.inputs["include_relevance_notes"] is True
        assert [item["role"] for item in draft.inputs["partners"]] == ["JV_MEMBER"]
        assert draft.manifest["criteria"] and all(DUTY != item["original_quote"] for item in draft.manifest["criteria"])
    assert first["eoi_summary"]["partner_count"] == 1 and first["eoi_summary"]["own_reference_count"] >= 1
    assert sorted(item["format"] for item in first["eoi_artifacts"]) == ["DOCX", "PDF"]

    # ---- resume: idempotent within a run ----------------------------------------------------------
    async with sessions() as db:
        rows_before = await _row_counts(db)
    resumed = await seed_demo.seed(sessions, Options(**{**options.__dict__, "resume": "20261002-1"}), today=TODAY,
                                   process_inline=None, note_call=_note)
    assert resumed["organization_id"] == first["organization_id"] and resumed["eoi_draft_id"] == first["eoi_draft_id"]
    assert resumed["eoi_reused"] is True and resumed["reviews"]["requirements_confirmed"] == 0
    async with sessions() as db:
        assert await _row_counts(db) == rows_before
    with pytest.raises(DemoSeedError, match="no organization"):
        await seed_demo.seed(sessions, Options(**{**options.__dict__, "resume": "20261002-9"}), today=TODAY)

    # ---- run 2: fresh organization, previous one handed to its steward ----------------------------
    second = await seed_demo.seed(sessions, options, today=TODAY, process_inline=_inline, note_call=_note)
    assert second["label"] == "20261002-2" and second["organization_id"] != first["organization_id"]
    assert second["revoked_in_older_organizations"] == [first["organization_id"]]
    assert len(second["profiles_handed_off"]) == 1
    async with sessions() as db:
        user = await db.scalar(select(User).where(User.email == seed_demo.DEMO_EMAIL))
        active = await _active_memberships(db, user.id)
        assert [str(item.organization_id) for item in active] == [second["organization_id"]]
        old = await db.get(Organization, organization_id)
        old_profile = await db.get(CompanyProfile, old.legacy_company_profile_id)
        steward = await db.scalar(select(User).where(User.email == seed_demo.steward_email("20261002-1")))
        assert old_profile.user_id == steward.id  # the old organization keeps an owner and its profile
        assert [item.role for item in await _active_memberships(db, steward.id)] == [MembershipRole.OWNER]
        new_profile = await db.scalar(select(CompanyProfile).where(CompanyProfile.user_id == user.id))
        assert new_profile.company_name == "Demo Consulting LLC — 20261002-2"
        assert user.auth_version >= 1

    # ---- a user with their own (non-demo) company keeps it ------------------------------------------
    async with sessions() as db:
        owner = User(google_id="real-google-subject", email="someone@example.com", name="Someone",
                     approval_status=USER_APPROVAL_APPROVED, platform_role="pilot_user")
        db.add(owner)
        await db.flush()
        real = CompanyProfile(user_id=owner.id, company_name="Real Company LLC", approval_status=COMPANY_APPROVAL_APPROVED)
        db.add(real)
        await db.commit()
        real_id = real.id
    member = await seed_demo.seed(sessions, Options(**{**options.__dict__, "email": "someone@example.com"}), today=TODAY,
                                  process_inline=_inline, note_call=_note)
    assert member["profile_mode"] == "MEMBER" and member["label"] == "20261002-3"
    async with sessions() as db:
        assert (await db.scalar(select(CompanyProfile).where(CompanyProfile.user_id == owner.id))).id == real_id
        organization = await db.get(Organization, UUID(member["organization_id"]))
        demo_profile = await db.get(CompanyProfile, organization.legacy_company_profile_id)
        steward = await db.scalar(select(User).where(User.email == seed_demo.steward_email("20261002-3")))
        assert demo_profile.user_id == steward.id
        roles = {(row.user_id, row.role, row.state) for row in (await db.scalars(select(Membership).where(
            Membership.organization_id == organization.id))).all()}
        assert (owner.id, MembershipRole.OWNER, MembershipState.ACTIVE) in roles
        # the support user's newest demo organization is untouched by someone else's run
        support_user = await db.scalar(select(User).where(User.email == seed_demo.DEMO_EMAIL))
        assert [str(item.organization_id) for item in await _active_memberships(db, support_user.id)] == [second["organization_id"]]


def or_owner(organization_id: UUID):
    return (Firm.organization_id == organization_id) | ((Firm.owner_organization_id == organization_id) & Firm.organization_id.is_(None))


async def _row_counts(db) -> dict[str, int]:
    tables = ("users", "organizations", "memberships", "company_profiles", "candidate_firms", "candidate_project_references", "candidate_experts",
              "candidate_cv_versions", "organization_pursuits", "pursuit_analysis_runs", "pursuit_analysis_review_assertions", "eoi_drafts")
    return {table: await db.scalar(text(f"SELECT count(*) FROM {table}")) for table in tables}
