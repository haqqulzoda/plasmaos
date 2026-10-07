"""D2-01 the organization's own firm, own experience in analysis, and submission/notes.

Pure rules first, then the migration, then one Postgres scenario that drives the
self-firm endpoints, reference edits, W5/W7 exclusions and a W4 analysis run.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.endpoints import candidates as candidate_endpoints
from app.core.agents import pursuit_analyzer
from app.core.agents.pursuit_analyzer import ExtractedFact, NumericPredicate, VerifiedFact
from app.main import app
from app.models.all_models import TenderDocument
from app.models.base import TenderEngagementOrigin, TenderEngagementStatus
from app.models.candidate_retrieval import CandidateMatch, Firm, ProjectReference
from app.models.pursuit_analysis import AnalysisCompanySnapshot, AnalysisPackItem, AnalysisRun, PursuitGap, PursuitRequirement
from app.models.user import User
from app.schemas.candidate_retrieval import (
    CandidateReviewRequest,
    CandidateSearchRequest,
    FirmCreateRequest,
    ProjectReferenceCreateRequest,
    ProjectReferenceUpdateRequest,
    SelfFirmUpsertRequest,
)
from app.schemas.participation import ParticipationStartRequest
from app.schemas.team_scenarios import TeamScenarioCreateRequest
from app.schemas.tenancy import AnalysisReviewAssertionRequest, PursuitAnalysisStartRequest
from app.services import pursuit_analysis as analysis_service
from app.services.candidate_retrieval import (
    append_candidate_review,
    create_candidate_search,
    create_firm,
    create_project_reference,
    list_candidate_library,
    reference_evidence_basis,
)
from app.services.memberships import activate_invitation, invite_member, revoke_membership
from app.services.own_experience import (
    is_experience_requirement,
    match_own_references,
    note_kind,
    recency_window_years,
    terms,
)
from app.services.participation import start_participation
from app.services.private_documents import build_analysis_pack_candidate
from app.services.pursuit_analysis import (
    _assess_requirement,
    _coverage_for_requirement,
    append_review_assertion,
    create_analysis_run,
    get_analysis_run,
    process_analysis_run,
)
from app.services.pursuits import get_or_create_source_pursuit
from app.services.team_scenarios import TeamScenarioEligibilityError, create_team_scenario
from scripts import test_s0_5b4_baseline as support
from test_w2_organization_pursuit_foundation import W1_HEAD, _seed_w1


D1_03_HEAD = "20261003_0001_d1_03_official_notice_unique"
HEAD = "20261005_0001_d2_05_eoi_drafts"
AS_OF = date(2026, 9, 30)
SUBSTATION = (
    "Successful completion of at least two contracts within the last 10 years involving detailed "
    "engineering designs for substations and overhead transmission lines."
)


def _reference(**values):
    base = {
        "id": str(uuid4()), "project_name": "Substation design Navoi", "client_name": "National Grid",
        "country": "Uzbekistan", "sector": "Energy", "service": "Engineering design", "role": "LEAD",
        "start_date": "2019-01-01", "completion_date": "2021-06-30", "completion_state": "COMPLETED",
        "contract_value": None, "contract_currency": None, "value_basis": "UNKNOWN",
        "relevant_scope": "Detailed design of 220 kV substations", "evidence_state": "UNVERIFIED",
        "evidence_basis": "METADATA_ONLY",
    }
    base.update(values)
    return base


def _fact(**values) -> ExtractedFact:
    base = dict(
        kind="CORPORATE_REQUIREMENT", original_quote=SUBSTATION, normalized_text=SUBSTATION,
        category="EXPERIENCE", requirement_type="QUALIFICATION", stage_scope="EXPRESSION_OF_INTEREST",
        distinction="MANDATORY", predicate=NumericPredicate(operator=">=", threshold=2, unit="contracts"),
    )
    base.update(values)
    return ExtractedFact(**base)


# ---- pure rules -----------------------------------------------------------------------------------

def test_informational_statements_and_submission_instructions_are_notes() -> None:
    assert note_kind("INFORMATIONAL", "EVALUATION_CRITERIA") == "INFORMATIONAL"
    for value in ("SUBMISSION_INSTRUCTION", "Submission Deadline", "submission-manner", "SUBMISSION_METHOD"):
        assert note_kind("MANDATORY", value) == "SUBMISSION_INSTRUCTION", value
    # A document the bidder must provide is not an instruction, whatever the model calls it.
    for value in ("SUBMISSION_REQUIREMENT", "Submission Artifact", "REFERENCES", "DOCUMENTATION", ""):
        assert note_kind("MANDATORY", value) is None, value
    assert note_kind("SCORED", "QUALIFICATION") is None

    snapshot = {"readiness_documents": [], "own_project_references": [_reference()]}
    informational = _fact(
        original_quote="Key Experts will not be evaluated during the shortlisting stage.",
        normalized_text="Key Experts will not be evaluated during the shortlisting stage.",
        category="PERSONNEL", requirement_type="EVALUATION_CRITERIA", stage_scope="SHORTLISTING",
        distinction="INFORMATIONAL", predicate=None,
    )
    submission = _fact(
        original_quote="Expressions of interest must be delivered in written form via e-mail no later than 16 October.",
        normalized_text="Expressions of interest must be delivered by e-mail by 16 October.",
        category="SUBMISSION", requirement_type="SUBMISSION_DEADLINE", stage_scope="SUBMISSION", predicate=None,
    )
    for fact, kind in ((informational, "INFORMATIONAL"), (submission, "SUBMISSION_INSTRUCTION")):
        assessment = _assess_requirement(fact, snapshot, as_of=AS_OF)
        assert (assessment.coverage, assessment.note_kind, assessment.matched_reference_ids) == ("NOT_APPLICABLE", kind, ())
    # A later-stage duty stays a later-stage duty even when it is informational.
    later = informational.model_copy(update={"stage_scope": "POST_AWARD_OBLIGATION"})
    assert _coverage_for_requirement(later, snapshot)[0] == "LATER_STAGE_OBLIGATION"


def test_experience_requirements_are_recognized_by_label_or_wording() -> None:
    # D2 analysis quality narrowed the scope: "EXPERIENCE" alone, or a references list, is not
    # enough; the label or the statement must ask for similar assignments or a track record.
    assert not is_experience_requirement("EXPERIENCE", "QUALIFICATION", "")
    assert is_experience_requirement("Corporate Experience", "References", "")
    assert not is_experience_requirement("SUBMISSION_REQUIREMENT", "REFERENCES", "")
    assert is_experience_requirement("QUALIFICATION", "TRACK_RECORD", "")
    assert is_experience_requirement("ELIGIBILITY", "SIMILAR_ASSIGNMENTS", "")
    assert is_experience_requirement("QUALIFICATION", "OTHER", "The firm shall have experience in energy projects.")
    assert not is_experience_requirement("TERMS_OF_REFERENCE", "SCOPE", "Prepare designs.")
    assert not is_experience_requirement("LEGAL", "CERTIFICATION", "The firm must hold valid licenses.")


def test_words_match_whole_words_only() -> None:
    assert "substation" in terms("designs for Substations")  # plural folded, case folded
    assert "design" in terms("designs")
    assert "design" not in terms("redesigned")
    assert not terms("IT")  # shorter than three letters
    assert recency_window_years(SUBSTATION) == 10
    assert recency_window_years("in the past ten (10) years") == 10
    assert recency_window_years("during the last five years") == 5
    assert recency_window_years("at least two contracts") is None


def test_own_references_match_deterministically_and_never_prove_the_requirement() -> None:
    relevant = _reference(project_name="Substation design Navoi")
    water = _reference(project_name="Water network design", sector="Water", service="Water supply design",
                       relevant_scope="Design of water distribution networks")
    too_old = _reference(project_name="Transmission line design Andijan", completion_date="2012-05-01",
                         relevant_scope="Design of overhead transmission lines")
    ongoing = _reference(project_name="Substation upgrade Samarkand", completion_state="ONGOING",
                         completion_date=None)
    undated = _reference(project_name="Substation design Bukhara", completion_date=None)
    references = [relevant, water, too_old, ongoing, undated]
    match = match_own_references(
        text=SUBSTATION, predicate={"operator": ">=", "threshold": 2, "unit": "contracts"},
        references=references, as_of=AS_OF,
    )
    # One shared activity word ("design") does not make a water reference relevant.
    assert match.reference_ids == [relevant["id"], undated["id"]]
    reasons = {item["id"]: reason for item, reason in match.excluded}
    assert "outside the 10-year window" in reasons[too_old["id"]]
    assert "ongoing" in reasons[ongoing["id"]]
    rationale = match.rationale()
    assert "Substation design Navoi" in rationale and "Water network design" not in rationale.split("Not counted")[0]
    assert "the count of 2 is met by recorded references only" in rationale
    assert "completion date not recorded for Substation design Bukhara" in rationale
    assert "not verified" in rationale and "reviewer must confirm" in rationale

    # One reference against a count of two: named as still unproven.
    single = match_own_references(
        text=SUBSTATION, predicate={"operator": ">=", "threshold": 2, "unit": "contracts"},
        references=[relevant], as_of=AS_OF,
    )
    assert "1 of the 2 required comparable references are recorded" in single.rationale()

    # Lead-only role and a named region are conditions a recorded fact can contradict.
    lead_text = "Experience as lead consultant in at least one substation design contract in Central Asia."
    member = _reference(project_name="Substation design Osh", role="JV_MEMBER", country="Kyrgyzstan")
    outside = _reference(project_name="Substation design Ulaanbaatar", country="Mongolia")
    unknown_role = _reference(project_name="Substation design Almaty", role="UNKNOWN", country="Kazakhstan")
    lead = match_own_references(text=lead_text, predicate=None, references=[member, outside, unknown_role], as_of=AS_OF)
    assert lead.reference_ids == [unknown_role["id"]]
    assert "role not recorded for Substation design Almaty" in lead.rationale()
    assert any("outside the country or region" in reason for _, reason in lead.excluded)

    assert match_own_references(text=SUBSTATION, predicate=None, references=[water], as_of=AS_OF).matched == []

    snapshot = {"readiness_documents": [], "own_project_references": references}
    partial = _assess_requirement(_fact(), snapshot, as_of=AS_OF)
    assert partial.coverage == "PARTIAL" and list(partial.matched_reference_ids) == [relevant["id"], undated["id"]]
    assert partial.rationale.startswith("Own experience: 2 recorded project reference(s)")
    complex_rule = _assess_requirement(_fact(complex_rule=True), snapshot, as_of=AS_OF)
    assert complex_rule.coverage == "NEEDS_INTERPRETATION" and complex_rule.matched_reference_ids
    assert "Own experience" in complex_rule.rationale
    license_fact = _fact(
        original_quote="The firm must hold valid licenses for substation design.",
        normalized_text="Valid licenses for substation design", category="LEGAL", requirement_type="CERTIFICATION",
        predicate=None,
    )
    assert _assess_requirement(license_fact, snapshot, as_of=AS_OF).coverage == "EVIDENCE_MISSING"
    assert _coverage_for_requirement(_fact(), {"readiness_documents": []})[0] == "EVIDENCE_MISSING"
    for fact in (_fact(), _fact(complex_rule=True), license_fact):
        assert _assess_requirement(fact, snapshot, as_of=AS_OF).coverage != "SUPPORTED"


def test_evidence_basis_prompt_and_contract() -> None:
    assert reference_evidence_basis({}) == "METADATA_ONLY"
    assert reference_evidence_basis({"source": "completion record"}) == "METADATA_ONLY"
    assert reference_evidence_basis({"document_reference": "certificate.pdf"}) == "FILE_BACKED"
    prompt = " ".join(pursuit_analyzer.SYSTEM_PROMPT.split())
    assert "Use requirement_type=SUBMISSION_INSTRUCTION for a fact that only states how, where, when, or in what form the submission is delivered" in prompt
    assert "distinction=INFORMATIONAL for a statement that asks nothing of the bidder" in prompt
    assert pursuit_analyzer.PROMPT_VERSION == "pursuit_analysis_d2_v2"
    assert pursuit_analyzer.PIPELINE_VERSION == "pursuit_analysis_pipeline_d2_v2"

    paths = app.openapi()["paths"]
    assert set(paths["/api/v1/candidates/self-firm"]) == {"get", "put"}
    assert "patch" in paths["/api/v1/candidates/firms/{firm_id}/project-references/{reference_id}"]
    assert "post" in paths["/api/v1/candidates/firms/{firm_id}/project-references/{reference_id}/archive"]
    schemas = app.openapi()["components"]["schemas"]
    assert "self_firm" in schemas["CandidateLibraryResponse"]["properties"]
    assert "scope" not in schemas["SelfFirmUpsertRequest"]["properties"]
    assert "network_permission_basis" not in schemas["SelfFirmUpsertRequest"]["properties"]
    assert "submission_and_notes" in schemas["PursuitAnalysisResponse"]["properties"]
    assert "matched_reference_ids" in schemas["PursuitRequirementResponse"]["properties"]
    assert "matched_reference_ids" in schemas["PursuitGapResponse"]["properties"]
    assert "note_kind" in schemas["PursuitSubmissionNoteResponse"]["properties"]


# ---- migration ------------------------------------------------------------------------------------

def test_d2_01_migration_is_additive_reversible_and_drift_free() -> None:
    async def scenario() -> None:
        database = support.database_name("d2_01_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", D1_03_HEAD)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT version_num FROM alembic_version") == HEAD
                columns = {
                    (row["table_name"], row["column_name"]): row["is_nullable"]
                    for row in await connection.fetch(
                        "SELECT table_name, column_name, is_nullable FROM information_schema.columns "
                        "WHERE table_name IN ('candidate_firms','candidate_project_references')"
                    )
                }
                for key in (
                    ("candidate_firms", "organization_id"),
                    ("candidate_project_references", "archived_at"),
                    ("candidate_project_references", "archived_by_user_id"),
                    ("candidate_project_references", "supersedes_reference_id"),
                ):
                    assert columns[key] == "YES", key
                assert await connection.fetchval("SELECT to_regclass('uq_candidate_firms_self_organization')")
                assert await connection.fetchval("SELECT to_regclass('uq_candidate_references_supersedes')")
                assert await connection.fetchval(
                    "SELECT count(*) FROM pg_constraint WHERE conname IN "
                    "('ck_candidate_firm_self_private','ck_candidate_reference_supersedes_other')"
                ) == 2
                assert await connection.fetchval(
                    "SELECT count(*) FROM pg_trigger WHERE tgname='candidate_project_references_facts_immutable'"
                ) == 1
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", D1_03_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval(
                    "SELECT count(*) FROM information_schema.columns WHERE "
                    "(table_name='candidate_firms' AND column_name='organization_id') OR "
                    "(table_name='candidate_project_references' AND column_name IN "
                    "('archived_at','archived_by_user_id','supersedes_reference_id'))"
                ) == 0
                assert await connection.fetchval("SELECT to_regclass('uq_candidate_firms_self_organization')") is None
                assert await connection.fetchval(
                    "SELECT count(*) FROM pg_proc WHERE proname='candidate_project_reference_facts_immutable'"
                ) == 0
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


# ---- Postgres scenario ----------------------------------------------------------------------------

def test_self_firm_references_exclusions_and_own_experience_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        database = support.database_name("d2_01_own_experience")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                organization_a = await connection.fetchval(
                    "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"]
                )
                organization_b = await connection.fetchval(
                    "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_b"]
                )
                owner_a = await connection.fetchval(
                    "SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", organization_a, ids["user_a"]
                )
            finally:
                await connection.close()

            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                await _self_firm_api(sessions, ids, organization_a, organization_b, owner_a)
                references = await _reference_edits(sessions, ids, organization_a, database)
                await _exclusions_and_analysis(
                    sessions, ids, organization_a, owner_a, references, monkeypatch,
                )
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _self_firm_api(sessions, ids, organization_a, organization_b, owner_a) -> None:
    read, save = candidate_endpoints.read_self_firm, candidate_endpoints.save_self_firm
    async with sessions() as db:
        user_a = await db.get(User, ids["user_a"])
        user_b = await db.get(User, ids["user_b"])
        # Passive GET: 404 and nothing created.
        with pytest.raises(HTTPException) as missing:
            await read(x_organization_id=organization_a, current_user=user_a, db=db)
        assert missing.value.status_code == 404
        assert await db.scalar(select(func.count(Firm.id))) == 0

        created = await save(payload=SelfFirmUpsertRequest(), x_organization_id=organization_a, current_user=user_a, db=db)
        assert created.is_self_firm and created.scope == "ORGANIZATION_PRIVATE"
        assert created.display_name == "Same Name Company" == created.canonical_name  # the organization's name
        assert created.evidence_state == "UNVERIFIED" and created.project_references == []
        updated = await save(
            payload=SelfFirmUpsertRequest(display_name="Codex  Energy", sectors=["Energy", "energy"], country="Uzbekistan"),
            x_organization_id=organization_a, current_user=user_a, db=db,
        )
        assert updated.firm_id == created.firm_id and updated.display_name == "Codex Energy"
        assert updated.sectors == ["Energy"] and updated.canonical_name == "Same Name Company"
        again = await read(x_organization_id=organization_a, current_user=user_a, db=db)
        assert again.firm_id == created.firm_id and again.country == "Uzbekistan"
        with pytest.raises(HTTPException) as empty:
            await save(payload=SelfFirmUpsertRequest(display_name=None), x_organization_id=organization_a, current_user=user_a, db=db)
        assert empty.value.status_code == 422
        with pytest.raises(ValueError):
            SelfFirmUpsertRequest(scope="NETWORK_SHARED")

        # Tenant isolation: B sees no A firm, cannot name A's context, and owns its own.
        with pytest.raises(HTTPException) as isolated:
            await read(x_organization_id=organization_b, current_user=user_b, db=db)
        assert isolated.value.status_code == 404
        with pytest.raises(HTTPException) as foreign:
            await read(x_organization_id=organization_a, current_user=user_b, db=db)
        assert foreign.value.status_code == 404
        firm_b = await save(payload=SelfFirmUpsertRequest(), x_organization_id=organization_b, current_user=user_b, db=db)
        assert firm_b.firm_id != created.firm_id
        assert await db.scalar(select(func.count(Firm.id)).where(Firm.organization_id.is_not(None))) == 2

    # The database keeps one private self firm per organization.
    async with sessions() as db:
        with pytest.raises(Exception, match="uq_candidate_firms_self_organization"):
            db.add(Firm(
                scope="ORGANIZATION_PRIVATE", owner_organization_id=organization_a, organization_id=organization_a,
                canonical_name="Second", display_name="Second", source_type="MANUAL", source_provenance={},
                evidence_state="UNVERIFIED", created_by_user_id=ids["user_a"],
                regions=[], services=[], capabilities=[], sectors=[],
            ))
            await db.commit()
        await db.rollback()
        with pytest.raises(Exception, match="ck_candidate_firm_self_private"):
            db.add(Firm(
                scope="ORGANIZATION_PRIVATE", owner_organization_id=organization_b, organization_id=organization_a,
                canonical_name="Mismatch", display_name="Mismatch", source_type="MANUAL", source_provenance={},
                evidence_state="UNVERIFIED", created_by_user_id=ids["user_a"],
                regions=[], services=[], capabilities=[], sectors=[],
            ))
            await db.commit()
        await db.rollback()

    # A revoked membership loses the self firm with the rest of the organization.
    async with sessions() as db, db.begin():
        invited = await invite_member(db, organization_id=organization_a, actor_membership_id=owner_a, user_id=ids["member"])
        invited_id = invited.id
    async with sessions() as db, db.begin():
        await activate_invitation(db, membership_id=invited_id, user_id=ids["member"])
    async with sessions() as db:
        member = await db.get(User, ids["member"])
        assert (await read(x_organization_id=organization_a, current_user=member, db=db)).firm_id == created.firm_id
    async with sessions() as db, db.begin():
        await revoke_membership(db, organization_id=organization_a, actor_membership_id=owner_a, membership_id=invited_id)
    async with sessions() as db:
        member = await db.get(User, ids["member"])
        for call in (
            read(x_organization_id=organization_a, current_user=member, db=db),
            save(payload=SelfFirmUpsertRequest(country="Kazakhstan"), x_organization_id=organization_a, current_user=member, db=db),
        ):
            with pytest.raises(HTTPException) as revoked:
                await call
            assert revoked.value.status_code == 404
        assert (await db.scalar(select(Firm).where(Firm.organization_id == organization_a))).country == "Uzbekistan"


async def _reference_edits(sessions, ids, organization_a, database) -> dict[str, object]:
    edit = candidate_endpoints.edit_project_reference
    archive = candidate_endpoints.retire_project_reference
    add = candidate_endpoints.add_project_reference
    async with sessions() as db:
        user_a = await db.get(User, ids["user_a"])
        self_firm = await db.scalar(select(Firm).where(Firm.organization_id == organization_a))

        def payload(name: str, **values) -> ProjectReferenceCreateRequest:
            base = dict(
                project_name=name, client_name="National Grid", country="Uzbekistan", sector="Energy",
                service="Engineering design", role="LEAD", value_basis="UNKNOWN", start_date="2019-01-01",
                completion_date="2021-06-30", completion_state="COMPLETED",
                relevant_scope="Detailed design of 220 kV substations", evidence_state="UNVERIFIED",
            )
            base.update(values)
            return ProjectReferenceCreateRequest(**base)

        navoi = await add(firm_id=self_firm.id, payload=payload("Substation design Navoi"),
                          x_organization_id=organization_a, current_user=user_a, db=db)
        water = await add(firm_id=self_firm.id, payload=payload(
            "Water network design", sector="Water", service="Water supply design",
            relevant_scope="Design of water distribution networks",
        ), x_organization_id=organization_a, current_user=user_a, db=db)
        andijan = await add(firm_id=self_firm.id, payload=payload(
            "Transmission line design Andijan", start_date="2010-01-01", completion_date="2012-05-01",
            relevant_scope="Design of overhead transmission lines",
        ), x_organization_id=organization_a, current_user=user_a, db=db)
        retired = await add(firm_id=self_firm.id, payload=payload("Substation design Termez"),
                            x_organization_id=organization_a, current_user=user_a, db=db)
        assert navoi.evidence_basis == "METADATA_ONLY" and navoi.supersedes_reference_id is None

        # Edit = supersede: new row, old row archived with its facts unchanged.
        edited = await edit(
            firm_id=self_firm.id, reference_id=navoi.reference_id,
            payload=ProjectReferenceUpdateRequest(
                client_name="National Electric Grid", evidence_provenance={"document_reference": "acceptance.pdf"},
            ),
            x_organization_id=organization_a, current_user=user_a, db=db,
        )
        assert edited.reference_id != navoi.reference_id and edited.supersedes_reference_id == navoi.reference_id
        assert edited.client_name == "National Electric Grid" and edited.evidence_basis == "FILE_BACKED"
        assert edited.project_name == "Substation design Navoi" and edited.archived_at is None
        old = await db.get(ProjectReference, navoi.reference_id)
        await db.refresh(old)
        assert old.archived_at is not None and old.client_name == "National Grid"
        # A request that changes nothing writes nothing.
        same = await edit(
            firm_id=self_firm.id, reference_id=edited.reference_id,
            payload=ProjectReferenceUpdateRequest(client_name="National Electric Grid"),
            x_organization_id=organization_a, current_user=user_a, db=db,
        )
        assert same.reference_id == edited.reference_id
        for bad, code in (
            (ProjectReferenceUpdateRequest(contract_value=Decimal("100")), 422),  # value without currency
            (ProjectReferenceUpdateRequest(project_name=None), 422),
        ):
            with pytest.raises(HTTPException) as rejected:
                await edit(firm_id=self_firm.id, reference_id=edited.reference_id, payload=bad,
                           x_organization_id=organization_a, current_user=user_a, db=db)
            assert rejected.value.status_code == code
        with pytest.raises(HTTPException) as archived_edit:
            await edit(firm_id=self_firm.id, reference_id=navoi.reference_id,
                       payload=ProjectReferenceUpdateRequest(client_name="Rewrite history"),
                       x_organization_id=organization_a, current_user=user_a, db=db)
        assert archived_edit.value.status_code == 409

        first = await archive(firm_id=self_firm.id, reference_id=retired.reference_id,
                              x_organization_id=organization_a, current_user=user_a, db=db)
        second = await archive(firm_id=self_firm.id, reference_id=retired.reference_id,
                               x_organization_id=organization_a, current_user=user_a, db=db)
        assert first.archived_at is not None and second.archived_at == first.archived_at
        with pytest.raises(HTTPException) as unknown:
            await archive(firm_id=self_firm.id, reference_id=uuid4(),
                          x_organization_id=organization_a, current_user=user_a, db=db)
        assert unknown.value.status_code == 404

        library = await list_candidate_library(db, organization_id=organization_a)
        assert library.self_firm and library.self_firm.firm_id == self_firm.id
        assert self_firm.id not in {row.firm_id for row in library.firms}
        assert [row.reference_id for row in library.self_firm.project_references] == [
            water.reference_id, andijan.reference_id, edited.reference_id,
        ]
        assert await db.scalar(select(func.count(ProjectReference.id))) == 5

    # The database keeps recorded facts immutable, archived rows included.
    connection = await support.database_connection(database)
    try:
        with pytest.raises(Exception, match="immutable"):
            await connection.execute(
                "UPDATE candidate_project_references SET project_name='Rewritten' WHERE id=$1", water.reference_id
            )
        with pytest.raises(Exception, match="immutable"):
            await connection.execute(
                "UPDATE candidate_project_references SET archived_at=NULL WHERE id=$1", navoi.reference_id
            )
    finally:
        await connection.close()
    return {"navoi": edited, "water": water, "andijan": andijan, "retired": retired}


async def _exclusions_and_analysis(sessions, ids, organization_a, owner_a, references, monkeypatch) -> None:
    async with sessions() as db:
        source = await get_or_create_source_pursuit(
            db, organization_id=organization_a, actor_user_id=ids["user_a"],
            actor_membership_id=owner_a, tender_id=ids["tender"], stage=TenderEngagementStatus.SAVED,
            legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
        )
        issued = (
            f"{SUBSTATION}\n"
            "Key Experts will not be evaluated during the shortlisting stage.\n"
            "Expressions of interest must be delivered in written form via e-mail no later than 16 October 2026.\n"
            "The firm must hold valid licenses for high-complexity facility construction.\n"
            "Joint venture members may combine experience in substation design contracts, subject to review."
        )
        document = TenderDocument(
            tender_id=ids["tender"], file_url="d2-issued.pdf", file_type="pdf",
            source_document_url="https://example.invalid/d2-issued.pdf", source_document_type="RFP",
            sha256=hashlib.sha256(issued.encode()).hexdigest(), parsed_text=issued,
        )
        db.add(document)
        await db.commit()
        candidate = await build_analysis_pack_candidate(db, organization_id=organization_a, pursuit_id=source.pursuit.id)
        started = await create_analysis_run(
            db, organization_id=organization_a, pursuit_id=source.pursuit.id, membership_id=owner_a,
            request=PursuitAnalysisStartRequest(
                candidate_sha256=candidate.candidate_sha256, analysis_language="en", source_document_ids=[document.id],
            ),
        )
        snapshot = await db.scalar(select(AnalysisCompanySnapshot).where(
            AnalysisCompanySnapshot.analysis_run_id == started.analysis_run_id
        ))
        own = snapshot.snapshot_json["own_project_references"]
        assert snapshot.snapshot_json["self_firm"]["display_name"] == "Codex Energy"
        assert [item["id"] for item in own] == [
            str(references["water"].reference_id), str(references["andijan"].reference_id),
            str(references["navoi"].reference_id),
        ]  # archived and superseded rows are not the organization's current record
        navoi = own[-1]
        assert navoi["client_name"] == "National Electric Grid" and navoi["evidence_basis"] == "FILE_BACKED"
        assert set(navoi) >= {
            "id", "project_name", "client_name", "country", "sector", "service", "role", "start_date",
            "completion_date", "completion_state", "contract_value", "contract_currency", "value_basis",
            "evidence_state", "evidence_basis",
        }
        assert snapshot.file_backed_count == 1

    lines = issued.split("\n")

    async def extracted(sealed, language):
        item = sealed[0]

        def verified(fact: ExtractedFact) -> VerifiedFact:
            start = issued.index(fact.original_quote)
            return VerifiedFact(item.pack_item_id, fact, start, start + len(fact.original_quote), 1, 1)

        return [
            verified(_fact(original_quote=lines[0], normalized_text=lines[0])),
            verified(_fact(
                original_quote=lines[1], normalized_text=lines[1], category="PERSONNEL",
                requirement_type="EVALUATION_CRITERIA", stage_scope="SHORTLISTING", distinction="INFORMATIONAL",
                predicate=None,
            )),
            verified(_fact(
                original_quote=lines[2], normalized_text="Deliver the expression of interest by e-mail by 16 October 2026",
                category="SUBMISSION", requirement_type="SUBMISSION_INSTRUCTION", stage_scope="SUBMISSION", predicate=None,
            )),
            verified(_fact(
                original_quote=lines[3], normalized_text=lines[3], category="LEGAL", requirement_type="CERTIFICATION",
                predicate=None,
            )),
            verified(_fact(
                original_quote=lines[4], normalized_text=lines[4], category="EXPERIENCE",
                requirement_type="JV_EXPERIENCE", predicate=None, complex_rule=True,
                contribution_rule="Joint venture members may combine experience, subject to review",
            )),
        ]

    monkeypatch.setattr(analysis_service.pursuit_analyzer, "analyze_pack_items", extracted)
    async with sessions() as db:
        await process_analysis_run(db, started.analysis_run_id, worker_id="d2-01-worker")
        run = await db.get(AnalysisRun, started.analysis_run_id)
        assert run.status == "COMPLETED" and run.pipeline_version == "pursuit_analysis_pipeline_d2_v2"
        assert run.extraction_diagnostics["persisted_requirement_count"] == 5
        assert run.extraction_diagnostics["persisted_gap_count"] == 3  # no Gap for either note
        assert run.extraction_diagnostics["submission_and_notes_count"] == 2
        assert run.extraction_diagnostics["own_experience_partial_count"] == 1
        # One transaction writes every row with the same created_at: order by source line.
        by_quote = {row.original_quote: row for row in (await db.scalars(select(PursuitRequirement).where(
            PursuitRequirement.analysis_run_id == run.id
        ))).all()}
        rows = [by_quote[line] for line in lines]
        navoi_id = str(references["navoi"].reference_id)
        assert [row.coverage_state for row in rows] == [
            "PARTIAL", "NOT_APPLICABLE", "NOT_APPLICABLE", "EVIDENCE_MISSING", "NEEDS_INTERPRETATION",
        ]
        assert rows[0].source_locator["matched_reference_ids"] == [navoi_id]
        assert rows[4].source_locator["matched_reference_ids"] == [navoi_id]
        assert "matched_reference_ids" not in rows[3].source_locator
        assert await db.scalar(select(func.count(PursuitGap.id)).where(
            PursuitGap.analysis_run_id == run.id, PursuitGap.requirement_id.in_([rows[1].id, rows[2].id])
        )) == 0

        analysis = await get_analysis_run(db, organization_id=organization_a, pursuit_id=source.pursuit.id)
        assert {item.requirement_id for item in analysis.requirements} == {rows[0].id, rows[3].id, rows[4].id}
        notes = {item.requirement_id: item.note_kind for item in analysis.submission_and_notes}
        assert notes == {rows[1].id: "INFORMATIONAL", rows[2].id: "SUBMISSION_INSTRUCTION"}
        assert all(item.effective_coverage_state == "NOT_APPLICABLE" for item in analysis.submission_and_notes)
        partial = next(item for item in analysis.requirements if item.requirement_id == rows[0].id)
        assert [str(value) for value in partial.matched_reference_ids] == [navoi_id]
        gap = next(item for item in analysis.gaps if item.requirement_id == rows[0].id)
        assert gap.coverage_state == "PARTIAL" and [str(value) for value in gap.matched_reference_ids] == [navoi_id]
        assert "Substation design Navoi" in gap.rationale and "1 of the 2 required" in gap.rationale
        assert "Transmission line design Andijan" in gap.rationale  # named as not counted (outside the window)
        assert all(item.matched_reference_ids == [] for item in analysis.gaps if item.requirement_id == rows[3].id)
        missing = [item for item in analysis.requirements if item.effective_coverage_state == "EVIDENCE_MISSING"]
        assert [item.requirement_id for item in missing] == [rows[3].id]

        # A reviewer who re-states a note's coverage takes it back into requirements.
        await append_review_assertion(
            db, organization_id=organization_a, pursuit_id=source.pursuit.id, run_id=run.id, membership_id=owner_a,
            request=AnalysisReviewAssertionRequest(
                target_kind="REQUIREMENT", target_id=rows[2].id, new_coverage_state="EVIDENCE_MISSING",
                new_review_state="CORRECTED", corrected_fields={}, reason="The e-mail address must be registered first.",
            ),
        )
        reviewed = await get_analysis_run(db, organization_id=organization_a, pursuit_id=source.pursuit.id)
        assert rows[2].id in {item.requirement_id for item in reviewed.requirements}
        assert [item.requirement_id for item in reviewed.submission_and_notes] == [rows[1].id]

    await _search_and_scenario_exclusions(sessions, ids, organization_a, owner_a, source.pursuit.id, run.id, rows[0].id)


async def _search_and_scenario_exclusions(sessions, ids, organization_a, owner_a, pursuit_id, run_id, requirement_id) -> None:
    async with sessions() as db:
        gap = await db.scalar(select(PursuitGap).where(PursuitGap.requirement_id == requirement_id))
        await append_review_assertion(
            db, organization_id=organization_a, pursuit_id=pursuit_id, run_id=run_id, membership_id=owner_a,
            request=AnalysisReviewAssertionRequest(
                target_kind="GAP", target_id=gap.id, new_coverage_state="PARTIAL", new_review_state="CORRECTED",
                corrected_fields={
                    "resolution_category": "PARTNER_FIRM",
                    "contribution_rule": "Joint venture members collectively may satisfy this requirement",
                },
                reason="A partner may add the second substation contract.",
            ),
        )
        partner = await create_firm(
            db, organization_id=organization_a, actor_user_id=ids["user_a"], operator=False,
            payload=FirmCreateRequest(
                scope="ORGANIZATION_PRIVATE", canonical_name="Grid Partner", display_name="Grid Partner",
                country="Kazakhstan", services=["Substation design"], sectors=["Energy"], source_type="MANUAL",
                evidence_state="REVIEWED",
            ),
        )
        await create_project_reference(
            db, organization_id=organization_a, firm_id=partner.firm_id, actor_user_id=ids["user_a"], operator=False,
            payload=ProjectReferenceCreateRequest(
                project_name="Substation design Almaty", country="Kazakhstan", sector="Energy",
                service="Substation design", role="LEAD", value_basis="UNKNOWN", completion_date="2023-01-01",
                completion_state="COMPLETED", relevant_scope="Detailed engineering design of substations",
                evidence_provenance={"document_reference": "certificate.pdf"}, evidence_state="VERIFIED",
            ),
        )
        search = await create_candidate_search(
            db, organization_id=organization_a, pursuit_id=pursuit_id, membership_id=owner_a,
            request=CandidateSearchRequest(analysis_run_id=run_id, gap_id=gap.id),
        )
        self_firm = await db.scalar(select(Firm).where(Firm.organization_id == organization_a))
        candidates = {item.candidate_id for item in search.matches}
        assert partner.firm_id in candidates and self_firm.id not in candidates  # the own firm is never a partner
        match = next(item for item in search.matches if item.candidate_id == partner.firm_id)
        review = await append_candidate_review(
            db, organization_id=organization_a, pursuit_id=pursuit_id, search_run_id=search.candidate_search_run_id,
            match_id=match.candidate_match_id, membership_id=owner_a,
            request=CandidateReviewRequest(decision="SHORTLISTED", reason="Second substation contract."),
        )
        record = await start_participation(
            db, organization_id=organization_a, pursuit_id=pursuit_id, candidate_match_id=match.candidate_match_id,
            membership_id=owner_a, request=ParticipationStartRequest(shortlist_decision_id=review.decision_id),
        )
        # W7 keeps the lead organization separate: were this firm the organization's own
        # firm, it could not be a scenario participant.
        self_firm.organization_id = None
        await db.commit()
        partner_row = await db.get(Firm, partner.firm_id)
        partner_row.organization_id = organization_a
        await db.commit()
        with pytest.raises(TeamScenarioEligibilityError, match="own firm"):
            await create_team_scenario(
                db, organization_id=organization_a, pursuit_id=pursuit_id, membership_id=owner_a,
                request=TeamScenarioCreateRequest(title="Own firm as participant", participation_record_ids=[record.participation_record_id]),
            )
        partner_row.organization_id = None
        await db.commit()
        self_firm.organization_id = organization_a
        await db.commit()
        scenario = await create_team_scenario(
            db, organization_id=organization_a, pursuit_id=pursuit_id, membership_id=owner_a,
            request=TeamScenarioCreateRequest(title="Partner scenario", participation_record_ids=[record.participation_record_id]),
        )
        assert scenario.latest_revision and scenario.latest_revision.participant_count == 1
        assert await db.scalar(select(func.count(CandidateMatch.id)).where(CandidateMatch.firm_id == self_firm.id)) == 0
