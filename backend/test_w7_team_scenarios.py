"""Permanent W7 scenario versioning, assessment, staleness, and privacy proofs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.private_storage import PDF_MEDIA_TYPE
from app.models.all_models import TenderDocument
from app.models.base import PrivateDocumentRole, TenderEngagementOrigin, TenderEngagementStatus
from app.models.pursuit_analysis import AnalysisPackItem, AnalysisRun, PursuitGap, PursuitPosition, PursuitRequirement
from app.models.team_scenarios import (
    GAP_ASSESSMENTS,
    PARTICIPANT_TYPES,
    SCENARIO_ASSESSMENTS,
    SCENARIO_DECISIONS,
    TeamScenario,
    TeamScenarioContribution,
    TeamScenarioParticipant,
    TeamScenarioRevision,
)
from app.schemas.candidate_retrieval import (
    CVVersionCreateRequest,
    CandidateReviewRequest,
    CandidateSearchRequest,
    ExpertCreateRequest,
    FirmCreateRequest,
    ProjectReferenceCreateRequest,
)
from app.schemas.participation import (
    AvailabilityFactCreateRequest,
    InterestFactCreateRequest,
    ParticipationDecisionCreateRequest,
    ParticipationStartRequest,
)
from app.schemas.team_scenarios import (
    TeamScenarioCreateRequest,
    TeamScenarioDecisionCreateRequest,
    TeamScenarioRevisionCreateRequest,
)
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
from app.services.participation import (
    append_availability,
    append_interest,
    append_participation_decision,
    get_participation,
    start_participation,
)
from app.services.private_documents import build_analysis_pack_candidate, persist_private_pack, process_document_job
from app.services.pursuit_analysis import append_review_assertion, create_analysis_run
from app.services.pursuits import create_upload_pursuit, get_or_create_source_pursuit
from app.services.team_scenarios import (
    NONCANDIDATE_RESOLUTIONS,
    TeamScenarioEligibilityError,
    _contribution_issue_specs,
    _fully_supports,
    append_team_scenario_decision,
    create_team_scenario,
    get_proposal_handoff,
    get_team_scenario,
    list_team_scenarios,
    revise_team_scenario,
)
from scripts import test_s0_5b4_baseline as support
from test_w2_organization_pursuit_foundation import W1_HEAD, _digest, _seed_w1
from test_w3_private_document_foundation import _pdf_bytes, _stage
from test_w6_participation import W6_HEAD


W7_HEAD = "20260930_0001_w7_team_scenarios"
CURRENT_HEAD = "20261008_0001_r3_pending_invitations"


def test_w7_model_and_semantic_contracts() -> None:
    assert set(SCENARIO_ASSESSMENTS) == {"DRAFT", "NEEDS_REVIEW", "BLOCKED", "VIABLE"}
    assert set(GAP_ASSESSMENTS) == {"COVERED", "PARTIAL", "UNRESOLVED", "BLOCKED", "NEEDS_REVIEW"}
    assert set(PARTICIPANT_TYPES) == {"PARTNER_FIRM", "EXPERT"}
    assert set(SCENARIO_DECISIONS) == {"PREFERRED", "REJECTED", "APPROVED_FOR_PROPOSAL"}
    assert NONCANDIDATE_RESOLUTIONS == {"COMPANY_EVIDENCE", "CLARIFICATION", "HUMAN_INTERPRETATION"}
    assert not any(name in TeamScenario.__table__.c for name in ("participants", "composition", "assessment_state"))
    assert "selection_sha256" in TeamScenarioRevision.__table__.c
    assert "shortlist_decision_state_snapshot" in TeamScenarioContribution.__table__.c
    assert any(item.name == "uq_team_participant_revision_expert" for item in TeamScenarioParticipant.__table__.constraints)
    assert any(item.name == "uq_team_participant_revision_firm" for item in TeamScenarioParticipant.__table__.constraints)
    with pytest.raises(ValueError, match="blank"):
        TeamScenarioCreateRequest(title="   ")


def test_w7_migration_from_w6_is_reversible_and_drift_free() -> None:
    async def scenario() -> None:
        database = support.database_name("w7_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W6_HEAD)
            await asyncio.to_thread(support.alembic, database, "upgrade", W7_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT version_num FROM alembic_version") == W7_HEAD
                for table in (
                    "team_scenarios", "team_scenario_revisions", "team_scenario_participants",
                    "team_scenario_contributions", "team_scenario_gap_assessments",
                    "team_scenario_issues", "team_scenario_decisions",
                ):
                    assert await connection.fetchval("SELECT to_regclass($1)", table) == table
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", W6_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('team_scenarios')") is None
                assert await connection.fetchval("SELECT to_regclass('candidate_participation_records')") == "candidate_participation_records"
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", W7_HEAD)
            await asyncio.to_thread(support.alembic, database, "upgrade", CURRENT_HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


def test_w7_scenarios_are_reproducible_strict_private_and_origin_neutral(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        database = support.database_name("w7_authority")
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
                preserved_world_bank = {
                    label: await _digest(connection, table, row_id)
                    for label, table, row_id in (
                        ("project", "projects", ids["project"]),
                        ("leader", "project_role_assignments", ids["current_leader"]),
                    )
                }
            finally:
                await connection.close()

            engine = create_async_engine(support.target_url(database), pool_size=8)
            query_count = 0

            def count_query(*_args) -> None:
                nonlocal query_count
                query_count += 1

            event.listen(engine.sync_engine, "before_cursor_execute", count_query)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with sessions() as db:
                    source = await get_or_create_source_pursuit(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"],
                        actor_membership_id=owner_a, tender_id=ids["tender"],
                        stage=TenderEngagementStatus.SAVED,
                        legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
                    )
                    issued = (
                        "A partner firm may contribute completed water contracts. "
                        "A Water Engineer is required from 2099-01-01 to 2099-03-31. "
                        "A Deputy Water Engineer is required from 2099-02-01 to 2099-04-30."
                    )
                    document = TenderDocument(
                        tender_id=ids["tender"], file_url="w7-issued.pdf", file_type="pdf",
                        source_document_url="https://example.invalid/w7-issued.pdf", source_document_type="RFP",
                        sha256=hashlib.sha256(issued.encode()).hexdigest(), parsed_text=issued,
                    )
                    db.add(document)
                    await db.commit()
                    candidate = await build_analysis_pack_candidate(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                    )
                    started = await create_analysis_run(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        membership_id=owner_a,
                        request=PursuitAnalysisStartRequest(
                            candidate_sha256=candidate.candidate_sha256, analysis_language="en",
                            source_document_ids=[document.id],
                        ),
                    )
                    run = await db.get(AnalysisRun, started.analysis_run_id)
                    pack_item = await db.scalar(select(AnalysisPackItem).where(AnalysisPackItem.pack_id == started.analysis_pack_id))
                    assert run and pack_item
                    run.status = "COMPLETED"
                    run.result_completeness = "FULL"
                    run.completed_at = datetime.now(timezone.utc)
                    requirements = [
                        PursuitRequirement(
                            analysis_run_id=run.id, pack_item_id=pack_item.id, source_span=f"{index}:{index + 20}",
                            source_locator={"page_number": 1}, original_quote="Partner contribution is allowed.",
                            source_context=None, normalized_requirement=f"Completed water contract {index + 1}",
                            category="WATER", requirement_type="CORPORATE_EXPERIENCE", stage_scope="ELIGIBILITY",
                            distinction="MANDATORY", predicate_json={"operator": ">=", "threshold": 1, "unit": "contracts"},
                            contribution_rule="Partner firm contribution is permitted", coverage_state="EVIDENCE_MISSING",
                            review_state="PROVISIONAL", extraction_confidence=0.9, generated_interpretation=None,
                        ) for index in range(2)
                    ]
                    positions = [
                        PursuitPosition(
                            analysis_run_id=run.id, pack_item_id=pack_item.id, title=title, quantity=1,
                            distinction="MANDATORY", education_qualification="Civil engineering",
                            general_experience=None, specific_experience="Water design", relevant_assignments="Water design",
                            languages=["English"], certifications=[], location_travel=None, expected_effort="50%",
                            assignment_dates=dates, source_span=f"{60 + index}:{90 + index}",
                            source_locator={"page_number": 1}, original_quote=f"{title} is required.", source_context=None,
                            coverage_state="EVIDENCE_MISSING", review_state="PROVISIONAL",
                            extraction_confidence=0.9, generated_interpretation=None,
                        ) for index, (title, dates) in enumerate((
                            ("Water Engineer", "2099-01-01 to 2099-03-31"),
                            ("Deputy Water Engineer", "2099-02-01 to 2099-04-30"),
                        ))
                    ]
                    db.add_all([*requirements, *positions])
                    await db.flush()
                    gaps = [
                        *[
                            PursuitGap(
                                analysis_run_id=run.id, requirement_id=item.id, position_id=None,
                                source_pack_item_id=pack_item.id, missing_contribution=item.normalized_requirement,
                                coverage_state="EVIDENCE_MISSING", resolution_category="PARTNER_FIRM",
                                review_state="PROVISIONAL", rationale="Partner evidence is required.",
                            ) for item in requirements
                        ],
                        *[
                            PursuitGap(
                                analysis_run_id=run.id, requirement_id=None, position_id=item.id,
                                source_pack_item_id=pack_item.id, missing_contribution=item.title,
                                coverage_state="EVIDENCE_MISSING", resolution_category="EXPERT",
                                review_state="PROVISIONAL", rationale="Expert evidence is required.",
                            ) for item in positions
                        ],
                    ]
                    db.add_all(gaps)
                    await db.commit()
                    for gap in gaps:
                        await append_review_assertion(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            run_id=run.id, membership_id=owner_a,
                            request=AnalysisReviewAssertionRequest(
                                target_kind="GAP", target_id=gap.id, new_coverage_state="EVIDENCE_MISSING",
                                new_review_state="CONFIRMED", corrected_fields={}, reason="Reviewed exact current-stage Gap.",
                            ),
                        )

                    firm = await create_firm(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"], operator=False,
                        payload=FirmCreateRequest(
                            scope="ORGANIZATION_PRIVATE", canonical_name="Aqua Scenario Partner",
                            display_name="Aqua Scenario Partner", country="Uzbekistan", services=["Water design"],
                            capabilities=["Water"], sectors=["Water"], source_type="MANUAL", evidence_state="REVIEWED",
                        ),
                    )
                    await create_project_reference(
                        db, organization_id=organization_a, firm_id=firm.firm_id,
                        actor_user_id=ids["user_a"], operator=False,
                        payload=ProjectReferenceCreateRequest(
                            project_name="Completed water contract", country="Uzbekistan", service="Water design",
                            sector="Water", role="JV_MEMBER", contract_share_percent=Decimal("40"),
                            value_basis="FIRM_SHARE", start_date="2024-01-01", completion_date="2025-01-01",
                            completion_state="COMPLETED", relevant_scope="Water design",
                            evidence_provenance={"source": "completion record"}, evidence_state="VERIFIED",
                        ),
                    )
                    expert = await create_expert(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"], operator=True,
                        payload=ExpertCreateRequest(
                            scope="NETWORK_SHARED", display_name="Shared Scenario Engineer",
                            qualifications=["Civil engineering"], languages=["English"],
                            specializations=["Water design"], consent_state="EXPLICIT_CONSENT",
                            network_permission_basis="signed network profile consent", evidence_state="REVIEWED",
                            source_provenance={"consent": "recorded"},
                        ),
                    )
                    await create_cv_version(
                        db, organization_id=organization_a, expert_id=expert.expert_id,
                        actor_user_id=ids["user_a"], operator=True,
                        payload=CVVersionCreateRequest(
                            education=[{"degree": "Civil engineering"}], qualifications=[{"qualification": "Water design"}],
                            certifications=[], assignments=[{"project": "Water design", "actual_role": "Water Engineer"}],
                            languages=[{"language": "English"}], evidence_provenance={"source": "reviewed CV"},
                            evidence_state="VERIFIED",
                        ),
                    )

                    participation_ids = []
                    candidate_match_ids = []
                    firm_record_ids = []
                    expert_record_ids = []
                    now = datetime.now(timezone.utc)
                    for gap in gaps:
                        search = await create_candidate_search(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            membership_id=owner_a, request=CandidateSearchRequest(analysis_run_id=run.id, gap_id=gap.id),
                        )
                        candidate_id = firm.firm_id if gap.requirement_id else expert.expert_id
                        match = next(item for item in search.matches if item.candidate_id == candidate_id)
                        candidate_match_ids.append(match.candidate_match_id)
                        assert match.qualification_state == "SUPPORTED_BY_EVIDENCE"
                        review = await append_candidate_review(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            search_run_id=search.candidate_search_run_id, match_id=match.candidate_match_id,
                            membership_id=owner_a,
                            request=CandidateReviewRequest(decision="SHORTLISTED", reason="Evidence supports this exact contribution."),
                        )
                        record = await start_participation(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            candidate_match_id=match.candidate_match_id, membership_id=owner_a,
                            request=ParticipationStartRequest(shortlist_decision_id=review.decision_id),
                        )
                        participation_ids.append(record.participation_record_id)
                        if record.candidate_kind == "FIRM":
                            firm_record_ids.append(record.participation_record_id)
                            availability_request = AvailabilityFactCreateRequest(
                                status="AVAILABLE", capacity_description="One delivery team", confirmation_source="SIGNED_DOCUMENT",
                                observed_at=now, valid_until=now + timedelta(days=30),
                            )
                        else:
                            expert_record_ids.append(record.participation_record_id)
                            start, end = record.assignment_dates.split(" to ")
                            availability_request = AvailabilityFactCreateRequest(
                                status="AVAILABLE", window_start=start, window_end=end, effort_percent=Decimal("50"),
                                capacity_description="50 percent assignment", confirmation_source="SIGNED_DOCUMENT",
                                observed_at=now, valid_until=now + timedelta(days=30),
                            )
                        await append_availability(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=record.participation_record_id, membership_id=owner_a,
                            request=availability_request,
                        )
                        await append_participation_decision(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=record.participation_record_id, membership_id=owner_a,
                            request=ParticipationDecisionCreateRequest(
                                state="CONFIRMED", confirmation_source="SIGNED_DOCUMENT", observed_at=now,
                                reconfirm_by=now + timedelta(days=30), conditions_summary="Confirmed for the recorded contribution.",
                            ),
                        )

                    lineage_connection = await support.database_connection(database)
                    try:
                        preserved_w4_w5_w6 = {
                            "gap": await _digest(lineage_connection, "pursuit_analysis_gaps", gaps[0].id),
                            "match": await _digest(lineage_connection, "candidate_matches", candidate_match_ids[0]),
                            "participation": await _digest(
                                lineage_connection, "candidate_participation_records", participation_ids[0]
                            ),
                        }
                    finally:
                        await lineage_connection.close()

                    scenario_a = await create_team_scenario(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id, membership_id=owner_a,
                        request=TeamScenarioCreateRequest(title="Evidence-backed team A", participation_record_ids=participation_ids),
                    )
                    revision_a = scenario_a.latest_revision
                    assert revision_a and revision_a.assessment_state == "VIABLE" and revision_a.scenario_current
                    assert revision_a.gap_count == revision_a.covered_gap_count == 4
                    assert revision_a.participant_count == revision_a.confirmed_participant_count == 2
                    assert sorted(len(item.contributions) for item in revision_a.participants) == [2, 2]
                    assert all(item.review_assertion_id for item in revision_a.gap_assessments)
                    assert all(
                        contribution.shortlist_decision_state == "SHORTLISTED"
                        for participant in revision_a.participants for contribution in participant.contributions
                    )
                    assert any(
                        evidence["type"] == "PROJECT_REFERENCE"
                        for participant in revision_a.participants for contribution in participant.contributions
                        for evidence in contribution.evidence_identities
                    )
                    assert any(
                        evidence["type"] == "CV_VERSION"
                        for participant in revision_a.participants for contribution in participant.contributions
                        for evidence in contribution.evidence_identities
                    )

                    draft = await create_team_scenario(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id, membership_id=owner_a,
                        request=TeamScenarioCreateRequest(title="Planning alternative", participation_record_ids=[]),
                    )
                    assert draft.latest_revision and draft.latest_revision.assessment_state == "DRAFT"
                    query_count = 0
                    alternatives = await list_team_scenarios(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                    )
                    assert len(alternatives) == 2
                    assert query_count <= 40
                    assert await list_team_scenarios(
                        db, organization_id=organization_b, pursuit_id=source.pursuit.id,
                    ) == []
                    assert await get_team_scenario(
                        db, organization_id=organization_b, pursuit_id=source.pursuit.id,
                        scenario_id=scenario_a.scenario_id,
                    ) is None

                    preferred = await append_team_scenario_decision(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        scenario_id=draft.scenario_id, revision_id=draft.latest_revision.revision_id,
                        membership_id=owner_a,
                        request=TeamScenarioDecisionCreateRequest(
                            decision="PREFERRED", reason="Retain this alternative for planning.",
                        ),
                    )
                    assert preferred.latest_revision and preferred.latest_revision.decisions[-1].decision == "PREFERRED"
                    with pytest.raises(TeamScenarioEligibilityError, match="explicit confirmation"):
                        await append_team_scenario_decision(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            scenario_id=scenario_a.scenario_id, revision_id=revision_a.revision_id,
                            membership_id=owner_a,
                            request=TeamScenarioDecisionCreateRequest(
                                decision="APPROVED_FOR_PROPOSAL", reason="Approve exact viable team.",
                            ),
                        )
                    approved = await append_team_scenario_decision(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        scenario_id=scenario_a.scenario_id, revision_id=revision_a.revision_id,
                        membership_id=owner_a,
                        request=TeamScenarioDecisionCreateRequest(
                            decision="APPROVED_FOR_PROPOSAL", reason="Approve exact viable team.", explicit_confirmation=True,
                        ),
                    )
                    assert approved.latest_revision and approved.latest_revision.decisions[-1].decision == "APPROVED_FOR_PROPOSAL"
                    handoff = await get_proposal_handoff(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        scenario_id=scenario_a.scenario_id, revision_id=revision_a.revision_id,
                    )
                    assert handoff.revision_id == revision_a.revision_id
                    assert handoff.analysis_run_id == run.id and handoff.analysis_pack_id == started.analysis_pack_id

                    first_expert = await get_participation(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record_ids[0],
                    )
                    assert first_expert and first_expert.latest_availability
                    start, end = first_expert.assignment_dates.split(" to ")
                    await append_availability(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record_ids[0], membership_id=owner_a,
                        request=AvailabilityFactCreateRequest(
                            status="AVAILABLE", window_start=start, window_end=end, effort_percent=Decimal("50"),
                            capacity_description="50 percent assignment", confirmation_source="SIGNED_DOCUMENT",
                            observed_at=now + timedelta(minutes=1), valid_until=now + timedelta(days=30),
                            supersedes_fact_id=first_expert.latest_availability.fact_id,
                        ),
                    )
                    stale = await get_team_scenario(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        scenario_id=scenario_a.scenario_id,
                    )
                    assert stale and stale.latest_revision and not stale.latest_revision.scenario_current
                    with pytest.raises(TeamScenarioEligibilityError, match="stale or non-VIABLE"):
                        await get_proposal_handoff(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            scenario_id=scenario_a.scenario_id, revision_id=revision_a.revision_id,
                        )
                    revised = await revise_team_scenario(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        scenario_id=scenario_a.scenario_id, membership_id=owner_a,
                        request=TeamScenarioRevisionCreateRequest(participation_record_ids=participation_ids),
                    )
                    assert revised.latest_revision and revised.latest_revision.version_number == 2
                    assert revised.latest_revision.assessment_state == "VIABLE"

                    for record_id in expert_record_ids:
                        current = await get_participation(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=record_id,
                        )
                        assert current and current.assignment_dates and current.latest_availability
                        window_start, window_end = current.assignment_dates.split(" to ")
                        await append_availability(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=record_id, membership_id=owner_a,
                            request=AvailabilityFactCreateRequest(
                                status="AVAILABLE", window_start=window_start, window_end=window_end,
                                effort_percent=Decimal("70"), capacity_description="70 percent assignment",
                                confirmation_source="SIGNED_DOCUMENT", observed_at=now + timedelta(minutes=2),
                                valid_until=now + timedelta(days=30), supersedes_fact_id=current.latest_availability.fact_id,
                            ),
                        )
                    overallocated = await revise_team_scenario(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        scenario_id=scenario_a.scenario_id, membership_id=owner_a,
                        request=TeamScenarioRevisionCreateRequest(participation_record_ids=participation_ids),
                    )
                    assert overallocated.latest_revision and overallocated.latest_revision.assessment_state == "BLOCKED"
                    assert "EXPERT_DOUBLE_COUNT" in {item.issue_code for item in overallocated.latest_revision.issues}

                    for record_id in expert_record_ids:
                        current = await get_participation(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=record_id,
                        )
                        assert current and current.assignment_dates and current.latest_availability
                        window_start, window_end = current.assignment_dates.split(" to ")
                        await append_availability(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=record_id, membership_id=owner_a,
                            request=AvailabilityFactCreateRequest(
                                status="AVAILABLE", window_start=window_start, window_end=window_end,
                                capacity_description="Effort pending", confirmation_source="SIGNED_DOCUMENT",
                                observed_at=now + timedelta(minutes=3), valid_until=now + timedelta(days=30),
                                supersedes_fact_id=current.latest_availability.fact_id,
                            ),
                        )
                    unknown_effort = await revise_team_scenario(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        scenario_id=scenario_a.scenario_id, membership_id=owner_a,
                        request=TeamScenarioRevisionCreateRequest(participation_record_ids=participation_ids),
                    )
                    assert unknown_effort.latest_revision and unknown_effort.latest_revision.assessment_state == "NEEDS_REVIEW"
                    assert "UNKNOWN_EFFORT" in {item.issue_code for item in unknown_effort.latest_revision.issues}

                    for record_id in expert_record_ids:
                        current = await get_participation(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=record_id,
                        )
                        assert current and current.assignment_dates and current.latest_availability
                        window_start, window_end = current.assignment_dates.split(" to ")
                        await append_availability(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=record_id, membership_id=owner_a,
                            request=AvailabilityFactCreateRequest(
                                status="AVAILABLE", window_start=window_start, window_end=window_end,
                                capacity_description="Full-time assignment", confirmation_source="SIGNED_DOCUMENT",
                                observed_at=now + timedelta(minutes=4), valid_until=now + timedelta(days=30),
                                supersedes_fact_id=current.latest_availability.fact_id,
                            ),
                        )
                    full_time = await revise_team_scenario(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        scenario_id=scenario_a.scenario_id, membership_id=owner_a,
                        request=TeamScenarioRevisionCreateRequest(participation_record_ids=participation_ids),
                    )
                    assert full_time.latest_revision and full_time.latest_revision.assessment_state == "BLOCKED"
                    assert "CONCURRENT_FULL_TIME_CONFLICT" in {item.issue_code for item in full_time.latest_revision.issues}

                    for index, record_id in enumerate(expert_record_ids):
                        current = await get_participation(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=record_id,
                        )
                        assert current and current.assignment_dates and current.latest_availability
                        window_start, window_end = current.assignment_dates.split(" to ")
                        await append_availability(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=record_id, membership_id=owner_a,
                            request=AvailabilityFactCreateRequest(
                                status="AVAILABLE", window_start=("2098-01-01" if index == 0 else window_start),
                                window_end=("2098-02-01" if index == 0 else window_end), effort_percent=Decimal("50"),
                                capacity_description="50 percent assignment", confirmation_source="SIGNED_DOCUMENT",
                                observed_at=now + timedelta(minutes=5), valid_until=now + timedelta(days=30),
                                supersedes_fact_id=current.latest_availability.fact_id,
                            ),
                        )
                    no_overlap = await revise_team_scenario(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        scenario_id=scenario_a.scenario_id, membership_id=owner_a,
                        request=TeamScenarioRevisionCreateRequest(participation_record_ids=participation_ids),
                    )
                    assert no_overlap.latest_revision and no_overlap.latest_revision.assessment_state == "BLOCKED"
                    assert "NO_WINDOW_OVERLAP" in {item.issue_code for item in no_overlap.latest_revision.issues}

                    current = await get_participation(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record_ids[0],
                    )
                    assert current and current.latest_availability
                    await append_availability(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record_ids[0], membership_id=owner_a,
                        request=AvailabilityFactCreateRequest(
                            status="AVAILABLE", window_start="2099-02-01", window_end="2099-03-31",
                            effort_percent=Decimal("50"), capacity_description="50 percent assignment",
                            confirmation_source="SIGNED_DOCUMENT", observed_at=now + timedelta(minutes=6),
                            valid_until=now + timedelta(days=30), supersedes_fact_id=current.latest_availability.fact_id,
                        ),
                    )
                    partial = await revise_team_scenario(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        scenario_id=scenario_a.scenario_id, membership_id=owner_a,
                        request=TeamScenarioRevisionCreateRequest(participation_record_ids=participation_ids),
                    )
                    assert partial.latest_revision and partial.latest_revision.assessment_state == "NEEDS_REVIEW"
                    assert "PARTIAL_WINDOW" in {item.issue_code for item in partial.latest_revision.issues}

                    current = await get_participation(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record_ids[0],
                    )
                    assert current and current.latest_availability
                    await append_availability(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record_ids[0], membership_id=owner_a,
                        request=AvailabilityFactCreateRequest(
                            status="AVAILABLE", window_start="2099-01-01", window_end="2099-03-31",
                            effort_percent=Decimal("50"), capacity_description="50 percent assignment",
                            confirmation_source="SIGNED_DOCUMENT", observed_at=now - timedelta(days=2),
                            valid_until=now - timedelta(days=1), supersedes_fact_id=current.latest_availability.fact_id,
                        ),
                    )
                    expired = await revise_team_scenario(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        scenario_id=scenario_a.scenario_id, membership_id=owner_a,
                        request=TeamScenarioRevisionCreateRequest(participation_record_ids=participation_ids),
                    )
                    assert expired.latest_revision and expired.latest_revision.assessment_state == "BLOCKED"
                    assert "EXPIRED_AVAILABILITY" in {item.issue_code for item in expired.latest_revision.issues}

                    current = await get_participation(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record_ids[0],
                    )
                    assert current and current.latest_availability
                    await append_availability(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record_ids[0], membership_id=owner_a,
                        request=AvailabilityFactCreateRequest(
                            status="AVAILABLE", window_start="2099-01-01", window_end="2099-03-31",
                            effort_percent=Decimal("50"), capacity_description="50 percent assignment",
                            confirmation_source="SIGNED_DOCUMENT", observed_at=now + timedelta(minutes=7),
                            valid_until=now + timedelta(days=30), supersedes_fact_id=current.latest_availability.fact_id,
                        ),
                    )
                    await append_participation_decision(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record_ids[0], membership_id=owner_a,
                        request=ParticipationDecisionCreateRequest(
                            state="CONFIRMED", confirmation_source="SIGNED_DOCUMENT", observed_at=now - timedelta(days=2),
                            reconfirm_by=now - timedelta(days=1), conditions_summary="Confirmed for the recorded contribution.",
                        ),
                    )
                    reconfirm = await revise_team_scenario(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        scenario_id=scenario_a.scenario_id, membership_id=owner_a,
                        request=TeamScenarioRevisionCreateRequest(participation_record_ids=participation_ids),
                    )
                    assert reconfirm.latest_revision and reconfirm.latest_revision.assessment_state == "BLOCKED"
                    assert "NEEDS_RECONFIRMATION" in {item.issue_code for item in reconfirm.latest_revision.issues}

                    await append_participation_decision(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record_ids[0], membership_id=owner_a,
                        request=ParticipationDecisionCreateRequest(
                            state="TENTATIVE", confirmation_source="CALL", observed_at=now + timedelta(minutes=8),
                            reconfirm_by=now + timedelta(days=30), conditions_summary="Awaiting final reconfirmation.",
                        ),
                    )
                    tentative = await revise_team_scenario(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        scenario_id=scenario_a.scenario_id, membership_id=owner_a,
                        request=TeamScenarioRevisionCreateRequest(participation_record_ids=participation_ids),
                    )
                    assert tentative.latest_revision and tentative.latest_revision.assessment_state == "NEEDS_REVIEW"
                    assert "UNCONFIRMED_PARTICIPANT" in {item.issue_code for item in tentative.latest_revision.issues}

                    await append_participation_decision(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record_ids[0], membership_id=owner_a,
                        request=ParticipationDecisionCreateRequest(
                            state="CONFIRMED", confirmation_source="SIGNED_DOCUMENT", observed_at=now + timedelta(minutes=9),
                            reconfirm_by=now + timedelta(days=30), conditions_summary="Confirmed for the recorded contribution.",
                        ),
                    )
                    for index, record_id in enumerate(expert_record_ids):
                        await append_interest(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=record_id, membership_id=owner_a,
                            request=InterestFactCreateRequest(
                                status="CONDITIONAL", confirmation_source="CALL", observed_at=now + timedelta(minutes=10 + index),
                                valid_until=now + timedelta(days=30), conditions=f"Condition {index + 1}",
                            ),
                        )
                    conflict = await revise_team_scenario(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        scenario_id=scenario_a.scenario_id, membership_id=owner_a,
                        request=TeamScenarioRevisionCreateRequest(participation_record_ids=participation_ids),
                    )
                    assert conflict.latest_revision and conflict.latest_revision.assessment_state == "NEEDS_REVIEW"
                    assert "CONFLICTING_PARTICIPATION_FACTS" in {item.issue_code for item in conflict.latest_revision.issues}

                    unsupported = await get_participation(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=firm_record_ids[0],
                    )
                    assert unsupported
                    unsupported = unsupported.model_copy(update={"w5_qualification_state": "PARTIAL"})
                    specs = _contribution_issue_specs(unsupported)
                    assert ("PARTIAL_CANDIDATE_EVIDENCE", "REVIEW") in specs
                    assert not _fully_supports(unsupported, specs)

                    monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private"))
                    upload = await create_upload_pursuit(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"], actor_membership_id=owner_a,
                    )
                    pack = await persist_private_pack(
                        db, pursuit=upload, membership_id=owner_a,
                        files=[_stage(
                            tmp_path / "w7-upload.pdf", _pdf_bytes("Private uploaded tender for scenario planning."),
                            "W7-upload.pdf", PDF_MEDIA_TYPE, PrivateDocumentRole.RFP,
                        )],
                    )

                    async def parsed(_path: Path, _media_type: str):
                        return {
                            "text": "[[PAGE 1]]\nPrivate uploaded tender for scenario planning.",
                            "page_count": 1, "page_count_status": "KNOWN", "state": "READY",
                            "error_code": None, "parser_name": "w7-upload-test",
                        }

                    monkeypatch.setattr(private_service, "scan_with_clamav", lambda _path: "stream: OK")
                    monkeypatch.setattr(private_service, "_parse_private_file", parsed)
                    assert (await process_document_job(db, pack.job_ids[0]))["state"] == "READY"
                    upload_candidate = await build_analysis_pack_candidate(
                        db, organization_id=organization_a, pursuit_id=upload.id,
                    )
                    upload_started = await create_analysis_run(
                        db, organization_id=organization_a, pursuit_id=upload.id, membership_id=owner_a,
                        request=PursuitAnalysisStartRequest(
                            candidate_sha256=upload_candidate.candidate_sha256, analysis_language="en",
                            private_version_ids=[upload_candidate.private_versions[0].document_version_id],
                        ),
                    )
                    upload_run = await db.get(AnalysisRun, upload_started.analysis_run_id)
                    assert upload_run
                    upload_run.status = "COMPLETED"
                    upload_run.result_completeness = "FULL"
                    upload_run.completed_at = datetime.now(timezone.utc)
                    await db.commit()
                    upload_scenario = await create_team_scenario(
                        db, organization_id=organization_a, pursuit_id=upload.id, membership_id=owner_a,
                        request=TeamScenarioCreateRequest(title="Uploaded pursuit draft", participation_record_ids=[]),
                    )
                    assert upload_scenario.latest_revision
                    assert upload_scenario.latest_revision.assessment_state == "DRAFT"
                    assert upload_scenario.latest_revision.private_provenance_count == 1
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", count_query)
                await engine.dispose()

            connection = await support.database_connection(database)
            try:
                for table in (
                    "team_scenario_revisions", "team_scenario_participants", "team_scenario_contributions",
                    "team_scenario_gap_assessments", "team_scenario_issues", "team_scenario_decisions",
                ):
                    row_id = await connection.fetchval(f"SELECT id FROM {table} LIMIT 1")
                    assert row_id
                    with pytest.raises(Exception, match="append-only"):
                        await connection.execute(f"UPDATE {table} SET created_at=now() WHERE id=$1", row_id)
                    with pytest.raises(Exception, match="append-only"):
                        await connection.execute(f"DELETE FROM {table} WHERE id=$1", row_id)
                scenario_id = await connection.fetchval("SELECT id FROM team_scenarios LIMIT 1")
                with pytest.raises(Exception, match="append-only"):
                    await connection.execute("DELETE FROM team_scenarios WHERE id=$1", scenario_id)
                assert await connection.fetchval(
                    "SELECT count(*) FROM team_scenarios WHERE organization_id=$1", organization_b,
                ) == 0
                assert {
                    label: await _digest(connection, table, row_id)
                    for label, table, row_id in (
                        ("project", "projects", ids["project"]),
                        ("leader", "project_role_assignments", ids["current_leader"]),
                    )
                } == preserved_world_bank
                assert {
                    "gap": await _digest(connection, "pursuit_analysis_gaps", gaps[0].id),
                    "match": await _digest(connection, "candidate_matches", candidate_match_ids[0]),
                    "participation": await _digest(
                        connection, "candidate_participation_records", participation_ids[0]
                    ),
                } == preserved_w4_w5_w6
            finally:
                await connection.close()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())
