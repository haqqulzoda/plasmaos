"""R3 Task 4: the SMTP e-mail channel of the notification outbox.

Staging: an idempotent ``email_deliveries`` row per e-mail (the outbox dedupe key, the
invitation id and send count, or the digest day), only when the channel is configured
and the recipient's preference allows it. Sending: a Beat task leases due rows, renders
the localized template (links only, no private content), sends over SMTP with TLS and
records SENT, BOUNCED (recipient refused) or FAILED; transient failures retry with
backoff. Logs carry delivery ids, kinds and error codes only, never credentials,
addresses or bodies.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate
import hashlib
import logging
import smtplib
import socket
import ssl
from typing import Any, Callable
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import COMPANY_PILOT_ACTIVE, COMPANY_PILOT_SCOPED, USER_APPROVAL_APPROVED
from app.core.config import settings
from app.models.base import MembershipState
from app.models.email import EmailDelivery, EmailNotificationPreference
from app.models.invitations import PendingInvitation
from app.models.tenancy import Membership, Organization
from app.models.user import User
from app.services.email_templates import LOCALES, render_email

logger = logging.getLogger(__name__)

EMAIL_DELIVERY_QUEUED = "QUEUED"
EMAIL_DELIVERY_DISABLED = "DISABLED"

MAX_SEND_ATTEMPTS = 5
SEND_BATCH = 25
LEASE_SECONDS = 300
DIGEST_TIMEZONE = ZoneInfo("Asia/Tashkent")
DIGEST_HOUR = 8
DIGEST_MAX_ITEMS = 10
PILOT_STATUSES = (COMPANY_PILOT_SCOPED, COMPANY_PILOT_ACTIVE)

# Outbox event types that also go out by e-mail: (kind, category, preference column).
EVENT_EMAILS: dict[str, tuple[str, str, str]] = {
    "PURSUIT_ANALYSIS_COMPLETED": ("ANALYSIS_COMPLETED", "ANALYSIS", "analysis_enabled"),
    "PURSUIT_ANALYSIS_FAILED": ("ANALYSIS_FAILED", "ANALYSIS", "analysis_enabled"),
    "EOI_DRAFT_READY": ("EOI_DRAFT_READY", "EOI", "eoi_enabled"),
}
PREFERENCE_FIELDS = ("analysis_enabled", "eoi_enabled", "digest_enabled")


# ---- configuration --------------------------------------------------------------------------------

def email_channel_enabled() -> bool:
    return bool((settings.SMTP_HOST or "").strip() and (settings.SMTP_FROM or "").strip())


def app_url() -> str | None:
    value = (settings.PUBLIC_APP_URL or "").strip().rstrip("/")
    return value or None


def _fernet():
    from cryptography.fernet import Fernet

    key = hashlib.sha256(f"plasma:r3:email-secret:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def open_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def user_locale(user: User | None) -> str:
    locale = (getattr(user, "ui_locale", None) or "en") if user is not None else "en"
    return locale if locale in LOCALES else "en"


# ---- preferences ----------------------------------------------------------------------------------

async def _is_pilot_member(db: AsyncSession, user_id: UUID) -> bool:
    from app.services.organization_context import effective_company_profile

    profile = await effective_company_profile(db, user_id=user_id)
    return bool(profile is not None and profile.approval_status == "approved" and profile.pilot_status in PILOT_STATUSES)


async def effective_preferences(db: AsyncSession, user: User) -> dict[str, bool]:
    """Stored switches, else defaults: analysis and EOI on; the digest on for pilot organizations."""
    stored = await db.get(EmailNotificationPreference, user.id)
    defaults = {"analysis_enabled": True, "eoi_enabled": True, "digest_enabled": await _is_pilot_member(db, user.id)}
    return {
        field: (getattr(stored, field) if stored is not None and getattr(stored, field) is not None else defaults[field])
        for field in PREFERENCE_FIELDS
    }


async def update_preferences(db: AsyncSession, user: User, changes: dict[str, bool]) -> dict[str, bool]:
    values = {field: bool(changes[field]) for field in PREFERENCE_FIELDS if changes.get(field) is not None}
    if values:
        await db.execute(
            pg_insert(EmailNotificationPreference)
            .values(user_id=user.id, **values)
            .on_conflict_do_update(index_elements=["user_id"], set_={**values, "updated_at": func.now()})
        )
        await db.flush()
        stored = await db.get(EmailNotificationPreference, user.id)
        if stored is not None:
            await db.refresh(stored)
    return await effective_preferences(db, user)


# ---- staging --------------------------------------------------------------------------------------

async def stage_email(
    db: AsyncSession,
    *,
    dedupe_key: str,
    kind: str,
    category: str,
    recipient_email: str,
    locale: str,
    payload: dict[str, Any],
    user_id: UUID | None = None,
    secret: str | None = None,
) -> bool:
    """Insert one delivery; a replay with the same dedupe key changes nothing."""
    if not email_channel_enabled() or not recipient_email:
        return False
    result = await db.execute(
        pg_insert(EmailDelivery)
        .values(
            dedupe_key=dedupe_key[:200], kind=kind, category=category, user_id=user_id,
            recipient_email=recipient_email.strip().lower(), locale=locale if locale in LOCALES else "en",
            payload=payload, secret_ciphertext=seal_secret(secret) if secret else None,
            state="PENDING", attempt_count=0,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(EmailDelivery.id)
    )
    return result.scalar_one_or_none() is not None


async def queue_invitation_email(
    db: AsyncSession, *, invitation: PendingInvitation, token: str, inviter: User
) -> str:
    """Queue the team invitation e-mail; without a channel or app URL the link is copied by hand."""
    if not email_channel_enabled() or app_url() is None:
        return EMAIL_DELIVERY_DISABLED
    organization = await db.get(Organization, invitation.organization_id)
    invitee = await db.scalar(select(User).where(func.lower(User.email) == invitation.email))
    await stage_email(
        db,
        dedupe_key=f"email:invitation:{invitation.id}:{invitation.send_count}",
        kind="TEAM_INVITATION", category="TEAM", recipient_email=invitation.email,
        locale=user_locale(invitee) if invitee is not None else user_locale(inviter),
        payload={
            "invitation_id": str(invitation.id),
            "organization_name": (organization.display_name if organization is not None else None),
            "inviter_name": inviter.name,
            "role": invitation.role.value,
            "expires_on": invitation.expires_at.date().isoformat(),
        },
        user_id=invitee.id if invitee is not None else None,
        secret=token,
    )
    return EMAIL_DELIVERY_QUEUED


async def stage_event_email(
    db: AsyncSession, *, user_id: UUID, event_type: str, payload: dict[str, Any], dedupe_key: str
) -> bool:
    """The e-mail of one published outbox event, when the user's preference allows it."""
    mapping = EVENT_EMAILS.get(event_type)
    if mapping is None or not email_channel_enabled():
        return False
    user = await db.get(User, user_id)
    if user is None or user.approval_status != USER_APPROVAL_APPROVED or not user.email:
        return False
    kind, category, field = mapping
    if not (await effective_preferences(db, user))[field]:
        return False
    return await stage_email(
        db, dedupe_key=f"email:{dedupe_key}", kind=kind, category=category, recipient_email=user.email,
        locale=user_locale(user), payload=dict(payload), user_id=user.id,
    )


