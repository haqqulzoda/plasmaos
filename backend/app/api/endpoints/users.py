"""
Plasma AI - Users Endpoints

Protected endpoints for user operations.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_approved_pilot_access
from app.core.access import (
    COMPANY_APPROVAL_APPROVED,
    COMPANY_APPROVAL_PENDING,
    COMPANY_PILOT_SCOPED,
)
from app.core.geography import normalize_target_countries, normalize_target_regions
from app.core.services import normalize_target_services
from app.db.session import get_db
from app.models.all_models import User, SubscriptionTier
from app.models.company import CompanyProfile

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
    approval_status: str
    platform_role: str
    
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
    company_profile_id: UUID | None = None
    onboarding_required: bool = False
    company_name: str | None
    director_name: str | None
    address: str | None
    phone_contact: str | None
    bank_name: str | None
    mfo: str | None
    account_number: str | None
    inn: str | None
    industry: str | None = None
    website: str | None = None
    target_regions: list[str] | None = None
    target_countries: list[str] | None = None
    target_services: list[str] | None = None
    notes: str | None = None
    pilot_status: str | None = None
    approval_status: str | None = None
    
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
    industry: str | None = None
    website: str | None = None
    target_regions: list[str] | None = None
    target_countries: list[str] | None = None
    target_services: list[str] | None = None
    notes: str | None = None

    @field_validator(
        "company_name",
        "director_name",
        "address",
        "phone_contact",
        "bank_name",
        "mfo",
        "account_number",
        "inn",
        "industry",
        "website",
        "notes",
        mode="before",
    )
    @classmethod
    def _strip_optional_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("target_regions", "target_countries", "target_services")
    @classmethod
    def _normalize_optional_lists(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_values(value)

    @field_validator("target_regions")
    @classmethod
    def _validate_target_regions(cls, value: list[str] | None) -> list[str] | None:
        return normalize_target_regions(value)

    @field_validator("target_countries")
    @classmethod
    def _validate_target_countries(cls, value: list[str] | None) -> list[str] | None:
        return normalize_target_countries(value)

    @field_validator("target_services")
    @classmethod
    def _validate_target_services(cls, value: list[str] | None) -> list[str] | None:
        return normalize_target_services(value)


class CompanyOnboardingRequest(BaseModel):
    """Request schema for intentional company onboarding submission."""
    company_name: str = Field(min_length=1, max_length=255)
    industry: str = Field(min_length=1, max_length=255)
    target_regions: list[str] = Field(min_length=1)
    target_countries: list[str] = Field(min_length=1)
    target_services: list[str] = Field(min_length=1)
    director_name: str = Field(min_length=1, max_length=255)
    phone_contact: str = Field(min_length=1, max_length=50)
    inn: str = Field(min_length=1, max_length=15)
    website: str | None = Field(default=None, max_length=500)
    address: str | None = None
    bank_name: str | None = Field(default=None, max_length=255)
    mfo: str | None = Field(default=None, max_length=10)
    account_number: str | None = Field(default=None, max_length=30)
    notes: str | None = None

    @field_validator(
        "company_name",
        "industry",
        "director_name",
        "phone_contact",
        "inn",
        "website",
        "address",
        "bank_name",
        "mfo",
        "account_number",
        "notes",
        mode="before",
    )
    @classmethod
    def _strip_optional_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("target_regions", "target_countries", "target_services")
    @classmethod
    def _normalize_non_empty_lists(cls, value: list[str]) -> list[str]:
        normalized = _normalize_values(value)
        if not normalized:
            raise ValueError("At least one value is required")
        return normalized

    @field_validator("target_regions")
    @classmethod
    def _validate_target_regions(cls, value: list[str]) -> list[str]:
        return normalize_target_regions(value) or []

    @field_validator("target_countries")
    @classmethod
    def _validate_target_countries(cls, value: list[str]) -> list[str]:
        return normalize_target_countries(value) or []

    @field_validator("target_services")
    @classmethod
    def _validate_target_services(cls, value: list[str]) -> list[str]:
        return normalize_target_services(value) or []


def _normalize_values(values: list[str]) -> list[str]:
    normalized = []
    seen = set()
    for item in values:
        cleaned = item.strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            normalized.append(cleaned)
            seen.add(key)
    return normalized


def _company_profile_response(
    *,
    current_user: User,
    profile: CompanyProfile | None,
) -> CompanyProfileResponse:
    if profile is None:
        return CompanyProfileResponse(
            company_profile_id=None,
            onboarding_required=True,
            company_name=current_user.company_name,
            director_name=current_user.director_name,
            address=current_user.address,
            phone_contact=current_user.phone_contact,
            bank_name=current_user.bank_name,
            mfo=current_user.mfo,
            account_number=current_user.account_number,
            inn=current_user.inn,
        )

    return CompanyProfileResponse(
        company_profile_id=profile.id,
        onboarding_required=False,
        company_name=profile.company_name,
        director_name=profile.director_name,
        address=profile.address,
        phone_contact=profile.phone_contact,
        bank_name=profile.bank_name,
        mfo=profile.mfo,
        account_number=profile.account_number,
        inn=profile.inn,
        industry=profile.industry,
        website=profile.website,
        target_regions=normalize_target_regions(profile.target_regions, reject_invalid=False),
        target_countries=normalize_target_countries(profile.target_countries, reject_invalid=False),
        target_services=normalize_target_services(profile.target_services, reject_invalid=False),
        notes=profile.notes,
        pilot_status=profile.pilot_status,
        approval_status=profile.approval_status,
    )


async def _get_company_profile(
    *,
    db: AsyncSession,
    user_id: UUID,
) -> CompanyProfile | None:
    result = await db.execute(
        select(CompanyProfile).where(CompanyProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


@router.get("/me/company", response_model=CompanyProfileResponse)
async def get_company_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompanyProfileResponse:
    """
    Get current user's company profile details.
    
    Returns company name, director, address, and banking details
    for use in Commercial Proposal PDFs.
    """
    profile = await _get_company_profile(
        db=db,
        user_id=current_user.id,
    )
    return _company_profile_response(current_user=current_user, profile=profile)


@router.put("/me/company", response_model=CompanyProfileResponse)
async def update_company_profile(
    profile_data: CompanyProfileUpdate,
    current_user: User = Depends(require_approved_pilot_access),
    db: AsyncSession = Depends(get_db),
) -> CompanyProfileResponse:
    """
    Update current user's company profile details.
    
    Only updates fields that are provided (not None).
    """
    profile = await _get_company_profile(db=db, user_id=current_user.id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company onboarding required",
        )

    update_data = profile_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(profile, field, value)
    
    await db.commit()
    await db.refresh(profile)
    
    return _company_profile_response(current_user=current_user, profile=profile)


@router.post("/me/company/onboarding", response_model=CompanyProfileResponse)
async def submit_company_onboarding(
    payload: CompanyOnboardingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompanyProfileResponse:
    """Create or update the current user's company profile from onboarding."""
    profile = await _get_company_profile(db=db, user_id=current_user.id)
    is_new_profile = profile is None
    if profile is None:
        profile = CompanyProfile(
            user_id=current_user.id,
            created_by_user_id=current_user.id,
            approval_status=COMPANY_APPROVAL_PENDING,
            pilot_status=COMPANY_PILOT_SCOPED,
        )
        db.add(profile)
    else:
        profile.user_id = current_user.id
        if profile.created_by_user_id is None:
            profile.created_by_user_id = current_user.id

    for field, value in payload.model_dump().items():
        setattr(profile, field, value)

    if is_new_profile or profile.approval_status != COMPANY_APPROVAL_APPROVED:
        profile.approval_status = COMPANY_APPROVAL_PENDING
    if not profile.pilot_status:
        profile.pilot_status = COMPANY_PILOT_SCOPED

    await db.commit()
    await db.refresh(profile)

    return _company_profile_response(current_user=current_user, profile=profile)
