"""
Plasma AI - Authentication Endpoints

Google OAuth bridge endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
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
    create_access_token,
    get_current_user,
)
from app.db.session import get_db
from app.models.all_models import User
from app.models.company import CompanyProfile
from app.services.admin_activity import (
    ACTION_ADMIN_GRANTED,
    ACTION_ALLOWLIST_PRIVILEGE_RECONCILED,
    ACTION_OPERATOR_GRANTED,
    ACTOR_SYSTEM,
    OUTCOME_SUCCESS,
    SOURCE_GOOGLE_ALLOWLIST,
    bump_auth_version,
    record_admin_audit_event,
    user_role_snapshot,
)

router = APIRouter()


class GoogleAuthRequest(BaseModel):
    google_id: str
    email: str
    name: str
    avatar_url: str | None = None


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
    if not user.approval_status:
        user.approval_status = USER_APPROVAL_PENDING


def _role_state_changed(before: dict, user: User) -> bool:
    after = user_role_snapshot(user)
    return any(before.get(key) != after.get(key) for key in ("platform_role", "approval_status", "is_admin"))


async def _load_company_profile(
    *,
    db: AsyncSession,
    user_id,
) -> CompanyProfile | None:
    result = await db.execute(
        select(CompanyProfile).where(CompanyProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


def _token_payload(user: User, profile: CompanyProfile | None) -> dict:
    onboarding_required = profile is None
    company_profile_id = str(profile.id) if profile is not None else None
    company_approval_status = profile.approval_status if profile is not None else None
    company_pilot_status = profile.pilot_status if profile is not None else None
    return {
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


def _token_response(*, access_token: str, user: User, profile: CompanyProfile | None) -> TokenResponse:
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
    )

@router.post("/google", response_model=TokenResponse)
async def google_auth_bridge(
    payload: GoogleAuthRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    email = payload.email.strip().lower()
    google_id = payload.google_id.strip()
    name = payload.name.strip() or email
    avatar_url = payload.avatar_url

    result = await db.execute(
        select(User).where(or_(User.google_id == google_id, User.email == email))
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            google_id=google_id,
            email=email,
            name=name,
            avatar_url=avatar_url,
            platform_role=PLATFORM_ROLE_PILOT_USER,
            approval_status=USER_APPROVAL_PENDING,
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
    if _role_state_changed(before_role_state, user):
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

    await db.commit()
    await db.refresh(user)
    profile = await _load_company_profile(db=db, user_id=user.id)

    access_token = create_access_token(data=_token_payload(user, profile))

    response.set_cookie(
        key="plasma_api_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 8,
        path="/",
    )

    return _token_response(access_token=access_token, user=user, profile=profile)


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie("plasma_api_token", path="/")
    return {"status": "ok"}


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Issue a fresh backend JWT for the authenticated user.

    Accepts the current token via Bearer header or ``plasma_api_token``
    cookie — whichever ``get_current_user`` resolves.  Returns a new
    token with a full 8-hour lifetime and refreshes the cookie.
    """
    # Defense in depth: token issuance must never revive a blocked account.
    if is_disabled_account(current_user) or is_rejected_account(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account unavailable",
        )

    profile = await _load_company_profile(db=db, user_id=current_user.id)
    access_token = create_access_token(data=_token_payload(current_user, profile))

    response.set_cookie(
        key="plasma_api_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 8,
        path="/",
    )

    return _token_response(access_token=access_token, user=current_user, profile=profile)
