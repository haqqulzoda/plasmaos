"""R3 Task 3: CV upload -> structured CV draft -> reviewed, confirmed CV version.

Pure quote verification, the migration, then a Postgres scenario through the endpoints
with the real intake (signature checks, staging, durable job) and a fake model.
"""

from __future__ import annotations

import asyncio
from io import BytesIO
import json
from pathlib import Path

from fastapi import HTTPException, UploadFile
import pymupdf
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import Headers

from app.api.endpoints import candidates as endpoints
from app.core.agents import pursuit_analyzer
from app.core.config import settings
from app.models.candidate_retrieval import CVVersion, Expert
from app.models.cv_drafts import CVDraft
from app.models.private_documents import DocumentProcessingJob, PrivateDocument
from app.models.user import User
from app.schemas.candidate_retrieval import CVDraftConfirmRequest, ExpertCreateRequest
from app.services import cv_extraction
from app.services import private_documents as private_service
from app.services.candidate_retrieval import create_expert
from app.services.cv_library import due_cv_draft_ids, process_cv_draft
from app.services.private_documents import build_analysis_pack_candidate, process_document_job
from app.services.pursuits import create_upload_pursuit
from scripts import test_s0_5b4_baseline as support
from test_w2_organization_pursuit_foundation import W1_HEAD, _seed_w1


PREVIOUS = "20261008_0001_r3_pending_invitations"
REVISION = "20261009_0001_r3_cv_library_drafts"
HEAD = "20261011_0001_r3_organization_record_events"

CV_TEXT = (
    "[[PAGE 1]]\n"
    "Dilnoza Karimova\n"
    "Education\n"
    "MSc Electrical Engineering, Tashkent State Technical University, 2009\n"
    "Professional experience\n"
    "2019-2023 Team Leader, substation design for National Grid of Uzbekistan, Navoi region\n"
    "2015 - 2018: Design Engineer, Asian Development Bank energy project, Kazakhstan\n"
    "Languages: Uzbek (native), Russian (fluent), English (C1)\n"
    "Certifications: PMP, Project Management Institute, 2017"
)


def _model_output(**overrides) -> dict:
    output = {
        "full_name": {"value": "Dilnoza Karimova", "quote": "Dilnoza Karimova"},
        "education": [{
            "degree": "MSc Electrical Engineering", "institution": "Tashkent State Technical University", "year": "2009",
            "quote": "MSc Electrical Engineering, Tashkent State Technical University, 2009",
        }],
        "assignments": [
            {"role": "Team Leader", "client": "National Grid of Uzbekistan", "country": "Uzbekistan", "sector": "Energy",
             "start": "2019", "end": "2023", "description": "Substation design",
             "quote": "2019-2023 Team Leader, substation design for National Grid of Uzbekistan, Navoi region"},
            # Quote with harmless layout differences (en dash, spacing): same rule as analysis.
            {"role": "Design Engineer", "client": "Asian Development Bank", "country": "Kazakhstan", "sector": "Energy",
             "start": "2015", "end": "2018", "description": "",
             "quote": "2015 – 2018:  Design Engineer, Asian Development Bank energy project, Kazakhstan"},
            # Invented: the quote is not in the CV.
            {"role": "Chief Engineer", "client": "World Bank", "country": "Mongolia", "sector": "Energy",
             "start": "2024", "end": "", "description": "", "quote": "2024 Chief Engineer, World Bank, Mongolia"},
        ],
        "languages": [
            {"language": "Uzbek", "level": "native", "quote": "Uzbek (native)"},
            {"language": "English", "level": "C1", "quote": "English (C1)"},
        ],
        # The year is not in the quote, so it is not proposed.
        "certifications": [{"name": "PMP", "issuer": "Project Management Institute", "year": "2016",
                            "quote": "PMP, Project Management Institute"}],
    }
    output.update(overrides)
    return output


# ---- pure rules -------------------------------------------------------------------------------------

