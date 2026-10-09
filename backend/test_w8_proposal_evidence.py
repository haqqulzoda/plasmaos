"""Permanent W8 sealing, manifest, export, staleness, and privacy proofs."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.private_storage import PDF_MEDIA_TYPE
from app.models.all_models import Proposal, TenderDocument
from app.models.base import MembershipState, PrivateDocumentRole, TenderEngagementOrigin, TenderEngagementStatus
from app.models.proposal_evidence import (
    ARTIFACT_TYPES,
    PACK_ITEM_CATEGORIES,
    ProposalEvidenceArtifact,
    ProposalEvidencePack,
    ProposalEvidencePackItem,
    PursuitProposalWorkspace,
)
from app.models.pursuit_analysis import AnalysisPackItem, AnalysisRun, PursuitGap, PursuitPosition, PursuitRequirement
from app.models.tenancy import Membership
from app.schemas.candidate_retrieval import (
    CandidateReviewRequest,
    CandidateSearchRequest,
    CVVersionCreateRequest,
    ExpertCreateRequest,
    FirmCreateRequest,
    ProjectReferenceCreateRequest,
)
from app.schemas.participation import (
    AvailabilityFactCreateRequest,
    ParticipationDecisionCreateRequest,
    ParticipationStartRequest,
)
from app.schemas.proposal_evidence import ProposalEvidenceExportRequest, ProposalEvidenceSealRequest
from app.schemas.team_scenarios import TeamScenarioCreateRequest, TeamScenarioDecisionCreateRequest
from app.schemas.tenancy import AnalysisReviewAssertionRequest, PursuitAnalysisStartRequest
from app.services import private_documents as private_service
from app.services.candidate_retrieval import (
    append_candidate_review,
    create_candidate_search,
    create_cv_version,
    create_expert,
    create_firm,
    create_project_reference,
)
from app.services.participation import append_availability, append_participation_decision, start_participation
from app.services.private_documents import build_analysis_pack_candidate, persist_private_pack, process_document_job
from app.services.proposal_evidence import (
    PACK_SCHEMA_VERSION,
    ProposalEvidenceEligibilityError,
    generate_proposal_evidence_artifact,
    get_proposal_evidence_pack,
    get_proposal_workspace,
    resolve_proposal_evidence_artifact,
    seal_proposal_evidence_pack,
)
from app.services.pursuit_analysis import append_review_assertion, create_analysis_run
from app.services.pursuits import create_upload_pursuit, get_or_create_source_pursuit
from app.services.team_scenarios import append_team_scenario_decision, create_team_scenario
from scripts import test_s0_5b4_baseline as support
from test_w2_organization_pursuit_foundation import W1_HEAD, _digest, _seed_w1
from test_w3_private_document_foundation import _pdf_bytes, _stage


W7_HEAD = "20260930_0001_w7_team_scenarios"
W8_HEAD = "20261001_0001_w8_proposal_evidence_pack"
CURRENT_HEAD = "20261011_0001_r3_organization_record_events"


def test_w8_model_contracts_are_price_free_and_immutable_shaped() -> None:
    assert set(ARTIFACT_TYPES) == {"PDF", "DOCX", "JSON"}
    assert {"PROJECT_REFERENCE", "CV_FACTS", "PARTICIPATION_CONFIRMATION", "LATER_STAGE_OBLIGATION"} <= set(PACK_ITEM_CATEGORIES)
    assert PursuitProposalWorkspace.__table__.c.pursuit_id is not None
    assert "manifest_sha256" in ProposalEvidencePack.__table__.c
    assert "payload_snapshot" in ProposalEvidencePackItem.__table__.c
    assert "storage_key" in ProposalEvidenceArtifact.__table__.c
    forbidden = {"price", "our_price", "budget", "commercial_terms", "ai_price"}
    assert forbidden.isdisjoint(ProposalEvidencePack.__table__.c.keys())
    assert forbidden.isdisjoint(ProposalEvidencePackItem.__table__.c.keys())


def test_w8_migration_from_w7_is_reversible_and_drift_free() -> None:
    async def scenario() -> None:
        database = support.database_name("w8_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W7_HEAD)
            await asyncio.to_thread(support.alembic, database, "upgrade", W8_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT version_num FROM alembic_version") == W8_HEAD
                for table in (
                    "pursuit_proposal_workspaces", "proposal_evidence_packs",
                    "proposal_evidence_pack_items", "proposal_evidence_artifacts",
                ):
                    assert await connection.fetchval("SELECT to_regclass($1)", table) == table
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", W7_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('proposal_evidence_packs')") is None
                assert await connection.fetchval("SELECT to_regclass('team_scenarios')") == "team_scenarios"
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", CURRENT_HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _completed_analysis(
    db, *, organization_id, pursuit_id, owner_id, candidate_sha, source_ids=None, private_ids=None,
):
    started = await create_analysis_run(
        db, organization_id=organization_id, pursuit_id=pursuit_id, membership_id=owner_id,
        request=PursuitAnalysisStartRequest(
            candidate_sha256=candidate_sha, analysis_language="en",
            source_document_ids=source_ids or [], private_version_ids=private_ids or [],
        ),
    )
    run = await db.get(AnalysisRun, started.analysis_run_id)
    pack_item = await db.scalar(select(AnalysisPackItem).where(
        AnalysisPackItem.pack_id == started.analysis_pack_id
    ))
    assert run and pack_item
    run.status = "COMPLETED"
    run.result_completeness = "FULL"
    run.completed_at = datetime.now(timezone.utc)
    current = PursuitRequirement(
        analysis_run_id=run.id, pack_item_id=pack_item.id, source_span="0:42",
        source_locator={"page_number": 1}, original_quote="One completed water contract is required.",
        source_context=None, normalized_requirement="One completed water contract",
        category="CORPORATE_EXPERIENCE", requirement_type="REFERENCE",
        stage_scope="ELIGIBILITY", distinction="MANDATORY",
        predicate_json={"operator": ">=", "threshold": 1, "unit": "contracts"},
        contribution_rule="A shortlisted partner Firm may contribute the reviewed reference.",
        coverage_state="EVIDENCE_MISSING", review_state="PROVISIONAL",
        extraction_confidence=0.98, generated_interpretation=None,
    )
    later = PursuitRequirement(
        analysis_run_id=run.id, pack_item_id=pack_item.id, source_span="43:84",
        source_locator={"page_number": 2}, original_quote="A signed proposal form is required at submission.",
        source_context=None, normalized_requirement="Signed proposal form",
        category="FORM", requirement_type="REQUIRED_ARTIFACT",
        stage_scope="SUBMISSION", distinction="MANDATORY", predicate_json=None,
        contribution_rule=None, coverage_state="LATER_STAGE_OBLIGATION",
        review_state="PROVISIONAL", extraction_confidence=0.98, generated_interpretation=None,
    )
    position = PursuitPosition(
        analysis_run_id=run.id, pack_item_id=pack_item.id, title="Water Engineer", quantity=1,
        distinction="MANDATORY", education_qualification="Civil engineering degree",
        general_experience=None, specific_experience="Water design experience",
        relevant_assignments="Water network design", languages=["English"], certifications=[],
        location_travel=None, expected_effort="50%", assignment_dates="2099-01-01 to 2099-03-31",
        source_span="85:126", source_locator={"page_number": 3},
        original_quote="A Water Engineer is required for 2099-01-01 to 2099-03-31.",
        source_context=None, coverage_state="EVIDENCE_MISSING", review_state="PROVISIONAL",
        extraction_confidence=0.98, generated_interpretation=None,
    )
    db.add_all([current, later, position])
    await db.flush()
    gaps = [
        PursuitGap(
            analysis_run_id=run.id, requirement_id=current.id, position_id=None,
            source_pack_item_id=pack_item.id, missing_contribution=current.normalized_requirement,
            coverage_state="EVIDENCE_MISSING", resolution_category="PARTNER_FIRM",
            review_state="PROVISIONAL", rationale="A reviewed Firm reference is required.",
        ),
        PursuitGap(
            analysis_run_id=run.id, requirement_id=None, position_id=position.id,
            source_pack_item_id=pack_item.id, missing_contribution=position.title,
            coverage_state="EVIDENCE_MISSING", resolution_category="EXPERT",
            review_state="PROVISIONAL", rationale="A reviewed Expert CV is required.",
        ),
        PursuitGap(
            analysis_run_id=run.id, requirement_id=later.id, position_id=None,
            source_pack_item_id=pack_item.id, missing_contribution=later.normalized_requirement,
            coverage_state="LATER_STAGE_OBLIGATION", resolution_category="CLARIFICATION",
            review_state="PROVISIONAL", rationale="The signed form remains a later-stage obligation.",
        ),
    ]
    db.add_all(gaps)
    await db.commit()
    for requirement in (current, later):
        await append_review_assertion(
            db, organization_id=organization_id, pursuit_id=pursuit_id,
            run_id=run.id, membership_id=owner_id,
            request=AnalysisReviewAssertionRequest(
                target_kind="REQUIREMENT", target_id=requirement.id,
                new_coverage_state=requirement.coverage_state, new_review_state="CONFIRMED",
                corrected_fields={}, reason="Reviewed against the exact issued source.",
            ),
        )
    await append_review_assertion(
        db, organization_id=organization_id, pursuit_id=pursuit_id,
        run_id=run.id, membership_id=owner_id,
        request=AnalysisReviewAssertionRequest(
            target_kind="POSITION", target_id=position.id,
            new_coverage_state=position.coverage_state, new_review_state="CONFIRMED",
            corrected_fields={}, reason="Reviewed position against the exact issued source.",
        ),
    )
    for gap in gaps:
        await append_review_assertion(
            db, organization_id=organization_id, pursuit_id=pursuit_id,
            run_id=run.id, membership_id=owner_id,
            request=AnalysisReviewAssertionRequest(
                target_kind="GAP", target_id=gap.id,
                new_coverage_state=gap.coverage_state, new_review_state="CONFIRMED",
                corrected_fields={"resolution_category": gap.resolution_category},
                reason="Reviewed resolution authority.",
            ),
        )
    return started, run, current, gaps


async def _approved_scenario(
    db, *, organization_id, pursuit_id, owner_id, run, gap, firm_id, now,
    expert_gap=None, expert_id=None,
):
    records = []
    for selected_gap, candidate_id, is_expert in (
        (gap, firm_id, False), (expert_gap, expert_id, True),
    ):
        if selected_gap is None or candidate_id is None:
            continue
        search = await create_candidate_search(
            db, organization_id=organization_id, pursuit_id=pursuit_id, membership_id=owner_id,
            request=CandidateSearchRequest(analysis_run_id=run.id, gap_id=selected_gap.id),
        )
        match = next(item for item in search.matches if item.candidate_id == candidate_id)
        assert match.qualification_state == "SUPPORTED_BY_EVIDENCE"
        review = await append_candidate_review(
            db, organization_id=organization_id, pursuit_id=pursuit_id,
            search_run_id=search.candidate_search_run_id, match_id=match.candidate_match_id,
            membership_id=owner_id,
            request=CandidateReviewRequest(decision="SHORTLISTED", reason="Exact evidence supports this contribution."),
        )
        participation = await start_participation(
            db, organization_id=organization_id, pursuit_id=pursuit_id,
            candidate_match_id=match.candidate_match_id, membership_id=owner_id,
            request=ParticipationStartRequest(shortlist_decision_id=review.decision_id),
        )
        await append_availability(
            db, organization_id=organization_id, pursuit_id=pursuit_id,
            participation_record_id=participation.participation_record_id, membership_id=owner_id,
            request=AvailabilityFactCreateRequest(
                status="AVAILABLE", capacity_description="One confirmed delivery team",
                confirmation_source="SIGNED_DOCUMENT", observed_at=now,
                valid_until=datetime(2100, 1, 1, tzinfo=timezone.utc),
                window_start=date(2099, 1, 1) if is_expert else None,
                window_end=date(2099, 3, 31) if is_expert else None,
                effort_percent=Decimal("50") if is_expert else None,
            ),
        )
        await append_participation_decision(
            db, organization_id=organization_id, pursuit_id=pursuit_id,
            participation_record_id=participation.participation_record_id, membership_id=owner_id,
            request=ParticipationDecisionCreateRequest(
                state="CONFIRMED", confirmation_source="SIGNED_DOCUMENT", observed_at=now,
                reconfirm_by=datetime(2100, 1, 1, tzinfo=timezone.utc),
                conditions_summary="Confirmed only for this exact contribution.",
            ),
        )
        records.append(participation)
    scenario = await create_team_scenario(
        db, organization_id=organization_id, pursuit_id=pursuit_id, membership_id=owner_id,
        request=TeamScenarioCreateRequest(
            title="Approved evidence team",
            participation_record_ids=[item.participation_record_id for item in records],
        ),
    )
    assert scenario.latest_revision and scenario.latest_revision.assessment_state == "VIABLE"
    approved = await append_team_scenario_decision(
        db, organization_id=organization_id, pursuit_id=pursuit_id,
        scenario_id=scenario.scenario_id, revision_id=scenario.latest_revision.revision_id,
        membership_id=owner_id,
        request=TeamScenarioDecisionCreateRequest(
            decision="APPROVED_FOR_PROPOSAL", reason="Approved for deterministic evidence preparation.",
            explicit_confirmation=True,
        ),
    )
    revision = approved.latest_revision
    assert revision and revision.decisions[-1].decision == "APPROVED_FOR_PROPOSAL"
    return scenario, revision, records[0]


def test_w8_source_and_upload_vertical_slice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        database = support.database_name("w8_vertical")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", CURRENT_HEAD)
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
                owner_b = await connection.fetchval(
                    "SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", organization_b, ids["user_b"]
                )
                world_bank = {
                    key: await _digest(connection, table, row_id)
                    for key, table, row_id in (
                        ("project", "projects", ids["project"]),
                        ("leadership", "project_role_assignments", ids["current_leader"]),
                    )
                }
                legacy_before = await connection.fetchval("SELECT count(*) FROM proposals")
            finally:
                await connection.close()

            monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private"))
            engine = create_async_engine(support.target_url(database), pool_size=8)
            query_count = 0

            def count_query(*_args) -> None:
                nonlocal query_count
                query_count += 1

            event.listen(engine.sync_engine, "before_cursor_execute", count_query)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with sessions() as db:
                    firm = await create_firm(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"], operator=True,
                        payload=FirmCreateRequest(
                            scope="NETWORK_SHARED", display_name="W8 Evidence Partner",
                            canonical_name="w8 evidence partner",
                            country="Uzbekistan", services=["Water design"], capabilities=["Water"],
                            sectors=["Water"], source_type="MANUAL", evidence_state="REVIEWED",
                            network_permission_basis="Reviewed network sharing agreement",
                        ),
                    )
                    reference = await create_project_reference(
                        db, organization_id=organization_a, firm_id=firm.firm_id,
                        actor_user_id=ids["user_a"], operator=True,
                        payload=ProjectReferenceCreateRequest(
                            project_name="Completed water contract", client_name="Public water authority",
                            country="Uzbekistan", service="Water design", sector="Water",
                            role="JV_MEMBER", contract_share_percent=Decimal("40"),
                            contract_value=Decimal("1200000"), contract_currency="USD",
                            value_basis="CONTRACT_TOTAL", start_date="2023-01-01",
                            completion_date="2024-12-31", completion_state="COMPLETED",
                            relevant_scope="Water design", evidence_provenance={"source": "reviewed structured record"},
                            evidence_state="VERIFIED",
                        ),
                    )
                    expert = await create_expert(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"], operator=True,
                        payload=ExpertCreateRequest(
                            scope="NETWORK_SHARED", display_name="W8 Water Engineer",
                            qualifications=["Civil engineering"], languages=["English"],
                            specializations=["Water design"], consent_state="EXPLICIT_CONSENT",
                            network_permission_basis="Candidate signed network profile consent",
                            evidence_state="REVIEWED", source_provenance={"source": "authorized roster"},
                        ),
                    )
                    cv = await create_cv_version(
                        db, organization_id=organization_a, expert_id=expert.expert_id,
                        actor_user_id=ids["user_a"], operator=True,
                        payload=CVVersionCreateRequest(
                            education=[{"degree": "Civil engineering"}],
                            qualifications=[{"qualification": "Water systems design"}],
                            certifications=[], assignments=[{
                                "project": "Regional water design", "actual_role": "Water Engineer",
                                "start": "2021-01", "end": "2023-01", "scope": "Water network design",
                            }], languages=[{"language": "English", "level": "professional"}],
                            evidence_provenance={"source": "reviewed structured facts"},
                            evidence_state="VERIFIED",
                        ),
                    )
                    source = await get_or_create_source_pursuit(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"],
                        actor_membership_id=owner_a, tender_id=ids["tender"],
                        stage=TenderEngagementStatus.SAVED,
                        legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
                    )
                    issued = "One completed water contract is required. A signed proposal form is required at submission."
                    document = TenderDocument(
                        tender_id=ids["tender"], file_url="w8-issued.pdf", file_type="pdf",
                        source_document_url="https://example.invalid/w8-issued.pdf", source_document_type="RFP",
                        sha256=hashlib.sha256(issued.encode()).hexdigest(), parsed_text=issued,
                    )
                    db.add(document); await db.commit()
                    candidate = await build_analysis_pack_candidate(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                    )
                    started, run, _requirement, gaps = await _completed_analysis(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        owner_id=owner_a, candidate_sha=candidate.candidate_sha256,
                        source_ids=[document.id],
                    )
                    now = datetime.now(timezone.utc)
                    team, revision, participation = await _approved_scenario(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        owner_id=owner_a, run=run, gap=gaps[0], firm_id=firm.firm_id, now=now,
                        expert_gap=gaps[1], expert_id=expert.expert_id,
                    )
                    seal_request = ProposalEvidenceSealRequest(
                        scenario_id=team.scenario_id, revision_id=revision.revision_id,
                        approval_decision_id=revision.decisions[-1].decision_id,
                    )
                    pack = await seal_proposal_evidence_pack(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        membership_id=owner_a, request=seal_request,
                    )
                    assert pack.schema_version == PACK_SCHEMA_VERSION and pack.pack_current
                    assert pack.matrix_row_count == 2 and pack.participant_count == 2
                    assert pack.later_stage_count == 1 and pack.checklist_count == 1
                    categories = {item.category for item in pack.items}
                    assert {"PURSUIT_CONTEXT", "REQUIREMENT", "GAP_ASSESSMENT", "FIRM", "PROJECT_REFERENCE", "EXPERT", "CV_FACTS", "PARTICIPATION_CONFIRMATION", "SOURCE_DOCUMENT", "LATER_STAGE_OBLIGATION", "FORM_OR_REQUIRED_ARTIFACT", "OTHER"} <= categories
                    project_item = next(item for item in pack.items if item.category == "PROJECT_REFERENCE")
                    assert project_item.source_identity == str(reference.reference_id)
                    assert project_item.payload["value_basis"] == "CONTRACT_TOTAL"
                    assert project_item.payload["value_is_firm_share"] is False
                    cv_item = next(item for item in pack.items if item.category == "CV_FACTS")
                    assert cv_item.source_identity == str(cv.cv_version_id)
                    assert cv_item.payload["document_classification"] == "STRUCTURED_CV_FACTS"
                    assert cv_item.payload["source_cv_document_available"] is False
                    assert cv_item.payload["candidate_signed"] is False
                    assert cv_item.payload["original_cv"] is False
                    company_item = next(
                        item for item in pack.items
                        if item.category == "OTHER" and item.source_authority_type == "AnalysisCompanySnapshot"
                    )
                    assert company_item.payload["metadata_promoted_to_verified"] is False
                    assert all(
                        item.payload["provenance_independently_verified"] is False
                        for item in pack.items if item.category == "PARTICIPATION_CONFIRMATION"
                    )
                    assert all("private_notes" not in json.dumps(item.payload) for item in pack.items)

                    exported = {}
                    for kind in ("PDF", "DOCX", "JSON"):
                        exported[kind] = await generate_proposal_evidence_artifact(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            pack_id=pack.pack_id, membership_id=owner_a,
                            request=ProposalEvidenceExportRequest(artifact_type=kind),
                        )
                    _, pdf_path = await resolve_proposal_evidence_artifact(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        artifact_id=exported["PDF"].artifact_id, membership_id=owner_a,
                    )
                    _, docx_path = await resolve_proposal_evidence_artifact(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        artifact_id=exported["DOCX"].artifact_id, membership_id=owner_a,
                    )
                    _, json_path = await resolve_proposal_evidence_artifact(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        artifact_id=exported["JSON"].artifact_id, membership_id=owner_a,
                    )
                    assert pdf_path.read_bytes().startswith(b"%PDF-")
                    assert docx_path.read_bytes().startswith(b"PK")
                    manifest = json.loads(json_path.read_text())
                    rendered = json.dumps(manifest).casefold()
                    assert manifest["disclosure"]["commercial_price_included"] is False
                    assert "our_price" not in rendered and "ai_price" not in rendered

                    query_count = 0
                    workspace = await get_proposal_workspace(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        user_id=ids["user_a"],
                    )
                    assert workspace.workspace_id and len(workspace.packs) == 1
                    assert query_count <= 50
                    with pytest.raises(ProposalEvidenceEligibilityError, match="active"):
                        await seal_proposal_evidence_pack(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            membership_id=owner_b, request=seal_request,
                        )
                    assert await get_proposal_evidence_pack(
                        db, organization_id=organization_b, pursuit_id=source.pursuit.id,
                        pack_id=pack.pack_id,
                    ) is None

                    current_participation = participation
                    await append_availability(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=current_participation.participation_record_id,
                        membership_id=owner_a,
                        request=AvailabilityFactCreateRequest(
                            status="AVAILABLE", capacity_description="Updated capacity fact",
                            confirmation_source="SIGNED_DOCUMENT", observed_at=now + timedelta(minutes=1),
                            valid_until=now + timedelta(days=30),
                            supersedes_fact_id=next(
                                item.payload["availability_fact_id"] for item in pack.items
                                if item.category == "PARTICIPATION_CONFIRMATION"
                                and item.payload["participation_record_id"] == str(current_participation.participation_record_id)
                            ),
                        ),
                    )
                    stale = await get_proposal_evidence_pack(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        pack_id=pack.pack_id,
                    )
                    assert stale and not stale.pack_current
                    with pytest.raises(ProposalEvidenceEligibilityError):
                        await seal_proposal_evidence_pack(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            membership_id=owner_a, request=seal_request,
                        )
                    with pytest.raises(ProposalEvidenceEligibilityError, match="HISTORICAL SNAPSHOT"):
                        await generate_proposal_evidence_artifact(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            pack_id=pack.pack_id, membership_id=owner_a,
                            request=ProposalEvidenceExportRequest(artifact_type="JSON"),
                        )
                    historical = await generate_proposal_evidence_artifact(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        pack_id=pack.pack_id, membership_id=owner_a,
                        request=ProposalEvidenceExportRequest(artifact_type="JSON", historical_snapshot=True),
                    )
                    _, historical_path = await resolve_proposal_evidence_artifact(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        artifact_id=historical.artifact_id, membership_id=owner_a,
                    )
                    assert json.loads(historical_path.read_text())["document_classification"] == "HISTORICAL SNAPSHOT"
                    with pytest.raises(Exception, match="immutable"):
                        await db.execute(text("UPDATE proposal_evidence_packs SET pack_state='SEALED' WHERE id=:id"), {"id": pack.pack_id})
                        await db.commit()
                    await db.rollback()

                    upload = await create_upload_pursuit(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"],
                        actor_membership_id=owner_a,
                    )
                    upload_pack = await persist_private_pack(
                        db, pursuit=upload, membership_id=owner_a,
                        files=[_stage(
                            tmp_path / "w8-upload.pdf", _pdf_bytes(issued),
                            "W8-upload.pdf", PDF_MEDIA_TYPE, PrivateDocumentRole.RFP,
                        )],
                    )

                    async def parsed(_path: Path, _media_type: str):
                        return {"text": f"[[PAGE 1]]\n{issued}", "page_count": 1,
                                "page_count_status": "KNOWN", "state": "READY", "error_code": None,
                                "parser_name": "w8-upload-test"}

                    monkeypatch.setattr(private_service, "scan_with_clamav", lambda _path: "stream: OK")
                    monkeypatch.setattr(private_service, "_parse_private_file", parsed)
                    assert (await process_document_job(db, upload_pack.job_ids[0]))["state"] == "READY"
                    upload_candidate = await build_analysis_pack_candidate(
                        db, organization_id=organization_a, pursuit_id=upload.id,
                    )
                    upload_started, upload_run, _upload_req, upload_gaps = await _completed_analysis(
                        db, organization_id=organization_a, pursuit_id=upload.id, owner_id=owner_a,
                        candidate_sha=upload_candidate.candidate_sha256,
                        private_ids=[upload_candidate.private_versions[0].document_version_id],
                    )
                    upload_team, upload_revision, _ = await _approved_scenario(
                        db, organization_id=organization_a, pursuit_id=upload.id, owner_id=owner_a,
                        run=upload_run, gap=upload_gaps[0], firm_id=firm.firm_id,
                        expert_gap=upload_gaps[1], expert_id=expert.expert_id,
                        now=now + timedelta(minutes=2),
                    )
                    upload_evidence = await seal_proposal_evidence_pack(
                        db, organization_id=organization_a, pursuit_id=upload.id, membership_id=owner_a,
                        request=ProposalEvidenceSealRequest(
                            scenario_id=upload_team.scenario_id,
                            revision_id=upload_revision.revision_id,
                            approval_decision_id=upload_revision.decisions[-1].decision_id,
                        ),
                    )
                    assert upload_evidence.pack_current
                    assert any(item.category == "PRIVATE_DOCUMENT" for item in upload_evidence.items)
                    assert not any(item.category == "SOURCE_DOCUMENT" for item in upload_evidence.items)
                    upload_json = await generate_proposal_evidence_artifact(
                        db, organization_id=organization_a, pursuit_id=upload.id,
                        pack_id=upload_evidence.pack_id, membership_id=owner_a,
                        request=ProposalEvidenceExportRequest(artifact_type="JSON"),
                    )
                    assert upload_json.byte_size > 0

                    membership = await db.get(Membership, owner_a)
                    assert membership is not None
                    membership.state = MembershipState.REVOKED
                    membership.revoked_at = datetime.now(timezone.utc)
                    await db.commit()
                    with pytest.raises(ProposalEvidenceEligibilityError, match="active"):
                        await resolve_proposal_evidence_artifact(
                            db, organization_id=organization_a, pursuit_id=pack.pursuit_id,
                            artifact_id=exported["JSON"].artifact_id, membership_id=owner_a,
                        )

                connection = await support.database_connection(database)
                try:
                    assert await connection.fetchval("SELECT count(*) FROM proposals") == legacy_before
                    for key, table, row_id in (
                        ("project", "projects", ids["project"]),
                        ("leadership", "project_role_assignments", ids["current_leader"]),
                    ):
                        assert await _digest(connection, table, row_id) == world_bank[key]
                finally:
                    await connection.close()
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())
