"""
Plasma AI - API Dependencies

Common dependencies for FastAPI endpoints including authentication and tier gating.
"""

from typing import Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import (
    COMPANY_APPROVAL_APPROVED,
    PLATFORM_ROLE_ADMIN,
    PLATFORM_ROLE_OPERATOR,
    USER_APPROVAL_APPROVED,
    configured_email_allowlist,
)
from app.core.security import get_current_user as core_get_current_user
from app.db.session import get_db
from app.models.all_models import SubscriptionTier, User
from app.models.company import CompanyProfile

# Tier hierarchy for comparison
TIER_HIERARCHY = {
    SubscriptionTier.SCOUT: 0,
    SubscriptionTier.AGENT: 1,
    SubscriptionTier.ENTERPRISE: 2,
}


async def get_current_user(
    current_user: User = Depends(core_get_current_user),
) -> User:
    """
    Backward-compatible wrapper around core security dependency.
    """
    return current_user


def admin_email_allowlist() -> set[str]:
    """Return configured bootstrap administrator emails."""
    return configured_email_allowlist("PLASMA_ADMIN_EMAILS")


def operator_email_allowlist() -> set[str]:
    """Return configured operator emails."""
    return configured_email_allowlist("PLASMA_OPERATOR_EMAILS")


def _operator_email_allowlist() -> set[str]:
    """Backward-compatible alias for older tests/imports."""
    return operator_email_allowlist()


def _normalized_email(user: User) -> str:
    return (user.email or "").strip().lower()


def is_admin_user(user: User) -> bool:
    """Return whether a user has platform administrator access."""
    return bool(user.is_admin) or user.platform_role == PLATFORM_ROLE_ADMIN


def is_operator_user(user: User) -> bool:
    """Return whether a user has operator-level platform access."""
    if is_admin_user(user):
        return True
    if user.platform_role == PLATFORM_ROLE_OPERATOR:
        return True
    return _normalized_email(user) in operator_email_allowlist()


def is_operator_or_admin(current_user: User) -> bool:
    """Backward-compatible alias for existing tender access checks."""
    return is_operator_user(current_user)


def is_approved_user(user: User) -> bool:
    """Return whether a user has passed account approval."""
    if is_operator_user(user):
        return True
    return user.approval_status == USER_APPROVAL_APPROVED


def has_approved_pilot_account_access(user: User, company_profile: object | None) -> bool:
    """
    Return whether a pilot account has both user and company approval.

    S1.1 does not enforce this on tender APIs yet; S1.2/S1.3 can use this
    helper when onboarding and approval gates become active.
    """
    if is_operator_user(user):
        return True
    if not is_approved_user(user) or company_profile is None:
        return False
    return getattr(company_profile, "approval_status", None) == COMPANY_APPROVAL_APPROVED


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require an authenticated administrator."""
    if not is_admin_user(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    return current_user


async def require_operator(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require an authenticated operator or administrator."""
    if not is_operator_user(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator access required",
        )

    return current_user


async def require_operator_or_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Backward-compatible dependency name for existing routes."""
    return await require_operator(current_user)


async def require_approved_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require an approved user, operator, or administrator."""
    if not is_approved_user(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User approval required",
        )

    return current_user


async def require_approved_pilot_access(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Require approved user + approved company, with admin/operator bypass."""
    if is_operator_user(current_user):
        return current_user

    result = await db.execute(
        select(CompanyProfile).where(CompanyProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()

    if not has_approved_pilot_account_access(current_user, profile):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approved pilot access required",
        )

    return current_user


def require_tier(required_tier: SubscriptionTier) -> Callable:
    """
    Validate user subscription tier against required endpoint tier.
    """
    async def check_tier(
        current_user: User = Depends(get_current_user),
    ) -> User:
        current_level = TIER_HIERARCHY[current_user.subscription_tier]
        required_level = TIER_HIERARCHY[required_tier]

        if current_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This endpoint requires {required_tier.value} tier "
                    f"(current: {current_user.subscription_tier.value})"
                ),
            )

        return current_user

    return check_tier