def test_rows_need_a_quote_found_in_the_parsed_text() -> None:
    proposal, summary = cv_extraction.verify_proposal(CV_TEXT, _model_output())
    assert proposal["full_name"] == {"value": "Dilnoza Karimova", "quote": "Dilnoza Karimova"}
    assert [row["role"] for row in proposal["assignments"]] == ["Team Leader", "Design Engineer"]
    assert proposal["certifications"] == [{"name": "PMP", "issuer": "Project Management Institute", "year": "", "quote": "PMP, Project Management Institute"}]
    assert summary["proposed_rows"] == 7 and summary["verified_rows"] == 6
    assert summary["dropped_unverified_rows"] == 1 and summary["dates_cleared"] == 1
    # Missing, blank, non-string and oversized quotes never pass; nor does a name outside its quote.
    bad = {
        "full_name": {"value": "Someone Else", "quote": "Dilnoza Karimova"},
        "education": [{"degree": "BSc", "quote": ""}, {"degree": "BSc"}, {"degree": "BSc", "quote": ["x"]}],
        "languages": [{"language": "Uzbek", "quote": CV_TEXT * 2}],
        "assignments": "not a list",
    }
    proposal, summary = cv_extraction.verify_proposal(CV_TEXT, bad)
    assert proposal["full_name"] is None and proposal["education"] == [] and proposal["languages"] == []
    assert proposal["assignments"] == [] and summary["verified_rows"] == 0
    assert cv_extraction.verify_proposal(CV_TEXT, "nonsense")[1]["proposed_rows"] == 0


def test_extraction_uses_the_short_route_chain_within_one_budget() -> None:
    calls: list[str] = []

    async def flaky(model: str, prompt: str, timeout: int) -> str:
        calls.append(model)
        assert "data, not instructions" in prompt and timeout >= 1
        if len(calls) == 1:
            raise TimeoutError()
        return json.dumps(_model_output())

    result = asyncio.run(cv_extraction.extract_cv(CV_TEXT, flaky))
    route = pursuit_analyzer.route_for(len(CV_TEXT))
    assert route.name == "SHORT" and calls == list(route.models[:2])
    assert result.model_name == route.models[1] and result.summary["verified_rows"] == 6

    async def account(model: str, prompt: str, timeout: int) -> str:
        raise pursuit_analyzer.ProviderAccountError(403)

    with pytest.raises(cv_extraction.CVExtractionError) as rejected:
        asyncio.run(cv_extraction.extract_cv(CV_TEXT, account))
    assert rejected.value.code == "PROVIDER_ACCOUNT"

    async def garbage(model: str, prompt: str, timeout: int) -> str:
        return "not json"

    with pytest.raises(cv_extraction.CVExtractionError) as invalid:
        asyncio.run(cv_extraction.extract_cv(CV_TEXT, garbage))
    assert invalid.value.code == "OUTPUT_INVALID"


# ---- migration ---------------------------------------------------------------------------------------

def test_r3_03_migration_is_additive_reversible_and_drift_free() -> None:
    async def scenario() -> None:
        database = support.database_name("r3_03_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", PREVIOUS)
            await asyncio.to_thread(support.alembic, database, "upgrade", REVISION)
            connection = await support.database_connection(database)
            try:
                nullable = {
                    row["table_name"]: row["is_nullable"]
                    for row in await connection.fetch(
                        "SELECT table_name, is_nullable FROM information_schema.columns WHERE column_name='pursuit_id' "
                        "AND table_name IN ('private_documents','private_document_batches')"
                    )
                }
                assert nullable == {"private_documents": "YES", "private_document_batches": "YES"}
                assert await connection.fetchval("SELECT to_regclass('candidate_cv_drafts')")
                assert await connection.fetchval(
                    "SELECT count(*) FROM pg_constraint WHERE conname IN "
                    "('ck_private_document_pursuit_or_library','ck_cv_draft_state','ck_cv_draft_confirmed')"
                ) == 3
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", PREVIOUS)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('candidate_cv_drafts')") is None
                assert await connection.fetchval(
                    "SELECT is_nullable FROM information_schema.columns WHERE table_name='private_documents' AND column_name='pursuit_id'"
                ) == "NO"
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


