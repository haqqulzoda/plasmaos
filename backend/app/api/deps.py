"""
Plasma AI - API Dependencies

Common dependencies for FastAPI endpoints including authentication and tier gating.
"""

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
