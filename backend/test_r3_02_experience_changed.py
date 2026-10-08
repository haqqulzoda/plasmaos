"""R3 Task 2: analysis reads say when recorded experience changed since the run sealed it."""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.agents.pursuit_analyzer import VerifiedFact
from app.models.all_models import TenderDocument
from app.models.base import TenderEngagementOrigin, TenderEngagementStatus
from app.models.candidate_retrieval import Firm, ProjectReference
from app.models.company import CompanyProfile
from app.models.pursuit_analysis import AnalysisCompanySnapshot, AnalysisRun
from app.schemas.candidate_retrieval import (
    ProjectReferenceCreateRequest,
    ProjectReferenceUpdateRequest,
    SelfFirmUpsertRequest,
)
from app.schemas.tenancy import PursuitAnalysisStartRequest
from app.services import pursuit_analysis as analysis_service
from app.services.candidate_retrieval import create_project_reference, update_project_reference, upsert_self_firm
from app.services.eoi import eoi_suggestions
from app.services.private_documents import build_analysis_pack_candidate
from app.services.pursuit_analysis import (
    compare_company_evidence,
    create_analysis_run,
    get_analysis_run,
    process_analysis_run,
)
from app.services.pursuits import get_or_create_source_pursuit
from scripts import test_s0_5b4_baseline as support
from test_d2_01_own_experience import SUBSTATION, _fact
from test_w2_organization_pursuit_foundation import W1_HEAD, _seed_w1


HEAD = "20261009_0001_r3_cv_library_drafts"


def _sha(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    ).hexdigest()


# ---- pure comparison --------------------------------------------------------------------------------

def test_comparison_names_the_changed_sections() -> None:
    sealed = {
        "truth_notice": "x", "profile": {"id": "p", "company_name": "Codex"},
        "certifications": [], "licenses": [], "financial_history": [], "readiness_documents": [],
        "self_firm": {"id": "f", "display_name": "Codex"},
        "own_project_references": [{"id": "r1", "project_name": "Navoi"}],
    }
    assert compare_company_evidence(_sha(sealed), sealed, dict(sealed)).changed is False

    edited = {**sealed, "own_project_references": [{"id": "r2", "project_name": "Navoi substations"}]}
    state = compare_company_evidence(_sha(sealed), sealed, edited)
    assert state.changed and state.sections == ("OWN_EXPERIENCE",)
    assert "project references" in state.reason

    profile = {**edited, "profile": {"id": "p", "company_name": "Codex LLC"}}
    assert compare_company_evidence(_sha(sealed), sealed, profile).sections == ("OWN_EXPERIENCE", "COMPANY_PROFILE")
    readiness = {**sealed, "licenses": [{"id": "l1"}]}
    assert compare_company_evidence(_sha(sealed), sealed, readiness).sections == ("READINESS_RECORDS",)

    # A run sealed before D2-01 recorded no own experience: nothing recorded now is no change.
    old = {key: value for key, value in sealed.items() if key not in {"self_firm", "own_project_references"}}
    current = {**old, "self_firm": None, "own_project_references": []}
    assert compare_company_evidence(_sha(old), old, current).changed is False
    # ...but experience recorded since then is.
    assert compare_company_evidence(_sha(old), old, sealed).sections == ("OWN_EXPERIENCE",)
    # A different notice wording alone is not a change of evidence.
    assert compare_company_evidence(_sha(sealed), sealed, {**sealed, "truth_notice": "y"}).changed is False


# ---- Postgres scenario ------------------------------------------------------------------------------

