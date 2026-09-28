"""Permanent W4 sealed-pack, provenance, durability, review, and tenancy proofs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from google.genai import _transformers, types
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.agents import pursuit_analyzer
from app.core.agents.pursuit_analyzer import ExtractedFact, NumericPredicate, PositionDetails, VerifiedFact
from app.core.config import settings
from app.core.private_storage import DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE
from app.models.all_models import TenderDocument
from app.models.base import DocumentProcessingState, PrivateDocumentRole, TenderEngagementOrigin, TenderEngagementStatus
from app.models.private_documents import DocumentProcessingJob, DocumentProcessingResult, DocumentVersion
from app.models.pursuit_analysis import (
    COVERAGE_STATES,
    AnalysisCompanySnapshot,
    AnalysisItemLineage,
    AnalysisPack,
    AnalysisPackItem,
    AnalysisReviewAssertion,
    AnalysisRun,
    PursuitGap,
    PursuitPosition,
    PursuitRequirement,
)
from app.schemas.tenancy import AnalysisLineageRequest, AnalysisReviewAssertionRequest, PursuitAnalysisStartRequest
from app.services import private_documents as private_service
from app.services.private_documents import (
    add_document_version,
    build_analysis_pack_candidate,
    list_private_documents,
    persist_private_pack,
    process_document_job,
    update_document_role,
)
from app.services.pursuit_analysis import (
    AnalysisAdmissionError,
    PAGE_LIMIT,
    UNKNOWN_PAGE_CHARACTER_LIMIT,
    _coverage_for_requirement,
    append_lineage,
    append_review_assertion,
    create_analysis_run,
    due_analysis_run_ids,
    get_analysis_run,
    process_analysis_run,
    renew_analysis_lease,
)
from app.services.pursuits import create_upload_pursuit, get_or_create_source_pursuit
from scripts import test_s0_5b4_baseline as support
from test_w2_organization_pursuit_foundation import W1_HEAD, _digest, _seed_w1
from test_w3_private_document_foundation import W3_HEAD, _docx_bytes, _pdf_bytes, _stage


W4_HEAD = "20260927_0001_w4_pursuit_analysis"
CURRENT_HEAD = "20261002_0001_p0_extraction_trust_gate"


def test_w4_gemini_schema_uses_sdk_compatible_explicit_dictionary() -> None:
    config = types.GenerateContentConfig(
        response_schema=pursuit_analyzer.PURSUIT_ANALYSIS_RESPONSE_SCHEMA
    )

    assert isinstance(config.response_schema, dict)
    transformed = _transformers.t_schema(None, config.response_schema)
    assert transformed["type"] == "ARRAY"
    assert transformed["items"]["type"] == "OBJECT"
    assert transformed["items"]["properties"]["position"]["type"] == "OBJECT"


def test_w4_migration_from_w3_is_reversible_and_drift_free() -> None:
    async def scenario() -> None:
        database = support.database_name("w4_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W3_HEAD)
            await asyncio.to_thread(support.alembic, database, "upgrade", W4_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT version_num FROM alembic_version") == W4_HEAD
                for table in (
                    "pursuit_analysis_packs", "pursuit_analysis_pack_items", "pursuit_analysis_runs",
                    "pursuit_analysis_requirements", "pursuit_analysis_positions", "pursuit_analysis_gaps",
                    "pursuit_analysis_review_assertions", "pursuit_analysis_item_lineage",
                ):
                    assert await connection.fetchval("SELECT to_regclass($1)", table) == table
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", W3_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('pursuit_analysis_packs')") is None
                assert await connection.fetchval("SELECT to_regclass('private_documents')") == "private_documents"
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", CURRENT_HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


def test_w4_coverage_semantics_are_complete_and_missing_evidence_is_not_failure() -> None:
    assert set(COVERAGE_STATES) == {
        "SUPPORTED", "PARTIAL", "GAP", "EVIDENCE_MISSING", "NEEDS_INTERPRETATION",
        "NOT_APPLICABLE", "LATER_STAGE_OBLIGATION",
    }
    ordinary = ExtractedFact(
        kind="CORPORATE_REQUIREMENT", original_quote="at least three contracts",
        normalized_text="At least three similar contracts", category="EXPERIENCE",
        requirement_type="CORPORATE_EXPERIENCE", stage_scope="ELIGIBILITY",
        distinction="MANDATORY", predicate=NumericPredicate(operator=">=", threshold=3, unit="contracts"),
    )
    coverage, _ = _coverage_for_requirement(ordinary, {"readiness_documents": []})
    assert coverage == "EVIDENCE_MISSING" and coverage != "GAP"
    later = ordinary.model_copy(update={"stage_scope": "POST_AWARD_OBLIGATION"})
    assert _coverage_for_requirement(later, {"readiness_documents": []})[0] == "LATER_STAGE_OBLIGATION"
    complex_rule = ordinary.model_copy(update={"complex_rule": True, "contribution_rule": "Lead/member allocation is ambiguous"})
    assert _coverage_for_requirement(complex_rule, {"readiness_documents": []})[0] == "NEEDS_INTERPRETATION"


def test_w4_page_locators_require_sealed_page_truth_and_positions_stay_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "[[PAGE 2]]\nInformational observer.\nRequired Team Leader."
    unknown = pursuit_analyzer._locate(
        text,
        "Required Team Leader.",
        chunk_start=0,
        chunk_end=len(text),
        page_count=None,
        page_count_known=False,
    )
    known = pursuit_analyzer._locate(
        text,
        "Required Team Leader.",
        chunk_start=0,
        chunk_end=len(text),
        page_count=2,
        page_count_known=True,
    )
    out_of_range = pursuit_analyzer._locate(
        text,
        "Required Team Leader.",
        chunk_start=0,
        chunk_end=len(text),
        page_count=1,
        page_count_known=True,
    )
    assert unknown and unknown[2] is None
    assert known and known[2] == 2
    assert out_of_range and out_of_range[2] is None

    informational = ExtractedFact(
        kind="POSITION", original_quote="Informational observer.",
        normalized_text="Observer", category="PERSONNEL", requirement_type="OTHER",
        stage_scope="INFORMATION", distinction="INFORMATIONAL",
        position=PositionDetails(title="Observer"),
    )
    required = ExtractedFact(
        kind="POSITION", original_quote="Required Team Leader.",
        normalized_text="Team Leader", category="PERSONNEL", requirement_type="KEY_EXPERT",
        stage_scope="TECHNICAL_EVALUATION", distinction="MANDATORY",
        position=PositionDetails(title="Team Leader"),
    )
    monkeypatch.setattr(pursuit_analyzer, "_resolve_gemini_api_key", lambda: "test-key")
    monkeypatch.setattr(
        pursuit_analyzer,
        "_extract_chunk_sync",
        lambda *_: [informational, required],
    )
    result = asyncio.run(
        pursuit_analyzer.analyze_pack_items(
            [
                pursuit_analyzer.SealedTextInput(
                    uuid4(), "sealed.pdf", text, page_count=2, page_count_known=True
                )
            ],
            "en",
        )
    )
    assert [item.fact.position.title for item in result if item.fact.position] == ["Team Leader"]
    assert result[0].page_number == 2


def test_w4_analysis_authority_for_upload_and_source_pursuits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        database = support.database_name("w4_authority")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", CURRENT_HEAD)
            connection = await support.database_connection(database)
            try:
                organization_a = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"])
                organization_b = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_b"])
                owner_a = await connection.fetchval("SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", organization_a, ids["user_a"])
                preserved_before = {
                    label: await _digest(connection, table, row_id)
                    for label, table, row_id in (
                        ("project", "projects", ids["project"]),
                        ("leader", "project_role_assignments", ids["current_leader"]),
                        ("legacy_analysis", "tender_analyses", ids["analysis"]),
                        ("legacy_version", "analysis_versions", ids["analysis_version"]),
                    )
                }
            finally:
                await connection.close()

            monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private"))
            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with sessions() as db:
                    pursuit = await create_upload_pursuit(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"], actor_membership_id=owner_a
                    )
                    pack = await persist_private_pack(
                        db, pursuit=pursuit, membership_id=owner_a,
                        files=[
                            _stage(tmp_path / "rfp.pdf", _pdf_bytes("W4"), "RFP.pdf", PDF_MEDIA_TYPE, PrivateDocumentRole.RFP),
                            _stage(tmp_path / "tor.docx", _docx_bytes(pages=None), "TOR.docx", DOCX_MEDIA_TYPE, PrivateDocumentRole.TOR),
                        ],
                    )

                pdf_text = (
                    "[[PAGE 1]]\nBidder shall have at least three similar contracts.\n"
                    "Team Leader must have ten years of specific experience.\n"
                    "After award, the consultant shall mobilize within 14 days."
                )
                docx_text = "The joint venture contribution rule requires human interpretation."

                async def parsed(path: Path, media_type: str):
                    if media_type == PDF_MEDIA_TYPE:
                        return {"text": pdf_text, "page_count": 1, "page_count_status": "KNOWN", "state": "READY", "error_code": None, "parser_name": "w4-test"}
                    return {"text": docx_text, "page_count": None, "page_count_status": "UNKNOWN", "state": "READY", "error_code": None, "parser_name": "w4-test"}

                monkeypatch.setattr(private_service, "scan_with_clamav", lambda _: "stream: OK")
                monkeypatch.setattr(private_service, "_parse_private_file", parsed)
                for job_id in pack.job_ids:
                    async with sessions() as db:
                        assert (await process_document_job(db, job_id))["state"] == "READY"

                async with sessions() as db:
                    candidate = await build_analysis_pack_candidate(db, organization_id=organization_a, pursuit_id=pursuit.id)
                    assert candidate.parse_ready and len(candidate.private_versions) == 2
                    assert all(item.processing_result_sha256 for item in candidate.private_versions)
                    pdf_candidate = next(item for item in candidate.private_versions if item.display_name == "RFP.pdf")
                    docx_candidate = next(item for item in candidate.private_versions if item.display_name == "TOR.docx")

                    # User inclusion is authoritative: seal only the PDF first.
                    started = await create_analysis_run(
                        db, organization_id=organization_a, pursuit_id=pursuit.id, membership_id=owner_a,
                        request=PursuitAnalysisStartRequest(
                            candidate_sha256=candidate.candidate_sha256, analysis_language="en",
                            private_version_ids=[pdf_candidate.document_version_id],
                        ),
                    )
                    assert started.page_count_known and started.total_known_pages == 1
                    assert await db.scalar(select(func.count(AnalysisPackItem.id)).where(AnalysisPackItem.pack_id == started.analysis_pack_id)) == 1
                    sealed_pdf_text = await db.scalar(select(AnalysisPackItem.analyzed_text).where(AnalysisPackItem.pack_id == started.analysis_pack_id))
                    assert sealed_pdf_text == pdf_text

                    # Candidate/hash race is fail closed.
                    race_candidate = await build_analysis_pack_candidate(db, organization_id=organization_a, pursuit_id=pursuit.id)
                    result = await db.scalar(select(DocumentProcessingResult).where(DocumentProcessingResult.document_version_id == docx_candidate.document_version_id))
                    assert result is not None
                    result.parser_version = "changed-after-review"
                    await db.commit()
                    with pytest.raises(AnalysisAdmissionError, match="changed after review"):
                        await create_analysis_run(
                            db, organization_id=organization_a, pursuit_id=pursuit.id, membership_id=owner_a,
                            request=PursuitAnalysisStartRequest(
                                candidate_sha256=race_candidate.candidate_sha256, analysis_language="en",
                                private_version_ids=[docx_candidate.document_version_id],
                            ),
                        )

                    oversized_text = "x" * (UNKNOWN_PAGE_CHARACTER_LIMIT + 1)
                    result.extracted_text = oversized_text
                    result.extracted_sha256 = hashlib.sha256(oversized_text.encode()).hexdigest()
                    await db.commit()
                    oversized_candidate = await build_analysis_pack_candidate(db, organization_id=organization_a, pursuit_id=pursuit.id)
                    with pytest.raises(AnalysisAdmissionError, match="alternate limit"):
                        await create_analysis_run(
                            db, organization_id=organization_a, pursuit_id=pursuit.id, membership_id=owner_a,
                            request=PursuitAnalysisStartRequest(
                                candidate_sha256=oversized_candidate.candidate_sha256, analysis_language="uz",
                                private_version_ids=[docx_candidate.document_version_id],
                            ),
                        )
                    result.extracted_text = docx_text
                    result.extracted_sha256 = hashlib.sha256(docx_text.encode()).hexdigest()
                    await db.commit()

                    # Unknown DOCX pages use the explicit character policy without inventing pages.
                    current_candidate = await build_analysis_pack_candidate(db, organization_id=organization_a, pursuit_id=pursuit.id)
                    docx_current = next(item for item in current_candidate.private_versions if item.document_version_id == docx_candidate.document_version_id)
                    unknown_run = await create_analysis_run(
                        db, organization_id=organization_a, pursuit_id=pursuit.id, membership_id=owner_a,
                        request=PursuitAnalysisStartRequest(
                            candidate_sha256=current_candidate.candidate_sha256, analysis_language="uz",
                            private_version_ids=[docx_current.document_version_id],
                        ),
                    )
                    assert not unknown_run.page_count_known
                    assert str(UNKNOWN_PAGE_CHARACTER_LIMIT) in unknown_run.limit_disclosure

                    # Exact PDF page totals over 500 are rejected without truncation.
                    pdf_result = await db.scalar(select(DocumentProcessingResult).where(DocumentProcessingResult.document_version_id == pdf_candidate.document_version_id))
                    assert pdf_result is not None
                    pdf_result.page_count = PAGE_LIMIT + 1
                    await db.commit()
                    over_candidate = await build_analysis_pack_candidate(db, organization_id=organization_a, pursuit_id=pursuit.id)
                    with pytest.raises(AnalysisAdmissionError, match="501 pages"):
                        await create_analysis_run(
                            db, organization_id=organization_a, pursuit_id=pursuit.id, membership_id=owner_a,
                            request=PursuitAnalysisStartRequest(
                                candidate_sha256=over_candidate.candidate_sha256, analysis_language="ru",
                                private_version_ids=[pdf_candidate.document_version_id],
                            ),
                        )
                    pdf_result.page_count = 1
                    pdf_job = await db.scalar(select(DocumentProcessingJob).where(DocumentProcessingJob.document_version_id == pdf_candidate.document_version_id))
                    assert pdf_job is not None
                    pdf_job.state = DocumentProcessingState.PARTIAL
                    await db.commit()
                    partial_candidate = await build_analysis_pack_candidate(db, organization_id=organization_a, pursuit_id=pursuit.id)
                    assert not next(item for item in partial_candidate.private_versions if item.document_version_id == pdf_candidate.document_version_id).parse_ready
                    with pytest.raises(AnalysisAdmissionError, match="FULL analysis requires READY"):
                        await create_analysis_run(
                            db, organization_id=organization_a, pursuit_id=pursuit.id, membership_id=owner_a,
                            request=PursuitAnalysisStartRequest(
                                candidate_sha256=partial_candidate.candidate_sha256, analysis_language="ru",
                                private_version_ids=[pdf_candidate.document_version_id],
                            ),
                        )
                    pdf_job.state = DocumentProcessingState.READY
                    await db.commit()

                async def extracted(sealed, language):
                    assert language in {"en", "uz", "ru"}
                    item = sealed[0]
                    return [
                        VerifiedFact(item.pack_item_id, ExtractedFact(
                            kind="CORPORATE_REQUIREMENT",
                            original_quote="Bidder shall have at least three similar contracts.",
                            normalized_text="At least three similar contracts", category="EXPERIENCE",
                            requirement_type="CORPORATE_EXPERIENCE", stage_scope="ELIGIBILITY",
                            distinction="MANDATORY", predicate=NumericPredicate(operator=">=", threshold=3, unit="contracts"),
                            contribution_rule="Joint venture members collectively may satisfy this requirement", confidence=0.91,
                        ), 11, 64, 1, 1),
                        VerifiedFact(item.pack_item_id, ExtractedFact(
                            kind="POSITION", original_quote="Team Leader must have ten years of specific experience.",
                            normalized_text="Team Leader with ten years specific experience", category="PERSONNEL",
                            requirement_type="KEY_EXPERT", stage_scope="TECHNICAL_EVALUATION", distinction="MANDATORY",
                            position=PositionDetails(title="Team Leader", quantity=1, specific_experience="Ten years"), confidence=0.89,
                        ), 65, 121, 1, 2),
                        VerifiedFact(item.pack_item_id, ExtractedFact(
                            kind="CORPORATE_REQUIREMENT",
                            original_quote="After award, the consultant shall mobilize within 14 days.",
                            normalized_text="Mobilize within 14 days after award", category="MOBILIZATION",
                            requirement_type="CONTRACT_DUTY", stage_scope="POST_AWARD_OBLIGATION",
                            distinction="MANDATORY", predicate=NumericPredicate(operator="<=", threshold=14, unit="days"),
                        ), 122, 182, 1, 3),
                    ]

                from app.services import pursuit_analysis as analysis_service
                monkeypatch.setattr(analysis_service.pursuit_analyzer, "analyze_pack_items", extracted)
                async with sessions() as db:
                    recoverable = await db.get(AnalysisRun, unknown_run.analysis_run_id)
                    assert recoverable
                    recoverable.status = "RUNNING"
                    recoverable.lease_owner = "lost-worker"
                    recoverable.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
                    await db.commit()
                    due = await due_analysis_run_ids(db)
                    assert started.analysis_run_id in due and unknown_run.analysis_run_id in due
                    started_row = await db.get(AnalysisRun, started.analysis_run_id)
                    assert started_row and started_row.dispatch_attempt_count == 1
                    await process_analysis_run(db, started.analysis_run_id, worker_id="w4-test-worker")
                    # Terminal replay cannot duplicate immutable outputs.
                    await process_analysis_run(db, started.analysis_run_id, worker_id="w4-test-worker")
                    completed_run = await db.get(AnalysisRun, started.analysis_run_id)
                    assert completed_run and completed_run.quality_state == "READY_FOR_REVIEW"
                    assert completed_run.extraction_diagnostics["persisted_requirement_count"] == 2
                    assert completed_run.extraction_diagnostics["persisted_position_count"] == 1
                    assert completed_run.extraction_diagnostics["persisted_gap_count"] == 2
                    assert await db.scalar(select(func.count(PursuitRequirement.id)).where(PursuitRequirement.analysis_run_id == started.analysis_run_id)) == 2
                    assert await db.scalar(select(func.count(PursuitPosition.id)).where(PursuitPosition.analysis_run_id == started.analysis_run_id)) == 1
                    requirements = list((await db.scalars(select(PursuitRequirement).where(PursuitRequirement.analysis_run_id == started.analysis_run_id).order_by(PursuitRequirement.created_at))).all())
                    corporate = requirements[0]
                    later = requirements[1]
                    assert corporate.predicate_json == {"operator": ">=", "threshold": 3.0, "unit": "contracts"}
                    assert corporate.coverage_state == "EVIDENCE_MISSING"
                    assert later.coverage_state == "LATER_STAGE_OBLIGATION"
                    gap = await db.scalar(select(PursuitGap).where(PursuitGap.requirement_id == corporate.id))
                    assert gap and gap.resolution_category == "PARTNER_FIRM"
                    assert await db.scalar(select(PursuitGap).where(PursuitGap.requirement_id == later.id)) is None
                    position = await db.scalar(select(PursuitPosition).where(PursuitPosition.analysis_run_id == started.analysis_run_id))
                    assert position and position.specific_experience == "Ten years"
                    assert position.title == "Team Leader" and position.coverage_state == "EVIDENCE_MISSING"
                    company = await db.scalar(select(AnalysisCompanySnapshot).where(AnalysisCompanySnapshot.analysis_run_id == started.analysis_run_id))
                    assert company and company.snapshot_json["truth_notice"].startswith("Recorded organization claims")

                    # Heartbeat is owned and bounded; terminal state rejects renewal.
                    assert not await renew_analysis_lease(db, started.analysis_run_id, worker_id="w4-test-worker")

                    # Every reviewed state is accepted through append-only assertions.
                    for state in COVERAGE_STATES:
                        assertion = await append_review_assertion(
                            db, organization_id=organization_a, pursuit_id=pursuit.id,
                            run_id=started.analysis_run_id, membership_id=owner_a,
                            request=AnalysisReviewAssertionRequest(
                                target_kind="REQUIREMENT", target_id=corporate.id,
                                new_coverage_state=state, new_review_state="CORRECTED",
                                corrected_fields={"normalized_text": f"Reviewed: {state}"}, reason=f"Reviewer set {state}",
                            ),
                        )
                        assert assertion.new_coverage_state == state
                    projection = await get_analysis_run(db, organization_id=organization_a, pursuit_id=pursuit.id, run_id=started.analysis_run_id)
                    assert projection
                    reviewed = next(item for item in projection.requirements if item.requirement_id == corporate.id)
                    assert reviewed.coverage_state == "EVIDENCE_MISSING"
                    assert reviewed.effective_coverage_state == "LATER_STAGE_OBLIGATION"
                    assert reviewed.effective_normalized_requirement == "Reviewed: LATER_STAGE_OBLIGATION"
                    assert await get_analysis_run(db, organization_id=organization_b, pursuit_id=pursuit.id, run_id=started.analysis_run_id) is None

                    old_requirement_count = await db.scalar(select(func.count(PursuitRequirement.id)).where(PursuitRequirement.analysis_run_id == started.analysis_run_id))
                    await update_document_role(
                        db, organization_id=organization_a, pursuit_id=pursuit.id,
                        document_id=pdf_candidate.private_document_id, membership_id=owner_a,
                        role=PrivateDocumentRole.ANNEX,
                    )
                    stale = await get_analysis_run(db, organization_id=organization_a, pursuit_id=pursuit.id, run_id=started.analysis_run_id)
                    assert stale and stale.inputs_changed and "differ" in (stale.stale_reason or "")
                    fresh_candidate = await build_analysis_pack_candidate(db, organization_id=organization_a, pursuit_id=pursuit.id)
                    rerun = await create_analysis_run(
                        db, organization_id=organization_a, pursuit_id=pursuit.id, membership_id=owner_a,
                        request=PursuitAnalysisStartRequest(
                            candidate_sha256=fresh_candidate.candidate_sha256, analysis_language="ru",
                            private_version_ids=[pdf_candidate.document_version_id],
                        ),
                    )
                    await process_analysis_run(db, rerun.analysis_run_id, worker_id="w4-rerun")
                    newer = await db.scalar(select(PursuitRequirement).where(PursuitRequirement.analysis_run_id == rerun.analysis_run_id).order_by(PursuitRequirement.created_at))
                    assert newer and await db.scalar(select(func.count(PursuitRequirement.id)).where(PursuitRequirement.analysis_run_id == started.analysis_run_id)) == old_requirement_count
                    lineage = await append_lineage(
                        db, organization_id=organization_a, pursuit_id=pursuit.id, membership_id=owner_a,
                        request=AnalysisLineageRequest(
                            target_kind="REQUIREMENT", prior_item_id=corporate.id,
                            current_item_id=newer.id, rationale="Reviewer confirmed the same issued clause",
                        ),
                    )
                    assert lineage.prior_item_id == corporate.id and lineage.current_item_id == newer.id
                    corporate_id = corporate.id

                    # Provider/schema exceptions must persist truthful diagnostics
                    # after rollback without dereferencing expired ORM pack items.
                    failure_candidate = await build_analysis_pack_candidate(
                        db, organization_id=organization_a, pursuit_id=pursuit.id
                    )
                    failed = await create_analysis_run(
                        db, organization_id=organization_a, pursuit_id=pursuit.id,
                        membership_id=owner_a,
                        request=PursuitAnalysisStartRequest(
                            candidate_sha256=failure_candidate.candidate_sha256,
                            analysis_language="en",
                            private_version_ids=[pdf_candidate.document_version_id],
                        ),
                    )

                    async def malformed_output(*_args, **_kwargs):
                        raise json.JSONDecodeError("unterminated provider JSON", "{", 1)

                    monkeypatch.setattr(
                        analysis_service.pursuit_analyzer,
                        "analyze_pack_items",
                        malformed_output,
                    )
                    with pytest.raises(json.JSONDecodeError, match="unterminated provider JSON"):
                        await process_analysis_run(
                            db, failed.analysis_run_id, worker_id="w4-failure-worker"
                        )
                    failed_row = await db.get(AnalysisRun, failed.analysis_run_id)
                    assert failed_row and failed_row.status == "QUEUED"
                    assert failed_row.quality_state == "FAILED"
                    assert failed_row.lease_owner is None and failed_row.lease_until is None
                    assert failed_row.failure_stage == "EXTRACTION"
                    assert failed_row.extraction_diagnostics["schema_rejected_count"] == 1
                    assert failed_row.extraction_diagnostics["input_character_count"] > 0
                    assert failed_row.extraction_diagnostics["input_page_count"] == 1
                    monkeypatch.setattr(
                        analysis_service.pursuit_analyzer,
                        "analyze_pack_items",
                        extracted,
                    )

                # SOURCE pursuit follows the same pack/run authority and snapshots source text.
                async with sessions() as db:
                    source = await get_or_create_source_pursuit(
                        db, organization_id=organization_a, actor_user_id=ids["user_a"],
                        actor_membership_id=owner_a, tender_id=ids["tender"],
                        stage=TenderEngagementStatus.SAVED,
                        legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
                    )
                    source_text = "Issued document requirement: audited statements are mandatory."
                    source_doc = TenderDocument(
                        tender_id=ids["tender"], file_url="issued-rfp.pdf", file_type="pdf",
                        source_document_url="https://example.invalid/issued-rfp.pdf",
                        source_document_type="RFP", sha256="b" * 64, parsed_text=source_text,
                    )
                    db.add(source_doc)
                    await db.commit()
                    candidate = await build_analysis_pack_candidate(db, organization_id=organization_a, pursuit_id=source.pursuit.id)
                    assert candidate.source_documents[0].provenance == "SHARED_SOURCE"
                    source_doc.parsed_text = "Changed between candidate review and seal."
                    await db.commit()
                    with pytest.raises(AnalysisAdmissionError, match="changed after review"):
                        await create_analysis_run(
                            db, organization_id=organization_a, pursuit_id=source.pursuit.id, membership_id=owner_a,
                            request=PursuitAnalysisStartRequest(
                                candidate_sha256=candidate.candidate_sha256, analysis_language="en",
                                source_document_ids=[source_doc.id],
                            ),
                        )
                    source_doc.parsed_text = source_text
                    await db.commit()
                    candidate = await build_analysis_pack_candidate(db, organization_id=organization_a, pursuit_id=source.pursuit.id)
                    source_run = await create_analysis_run(
                        db, organization_id=organization_a, pursuit_id=source.pursuit.id, membership_id=owner_a,
                        request=PursuitAnalysisStartRequest(
                            candidate_sha256=candidate.candidate_sha256, analysis_language="en",
                            source_document_ids=[source_doc.id],
                        ),
                    )
                    source_doc.parsed_text = "A future source refresh changed this row."
                    await db.commit()
                    sealed = await db.scalar(select(AnalysisPackItem).where(AnalysisPackItem.pack_id == source_run.analysis_pack_id))
                    assert sealed and sealed.analyzed_text == source_text and sealed.provenance == "SHARED_SOURCE"
                    passive = await get_analysis_run(db, organization_id=organization_a, pursuit_id=source.pursuit.id, run_id=source_run.analysis_run_id)
                    assert passive and passive.inputs_changed

                # Revoked membership cannot seal a pack even when invoked below the API boundary.
                connection = await support.database_connection(database)
                try:
                    revoked_id = uuid4()
                    await connection.execute(
                        "INSERT INTO memberships(id,organization_id,user_id,role,state,revoked_at) VALUES($1,$2,$3,'MEMBER','REVOKED',now())",
                        revoked_id, organization_a, ids["member"],
                    )
                finally:
                    await connection.close()
                async with sessions() as db:
                    fresh = await build_analysis_pack_candidate(db, organization_id=organization_a, pursuit_id=pursuit.id)
                    with pytest.raises(AnalysisAdmissionError, match="active organization Membership"):
                        await create_analysis_run(
                            db, organization_id=organization_a, pursuit_id=pursuit.id, membership_id=revoked_id,
                            request=PursuitAnalysisStartRequest(
                                candidate_sha256=fresh.candidate_sha256, analysis_language="en",
                                private_version_ids=[pdf_candidate.document_version_id],
                            ),
                        )

                connection = await support.database_connection(database)
                try:
                    # Database triggers protect packs, results, assertions, and explicit lineage.
                    for table, row_id in (
                        ("pursuit_analysis_packs", started.analysis_pack_id),
                        ("pursuit_analysis_pack_items", sealed.id),
                            ("pursuit_analysis_requirements", corporate_id),
                        ("pursuit_analysis_review_assertions", assertion.assertion_id),
                        ("pursuit_analysis_item_lineage", lineage.lineage_id),
                    ):
                        with pytest.raises(Exception, match="immutable"):
                            await connection.execute(f"DELETE FROM {table} WHERE id=$1", row_id)
                    preserved_after = {
                        label: await _digest(connection, table, row_id)
                        for label, table, row_id in (
                            ("project", "projects", ids["project"]),
                            ("leader", "project_role_assignments", ids["current_leader"]),
                            ("legacy_analysis", "tender_analyses", ids["analysis"]),
                            ("legacy_version", "analysis_versions", ids["analysis_version"]),
                        )
                    }
                    assert preserved_after == preserved_before
                finally:
                    await connection.close()
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


def test_w4_static_boundaries_no_pricing_search_or_passive_side_effects() -> None:
    from app.api.endpoints import pursuits
    from app.core.agents import pursuit_analyzer

    api_source = Path(pursuits.__file__).read_text(encoding="utf-8")
    analyzer_source = Path(pursuit_analyzer.__file__).read_text(encoding="utf-8")
    service_source = Path(__file__).with_name("app").joinpath("services", "pursuit_analysis.py").read_text(encoding="utf-8")
    assert "analysis-runs" in api_source and "analysis-pack-candidate" in api_source
    assert "httpx" not in service_source and "requests." not in service_source
    assert "pricing" not in analyzer_source.casefold()
    assert "find_partner" not in service_source and "find_expert" not in service_source
    assert "gemini-3.1-pro-preview" not in analyzer_source  # inherits the existing extractor model authority
