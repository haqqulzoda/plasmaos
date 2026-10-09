from __future__ import annotations

from uuid import UUID

from typing import Annotated
from fastapi import Query, Response
from app.core.pagination import page_rows
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_approved_pilot_access
from app.services.organization_context import (
    ProfileContext,
    effective_company_profile,
    effective_company_profile_id,
    organization_profile_context,
)
from app.services.organization_records import changed_fields, record_for_context, snapshot
from app.db.session import get_db
from app.models.all_models import User
from app.models.company import (
    Certification,
    CompanyProfile,
    FinancialHistory,
    License,
    ReadinessDocument,
)
from app.schemas.vault import (
    CertificationItem,
    CompanyVaultResponse,
    CompanyVaultUpdate,
    FinancialHistoryItem,
    LicenseItem,
    ReadinessDocumentCreate,
    ReadinessDocumentResponse,
    ReadinessDocumentUpdate,
)

router = APIRouter()


async def _organization_profile(db: AsyncSession, user_id) -> tuple[ProfileContext | None, CompanyProfile]:
    """The selected organization's company profile (R3 Task 6), never the user's own."""
    context = await organization_profile_context(db, user_id=user_id)
    profile = context.profile if context is not None else await effective_company_profile(db, user_id=user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company onboarding required",
        )
    return context, profile


async def _get_profile_or_404(db: AsyncSession, user_id) -> CompanyProfile:
    return (await _organization_profile(db, user_id))[1]


async def _get_readiness_document_or_404(
    *,
    db: AsyncSession,
    document_id: UUID,
    company_profile_id: UUID,
) -> ReadinessDocument:
    result = await db.execute(
        select(ReadinessDocument).where(
            ReadinessDocument.id == document_id,
            ReadinessDocument.company_profile_id == company_profile_id,
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Readiness document not found",
        )
    return document


async def _load_profile_with_children(
    db: AsyncSession,
    user_id,
) -> CompanyProfile | None:
    profile_id = await effective_company_profile_id(db, user_id=user_id)
    if profile_id is None:
        return None
    result = await db.execute(
        select(CompanyProfile)
        .options(
            selectinload(CompanyProfile.certifications),
            selectinload(CompanyProfile.licenses),
            selectinload(CompanyProfile.financial_history),
        )
        .where(CompanyProfile.id == profile_id)
    )
    return result.scalar_one_or_none()


async def _children_signature(db: AsyncSession, profile_id) -> dict[str, list]:
    """Comparable contents of the replaced vault collections (for the audit field list)."""
    certifications = (await db.execute(
        select(Certification.cert_type, Certification.issue_date, Certification.expiry_date)
        .where(Certification.company_id == profile_id)
    )).all()
    licenses = (await db.execute(
        select(License.license_name, License.is_active).where(License.company_id == profile_id)
    )).all()
    financial = (await db.execute(
        select(FinancialHistory.year, FinancialHistory.turnover_uzs).where(FinancialHistory.company_id == profile_id)
    )).all()
    return {
        "certifications": sorted(map(tuple, certifications), key=str),
        "licenses": sorted(map(tuple, licenses), key=str),
        "financial_history": sorted(map(tuple, financial), key=str),
    }


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
        industry=profile.industry,
        website=profile.website,
        target_regions=profile.target_regions,
        target_countries=profile.target_countries,
        target_services=profile.target_services,
        notes=profile.notes,
        pilot_status=profile.pilot_status,
        approval_status=profile.approval_status,
        certifications=certifications,
        licenses=licenses,
        financial_history=financial_history,
    )


@router.get("/vault", response_model=CompanyVaultResponse)
async def get_company_vault(
    current_user: User = Depends(require_approved_pilot_access),
    db: AsyncSession = Depends(get_db),
) -> CompanyVaultResponse:
    profile = await _load_profile_with_children(db=db, user_id=current_user.id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company onboarding required",
        )
    return _to_response(profile)


