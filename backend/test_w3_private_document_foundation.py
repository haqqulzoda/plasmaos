"""Permanent W3 security, migration, durability, and tenant-boundary proofs."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
import hashlib
from io import BytesIO
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pymupdf
import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.endpoints.pursuits import _enrichment_maps, _stage_files
from app.core.config import settings
from app.core.private_document_parser import _parse_docx, _parse_pdf
from app.core.private_storage import (
    DOCX_MEDIA_TYPE,
    MAX_PRIVATE_FILE_BYTES,
    MAX_PRIVATE_PACK_BYTES,
    MalwareScanError,
    PDF_MEDIA_TYPE,
    PrivateUploadError,
    scan_with_clamav,
    stage_private_upload,
)
from app.models.base import PrivateDocumentRole, TenderEngagementOrigin, TenderEngagementStatus
from app.models.private_documents import DocumentProcessingJob, DocumentVersion, MembershipLifecycleEvent, PrivateDocument
from app.services import private_documents as private_service
from app.services.memberships import activate_invitation, invite_member, revoke_membership
from app.services.organization_context import OrganizationAccessDeniedError, OrganizationContextRequiredError, resolve_organization_context
from app.services.private_documents import (
    PrivateDocumentNotFoundError,
    StagedPrivateFile,
    add_document_version,
    build_analysis_pack_candidate,
    get_authorized_version,
    list_private_documents,
    persist_private_pack,
    process_document_job,
    retry_processing_job,
    update_document_role,
)
from app.services.pursuits import create_upload_pursuit, get_or_create_source_pursuit
from app.workers import private_document_tasks
from scripts import test_s0_5b4_baseline as support
from test_w2_organization_pursuit_foundation import W1_HEAD, W2_HEAD, _digest, _seed_w1


W3_HEAD = "20260926_0001_w3_private_documents"


def _pdf_bytes(text: str = "Request for proposals\nReference: W3-001\nWorld Bank") -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


def _blank_pdf_bytes() -> bytes:
    document = pymupdf.open()
    document.new_page()
    payload = document.tobytes()
    document.close()
    return payload


def _encrypted_pdf_bytes() -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "protected")
    payload = document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    document.close()
    return payload


def _docx_bytes(*, pages: int | None = 2, body: str = "Tender notice W3-002") -> bytes:
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
            "<Default Extension='xml' ContentType='application/xml'/></Types>",
        )
        archive.writestr(
            "word/document.xml",
            "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
            f"<w:body><w:p><w:r><w:t>{body}</w:t></w:r></w:p></w:body></w:document>",
        )
        if pages is not None:
            archive.writestr(
                "docProps/app.xml",
                f"<Properties xmlns='http://schemas.openxmlformats.org/officeDocument/2006/extended-properties'><Pages>{pages}</Pages></Properties>",
            )
    return stream.getvalue()


def _upload(name: str, media_type: str, payload: bytes) -> UploadFile:
    return UploadFile(
        filename=name,
        file=BytesIO(payload),
        headers=Headers({"content-type": media_type}),
    )


def _stage(path: Path, payload: bytes, name: str, media_type: str, role=PrivateDocumentRole.OTHER) -> StagedPrivateFile:
    path.write_bytes(payload)
    return StagedPrivateFile(
        path=path,
        original_filename=name,
        safe_display_filename=name,
        media_type=media_type,
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        role=role,
    )


def test_w3_clean_upgrade_downgrade_reupgrade_on_disposable_postgresql() -> None:
    async def scenario() -> None:
        database = support.database_name("w3_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W2_HEAD)
            await asyncio.to_thread(support.alembic, database, "upgrade", W3_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT version_num FROM alembic_version") == W3_HEAD
                assert await connection.fetchval("SELECT to_regclass('private_documents')") == "private_documents"
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", W2_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('private_documents')") is None
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", W3_HEAD)
            await asyncio.to_thread(support.alembic, database, "upgrade", "head")
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


def test_w3_upload_validation_pdf_scanned_pdf_docx_and_rejections(tmp_path: Path) -> None:
    async def accepted(name: str, media: str, payload: bytes):
        return await stage_private_upload(_upload(name, media, payload), tmp_path / uuid4().hex)

    pdf = asyncio.run(accepted("RFP.pdf", PDF_MEDIA_TYPE, _pdf_bytes()))
    scanned = asyncio.run(accepted("scan.pdf", PDF_MEDIA_TYPE, _blank_pdf_bytes()))
    docx = asyncio.run(accepted("TOR.docx", DOCX_MEDIA_TYPE, _docx_bytes()))
    assert pdf[3] > 0 and scanned[3] > 0 and docx[3] > 0

    with pytest.raises(PrivateUploadError, match="media type"):
        asyncio.run(accepted("wrong.pdf", DOCX_MEDIA_TYPE, _pdf_bytes()))
    with pytest.raises(PrivateUploadError, match="Remove the PDF password"):
        asyncio.run(accepted("protected.pdf", PDF_MEDIA_TYPE, _encrypted_pdf_bytes()))
    with pytest.raises(PrivateUploadError, match="Only PDF and DOCX"):
        asyncio.run(accepted("macro.docm", "application/vnd.ms-word.document.macroEnabled.12", b"PK\x03\x04"))
    with pytest.raises(PrivateUploadError, match="HTML or active content"):
        asyncio.run(accepted("polyglot.pdf", PDF_MEDIA_TYPE, b"%PDF-1.7\n<script>alert(1)</script>"))
    with pytest.raises(PrivateUploadError, match="25 MiB"):
        asyncio.run(accepted("large.pdf", PDF_MEDIA_TYPE, b"%PDF-1.7\n" + b"0" * MAX_PRIVATE_FILE_BYTES))

    bomb = BytesIO()
    with ZipFile(bomb, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "A" * 1_000_000)
    with pytest.raises(PrivateUploadError, match="compression ratio"):
        asyncio.run(accepted("bomb.docx", DOCX_MEDIA_TYPE, bomb.getvalue()))


def test_w3_endpoint_staging_accepts_temporary_directory_string(tmp_path: Path) -> None:
    staging_directory = str(tmp_path / "pack")
    staged = asyncio.run(
        _stage_files(
            [_upload("RFP.pdf", PDF_MEDIA_TYPE, _pdf_bytes())],
            "[]",
            staging_directory,
        )
    )

    assert len(staged) == 1
    assert staged[0].path.parent == Path(staging_directory)
    assert staged[0].path.is_file()


def test_w3_bounded_local_parser_handles_pdf_ocr_docx_and_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text_pdf = tmp_path / "text.pdf"
    text_pdf.write_bytes(_pdf_bytes())
    parsed_pdf = _parse_pdf(text_pdf)
    assert parsed_pdf["state"] == "READY" and parsed_pdf["page_count"] == 1

    blank_pdf = tmp_path / "scan.pdf"
    blank_pdf.write_bytes(_blank_pdf_bytes())
    monkeypatch.setitem(sys.modules, "pytesseract", SimpleNamespace(image_to_string=lambda *args, **kwargs: "scanned tender"))
    parsed_scan = _parse_pdf(blank_pdf)
    assert parsed_scan["state"] == "READY" and "scanned tender" in parsed_scan["text"]

    docx = tmp_path / "document.docx"
    docx.write_bytes(_docx_bytes())
    parsed_docx = _parse_docx(docx)
    assert parsed_docx["state"] == "READY" and parsed_docx["page_count"] == 2
    unknown_pages = tmp_path / "unknown.docx"
    unknown_pages.write_bytes(_docx_bytes(pages=None))
    assert _parse_docx(unknown_pages)["state"] == "PARTIAL"


def test_w3_scanner_is_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = tmp_path / "checked.bin"
    payload.write_bytes(b"bounded")
    monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_SCAN_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_SCAN_PORT", 9)
    monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_SCAN_TIMEOUT_SECONDS", 1)
    with pytest.raises(MalwareScanError, match="temporarily unavailable"):
        scan_with_clamav(payload)


def test_w3_pack_limit_fails_before_persistence() -> None:
    oversized = [
        StagedPrivateFile(Path("unused"), "x.pdf", "x.pdf", PDF_MEDIA_TYPE, MAX_PRIVATE_PACK_BYTES + 1, "a" * 64, PrivateDocumentRole.RFP)
    ]
    with pytest.raises(PrivateUploadError, match="150 MiB"):
        asyncio.run(persist_private_pack(None, pursuit=SimpleNamespace(), membership_id=uuid4(), files=oversized))  # type: ignore[arg-type]


def test_w3_private_authority_processing_recovery_and_source_preservation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        database = support.database_name("w3_authority")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            # The current ORM runs this scenario, so the schema is the repository head
            # (R3 added library columns to private_documents).
            await asyncio.to_thread(support.alembic, database, "upgrade", "head")
            connection = await support.database_connection(database)
            try:
                organization_a = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"])
                organization_b = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_b"])
                owner_a = await connection.fetchval("SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", organization_a, ids["user_a"])
                before = {
                    label: await _digest(connection, table, row_id)
                    for label, table, row_id in (
                        ("tender", "tenders", ids["tender"]),
                        ("project", "projects", ids["project"]),
                        ("tender_project", "tender_projects", ids["tender_project"]),
                        ("leader_current", "project_role_assignments", ids["current_leader"]),
                        ("leader_history", "project_role_assignments", ids["historical_leader"]),
                    )
                }
            finally:
                await connection.close()

            monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private-storage"))
            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with sessions() as db:
                    upload_pursuit = await create_upload_pursuit(
                        db,
                        organization_id=organization_a,
                        actor_user_id=ids["user_a"],
                        actor_membership_id=owner_a,
                    )
                    first_pdf = _pdf_bytes()
                    pack = await persist_private_pack(
                        db,
                        pursuit=upload_pursuit,
                        membership_id=owner_a,
                        files=[
                            _stage(tmp_path / "a.pdf", first_pdf, "RFP.pdf", PDF_MEDIA_TYPE, PrivateDocumentRole.RFP),
                            _stage(tmp_path / "b.docx", _docx_bytes(), "TOR.docx", DOCX_MEDIA_TYPE, PrivateDocumentRole.TOR),
                        ],
                    )
                    assert upload_pursuit.source_tender_id is None
                    assert len(pack.document_ids) == 2 and len(pack.job_ids) == 2

                async def parsed(path: Path, media_type: str):
                    if media_type == PDF_MEDIA_TYPE:
                        return {"text": "[[PAGE 1]]\nRequest for proposals\nReference: W3-001\nWorld Bank", "page_count": 1, "page_count_status": "KNOWN", "state": "READY", "error_code": None, "parser_name": "test-pdf"}
                    return {"text": "Tender notice W3-002", "page_count": 2, "page_count_status": "KNOWN", "state": "READY", "error_code": None, "parser_name": "test-docx"}

                scanner_calls = 0
                def clean_scan(_: Path) -> str:
                    nonlocal scanner_calls
                    scanner_calls += 1
                    return "stream: OK"
                monkeypatch.setattr(private_service, "scan_with_clamav", clean_scan)
                monkeypatch.setattr(private_service, "_parse_private_file", parsed)
                for job_id in pack.job_ids:
                    async with sessions() as db:
                        assert (await process_document_job(db, job_id))["state"] == "READY"
                assert scanner_calls == 2
                async with sessions() as db:
                    replay = await process_document_job(db, pack.job_ids[0])
                    assert replay == {"state": "READY", "replayed": True}
                    rows = await list_private_documents(db, organization_id=organization_a, pursuit_id=upload_pursuit.id)
                    assert len(rows) == 2 and all(row[2].state.value == "READY" for row in rows)
                    candidate = await build_analysis_pack_candidate(db, organization_id=organization_a, pursuit_id=upload_pursuit.id)
                    assert candidate.parse_ready and {item.document_version_id for item in candidate.private_versions} == {row[1].id for row in rows}
                    with pytest.raises(PrivateDocumentNotFoundError):
                        await list_private_documents(db, organization_id=organization_b, pursuit_id=upload_pursuit.id)
                    with pytest.raises(PrivateDocumentNotFoundError):
                        await get_authorized_version(
                            db, organization_id=organization_b, pursuit_id=upload_pursuit.id,
                            document_id=rows[0][0].id, version_id=rows[0][1].id,
                        )

                async with sessions() as db:
                    original_version_id = rows[0][1].id
                    corrected = await update_document_role(
                        db,
                        organization_id=organization_a,
                        pursuit_id=upload_pursuit.id,
                        document_id=rows[0][0].id,
                        membership_id=owner_a,
                        role=PrivateDocumentRole.ANNEX,
                    )
                    assert corrected.role == PrivateDocumentRole.ANNEX
                    revision_pack = await add_document_version(
                        db,
                        organization_id=organization_a,
                        pursuit_id=upload_pursuit.id,
                        document_id=rows[0][0].id,
                        membership_id=owner_a,
                        staged=_stage(tmp_path / "revision.pdf", _pdf_bytes("Revised RFP"), "RFP-revised.pdf", PDF_MEDIA_TYPE),
                    )
                    assert revision_pack.document_ids == (rows[0][0].id,)
                    versions = list((await db.scalars(select(DocumentVersion).where(DocumentVersion.private_document_id == rows[0][0].id).order_by(DocumentVersion.version_number))).all())
                    assert [item.version_number for item in versions] == [1, 2]
                    assert versions[0].id == original_version_id
                    counts, rollups = await _enrichment_maps(db, [upload_pursuit.id])
                    assert counts[upload_pursuit.id] == 2
                    assert rollups[upload_pursuit.id].processed_count == 1
                    assert rollups[upload_pursuit.id].state.value == "CHECKING"

                async with sessions() as db:
                    duplicate = await persist_private_pack(
                        db,
                        pursuit=upload_pursuit,
                        membership_id=owner_a,
                        files=[_stage(tmp_path / "duplicate.pdf", first_pdf, "copy.pdf", PDF_MEDIA_TYPE)],
                    )
                    assert duplicate.duplicate_document_ids and duplicate.document_ids[0] not in duplicate.duplicate_document_ids
                    assert await db.scalar(select(func.count(PrivateDocument.id)).where(PrivateDocument.pursuit_id == upload_pursuit.id)) == 3

                async with sessions() as db:
                    source = await get_or_create_source_pursuit(
                        db,
                        organization_id=organization_a,
                        actor_user_id=ids["user_a"],
                        actor_membership_id=owner_a,
                        tender_id=ids["tender"],
                        stage=TenderEngagementStatus.SAVED,
                        legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
                    )
                    source_pack = await persist_private_pack(
                        db,
                        pursuit=source.pursuit,
                        membership_id=owner_a,
                        files=[_stage(tmp_path / "clarification.pdf", _pdf_bytes("Clarification"), "clarification.pdf", PDF_MEDIA_TYPE, PrivateDocumentRole.CLARIFICATION)],
                    )
                    assert source.pursuit.source_tender_id == ids["tender"]
                    assert len(source_pack.document_ids) == 1

                connection = await support.database_connection(database)
                try:
                    after = {
                        label: await _digest(connection, table, row_id)
                        for label, table, row_id in (
                            ("tender", "tenders", ids["tender"]),
                            ("project", "projects", ids["project"]),
                            ("tender_project", "tender_projects", ids["tender_project"]),
                            ("leader_current", "project_role_assignments", ids["current_leader"]),
                            ("leader_history", "project_role_assignments", ids["historical_leader"]),
                        )
                    }
                    assert after == before
                    version_id = await connection.fetchval("SELECT current_version_id FROM private_documents WHERE id=$1", pack.document_ids[0])
                    with pytest.raises(Exception, match="immutable"):
                        await connection.execute("UPDATE private_document_versions SET safe_display_filename='changed.pdf' WHERE id=$1", version_id)
                finally:
                    await connection.close()

                async with sessions() as db:
                    failing_pack = await persist_private_pack(
                        db,
                        pursuit=upload_pursuit,
                        membership_id=owner_a,
                        files=[_stage(tmp_path / "failure.pdf", _pdf_bytes("failure"), "failure.pdf", PDF_MEDIA_TYPE)],
                    )
                async def parser_failure(*_: object):
                    raise private_service.PrivateDocumentError("parser failed")
                monkeypatch.setattr(private_service, "_parse_private_file", parser_failure)
                async with sessions() as db:
                    assert (await process_document_job(db, failing_pack.job_ids[0]))["state"] == "FAILED"
                    failed_job = await db.get(DocumentProcessingJob, failing_pack.job_ids[0])
                    stable_version = failed_job.document_version_id
                    await retry_processing_job(
                        db, organization_id=organization_a, pursuit_id=upload_pursuit.id,
                        document_id=failing_pack.document_ids[0], membership_id=owner_a,
                    )
                monkeypatch.setattr(private_service, "_parse_private_file", parsed)
                calls_before_retry = scanner_calls
                async with sessions() as db:
                    assert (await process_document_job(db, failing_pack.job_ids[0]))["state"] == "READY"
                    retried_job = await db.get(DocumentProcessingJob, failing_pack.job_ids[0])
                    assert retried_job.document_version_id == stable_version
                    assert await db.scalar(select(func.count(DocumentVersion.id)).where(DocumentVersion.id == stable_version)) == 1
                assert scanner_calls == calls_before_retry

                monkeypatch.setattr(private_document_tasks, "AsyncSessionLocal", sessions)
                monkeypatch.setattr(private_document_tasks, "engine", engine)
                monkeypatch.setattr(private_document_tasks, "dispatch_job_ids", lambda ids: 0)
                recovery = await private_document_tasks.dispatch_pending_private_documents()
                assert recovery["leased"] >= 1 and recovery["published"] == 0
                async with sessions() as db:
                    recovered = await db.get(DocumentProcessingJob, source_pack.job_ids[0])
                    assert recovered.state.value == "QUEUED" and recovered.dispatch_attempt_count >= 1

                async with sessions() as db, db.begin():
                    invited = await invite_member(db, organization_id=organization_a, actor_membership_id=owner_a, user_id=ids["member"])
                    invited_id = invited.id
                async with sessions() as db, db.begin():
                    await activate_invitation(db, membership_id=invited_id, user_id=ids["member"])
                async with sessions() as db:
                    assert (await resolve_organization_context(db, user_id=ids["member"], organization_id=organization_a)).membership.id == invited_id
                async with sessions() as db, db.begin():
                    await revoke_membership(db, organization_id=organization_a, actor_membership_id=owner_a, membership_id=invited_id)
                async with sessions() as db:
                    with pytest.raises(OrganizationAccessDeniedError):
                        await resolve_organization_context(db, user_id=ids["member"], organization_id=organization_a)
                    actions = set((await db.scalars(select(MembershipLifecycleEvent.action).where(MembershipLifecycleEvent.membership_id == invited_id))).all())
                    assert {"INVITE", "ACTIVATE", "REVOKE"}.issubset(actions)

                connection = await support.database_connection(database)
                try:
                    await connection.execute(
                        "INSERT INTO memberships(id,organization_id,user_id,role,state,activated_at) VALUES($1,$2,$3,'MEMBER','ACTIVE',now())",
                        uuid4(), organization_b, ids["multi"],
                    )
                    await connection.execute(
                        "INSERT INTO memberships(id,organization_id,user_id,role,state,activated_at) VALUES($1,$2,$3,'MEMBER','ACTIVE',now())",
                        uuid4(), organization_a, ids["multi"],
                    )
                finally:
                    await connection.close()
                async with sessions() as db:
                    with pytest.raises(OrganizationContextRequiredError):
                        await resolve_organization_context(db, user_id=ids["multi"], organization_id=None)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


def test_w3_storage_boundary_remains_private_after_w4_extension() -> None:
    from app.api.endpoints import pursuits
    from app.schemas.tenancy import PrivateDocumentItem, PursuitResponse

    response_fields = set(PursuitResponse.model_fields) | set(PrivateDocumentItem.model_fields)
    assert "storage_key" not in response_fields
    assert "extracted_text" not in response_fields
    source = Path(pursuits.__file__).read_text(encoding="utf-8")
    assert "analysis-runs" in source
    assert "PrivateDocument" in source