# ---- Postgres scenario -------------------------------------------------------------------------------

def _pdf(text: str) -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


def _upload(name: str, payload: bytes, media_type: str = "application/pdf") -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(payload), headers=Headers({"content-type": media_type}))


def test_cv_upload_review_confirm_isolated_and_manual_on_provider_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private"))
    monkeypatch.setattr(endpoints, "dispatch_job_ids", lambda ids: 0)

    async def scenario() -> None:
        database = support.database_name("r3_03_cv")
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


async def _process_document(sessions, draft_id, monkeypatch, *, text: str | None = CV_TEXT, infected: bool = False) -> None:
    async def parsed(path: Path, media_type: str):
        return {"text": text or "", "page_count": 1, "page_count_status": "KNOWN", "state": "READY", "error_code": None, "parser_name": "test-pdf"}

    def scan(_: Path) -> str:
        if infected:
            raise private_service.MalwareDetectedError("Eicar-Test-Signature")
        return "stream: OK"

    monkeypatch.setattr(private_service, "scan_with_clamav", scan)
    monkeypatch.setattr(private_service, "_parse_private_file", parsed)
    async with sessions() as db:
        draft = await db.get(CVDraft, draft_id)
        job_id = await db.scalar(select(DocumentProcessingJob.id).where(DocumentProcessingJob.document_version_id == draft.document_version_id))
        await db.rollback()
        await process_document_job(db, job_id)


