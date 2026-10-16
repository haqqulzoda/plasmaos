"""P1: sign in with a one-time code sent by e-mail.

Request: any syntactically valid address gets the same answer. A new challenge closes the
previous open one; the 6-digit code is kept only as HMAC-SHA256(key derived from SECRET_KEY,
challenge id + code) and travels to the outbox sealed (Fernet) until the delivery ends.
Blocked accounts (disabled, rejected) and privileged ones (admin, operator, or on an
allowlist: they sign in with Google only) get a challenge but no e-mail, so the outside
behaviour never depends on the account.

Verify: 10 minutes, single use, 5 wrong attempts close the challenge. Rate limits (Redis,
fail closed) per e-mail and per client address on both steps. Every request, success,
failure and lock is an administrative audit event; codes and hashes never are.

A verified address reaches the user with that e-mail, exactly as Google does: the first
Google sign-in later binds the same row (``PREPROVISIONED_GOOGLE_ID_PREFIX``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import logging
import re
import secrets
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.access import (
    PLATFORM_ROLE_ADMIN,
    PLATFORM_ROLE_OPERATOR,
    PLATFORM_ROLE_PILOT_USER,
    USER_APPROVAL_APPROVED,
    USER_APPROVAL_PENDING,
    configured_email_allowlist,
    is_disabled_account,
    is_rejected_account,
)
from app.core.config import settings
from app.models.auth_sessions import EmailSignInChallenge
from app.models.user import User
from app.services.admin_activity import (
    ACTION_EMAIL_SIGN_IN_CODE_LOCKED,
    ACTION_EMAIL_SIGN_IN_CODE_REQUESTED,
    ACTION_EMAIL_SIGN_IN_FAILED,
    ACTION_EMAIL_SIGN_IN_SUCCEEDED,
    ACTION_USER_APPROVED,
    ACTOR_SYSTEM,
    OUTCOME_DENIED,
    OUTCOME_FAILED,
    OUTCOME_SUCCESS,
    SOURCE_EMAIL_SIGN_IN,
    record_admin_audit_event,
    user_role_snapshot,
)
from app.services.email_notifications import email_channel_enabled, stage_email, user_locale
from app.services.invitations import InvitationError, mask_email, normalize_email

logger = logging.getLogger(__name__)

CODE_DIGITS = 6
CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
# Rate limits: (scope, limit, window seconds). Keyed by e-mail or by client address.
REQUEST_EMAIL_LIMITS = (("email_code_request_email_min", 1, 60), ("email_code_request_email_hour", 5, 3600))
REQUEST_IP_LIMITS = (("email_code_request_ip", 30, 3600),)
VERIFY_EMAIL_LIMITS = (("email_code_verify_email", 10, 600),)
VERIFY_IP_LIMITS = (("email_code_verify_ip", 30, 600),)
# A pre-provisioned row (no Google subject yet); the first verified Google sign-in binds it.
PREPROVISIONED_GOOGLE_ID_PREFIX = "plasma-preprovisioned:"

DELIVERY_STAGED = "STAGED"
DELIVERY_NO_CHANNEL = "NO_CHANNEL"
DELIVERY_ACCOUNT_BLOCKED = "ACCOUNT_BLOCKED"
DELIVERY_PRIVILEGED = "PRIVILEGED"


class EmailSignInError(RuntimeError):
    """Base class; ``code`` is the public, account-independent reason."""

    code = "INVALID_CODE"


class InvalidEmailError(EmailSignInError):
    code = "INVALID_EMAIL"


class RateLimitedError(EmailSignInError):
    code = "RATE_LIMITED"

    def __init__(self, retry_after: int) -> None:
        super().__init__("too many requests")
        self.retry_after = retry_after


class InvalidCodeError(EmailSignInError):
    code = "INVALID_CODE"


class CodeExpiredError(EmailSignInError):
    """No usable challenge: never requested, expired, used, superseded or locked."""

    code = "CODE_EXPIRED"


class AccountUnavailableError(EmailSignInError):
    code = "ACCOUNT_UNAVAILABLE"


@dataclass(frozen=True)
class CodeRequestResult:
    challenge_id: UUID
    delivery: str
    expires_at: datetime


@dataclass(frozen=True)
class VerifiedSignIn:
    user: User
    new_account: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _code_key() -> bytes:
    return hashlib.sha256(f"plasma:p1:email-sign-in-code:{settings.SECRET_KEY}".encode()).digest()


def hash_code(challenge_id: UUID, code: str) -> str:
    return hmac.new(_code_key(), f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def hash_client(client: str | None) -> str | None:
    if not client:
        return None
    return hmac.new(_code_key(), f"ip:{client}".encode(), hashlib.sha256).hexdigest()


def generate_code() -> str:
    return f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"


def normalize_code(raw: str | None) -> str | None:
    value = "".join((raw or "").split())
    return value if len(value) == CODE_DIGITS and value.isascii() and value.isdigit() else None


def display_name_for(email: str) -> str:
    """A first name for a code-only account: "aziza.rahimova@x" -> "Aziza Rahimova", else the local part."""
    local = email.split("@", 1)[0]
    parts = [part for part in re.split(r"[._-]+", local) if part]
    if len(parts) >= 2 and all(part.isalpha() for part in parts):
        return " ".join(part.capitalize() for part in parts)[:255]
    return local[:255]


def _email_key(email: str) -> str:
    # Rate-limit keys never carry the address itself.
    return hashlib.sha256(email.encode()).hexdigest()[:32]


async def _enforce(limits, identifier: str) -> None:
    for scope, limit, window in limits:
        retry_after = await rate_limit.hit(scope, identifier, limit=limit, window_seconds=window, fail_closed=True)
        if retry_after is not None:
            raise RateLimitedError(retry_after)


def privileged_email(email: str) -> bool:
    return email in configured_email_allowlist("PLASMA_ADMIN_EMAILS") or email in configured_email_allowlist(
        "PLASMA_OPERATOR_EMAILS"
    )


def _is_privileged(user: User | None, email: str) -> bool:
    if privileged_email(email):
        return True
    return user is not None and (bool(user.is_admin) or user.platform_role in {PLATFORM_ROLE_ADMIN, PLATFORM_ROLE_OPERATOR})


async def _user_by_email(db: AsyncSession, email: str, *, lock: bool = False) -> User | None:
    statement = select(User).where(func.lower(User.email) == email)
    if lock:
        statement = statement.with_for_update()
    return await db.scalar(statement)


async def _lock_email(db: AsyncSession, email: str) -> None:
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"email-sign-in:{email}"})


def _close(challenge: EmailSignInChallenge, reason: str, now: datetime) -> None:
    challenge.closed_at = now
    challenge.close_reason = reason


async def _audit(
    db: AsyncSession, *, action: str, outcome: str, email: str, user: User | None, reason: str,
    metadata: dict | None = None, previous_state: dict | None = None, new_state: dict | None = None,
) -> None:
    await record_admin_audit_event(
        db, action=action, outcome=outcome, source=SOURCE_EMAIL_SIGN_IN, target_user=user, target_email=email,
        actor_type=ACTOR_SYSTEM, actor_label="auth/email-code", reason=reason, metadata=metadata,
        previous_state=previous_state, new_state=new_state,
    )


async def request_code(
    db: AsyncSession, *, raw_email: str, client: str | None, now: datetime | None = None,
) -> tuple[CodeRequestResult, str]:
    """Open a challenge and stage its e-mail. Returns the result and the plain code.

    The caller commits and must not return or log the code (tests and the operator's
    test command read it). Raises InvalidEmailError or RateLimitedError only.
    """
    try:
        email = normalize_email(raw_email)
    except InvitationError:
        raise InvalidEmailError("a valid e-mail address is required") from None
    await _enforce(REQUEST_IP_LIMITS, client or "unknown")
    await _enforce(REQUEST_EMAIL_LIMITS, _email_key(email))

    moment = now or _now()
    await _lock_email(db, email)
    for open_challenge in (await db.scalars(
        select(EmailSignInChallenge).where(EmailSignInChallenge.email == email, EmailSignInChallenge.closed_at.is_(None))
    )).all():
        _close(open_challenge, "SUPERSEDED", moment)
    await db.flush()

    user = await _user_by_email(db, email)
    if user is not None and (is_disabled_account(user) or is_rejected_account(user)):
        delivery = DELIVERY_ACCOUNT_BLOCKED
    elif _is_privileged(user, email):
        delivery = DELIVERY_PRIVILEGED
    elif not email_channel_enabled():
        delivery = DELIVERY_NO_CHANNEL
    else:
        delivery = DELIVERY_STAGED

    code = generate_code()
    challenge_id = uuid4()
    expires_at = moment + CODE_TTL
    challenge = EmailSignInChallenge(
        id=challenge_id, email=email, code_hash=hash_code(challenge_id, code), attempt_count=0,
        expires_at=expires_at, delivery=delivery, requester_ip_hash=hash_client(client),
    )
    db.add(challenge)
    await db.flush()
    if delivery == DELIVERY_STAGED:
        staged = await stage_email(
            db, dedupe_key=f"email:sign-in-code:{challenge_id}", kind="SIGN_IN_CODE", category="AUTH",
            recipient_email=email, locale=user_locale(user),
            payload={"challenge_id": str(challenge_id), "expires_at": expires_at.isoformat(),
                     "expires_minutes": int(CODE_TTL.total_seconds() // 60)},
            user_id=user.id if user is not None else None, secret=code,
        )
        if not staged:
            challenge.delivery = DELIVERY_NO_CHANNEL
            delivery = DELIVERY_NO_CHANNEL
    if delivery == DELIVERY_NO_CHANNEL:
        logger.warning("email_sign_in_code_not_sent reason=no_channel challenge=%s", challenge_id)
    await _audit(
        db, action=ACTION_EMAIL_SIGN_IN_CODE_REQUESTED, outcome=OUTCOME_SUCCESS, email=email, user=user,
        reason="Sign-in code requested.",
        metadata={"challenge_id": str(challenge_id), "delivery": delivery, "existing_account": user is not None},
    )
    return CodeRequestResult(challenge_id=challenge_id, delivery=delivery, expires_at=expires_at), code


async def verify_code(
    db: AsyncSession, *, raw_email: str, raw_code: str, client: str | None, now: datetime | None = None,
) -> VerifiedSignIn:
    """Consume a valid code and return the (possibly new, always approved) user.

    Wrong-code attempts are committed by the caller even on failure: call ``db.commit()``
    in the error path too (the endpoint does).
    """
    try:
        email = normalize_email(raw_email)
    except InvitationError:
        raise InvalidCodeError("invalid code") from None
    await _enforce(VERIFY_IP_LIMITS, client or "unknown")
    await _enforce(VERIFY_EMAIL_LIMITS, _email_key(email))
    code = normalize_code(raw_code)
    moment = now or _now()

    await _lock_email(db, email)
    challenge = await db.scalar(
        select(EmailSignInChallenge)
        .where(EmailSignInChallenge.email == email, EmailSignInChallenge.closed_at.is_(None))
        .with_for_update()
    )
    if challenge is None:
        await _audit(db, action=ACTION_EMAIL_SIGN_IN_FAILED, outcome=OUTCOME_DENIED, email=email,
                     user=await _user_by_email(db, email), reason="No open sign-in code.",
                     metadata={"reason_code": "NO_OPEN_CODE"})
        raise CodeExpiredError("no usable code")
    if challenge.expires_at <= moment:
        _close(challenge, "EXPIRED", moment)
        await _audit(db, action=ACTION_EMAIL_SIGN_IN_FAILED, outcome=OUTCOME_DENIED, email=email,
                     user=await _user_by_email(db, email), reason="Sign-in code expired.",
                     metadata={"reason_code": "EXPIRED", "challenge_id": str(challenge.id)})
        raise CodeExpiredError("no usable code")

    if code is None or not hmac.compare_digest(challenge.code_hash, hash_code(challenge.id, code)):
        challenge.attempt_count += 1
        user = await _user_by_email(db, email)
        metadata = {"challenge_id": str(challenge.id), "attempt": challenge.attempt_count}
        if challenge.attempt_count >= MAX_ATTEMPTS:
            _close(challenge, "LOCKED", moment)
            await _audit(db, action=ACTION_EMAIL_SIGN_IN_CODE_LOCKED, outcome=OUTCOME_DENIED, email=email, user=user,
                         reason=f"Sign-in code closed after {MAX_ATTEMPTS} wrong attempts.", metadata=metadata)
            raise CodeExpiredError("no usable code")
        await _audit(db, action=ACTION_EMAIL_SIGN_IN_FAILED, outcome=OUTCOME_DENIED, email=email, user=user,
                     reason="Wrong sign-in code.", metadata={**metadata, "reason_code": "WRONG_CODE"})
        raise InvalidCodeError("invalid code")

    _close(challenge, "CONSUMED", moment)
    user = await _user_by_email(db, email, lock=True)
    if user is not None and (
        is_disabled_account(user) or is_rejected_account(user) or _is_privileged(user, email)
        or challenge.delivery != DELIVERY_STAGED
    ):
        # Unreachable without the mailbox: these challenges never sent an e-mail.
        await _audit(db, action=ACTION_EMAIL_SIGN_IN_FAILED, outcome=OUTCOME_FAILED, email=email, user=user,
                     reason="Account cannot sign in with an e-mail code.",
                     metadata={"reason_code": "ACCOUNT_UNAVAILABLE", "challenge_id": str(challenge.id)})
        raise AccountUnavailableError("account unavailable")
    if user is None and (challenge.delivery != DELIVERY_STAGED or privileged_email(email)):
        await _audit(db, action=ACTION_EMAIL_SIGN_IN_FAILED, outcome=OUTCOME_FAILED, email=email, user=None,
                     reason="Account cannot sign in with an e-mail code.",
                     metadata={"reason_code": "ACCOUNT_UNAVAILABLE", "challenge_id": str(challenge.id)})
        raise AccountUnavailableError("account unavailable")

    new_account = user is None
    if user is None:
        user = User(
            google_id=PREPROVISIONED_GOOGLE_ID_PREFIX + email, email=email, name=display_name_for(email),
            platform_role=PLATFORM_ROLE_PILOT_USER, approval_status=USER_APPROVAL_APPROVED, approved_at=moment,
        )
        db.add(user)
        await db.flush()
        await _audit(db, action=ACTION_USER_APPROVED, outcome=OUTCOME_SUCCESS, email=email, user=user,
                     reason="Verified e-mail address: approved at sign-up.", new_state=user_role_snapshot(user),
                     metadata={"sign_in_method": "EMAIL_CODE"})
    elif user.approval_status == USER_APPROVAL_PENDING:
        before = user_role_snapshot(user)
        user.approval_status = USER_APPROVAL_APPROVED
        user.approved_at = user.approved_at or moment
        await _audit(db, action=ACTION_USER_APPROVED, outcome=OUTCOME_SUCCESS, email=email, user=user,
                     reason="Verified e-mail address: approved at sign-in.", previous_state=before,
                     new_state=user_role_snapshot(user), metadata={"sign_in_method": "EMAIL_CODE"})
    await _audit(db, action=ACTION_EMAIL_SIGN_IN_SUCCEEDED, outcome=OUTCOME_SUCCESS, email=email, user=user,
                 reason="Signed in with an e-mail code.",
                 metadata={"challenge_id": str(challenge.id), "new_account": new_account, "masked": mask_email(email)})
    return VerifiedSignIn(user=user, new_account=new_account)
