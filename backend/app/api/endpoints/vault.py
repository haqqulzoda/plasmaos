from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.all_models import User
from app.models.company import Certification, CompanyProfile, FinancialHistory, License
from app.schemas.vault import (
    CertificationItem,
    CompanyVaultResponse,
    CompanyVaultUpdate,
    FinancialHistoryItem,
    LicenseItem,
)

router = APIRouter()


async def _get_or_create_profile(db: AsyncSession, user_id) -> CompanyProfile:
    result = await db.execute(
        select(CompanyProfile).where(CompanyProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = CompanyProfile(user_id=user_id)
        db.add(profile)
        await db.flush()

    return profile


async def _load_profile_with_children(
    db: AsyncSession,
    user_id,
) -> CompanyProfile:
    result = await db.execute(
        select(CompanyProfile)
        .options(
            selectinload(CompanyProfile.certifications),
            selectinload(CompanyProfile.licenses),
            selectinload(CompanyProfile.financial_history),
        )
        .where(CompanyProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if profile is not None:
        return profile

    profile = CompanyProfile(user_id=user_id)
    db.add(profile)
    await db.commit()

    refreshed = await db.execute(
        select(CompanyProfile)
        .options(
            selectinload(CompanyProfile.certifications),
            selectinload(CompanyProfile.licenses),
            selectinload(CompanyProfile.financial_history),
        )
        .where(CompanyProfile.user_id == user_id)
    )
    return refreshed.scalar_one()


def _to_response(profile: CompanyProfile) -> CompanyVaultResponse:
    certifications = [
        CertificationItem.model_validate(item)
        for item in sorted(
            profile.certifications,
            key=lambda x: (x.issue_date, x.expiry_date, x.cert_type),
        )
    ]
    licenses = [
        LicenseItem.model_validate(item)
        for item in sorted(
            profile.licenses,
            key=lambda x: x.license_name.lower(),
        )
    ]
    financial_history = [
        FinancialHistoryItem.model_validate(item)
        for item in sorted(
            profile.financial_history,
            key=lambda x: x.year,
        )
    ]

    return CompanyVaultResponse(
        id=profile.id,
        user_id=profile.user_id,
        company_name=profile.company_name,
        director_name=profile.director_name,
        address=profile.address,
        phone_contact=profile.phone_contact,
        bank_name=profile.bank_name,
        mfo=profile.mfo,
        account_number=profile.account_number,
        inn=profile.inn,
        certifications=certifications,
        licenses=licenses,
        financial_history=financial_history,
    )


@router.get("/vault", response_model=CompanyVaultResponse)
async def get_company_vault(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompanyVaultResponse:
    profile = await _load_profile_with_children(db=db, user_id=current_user.id)
    return _to_response(profile)


@router.put("/vault", response_model=CompanyVaultResponse, status_code=status.HTTP_200_OK)
async def update_company_vault(
    payload: CompanyVaultUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompanyVaultResponse:
    profile = await _get_or_create_profile(db=db, user_id=current_user.id)

    # Update root company profile fields
    profile.company_name = payload.company_name
    profile.director_name = payload.director_name
    profile.address = payload.address
    profile.phone_contact = payload.phone_contact
    profile.bank_name = payload.bank_name
    profile.mfo = payload.mfo
    profile.account_number = payload.account_number
    profile.inn = payload.inn

    user_company_ids = select(CompanyProfile.id).where(
        CompanyProfile.user_id == current_user.id
    )

    # Full replacement strategy for nested collections.
    await db.execute(
        delete(Certification).where(Certification.company_id.in_(user_company_ids))
    )
    await db.execute(
        delete(License).where(License.company_id.in_(user_company_ids))
    )
    await db.execute(
        delete(FinancialHistory).where(FinancialHistory.company_id.in_(user_company_ids))
    )
    await db.flush()

    db.add_all(
        [
            Certification(
                company_id=profile.id,
                cert_type=item.cert_type,
                issue_date=item.issue_date,
                expiry_date=item.expiry_date,
            )
            for item in payload.certifications
        ]
    )
    db.add_all(
        [
            License(
                company_id=profile.id,
                license_name=item.license_name,
                is_active=item.is_active,
            )
            for item in payload.licenses
        ]
    )
    db.add_all(
        [
            FinancialHistory(
                company_id=profile.id,
                year=item.year,
                turnover_uzs=item.turnover_uzs,
            )
            for item in payload.financial_history
        ]
    )

    await db.commit()

    refreshed = await db.execute(
        select(CompanyProfile)
        .options(
            selectinload(CompanyProfile.certifications),
            selectinload(CompanyProfile.licenses),
            selectinload(CompanyProfile.financial_history),
        )
        .where(
            CompanyProfile.id == profile.id,
            CompanyProfile.user_id == current_user.id,
        )
    )
    return _to_response(refreshed.scalar_one())
