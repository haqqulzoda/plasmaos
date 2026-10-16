#!/usr/bin/env python3
"""P1: send a sign-in code to an address, to prove SMTP and the DNS records end to end.

Run inside the backend container (it has the release's SMTP_* settings):

    scripts/compose-release.sh run --rm --no-deps -T backend \\
        python scripts/send_test_sign_in_code.py --to someone@example.org --confirm SEND_TEST_CODE

Default: the real path. It opens a sign-in challenge for the address exactly as the sign-in
page does (rate limits, audit event), then sends that one e-mail now and prints the outcome
(SENT / FAILED / BOUNCED with the SMTP error code). The code itself is never printed: it is
in the mailbox, and it signs that address in for 10 minutes. Admin and operator addresses get
no e-mail by design (they sign in with Google): use --direct for those.

--direct: render the same template with a random code that is stored nowhere and send it
straight over SMTP (no challenge, no audit event, no outbox row). The code does not work.

Check the received message's headers for ``spf=pass``, ``dkim=pass`` and ``dmarc=pass``.
"""

from __future__ import annotations

import argparse
import asyncio
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

CONFIRMATION = "SEND_TEST_CODE"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--to", required=True, help="Recipient address.")
    parser.add_argument("--confirm", default="", help=f"Required: {CONFIRMATION}")
    parser.add_argument("--direct", action="store_true", help="Send a non-working sample code straight over SMTP.")
    parser.add_argument("--locale", default="en", choices=("en", "ru", "uz", "ar"), help="Only with --direct.")
    return parser


async def _real(to: str) -> int:
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal, engine
    from app.models.email import EmailDelivery
    from app.services import email_sign_in
    from app.services.email_notifications import SmtpTransport, send_due_emails

    try:
        async with AsyncSessionLocal() as db:
            try:
                result, _code = await email_sign_in.request_code(db, raw_email=to, client="operator-test-command")
            except email_sign_in.EmailSignInError as exc:
                print(f"REFUSED: {exc.code}")
                return 2
            await db.commit()
            print(f"challenge {result.challenge_id} delivery={result.delivery} expires_at={result.expires_at.isoformat()}")
            if result.delivery != email_sign_in.DELIVERY_STAGED:
                reasons = {
                    email_sign_in.DELIVERY_NO_CHANNEL: "SMTP_HOST / SMTP_FROM are not configured",
                    email_sign_in.DELIVERY_PRIVILEGED: "an admin or operator address (Google only); use --direct",
                    email_sign_in.DELIVERY_ACCOUNT_BLOCKED: "the account is disabled or rejected",
                }
                print(f"NOT SENT: {reasons.get(result.delivery, result.delivery)}")
                return 2
            counts = await send_due_emails(db, transport=SmtpTransport())
            delivery = await db.scalar(
                select(EmailDelivery).where(EmailDelivery.dedupe_key == f"email:sign-in-code:{result.challenge_id}")
            )
            state = delivery.state if delivery is not None else "MISSING"
            print(f"outbox run {counts}; this delivery: state={state} error={getattr(delivery, 'last_error_code', None)}")
            return 0 if state == "SENT" else 1
    finally:
        await engine.dispose()


def _direct(to: str, locale: str) -> int:
    from app.core.config import settings
    from app.services.email_notifications import SmtpTransport, classify_smtp_error, email_channel_enabled
    from app.services.email_sign_in import generate_code
    from app.services.email_templates import render_email
    from app.services.invitations import normalize_email

    if not email_channel_enabled():
        print("NOT SENT: SMTP_HOST / SMTP_FROM are not configured")
        return 2
    rendered = render_email("SIGN_IN_CODE", locale, {"code": generate_code(), "expires_minutes": 10}, app_url="")
    sender = (settings.SMTP_FROM or "").strip()
    message = EmailMessage()
    message["From"] = sender
    message["To"] = normalize_email(to)
    message["Subject"] = f"[TEST] {rendered.subject}"
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1].strip(">") or None)
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(rendered.text)
    message.add_alternative(rendered.html, subtype="html")
    try:
        SmtpTransport().send(message)
    except Exception as exc:  # noqa: BLE001 - reported as the classified SMTP outcome
        outcome = classify_smtp_error(exc)
        print(f"FAILED: {outcome.state} {outcome.error_code}")
        return 1
    print("SENT (direct sample; the code in it does not sign anyone in)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.confirm != CONFIRMATION:
        print(f"REFUSED: pass --confirm {CONFIRMATION}")
        return 2
    if args.direct:
        return _direct(args.to, args.locale)
    return asyncio.run(_real(args.to))


if __name__ == "__main__":
    raise SystemExit(main())
