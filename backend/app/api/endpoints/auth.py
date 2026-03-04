"""
Plasma AI - Authentication Endpoints

Google OAuth bridge endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, get_current_user
from app.db.session import get_db
from app.models.all_models import User

router = APIRouter()


class GoogleAuthRequest(BaseModel):
    google_id: str
    email: str
    name: str
    avatar_url: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str

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
        )
        db.add(user)
    else:
        user.google_id = google_id
        user.email = email
        user.name = name
        user.avatar_url = avatar_url

    await db.commit()
    await db.refresh(user)

    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "google_id": user.google_id,
            "email": user.email,
            "name": user.name,
            "is_admin": user.is_admin,
            "tier": user.subscription_tier.value,
        }
    )

    response.set_cookie(
        key="plasma_api_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 8,
        path="/",
    )

    return TokenResponse(access_token=access_token, token_type="bearer")


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie("plasma_api_token", path="/")
    return {"status": "ok"}


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    response: Response,
    current_user: User = Depends(get_current_user),
) -> TokenResponse:
    """
    Issue a fresh backend JWT for the authenticated user.

    Accepts the current token via Bearer header or ``plasma_api_token``
    cookie — whichever ``get_current_user`` resolves.  Returns a new
    token with a full 8-hour lifetime and refreshes the cookie.
    """
    access_token = create_access_token(
        data={
            "sub": str(current_user.id),
            "google_id": current_user.google_id,
            "email": current_user.email,
            "name": current_user.name,
            "is_admin": current_user.is_admin,
            "tier": current_user.subscription_tier.value,
        }
    )

    response.set_cookie(
        key="plasma_api_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 8,
        path="/",
    )

    return TokenResponse(access_token=access_token, token_type="bearer")