def test_analysis_and_eoi_reads_flag_changed_experience_passively(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        database = support.database_name("r3_02_experience")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                org_a = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"])
                org_b = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_b"])
                owner_a = await connection.fetchval("SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", org_a, ids["user_a"])
            finally:
                await connection.close()
            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                await _flow(sessions, ids, org_a, org_b, owner_a, monkeypatch)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _counts(db) -> dict[str, int]:
    return {
        model.__tablename__: await db.scalar(select(func.count()).select_from(model))
        for model in (AnalysisRun, AnalysisCompanySnapshot, Firm, ProjectReference)
    }


def _reference(name: str, **values) -> ProjectReferenceCreateRequest:
    base = dict(
        project_name=name, client_name="National Grid", country="Uzbekistan", sector="Energy",
        service="Engineering design", role="LEAD", value_basis="UNKNOWN", start_date="2019-01-01",
        completion_date="2021-06-30", completion_state="COMPLETED",
        relevant_scope="Detailed design of 220 kV substations", evidence_state="UNVERIFIED",
    )
    base.update(values)
    return ProjectReferenceCreateRequest(**base)


async def _run(sessions, ids, org_a, owner_a, pursuit_id, document_id) -> object:
    async with sessions() as db:
        candidate = await build_analysis_pack_candidate(db, organization_id=org_a, pursuit_id=pursuit_id)
        started = await create_analysis_run(
            db, organization_id=org_a, pursuit_id=pursuit_id, membership_id=owner_a,
            request=PursuitAnalysisStartRequest(
                candidate_sha256=candidate.candidate_sha256, analysis_language="en", source_document_ids=[document_id],
            ),
        )
    async with sessions() as db:
        await process_analysis_run(db, started.analysis_run_id, worker_id="r3-02")
    return started.analysis_run_id


async def _flow(sessions, ids, org_a, org_b, owner_a, monkeypatch) -> None:
    async with sessions() as db:
        source = await get_or_create_source_pursuit(
            db, organization_id=org_a, actor_user_id=ids["user_a"], actor_membership_id=owner_a, tender_id=ids["tender"],
            stage=TenderEngagementStatus.SAVED, legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
        )
        pursuit_id = source.pursuit.id
        document = TenderDocument(
            tender_id=ids["tender"], file_url="r302.pdf", file_type="pdf", source_document_url="https://example.invalid/r302.pdf",
            source_document_type="RFP", sha256=hashlib.sha256(SUBSTATION.encode()).hexdigest(), parsed_text=SUBSTATION,
        )
        db.add(document)
        await db.commit()
        document_id = document.id
        firm = await upsert_self_firm(db, organization_id=org_a, actor_user_id=ids["user_a"], payload=SelfFirmUpsertRequest(
            display_name="Codex Energy", country="Uzbekistan"))
        navoi = await create_project_reference(
            db, organization_id=org_a, firm_id=firm.firm_id, actor_user_id=ids["user_a"], operator=False,
            payload=_reference("Substation design Navoi"),
        )
        # Organization B's own experience, to prove isolation.
        firm_b = await upsert_self_firm(db, organization_id=org_b, actor_user_id=ids["user_b"], payload=SelfFirmUpsertRequest(
            display_name="Other Energy"))

    async def extracted(sealed, language):
        item = sealed[0]
        fact = _fact(original_quote=SUBSTATION, normalized_text=SUBSTATION)
        return [VerifiedFact(item.pack_item_id, fact, 0, len(SUBSTATION), None, 1)]

    monkeypatch.setattr(analysis_service.pursuit_analyzer, "analyze_pack_items", extracted)
    first = await _run(sessions, ids, org_a, owner_a, pursuit_id, document_id)

    async with sessions() as db:
        before = await _counts(db)
        analysis = await get_analysis_run(db, organization_id=org_a, pursuit_id=pursuit_id, include_company_evidence=True)
        assert analysis.status == "COMPLETED" and analysis.company_evidence_changed is False
        assert analysis.company_evidence_change_reason is None and analysis.company_evidence_changed_sections == []
        # The pack selection is exposed for a re-run.
        assert [item.tender_document_id for item in analysis.pack_items] == [document_id]
        suggestions = await eoi_suggestions(db, organization_id=org_a, pursuit_id=pursuit_id, analysis_run_id=first)
        assert suggestions.company_evidence_changed is False

    # Another organization's experience never flags A's analysis.
    async with sessions() as db:
        await create_project_reference(
            db, organization_id=org_b, firm_id=firm_b.firm_id, actor_user_id=ids["user_b"], operator=False,
            payload=_reference("Somewhere else"),
        )
        assert (await get_analysis_run(db, organization_id=org_a, pursuit_id=pursuit_id, include_company_evidence=True)).company_evidence_changed is False

    # Editing an own reference (supersede) flags the run on both reads, with a reason.
    async with sessions() as db:
        await update_project_reference(
            db, organization_id=org_a, firm_id=firm.firm_id, reference_id=navoi.reference_id,
            actor_user_id=ids["user_a"], operator=False,
            payload=ProjectReferenceUpdateRequest(project_name="Substation design Navoi, 220 kV"),
        )
    async with sessions() as db:
        before = await _counts(db)
        analysis = await get_analysis_run(db, organization_id=org_a, pursuit_id=pursuit_id, include_company_evidence=True)
        assert analysis.company_evidence_changed is True
        assert analysis.company_evidence_changed_sections == ["OWN_EXPERIENCE"]
        assert "project references" in analysis.company_evidence_change_reason
        by_id = await get_analysis_run(db, organization_id=org_a, pursuit_id=pursuit_id, run_id=first, include_company_evidence=True)
        assert by_id.company_evidence_changed is True
        suggestions = await eoi_suggestions(db, organization_id=org_a, pursuit_id=pursuit_id, analysis_run_id=first)
        assert suggestions.company_evidence_changed is True and suggestions.run_current is True
        # Passive: reads create nothing and the sealed snapshot is untouched.
        assert await _counts(db) == before
        sealed = await db.scalar(select(AnalysisCompanySnapshot).where(AnalysisCompanySnapshot.analysis_run_id == first))
        assert sealed.snapshot_sha256 == _sha(sealed.snapshot_json)
        assert [item["project_name"] for item in sealed.snapshot_json["own_project_references"]] == ["Substation design Navoi"]

    # A company profile edit is named as well.
    async with sessions() as db:
        profile = await db.get(CompanyProfile, ids["profile_a"])
        profile.website = "https://codex.example"
        await db.commit()
        analysis = await get_analysis_run(db, organization_id=org_a, pursuit_id=pursuit_id, include_company_evidence=True)
        assert analysis.company_evidence_changed_sections == ["OWN_EXPERIENCE", "COMPANY_PROFILE"]

    # The explicit re-run seals the current records: the new run is current again.
    second = await _run(sessions, ids, org_a, owner_a, pursuit_id, document_id)
    async with sessions() as db:
        latest = await get_analysis_run(db, organization_id=org_a, pursuit_id=pursuit_id, include_company_evidence=True)
        assert latest.analysis_run_id == second and latest.company_evidence_changed is False
        old = await get_analysis_run(db, organization_id=org_a, pursuit_id=pursuit_id, run_id=first, include_company_evidence=True)
        assert old.company_evidence_changed is True
