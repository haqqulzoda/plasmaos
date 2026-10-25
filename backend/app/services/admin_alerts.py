"""P1: alert the Plasma team on every new self sign-up and every pilot or call request
(P2: and every partner introduction or expert sourcing request).

``stage_admin_alert`` inserts one idempotent row in the caller's transaction. A Beat task
(and a kick right after the request commits) delivers due rows: Telegram when
ADMIN_ALERT_TELEGRAM_CHAT_ID is set (bot: ADMIN_ALERT_TELEGRAM_BOT_TOKEN, else
TELEGRAM_BOT_TOKEN), otherwise one ADMIN_ALERT e-mail per PLASMA_ADMIN_EMAILS address through
the e-mail outbox. Telegram failures retry with backoff (5 attempts). Logs carry ids, kinds and
error codes only; the bot token never appears in a log line or an error code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import configured_email_allowlist
from app.core.config import settings
from app.models.admin_alerts import AdminAlert
from app.services.email_notifications import email_channel_enabled, stage_email

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BATCH = 20
METHOD_LABELS = {"GOOGLE": "Google", "EMAIL_CODE": "e-mail code"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def telegram_target() -> tuple[str, str] | None:
    chat_id = (settings.ADMIN_ALERT_TELEGRAM_CHAT_ID or "").strip()
    token = (settings.ADMIN_ALERT_TELEGRAM_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN or "").strip()
    return (token, chat_id) if chat_id and token else None


def admin_alert_channel() -> str | None:
    if telegram_target() is not None:
        return "TELEGRAM"
    if email_channel_enabled() and configured_email_allowlist("PLASMA_ADMIN_EMAILS"):
        return "EMAIL"
    return None


async def stage_admin_alert(db: AsyncSession, *, kind: str, dedupe_key: str, payload: dict[str, Any]) -> bool:
    result = await db.execute(
        pg_insert(AdminAlert)
        .values(dedupe_key=dedupe_key[:200], kind=kind, payload=payload, state="PENDING", attempt_count=0)
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(AdminAlert.id)
    )
    return result.scalar_one_or_none() is not None


async def stage_new_signup(db: AsyncSession, *, user_id: UUID, email: str, name: str | None, method: str) -> bool:
    return await stage_admin_alert(
        db, kind="NEW_SIGNUP", dedupe_key=f"admin-alert:signup:{user_id}",
        payload={"user_id": str(user_id), "email": email, "name": name or "", "method": method,
                 "at": _now().isoformat(timespec="seconds")},
    )


def render_alert(alert: AdminAlert) -> tuple[str, list[str]]:
    """(subject, lines): plain text, English (the team's language for admin surfaces)."""
    data = alert.payload or {}
    when = str(data.get("at") or alert.created_at.isoformat(timespec="seconds")).replace("T", " ").replace("+00:00", " UTC")
    if alert.kind == "NEW_SIGNUP":
        method = METHOD_LABELS.get(str(data.get("method")), str(data.get("method") or "?"))
        name = str(data.get("name") or "").strip()
        who = f"{name} <{data.get('email')}>" if name and name != data.get("email") else str(data.get("email"))
        return (f"New Plasma sign-up: {data.get('email')}", [
            f"New self sign-up: {who}",
            f"Signed in with {method} at {when}.",
            "They are in Explore until an admin moves their organization to pilot or paid.",
        ])
    if alert.kind == "ANALYSIS_PROVIDER_ERROR":
        return ("Plasma analyses are failing: the AI provider rejects the key or billing", [
            f"The analysis provider answered HTTP {data.get('status') or '401/402/403'} ({data.get('code') or 'account error'}) at {when}.",
            "Every analysis fails until the key, billing or quota is fixed (GEMINI_API_KEY on the host).",
            f"Example run: {data.get('analysis_run_id')}. Repeats at most once an hour while it lasts.",
        ])
    if alert.kind == "PLAN_USAGE":
        organization = data.get("organization_name") or "An organization"
        reached = str(data.get("threshold")) == "100"
        subject = f"Plasma plan {'limit reached' if reached else 'at 80%'}: {organization}"
        return subject, [
            f"{organization} has used {data.get('used')} of {data.get('limit')} pursuits on the {data.get('plan')} plan "
            f"(period {data.get('period_start')} to {data.get('period_end') or 'open'}).",
            "New pursuits are blocked until an upgrade or extra pursuits (admin: /admin/organizations)." if reached
            else "They will be blocked at the limit: offer an upgrade or extra pursuits.",
            f"At {when}.",
        ]
    if alert.kind == "BILLING":
        return _render_billing(data, when)
    if alert.kind == "PARTNER_REQUEST":
        organization = data.get("organization_name") or "An organization"
        tender = " ".join(filter(None, [str(data.get("tender_reference") or ""), str(data.get("tender_title") or "")]))
        if data.get("kind") == "EXPERT_SOURCING":
            subject = f"Plasma expert sourcing request: {organization}"
            first = f"{organization} asked Plasma to source a key expert."
        else:
            firm = f"{data.get('firm_name')} ({data.get('firm_country')})" if data.get("firm_country") else str(data.get("firm_name"))
            subject = f"Plasma partner introduction request: {organization} -> {data.get('firm_name')}"
            first = f"{organization} asked for an introduction to {firm}."
        lines = [first, f"Requested by {data.get('requester_email')} at {when}."]
        if tender:
            lines.append(f"Tender: {tender}")
        lines.append(f"Gap: {data.get('gap_summary')}")
        if data.get("note"):
            lines.append(f"Note: {data['note']}")
        lines.append("Work it on /admin/partner-requests. Nothing has been sent to the firm.")
        return subject, lines
    kind = {"call": "a call", "upgrade": "an upgrade or more pursuits"}.get(str(data.get("request")), "a pilot")
    lines = [
        f"{data.get('name') or data.get('email')} <{data.get('email')}> asked for {kind}.",
        f"Organization: {data.get('organization_name') or '(not set up yet)'}",
        f"Requested at {when}.",
    ]
    if data.get("phone"):
        lines.append(f"Phone: {data['phone']}")
    if data.get("message"):
        lines.append(f"Message: {data['message']}")
    label = "upgrade" if data.get("request") == "upgrade" else kind
    return (f"Plasma {label} request: {data.get('organization_name') or data.get('email')}", lines)


BILLING_PRODUCTS = {"pilot": "Pilot", "pursuit_desk": "Pursuit Desk", "extra_pursuit": "an extra pursuit",
                    "per_tender": "a per-tender review"}
BILLING_EVENTS = {
    "activated": "{organization} bought {product} ({method}): active now",
    "bank_transfer_paid": "{organization} paid invoice {invoice} by bank transfer",
    "suspended": "{organization}: invoice {invoice} unpaid on day 10, back to Explore",
    "refunded": "{organization}: {product} refunded",
    "partially_refunded": "{organization}: {product} partially refunded",
    "renewed": "{organization}: {product} renewed",
    "credit_already_used": "{organization}: the pilot credit was already used, check this order",
    "paid_after_close": "{organization} paid an order that was closed, check it",
    "subscription_canceled": "{organization} canceled the {product} subscription (active to the period end)",
    "subscription_revoked": "{organization}: {product} subscription ended, back to Explore",
    "subscription_active": "{organization}: {product} subscription active",
    "subscription_uncanceled": "{organization}: {product} subscription resumed",
    "plan_ended": "{organization}: {product} ended, back to Explore",
    "cancel_requested": "{organization} asked not to renew {product}: confirm on /admin/billing",
}


def _render_billing(data: dict[str, Any], when: str) -> tuple[str, list[str]]:
    organization = data.get("organization_name") or "An organization"
    product = BILLING_PRODUCTS.get(str(data.get("product") or data.get("ended_plan")),
                                   str(data.get("product") or data.get("ended_plan") or "the plan"))
    method = "card" if data.get("method") == "card" else "bank transfer"
    template = BILLING_EVENTS.get(str(data.get("event")), "{organization}: billing event {event}")
    headline = template.format(organization=organization, product=product, method=method,
                               invoice=data.get("invoice_number") or "", event=data.get("event"))
    amount = int(data.get("amount_cents") or 0) / 100
    lines = [headline + ".", f"Amount USD {amount:,.2f}" + (
        f" (pilot credit USD {int(data['credit_cents']) / 100:,.2f})" if data.get("credit_cents") else "") + ".",
        f"Plan now: {data.get('plan')}, billing status: {data.get('billing_status') or 'none'}.",
        f"At {when}. Billing console: /admin/billing"]
    if data.get("event") == "activated" and data.get("product") != "extra_pursuit":
        lines.insert(2, "An onboarding task is open in /admin/billing: book the kickoff.")
    return f"Plasma billing: {headline}", lines


@dataclass(frozen=True)
class TelegramOutcome:
    ok: bool
    error_code: str | None = None
    retry: bool = True


class TelegramTransport:
    async def send(self, token: str, chat_id: str, text: str) -> TelegramOutcome:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                )
        except Exception as exc:  # noqa: BLE001 - classified; the URL (with the token) is never logged
            return TelegramOutcome(False, f"TELEGRAM_{type(exc).__name__}"[:80])
        if response.status_code == 200:
            return TelegramOutcome(True)
        return TelegramOutcome(False, f"TELEGRAM_HTTP_{response.status_code}", retry=response.status_code >= 500 or response.status_code == 429)