# ---- daily digest ---------------------------------------------------------------------------------

def digest_day(now: datetime) -> date:
    return now.astimezone(DIGEST_TIMEZONE).date()


async def stage_daily_digests(db: AsyncSession, *, now: datetime | None = None) -> int:
    """At most one digest per user and Tashkent day, with up to 10 items, only when any match."""
    from app.api.endpoints.tenders import apply_explorer_tender_filters
    from app.models.all_models import Tender
    from app.models.company import CompanyProfile
    from app.services.profile_match import (
        profile_match_condition,
        profile_match_tier_expression,
        profile_targets,
    )

    if not email_channel_enabled():
        return 0
    now = now or datetime.now(timezone.utc)
    day = digest_day(now)
    since = now - timedelta(hours=24)
    rows = (
        await db.execute(
            select(User, CompanyProfile)
            .join(Membership, Membership.user_id == User.id)
            .join(Organization, Organization.id == Membership.organization_id)
            .join(CompanyProfile, CompanyProfile.id == Organization.legacy_company_profile_id)
            .where(
                Membership.state == MembershipState.ACTIVE,
                User.approval_status == USER_APPROVAL_APPROVED,
                CompanyProfile.approval_status == "approved",
            )
            .order_by(User.id, Membership.activated_at)
        )
    ).all()
    staged = 0
    seen: set[UUID] = set()
    for user, profile in rows:
        if user.id in seen:
            continue
        seen.add(user.id)
        if not (await effective_preferences(db, user))["digest_enabled"]:
            continue
        targets = profile_targets(profile.target_countries, profile.target_regions, profile.target_services)
        condition = profile_match_condition(targets)
        if condition is None:
            continue
        base = apply_explorer_tender_filters(select(Tender), tender_status="open")[0].where(
            Tender.created_at >= since, Tender.created_at <= now, condition,
        )
        total = int(await db.scalar(select(func.count()).select_from(base.subquery())) or 0)
        if not total:
            continue
        tenders = list((await db.scalars(
            base.order_by(profile_match_tier_expression(targets), Tender.created_at.desc(), Tender.id).limit(DIGEST_MAX_ITEMS)
        )).all())
        items = [
            {
                "tender_id": str(tender.id), "title": (tender.title or "")[:300], "country": tender.country,
                "deadline": tender.deadline.date().isoformat() if tender.deadline else None,
            }
            for tender in tenders
        ]
        staged += await stage_email(
            db, dedupe_key=f"email:digest:{user.id}:{day.isoformat()}", kind="DAILY_DIGEST", category="DIGEST",
            recipient_email=user.email, locale=user_locale(user),
            payload={"day": day.isoformat(), "total": total, "items": items}, user_id=user.id,
        )
    return staged


