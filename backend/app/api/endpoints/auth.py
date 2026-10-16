"""
Plasma AI - Authentication Endpoints

Google OAuth bridge, e-mail one-time-code sign-in (P1) and rotating sessions (P1).
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import admin_email_allowlist, is_admin_user, operator_email_allowlist
from app.core.access import (
    PLATFORM_ROLE_ADMIN,
    PLATFORM_ROLE_OPERATOR,
    PLATFORM_ROLE_PILOT_USER,
    USER_APPROVAL_APPROVED,
    USER_APPROVAL_PENDING,
    USER_APPROVAL_REJECTED,
    is_disabled_account,
    is_rejected_account,
)
from app.core.security import (
    bearer_scheme,
    create_access_token,
    decode_access_token,
    get_current_user,
)
from app.core.auth_bridge import verify_bridge_assertion, verify_email_code_assertion
from app.db.session import get_db
from app.models.all_models import User
from app.models.company import CompanyProfile
from app.services import auth_sessions, email_sign_in
from app.services.admin_alerts import kick_admin_alerts, stage_new_signup
from app.services.email_sign_in import PREPROVISIONED_GOOGLE_ID_PREFIX
from app.services.invitations import accept_open_invitations_for_sign_in
from app.services.organization_context import effective_company_profile
from app.services.admin_activity import (
    ACTION_ADMIN_GRANTED,
    ACTION_ALLOWLIST_PRIVILEGE_RECONCILED,
    ACTION_OPERATOR_GRANTED,
    ACTION_USER_APPROVED,
    ACTOR_SYSTEM,
    OUTCOME_SUCCESS,
    SOURCE_GOOGLE_ALLOWLIST,
    bump_auth_version,
    record_admin_audit_event,
    user_role_snapshot,
)

logger = logging.getLogger(__name__)

router = APIRouter()

API_COOKIE_MAX_AGE = 60 * 60 * 8


class GoogleAuthRequest(BaseModel):
    bridge_assertion: str | None = None
    google_id: str
    email: str
    name: str
    avatar_url: str | None = None


class EmailCodeRequest(BaseModel):
    email: str = Field(max_length=320)


class EmailCodeRequestAccepted(BaseModel):
    """The same answer whether or not the address has an account."""

    status: str = "accepted"
    expires_in_seconds: int
    resend_after_seconds: int


class EmailCodeVerifyRequest(BaseModel):
    bridge_assertion: str
    email: str = Field(max_length=320)
    code: str = Field(max_length=32)


class SessionRotateRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    platform_role: str
    approval_status: str
    is_admin: bool
    onboarding_required: bool
    company_profile_id: UUID | None = None
    company_approval_status: str | None = None
    company_pilot_status: str | None = None
    # P1: present on sign-in and rotation only; never on the bearer re-issue (/auth/refresh).
    refresh_token: str | None = None
    refresh_expires_at: datetime | None = None


def _apply_email_bootstrap(user: User, *, email: str) -> None:
    # Allowlist membership may bootstrap eligible users, but it must never
    # reverse an explicit administrative disable.
    if is_disabled_account(user) or user.approval_status == USER_APPROVAL_REJECTED:
        return

    now = datetime.now(timezone.utc)
    if user.is_admin or email in admin_email_allowlist():
        user.platform_role = PLATFORM_ROLE_ADMIN
        user.approval_status = USER_APPROVAL_APPROVED
        user.is_admin = True
        user.approved_at = user.approved_at or now
        return

    if email in operator_email_allowlist():
        user.platform_role = PLATFORM_ROLE_OPERATOR
        user.approval_status = USER_APPROVAL_APPROVED
        user.approved_at = user.approved_at or now
        return

    if not user.platform_role:
        user.platform_role = PLATFORM_ROLE_PILOT_USER
    # P1: a verified e-mail approves the account; the organization gate stays.
    if not user.approval_status or user.approval_status == USER_APPROVAL_PENDING:
        user.approval_status = USER_APPROVAL_APPROVED
        user.approved_at = user.approved_at or now


def _bound_google_id(user: User) -> str | None:
    value = user.google_id or None
    return None if value and value.startswith(PREPROVISIONED_GOOGLE_ID_PREFIX) else value


def _role_state_changed(before: dict, user: User) -> bool:
    after = user_role_snapshot(user)
    return any(before.get(key) != after.get(key) for key in ("platform_role", "approval_status", "is_admin"))


async def _load_company_profile(
    *,
    db: AsyncSession,
    user_id,
) -> CompanyProfile | None:
    # Own profile, else the organization joined by invitation: onboarding is skipped.
    return await effective_company_profile(db, user_id=user_id)


def _token_payload(user: User, profile: CompanyProfile | None, *, family_id: UUID | None = None) -> dict:
    onboarding_required = profile is None
    company_profile_id = str(profile.id) if profile is not None else None
    company_approval_status = profile.approval_status if profile is not None else None
    company_pilot_status = profile.pilot_status if profile is not None else None
    payload = {
        "sub": str(user.id),
        "google_id": user.google_id,
        "email": user.email,
        "name": user.name,
        "is_admin": is_admin_user(user),
        "tier": user.subscription_tier.value,
        "platform_role": user.platform_role,
        "approval_status": user.approval_status,
        "auth_version": getattr(user, "auth_version", 0),
        "onboarding_required": onboarding_required,
        "company_profile_id": company_profile_id,
        "company_approval_status": company_approval_status,
        "company_pilot_status": company_pilot_status,
    }
    if family_id is not None:
        payload["sid"] = str(family_id)  # the refresh-token family: logout ends it
    return payload


def _token_response(
    *, access_token: str, user: User, profile: CompanyProfile | None,
    refresh: auth_sessions.IssuedRefreshToken | None = None,
) -> TokenResponse:
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        platform_role=user.platform_role,
        approval_status=user.approval_status,
        is_admin=is_admin_user(user),
        onboarding_required=profile is None,
        company_profile_id=profile.id if profile is not None else None,
        company_approval_status=profile.approval_status if profile is not None else None,
        company_pilot_status=profile.pilot_status if profile is not None else None,
        refresh_token=refresh.token if refresh is not None else None,
        refresh_expires_at=refresh.expires_at if refresh is not None else None,
    )


def _set_api_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        key="plasma_api_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=API_COOKIE_MAX_AGE,
        path="/",
    )


async def _stage_sign_in(db: AsyncSession, *, user: User, new_account: bool, method: str = "GOOGLE") -> None:
    """Sprint 1 analytics: the sign-in, in the default organization context when there is one."""
    from app.services.organization_context import organization_profile_context
    from app.services.product_analytics import stage_product_event

    try:
        context = await organization_profile_context(db, user_id=user.id)
    except Exception:  # no usable organization context: the event still counts the person
        context = None
    stage_product_event(
        db, "sign_in", organization_id=context.organization.id if context else None, actor_user_id=user.id,
        actor_membership_id=context.membership.id if context else None,
        properties={"new_account": new_account, "approval_status": user.approval_status, "method": method},
    )


def _client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/google", response_model=TokenResponse)
async def google_auth_bridge(
    payload: GoogleAuthRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    identity = await verify_bridge_assertion(payload)
    email = identity["email"].strip().lower()
    google_id = identity["sub"]
    name = identity["name"].strip() or email
    avatar_url = identity.get("avatar_url")

    result = await db.execute(
        select(User).where(or_(User.google_id == google_id, User.email == email))
    )
    matches = result.scalars().all()
    if len(matches) > 1:
        raise HTTPException(409, detail="Account identity conflict")
    user = matches[0] if matches else None
    new_account = user is None
    if user is not None and _bound_google_id(user) and user.google_id != google_id:
        raise HTTPException(409, detail="Account identity conflict")

    if user is None:
        user = User(
            google_id=google_id,
            email=email,
            name=name,
            avatar_url=avatar_url,
            platform_role=PLATFORM_ROLE_PILOT_USER,
            # P1: Google proves the address (email_verified is required by the bridge).
            approval_status=USER_APPROVAL_APPROVED,
            approved_at=datetime.now(timezone.utc),
        )
        db.add(user)
    else:
        if is_disabled_account(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account disabled",
            )
        if is_rejected_account(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account rejected",
            )
        user.google_id = google_id
        user.email = email
        user.name = name
        user.avatar_url = avatar_url
    before_role_state = user_role_snapshot(user)
    _apply_email_bootstrap(user, email=email)
    if new_account or _role_state_changed(before_role_state, user):
        await db.flush()
    if _role_state_changed(before_role_state, user) and user.platform_role in {PLATFORM_ROLE_ADMIN, PLATFORM_ROLE_OPERATOR}:
        bump_auth_version(user)
        await db.flush()
        audit_action = ACTION_ALLOWLIST_PRIVILEGE_RECONCILED
        if user.platform_role == PLATFORM_ROLE_ADMIN:
            audit_action = ACTION_ADMIN_GRANTED
        elif user.platform_role == PLATFORM_ROLE_OPERATOR:
            audit_action = ACTION_OPERATOR_GRANTED
        await record_admin_audit_event(
            db,
            action=audit_action,
            outcome=OUTCOME_SUCCESS,
            source=SOURCE_GOOGLE_ALLOWLIST,
            target_user=user,
            actor_type=ACTOR_SYSTEM,
            actor_label="auth/google",
            reason="Successful Google authentication matched configured role allowlist.",
            previous_state=before_role_state,
            new_state=user_role_snapshot(user, credentials_invalidated=True),
            metadata={
                "admin_allowlist_match": email in admin_email_allowlist(),
                "operator_allowlist_match": email in operator_email_allowlist(),
            },
        )
    elif new_account or _role_state_changed(before_role_state, user):
        # A pending account (before P1) or a new one: approved because Google verified the address.
        await record_admin_audit_event(
            db,
            action=ACTION_USER_APPROVED,
            outcome=OUTCOME_SUCCESS,
            source=SOURCE_GOOGLE_ALLOWLIST,
            target_user=user,
            actor_type=ACTOR_SYSTEM,
            actor_label="auth/google",
            reason="Verified e-mail address: approved at sign-up." if new_account
            else "Verified e-mail address: approved at sign-in.",
            previous_state=None if new_account else before_role_state,
            new_state=user_role_snapshot(user),
            metadata={"sign_in_method": "GOOGLE"},
        )

    # R3: an open invitation for exactly this verified e-mail binds now (never by domain).
    await db.flush()
    joined = await accept_open_invitations_for_sign_in(db, user=user, verified_email=email)
    await _stage_sign_in(db, user=user, new_account=new_account)
    alerted = new_account and not joined and await stage_new_signup(
        db, user_id=user.id, email=email, name=name, method=auth_sessions.METHOD_GOOGLE,
    )
    token = await _issue_signed_in(db, response, user=user, method=auth_sessions.METHOD_GOOGLE)
    if alerted:
        kick_admin_alerts()
    return token


async def _issue_signed_in(
    db: AsyncSession, response: Response, *, user: User, method: str,
) -> TokenResponse:
    """Start a refresh family, commit, and return the access token for a completed sign-in."""
    refresh = await auth_sessions.start_family(db, user=user, method=method)
    await db.commit()
    await db.refresh(user)
    profile = await _load_company_profile(db=db, user_id=user.id)
    access_token = create_access_token(data=_token_payload(user, profile, family_id=refresh.family_id))
    _set_api_cookie(response, access_token)
    return _token_response(access_token=access_token, user=user, profile=profile, refresh=refresh)


# ---- P1: e-mail one-time code ----------------------------------------------------------------------

def _email_sign_in_http_error(exc: email_sign_in.EmailSignInError) -> HTTPException:
    if isinstance(exc, email_sign_in.RateLimitedError):
        return HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail={"code": exc.code},
            headers={"Retry-After": str(exc.retry_after)},
        )
    if isinstance(exc, email_sign_in.AccountUnavailableError):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": exc.code})
    if isinstance(exc, email_sign_in.InvalidEmailError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": exc.code})
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": exc.code})


def _kick_email_sender() -> None:
    """Send now instead of at the next 30-second Beat tick; Beat stays the fallback."""
    try:
        from app.core.celery_app import celery_app

        celery_app.send_task("app.workers.communications_tasks.send_emails")
    except Exception as exc:  # noqa: BLE001 - delivery still happens on the next Beat tick
        logger.warning("email_sign_in_kick_failed error_type=%s", type(exc).__name__)


@router.post("/email/request-code", response_model=EmailCodeRequestAccepted, status_code=status.HTTP_202_ACCEPTED)
async def request_email_code(
    payload: EmailCodeRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> EmailCodeRequestAccepted:
    """Send a 6-digit sign-in code. The answer never depends on whether the account exists."""
    response.headers["Cache-Control"] = "no-store"
    try:
        result, _code = await email_sign_in.request_code(db, raw_email=payload.email, client=_client_address(request))
    except email_sign_in.EmailSignInError as exc:
        await db.rollback()
        raise _email_sign_in_http_error(exc) from None
    await db.commit()
    if result.delivery == email_sign_in.DELIVERY_STAGED:
        _kick_email_sender()
    return EmailCodeRequestAccepted(
        expires_in_seconds=int(email_sign_in.CODE_TTL.total_seconds()),
        resend_after_seconds=email_sign_in.REQUEST_EMAIL_LIMITS[0][2],
    )


@router.post("/email/verify-code", response_model=TokenResponse)
async def verify_email_code(
    payload: EmailCodeVerifyRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Called by the Auth.js server only (signed, single-use bridge assertion)."""
    response.headers["Cache-Control"] = "no-store"
    claims = await verify_email_code_assertion(payload.bridge_assertion, email=payload.email)
    try:
        verified = await email_sign_in.verify_code(
            db, raw_email=payload.email, raw_code=payload.code, client=claims.get("client_ip"),
        )
    except email_sign_in.EmailSignInError as exc:
        # Wrong attempts, locks and the audit trail persist even though the sign-in fails.
        await db.commit()
        raise _email_sign_in_http_error(exc) from None
    user = verified.user
    await db.flush()
    joined = await accept_open_invitations_for_sign_in(
        db, user=user, verified_email=user.email, actor_label="auth/email-code",
    )
    await _stage_sign_in(db, user=user, new_account=verified.new_account, method="EMAIL_CODE")
    # P1: every new self sign-up (not one who joined by invitation) alerts the Plasma team.
    alerted = verified.new_account and not joined and await stage_new_signup(
        db, user_id=user.id, email=user.email, name=user.name, method=auth_sessions.METHOD_EMAIL_CODE,
    )
    token = await _issue_signed_in(db, response, user=user, method=auth_sessions.METHOD_EMAIL_CODE)
    if alerted:
        kick_admin_alerts()
    return token


