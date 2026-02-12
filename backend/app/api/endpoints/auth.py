"""
Plasma AI - Traffic Light Authentication Endpoints

No-password authentication flow:
1. Frontend calls /init with a 4-digit code
2. User types code in Telegram Bot
3. Bot verifies and updates session status
4. Frontend polls /verify to get JWT token
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db.session import get_db
from app.models.all_models import AuthSession, AuthSessionStatus, User

router = APIRouter()


# =============================================================================
# Pydantic Schemas
# =============================================================================

class AuthInitRequest(BaseModel):
    """Request body for initializing auth session."""
    code: str = Field(..., min_length=4, max_length=4, pattern=r"^\d{4}$")
    ip: str = Field(..., examples=["127.0.0.1"])


class AuthInitResponse(BaseModel):
    """Response for auth initialization."""
    code: str
    status: str
    expires_at: datetime


class AuthVerifyRequest(BaseModel):
    """Request body for verifying auth session."""
    code: str = Field(..., min_length=4, max_length=4, pattern=r"^\d{4}$")


class AuthVerifyResponse(BaseModel):
    """Response for auth verification."""
    status: str
    token: str | None = None
    user_id: str | None = None


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/init", response_model=AuthInitResponse)
async def init_auth_session(
    request: AuthInitRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthInitResponse:
    """
    Initialize a new Traffic Light auth session.
    
    Creates a PENDING session with the provided 4-digit code.
    If code already exists, updates the existing session.
    """
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    
    # Check if code already exists
    result = await db.execute(
        select(AuthSession).where(AuthSession.code == request.code)
    )
    existing_session = result.scalar_one_or_none()
    
    if existing_session:
        # Update existing session
        existing_session.ip_address = request.ip
        existing_session.status = AuthSessionStatus.PENDING
        existing_session.expires_at = expires_at
        existing_session.user_id = None
    else:
        # Create new session
        new_session = AuthSession(
            code=request.code,
            ip_address=request.ip,
            status=AuthSessionStatus.PENDING,
            expires_at=expires_at,
        )
        db.add(new_session)
    
    await db.commit()
    
    return AuthInitResponse(
        code=request.code,
        status="pending",
        expires_at=expires_at,
    )


@router.post("/verify", response_model=AuthVerifyResponse)
async def verify_auth_session(
    request: AuthVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthVerifyResponse:
    """
    Check the status of an auth session.
    
    If VERIFIED: Returns JWT token for the authenticated user.
    If PENDING: Returns pending status (frontend should poll again).
    If expired or not found: Returns error.
    """
    result = await db.execute(
        select(AuthSession).where(AuthSession.code == request.code)
    )
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Auth session not found",
        )
    
    # Check if expired
    if session.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Auth session expired",
        )
    
    # Check status
    if session.status == AuthSessionStatus.PENDING:
        return AuthVerifyResponse(status="pending")
    
    if session.status == AuthSessionStatus.VERIFIED:
        # Session is verified, generate token
        if not session.user_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Session verified but no user linked",
            )
        
        # Fetch user details
        user_result = await db.execute(
            select(User).where(User.id == session.user_id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        
        # Generate JWT token
        token = create_access_token(
            data={
                "sub": str(user.id),
                "telegram_id": user.telegram_id,
                "tier": user.subscription_tier.value,
                "is_admin": user.is_admin,
            }
        )
        
        # Clean up used session
        await db.delete(session)
        await db.commit()
        
        return AuthVerifyResponse(
            status="verified",
            token=token,
            user_id=str(user.id),
        )
    
    # Unknown status
    return AuthVerifyResponse(status="unknown")