# ---- sending --------------------------------------------------------------------------------------

class SmtpTransport:
    """SMTP with STARTTLS (default) or implicit TLS; plain only when explicitly configured."""

    def send(self, message: EmailMessage) -> None:
        host, port = settings.SMTP_HOST or "", int(settings.SMTP_PORT)
        timeout = max(1, int(settings.SMTP_TIMEOUT_SECONDS))
        mode = (settings.SMTP_TLS or "starttls").strip().lower()
        if mode == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(host, port, timeout=timeout)
        try:
            client.ehlo()
            if mode == "starttls":
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if settings.SMTP_USER:
                client.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
            client.send_message(message)
        finally:
            try:
                client.quit()
            except Exception:  # noqa: BLE001 - the message outcome is already known
                client.close()


@dataclass(frozen=True)
class SendOutcome:
    state: str
    error_code: str | None = None


def classify_smtp_error(exc: Exception) -> SendOutcome:
    """BOUNCED: the server refused the recipient; FAILED: permanent; PENDING: retry later."""
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = [code for code, _ in exc.recipients.values()]
        if codes and all(int(code) >= 500 for code in codes):
            return SendOutcome("BOUNCED", f"SMTP_RECIPIENT_REFUSED_{codes[0]}")
        return SendOutcome("PENDING", "SMTP_RECIPIENT_DEFERRED")
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return SendOutcome("PENDING", "SMTP_AUTH")
    if isinstance(exc, smtplib.SMTPResponseException):
        code = int(exc.smtp_code)
        return SendOutcome("FAILED" if 500 <= code < 600 else "PENDING", f"SMTP_{code}")
    if isinstance(exc, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, socket.timeout, TimeoutError, OSError)):
        return SendOutcome("PENDING", "SMTP_UNAVAILABLE")
    if isinstance(exc, smtplib.SMTPException):
        return SendOutcome("PENDING", "SMTP_ERROR")
    return SendOutcome("FAILED", "RENDER_ERROR")