# ---- sessions --------------------------------------------------------------------------------------

def _presented_claims(
    credentials: HTTPAuthorizationCredentials | None, plasma_api_token: str | None,
) -> dict:
    token = credentials.credentials if credentials else plasma_api_token
    return (decode_access_token(token) if token else None) or {}


def _family_id(claims: dict) -> UUID | None:
    try:
        return UUID(str(claims["sid"]))
    except (KeyError, TypeError, ValueError):
        return None


@router.post("/session/rotate", response_model=TokenResponse)
async def rotate_session(
    payload: SessionRotateRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a refresh token for a new access token and a new refresh token."""
    response.headers["Cache-Control"] = "no-store"
    from app.core import rate_limit

    retry_after = await rate_limit.hit("session_rotate_ip", _client_address(request), limit=600, window_seconds=600)
    if retry_after is not None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests",
                            headers={"Retry-After": str(retry_after)})
    try:
        user, refresh = await auth_sessions.rotate(db, token=payload.refresh_token)
    except auth_sessions.RefreshTokenError:
        await db.commit()  # a reuse revocation and its audit event must persist
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Fresh authentication required") from None
    await db.commit()
    profile = await _load_company_profile(db=db, user_id=user.id)
    access_token = create_access_token(data=_token_payload(user, profile, family_id=refresh.family_id))
    _set_api_cookie(response, access_token)
    return _token_response(access_token=access_token, user=user, profile=profile, refresh=refresh)


@router.post("/logout")
async def logout(
    response: Response,
    db: AsyncSession = Depends(get_db),
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    plasma_api_token: Annotated[str | None, Cookie()] = None,
) -> dict[str, str]:
    family_id = _family_id(_presented_claims(credentials, plasma_api_token))
    if family_id is not None:
        await auth_sessions.revoke_family(db, family_id=family_id, reason="LOGOUT")
        await db.commit()
    response.delete_cookie("plasma_api_token", path="/")
    return {"status": "ok"}


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    plasma_api_token: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    """
    Issue a fresh backend JWT for the authenticated user.

    Accepts the current token via Bearer header or ``plasma_api_token``
    cookie — whichever ``get_current_user`` resolves.  Returns a new
    token with a full 8-hour lifetime and refreshes the cookie. The refresh-token
    family (``sid``) carries over; the refresh token itself is not rotated here.
    """
    # Defense in depth: token issuance must never revive a blocked account.
    if is_disabled_account(current_user) or is_rejected_account(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account unavailable",
        )

    profile = await _load_company_profile(db=db, user_id=current_user.id)
    family_id = _family_id(_presented_claims(credentials, plasma_api_token))
    access_token = create_access_token(data=_token_payload(current_user, profile, family_id=family_id))
    _set_api_cookie(response, access_token)

    return _token_response(access_token=access_token, user=current_user, profile=profile)
