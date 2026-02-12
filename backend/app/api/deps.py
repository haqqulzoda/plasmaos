"""
Plasma AI - API Dependencies

Common dependencies for FastAPI endpoints including authentication and tier gating.
"""

from typing import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.all_models import User, SubscriptionTier

# HTTPBearer for simple token input in Swagger UI
security = HTTPBearer()

# Tier hierarchy for comparison
TIER_HIERARCHY = {
    SubscriptionTier.SCOUT: 0,
    SubscriptionTier.AGENT: 1,
    SubscriptionTier.ENTERPRISE: 2,
}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Validate JWT token and return current user.
    
    Args:
        credentials: HTTP Bearer credentials containing the JWT token.
        db: Database session.
        
    Returns:
        User object for the authenticated user.
        
    Raises:
        HTTPException: If token is invalid or user not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # Extract token from credentials
    token = credentials.credentials
    
    # Decode and validate token
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    
    # Extract user ID from token
    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        raise credentials_exception
    
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise credentials_exception
    
    # Fetch user from database
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        raise credentials_exception
    
    return user


def require_tier(required_tier: SubscriptionTier) -> Callable:
    """
    Create a dependency that checks if user has required subscription tier.
    
    Args:
        required_tier: Minimum tier required to access the endpoint.
        
    Returns:
        Dependency function that validates user tier.
    """
    async def check_tier(
        current_user: User = Depends(get_current_user),
    ) -> User:
        user_tier_level = TIER_HIERARCHY.get(current_user.subscription_tier, 0)
        required_tier_level = TIER_HIERARCHY.get(required_tier, 0)
        
        if user_tier_level < required_tier_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Upgrade to Plasma {required_tier.value.capitalize()} to unlock this feature",
            )
        
        return current_user
    
    return check_tier