def build_message(delivery: EmailDelivery, *, link_base: str) -> EmailMessage:
    context = dict(delivery.payload or {})
    if delivery.kind == "TEAM_INVITATION":
        if not delivery.secret_ciphertext:
            raise ValueError("invitation link is no longer available")
        context["invite_url"] = f"{link_base}/invite/{open_secret(delivery.secret_ciphertext)}"
    rendered = render_email(delivery.kind, delivery.locale, context, app_url=link_base)
    sender = (settings.SMTP_FROM or "").strip()
    domain = sender.rsplit("@", 1)[-1].strip(">") or "plasma.local"
    message = EmailMessage()
    message["From"] = sender
    message["To"] = delivery.recipient_email
    message["Subject"] = rendered.subject
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = f"<{delivery.id}@{domain}>"
    message["Auto-Submitted"] = "auto-generated"
    message["X-Plasma-Delivery"] = str(delivery.id)
    message.set_content(rendered.text)
    message.add_alternative(rendered.html, subtype="html")
    return message


async def _lease_due(db: AsyncSession, *, limit: int, now: datetime) -> list[UUID]:
    rows = list((await db.scalars(
        select(EmailDelivery)
        .where(
            EmailDelivery.next_attempt_at <= now,
            or_(
                EmailDelivery.state == "PENDING",
                (EmailDelivery.state == "SENDING") & (EmailDelivery.lease_until.is_(None) | (EmailDelivery.lease_until <= now)),
            ),
        )
        .order_by(EmailDelivery.next_attempt_at, EmailDelivery.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )).all())
    for row in rows:
        row.state = "SENDING"
        row.attempt_count += 1
        row.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    ids = [row.id for row in rows]
    await db.commit()
    return ids


async def send_due_emails(
    db: AsyncSession,
    *,
    transport: Any = None,
    limit: int = SEND_BATCH,
    now: Callable[[], datetime] | None = None,
) -> dict[str, int]:
    """Lease, send and record up to ``limit`` due e-mails. Safe to run concurrently."""
    clock = now or (lambda: datetime.now(timezone.utc))
    if not email_channel_enabled():
        return {"leased": 0}
    link_base = app_url() or ""
    transport = transport or SmtpTransport()
    counts = {"leased": 0, "SENT": 0, "BOUNCED": 0, "FAILED": 0, "RETRY": 0}
    ids = await _lease_due(db, limit=limit, now=clock())
    counts["leased"] = len(ids)
    for delivery_id in ids:
        delivery = await db.get(EmailDelivery, delivery_id)
        if delivery is None or delivery.state != "SENDING":
            continue
        try:
            message = build_message(delivery, link_base=link_base)
            await asyncio.to_thread(transport.send, message)
            outcome = SendOutcome("SENT")
        except Exception as exc:  # classified below; never logged with content
            outcome = classify_smtp_error(exc)
        delivery = await db.scalar(select(EmailDelivery).where(EmailDelivery.id == delivery_id).with_for_update())
        if delivery is None:
            continue
        current = clock()
        if outcome.state == "PENDING" and delivery.attempt_count < MAX_SEND_ATTEMPTS:
            delivery.state = "PENDING"
            delivery.next_attempt_at = current + timedelta(seconds=60 * (2 ** (delivery.attempt_count - 1)))
            counts["RETRY"] += 1
        else:
            delivery.state = "FAILED" if outcome.state == "PENDING" else outcome.state
            delivery.secret_ciphertext = None
            counts[delivery.state] += 1
        delivery.last_error_code = outcome.error_code
        delivery.sent_at = current if delivery.state == "SENT" else None
        delivery.lease_until = None
        await db.commit()
        logger.info(
            "email_delivery id=%s kind=%s state=%s attempt=%s code=%s",
            delivery.id, delivery.kind, delivery.state, delivery.attempt_count, outcome.error_code,
        )
    return counts


def next_digest_run(now: datetime) -> datetime:
    """The next 08:00 Asia/Tashkent, as UTC (shown in the admin source panel style)."""
    local = now.astimezone(DIGEST_TIMEZONE)
    candidate = datetime.combine(local.date(), time(DIGEST_HOUR), DIGEST_TIMEZONE)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)
