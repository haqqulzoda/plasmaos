"""R3: the public, token-gated invitation preview (POST /api/v1/invitations/preview).

1 tokens are 256-bit random and only their SHA-256 is stored and looked up;
2 unknown, expired, revoked and accepted tokens get one generic 404;
3 a usable token shows only organization name, inviter name, role, masked e-mail, expiry;
4 a per-client limit (30 per 10 minutes, Redis) answers 429 beyond it;
5 every answer carries Cache-Control: no-store and X-Robots-Tag: noindex;
6 accepting needs a signed-in user with the invited e-mail, and only while the invitation is open.
The database-backed proof (resend, revoke, accept, sign-in binding) is test_r3_01_invitations.py.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.endpoints import organizations as endpoints
from app.core import rate_limit
from app.db.session import get_db
from app.models.base import MembershipRole
from app.services import invitations as service

BACKEND = Path(__file__).resolve().parent
NOW = datetime.now(timezone.utc)


def _invitation(**state):
    values = dict(id=uuid4(), organization_id=uuid4(), invited_by_membership_id=uuid4(), email="new.person@example.org",
                  role=MembershipRole.MEMBER, accepted_at=None, revoked_at=None, expires_at=NOW + timedelta(days=14))
    values.update(state)
    return SimpleNamespace(**values)


def _preview(invitation, monkeypatch):
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[invitation, "Ada Owner"]))
    profile = (SimpleNamespace(display_name="Acme Consulting"), SimpleNamespace(company_name="Acme LLC"))
    monkeypatch.setattr(service, "_organization_profile", AsyncMock(return_value=profile))
    return asyncio.run(service.preview_invitation(db, token="t" * 43))


def test_tokens_are_256_bit_random_and_only_their_hash_is_stored() -> None:
    source = (BACKEND / "app" / "services" / "invitations.py").read_text(encoding="utf-8")
    assert source.count("secrets.token_urlsafe(32)") == 2          # issue and resend: 32 bytes = 256 bits
    assert service.hash_token("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    model = (BACKEND / "app" / "models" / "invitations.py").read_text(encoding="utf-8")
    assert "token_hash" in model and "token:" not in model.replace("token_hash", "")  # no plaintext column
    # Lookups are by the stored hash (an index lookup of SHA-256(token)); the plaintext is never compared.
    assert source.count("PendingInvitation.token_hash == hash_token(") == 2


@pytest.mark.parametrize("state", [
    {"expires_at": NOW - timedelta(seconds=1)},
    {"revoked_at": NOW - timedelta(hours=1)},
    {"accepted_at": NOW - timedelta(hours=1)},
])
def test_non_usable_tokens_read_like_unknown_ones(state, monkeypatch) -> None:
    assert _preview(_invitation(**state), monkeypatch) is None
    assert _preview(None, monkeypatch) is None


def test_a_usable_token_shows_only_the_five_allowed_fields(monkeypatch) -> None:
    preview = _preview(_invitation(), monkeypatch)
    assert set(preview) == {"organization_name", "inviter_name", "role", "email_hint", "expires_at"}
    assert preview["email_hint"] == "n******@example.org" and preview["organization_name"] == "Acme Consulting"
    assert set(endpoints.InvitationPreviewResponse.model_fields) == set(preview)  # no ids, no full e-mail, no status


class FakeRedis:
    def __init__(self, fail: bool = False):
        self.counts, self.fail = {}, fail

    async def incr(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, seconds):
        return True


def test_rate_limit_counts_per_client_and_window_and_fails_open() -> None:
    redis = FakeRedis()

    def hit(client, now):
        return asyncio.run(rate_limit.hit("invitation_preview", client, limit=30, window_seconds=600, client=redis, now=now))

    assert [hit("198.51.100.7", 1_000_000.0) for _ in range(30)] == [None] * 30
    assert hit("198.51.100.7", 1_000_000.0) == 200                   # 31st: 429, retry when the window ends
    assert hit("203.0.113.9", 1_000_000.0) is None                    # another client has its own budget
    assert hit("198.51.100.7", 1_000_200.0 + 1) is None               # next window
    assert asyncio.run(rate_limit.hit("x", "y", limit=1, window_seconds=60, client=FakeRedis(fail=True))) is None


def _client(monkeypatch, preview_result):
    app = FastAPI()
    app.include_router(endpoints.invitations_router, prefix="/api/v1/invitations")
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    monkeypatch.setattr(endpoints, "preview_invitation", AsyncMock(return_value=preview_result))
    redis = FakeRedis()
    monkeypatch.setattr(rate_limit, "_redis", lambda: redis)
    return TestClient(app)


def test_every_answer_is_uncacheable_unindexed_and_rate_limited(monkeypatch) -> None:
    usable = {"organization_name": "Acme", "inviter_name": "Ada", "role": "MEMBER",
              "email_hint": "n******@example.org", "expires_at": NOW + timedelta(days=3)}
    client = _client(monkeypatch, usable)
    ok = client.post("/api/v1/invitations/preview", json={"token": "x" * 43})
    assert ok.status_code == 200 and set(ok.json()) == set(usable)
    assert ok.headers["cache-control"] == "no-store" and ok.headers["x-robots-tag"] == "noindex"

    missing = _client(monkeypatch, None).post("/api/v1/invitations/preview", json={"token": "x" * 43})
    assert missing.status_code == 404 and missing.json() == {"detail": "Invitation not found"}
    assert missing.headers["cache-control"] == "no-store" and missing.headers["x-robots-tag"] == "noindex"

    limited = _client(monkeypatch, None)
    codes = [limited.post("/api/v1/invitations/preview", json={"token": "x" * 43}).status_code for _ in range(31)]
    assert codes[:30] == [404] * 30 and codes[30] == 429
    last = limited.post("/api/v1/invitations/preview", json={"token": "x" * 43})
    assert last.status_code == 429 and int(last.headers["retry-after"]) > 0
    assert last.headers["cache-control"] == "no-store" and last.headers["x-robots-tag"] == "noindex"


def test_accepting_needs_a_session_with_the_invited_email_and_an_open_invitation() -> None:
    route = next(r for r in endpoints.invitations_router.routes if r.path == "/accept")
    assert route.dependencies, "accept must keep authenticated_dependency()"
    source = (BACKEND / "app" / "services" / "invitations.py").read_text(encoding="utf-8")
    accept = source[source.index("async def accept_invitation_token"):source.index("async def user_has_active_membership")]
    assert "if status != STATUS_OPEN:" in accept                     # accepted/expired/revoked tokens are dead
    assert '(user.email or "").strip().lower() != invitation.email' in accept
    assert "InvitationEmailMismatchError" in accept


def test_the_client_address_cannot_be_chosen_by_the_client() -> None:
    # The rate limit keys on request.client.host. docker-compose.yml runs uvicorn with
    # --forwarded-allow-ips limited to loopback and private (Docker network) ranges.
    import yaml
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    compose = yaml.safe_load((BACKEND.parent / "docker-compose.yml").read_text(encoding="utf-8"))
    command = compose["services"]["backend"]["command"]
    allowed = command[command.index("--forwarded-allow-ips") + 1]
    assert "--proxy-headers" in command and "*" not in allowed
    trusted = allowed.split(":-", 1)[1].rstrip("}")   # the default when BACKEND_FORWARDED_ALLOW_IPS is unset
    assert "0.0.0.0/0" not in trusted

    def client_of(peer: str, forwarded: str | None) -> str:
        seen = {}

        async def app(scope, receive, send):
            seen["client"] = scope["client"][0]

        headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
        scope = {"type": "http", "client": (peer, 50000), "headers": headers, "scheme": "http"}
        asyncio.run(ProxyHeadersMiddleware(app, trusted_hosts=trusted)(scope, None, None))
        return seen["client"]

    # A client talking to the backend directly cannot claim another address.
    assert client_of("203.0.113.5", "198.51.100.1") == "203.0.113.5"
    # Browser -> Caddy (sets the real client) -> Next.js (appends Caddy) -> backend.
    assert client_of("172.18.0.6", "198.51.100.7, 172.18.0.9") == "198.51.100.7"
    # A forged entry in front of the chain is ignored: the rightmost untrusted address wins.
    assert client_of("172.18.0.6", "6.6.6.6, 198.51.100.7, 172.18.0.9") == "198.51.100.7"
    # API domain: Caddy -> backend directly.
    assert client_of("172.18.0.9", "198.51.100.7") == "198.51.100.7"
