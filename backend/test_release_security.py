"""Maintained release security regressions. Synthetic identities/local fakes only."""
import asyncio
import copy
import io
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI, HTTPException, Response, UploadFile
from fastapi.testclient import TestClient

from app.api.endpoints import auth, tenders
from app.core import auth_bridge
from app.core.config import settings
from app.core.http_hardening import HardenedHTTPMiddleware, validation_error
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.all_models import SubscriptionTier, User
from app.models.company import CompanyProfile

BRIDGE_SECRET = "synthetic-release-bridge-secret-32-characters"
SENTINEL = "SECRET_SENTINEL AUTH_TOKEN_SENTINEL CUSTOMER_TEXT_SENTINEL"


def proof_payload(**changes):
    now = int(time.time())
    claims = dict(sub="synthetic-google-subject", email="pilot@example.invalid", name="Synthetic Pilot",
                  avatar_url=None, email_verified=True, iss="plasma-authjs", aud="plasma-backend",
                  iat=now, exp=now + 60, jti=str(uuid4()))
    claims.update(changes)
    return auth.GoogleAuthRequest(google_id=claims["sub"], email=claims["email"], name=claims["name"],
                                  bridge_assertion=jwt.encode(claims, BRIDGE_SECRET, algorithm="HS256"))


@pytest.mark.parametrize("attack", ["approved_no_proof", "admin_no_proof", "operator_no_proof", "arbitrary_no_proof",
    "forged_subject", "expired", "audience", "issuer", "tampered", "email_injection", "name_injection", "unverified", "long_lifetime"])
def test_bridge_rejects_impersonation_without_database_mutation(attack):
    payload = proof_payload()
    if attack.endswith("no_proof"):
        payload.bridge_assertion = None
        payload.email = attack + "@example.invalid"
    elif attack == "forged_subject": payload.google_id = "another-subject"
    elif attack == "email_injection": payload.email = "admin@example.invalid"
    elif attack == "name_injection": payload.name = "Administrator"
    elif attack == "expired": payload = proof_payload(iat=int(time.time()) - 120, exp=int(time.time()) - 60)
    elif attack == "audience": payload = proof_payload(aud="other-backend")
    elif attack == "issuer": payload = proof_payload(iss="browser")
    elif attack == "unverified": payload = proof_payload(email_verified=False)
    elif attack == "long_lifetime": payload = proof_payload(exp=int(time.time()) + 3600)
    elif attack == "tampered": payload.bridge_assertion = payload.bridge_assertion[:-8] + "abcdefgh"
    db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock(), add=AsyncMock())
    with patch.object(settings, "AUTH_BRIDGE_SECRET", BRIDGE_SECRET), patch.object(auth_bridge, "consume_assertion", AsyncMock()) as consume:
        with pytest.raises(HTTPException) as caught:
            asyncio.run(auth.google_auth_bridge(payload, Response(), db))
        assert caught.value.status_code == 401
        consume.assert_not_awaited()
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()
    db.add.assert_not_called()


def test_bridge_replay_and_store_outage_fail_closed():
    payload = proof_payload()
    with patch.object(settings, "AUTH_BRIDGE_SECRET", BRIDGE_SECRET), patch.object(auth_bridge, "consume_assertion", AsyncMock(side_effect=[True, False])):
        assert asyncio.run(auth_bridge.verify_bridge_assertion(payload))["email"] == payload.email
        with pytest.raises(HTTPException) as caught:
            asyncio.run(auth_bridge.verify_bridge_assertion(payload))
        assert caught.value.status_code == 401
    with patch.object(auth_bridge.Redis, "from_url", side_effect=RuntimeError(SENTINEL)):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(auth_bridge.consume_assertion(str(uuid4())))
        assert caught.value.status_code == 503
        assert SENTINEL not in caught.value.detail


class QueryResult:
    def __init__(self, rows): self.rows = rows
    def scalar_one_or_none(self): return self.rows[0] if self.rows else None
    def scalars(self): return self
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None
    def mappings(self): return self


class IdentityDB:
    def __init__(self, user):
        self.user = user
        self.reads = []
        self.writes = []
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.flush = AsyncMock()
    async def execute(self, query):
        self.reads.append(str(query))
        entity = query.column_descriptions[0].get("entity")
        if entity is User: return QueryResult([self.user] if self.user else [])
        if entity is CompanyProfile: return QueryResult([SimpleNamespace(id=uuid4(), user_id=self.user.id, approval_status="approved", pilot_status="active")])
        return QueryResult([])
    async def scalar(self, query):
        return (await self.execute(query)).scalar_one_or_none()
    def add(self, value):
        self.writes.append(value)
        self.user = value
        value.id = uuid4()
        value.auth_version = 0
        value.subscription_tier = SubscriptionTier.SCOUT


def synthetic_user(state="approved", role="pilot_user", version=3):
    return SimpleNamespace(id=uuid4(), google_id="synthetic-google-subject", email="pilot@example.invalid", name="Synthetic Pilot",
        approval_status=state, platform_role=role, is_admin=role == "admin", auth_version=version,
        subscription_tier=SubscriptionTier.SCOUT, approved_at=None, avatar_url=None)


