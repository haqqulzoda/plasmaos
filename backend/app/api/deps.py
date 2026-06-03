"""
Plasma AI - API Dependencies

Common dependencies for FastAPI endpoints including authentication and tier gating.
"""

import os
from typing import Callable

from fastapi import Depends, HTTPException, status

from app.core.security import get_current_user as core_get_current_user
from app.models.all_models import SubscriptionTier, User

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


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Require an authenticated administrator.

    This intentionally stays small: the pilot P0 need is to block dev/operator
    routes from normal customer accounts, not to introduce a full RBAC system.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    return current_user


def _operator_email_allowlist() -> set[str]:
    """
    Return the temporary founder/operator allowlist from environment.
    """
    raw_emails = os.getenv("PLASMA_OPERATOR_EMAILS", "")
    return {
        email.strip().lower()
        for email in raw_emails.split(",")
        if email.strip()
    }


def is_operator_or_admin(current_user: User) -> bool:
    """
    Allow admins and explicitly allowlisted founder/operator emails.

    This is a narrow pilot-demo bridge, not a replacement for full RBAC.
    """
    if current_user.is_admin:
        return True

    if bool(getattr(current_user, "is_operator", False)):
        return True

    if bool(getattr(current_user, "is_founder", False)):
        return True

    user_email = (current_user.email or "").strip().lower()
    return user_email in _operator_email_allowlist()


async def require_operator_or_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Require an authenticated administrator or configured operator.
    """
    if not is_operator_or_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator access required",
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
