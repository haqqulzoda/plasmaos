"""Admin/operator endpoints for platform administration."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, not_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_admin, require_operator_or_admin
from app.core.access import (
    COMPANY_APPROVAL_APPROVED,
    COMPANY_APPROVAL_DISABLED,
    COMPANY_APPROVAL_PENDING,
    COMPANY_APPROVAL_REJECTED,
    USER_APPROVAL_APPROVED,
    USER_APPROVAL_DISABLED,
    USER_APPROVAL_PENDING,
    USER_APPROVAL_REJECTED,
)
from app.core.geography import normalize_target_countries, normalize_target_regions
from app.core.reproducibility import requirement_route_records
from app.core.services import normalize_target_services
from app.db.session import get_db
from app.models.all_models import AdminActivityEvent, Proposal, ProposalStatus, Tender, TenderAnalysis, User
from app.models.company import CompanyProfile, ReadinessDocument
from app.schemas.vault import ReadinessDocumentResponse
from app.services.admin_activity import (
    bump_auth_version,
    record_admin_activity,
    user_role_snapshot,
)
from app.services.tender_sources.uzex_scope import (
    customer_visible_tender_condition,
    uzex_small_scale_tender_condition,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class ApprovalActionRequest(BaseModel):
    reason: str | None = None


class ApprovalQueueCompany(BaseModel):
    id: UUID
    company_name: str | None = None
    industry: str | None = None
    target_regions: list[str] | None = None
    target_countries: list[str] | None = None
    target_services: list[str] | None = None
    approval_status: str
    pilot_status: str
    rejection_reason: str | None = None
    created_at: str | None = None


class ApprovalQueueUser(BaseModel):
    id: UUID
    name: str
    email: str
    approval_status: str
    platform_role: str
    is_admin: bool
    rejection_reason: str | None = None
    created_at: str | None = None


class ApprovalQueueItem(BaseModel):
    user: ApprovalQueueUser
    company: ApprovalQueueCompany | None = None


class ApprovalQueueResponse(BaseModel):
    items: list[ApprovalQueueItem]


class AdminCompanyResponse(BaseModel):
    id: UUID
    user_id: UUID
    user_name: str | None = None
    user_email: str | None = None
    company_name: str | None = None
    industry: str | None = None
    inn: str | None = None
    website: str | None = None
    phone_contact: str | None = None
    address: str | None = None
    target_regions: list[str] | None = None
    target_countries: list[str] | None = None
    target_services: list[str] | None = None
    pilot_status: str
    approval_status: str


class AdminActivityEventResponse(BaseModel):
    id: UUID
    action: str
    actor_label: str | None = None
    target_email: str
    reason: str | None = None
    created_at: str | None = None


class AdminActivityResponse(BaseModel):
    total_users: int
    pending_users: int
    approved_users: int
    total_companies: int
    pending_companies: int
    approved_companies: int
    analyses_count: int
    reports_count: int
    vault_records_count: int
    recent_events: list[AdminActivityEventResponse] = Field(default_factory=list)


class AdminCorpusHealthResponse(BaseModel):
    uzex_visible_count: int
    world_bank_visible_count: int
    adb_visible_count: int
    hidden_legacy_uzex_count: int
    small_uzex_count: int


async def _count_model_rows(db: AsyncSession, model: Any, *conditions: Any) -> int:
    query = select(func.count()).select_from(model)
    if conditions:
        query = query.where(*conditions)
    result = await db.execute(query)
    return int(result.scalar_one() or 0)


async def _count_optional_model_rows(
    db: AsyncSession,
    model: Any,
    *conditions: Any,
) -> int:
    try:
        return await _count_model_rows(db, model, *conditions)
    except SQLAlchemyError:
        await db.rollback()
        logger.warning(
            "admin_optional_metric_unavailable table=%s",
            getattr(model, "__tablename__", str(model)),
            exc_info=True,
        )
        return 0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _user_payload(user: User) -> ApprovalQueueUser:
    return ApprovalQueueUser(
        id=user.id,
        name=user.name,
        email=user.email,
        approval_status=user.approval_status,
        platform_role=user.platform_role,
        is_admin=user.is_admin,
        rejection_reason=user.rejection_reason,
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


def _company_payload(profile: CompanyProfile | None) -> ApprovalQueueCompany | None:
    if profile is None:
        return None
    return ApprovalQueueCompany(
        id=profile.id,
        company_name=profile.company_name,
        industry=profile.industry,
        target_regions=normalize_target_regions(profile.target_regions, reject_invalid=False),
        target_countries=normalize_target_countries(profile.target_countries, reject_invalid=False),
        target_services=normalize_target_services(profile.target_services, reject_invalid=False),
        approval_status=profile.approval_status,
        pilot_status=profile.pilot_status,
        rejection_reason=profile.rejection_reason,
    )


def _clean_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    stripped = reason.strip()
    return stripped or None


def _admin_activity_event_payload(
    event: AdminActivityEvent,
) -> AdminActivityEventResponse:
    return AdminActivityEventResponse(
        id=event.id,
        action=event.action,
        actor_label=event.actor_label,
        target_email=event.target_email,
        reason=event.reason,
        created_at=event.created_at.isoformat() if event.created_at else None,
    )


async def _latest_admin_activity_events(db: AsyncSession) -> list[AdminActivityEventResponse]:
    result = await db.execute(
        select(AdminActivityEvent)
        .order_by(AdminActivityEvent.created_at.desc(), AdminActivityEvent.id.desc())
        .limit(20)
    )
    return [_admin_activity_event_payload(event) for event in result.scalars().all()]


@router.get(
    "/activity",
    response_model=AdminActivityResponse,
    dependencies=[Depends(require_operator_or_admin)],
)
async def get_admin_activity(
    db: AsyncSession = Depends(get_db),
) -> AdminActivityResponse:
    """Return simple read-only operational counts for the Admin overview."""
    return AdminActivityResponse(
        total_users=await _count_model_rows(db, User),
        pending_users=await _count_model_rows(
            db,
            User,
            User.approval_status == USER_APPROVAL_PENDING,
        ),
        approved_users=await _count_model_rows(
            db,
            User,
            User.approval_status == USER_APPROVAL_APPROVED,
        ),
        total_companies=await _count_model_rows(db, CompanyProfile),
        pending_companies=await _count_model_rows(
            db,
            CompanyProfile,
            CompanyProfile.approval_status == COMPANY_APPROVAL_PENDING,
        ),
        approved_companies=await _count_model_rows(
            db,
            CompanyProfile,
            CompanyProfile.approval_status == COMPANY_APPROVAL_APPROVED,
        ),
        analyses_count=await _count_model_rows(db, TenderAnalysis),
        reports_count=await _count_model_rows(
            db,
            Proposal,
            Proposal.status == ProposalStatus.COMPLETED,
        ),
        vault_records_count=await _count_optional_model_rows(db, ReadinessDocument),
        recent_events=await _latest_admin_activity_events(db),
    )


@router.get(
    "/corpus-health",
    response_model=AdminCorpusHealthResponse,
    dependencies=[Depends(require_operator_or_admin)],
)
async def get_admin_corpus_health(
    db: AsyncSession = Depends(get_db),
) -> AdminCorpusHealthResponse:
    """Return source-level tender corpus visibility counts."""
    visible_condition = customer_visible_tender_condition(Tender)
    small_uzex_condition = uzex_small_scale_tender_condition(Tender)
    hidden_legacy_condition = (
        (Tender.source_system == "uzex")
        & not_(visible_condition)
        & not_(small_uzex_condition)
    )

    return AdminCorpusHealthResponse(
        uzex_visible_count=await _count_model_rows(
            db,
            Tender,
            Tender.source_system == "uzex",
            visible_condition,
        ),
        world_bank_visible_count=await _count_model_rows(
            db,
            Tender,
            Tender.source_system == "world_bank",
            visible_condition,
        ),
        adb_visible_count=await _count_model_rows(
            db,
            Tender,
            Tender.source_system == "adb",
            visible_condition,
        ),
        hidden_legacy_uzex_count=await _count_model_rows(
            db,
            Tender,
            hidden_legacy_condition,
        ),
        small_uzex_count=await _count_model_rows(
            db,
            Tender,
            small_uzex_condition,
        ),
    )


async def _get_user_or_404(db: AsyncSession, user_id: UUID) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


async def _get_company_or_404(db: AsyncSession, company_profile_id: UUID) -> CompanyProfile:
    result = await db.execute(
        select(CompanyProfile)
        .options(selectinload(CompanyProfile.user))
        .where(CompanyProfile.id == company_profile_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found",
        )
    return profile


@router.get(
    "/approval-queue",
    response_model=ApprovalQueueResponse,
    dependencies=[Depends(require_operator_or_admin)],
)
async def get_approval_queue(
    db: AsyncSession = Depends(get_db),
) -> ApprovalQueueResponse:
    """Return users/companies that need or recently received approval review."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.company_profile))
        .where(
            or_(
                User.approval_status != USER_APPROVAL_APPROVED,
                User.company_profile.has(
                    CompanyProfile.approval_status != COMPANY_APPROVAL_APPROVED,
                ),
            )
        )
        .order_by(User.created_at.desc())
    )
    users = result.scalars().unique().all()
    return ApprovalQueueResponse(
        items=[
            ApprovalQueueItem(
                user=_user_payload(user),
                company=_company_payload(user.company_profile),
            )
            for user in users
        ]
    )


