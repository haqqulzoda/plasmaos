"""R3 Task 4: e-mail notifications over SMTP, against a fake SMTP server.

Templates and SMTP outcome rules first, then a Postgres scenario: invitation, outbox
events (analysis, EOI), preferences, the daily digest, retries, bounces and idempotency.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
import logging
import smtplib
import socketserver
import threading
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.endpoints import organizations as org_endpoints
from app.api.endpoints import users as user_endpoints
from app.core.config import settings
from app.models.communications import NotificationDelivery, NotificationEvent, NotificationOutbox
from app.models.email import EmailDelivery
from app.models.user import User
from app.schemas.tenancy import EmailInvitationCreateRequest, InvitationResendRequest
from app.services import email_notifications as email
from app.services.email_templates import LOCALES, render_email
from app.services.notifications import publish_outbox_batch, stage_system_outbox
from scripts import test_s0_5b4_baseline as support
from test_w2_organization_pursuit_foundation import W1_HEAD, _seed_w1


REVISION = "20261010_0001_r3_email_notifications"
HEAD = "20261011_0001_r3_organization_record_events"
PREVIOUS = "20261009_0001_r3_cv_library_drafts"


# ---- fake SMTP server -----------------------------------------------------------------------------

class FakeSmtp:
    """A minimal SMTP server: records messages, refuses chosen recipients, defers on demand."""

    def __init__(self) -> None:
        self.messages: list[bytes] = []
        self.refuse: set[str] = set()
        self.defer_next = 0
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                self.wfile.write(b"220 fake.smtp ESMTP\r\n")
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    command = line.decode("utf-8", "replace").strip()
                    upper = command.upper()
                    if upper.startswith("EHLO"):
                        self.wfile.write(b"250-fake.smtp\r\n250 8BITMIME\r\n")
                    elif upper.startswith("HELO") or upper.startswith("RSET") or upper.startswith("NOOP"):
                        self.wfile.write(b"250 OK\r\n")
                    elif upper.startswith("MAIL FROM"):
                        if outer.defer_next:
                            outer.defer_next -= 1
                            self.wfile.write(b"451 4.3.0 try again later\r\n")
                        else:
                            self.wfile.write(b"250 OK\r\n")
                    elif upper.startswith("RCPT TO"):
                        address = command.split(":", 1)[1].strip().strip("<>").split(">")[0].lower()
                        self.wfile.write(b"550 5.1.1 no such user\r\n" if address in outer.refuse else b"250 OK\r\n")
                    elif upper == "DATA":
                        self.wfile.write(b"354 end with .\r\n")
                        chunks = []
                        while True:
                            data = self.rfile.readline()
                            if data in (b".\r\n", b".\n", b""):
                                break
                            chunks.append(data[1:] if data.startswith(b"..") else data)
                        outer.messages.append(b"".join(chunks))
                        self.wfile.write(b"250 queued\r\n")
                    elif upper == "QUIT":
                        self.wfile.write(b"221 bye\r\n")
                        return
                    else:
                        self.wfile.write(b"502 not implemented\r\n")

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "FakeSmtp":
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()

    def parsed(self, index: int = -1):
        return message_from_bytes(self.messages[index], policy=policy.default)


def _configure(monkeypatch: pytest.MonkeyPatch, port: int | None) -> None:
    monkeypatch.setattr(settings, "SMTP_HOST", "127.0.0.1" if port else None)
    monkeypatch.setattr(settings, "SMTP_PORT", port or 587)
    monkeypatch.setattr(settings, "SMTP_FROM", "Plasma <noreply@plasma.test>" if port else None)
    monkeypatch.setattr(settings, "SMTP_TLS", "none")
    monkeypatch.setattr(settings, "SMTP_USER", None)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "never-logged-secret")
    monkeypatch.setattr(settings, "PUBLIC_APP_URL", "https://app.example")


# ---- pure rules -----------------------------------------------------------------------------------

def test_templates_exist_in_every_locale_with_links_and_escaping() -> None:
    contexts = {
        "TEAM_INVITATION": {"inviter_name": "Ada <b>", "organization_name": "Codex & Co <script>", "role": "MEMBER",
                            "invite_url": "https://app.example/invite/tok", "expires_on": "2026-10-22"},
        "ANALYSIS_COMPLETED": {"pursuit_id": "p1"},
        "ANALYSIS_FAILED": {"pursuit_id": "p1"},
        "EOI_DRAFT_READY": {"pursuit_id": "p1", "version_number": 3},
        "DAILY_DIGEST": {"total": 12, "items": [
            {"tender_id": f"t{n}", "title": f"Tender {n}", "country": "Uzbekistan", "deadline": "2026-11-01"} for n in range(12)
        ]},
    }
    subjects = {}
    for kind, context in contexts.items():
        for locale in LOCALES:
            rendered = render_email(kind, locale, context, app_url="https://app.example")
            assert rendered.subject and rendered.text.strip() and rendered.html.startswith("<!doctype html>")
            assert "https://app.example/" in rendered.text and 'href="https://app.example/' in rendered.html
            assert ('dir="rtl"' in rendered.html) == (locale == "ar")
            assert "<script>" not in rendered.html and "<b>" not in rendered.html
            subjects[(kind, locale)] = rendered.subject
    assert len({subjects[("ANALYSIS_COMPLETED", locale)] for locale in LOCALES}) == 4
    digest = render_email("DAILY_DIGEST", "en", contexts["DAILY_DIGEST"], app_url="https://app.example")
    assert digest.text.count("/dashboard/tenders/t") == 10 and "And 2 more" in digest.text
    assert "/dashboard/pursuits/p1?tab=eoi" in render_email("EOI_DRAFT_READY", "ru", contexts["EOI_DRAFT_READY"], app_url="https://app.example").text
    with pytest.raises(ValueError):
        render_email("UNKNOWN", "en", {}, app_url="https://app.example")


def test_smtp_outcomes_classify_bounces_permanent_and_transient() -> None:
    refused = smtplib.SMTPRecipientsRefused({"a@b.c": (550, b"no such user")})
    assert email.classify_smtp_error(refused) == email.SendOutcome("BOUNCED", "SMTP_RECIPIENT_REFUSED_550")
    assert email.classify_smtp_error(smtplib.SMTPRecipientsRefused({"a@b.c": (450, b"busy")})).state == "PENDING"
    assert email.classify_smtp_error(smtplib.SMTPDataError(554, b"rejected")) == email.SendOutcome("FAILED", "SMTP_554")
    assert email.classify_smtp_error(smtplib.SMTPSenderRefused(451, b"later", "x")).state == "PENDING"
    assert email.classify_smtp_error(ConnectionRefusedError()).error_code == "SMTP_UNAVAILABLE"
    assert email.classify_smtp_error(KeyError("x")) == email.SendOutcome("FAILED", "RENDER_ERROR")
    assert email.next_digest_run(datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc)) == datetime(2026, 10, 8, 3, 0, tzinfo=timezone.utc)
    assert email.next_digest_run(datetime(2026, 10, 8, 3, 0, tzinfo=timezone.utc)) == datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc)


def test_production_refuses_plain_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    base = dict(
        ENVIRONMENT="production", POSTGRES_SERVER="db", POSTGRES_USER="u", POSTGRES_PASSWORD="p", POSTGRES_DB="d",
        SECRET_KEY="s" * 40, AUTH_BRIDGE_SECRET="b" * 40, TELEGRAM_BOT_TOKEN="t",
        BACKEND_CORS_ORIGINS=["https://app.example"], PRIVATE_DOCUMENT_SCAN_HOST="clamav",
    )
    with pytest.raises(ValueError, match="SMTP_TLS"):
        Settings(**base, SMTP_HOST="smtp.example", SMTP_TLS="none")
    assert Settings(**base, SMTP_HOST="smtp.example", SMTP_TLS="starttls").SMTP_PORT == 587


# ---- migration ------------------------------------------------------------------------------------

def test_r3_04_migration_is_additive_reversible_and_drift_free() -> None:
    async def scenario() -> None:
        database = support.database_name("r3_04_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", PREVIOUS)
            await asyncio.to_thread(support.alembic, database, "upgrade", REVISION)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('email_deliveries')")
                assert await connection.fetchval("SELECT to_regclass('email_notification_preferences')")
                assert await connection.fetchval(
                    "SELECT count(*) FROM pg_constraint WHERE conname LIKE 'ck_email_delivery_%'"
                ) == 8
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", PREVIOUS)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('email_deliveries')") is None
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


# ---- Postgres scenario ----------------------------------------------------------------------------

def test_email_channel_end_to_end_with_a_fake_smtp_server(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    async def scenario() -> None:
        database = support.database_name("r3_04_email")
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
                await connection.execute(
                    "UPDATE company_profiles SET target_countries='[\"Uzbekistan\"]'::json, pilot_status='active_pilot' WHERE id=$1",
                    ids["profile_a"],
                )
                await connection.execute("UPDATE company_profiles SET pilot_status='lead' WHERE id=$1", ids["profile_b"])
                await connection.execute("UPDATE users SET ui_locale='ru' WHERE id=$1", ids["user_a"])
                now = datetime.now(timezone.utc)
                for index in range(14):
                    created = now - timedelta(hours=1) if index < 12 else now - timedelta(days=3)
                    country = "Uzbekistan" if index != 11 else "Kenya"
                    await connection.execute(
                        """
                        INSERT INTO tenders(id,external_id,source_system,canonical_source_key,source_url,title,description,
                            budget,currency,category,status,deadline,country,created_at)
                        VALUES ($1,$2,'world_bank',$3,'https://example.invalid/t',$4,'Consulting services',
                            100000,'USD','Services','OPEN',$5,$6,$7)
                        """,
                        uuid4(), f"R3-{index}", f"world_bank:R3-{index}", f"Digest tender {index}",
                        now + timedelta(days=30), country, created,
                    )
            finally:
                await connection.close()
            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                await _flow(sessions, ids, org_a, org_b, monkeypatch, caplog)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _deliveries(db, **where) -> list[EmailDelivery]:
    statement = select(EmailDelivery).order_by(EmailDelivery.created_at, EmailDelivery.id)
    for key, value in where.items():
        statement = statement.where(getattr(EmailDelivery, key) == value)
    return list((await db.scalars(statement)).all())


async def _flow(sessions, ids, org_a, org_b, monkeypatch, caplog) -> None:
    create = org_endpoints.create_email_invitation_endpoint

    # Channel disabled (no SMTP_HOST): nothing is staged, the link is copied by hand.
    _configure(monkeypatch, None)
    async with sessions() as db:
        user_a = await db.get(User, ids["user_a"])
        invitation = await create(organization_id=org_a, payload=EmailInvitationCreateRequest(email="off@example.org"),
                                  current_user=user_a, db=db)
        await db.commit()
        assert invitation.email_delivery == "DISABLED"
        assert await db.scalar(select(func.count(EmailDelivery.id))) == 0
        assert await email.send_due_emails(db) == {"leased": 0}
        prefs = await user_endpoints.get_email_preferences(current_user=user_a, db=db)
        assert prefs.email_channel_enabled is False

    with FakeSmtp() as smtp:
        _configure(monkeypatch, smtp.port)
        transport = email.SmtpTransport()

        # Team invitation: queued, sent once, in the inviter's locale, with the one-time link.
        async with sessions() as db:
            user_a = await db.get(User, ids["user_a"])
            invited = await create(organization_id=org_a, payload=EmailInvitationCreateRequest(email="new.person@example.org"),
                                   current_user=user_a, db=db)
            await db.commit()
            assert invited.email_delivery == "QUEUED"
            token = invited.invite_path.removeprefix("/invite/")
            [row] = await _deliveries(db, kind="TEAM_INVITATION")
            assert row.state == "PENDING" and row.locale == "ru" and row.recipient_email == "new.person@example.org"
            assert row.secret_ciphertext and token not in row.secret_ciphertext and token not in str(row.payload)
            result = await email.send_due_emails(db, transport=transport)
            assert result["SENT"] == 1
            message = smtp.parsed()
            assert message["To"] == "new.person@example.org" and message["From"] == "Plasma <noreply@plasma.test>"
            assert "Plasma" in message["Subject"] and message["Message-ID"] == f"<{row.id}@plasma.test>"
            plain = message.get_body(("plain",)).get_content()
            html = message.get_body(("html",)).get_content()
            assert f"https://app.example/invite/{token}" in plain and f"https://app.example/invite/{token}" in html
            assert "Принять приглашение" in plain
            await db.refresh(row)
            assert row.state == "SENT" and row.sent_at is not None and row.secret_ciphertext is None
            # Idempotent: nothing left to send; resending is a new e-mail with a new link.
            assert (await email.send_due_emails(db, transport=transport))["leased"] == 0
            resent = await org_endpoints.resend_email_invitation_endpoint(
                organization_id=org_a, invitation_id=invited.invitation_id, payload=InvitationResendRequest(send_email=True),
                current_user=user_a, db=db,
            )
            link_only = await org_endpoints.resend_email_invitation_endpoint(
                organization_id=org_a, invitation_id=invited.invitation_id, payload=InvitationResendRequest(send_email=False),
                current_user=user_a, db=db,
            )
            await db.commit()
            assert resent.email_delivery == "QUEUED" and link_only.email_delivery == "SKIPPED"
            assert len(await _deliveries(db, kind="TEAM_INVITATION")) == 2
            await email.send_due_emails(db, transport=transport)
            assert len(smtp.messages) == 2

        # Outbox events: inbox + e-mail by preference, replays deduplicated.
        async with sessions() as db:
            payload = {"organization_id": str(org_a), "pursuit_id": str(uuid4()), "analysis_run_id": str(uuid4())}
            await stage_system_outbox(db, user_id=ids["user_a"], event_type="PURSUIT_ANALYSIS_COMPLETED",
                                      payload=payload, dedupe_key=f"pursuit-analysis:{payload['analysis_run_id']}:COMPLETED")
            await stage_system_outbox(db, user_id=ids["user_a"], event_type="PURSUIT_ANALYSIS_COMPLETED",
                                      payload=payload, dedupe_key=f"pursuit-analysis:{payload['analysis_run_id']}:COMPLETED")
            eoi = {"organization_id": str(org_a), "pursuit_id": payload["pursuit_id"], "eoi_draft_id": str(uuid4()), "version_number": 2}
            await stage_system_outbox(db, user_id=ids["user_a"], event_type="EOI_DRAFT_READY", payload=eoi,
                                      dedupe_key=f"eoi-draft:{eoi['eoi_draft_id']}:{ids['user_a']}")
            # user_b switched analysis e-mails off: inbox only.
            user_b = await db.get(User, ids["user_b"])
            off = await user_endpoints.update_email_preferences(
                payload=user_endpoints.EmailPreferencesUpdate(analysis_enabled=False), current_user=user_b, db=db,
            )
            assert off.analysis_enabled is False and off.eoi_enabled is True and off.digest_enabled is False
            failed = {"organization_id": str(org_b), "pursuit_id": str(uuid4()), "analysis_run_id": str(uuid4())}
            await stage_system_outbox(db, user_id=ids["user_b"], event_type="PURSUIT_ANALYSIS_FAILED",
                                      payload=failed, dedupe_key=f"pursuit-analysis:{failed['analysis_run_id']}:FAILED")
            await db.commit()
            staged_types = sorted((await db.scalars(select(NotificationOutbox.event_type).where(NotificationOutbox.published_at.is_(None)))).all())
            # (The seed's legacy analysis version already staged one ANALYSIS_COMPLETED.)
            assert staged_types == ["ANALYSIS_COMPLETED", "EOI_DRAFT_READY", "PURSUIT_ANALYSIS_COMPLETED", "PURSUIT_ANALYSIS_FAILED"]
            assert await publish_outbox_batch(db) == 4
            await db.commit()
            assert await publish_outbox_batch(db) == 0
            await db.commit()
            assert await db.scalar(
                select(func.count(NotificationDelivery.id)).join(NotificationEvent, NotificationEvent.id == NotificationDelivery.event_id)
                .where(NotificationEvent.event_type.in_(["PURSUIT_ANALYSIS_COMPLETED", "PURSUIT_ANALYSIS_FAILED", "EOI_DRAFT_READY"]))
            ) == 3
            kinds = sorted(row.kind for row in await _deliveries(db) if row.kind != "TEAM_INVITATION")
            assert kinds == ["ANALYSIS_COMPLETED", "EOI_DRAFT_READY"]
            await email.send_due_emails(db, transport=transport)
            subjects = [smtp.parsed(index)["Subject"] for index in (-2, -1)]
            assert "Ваш анализ готов" in subjects and any("2" in subject for subject in subjects)
            analysis_mail = next(smtp.parsed(index) for index in (-2, -1) if smtp.parsed(index)["Subject"] == "Ваш анализ готов")
            assert f"/dashboard/pursuits/{payload['pursuit_id']}?tab=requirements" in analysis_mail.get_body(("plain",)).get_content()

        # Transient failure retries with backoff; a refused recipient is recorded as a bounce.
        async with sessions() as db:
            user_a = await db.get(User, ids["user_a"])
            smtp.refuse.add("gone@example.org")
            await create(organization_id=org_a, payload=EmailInvitationCreateRequest(email="gone@example.org"), current_user=user_a, db=db)
            await create(organization_id=org_a, payload=EmailInvitationCreateRequest(email="later@example.org"), current_user=user_a, db=db)
            await db.commit()
            smtp.defer_next = 1
            first = await email.send_due_emails(db, transport=transport)
            assert first["BOUNCED"] + first["RETRY"] + first["SENT"] == 2
            states = {row.recipient_email: row for row in await _deliveries(db, kind="TEAM_INVITATION")}
            gone, later = states["gone@example.org"], states["later@example.org"]
            assert gone.state in {"BOUNCED", "PENDING"}
            pending = [row for row in (gone, later) if row.state == "PENDING"]
            assert len(pending) == 1 and pending[0].last_error_code == "SMTP_451" and pending[0].next_attempt_at > datetime.now(timezone.utc)
            assert (await email.send_due_emails(db, transport=transport))["leased"] == 0  # backoff respected
            later_clock = lambda: datetime.now(timezone.utc) + timedelta(minutes=5)  # noqa: E731
            await email.send_due_emails(db, transport=transport, now=later_clock)
            for row in (gone, later):
                await db.refresh(row)
            assert gone.state == "BOUNCED" and gone.last_error_code == "SMTP_RECIPIENT_REFUSED_550" and gone.secret_ciphertext is None
            assert later.state == "SENT" and later.attempt_count in {1, 2}

        # Daily digest: pilot members only (default on), up to 10 matching new open items, once a day.
        async with sessions() as db:
            moment = datetime.now(timezone.utc)
            assert await email.stage_daily_digests(db, now=moment) == 1
            assert await email.stage_daily_digests(db, now=moment) == 0
            await db.commit()
            [digest] = await _deliveries(db, kind="DAILY_DIGEST")
            assert digest.user_id == ids["user_a"] and digest.payload["total"] == 11 and len(digest.payload["items"]) == 10
            assert all(item["country"] == "Uzbekistan" for item in digest.payload["items"])
            await email.send_due_emails(db, transport=transport)
            text = smtp.parsed()  # the digest
            body = text.get_body(("plain",)).get_content()
            assert text["Subject"].startswith("Новые открытые возможности") and body.count("/dashboard/tenders/") == 10
            assert "И ещё 1" in body and "https://app.example/dashboard/tenders\n" in body
            # Opting out stops the next day's digest.
            user_a = await db.get(User, ids["user_a"])
            await user_endpoints.update_email_preferences(
                payload=user_endpoints.EmailPreferencesUpdate(digest_enabled=False), current_user=user_a, db=db,
            )
            assert await email.stage_daily_digests(db, now=moment + timedelta(days=1)) == 0
            prefs = await user_endpoints.get_email_preferences(current_user=user_a, db=db)
            assert prefs.email_channel_enabled and prefs.digest_enabled is False and prefs.analysis_enabled is True

    # Logs name deliveries and codes only: never the password, addresses, tokens or bodies.
    logged = caplog.text
    assert "email_delivery id=" in logged
    for secret in ("never-logged-secret", "new.person@example.org", "gone@example.org", token, "Принять"):
        assert secret not in logged