@pytest.mark.parametrize("kind", ["new", "approved", "restored", "operator", "admin"])
def test_valid_verified_login_preserves_account_policy(kind):
    user = None if kind == "new" else synthetic_user(role=kind if kind in {"operator", "admin"} else "pilot_user")
    db = IdentityDB(user)
    with patch.object(settings, "AUTH_BRIDGE_SECRET", BRIDGE_SECRET), patch.object(auth_bridge, "consume_assertion", AsyncMock(return_value=True)):
        result = asyncio.run(auth.google_auth_bridge(proof_payload(), Response(), db))
    assert result.access_token
    assert result.approval_status == ("pending" if kind == "new" else "approved")
    assert result.platform_role == (kind if kind in {"operator", "admin"} else "pilot_user")
    assert len(db.writes) == (1 if kind == "new" else 0)
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("state,expected", [("anonymous",401),("invalid",401),("pending",403),("rejected",401),("disabled",401),("stale",401),("approved",200),("operator",200),("admin",200)])
@pytest.mark.parametrize("route", ["", "/00000000-0000-4000-8000-000000000001", "/00000000-0000-4000-8000-000000000001/details", "/00000000-0000-4000-8000-000000000001/decision-snapshot", "/00000000-0000-4000-8000-000000000001/documents"])
def test_direct_tender_authorization_matrix(state, expected, route):
    user = synthetic_user(state=state if state in {"pending","rejected","disabled"} else "approved", role=state if state in {"operator","admin"} else "pilot_user")
    db = IdentityDB(user)
    app = FastAPI()
    app.include_router(tenders.router, prefix="/tenders")
    app.dependency_overrides[get_db] = lambda: db
    headers = {} if state == "anonymous" else {"Authorization": "Bearer " + ("invalid" if state == "invalid" else create_access_token({"sub":str(user.id),"auth_version":2 if state == "stale" else 3}))}
    with TestClient(app) as client:
        response = client.get("/tenders" + route, headers=headers)
    # Authorized absent resources are looked up and return 404; list is 200.
    assert response.status_code == (404 if expected == 200 and route else expected)
    if expected != 200:
        assert all("FROM tenders" not in query for query in db.reads)
    db.commit.assert_not_awaited()
    assert not db.writes


def test_safe_error_boundary_and_validation_do_not_echo_input(caplog):
    from fastapi.exceptions import RequestValidationError
    from pydantic import BaseModel
    app = FastAPI()
    app.add_middleware(HardenedHTTPMiddleware)
    app.add_exception_handler(RequestValidationError, validation_error)
    @app.get("/failure")
    async def failure(): raise RuntimeError(SENTINEL)
    @app.get("/validate")
    async def validate(number: int): return number
    with TestClient(app) as client:
        for route in ["/failure", "/validate?number=" + SENTINEL]:
            response = client.get(route)
            assert response.status_code in {500,422}
            assert "request_id" in response.json()
            assert "SENTINEL" not in response.text
    assert "SENTINEL" not in caplog.text


@pytest.mark.parametrize("filename,data,status", [("bad.txt",b"%PDF-1.4",415),("fake.pdf",b"<html>bad</html>",415),("empty.pdf",b"",415),("large.pdf", b"%PDF-" + b"x" * (20*1024*1024),413)])
def test_upload_rejects_bad_inputs_and_cleans_files(tmp_path, filename, data, status):
    from app.core.uploads import staged_pdf
    file = UploadFile(io.BytesIO(data), filename=filename)
    async def run():
        with pytest.raises(HTTPException) as caught:
            async with staged_pdf(file, tmp_path):
                pytest.fail("Invalid file admitted")
        assert caught.value.status_code == status
    asyncio.run(run())
    assert not list(tmp_path.iterdir())
    assert file.file.closed


def test_signature_checked_filename_cannot_escape_tenant_directory(tmp_path):
    from app.core.uploads import staged_pdf
    file = UploadFile(io.BytesIO(b"%PDF-1.4"), filename='../../unsafe\r\n".pdf')
    async def run():
        async with staged_pdf(file, tmp_path) as path:
            assert path.parent == tmp_path
            assert path.name.startswith("upload-")
    asyncio.run(run())
    assert not list(tmp_path.iterdir())


def test_document_filter_does_no_corpus_or_filesystem_prepass():
    db = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError("corpus prepass")))
    for mode in ("documents_available", "files_missing"):
        with patch.object(tenders, "storage_file_exists", side_effect=AssertionError("filesystem prepass")):
            assert asyncio.run(tenders.resolve_filesystem_document_filter_tender_ids(db=db, document_status=mode)) is None
    db.execute.assert_not_awaited()


@pytest.mark.parametrize('language', ['en','uz','ru'])
def test_historical_extraction_error_is_redacted_without_mutating_snapshot(language):
    from app.api.endpoints.tenders import _public_extraction_error
    value = 'SECRET_SENTINEL AUTH_TOKEN_SENTINEL CUSTOMER_TEXT_SENTINEL'
    safe = _public_extraction_error(value, language)
    assert 'SENTINEL' not in safe and safe
    assert _public_extraction_error(safe,language) == safe
    assert _public_extraction_error(None,language) is None


def test_historical_provider_diagnostics_are_not_returned_to_admins():
    from app.api.endpoints.tenders import _public_coverage_metadata_payload
    snapshot = {'coverage_status':'failed','technical_warnings':[SENTINEL]}
    for debug in (False,True):
        assert 'SENTINEL' not in str(_public_coverage_metadata_payload(snapshot,include_debug=debug))
    assert snapshot['technical_warnings'] == [SENTINEL]