@router.get(
    "/companies/{company_profile_id}",
    response_model=AdminCompanyResponse,
    dependencies=[Depends(require_operator_or_admin)],
)
async def get_admin_company_profile(
    company_profile_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> AdminCompanyResponse:
    """Return company profile data for operator/admin review."""
    profile = await _get_company_or_404(db, company_profile_id)
    return AdminCompanyResponse(
        id=profile.id,
        user_id=profile.user_id,
        user_name=profile.user.name if profile.user else None,
        user_email=profile.user.email if profile.user else None,
        company_name=profile.company_name,
        industry=profile.industry,
        inn=profile.inn,
        website=profile.website,
        phone_contact=profile.phone_contact,
        address=profile.address,
        target_regions=normalize_target_regions(profile.target_regions, reject_invalid=False),
        target_countries=normalize_target_countries(profile.target_countries, reject_invalid=False),
        target_services=normalize_target_services(profile.target_services, reject_invalid=False),
        pilot_status=profile.pilot_status,
        approval_status=profile.approval_status,
    )


@router.get(
    "/companies/{company_profile_id}/readiness",
    response_model=list[ReadinessDocumentResponse],
    dependencies=[Depends(require_operator_or_admin)],
)
async def get_admin_company_readiness_documents(
    company_profile_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ReadinessDocumentResponse]:
    """Return readiness vault records for operator/admin review."""
    await _get_company_or_404(db, company_profile_id)
    result = await db.execute(
        select(ReadinessDocument)
        .where(ReadinessDocument.company_profile_id == company_profile_id)
        .order_by(ReadinessDocument.document_type, ReadinessDocument.document_name)
    )
    return [
        ReadinessDocumentResponse.model_validate(document)
        for document in result.scalars().all()
    ]


@router.post("/users/{user_id}/approve", response_model=ApprovalQueueUser)
async def approve_user(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApprovalQueueUser:
    user = await _get_user_or_404(db, user_id)
    before = user_role_snapshot(user)
    user.approval_status = USER_APPROVAL_APPROVED
    user.approved_at = _utcnow()
    user.approved_by_user_id = current_user.id
    user.rejected_at = None
    user.rejection_reason = None
    user.disabled_at = None
    bump_auth_version(user)
    await record_admin_activity(
        db,
        action="user_approved",
        actor_user=current_user,
        target_user=user,
        reason="Admin approved user account.",
        metadata={"before": before, "after": user_role_snapshot(user)},
    )
    await db.commit()
    await db.refresh(user)
    return _user_payload(user)


@router.post("/users/{user_id}/reject", response_model=ApprovalQueueUser)
async def reject_user(
    user_id: UUID,
    payload: ApprovalActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ApprovalQueueUser:
    user = await _get_user_or_404(db, user_id)
    before = user_role_snapshot(user)
    user.approval_status = USER_APPROVAL_REJECTED
    user.rejected_at = _utcnow()
    user.rejection_reason = _clean_reason(payload.reason)
    bump_auth_version(user)
    await record_admin_activity(
        db,
        action="user_rejected",
        actor_user=current_user,
        target_user=user,
        reason=_clean_reason(payload.reason) or "Admin rejected user account.",
        metadata={"before": before, "after": user_role_snapshot(user)},
    )
    await db.commit()
    await db.refresh(user)
    return _user_payload(user)


@router.post("/users/{user_id}/disable", response_model=ApprovalQueueUser)
async def disable_user(
    user_id: UUID,
    payload: ApprovalActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ApprovalQueueUser:
    user = await _get_user_or_404(db, user_id)
    before = user_role_snapshot(user)
    user.approval_status = USER_APPROVAL_DISABLED
    user.disabled_at = _utcnow()
    user.rejection_reason = _clean_reason(payload.reason)
    bump_auth_version(user)
    await record_admin_activity(
        db,
        action="user_disabled",
        actor_user=current_user,
        target_user=user,
        reason=_clean_reason(payload.reason) or "Admin disabled user account.",
        metadata={"before": before, "after": user_role_snapshot(user)},
    )
    await db.commit()
    await db.refresh(user)
    return _user_payload(user)


@router.post("/companies/{company_profile_id}/approve", response_model=ApprovalQueueCompany)
async def approve_company(
    company_profile_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApprovalQueueCompany:
    profile = await _get_company_or_404(db, company_profile_id)
    target_user = profile.user
    before = {
        "company_approval_status": profile.approval_status,
        "user": user_role_snapshot(target_user),
    }
    profile.approval_status = COMPANY_APPROVAL_APPROVED
    profile.approved_at = _utcnow()
    profile.approved_by_user_id = current_user.id
    profile.rejected_at = None
    profile.rejection_reason = None
    bump_auth_version(target_user)
    await record_admin_activity(
        db,
        action="company_approved",
        actor_user=current_user,
        target_user=target_user,
        reason="Admin approved company profile.",
        metadata={
            "company_profile_id": str(profile.id),
            "before": before,
            "after": {
                "company_approval_status": profile.approval_status,
                "user": user_role_snapshot(target_user),
            },
        },
    )
    await db.commit()
    await db.refresh(profile)
    payload = _company_payload(profile)
    assert payload is not None
    return payload


@router.post("/companies/{company_profile_id}/reject", response_model=ApprovalQueueCompany)
async def reject_company(
    company_profile_id: UUID,
    payload: ApprovalActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ApprovalQueueCompany:
    profile = await _get_company_or_404(db, company_profile_id)
    target_user = profile.user
    before = {
        "company_approval_status": profile.approval_status,
        "user": user_role_snapshot(target_user),
    }
    profile.approval_status = COMPANY_APPROVAL_REJECTED
    profile.rejected_at = _utcnow()
    profile.rejection_reason = _clean_reason(payload.reason)
    bump_auth_version(target_user)
    await record_admin_activity(
        db,
        action="company_rejected",
        actor_user=current_user,
        target_user=target_user,
        reason=_clean_reason(payload.reason) or "Admin rejected company profile.",
        metadata={
            "company_profile_id": str(profile.id),
            "before": before,
            "after": {
                "company_approval_status": profile.approval_status,
                "user": user_role_snapshot(target_user),
            },
        },
    )
    await db.commit()
    await db.refresh(profile)
    company_payload = _company_payload(profile)
    assert company_payload is not None
    return company_payload


@router.post("/companies/{company_profile_id}/disable", response_model=ApprovalQueueCompany)
async def disable_company(
    company_profile_id: UUID,
    payload: ApprovalActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ApprovalQueueCompany:
    profile = await _get_company_or_404(db, company_profile_id)
    target_user = profile.user
    before = {
        "company_approval_status": profile.approval_status,
        "user": user_role_snapshot(target_user),
    }
    profile.approval_status = COMPANY_APPROVAL_DISABLED
    profile.rejection_reason = _clean_reason(payload.reason)
    bump_auth_version(target_user)
    await record_admin_activity(
        db,
        action="company_disabled",
        actor_user=current_user,
        target_user=target_user,
        reason=_clean_reason(payload.reason) or "Admin disabled company profile.",
        metadata={
            "company_profile_id": str(profile.id),
            "before": before,
            "after": {
                "company_approval_status": profile.approval_status,
                "user": user_role_snapshot(target_user),
            },
        },
    )
    await db.commit()
    await db.refresh(profile)
    company_payload = _company_payload(profile)
    assert company_payload is not None
    return company_payload


def _bucket_fingerprints(hybrid_compliance: dict[str, Any] | None) -> dict[str, list[str]]:
    if not isinstance(hybrid_compliance, dict):
        return {}

    return {
        "failed": [
            str(item.get("requirement_fingerprint"))
            for item in hybrid_compliance.get("failed_dealbreakers") or []
            if isinstance(item, dict) and item.get("requirement_fingerprint")
        ],
        "manual": [
            str(item.get("requirement_fingerprint"))
            for item in hybrid_compliance.get("manual_reviews_required") or []
            if isinstance(item, dict) and item.get("requirement_fingerprint")
        ],
        "satisfied": [
            str(item.get("requirement_fingerprint"))
            for item in hybrid_compliance.get("satisfied_requirements") or []
            if isinstance(item, dict) and item.get("requirement_fingerprint")
        ],
        "recorded": [
            str(item.get("requirement_fingerprint"))
            for item in hybrid_compliance.get("recorded_obligations") or []
            if isinstance(item, dict) and item.get("requirement_fingerprint")
        ],
    }


def _analysis_reproducibility_summary(analysis: TenderAnalysis) -> dict[str, Any]:
    analysis_data = analysis.analysis_json or {}
    hybrid_compliance = analysis_data.get("hybrid_compliance")
    if not isinstance(hybrid_compliance, dict):
        hybrid_compliance = {}
    snapshot = analysis_data.get("reproducibility_snapshot")
    snapshot_routes = []
    if isinstance(snapshot, dict):
        raw_routes = snapshot.get("requirement_route_summary") or []
        snapshot_routes = [item for item in raw_routes if isinstance(item, dict)]

    return {
        "analysis_id": str(analysis.id),
        "created_at": analysis.created_at.isoformat(),
        "analysis_status": analysis_data.get("analysis_status", "completed"),
        "content_hash": analysis.content_hash,
        "override_seal": analysis.override_seal,
        "coverage_metadata": analysis_data.get("coverage_metadata"),
        "reproducibility_snapshot": snapshot,
        "extraction_artifacts_metadata": analysis_data.get(
            "extraction_artifacts_metadata"
        )
        or [],
        "requirement_fingerprints": _bucket_fingerprints(hybrid_compliance),
        "requirement_route_summary": snapshot_routes
        or requirement_route_records(hybrid_compliance),
    }


@router.get("/tenders/{source_system}/{external_id}/reproducibility")
async def get_tender_reproducibility(
    source_system: str,
    external_id: str,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Return admin-only compliance reproducibility diagnostics for a tender.

    This intentionally excludes raw compiled text, parsed document text, prompts,
    secrets, and filesystem paths.
    """
    del current_user

    result = await db.execute(
        select(Tender).where(
            Tender.source_system == source_system.strip().casefold(),
            Tender.external_id == external_id,
        )
    )
    tender = result.scalar_one_or_none()
    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )

    analyses_result = await db.execute(
        select(TenderAnalysis)
        .where(TenderAnalysis.tender_id == tender.id)
        .order_by(TenderAnalysis.created_at.desc())
        .limit(10)
    )
    analyses = analyses_result.scalars().all()

    return {
        "tender_id": str(tender.id),
        "source_system": tender.source_system,
        "external_id": tender.external_id,
        "latest_analyses": [
            _analysis_reproducibility_summary(analysis)
            for analysis in analyses
        ],
    }