async def _flow(sessions, ids, org_a, org_b, owner_a, monkeypatch) -> None:
    upload, listing, read, confirm = (
        endpoints.upload_cv_endpoint, endpoints.list_cv_drafts_endpoint,
        endpoints.read_cv_draft_endpoint, endpoints.confirm_cv_draft_endpoint,
    )
    async with sessions() as db:
        user_a = await db.get(User, ids["user_a"])
        user_b = await db.get(User, ids["user_b"])
        # The intake's checks apply unchanged: type, signature, size.
        for bad, code in (
            (_upload("cv.txt", b"plain text", "text/plain"), 415),
            (_upload("cv.pdf", b"not really a pdf"), 422),
        ):
            with pytest.raises(HTTPException) as refused:
                await upload(file=bad, expert_id=None, x_organization_id=org_a, current_user=user_a, db=db)
            assert refused.value.status_code in {code, 400, 415, 422}

        draft = await upload(file=_upload("Karimova CV.pdf", _pdf("Dilnoza Karimova")), expert_id=None,
                             x_organization_id=org_a, current_user=user_a, db=db)
        assert draft.state == "PROCESSING_DOCUMENT" and draft.expert_id is None
        assert draft.display_filename.endswith(".pdf")
        # Library documents have no pursuit and never appear in a pursuit's pack.
        document = await db.get(PrivateDocument, draft.private_document_id)
        assert document.pursuit_id is None and document.library_kind == "CV"
        pursuit = await create_upload_pursuit(db, organization_id=org_a, actor_user_id=ids["user_a"], actor_membership_id=owner_a)
        candidate = await build_analysis_pack_candidate(db, organization_id=org_a, pursuit_id=pursuit.id)
        assert candidate.private_versions == []
        await db.commit()

    # Nothing is extracted before the document is scanned and parsed; then the job proposes.
    async with sessions() as db:
        assert await due_cv_draft_ids(db) == []
    await _process_document(sessions, draft.cv_draft_id, monkeypatch)
    async with sessions() as db:
        assert await due_cv_draft_ids(db) == [draft.cv_draft_id]
        calls = []

        async def fake_model(model: str, prompt: str, timeout: int) -> str:
            calls.append(model)
            return json.dumps(_model_output())

        assert await process_cv_draft(db, draft.cv_draft_id, call=fake_model) == "READY"
        assert len(calls) == 1
        # No auto-save: a READY draft has created no expert and no CV version.
        assert await db.scalar(select(func.count(CVVersion.id))) == 0
        assert await db.scalar(select(func.count(Expert.id))) == 0

    async with sessions() as db:
        user_a = await db.get(User, ids["user_a"])
        user_b = await db.get(User, ids["user_b"])
        review = await read(draft_id=draft.cv_draft_id, x_organization_id=org_a, current_user=user_a, db=db)
        assert review.state == "READY" and "National Grid of Uzbekistan" in review.document_text
        assert review.proposed_counts == {"education": 1, "assignments": 2, "languages": 2, "certifications": 1}
        assert review.extraction_summary["dropped_unverified_rows"] == 1
        assert all(row["quote"] for row in review.proposal["assignments"])
        # Tenant isolation: another organization neither lists nor reads nor confirms it.
        assert await listing(expert_id=None, x_organization_id=org_b, current_user=user_b, db=db) == []
        for call in (
            lambda: read(draft_id=draft.cv_draft_id, x_organization_id=org_b, current_user=user_b, db=db),
            lambda: confirm(draft_id=draft.cv_draft_id, payload=CVDraftConfirmRequest(new_expert_name="X Y"),
                            x_organization_id=org_b, current_user=user_b, db=db),
        ):
            with pytest.raises(HTTPException) as hidden:
                await call()
            assert hidden.value.status_code == 404
        with pytest.raises(HTTPException) as foreign_context:
            await read(draft_id=draft.cv_draft_id, x_organization_id=org_a, current_user=user_b, db=db)
        assert foreign_context.value.status_code == 404

        # Confirm the reviewed (edited) fields: a new expert, version 1, UNVERIFIED, with provenance.
        assignments = [dict(row) for row in review.proposal["assignments"]]
        assignments[0]["role"] = "Team Leader / Lead Substation Engineer"
        assignments.append({"role": "Reviewer added", "client": "Manual", "quote": "not in the document"})
        with pytest.raises(HTTPException) as unnamed:
            await confirm(draft_id=draft.cv_draft_id, payload=CVDraftConfirmRequest(assignments=assignments),
                          x_organization_id=org_a, current_user=user_a, db=db)
        assert unnamed.value.status_code == 409 and unnamed.value.detail["code"] == "EXPERT_NAME_REQUIRED"
        saved = await confirm(
            draft_id=draft.cv_draft_id,
            payload=CVDraftConfirmRequest(
                new_expert_name=review.proposal["full_name"]["value"], education=review.proposal["education"],
                assignments=assignments, languages=review.proposal["languages"],
                certifications=review.proposal["certifications"],
            ),
            x_organization_id=org_a, current_user=user_a, db=db,
        )
        cv = saved.cv_version
        assert saved.expert_name == "Dilnoza Karimova" and cv.version_number == 1 and cv.evidence_state == "UNVERIFIED"
        assert cv.assignments[0]["role"] == "Team Leader / Lead Substation Engineer" and len(cv.assignments) == 3
        assert all("quote" not in row for row in cv.assignments)
        provenance = cv.evidence_provenance
        assert provenance["entry"] == "CV_UPLOAD_REVIEWED" and provenance["document_version_id"] == str(review.document_version_id)
        assert provenance["rows_with_verified_quote"] == 6 and provenance["rows_without_verified_quote"] == 1
        assert {item["section"] for item in provenance["quotes"]} == {"education", "assignments", "languages", "certifications"}
        assert all(item["quote"] != "not in the document" for item in provenance["quotes"])
        with pytest.raises(HTTPException) as twice:
            await confirm(draft_id=draft.cv_draft_id, payload=CVDraftConfirmRequest(new_expert_name="Again"),
                          x_organization_id=org_a, current_user=user_a, db=db)
        assert twice.value.status_code == 409 and twice.value.detail["code"] == "ALREADY_CONFIRMED"
        expert_id = saved.expert_id

    # A late model result never overwrites a confirmed draft.
    async with sessions() as db:
        assert await process_cv_draft(db, draft.cv_draft_id) == "CONFIRMED"

    # Re-upload for the existing expert: a new document and a new draft; version 1 is untouched.
    async with sessions() as db:
        user_a = await db.get(User, ids["user_a"])
        second = await upload(file=_upload("Karimova CV 2026.pdf", _pdf("Dilnoza Karimova 2026")), expert_id=expert_id,
                              x_organization_id=org_a, current_user=user_a, db=db)
        assert second.cv_draft_id != draft.cv_draft_id and second.private_document_id != draft.private_document_id
        assert second.expert_id == expert_id and second.expert_name == "Dilnoza Karimova"
    await _process_document(sessions, second.cv_draft_id, monkeypatch)

    # Provider failure: the draft fails (after its retry) and the manual form still saves.
    async def down(model: str, prompt: str, timeout: int) -> str:
        raise RuntimeError("provider unavailable")

    async with sessions() as db:
        assert await process_cv_draft(db, second.cv_draft_id, call=down) == "QUEUED"  # one retry
        retry = await db.get(CVDraft, second.cv_draft_id)
        retry.next_attempt_at = retry.created_at
        await db.commit()
        assert await process_cv_draft(db, second.cv_draft_id, call=down) == "FAILED"
    async with sessions() as db:
        user_a = await db.get(User, ids["user_a"])
        failed = await read(draft_id=second.cv_draft_id, x_organization_id=org_a, current_user=user_a, db=db)
        assert failed.state == "FAILED" and failed.failure_code == "PROVIDER_ERROR"
        assert failed.document_text and failed.proposal.get("assignments") in (None, [])
        manual = await confirm(
            draft_id=second.cv_draft_id,
            payload=CVDraftConfirmRequest(languages=[{"language": "Russian", "level": "fluent"}]),
            x_organization_id=org_a, current_user=user_a, db=db,
        )
        assert manual.cv_version.version_number == 2 and manual.expert_id == expert_id
        assert manual.cv_version.evidence_provenance["rows_without_verified_quote"] == 1
        first = await db.scalar(select(CVVersion).where(CVVersion.expert_id == expert_id, CVVersion.version_number == 1))
        assert len(first.assignments) == 3  # never mutated
        listed = await listing(expert_id=expert_id, x_organization_id=org_a, current_user=user_a, db=db)
        assert [item.cv_draft_id for item in listed] == [second.cv_draft_id, draft.cv_draft_id]
        assert {item.state for item in listed} == {"CONFIRMED"}

    # A malware hit fails the draft and blocks saving anything from that document.
    async with sessions() as db:
        user_a = await db.get(User, ids["user_a"])
        infected = await upload(file=_upload("bad.pdf", _pdf("x")), expert_id=None, x_organization_id=org_a, current_user=user_a, db=db)
    await _process_document(sessions, infected.cv_draft_id, monkeypatch, infected=True)
    async with sessions() as db:
        user_a = await db.get(User, ids["user_a"])
        rejected = await read(draft_id=infected.cv_draft_id, x_organization_id=org_a, current_user=user_a, db=db)
        assert rejected.state == "FAILED" and rejected.failure_code == "DOCUMENT_REJECTED" and rejected.document_text is None
        with pytest.raises(HTTPException) as blocked:
            await confirm(draft_id=infected.cv_draft_id,
                          payload=CVDraftConfirmRequest(new_expert_name="Someone", languages=[{"language": "Uzbek"}]),
                          x_organization_id=org_a, current_user=user_a, db=db)
        assert blocked.value.status_code == 409 and blocked.value.detail["code"] == "NOT_CONFIRMABLE"

    # An expert of another organization cannot receive an upload.
    async with sessions() as db:
        expert_b = await create_expert(db, organization_id=org_b, actor_user_id=ids["user_b"], operator=False, payload=ExpertCreateRequest(
            scope="ORGANIZATION_PRIVATE", display_name="B Expert", consent_state="NOT_REQUIRED_PRIVATE", evidence_state="UNVERIFIED"))
        user_a = await db.get(User, ids["user_a"])
        with pytest.raises(HTTPException) as foreign:
            await upload(file=_upload("cv.pdf", _pdf("x")), expert_id=expert_b.expert_id, x_organization_id=org_a, current_user=user_a, db=db)
        assert foreign.value.status_code == 404
