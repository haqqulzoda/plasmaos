"""Permanent W6 participation authority, history, freshness, and tenancy proofs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.all_models import TenderDocument
from app.core.config import settings
from app.core.private_storage import PDF_MEDIA_TYPE
from app.models.base import (
    MembershipState,
    PrivateDocumentRole,
    TenderEngagementOrigin,
    TenderEngagementStatus,
)
from app.models.participation import (
    AVAILABILITY_STATES,
    CONFIRMATION_SOURCES,
    INTEREST_STATES,
    PARTICIPATION_STATES,
    CandidateAvailabilityFact,
    CandidateInterestFact,
    CandidateParticipationDecision,
    CandidateParticipationRecord,
)
from app.models.pursuit_analysis import (
    AnalysisPackItem,
    AnalysisRun,
    PursuitGap,
    PursuitPosition,
    PursuitRequirement,
)
from app.models.tenancy import Membership
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
from app.schemas.tenancy import AnalysisReviewAssertionRequest, PursuitAnalysisStartRequest
from app.services.candidate_retrieval import (
    append_candidate_review,
    create_candidate_search,
    create_cv_version,
    create_expert,
    create_firm,
    create_project_reference,
)
from app.services.participation import (
    ParticipationEligibilityError,
    append_availability,
    append_interest,
    append_participation_decision,
    assignment_window_coverage,
    get_participation,
    list_participation,
    start_participation,
)
from app.services import private_documents as private_service
from app.services.private_documents import (
    build_analysis_pack_candidate,
    persist_private_pack,
    process_document_job,
)
from app.services.pursuit_analysis import append_review_assertion, create_analysis_run
from app.services.pursuits import create_upload_pursuit, get_or_create_source_pursuit
from scripts import test_s0_5b4_baseline as support
from test_w2_organization_pursuit_foundation import W1_HEAD, _digest, _seed_w1
from test_w5_candidate_retrieval import W5_HEAD
from test_w3_private_document_foundation import _pdf_bytes, _stage


W6_HEAD = "20260929_0001_w6_participation"
CURRENT_HEAD = "20261010_0001_r3_email_notifications"


def test_w6_semantics_are_separate_private_and_bounded() -> None:
    assert set(AVAILABILITY_STATES) == {
        "UNKNOWN", "TENTATIVE", "AVAILABLE", "PARTIALLY_AVAILABLE", "UNAVAILABLE",
    }
    assert set(INTEREST_STATES) == {"UNKNOWN", "INTERESTED", "CONDITIONAL", "DECLINED"}
    assert set(PARTICIPATION_STATES) == {
        "UNCONFIRMED", "TENTATIVE", "CONFIRMED", "DECLINED", "WITHDRAWN",
    }
    assert "SIGNED_DOCUMENT" in CONFIRMATION_SOURCES
    assert CandidateParticipationRecord.__table__.c.candidate_match_id.unique is None
    assert any(
        constraint.name == "uq_candidate_participation_match"
        for constraint in CandidateParticipationRecord.__table__.constraints
    )
    assert not any(
        name in CandidateParticipationRecord.__table__.c
        for name in ("availability", "interest", "participation_state", "team_scenario_id")
    )
    assert "note" in CandidateAvailabilityFact.__table__.c
    assert "note" in CandidateInterestFact.__table__.c
    assert assignment_window_coverage("2099-01-01 to 2099-03-31", datetime(2098, 12, 1).date(), datetime(2099, 4, 1).date()) == "FULL_WINDOW"
    assert assignment_window_coverage("2099-01-01 to 2099-03-31", datetime(2099, 2, 1).date(), datetime(2099, 4, 1).date()) == "PARTIAL_WINDOW"
    assert assignment_window_coverage("2099-01-01 to 2099-03-31", datetime(2098, 1, 1).date(), datetime(2098, 2, 1).date()) == "NO_OVERLAP"
    assert assignment_window_coverage(None, None, None) == "UNKNOWN_DATES"


def test_w6_migration_from_w5_is_reversible_and_drift_free() -> None:
    async def scenario() -> None:
        database = support.database_name("w6_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W5_HEAD)
            await asyncio.to_thread(support.alembic, database, "upgrade", W6_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT version_num FROM alembic_version") == W6_HEAD
                for table in (
                    "candidate_participation_records", "candidate_availability_facts",
                    "candidate_interest_facts", "candidate_participation_decisions",
                ):
                    assert await connection.fetchval("SELECT to_regclass($1)", table) == table
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", W5_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('candidate_participation_records')") is None
                assert await connection.fetchval("SELECT to_regclass('candidate_matches')") == "candidate_matches"
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", CURRENT_HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


def test_w6_participation_history_freshness_staleness_and_isolation() -> None:
    async def scenario() -> None:
        database = support.database_name("w6_authority")
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
                preserved_before = {
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
                        "A partner firm may contribute one completed water assignment. "
                        "A Water Engineer is required from 2099-01-01 to 2099-03-31."
                    )
                    document = TenderDocument(
                        tender_id=ids["tender"], file_url="w6-issued.pdf", file_type="pdf",
                        source_document_url="https://example.invalid/w6-issued.pdf", source_document_type="RFP",
                        sha256=hashlib.sha256(issued.encode()).hexdigest(), parsed_text=issued,
                    )
                    db.add(document)
                    await db.commit()
                    candidate = await build_analysis_pack_candidate(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id
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
                    pack_item = await db.scalar(
                        select(AnalysisPackItem).where(AnalysisPackItem.pack_id == started.analysis_pack_id)
                    )
                    assert run and pack_item
                    run.status = "COMPLETED"
                    run.result_completeness = "FULL"
                    run.completed_at = datetime.now(timezone.utc)
                    requirement = PursuitRequirement(
                        analysis_run_id=run.id, pack_item_id=pack_item.id,
                        source_span="0:61", source_locator={"page_number": 1},
                        original_quote="A partner firm may contribute one completed water assignment.",
                        source_context=None, normalized_requirement="One completed water assignment",
                        category="WATER", requirement_type="CORPORATE_EXPERIENCE",
                        stage_scope="ELIGIBILITY", distinction="MANDATORY",
                        predicate_json={"operator": ">=", "threshold": 1, "unit": "assignments"},
                        contribution_rule="Partner firm contribution is permitted",
                        coverage_state="EVIDENCE_MISSING", review_state="PROVISIONAL",
                        extraction_confidence=0.9, generated_interpretation=None,
                    )
                    position = PursuitPosition(
                        analysis_run_id=run.id, pack_item_id=pack_item.id, title="Water Engineer", quantity=1,
                        distinction="MANDATORY", education_qualification="Civil engineering degree",
                        general_experience=None, specific_experience="Water design",
                        relevant_assignments="Water design", languages=["English"], certifications=[],
                        location_travel=None, expected_effort="50%", assignment_dates="2099-01-01 to 2099-03-31",
                        source_span="62:123", source_locator={"page_number": 1},
                        original_quote="A Water Engineer is required from 2099-01-01 to 2099-03-31.",
                        source_context=None, coverage_state="EVIDENCE_MISSING", review_state="PROVISIONAL",
                        extraction_confidence=0.9, generated_interpretation=None,
                    )
                    second_position = PursuitPosition(
                        analysis_run_id=run.id, pack_item_id=pack_item.id, title="Deputy Water Engineer", quantity=1,
                        distinction="SCORED", education_qualification="Civil engineering degree",
                        general_experience=None, specific_experience="Water design",
                        relevant_assignments="Water design", languages=["English"], certifications=[],
                        location_travel=None, expected_effort="25%", assignment_dates="2099-02-01 to 2099-04-30",
                        source_span="62:123", source_locator={"page_number": 1},
                        original_quote="A Water Engineer is required from 2099-01-01 to 2099-03-31.",
                        source_context=None, coverage_state="EVIDENCE_MISSING", review_state="PROVISIONAL",
                        extraction_confidence=0.8, generated_interpretation=None,
                    )
                    db.add_all([requirement, position, second_position])
                    await db.flush()
                    firm_gap = PursuitGap(
                        analysis_run_id=run.id, requirement_id=requirement.id, position_id=None,
                        source_pack_item_id=pack_item.id, missing_contribution="One completed water assignment",
                        coverage_state="EVIDENCE_MISSING", resolution_category="PARTNER_FIRM",
                        review_state="PROVISIONAL", rationale="No internal reference was found.",
                    )
                    expert_gap = PursuitGap(
                        analysis_run_id=run.id, requirement_id=None, position_id=position.id,
                        source_pack_item_id=pack_item.id, missing_contribution="Water Engineer",
                        coverage_state="EVIDENCE_MISSING", resolution_category="EXPERT",
                        review_state="PROVISIONAL", rationale="No internal expert was found.",
                    )
                    second_expert_gap = PursuitGap(
                        analysis_run_id=run.id, requirement_id=None, position_id=second_position.id,
                        source_pack_item_id=pack_item.id, missing_contribution="Deputy Water Engineer",
                        coverage_state="EVIDENCE_MISSING", resolution_category="EXPERT",
                        review_state="PROVISIONAL", rationale="A second reviewed expert contribution is required.",
                    )
                    db.add_all([firm_gap, expert_gap, second_expert_gap])
                    await db.commit()
                    firm_assertion = await append_review_assertion(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        run_id=run.id, membership_id=owner_a,
                        request=AnalysisReviewAssertionRequest(
                            target_kind="GAP", target_id=firm_gap.id,
                            new_coverage_state="EVIDENCE_MISSING", new_review_state="CONFIRMED",
                            corrected_fields={}, reason="Reviewed partner contribution gap.",
                        ),
                    )
                    expert_assertion = await append_review_assertion(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        run_id=run.id, membership_id=owner_a,
                        request=AnalysisReviewAssertionRequest(
                            target_kind="GAP", target_id=expert_gap.id,
                            new_coverage_state="EVIDENCE_MISSING", new_review_state="CONFIRMED",
                            corrected_fields={}, reason="Reviewed expert gap.",
                        ),
                    )
                    await append_review_assertion(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        run_id=run.id, membership_id=owner_a,
                        request=AnalysisReviewAssertionRequest(
                            target_kind="GAP", target_id=second_expert_gap.id,
                            new_coverage_state="EVIDENCE_MISSING", new_review_state="CONFIRMED",
                            corrected_fields={}, reason="Reviewed second expert gap.",
                        ),
                    )
                    assert firm_assertion.assertion_id and expert_assertion.assertion_id

                    firm = await create_firm(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"], operator=False,
                        payload=FirmCreateRequest(
                            scope="ORGANIZATION_PRIVATE", canonical_name="Aqua Participation",
                            display_name="Aqua Participation", country="Uzbekistan",
                            services=["Water design"], capabilities=["Water"], sectors=["Water"],
                            source_type="MANUAL", evidence_state="REVIEWED",
                        ),
                    )
                    await create_project_reference(
                        db, organization_id=organization_a, firm_id=firm.firm_id,
                        actor_user_id=ids["user_a"], operator=False,
                        payload=ProjectReferenceCreateRequest(
                            project_name="Water assignment", country="Uzbekistan", service="Water design",
                            sector="Water", role="JV_MEMBER", contract_share_percent=Decimal("40"),
                            value_basis="FIRM_SHARE", start_date="2024-01-01", completion_date="2025-01-01",
                            completion_state="COMPLETED", relevant_scope="Water design",
                            evidence_provenance={"source": "completion record"}, evidence_state="VERIFIED",
                        ),
                    )
                    expert = await create_expert(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"], operator=True,
                        payload=ExpertCreateRequest(
                            scope="NETWORK_SHARED", display_name="Shared Water Engineer",
                            qualifications=["Civil engineering"], languages=["English"],
                            specializations=["Water design"], consent_state="EXPLICIT_CONSENT",
                            network_permission_basis="signed network profile consent",
                            evidence_state="REVIEWED", source_provenance={"consent": "recorded"},
                        ),
                    )
                    await create_cv_version(
                        db, organization_id=organization_a, expert_id=expert.expert_id,
                        actor_user_id=ids["user_a"], operator=True,
                        payload=CVVersionCreateRequest(
                            education=[{"degree": "Civil engineering"}],
                            qualifications=[{"qualification": "Water design"}], certifications=[],
                            assignments=[{"project": "Water assignment", "actual_role": "Water Engineer", "scope": "Water design"}],
                            languages=[{"language": "English"}],
                            evidence_provenance={"source": "reviewed CV"}, evidence_state="VERIFIED",
                        ),
                    )
                    firm_search = await create_candidate_search(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        membership_id=owner_a,
                        request=CandidateSearchRequest(analysis_run_id=run.id, gap_id=firm_gap.id),
                    )
                    expert_search = await create_candidate_search(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        membership_id=owner_a,
                        request=CandidateSearchRequest(analysis_run_id=run.id, gap_id=expert_gap.id),
                    )
                    second_expert_search = await create_candidate_search(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        membership_id=owner_a,
                        request=CandidateSearchRequest(analysis_run_id=run.id, gap_id=second_expert_gap.id),
                    )
                    firm_match = next(item for item in firm_search.matches if item.candidate_id == firm.firm_id)
                    expert_match = next(item for item in expert_search.matches if item.candidate_id == expert.expert_id)
                    second_expert_match = next(
                        item for item in second_expert_search.matches if item.candidate_id == expert.expert_id
                    )
                    with pytest.raises(ParticipationEligibilityError, match="SHORTLISTED"):
                        await start_participation(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            candidate_match_id=expert_match.candidate_match_id, membership_id=owner_a,
                            request=ParticipationStartRequest(shortlist_decision_id=uuid4()),
                        )
                    firm_review = await append_candidate_review(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        search_run_id=firm_search.candidate_search_run_id,
                        match_id=firm_match.candidate_match_id, membership_id=owner_a,
                        request=CandidateReviewRequest(decision="SHORTLISTED", reason="Firm evidence is relevant."),
                    )
                    expert_review = await append_candidate_review(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        search_run_id=expert_search.candidate_search_run_id,
                        match_id=expert_match.candidate_match_id, membership_id=owner_a,
                        request=CandidateReviewRequest(decision="SHORTLISTED", reason="Expert evidence is relevant."),
                    )
                    second_expert_review = await append_candidate_review(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        search_run_id=second_expert_search.candidate_search_run_id,
                        match_id=second_expert_match.candidate_match_id, membership_id=owner_a,
                        request=CandidateReviewRequest(
                            decision="SHORTLISTED", reason="Expert is also relevant to the second exact Gap."
                        ),
                    )
                    with pytest.raises(ParticipationEligibilityError, match="current W5 decision"):
                        await start_participation(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            candidate_match_id=expert_match.candidate_match_id, membership_id=owner_a,
                            request=ParticipationStartRequest(shortlist_decision_id=firm_review.decision_id),
                        )
                    firm_record = await start_participation(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        candidate_match_id=firm_match.candidate_match_id, membership_id=owner_a,
                        request=ParticipationStartRequest(shortlist_decision_id=firm_review.decision_id),
                    )
                    expert_record = await start_participation(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        candidate_match_id=expert_match.candidate_match_id, membership_id=owner_a,
                        request=ParticipationStartRequest(shortlist_decision_id=expert_review.decision_id),
                    )
                    second_expert_record = await start_participation(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        candidate_match_id=second_expert_match.candidate_match_id, membership_id=owner_a,
                        request=ParticipationStartRequest(shortlist_decision_id=second_expert_review.decision_id),
                    )
                    assert firm_record.candidate_kind == "FIRM"
                    assert expert_record.candidate_kind == "EXPERT"
                    assert expert_record.shortlist_decision_id == expert_review.decision_id
                    assert expert_record.w5_qualification_state == expert_match.qualification_state
                    assert "private" not in expert_record.model_dump_json().lower()
                    duplicate_projection = await get_participation(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record.participation_record_id,
                    )
                    assert duplicate_projection
                    assert duplicate_projection.same_candidate_record_ids == [
                        second_expert_record.participation_record_id
                    ]

                    # The same consented NETWORK_SHARED identity can be shortlisted by a second
                    # Organization, while the resulting participation authority stays tenant private.
                    source_b = await get_or_create_source_pursuit(
                        db, organization_id=organization_b, actor_user_id=ids["user_b"],
                        actor_membership_id=owner_b, tender_id=ids["tender"],
                        stage=TenderEngagementStatus.SAVED,
                        legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
                    )
                    candidate_b = await build_analysis_pack_candidate(
                        db, organization_id=organization_b, pursuit_id=source_b.pursuit.id
                    )
                    started_b = await create_analysis_run(
                        db, organization_id=organization_b, pursuit_id=source_b.pursuit.id,
                        membership_id=owner_b,
                        request=PursuitAnalysisStartRequest(
                            candidate_sha256=candidate_b.candidate_sha256, analysis_language="en",
                            source_document_ids=[document.id],
                        ),
                    )
                    run_b = await db.get(AnalysisRun, started_b.analysis_run_id)
                    pack_item_b = await db.scalar(
                        select(AnalysisPackItem).where(AnalysisPackItem.pack_id == started_b.analysis_pack_id)
                    )
                    assert run_b and pack_item_b
                    run_b.status = "COMPLETED"
                    run_b.result_completeness = "FULL"
                    run_b.completed_at = datetime.now(timezone.utc)
                    position_b = PursuitPosition(
                        analysis_run_id=run_b.id, pack_item_id=pack_item_b.id,
                        title="Water Engineer", quantity=1, distinction="MANDATORY",
                        education_qualification="Civil engineering degree", general_experience=None,
                        specific_experience="Water design", relevant_assignments="Water design",
                        languages=["English"], certifications=[], location_travel=None,
                        expected_effort="50%", assignment_dates="2099-01-01 to 2099-03-31",
                        source_span="62:123", source_locator={"page_number": 1},
                        original_quote="A Water Engineer is required from 2099-01-01 to 2099-03-31.",
                        source_context=None, coverage_state="EVIDENCE_MISSING", review_state="PROVISIONAL",
                        extraction_confidence=0.9, generated_interpretation=None,
                    )
                    db.add(position_b)
                    await db.flush()
                    gap_b = PursuitGap(
                        analysis_run_id=run_b.id, requirement_id=None, position_id=position_b.id,
                        source_pack_item_id=pack_item_b.id, missing_contribution="Water Engineer",
                        coverage_state="EVIDENCE_MISSING", resolution_category="EXPERT",
                        review_state="PROVISIONAL", rationale="Organization B has a reviewed expert Gap.",
                    )
                    db.add(gap_b)
                    await db.commit()
                    await append_review_assertion(
                        db, organization_id=organization_b, pursuit_id=source_b.pursuit.id,
                        run_id=run_b.id, membership_id=owner_b,
                        request=AnalysisReviewAssertionRequest(
                            target_kind="GAP", target_id=gap_b.id,
                            new_coverage_state="EVIDENCE_MISSING", new_review_state="CONFIRMED",
                            corrected_fields={}, reason="Organization B reviewed its exact Gap.",
                        ),
                    )
                    search_b = await create_candidate_search(
                        db, organization_id=organization_b, pursuit_id=source_b.pursuit.id,
                        membership_id=owner_b,
                        request=CandidateSearchRequest(analysis_run_id=run_b.id, gap_id=gap_b.id),
                    )
                    match_b = next(item for item in search_b.matches if item.candidate_id == expert.expert_id)
                    review_b = await append_candidate_review(
                        db, organization_id=organization_b, pursuit_id=source_b.pursuit.id,
                        search_run_id=search_b.candidate_search_run_id,
                        match_id=match_b.candidate_match_id, membership_id=owner_b,
                        request=CandidateReviewRequest(
                            decision="SHORTLISTED", reason="Organization B independently shortlisted this expert."
                        ),
                    )
                    record_b = await start_participation(
                        db, organization_id=organization_b, pursuit_id=source_b.pursuit.id,
                        candidate_match_id=match_b.candidate_match_id, membership_id=owner_b,
                        request=ParticipationStartRequest(shortlist_decision_id=review_b.decision_id),
                    )
                    private_b = await append_interest(
                        db, organization_id=organization_b, pursuit_id=source_b.pursuit.id,
                        participation_record_id=record_b.participation_record_id, membership_id=owner_b,
                        request=InterestFactCreateRequest(
                            status="INTERESTED", confirmation_source="CUSTOMER_RECORDED",
                            observed_at=datetime.now(timezone.utc), conditions="Organization B only.",
                        ),
                    )
                    assert private_b.latest_interest and private_b.latest_interest.status == "INTERESTED"
                    assert await get_participation(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=record_b.participation_record_id,
                    ) is None

                    now = datetime.now(timezone.utc)
                    with pytest.raises(ParticipationEligibilityError, match="explicit availability window"):
                        await append_availability(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=expert_record.participation_record_id,
                            membership_id=owner_a,
                            request=AvailabilityFactCreateRequest(
                                status="AVAILABLE", confirmation_source="CALL", observed_at=now,
                                valid_until=now + timedelta(days=7),
                            ),
                        )
                    expired = await append_availability(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record.participation_record_id,
                        membership_id=owner_a,
                        request=AvailabilityFactCreateRequest(
                            status="AVAILABLE", window_start="2099-01-01", window_end="2099-03-31",
                            effort_percent=Decimal("50"), confirmation_source="CALL",
                            observed_at=now - timedelta(days=2), valid_until=now - timedelta(days=1),
                            note="raw private note must not be projected",
                        ),
                    )
                    assert expired.latest_availability and expired.latest_availability.effective_status == "EXPIRED"
                    assert expired.assignment_window_coverage == "FULL_WINDOW"
                    assert "raw private note" not in expired.model_dump_json()
                    with pytest.raises(ParticipationEligibilityError, match="unexpired availability"):
                        await append_participation_decision(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=expert_record.participation_record_id,
                            membership_id=owner_a,
                            request=ParticipationDecisionCreateRequest(
                                state="CONFIRMED", confirmation_source="DIRECT_EMAIL", observed_at=now,
                                reconfirm_by=now + timedelta(days=30),
                            ),
                        )
                    available = await append_availability(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record.participation_record_id,
                        membership_id=owner_a,
                        request=AvailabilityFactCreateRequest(
                            status="PARTIALLY_AVAILABLE", window_start="2099-02-01", window_end="2099-03-31",
                            effort_percent=Decimal("50"), confirmation_source="MEETING",
                            observed_at=now, valid_until=now + timedelta(days=7),
                            supersedes_fact_id=expired.latest_availability.fact_id,
                        ),
                    )
                    assert available.assignment_window_coverage == "PARTIAL_WINDOW"
                    interested = await append_interest(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record.participation_record_id,
                        membership_id=owner_a,
                        request=InterestFactCreateRequest(
                            status="CONDITIONAL", confirmation_source="MEETING", observed_at=now,
                            valid_until=now + timedelta(days=14), conditions="Subject to a 50% schedule.",
                        ),
                    )
                    assert interested.latest_interest and interested.latest_interest.status == "CONDITIONAL"
                    tentative = await append_participation_decision(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record.participation_record_id,
                        membership_id=owner_a,
                        request=ParticipationDecisionCreateRequest(
                            state="TENTATIVE", confirmation_source="CALL",
                            observed_at=now - timedelta(days=2), reconfirm_by=now - timedelta(days=1),
                            conditions_summary="Pending schedule review.",
                        ),
                    )
                    assert tentative.latest_participation
                    assert tentative.latest_participation.effective_state == "NEEDS_RECONFIRMATION"
                    with pytest.raises(ParticipationEligibilityError, match="Partial availability"):
                        await append_participation_decision(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=expert_record.participation_record_id,
                            membership_id=owner_a,
                            request=ParticipationDecisionCreateRequest(
                                state="CONFIRMED", confirmation_source="SIGNED_DOCUMENT",
                                observed_at=now, reconfirm_by=now + timedelta(days=30),
                            ),
                        )
                    confirmed = await append_participation_decision(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record.participation_record_id,
                        membership_id=owner_a,
                        request=ParticipationDecisionCreateRequest(
                            state="CONFIRMED", confirmation_source="SIGNED_DOCUMENT",
                            observed_at=now, reconfirm_by=now + timedelta(days=30),
                            conditions_summary="Confirmed for the recorded 50% schedule.",
                        ),
                    )
                    assert confirmed.latest_participation and confirmed.latest_participation.state == "CONFIRMED"
                    with pytest.raises(ParticipationEligibilityError, match="prior tentative or confirmed"):
                        await append_participation_decision(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=firm_record.participation_record_id,
                            membership_id=owner_a,
                            request=ParticipationDecisionCreateRequest(
                                state="WITHDRAWN", confirmation_source="CALL", observed_at=now,
                                reason="No longer pursuing this assignment.",
                            ),
                        )
                    withdrawn = await append_participation_decision(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record.participation_record_id,
                        membership_id=owner_a,
                        request=ParticipationDecisionCreateRequest(
                            state="WITHDRAWN", confirmation_source="CALL", observed_at=now,
                            reason="Candidate withdrew after confirming.",
                        ),
                    )
                    assert withdrawn.latest_participation and withdrawn.latest_participation.state == "WITHDRAWN"

                    # A later W5 rejection makes this immutable trail historical. Positive facts fail;
                    # negative facts remain recordable so real-world history is not lost.
                    await append_candidate_review(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        search_run_id=expert_search.candidate_search_run_id,
                        match_id=expert_match.candidate_match_id, membership_id=owner_a,
                        request=CandidateReviewRequest(decision="REJECTED", reason="Current shortlist changed."),
                    )
                    with pytest.raises(ParticipationEligibilityError, match="SHORTLISTED"):
                        await append_interest(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=expert_record.participation_record_id,
                            membership_id=owner_a,
                            request=InterestFactCreateRequest(
                                status="INTERESTED", confirmation_source="CALL", observed_at=now,
                            ),
                        )
                    historical = await append_interest(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record.participation_record_id,
                        membership_id=owner_a,
                        request=InterestFactCreateRequest(
                            status="DECLINED", confirmation_source="CALL", observed_at=now,
                            conditions="Candidate declined after shortlist changed.",
                        ),
                    )
                    assert historical.upstream_stale
                    assert historical.effective_shortlist_state == "REJECTED"

                    query_count = 0
                    rows = await list_participation(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id
                    )
                    assert query_count <= 16
                    assert {item.participation_record_id for item in rows} == {
                        firm_record.participation_record_id, expert_record.participation_record_id,
                        second_expert_record.participation_record_id,
                    }
                    query_count = 0
                    assert await list_participation(
                        db, organization_id=organization_b, pursuit_id=source.pursuit.id
                    ) == []
                    assert query_count <= 2
                    assert await get_participation(
                        db, organization_id=organization_b, pursuit_id=source.pursuit.id,
                        participation_record_id=expert_record.participation_record_id,
                    ) is None

                    membership = await db.get(Membership, owner_a)
                    assert membership
                    membership.state = MembershipState.REVOKED
                    membership.revoked_at = now
                    membership.activated_at = None
                    await db.commit()
                    with pytest.raises(ParticipationEligibilityError, match="active Organization Membership"):
                        await append_interest(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            participation_record_id=expert_record.participation_record_id,
                            membership_id=owner_a,
                            request=InterestFactCreateRequest(
                                status="DECLINED", confirmation_source="CALL", observed_at=now,
                            ),
                        )
                    membership.state = MembershipState.ACTIVE
                    membership.activated_at = now
                    membership.revoked_at = None
                    await db.commit()
                    assert owner_b != owner_a
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", count_query)
                await engine.dispose()

            connection = await support.database_connection(database)
            try:
                for table in (
                    "candidate_participation_records", "candidate_availability_facts",
                    "candidate_interest_facts", "candidate_participation_decisions",
                ):
                    row_id = await connection.fetchval(f"SELECT id FROM {table} LIMIT 1")
                    assert row_id
                    with pytest.raises(Exception, match="immutable"):
                        await connection.execute(f"UPDATE {table} SET created_at=now() WHERE id=$1", row_id)
                    with pytest.raises(Exception, match="immutable"):
                        await connection.execute(f"DELETE FROM {table} WHERE id=$1", row_id)
                assert await connection.fetchval(
                    "SELECT count(*) FROM candidate_participation_records WHERE organization_id=$1", organization_b
                ) == 1
                preserved_after = {
                    label: await _digest(connection, table, row_id)
                    for label, table, row_id in (
                        ("project", "projects", ids["project"]),
                        ("leader", "project_role_assignments", ids["current_leader"]),
                    )
                }
                assert preserved_after == preserved_before
            finally:
                await connection.close()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


def test_w6_upload_pursuit_uses_the_same_shortlist_authority(tmp_path: Path, monkeypatch) -> None:
    async def scenario() -> None:
        database = support.database_name("w6_upload")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", CURRENT_HEAD)
            connection = await support.database_connection(database)
            try:
                organization_id = await connection.fetchval(
                    "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"]
                )
                membership_id = await connection.fetchval(
                    "SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2",
                    organization_id, ids["user_a"],
                )
            finally:
                await connection.close()

            monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private"))
            engine = create_async_engine(support.target_url(database), pool_size=4)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with sessions() as db:
                    pursuit = await create_upload_pursuit(
                        db, organization_id=organization_id, actor_user_id=ids["user_a"],
                        actor_membership_id=membership_id,
                    )
                    pack = await persist_private_pack(
                        db, pursuit=pursuit, membership_id=membership_id,
                        files=[_stage(
                            tmp_path / "w6-upload.pdf",
                            _pdf_bytes("A Water Engineer is required from 2099-01-01 to 2099-03-31."),
                            "W6-upload.pdf", PDF_MEDIA_TYPE, PrivateDocumentRole.RFP,
                        )],
                    )

                async def parsed(_path: Path, _media_type: str):
                    text = "[[PAGE 1]]\nA Water Engineer is required from 2099-01-01 to 2099-03-31."
                    return {
                        "text": text, "page_count": 1, "page_count_status": "KNOWN",
                        "state": "READY", "error_code": None, "parser_name": "w6-upload-test",
                    }

                monkeypatch.setattr(private_service, "scan_with_clamav", lambda _path: "stream: OK")
                monkeypatch.setattr(private_service, "_parse_private_file", parsed)
                async with sessions() as db:
                    assert (await process_document_job(db, pack.job_ids[0]))["state"] == "READY"
                    candidate = await build_analysis_pack_candidate(
                        db, organization_id=organization_id, pursuit_id=pursuit.id
                    )
                    version_id = candidate.private_versions[0].document_version_id
                    started = await create_analysis_run(
                        db, organization_id=organization_id, pursuit_id=pursuit.id,
                        membership_id=membership_id,
                        request=PursuitAnalysisStartRequest(
                            candidate_sha256=candidate.candidate_sha256, analysis_language="en",
                            private_version_ids=[version_id],
                        ),
                    )
                    run = await db.get(AnalysisRun, started.analysis_run_id)
                    pack_item = await db.scalar(
                        select(AnalysisPackItem).where(AnalysisPackItem.pack_id == started.analysis_pack_id)
                    )
                    assert run and pack_item
                    run.status = "COMPLETED"
                    run.result_completeness = "FULL"
                    run.completed_at = datetime.now(timezone.utc)
                    position = PursuitPosition(
                        analysis_run_id=run.id, pack_item_id=pack_item.id,
                        title="Water Engineer", quantity=1, distinction="MANDATORY",
                        education_qualification="Civil engineering", general_experience=None,
                        specific_experience="Water design", relevant_assignments=None,
                        languages=["English"], certifications=[], location_travel=None,
                        expected_effort="100%", assignment_dates="2099-01-01 to 2099-03-31",
                        source_span="11:75", source_locator={"page_number": 1},
                        original_quote="A Water Engineer is required from 2099-01-01 to 2099-03-31.",
                        source_context=None, coverage_state="EVIDENCE_MISSING", review_state="PROVISIONAL",
                        extraction_confidence=0.9, generated_interpretation=None,
                    )
                    db.add(position)
                    await db.flush()
                    gap = PursuitGap(
                        analysis_run_id=run.id, requirement_id=None, position_id=position.id,
                        source_pack_item_id=pack_item.id, missing_contribution="Water Engineer",
                        coverage_state="EVIDENCE_MISSING", resolution_category="EXPERT",
                        review_state="PROVISIONAL", rationale="Uploaded TOR requires an expert.",
                    )
                    db.add(gap)
                    await db.commit()
                    await append_review_assertion(
                        db, organization_id=organization_id, pursuit_id=pursuit.id,
                        run_id=run.id, membership_id=membership_id,
                        request=AnalysisReviewAssertionRequest(
                            target_kind="GAP", target_id=gap.id,
                            new_coverage_state="EVIDENCE_MISSING", new_review_state="CONFIRMED",
                            corrected_fields={}, reason="Reviewed uploaded-pursuit expert Gap.",
                        ),
                    )
                    expert = await create_expert(
                        db, organization_id=organization_id, actor_user_id=ids["user_a"], operator=False,
                        payload=ExpertCreateRequest(
                            scope="ORGANIZATION_PRIVATE", display_name="Uploaded Pursuit Engineer",
                            qualifications=["Civil engineering"], languages=["English"],
                            specializations=["Water design"], consent_state="NOT_REQUIRED_PRIVATE",
                            evidence_state="REVIEWED", source_provenance={"source": "authorized roster"},
                        ),
                    )
                    await create_cv_version(
                        db, organization_id=organization_id, expert_id=expert.expert_id,
                        actor_user_id=ids["user_a"], operator=False,
                        payload=CVVersionCreateRequest(
                            education=[{"degree": "Civil engineering"}], qualifications=[], certifications=[],
                            assignments=[{"project": "Water design", "actual_role": "Water Engineer"}],
                            languages=[{"language": "English"}],
                            evidence_provenance={"source": "reviewed CV"}, evidence_state="REVIEWED",
                        ),
                    )
                    search = await create_candidate_search(
                        db, organization_id=organization_id, pursuit_id=pursuit.id,
                        membership_id=membership_id,
                        request=CandidateSearchRequest(analysis_run_id=run.id, gap_id=gap.id),
                    )
                    match = next(item for item in search.matches if item.candidate_id == expert.expert_id)
                    review = await append_candidate_review(
                        db, organization_id=organization_id, pursuit_id=pursuit.id,
                        search_run_id=search.candidate_search_run_id,
                        match_id=match.candidate_match_id, membership_id=membership_id,
                        request=CandidateReviewRequest(
                            decision="SHORTLISTED", reason="Uploaded pursuit expert evidence is relevant."
                        ),
                    )
                    record = await start_participation(
                        db, organization_id=organization_id, pursuit_id=pursuit.id,
                        candidate_match_id=match.candidate_match_id, membership_id=membership_id,
                        request=ParticipationStartRequest(shortlist_decision_id=review.decision_id),
                    )
                    current = datetime.now(timezone.utc)
                    projected = await append_availability(
                        db, organization_id=organization_id, pursuit_id=pursuit.id,
                        participation_record_id=record.participation_record_id,
                        membership_id=membership_id,
                        request=AvailabilityFactCreateRequest(
                            status="AVAILABLE", window_start="2099-01-01", window_end="2099-03-31",
                            effort_percent=Decimal("100"), confirmation_source="SIGNED_DOCUMENT",
                            observed_at=current, valid_until=current + timedelta(days=30),
                            supporting_document_version_id=version_id,
                        ),
                    )
                    assert projected.assignment_window_coverage == "FULL_WINDOW"
                    assert projected.latest_availability
                    assert projected.latest_availability.supporting_document_version_id == version_id
                    assert pursuit.source_tender_id is None
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())
