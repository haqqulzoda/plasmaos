"""Permanent W5 candidate authority, retrieval, evidence, and tenancy proofs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.all_models import TenderDocument
from app.models.candidate_retrieval import (
    CVVersion,
    CandidateMatch,
    CandidateReviewDecision,
    CandidateSearchRun,
    Expert,
    Firm,
    ProjectReference,
    QUALIFICATION_STATES,
)
from app.models.base import TenderEngagementOrigin, TenderEngagementStatus
from app.models.pursuit_analysis import (
    AnalysisPackItem,
    AnalysisReviewAssertion,
    AnalysisRun,
    PursuitGap,
    PursuitPosition,
    PursuitRequirement,
)
from app.schemas.candidate_retrieval import (
    CVVersionCreateRequest,
    CandidateReviewRequest,
    CandidateSearchRequest,
    ExpertCreateRequest,
    FirmCreateRequest,
    ProjectReferenceCreateRequest,
)
from app.schemas.tenancy import AnalysisReviewAssertionRequest, PursuitAnalysisStartRequest
from app.services.candidate_retrieval import (
    CandidateEligibilityError,
    append_candidate_review,
    create_candidate_search,
    create_cv_version,
    create_expert,
    create_firm,
    create_project_reference,
    get_candidate_search,
    list_candidate_library,
)
from app.services.private_documents import build_analysis_pack_candidate
from app.services.pursuit_analysis import append_review_assertion, create_analysis_run
from app.services.pursuits import get_or_create_source_pursuit
from scripts import test_s0_5b4_baseline as support
from test_w2_organization_pursuit_foundation import W1_HEAD, _digest, _seed_w1
from test_w4_pursuit_analysis import W4_HEAD


W5_HEAD = "20260928_0001_w5_candidate_retrieval"
CURRENT_HEAD = "20261005_0001_d2_05_eoi_drafts"


def test_w5_semantics_are_separate_and_bounded() -> None:
    assert set(QUALIFICATION_STATES) == {
        "SUPPORTED_BY_EVIDENCE", "PARTIAL", "EVIDENCE_MISSING", "NEEDS_REVIEW", "NOT_RELEVANT",
    }
    assert Firm.__tablename__ != "organizations"
    assert Expert.__tablename__ != "project_role_assignments"
    assert CVVersion.__tablename__ != "tender_documents"
    assert CandidateSearchRun.__table__.c.result_limit.type.python_type is int
    assert not any(name in CandidateMatch.__table__.c for name in ("availability", "commitment", "team_scenario"))


def test_w5_migration_from_w4_is_reversible_and_drift_free() -> None:
    async def scenario() -> None:
        database = support.database_name("w5_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W4_HEAD)
            await asyncio.to_thread(support.alembic, database, "upgrade", W5_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT version_num FROM alembic_version") == W5_HEAD
                for table in (
                    "candidate_firms", "candidate_project_references", "candidate_experts",
                    "candidate_cv_versions", "candidate_search_runs", "candidate_matches",
                    "candidate_review_decisions",
                ):
                    assert await connection.fetchval("SELECT to_regclass($1)", table) == table
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", W4_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('candidate_firms')") is None
                assert await connection.fetchval("SELECT to_regclass('pursuit_analysis_gaps')") == "pursuit_analysis_gaps"
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", W5_HEAD)
            await asyncio.to_thread(support.alembic, database, "upgrade", CURRENT_HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


def test_w5_reviewed_gap_retrieval_evidence_history_and_isolation() -> None:
    async def scenario() -> None:
        database = support.database_name("w5_authority")
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
                        "Joint venture members collectively may satisfy one completed water and sanitation contract. "
                        "A Water Engineer with civil engineering education and water design experience is required."
                    )
                    document = TenderDocument(
                        tender_id=ids["tender"], file_url="w5-issued.pdf", file_type="pdf",
                        source_document_url="https://example.invalid/w5-issued.pdf", source_document_type="RFP",
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
                    pack_item = await db.scalar(select(AnalysisPackItem).where(AnalysisPackItem.pack_id == started.analysis_pack_id))
                    assert run and pack_item
                    run.status = "COMPLETED"
                    run.result_completeness = "FULL"
                    run.completed_at = datetime.now(timezone.utc)
                    requirement = PursuitRequirement(
                        analysis_run_id=run.id, pack_item_id=pack_item.id,
                        source_span="0:78", source_locator={"page_number": 1},
                        original_quote="Joint venture members collectively may satisfy one completed water and sanitation contract.",
                        source_context=None, normalized_requirement="At least one completed water and sanitation contract",
                        category="WATER_SANITATION", requirement_type="CORPORATE_EXPERIENCE",
                        stage_scope="ELIGIBILITY", distinction="MANDATORY",
                        predicate_json={"operator": ">=", "threshold": 1, "unit": "contracts"},
                        contribution_rule="Joint venture members collectively may satisfy this requirement",
                        coverage_state="EVIDENCE_MISSING", review_state="PROVISIONAL",
                        extraction_confidence=0.9, generated_interpretation=None,
                    )
                    position = PursuitPosition(
                        analysis_run_id=run.id, pack_item_id=pack_item.id, title="Water Engineer", quantity=1,
                        distinction="MANDATORY", education_qualification="Civil engineering degree",
                        general_experience=None, specific_experience="Water design experience",
                        relevant_assignments="Water and sanitation design", languages=["English"],
                        certifications=[], location_travel=None, expected_effort=None, assignment_dates=None,
                        source_span="79:160", source_locator={"page_number": 1},
                        original_quote="A Water Engineer with civil engineering education and water design experience is required.",
                        source_context=None, coverage_state="EVIDENCE_MISSING", review_state="PROVISIONAL",
                        extraction_confidence=0.9, generated_interpretation=None,
                    )
                    db.add_all([requirement, position])
                    await db.flush()
                    firm_gap = PursuitGap(
                        analysis_run_id=run.id, requirement_id=requirement.id, position_id=None,
                        source_pack_item_id=pack_item.id, missing_contribution="One comparable water contract",
                        coverage_state="EVIDENCE_MISSING", resolution_category="PARTNER_FIRM",
                        review_state="PROVISIONAL", rationale="No organization evidence was available.",
                    )
                    expert_gap = PursuitGap(
                        analysis_run_id=run.id, requirement_id=None, position_id=position.id,
                        source_pack_item_id=pack_item.id, missing_contribution="Water Engineer",
                        coverage_state="EVIDENCE_MISSING", resolution_category="EXPERT",
                        review_state="PROVISIONAL", rationale="No expert profile was available.",
                    )
                    db.add_all([firm_gap, expert_gap])
                    await db.commit()

                    # Provisional and unsupported categories cannot start retrieval.
                    with pytest.raises(CandidateEligibilityError, match="reviewed"):
                        await create_candidate_search(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            membership_id=owner_a,
                            request=CandidateSearchRequest(analysis_run_id=run.id, gap_id=firm_gap.id),
                        )
                    firm_assertion = await append_review_assertion(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        run_id=run.id, membership_id=owner_a,
                        request=AnalysisReviewAssertionRequest(
                            target_kind="GAP", target_id=firm_gap.id,
                            new_coverage_state="EVIDENCE_MISSING", new_review_state="CONFIRMED",
                            corrected_fields={}, reason="Issued contribution rule reviewed.",
                        ),
                    )
                    await append_review_assertion(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        run_id=run.id, membership_id=owner_a,
                        request=AnalysisReviewAssertionRequest(
                            target_kind="GAP", target_id=firm_gap.id,
                            new_coverage_state="EVIDENCE_MISSING", new_review_state="CORRECTED",
                            corrected_fields={"resolution_category": "COMPANY_EVIDENCE"},
                            reason="Temporarily classify as an internal evidence gap.",
                        ),
                    )
                    with pytest.raises(CandidateEligibilityError, match="resolution category"):
                        await create_candidate_search(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            membership_id=owner_a,
                            request=CandidateSearchRequest(analysis_run_id=run.id, gap_id=firm_gap.id),
                        )
                    firm_assertion = await append_review_assertion(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        run_id=run.id, membership_id=owner_a,
                        request=AnalysisReviewAssertionRequest(
                            target_kind="GAP", target_id=firm_gap.id,
                            new_coverage_state="EVIDENCE_MISSING", new_review_state="CORRECTED",
                            corrected_fields={"resolution_category": "PARTNER_FIRM"},
                            reason="Reviewer confirmed the issued JV contribution path.",
                        ),
                    )
                    expert_assertion = await append_review_assertion(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        run_id=run.id, membership_id=owner_a,
                        request=AnalysisReviewAssertionRequest(
                            target_kind="GAP", target_id=expert_gap.id,
                            new_coverage_state="EVIDENCE_MISSING", new_review_state="CONFIRMED",
                            corrected_fields={}, reason="Required position reviewed.",
                        ),
                    )
                    assert firm_assertion.target_id == firm_gap.id and expert_assertion.target_id == expert_gap.id

                    firm = await create_firm(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"], operator=False,
                        payload=FirmCreateRequest(
                            scope="ORGANIZATION_PRIVATE", canonical_name="Aqua Advisory", display_name="Aqua Advisory",
                            country="Uzbekistan", regions=["Central Asia"], services=["Water design"],
                            capabilities=["Water and sanitation"], sectors=["Water"], source_type="MANUAL",
                            source_provenance={"reviewed_by": "operator"}, evidence_state="REVIEWED",
                            private_notes="private relationship note",
                        ),
                    )
                    reference = await create_project_reference(
                        db, organization_id=organization_a, firm_id=firm.firm_id,
                        actor_user_id=ids["user_a"], operator=False,
                        payload=ProjectReferenceCreateRequest(
                            project_name="Regional water network design", client_name="Water Agency",
                            country="Uzbekistan", service="Water and sanitation design", sector="Water",
                            role="JV_MEMBER", contract_share_percent=Decimal("40"),
                            contract_value=Decimal("250000.00"), contract_currency="USD", value_basis="FIRM_SHARE",
                            start_date="2022-01-01", completion_date="2023-01-01", completion_state="COMPLETED",
                            relevant_scope="Design of water distribution systems",
                            evidence_provenance={"document": "signed completion certificate"}, evidence_state="VERIFIED",
                        ),
                    )
                    assert reference.value_basis == "FIRM_SHARE" and reference.completion_state == "COMPLETED"

                    expert = await create_expert(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"], operator=False,
                        payload=ExpertCreateRequest(
                            scope="ORGANIZATION_PRIVATE", display_name="Candidate Engineer",
                            qualifications=["Civil engineering"], languages=["English"],
                            specializations=["Water and sanitation design"], consent_state="NOT_REQUIRED_PRIVATE",
                            evidence_state="REVIEWED", source_provenance={"entry": "authorized roster"},
                            private_notes="private rate omitted from all responses",
                        ),
                    )
                    cv1 = await create_cv_version(
                        db, organization_id=organization_a, expert_id=expert.expert_id,
                        actor_user_id=ids["user_a"], operator=False,
                        payload=CVVersionCreateRequest(
                            education=[{"degree": "Civil engineering"}],
                            qualifications=[{"qualification": "Water systems design"}],
                            certifications=[],
                            assignments=[{"project": "Regional water design", "actual_role": "Water Engineer", "start": "2021-01", "end": "2022-01", "scope": "Water network design"}],
                            languages=[{"language": "English", "level": "professional"}],
                            evidence_provenance={"source": "reviewed structured CV"}, evidence_state="VERIFIED",
                        ),
                    )
                    cv2 = await create_cv_version(
                        db, organization_id=organization_a, expert_id=expert.expert_id,
                        actor_user_id=ids["user_a"], operator=False,
                        payload=CVVersionCreateRequest(
                            education=[{"degree": "Civil engineering"}], qualifications=[], certifications=[],
                            assignments=[{"project": "Sanitation design", "actual_role": "Engineer", "start": "2022-02", "end": "2023-02", "scope": "Sanitation"}],
                            languages=[{"language": "English"}],
                            evidence_provenance={"source": "reviewed structured CV v2"}, evidence_state="VERIFIED",
                        ),
                    )
                    assert cv2.version_number == cv1.version_number + 1 and cv1.structured_sha256 != cv2.structured_sha256

                    # Shared expert creation is fail-closed without explicit consent and operator authority.
                    with pytest.raises(CandidateEligibilityError, match="consent"):
                        await create_expert(
                            db, organization_id=organization_a, actor_user_id=ids["user_a"], operator=True,
                            payload=ExpertCreateRequest(
                                scope="NETWORK_SHARED", display_name="No Consent", consent_state="UNKNOWN",
                                network_permission_basis="candidate roster policy", evidence_state="UNVERIFIED",
                            ),
                        )
                    shared = await create_expert(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"], operator=True,
                        payload=ExpertCreateRequest(
                            scope="NETWORK_SHARED", display_name="Consenting Network Expert",
                            specializations=["Transport"], consent_state="EXPLICIT_CONSENT",
                            network_permission_basis="signed network profile consent",
                            evidence_state="REVIEWED", source_provenance={"consent_record": "consent-1"},
                        ),
                    )
                    assert shared.scope == "NETWORK_SHARED"

                    private_b = await create_firm(
                        db, organization_id=organization_b, actor_user_id=ids["user_b"], operator=False,
                        payload=FirmCreateRequest(
                            scope="ORGANIZATION_PRIVATE", canonical_name="Private B", display_name="Private B",
                            capabilities=["Water and sanitation"], source_type="MANUAL",
                            evidence_state="REVIEWED", private_notes="B only",
                        ),
                    )
                    query_count = 0
                    library_a = await list_candidate_library(db, organization_id=organization_a)
                    assert query_count <= 4
                    query_count = 0
                    library_b = await list_candidate_library(db, organization_id=organization_b)
                    assert query_count <= 4
                    assert firm.firm_id in {row.firm_id for row in library_a.firms}
                    assert firm.firm_id not in {row.firm_id for row in library_b.firms}
                    assert private_b.firm_id not in {row.firm_id for row in library_a.firms}
                    assert shared.expert_id in {row.expert_id for row in library_b.experts}
                    assert "private_notes" not in library_a.model_dump_json()

                    firm_search = await create_candidate_search(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        membership_id=owner_a,
                        request=CandidateSearchRequest(analysis_run_id=run.id, gap_id=firm_gap.id, result_limit=10),
                    )
                    expert_search = await create_candidate_search(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        membership_id=owner_a,
                        request=CandidateSearchRequest(analysis_run_id=run.id, gap_id=expert_gap.id, result_limit=10),
                    )
                    assert firm_search.review_assertion_id == firm_assertion.assertion_id
                    assert firm_search.requirement_id == requirement.id and firm_search.position_id is None
                    assert expert_search.position_id == position.id and expert_search.requirement_id is None
                    assert len(firm_search.matches) <= 10 and len(expert_search.matches) <= 10
                    firm_match = next(row for row in firm_search.matches if row.candidate_id == firm.firm_id)
                    expert_match = next(row for row in expert_search.matches if row.candidate_id == expert.expert_id)
                    assert firm_match.qualification_state == "SUPPORTED_BY_EVIDENCE"
                    assert firm_match.strongest_evidence and firm_match.strongest_evidence[0]["reference_id"] == str(reference.reference_id)
                    assert expert_match.qualification_state in {"SUPPORTED_BY_EVIDENCE", "PARTIAL"}
                    assert expert_match.strongest_evidence
                    query_count = 0
                    projected = await get_candidate_search(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        search_run_id=firm_search.candidate_search_run_id,
                    )
                    assert projected and projected.candidate_search_run_id == firm_search.candidate_search_run_id
                    assert query_count <= 10
                    assert await get_candidate_search(
                        db, organization_id=organization_b, pursuit_id=source.pursuit.id,
                        search_run_id=firm_search.candidate_search_run_id,
                    ) is None

                    review1 = await append_candidate_review(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        search_run_id=firm_search.candidate_search_run_id,
                        match_id=firm_match.candidate_match_id, membership_id=owner_a,
                        request=CandidateReviewRequest(decision="SHORTLISTED", reason="Evidence is relevant."),
                    )
                    review2 = await append_candidate_review(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        search_run_id=firm_search.candidate_search_run_id,
                        match_id=firm_match.candidate_match_id, membership_id=owner_a,
                        request=CandidateReviewRequest(
                            decision="CONTRIBUTION_CORRECTED", corrected_contribution="JV member for water reference",
                            reason="Clarify the proposed JV role.",
                        ),
                    )
                    latest = await db.get(CandidateReviewDecision, review2.decision_id)
                    assert latest and latest.supersedes_decision_id == review1.decision_id
                    assert requirement.coverage_state == "EVIDENCE_MISSING" and firm_gap.coverage_state == "EVIDENCE_MISSING"

                    # A changed source blocks fresh search while prior history remains readable and stale.
                    document.parsed_text = issued + " Changed addendum."
                    await db.commit()
                    with pytest.raises(CandidateEligibilityError, match="stale"):
                        await create_candidate_search(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                            membership_id=owner_a,
                            request=CandidateSearchRequest(analysis_run_id=run.id, gap_id=firm_gap.id),
                        )
                    historical = await get_candidate_search(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id,
                        search_run_id=firm_search.candidate_search_run_id,
                    )
                    assert historical and historical.is_stale and historical.matches

                    # No historical participant or World Bank leader was auto-created.
                    assert await db.scalar(select(func.count(Firm.id))) == 2
                    assert await db.scalar(select(func.count(Expert.id))) == 2
                    assert await db.scalar(select(func.count(ProjectReference.id))) == 1
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", count_query)
                await engine.dispose()

            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval(
                    "SELECT count(*) FROM candidate_search_runs WHERE organization_id=$1", organization_b
                ) == 0
                assert await connection.fetchval(
                    "SELECT count(*) FROM candidate_review_decisions WHERE organization_id=$1", organization_b
                ) == 0
                for table, row_id in (
                    ("candidate_cv_versions", cv1.cv_version_id),
                    ("candidate_search_runs", firm_search.candidate_search_run_id),
                    ("candidate_matches", firm_match.candidate_match_id),
                    ("candidate_review_decisions", review1.decision_id),
                ):
                    with pytest.raises(Exception, match="immutable"):
                        await connection.execute(f"DELETE FROM {table} WHERE id=$1", row_id)
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