@router.put("/vault", response_model=CompanyVaultResponse, status_code=status.HTTP_200_OK)
async def update_company_vault(
    payload: CompanyVaultUpdate,
    current_user: User = Depends(require_approved_pilot_access),
    db: AsyncSession = Depends(get_db),
) -> CompanyVaultResponse:
    context, profile = await _organization_profile(db, current_user.id)
    root_fields = (
        "company_name", "director_name", "address", "phone_contact", "bank_name", "mfo", "account_number",
        "inn", "industry", "website", "target_regions", "target_countries", "target_services", "notes",
    )
    before = snapshot(profile, root_fields)
    before_children = await _children_signature(db, profile.id)

    # Update root company profile fields
    profile.company_name = payload.company_name
    profile.director_name = payload.director_name
    profile.address = payload.address
    profile.phone_contact = payload.phone_contact
    profile.bank_name = payload.bank_name
    profile.mfo = payload.mfo
    profile.account_number = payload.account_number
    profile.inn = payload.inn
    profile.industry = payload.industry
    profile.website = payload.website
    profile.target_regions = payload.target_regions
    profile.target_countries = payload.target_countries
    profile.target_services = payload.target_services
    profile.notes = payload.notes

    user_company_ids = select(CompanyProfile.id).where(CompanyProfile.id == profile.id)

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

    await db.flush()
    fields = changed_fields(before, snapshot(profile, root_fields))
    after_children = await _children_signature(db, profile.id)
    fields += [name for name in after_children if after_children[name] != before_children[name]]
    await record_for_context(
        db, context, actor_user_id=current_user.id, record_type="COMPANY_VAULT", action="UPDATE",
        fields=fields, record_id=profile.id,
    )
    await db.commit()

    refreshed = await db.execute(
        select(CompanyProfile)
        .options(
            selectinload(CompanyProfile.certifications),
            selectinload(CompanyProfile.licenses),
            selectinload(CompanyProfile.financial_history),
        )
        .where(CompanyProfile.id == profile.id)
        .execution_options(populate_existing=True)
    )
    return _to_response(refreshed.scalar_one())


@router.get("/vault/readiness", response_model=list[ReadinessDocumentResponse])
async def list_readiness_documents(
    current_user: User = Depends(require_approved_pilot_access),
    db: AsyncSession = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    response: Response = None,
    document_type: str | None = None,
    status: str | None = None,
    related_service: str | None = None,
) -> list[ReadinessDocumentResponse]:
    profile = await _get_profile_or_404(db=db, user_id=current_user.id)
    from sqlalchemy import func
    conditions = [ReadinessDocument.company_profile_id == profile.id]
    for column, value in ((ReadinessDocument.document_type, document_type),
                          (ReadinessDocument.status, status),
                          (ReadinessDocument.related_service, related_service)):
        if value:
            conditions.append(column == value)
    if response is not None:
        total = await db.scalar(select(func.count()).select_from(ReadinessDocument).where(*conditions))
        response.headers["X-Total-Count"] = str(total)
    result = await db.execute(
        select(ReadinessDocument)
        .where(*conditions)
        .order_by(ReadinessDocument.document_type, ReadinessDocument.document_name, ReadinessDocument.id)
        .limit(limit + 1).offset(offset)
    )
    return [
        ReadinessDocumentResponse.model_validate(document)
        for document in page_rows(list(result.scalars().all()), limit=limit, offset=offset, response=response)
    ]


@router.post(
    "/vault/readiness",
    response_model=ReadinessDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_readiness_document(
    payload: ReadinessDocumentCreate,
    current_user: User = Depends(require_approved_pilot_access),
    db: AsyncSession = Depends(get_db),
) -> ReadinessDocumentResponse:
    context, profile = await _organization_profile(db, current_user.id)
    document = ReadinessDocument(
        company_profile_id=profile.id,
        **payload.model_dump(),
    )
    db.add(document)
    await db.flush()
    await record_for_context(
        db, context, actor_user_id=current_user.id, record_type="READINESS_DOCUMENT", action="CREATE",
        fields=sorted(payload.model_dump(exclude_none=True)), record_id=document.id,
    )
    await db.commit()
    await db.refresh(document)
    return ReadinessDocumentResponse.model_validate(document)


@router.put(
    "/vault/readiness/{document_id}",
    response_model=ReadinessDocumentResponse,
)
async def update_readiness_document(
    document_id: UUID,
    payload: ReadinessDocumentUpdate,
    current_user: User = Depends(require_approved_pilot_access),
    db: AsyncSession = Depends(get_db),
) -> ReadinessDocumentResponse:
    context, profile = await _organization_profile(db, current_user.id)
    document = await _get_readiness_document_or_404(
        db=db,
        document_id=document_id,
        company_profile_id=profile.id,
    )

    values = payload.model_dump(exclude_unset=True)
    before = snapshot(document, values)
    for field, value in values.items():
        setattr(document, field, value)

    await record_for_context(
        db, context, actor_user_id=current_user.id, record_type="READINESS_DOCUMENT", action="UPDATE",
        fields=changed_fields(before, values), record_id=document.id,
    )
    await db.commit()
    await db.refresh(document)
    return ReadinessDocumentResponse.model_validate(document)


@router.delete("/vault/readiness/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_readiness_document(
    document_id: UUID,
    current_user: User = Depends(require_approved_pilot_access),
    db: AsyncSession = Depends(get_db),
) -> None:
    context, profile = await _organization_profile(db, current_user.id)
    document = await _get_readiness_document_or_404(
        db=db,
        document_id=document_id,
        company_profile_id=profile.id,
    )
    await record_for_context(
        db, context, actor_user_id=current_user.id, record_type="READINESS_DOCUMENT", action="DELETE",
        fields=[], record_id=document.id,
    )
    await db.delete(document)
    await db.commit()
