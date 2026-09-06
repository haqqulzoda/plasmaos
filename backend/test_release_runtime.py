"""Shared Redis replay/processing and operational failure contracts on local services."""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from redis.asyncio import Redis

from app.core import auth_bridge, uploads
from app.core.http_hardening import HardenedHTTPMiddleware
from app.api.endpoints import operations


def test_shared_redis_replay_rate_and_processing_leases():
    url = os.environ.get('AUTH_REPLAY_REDIS_URL', 'redis://127.0.0.1:6379/0')
    assert urlsplit(url).hostname in {'localhost','127.0.0.1','::1'}, 'Local Redis required'
    async def scenario():
        async with Redis.from_url(url) as client:
            jti = str(uuid4())
            users = [str(uuid4()) for _ in range(6)]
            permits = []
            try:
                results = await asyncio.gather(*(auth_bridge.consume_assertion(jti) for _ in range(12)))
                assert results.count(True) == 1 and results.count(False) == 11
                for user in users[:4]:
                    permit = uploads.upload_permit(user)
                    await permit.__aenter__()
                    permits.append(permit)
                with pytest.raises(HTTPException) as busy:
                    async with uploads.upload_permit(users[4]): pass
                assert busy.value.status_code == 429
                with pytest.raises(HTTPException) as rate:
                    async with uploads.upload_permit(users[0]): pass
                assert rate.value.status_code == 429
                await permits.pop().__aexit__(None,None,None)
                async with uploads.upload_permit(users[5]): pass
            finally:
                for permit in permits: await permit.__aexit__(None,None,None)
                await client.delete(f'auth:assertion:{jti}',*(f'upload:rate:{user}' for user in users))
            assert not any([await client.exists(f'upload:slot:{i}') for i in range(4)])
    asyncio.run(scenario())


@pytest.mark.parametrize('dependencies,status', [({'database':True,'redis':True},200),({'database':False,'redis':True},503),({'database':True,'redis':False},503)])
def test_readiness_reports_safe_dependency_states(dependencies,status):
    with patch.object(operations,'dependency_status',AsyncMock(return_value=dependencies)):
        response = asyncio.run(operations.readiness())
    assert response.status_code == status
    assert b'SENTINEL' not in response.body


def test_operations_failure_redacts_database_or_redis_error():
    db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError('SECRET_SENTINEL CUSTOMER_TEXT_SENTINEL')))
    with pytest.raises(HTTPException) as caught: asyncio.run(operations.operations(db))
    assert caught.value.status_code == 503 and 'SENTINEL' not in caught.value.detail


def test_cookie_origin_and_security_headers_without_weakening_bearer_access():
    app = FastAPI()
    app.add_middleware(HardenedHTTPMiddleware)
    @app.post('/command')
    async def command(): return {'ok':True}
    with patch('app.core.http_hardening.settings.BACKEND_CORS_ORIGINS',['https://console.example.invalid']), TestClient(app,base_url='https://api.example.invalid') as client:
        denied = client.post('/command',headers={'Cookie':'plasma_api_token=synthetic','Origin':'https://evil.invalid'})
        assert denied.status_code == 403
        allowed = client.post('/command',headers={'Cookie':'plasma_api_token=synthetic','Origin':'https://console.example.invalid'})
        assert allowed.status_code == 200
        bearer = client.post('/command',headers={'Authorization':'Bearer synthetic'})
        assert bearer.status_code == 200
        for header in ('X-Request-ID','X-Content-Type-Options','Content-Security-Policy','Strict-Transport-Security'):
            assert allowed.headers[header]
