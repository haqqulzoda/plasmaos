"""P1-01: e-mail one-time-code sign-in, rotating 30-day sessions, no manual user approval.

Pure rules (code, hash, template, bridge assertion, fail-closed limits), the migration (pending
users approved and audited, reversible), then one Postgres scenario through the endpoints:
identical answers, lockout, expiry, single use, rate limits, same user as Google, invitations,
refresh rotation with reuse detection, logout and the outbox send.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials
import jwt
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.api.endpoints import auth as auth_endpoints
from app.api.endpoints import organizations as org_endpoints
from app.core import auth_bridge, rate_limit
from app.core.config import settings
from app.core.security import decode_access_token
from app.models.all_models import AdminActivityEvent
from app.models.auth_sessions import AuthRefreshToken, EmailSignInChallenge
from app.models.base import MembershipState
from app.models.email import EmailDelivery
from app.models.invitations import PendingInvitation
from app.models.tenancy import Membership
from app.models.user import User
from app.schemas.tenancy import EmailInvitationCreateRequest
from app.services import auth_sessions, email_notifications, email_sign_in
from app.services.email_templates import render_email
from scripts import test_s0_5b4_baseline as support
from test_w2_organization_pursuit_foundation import W1_HEAD, _seed_w1

PREVIOUS_HEAD = "20261012_0002_s1_product_analytics"
REVISION = "20261016_0001_p1_email_sign_in"
HEAD = "20261016_0002_p1_organization_access"
SECRET = "b" * 40


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


# ---- pure rules -----------------------------------------------------------------------------------

def test_code_generation_hashing_and_normalization() -> None:
    codes = {email_sign_in.generate_code() for _ in range(200)}
    assert all(len(code) == 6 and code.isdigit() for code in codes) and len(codes) > 150
    challenge = uuid4()
    digest = email_sign_in.hash_code(challenge, "012345")
    assert len(digest) == 64 and "012345" not in digest
    assert digest != email_sign_in.hash_code(uuid4(), "012345")         # bound to the challenge id
    assert digest != email_sign_in.hash_code(challenge, "012346")
    assert email_sign_in.normalize_code(" 012 345 ") == "012345"
    for bad in (None, "", "12345", "1234567", "12a456", "１２３４５６"):
        assert email_sign_in.normalize_code(bad) is None, bad
    assert email_sign_in.hash_client(None) is None and len(email_sign_in.hash_client("198.51.100.7")) == 64
    assert email_sign_in.CODE_TTL == timedelta(minutes=10) and email_sign_in.MAX_ATTEMPTS == 5


def test_sign_in_code_email_in_every_locale_has_the_code_and_no_link() -> None:
    for locale in ("en", "ru", "uz", "ar"):
        rendered = render_email("SIGN_IN_CODE", locale, {"code": "604218", "expires_minutes": 10}, app_url="https://app.example")
        assert "604218" in rendered.text and "604218" in rendered.html, locale
        assert "604218" not in rendered.subject, locale                  # never on a lock screen
        assert "href" not in rendered.html and "https://" not in rendered.text, locale
        assert "10" in rendered.text, locale
    assert 'dir="rtl"' in render_email("SIGN_IN_CODE", "ar", {"code": "1", "expires_minutes": 10}, app_url="").html


def test_build_message_never_sends_a_stale_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", "k" * 40)
    monkeypatch.setattr(settings, "SMTP_FROM", "Plasma <no-reply@plasmaos.uz>")
    sealed = email_notifications.seal_secret("123456")
    live = SimpleNamespace(
        id=uuid4(), kind="SIGN_IN_CODE", locale="en", recipient_email="a@example.org", secret_ciphertext=sealed,
        payload={"expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(), "expires_minutes": 10},
    )
    message = email_notifications.build_message(live, link_base="https://app.example")
    assert "123456" in message.get_body(("plain",)).get_content()
    stale = SimpleNamespace(**{**live.__dict__, "payload": {"expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}})
    with pytest.raises(ValueError):
        email_notifications.build_message(stale, link_base="")
    assert email_notifications.classify_smtp_error(ValueError("x")).state == "FAILED"


def _assertion(**overrides) -> str:
    now = int(time.time())
    claims = {"purpose": "email_code", "email": "a@example.org", "client_ip": "198.51.100.7",
              "iss": "plasma-authjs", "aud": "plasma-backend", "iat": now, "exp": now + 60, "jti": str(uuid4())}
    claims.update(overrides)
    claims = {key: value for key, value in claims.items() if value is not None}
    return jwt.encode(claims, SECRET, algorithm="HS256")


def test_email_code_bridge_assertion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_BRIDGE_SECRET", SECRET)
    seen: set[str] = set()

    async def consume(jti):
        if jti in seen:
            return False
        seen.add(jti)
        return True

    monkeypatch.setattr(auth_bridge, "consume_assertion", consume)
    run = lambda token, email="a@example.org": asyncio.run(auth_bridge.verify_email_code_assertion(token, email=email))  # noqa: E731
    good = _assertion()
    assert run(good)["client_ip"] == "198.51.100.7"
    for bad in (
        good,                                                            # single use
        _assertion(purpose="google"),
        _assertion(email_verified=True),                                 # a Google assertion is never accepted
        _assertion(email="b@example.org"),
        _assertion(iat=int(time.time()) - 120, exp=int(time.time()) - 60),
        _assertion(exp=int(time.time()) + 600),
        _assertion(iss="someone-else"),
        _assertion(client_ip="x" * 65),
        jwt.encode({"purpose": "email_code", "email": "a@example.org"}, "c" * 40, algorithm="HS256"),
        "",
    ):
        with pytest.raises(HTTPException) as refused:
            run(bad)
        assert refused.value.status_code == 401
    assert run(_assertion(email="A@Example.org"), email="a@example.org")["email"] == "A@Example.org"
    monkeypatch.setattr(settings, "AUTH_BRIDGE_SECRET", None)
    with pytest.raises(HTTPException) as unavailable:
        run(_assertion())
    assert unavailable.value.status_code == 503


def test_rate_limit_fails_closed_when_asked() -> None:
    down = FakeRedis(fail=True)
    assert asyncio.run(rate_limit.hit("x", "y", limit=5, window_seconds=60, client=down)) is None
    assert asyncio.run(rate_limit.hit("x", "y", limit=5, window_seconds=60, client=down, fail_closed=True)) == 30


# ---- migration ------------------------------------------------------------------------------------

def test_p1_01_migration_approves_pending_users_and_is_reversible() -> None:
    async def scenario() -> None:
        database = support.database_name("p1_01_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", PREVIOUS_HEAD)
            pending, disabled, approved = uuid4(), uuid4(), uuid4()
            connection = await support.database_connection(database)
            try:
                for user_id, state, before in ((pending, "pending", None), (disabled, "disabled", "pending"),
                                               (approved, "approved", None)):
                    await connection.execute(
                        "INSERT INTO users(id,google_id,email,name,subscription_tier,is_admin,approval_status,"
                        "platform_role,auth_version,pre_disabled_approval_status) "
                        "VALUES ($1,$2,$3,'n','SCOUT',false,$4,'pilot_user',0,$5)",
                        user_id, f"g-{user_id}", f"{state}@example.org", state, before,
                    )
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", REVISION)
            connection = await support.database_connection(database)
            try:
                rows = {r["id"]: r for r in await connection.fetch(
                    "SELECT id, approval_status, approved_at, pre_disabled_approval_status, auth_version FROM users")}
                assert rows[pending]["approval_status"] == "approved" and rows[pending]["approved_at"] is not None
                assert rows[pending]["auth_version"] == 0                 # nobody is signed out by the migration
                assert rows[disabled]["approval_status"] == "disabled"
                assert rows[disabled]["pre_disabled_approval_status"] == "approved"
                events = await connection.fetch(
                    "SELECT target_user_id, actor_type, source, previous_state->>'approval_status' AS before "
                    "FROM admin_activity_events WHERE action='USER_APPROVED'")
                assert {(e["target_user_id"], e["before"]) for e in events} == {(pending, "pending"), (disabled, "disabled")}
                assert {(e["actor_type"], e["source"]) for e in events} == {("SYSTEM", "P1_MIGRATION")}
                default = await connection.fetchval(
                    "SELECT column_default FROM information_schema.columns WHERE table_name='users' AND column_name='approval_status'")
                assert "approved" in default
                for table in ("email_sign_in_challenges", "auth_refresh_tokens"):
                    assert await connection.fetchval("SELECT to_regclass($1)", table)
                assert await connection.fetchval("SELECT to_regclass('uq_email_sign_in_open_email')")
                check = await connection.fetchval(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_email_delivery_kind'")
                assert "SIGN_IN_CODE" in check
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", PREVIOUS_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('email_sign_in_challenges')") is None
                assert await connection.fetchval("SELECT to_regclass('auth_refresh_tokens')") is None
                check = await connection.fetchval(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_email_delivery_kind'")
                assert "SIGN_IN_CODE" not in check
                assert await connection.fetchval("SELECT approval_status FROM users WHERE id=$1", pending) == "approved"
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


# ---- Postgres scenario ----------------------------------------------------------------------------

def _request(client: str = "198.51.100.7") -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": (client, 40000)})


def test_email_code_sign_in_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        database = support.database_name("p1_01_email_sign_in")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            redis = FakeRedis()
            monkeypatch.setattr(rate_limit, "_redis", lambda: redis)
            monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test")
            monkeypatch.setattr(settings, "SMTP_FROM", "Plasma <no-reply@plasmaos.uz>")
            monkeypatch.setattr(settings, "PUBLIC_APP_URL", "https://app.example")
            monkeypatch.setattr(settings, "AUTH_BRIDGE_SECRET", SECRET)
            monkeypatch.setenv("PLASMA_ADMIN_EMAILS", "boss@example.org")
            monkeypatch.setenv("PLASMA_OPERATOR_EMAILS", "")
            kicks: list[int] = []
            monkeypatch.setattr(auth_endpoints, "_kick_email_sender", lambda: kicks.append(1))

            async def consume(_jti):
                return True

            monkeypatch.setattr(auth_bridge, "consume_assertion", consume)
            try:
                await _scenario(sessions, ids, redis, kicks, database)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _request_code(sessions, email: str, client: str = "198.51.100.7"):
    async with sessions() as db:
        return await auth_endpoints.request_email_code(
            payload=auth_endpoints.EmailCodeRequest(email=email), request=_request(client), response=Response(), db=db,
        )


async def _code_for(sessions, email: str) -> str:
    async with sessions() as db:
        delivery = await db.scalar(
            select(EmailDelivery).where(EmailDelivery.recipient_email == email, EmailDelivery.kind == "SIGN_IN_CODE")
            .order_by(EmailDelivery.created_at.desc()).limit(1)
        )
        return email_notifications.open_secret(delivery.secret_ciphertext)


async def _verify(sessions, email: str, code: str):
    async with sessions() as db:
        return await auth_endpoints.verify_email_code(
            payload=auth_endpoints.EmailCodeVerifyRequest(email=email, code=code, bridge_assertion=_assertion(email=email)),
            response=Response(), db=db,
        )


async def _expect(coro, status: int, code: str | None = None):
    with pytest.raises(HTTPException) as failure:
        await coro
    assert failure.value.status_code == status, failure.value.detail
    if code is not None:
        assert failure.value.detail == {"code": code}
    return failure.value


async def _scenario(sessions, ids, redis, kicks, database) -> None:
    connection = await support.database_connection(database)
    try:
        await connection.execute(
            "INSERT INTO users(id,google_id,email,name,subscription_tier,is_admin,approval_status,platform_role,auth_version) "
            "VALUES ($1,'g-dis','disabled@example.org','d','SCOUT',false,'disabled','pilot_user',0),"
            "($2,'g-adm','admin@example.org','a','SCOUT',true,'approved','admin',0),"
            "($3,'g-pend','legacy@example.org','l','SCOUT',false,'pending','pilot_user',0)",
            uuid4(), uuid4(), uuid4(),
        )
    finally:
        await connection.close()

    # 1. The same answer for a new address, an existing user, a disabled account, an admin and an allowlisted address.
    answers = []
    for email in ("new.one@example.org", "user_a@same-domain.invalid", "disabled@example.org", "admin@example.org", "boss@example.org"):
        answers.append((await _request_code(sessions, email)).model_dump())
    assert all(answer == answers[0] for answer in answers)
    assert answers[0] == {"status": "accepted", "expires_in_seconds": 600, "resend_after_seconds": 60}
    async with sessions() as db:
        deliveries = {d.recipient_email: d for d in (await db.scalars(select(EmailDelivery))).all()}
        assert set(deliveries) == {"new.one@example.org", "user_a@same-domain.invalid"}   # blocked/privileged: no e-mail
        staged = deliveries["new.one@example.org"]
        assert staged.kind == "SIGN_IN_CODE" and staged.category == "AUTH" and staged.secret_ciphertext
        assert set(staged.payload) == {"challenge_id", "expires_at", "expires_minutes"}      # the code is not in the payload
        challenges = {c.email: c for c in (await db.scalars(select(EmailSignInChallenge))).all()}
        assert {c.email: c.delivery for c in challenges.values()} == {
            "new.one@example.org": "STAGED", "user_a@same-domain.invalid": "STAGED",
            "disabled@example.org": "ACCOUNT_BLOCKED", "admin@example.org": "PRIVILEGED", "boss@example.org": "PRIVILEGED",
        }
        code = email_notifications.open_secret(staged.secret_ciphertext)
        assert challenges["new.one@example.org"].code_hash == email_sign_in.hash_code(challenges["new.one@example.org"].id, code)
        assert challenges["new.one@example.org"].requester_ip_hash != "198.51.100.7"
        requested = (await db.scalars(select(AdminActivityEvent).where(
            AdminActivityEvent.action == "EMAIL_SIGN_IN_CODE_REQUESTED"))).all()
        assert len(requested) == 5 and all(code not in str(e.metadata_json) for e in requested)
    assert len(kicks) == 2

    # 2. Rate limits: one request a minute per address (429 + Retry-After), five an hour; fail closed without Redis.
    failure = await _expect(_request_code(sessions, "new.one@example.org"), 429, "RATE_LIMITED")
    assert int(failure.headers["Retry-After"]) >= 1
    await _expect(_request_code(sessions, "not-an-email"), 422, "INVALID_EMAIL")
    redis.fail = True
    await _expect(_request_code(sessions, "fresh@example.org"), 429, "RATE_LIMITED")
    redis.fail = False
    redis.counts.clear()

    # 3. Wrong codes: four INVALID_CODE, the fifth locks the challenge; then even the right code is refused.
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(4):
        await _expect(_verify(sessions, "new.one@example.org", wrong), 400, "INVALID_CODE")
    await _expect(_verify(sessions, "new.one@example.org", wrong), 400, "CODE_EXPIRED")
    await _expect(_verify(sessions, "new.one@example.org", code), 400, "CODE_EXPIRED")
    async with sessions() as db:
        locked = await db.scalar(select(EmailSignInChallenge).where(EmailSignInChallenge.email == "new.one@example.org"))
        assert (locked.close_reason, locked.attempt_count) == ("LOCKED", 5)
        assert await db.scalar(select(func.count(AdminActivityEvent.id)).where(
            AdminActivityEvent.action == "EMAIL_SIGN_IN_CODE_LOCKED")) == 1
        assert await db.scalar(select(func.count(User.id)).where(User.email == "new.one@example.org")) == 0
    redis.counts.clear()

    # 4. A new code supersedes nothing open; the right code signs in once: a new, approved account.
    await _request_code(sessions, "New.One@Example.org")
    code = await _code_for(sessions, "new.one@example.org")
    token = await _verify(sessions, "NEW.ONE@example.org", code)
    assert token.approval_status == "approved" and token.onboarding_required is True and token.refresh_token
    claims = decode_access_token(token.access_token)
    assert claims["email"] == "new.one@example.org" and UUID(claims["sid"])
    await _expect(_verify(sessions, "new.one@example.org", code), 400, "CODE_EXPIRED")    # single use
    async with sessions() as db:
        user = await db.scalar(select(User).where(User.email == "new.one@example.org"))
        assert user.google_id.startswith(email_sign_in.PREPROVISIONED_GOOGLE_ID_PREFIX)
        assert user.approval_status == "approved" and user.approved_at is not None
        assert await db.scalar(select(func.count(AdminActivityEvent.id)).where(
            AdminActivityEvent.action == "EMAIL_SIGN_IN_SUCCEEDED", AdminActivityEvent.target_user_id == user.id)) == 1
        family = (await db.scalars(select(AuthRefreshToken).where(AuthRefreshToken.user_id == user.id))).all()
        assert len(family) == 1 and family[0].sign_in_method == "EMAIL_CODE"
        assert family[0].token_hash == auth_sessions.hash_refresh_token(token.refresh_token)
        assert timedelta(days=29) < family[0].expires_at - family[0].created_at <= timedelta(days=30)
    redis.counts.clear()

    # 5. Requesting again supersedes the open code; an expired code is refused.
    await _request_code(sessions, "late@example.org")
    first = await _code_for(sessions, "late@example.org")
    redis.counts.clear()
    await _request_code(sessions, "late@example.org")
    second = await _code_for(sessions, "late@example.org")
    async with sessions() as db:
        reasons = sorted((c.close_reason or "OPEN") for c in (await db.scalars(
            select(EmailSignInChallenge).where(EmailSignInChallenge.email == "late@example.org"))).all())
        assert reasons == ["OPEN", "SUPERSEDED"]
    if first != second:
        await _expect(_verify(sessions, "late@example.org", first), 400, "INVALID_CODE")
    async with sessions() as db:
        with pytest.raises(email_sign_in.CodeExpiredError):
            await email_sign_in.verify_code(db, raw_email="late@example.org", raw_code=second, client=None,
                                            now=datetime.now(timezone.utc) + timedelta(minutes=11))
        await db.commit()
    redis.counts.clear()

    # 6. Blocked and privileged accounts never get an e-mail, so they cannot sign in with a code.
    async with sessions() as db:
        for email in ("disabled@example.org", "admin@example.org"):
            challenge = await db.scalar(select(EmailSignInChallenge).where(
                EmailSignInChallenge.email == email, EmailSignInChallenge.closed_at.is_(None)))
            assert challenge is not None and not await db.scalar(select(EmailDelivery.id).where(EmailDelivery.recipient_email == email))

    # 7. The same verified address reaches the same user through Google: no duplicate, the row binds.
    google = {"email": "new.one@example.org", "sub": "google-new-one", "name": "New One", "avatar_url": None}

    async def verified(_payload):
        return google

    auth_endpoints.verify_bridge_assertion = verified  # restored below
    try:
        async with sessions() as db:
            google_token = await auth_endpoints.google_auth_bridge(
                payload=auth_endpoints.GoogleAuthRequest(google_id="google-new-one", email="new.one@example.org", name="New One"),
                response=Response(), db=db,
            )
        assert google_token.refresh_token and google_token.approval_status == "approved"
        async with sessions() as db:
            rows = (await db.scalars(select(User).where(func.lower(User.email) == "new.one@example.org"))).all()
            assert len(rows) == 1 and rows[0].google_id == "google-new-one" and str(rows[0].id) == claims["sub"]
        # And back: a code still reaches the now Google-bound user.
        await _request_code(sessions, "new.one@example.org")
        again = await _verify(sessions, "new.one@example.org", await _code_for(sessions, "new.one@example.org"))
        assert decode_access_token(again.access_token)["sub"] == claims["sub"]
        redis.counts.clear()

        # A pending account from before P1 is approved at its next Google sign-in (audited).
        google.update(email="legacy@example.org", sub="g-pend", name="Legacy")
        async with sessions() as db:
            legacy = await auth_endpoints.google_auth_bridge(
                payload=auth_endpoints.GoogleAuthRequest(google_id="g-pend", email="legacy@example.org", name="Legacy"),
                response=Response(), db=db,
            )
        assert legacy.approval_status == "approved"
        async with sessions() as db:
            event = await db.scalar(select(AdminActivityEvent).where(
                AdminActivityEvent.action == "USER_APPROVED", AdminActivityEvent.target_email == "legacy@example.org"))
            assert event.previous_state["approval_status"] == "pending" and event.metadata_json["sign_in_method"] == "GOOGLE"
    finally:
        auth_endpoints.verify_bridge_assertion = auth_bridge.verify_bridge_assertion

    # 8. An open invitation is accepted on code sign-in exactly as on Google.
    connection = await support.database_connection(database)
    try:
        org_a = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"])
    finally:
        await connection.close()
    async with sessions() as db:
        owner = await db.get(User, ids["user_a"])
        await org_endpoints.create_email_invitation_endpoint(
            organization_id=org_a, payload=EmailInvitationCreateRequest(email="Invitee@Example.org", role="MEMBER"),
            current_user=owner, db=db,
        )
        await db.commit()
    await _request_code(sessions, "invitee@example.org")
    joined = await _verify(sessions, "invitee@example.org", await _code_for(sessions, "invitee@example.org"))
    assert joined.onboarding_required is False and str(joined.company_profile_id) == str(ids["profile_a"])
    async with sessions() as db:
        invitee = await db.scalar(select(User).where(User.email == "invitee@example.org"))
        membership = await db.scalar(select(Membership).where(Membership.user_id == invitee.id))
        assert (membership.organization_id, membership.state) == (org_a, MembershipState.ACTIVE)
        invitation = await db.scalar(select(PendingInvitation).where(PendingInvitation.email == "invitee@example.org"))
        assert invitation.accepted_user_id == invitee.id
        accepted = await db.scalar(select(AdminActivityEvent).where(AdminActivityEvent.action == "ORGANIZATION_INVITATION_ACCEPTED",
                                                                    AdminActivityEvent.target_user_id == invitee.id))
        assert accepted.actor_label == "auth/email-code"
    redis.counts.clear()

    # 9. Rotation: a new pair each time; a rotated token inside the grace window gets a sibling,
    #    after it the whole family is revoked (audited); auth_version and logout end a family.
    rotate = lambda refresh: _rotate(sessions, refresh)  # noqa: E731
    second_pair = await rotate(token.refresh_token)
    assert second_pair.refresh_token != token.refresh_token
    assert decode_access_token(second_pair.access_token)["sid"] == claims["sid"]
    sibling = await rotate(token.refresh_token)                                            # concurrent tab: allowed
    assert sibling.refresh_token not in {token.refresh_token, second_pair.refresh_token}
    async with sessions() as db:
        old = await db.scalar(select(AuthRefreshToken).where(
            AuthRefreshToken.token_hash == auth_sessions.hash_refresh_token(token.refresh_token)))
        old.rotated_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        await db.commit()
    await _expect(rotate(token.refresh_token), 401)
    await _expect(rotate(second_pair.refresh_token), 401)                                  # the family is gone
    async with sessions() as db:
        revoked = (await db.scalars(select(AuthRefreshToken).where(AuthRefreshToken.family_id == UUID(claims["sid"])))).all()
        assert revoked and all(row.revoke_reason == "REUSE_DETECTED" for row in revoked)
        assert await db.scalar(select(func.count(AdminActivityEvent.id)).where(
            AdminActivityEvent.action == "REFRESH_REUSE_DETECTED")) == 1
    await _expect(rotate("x" * 43), 401)

    pair = await rotate(again.refresh_token)
    async with sessions() as db:
        user = await db.scalar(select(User).where(User.email == "new.one@example.org"))
        user.auth_version += 1                                                             # e.g. a role change
        await db.commit()
    await _expect(rotate(pair.refresh_token), 401)

    await _request_code(sessions, "invitee@example.org")
    fresh = await _verify(sessions, "invitee@example.org", await _code_for(sessions, "invitee@example.org"))
    async with sessions() as db:
        await auth_endpoints.logout(
            response=Response(), credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=fresh.access_token), db=db,
        )
    await _expect(rotate(fresh.refresh_token), 401)
    async with sessions() as db:
        assert {row.revoke_reason for row in (await db.scalars(select(AuthRefreshToken).where(
            AuthRefreshToken.family_id == UUID(decode_access_token(fresh.access_token)["sid"])))).all()} == {"LOGOUT"}

    # 10. The outbox sends the code once, then wipes the sealed secret; logs and payloads never hold it.
    sent = []

    class Transport:
        def send(self, message):
            sent.append(message)

    async with sessions() as db:
        await db.execute(EmailDelivery.__table__.update().where(EmailDelivery.state == "PENDING").values(state="FAILED", secret_ciphertext=None))
        await db.commit()
    redis.counts.clear()
    await _request_code(sessions, "mail@example.org")
    mail_code = await _code_for(sessions, "mail@example.org")
    async with sessions() as db:
        counts = await email_notifications.send_due_emails(db, transport=Transport())
    assert counts["SENT"] == 1 and len(sent) == 1
    assert mail_code in sent[0].get_body(("plain",)).get_content() and mail_code not in sent[0]["Subject"]
    async with sessions() as db:
        row = await db.scalar(select(EmailDelivery).where(EmailDelivery.recipient_email == "mail@example.org"))
        assert row.state == "SENT" and row.secret_ciphertext is None


async def _rotate(sessions, refresh_token: str):
    async with sessions() as db:
        return await auth_endpoints.rotate_session(
            payload=auth_endpoints.SessionRotateRequest(refresh_token=refresh_token), request=_request(),
            response=Response(), db=db,
        )
