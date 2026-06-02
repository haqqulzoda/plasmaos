"""
Plasma AI - Users Endpoints

Protected endpoints for user operations.
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.all_models import User, SubscriptionTier

router = APIRouter()


# =============================================================================
# Pydantic Schemas
# =============================================================================

class UserResponse(BaseModel):
    """Response schema for user details."""
    id: UUID
    google_id: str
    email: str
    name: str
    avatar_url: str | None
    subscription_tier: SubscriptionTier
    is_admin: bool
    
    model_config = {"from_attributes": True}


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """
    Get current authenticated user's information.
    
    Requires valid JWT token in Authorization header.
    
    Returns:
        User details including subscription tier and admin status.
    """
    return UserResponse.model_validate(current_user)


@router.post("/admin/upgrade-me", response_model=UserResponse)
async def upgrade_to_agent(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    [DEV ONLY] Upgrade current user to Agent tier for testing.
    
    This is a development shortcut to test Pro features without payment.
    """
    current_user.subscription_tier = SubscriptionTier.AGENT
    await db.commit()
    await db.refresh(current_user)
    
    return UserResponse.model_validate(current_user)


# =============================================================================
# Company Profile Schemas & Endpoints
# =============================================================================

class CompanyProfileResponse(BaseModel):
    """Response schema for company profile."""
    company_name: str | None
    director_name: str | None
    address: str | None
    phone_contact: str | None
    bank_name: str | None
    mfo: str | None
    account_number: str | None
    inn: str | None
    
    model_config = {"from_attributes": True}


class CompanyProfileUpdate(BaseModel):
    """Request schema for updating company profile."""
    company_name: str | None = None
    director_name: str | None = None
    address: str | None = None
    phone_contact: str | None = None
    bank_name: str | None = None
    mfo: str | None = None
    account_number: str | None = None
    inn: str | None = None


@router.get("/me/company", response_model=CompanyProfileResponse)
async def get_company_profile(
    current_user: User = Depends(get_current_user),
) -> CompanyProfileResponse:
    """
    Get current user's company profile details.
    
    Returns company name, director, address, and banking details
    for use in Commercial Proposal PDFs.
    """
    return CompanyProfileResponse(
        company_name=current_user.company_name,
        director_name=current_user.director_name,
        address=current_user.address,
        phone_contact=current_user.phone_contact,
        bank_name=current_user.bank_name,
        mfo=current_user.mfo,
        account_number=current_user.account_number,
        inn=current_user.inn,
    )


@router.put("/me/company", response_model=CompanyProfileResponse)
async def update_company_profile(
    profile_data: CompanyProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompanyProfileResponse:
    """
    Update current user's company profile details.
    
    Only updates fields that are provided (not None).
    """
    if profile_data.company_name is not None:
        current_user.company_name = profile_data.company_name
    if profile_data.director_name is not None:
        current_user.director_name = profile_data.director_name
    if profile_data.address is not None:
        current_user.address = profile_data.address
    if profile_data.phone_contact is not None:
        current_user.phone_contact = profile_data.phone_contact
    if profile_data.bank_name is not None:
        current_user.bank_name = profile_data.bank_name
    if profile_data.mfo is not None:
        current_user.mfo = profile_data.mfo
    if profile_data.account_number is not None:
        current_user.account_number = profile_data.account_number
    if profile_data.inn is not None:
        current_user.inn = profile_data.inn
    
    await db.commit()
    await db.refresh(current_user)
    
    return CompanyProfileResponse(
        company_name=current_user.company_name,
        director_name=current_user.director_name,
        address=current_user.address,
        phone_contact=current_user.phone_contact,
        bank_name=current_user.bank_name,
        mfo=current_user.mfo,
        account_number=current_user.account_number,
        inn=current_user.inn,
    )

