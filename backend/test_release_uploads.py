"""Upload failure fingerprints, cleanup, signature and body-boundary regressions."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
import pytest

from app.api.endpoints.proposals import upload_tender_tz
from app.core import uploads
from app.core.http_hardening import HardenedHTTPMiddleware


@asynccontextmanager
async def permit(_user):
    yield


@pytest.mark.parametrize("failure", ["parse", "empty_parse", "model", "invalid_model", "commit", "success"])
def test_pipeline_failure_fingerprint_and_cleanup(tmp_path, failure):
    before = {"strategic_summary":"Preserved prior work", "nested":{"original":True}}
    proposal = SimpleNamespace(id=uuid4(), structured_data=deepcopy(before), ai_confidence_score=10,
                               tender=SimpleNamespace(budget=1000))
    user = SimpleNamespace(id=uuid4(), company_name="Synthetic company", core_services="", past_experience="")
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda:proposal)),
                         commit=AsyncMock(), rollback=AsyncMock())
    parser = AsyncMock(return_value="Parsed technical requirements")
    model = AsyncMock(return_value={"summary":"Model summary","items":[],"delivery_days":30})
    if failure == "parse": parser.side_effect = HTTPException(422,"PDF could not be parsed")
    if failure == "empty_parse": parser.return_value = ""
    if failure == "model": model.side_effect = RuntimeError("SECRET_SENTINEL CUSTOMER_TEXT_SENTINEL")
    if failure == "invalid_model": model.return_value = {"error":"SECRET_SENTINEL"}
    if failure == "commit": db.commit.side_effect = RuntimeError("Database unavailable")
    original_stager = uploads.staged_pdf
    @asynccontextmanager
    async def stage_here(file, _directory):
        _directory.mkdir(parents=True, exist_ok=True)
        async with original_stager(file, tmp_path) as path:
            yield path
    # The route derives its tenant directory from this module's location.
    with patch("app.api.endpoints.proposals.__file__", str(tmp_path / "app/api/endpoints/proposals.py")), patch.object(uploads,"staged_pdf",stage_here), patch.object(uploads,"upload_permit",permit), patch.object(uploads,"parse_uploaded_pdf",parser), patch.object(uploads,"analyze_uploaded_pdf",model):
        file = UploadFile(io.BytesIO(b"%PDF-1.4 fixture"),filename='../../source.pdf')
        if failure == "success":
            result = asyncio.run(upload_tender_tz(proposal.id,file,user,db))
            assert result.suggested_price == 850
            assert proposal.structured_data["uploaded_tz_text"]
            assert Path(proposal.structured_data["uploaded_tz_path"]).is_file()
            db.commit.assert_awaited_once()
        else:
            with pytest.raises((HTTPException,RuntimeError)) as caught:
                asyncio.run(upload_tender_tz(proposal.id,file,user,db))
            assert "SENTINEL" not in str(caught.value)
            if failure in {"parse","empty_parse"}: model.assert_not_awaited()
            if failure != "commit":
                assert proposal.structured_data == before
                assert proposal.ai_confidence_score == 10
                db.commit.assert_not_awaited()
            else: db.rollback.assert_awaited_once()
            assert not list(tmp_path.rglob("*.pdf"))
        assert file.file.closed
        assert not list(tmp_path.glob("upload-*.pdf"))


def test_real_parser_accepts_pdf_and_rejects_malformed_before_model(tmp_path):
    import pymupdf
    valid = tmp_path / "valid.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((40,40),"Synthetic technical requirements: supply certified equipment and installation services.")
        document.save(valid)
    assert "Synthetic technical requirements" in asyncio.run(uploads.parse_uploaded_pdf(valid))
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"%PDF-malformed")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(uploads.parse_uploaded_pdf(invalid))
    assert caught.value.status_code == 422


def test_oversized_content_length_is_rejected_before_multipart_or_handler():
    app = FastAPI()
    app.add_middleware(HardenedHTTPMiddleware)
    called = []
    @app.post("/api/v1/proposals/fixture/upload-tz")
    async def upload(file: UploadFile):
        called.append(True)
        return {"success":True}
    with TestClient(app) as client:
        response = client.post("/api/v1/proposals/fixture/upload-tz", content=b"ignored",headers={"Content-Length":str(uploads.MAX_UPLOAD_REQUEST_BYTES+1)})
    assert response.status_code == 413 and not called


def test_chunked_body_limit_cannot_be_bypassed_without_content_length():
    sent = []
    received = 0
    async def app(scope, receive, send):
        while (await receive()).get("more_body",False): pass
    async def receive():
        nonlocal received
        received += 1
        return {"type":"http.request","body":b"x"*(1024*1024),"more_body":True}
    async def send(message): sent.append(message)
    scope = {"type":"http","path":"/api/v1/proposals/fixture/upload-tz","method":"POST","headers":[]}
    asyncio.run(HardenedHTTPMiddleware(app)(scope,receive,send))
    assert received == 22
    # Middleware must preserve the 413 even when no router exception handler exists.
    assert sent[0]["status"] == 413


def test_chunked_multipart_overflow_closes_partial_spooled_files():
    import starlette.formparsers
    from tempfile import SpooledTemporaryFile
    app = FastAPI()
    app.add_middleware(HardenedHTTPMiddleware)
    called, spools = [], []
    @app.post('/api/v1/proposals/fixture/upload-tz')
    async def upload(file: UploadFile):
        called.append(True)
        return {'success': True}
    def tracked_spool(*args, **kwargs):
        spool = SpooledTemporaryFile(*args, **kwargs)
        spools.append(spool)
        return spool
    async def exercise():
        import httpx
        async def chunks():
            yield b'--fixture\r\nContent-Disposition: form-data; name="file"; filename="large.pdf"\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.4\n'
            for _ in range(22): yield b'x' * (1024 * 1024)
            yield b'\r\n--fixture--\r\n'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            return await client.post('/api/v1/proposals/fixture/upload-tz',content=chunks(),headers={'Content-Type':'multipart/form-data; boundary=fixture'})
    with patch.object(starlette.formparsers,'SpooledTemporaryFile',tracked_spool):
        response = asyncio.run(exercise())
    assert response.status_code == 413 and not called
    assert spools and all(file.closed for file in spools)


@pytest.mark.parametrize('operation', ['parse_uploaded_pdf', 'analyze_uploaded_pdf'])
def test_timeout_kills_processing_group_before_releasing_permit(operation):
    process = SimpleNamespace(pid=99999,returncode=None,communicate=AsyncMock(),wait=AsyncMock())
    async def timed_out(awaitable, **_):
        awaitable.close()
        raise TimeoutError()
    with patch.object(uploads.asyncio,'create_subprocess_exec',AsyncMock(return_value=process)), patch.object(uploads.asyncio,'wait_for',timed_out), patch.object(uploads.os,'killpg') as kill:
        with pytest.raises(HTTPException):
            asyncio.run(getattr(uploads,operation)(Path('fixture.pdf'), *([{}] if operation.startswith('analyze') else [])))
        kill.assert_called_once_with(process.pid, uploads.signal.SIGKILL)
        process.wait.assert_awaited_once()