async def deliver_due_alerts(
    db: AsyncSession, *, telegram: TelegramTransport | None = None, now: Callable[[], datetime] | None = None,
) -> dict[str, int]:
    clock = now or _now
    counts = {"leased": 0, "SENT": 0, "FAILED": 0, "RETRY": 0}
    rows = list((await db.scalars(
        select(AdminAlert)
        .where(AdminAlert.state == "PENDING", AdminAlert.next_attempt_at <= clock())
        .order_by(AdminAlert.next_attempt_at, AdminAlert.id)
        .limit(BATCH)
        .with_for_update(skip_locked=True)
    )).all())
    counts["leased"] = len(rows)
    target = telegram_target()
    admins = sorted(configured_email_allowlist("PLASMA_ADMIN_EMAILS"))
    transport = telegram or TelegramTransport()
    for alert in rows:
        alert.attempt_count += 1
        subject, lines = render_alert(alert)
        if target is not None:
            outcome = await transport.send(target[0], target[1], "\n".join([subject, "", *lines]))
            if outcome.ok:
                alert.state, alert.channel, alert.sent_at, alert.last_error_code = "SENT", "TELEGRAM", clock(), None
            elif outcome.retry and alert.attempt_count < MAX_ATTEMPTS:
                alert.next_attempt_at = clock() + timedelta(seconds=60 * (2 ** (alert.attempt_count - 1)))
                alert.last_error_code = outcome.error_code
            else:
                alert.state, alert.channel, alert.last_error_code = "FAILED", "TELEGRAM", outcome.error_code
        elif email_channel_enabled() and admins:
            for address in admins:
                await stage_email(
                    db, dedupe_key=f"email:admin-alert:{alert.id}:{address}", kind="ADMIN_ALERT", category="ADMIN",
                    recipient_email=address, locale="en", payload={"subject": subject, "lines": lines},
                )
            alert.state, alert.channel, alert.sent_at, alert.last_error_code = "SENT", "EMAIL", clock(), None
        else:
            alert.state, alert.last_error_code = "FAILED", "NO_CHANNEL"
        counts[alert.state if alert.state != "PENDING" else "RETRY"] += 1
        logger.info("admin_alert id=%s kind=%s state=%s channel=%s code=%s",
                    alert.id, alert.kind, alert.state, alert.channel, alert.last_error_code)
    await db.commit()
    return counts


def kick_admin_alerts() -> None:
    """Deliver now instead of at the next Beat tick; Beat stays the fallback."""
    try:
        from app.core.celery_app import celery_app

        celery_app.send_task("app.workers.communications_tasks.deliver_admin_alerts")
    except Exception as exc:  # noqa: BLE001
        logger.warning("admin_alert_kick_failed error_type=%s", type(exc).__name__)
