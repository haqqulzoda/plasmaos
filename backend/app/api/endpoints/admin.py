"""Admin/operator endpoints for platform administration."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, not_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_admin, require_operator_or_admin
from app.core.access import (
    COMPANY_APPROVAL_APPROVED,
    COMPANY_APPROVAL_DISABLED,
    COMPANY_APPROVAL_PENDING,
    COMPANY_APPROVAL_REJECTED,
    PLATFORM_ROLE_ADMIN,
    PLATFORM_ROLE_OPERATOR,
    USER_APPROVAL_APPROVED,
    USER_APPROVAL_DISABLED,
    USER_APPROVAL_PENDING,
    USER_APPROVAL_REJECTED,
    USER_APPROVAL_STATUSES,
    USER_RESTORABLE_APPROVAL_STATUSES,
    is_effective_admin,
    normalized_approval_status,
)
from app.core.geography import normalize_target_countries, normalize_target_regions
from app.core.reproducibility import requirement_route_records
from app.core.services import normalize_target_services
from app.db.session import get_db
from app.models.all_models import AdminActivityEvent, Proposal, ProposalStatus, Tender, TenderAnalysis, User
from app.models.audit import AnalysisVersion
from app.models.company import CompanyProfile, ReadinessDocument
from app.schemas.vault import ReadinessDocumentResponse
from app.services.admin_activity import (
    ACTION_COMPANY_APPROVED,
    ACTION_COMPANY_DISABLED,
    ACTION_COMPANY_REJECTED,
    ACTION_USER_APPROVED,
    ACTION_USER_DISABLED,
    ACTION_USER_REJECTED,
    ACTION_USER_RESTORED,
    OUTCOME_DENIED,
    OUTCOME_FAILED,
    OUTCOME_SUCCESS,
    REASON_INVALID_LIFECYCLE_TRANSITION,
    REASON_TRANSACTION_FAILED,
    SOURCE_ADMIN_API,
    bump_auth_version,
    company_role_snapshot,
    record_admin_audit_event,
    record_independent_user_audit_event,
    user_role_snapshot,
)
from app.services.account_lifecycle import (
    ALLOWED_USER_LIFECYCLE_TRANSITIONS,
    InvalidAccountLifecycleTransition,
    LifecycleAction,
)
from app.services.admin_survivability import (
    AdminActorAuthorityLost,
    AdminSurvivabilityViolation,
    apply_locked_user_lifecycle_mutation,
)
from app.services.analysis_versions import (
    get_latest_analysis_version_for_parent,
    verify_analysis_version_integrity,
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
    pre_disabled_approval_status: str | None = None
    platform_role: str
    is_admin: bool
    rejection_reason: str | None = None
    created_at: str | None = None


class ApprovalQueueItem(BaseModel):
    user: ApprovalQueueUser
    company: ApprovalQueueCompany | None = None


class ApprovalQueueResponse(BaseModel):
    items: list[ApprovalQueueItem]


class AdminAccountItem(BaseModel):
    id: UUID
    name: str
    email: str
    approval_status: str
    role: str
    is_current_actor: bool
    restore_target_status: str | None = None
    allowed_actions: list[LifecycleAction] = Field(default_factory=list)
    company: ApprovalQueueCompany | None = None
    created_at: str | None = None


class AdminAccountsPage(BaseModel):
    items: list[AdminAccountItem]
    total: int
    limit: int
    offset: int


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


class AdminAuditEventResponse(BaseModel):
    id: UUID
    occurred_at: str
    action: str
    outcome: str | None = None
    actor_user_id: UUID | None = None
    actor_type: str | None = None
    actor_email_snapshot: str | None = None
    actor_role_snapshot: str | None = None
    actor_label: str | None = None
    target_user_id: UUID | None = None
    target_email_snapshot: str
    target_resource_type: str | None = None
    target_resource_id: str | None = None
    previous_state: dict[str, Any] | None = None
    new_state: dict[str, Any] | None = None
    reason_code: str | None = None
    reason: str | None = None
    request_id: str | None = None
    source: str | None = None
    metadata: dict[str, Any] | None = None


class AdminAuditEventsPage(BaseModel):
    items: list[AdminAuditEventResponse]
    total: int
    limit: int
    offset: int


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
        pre_disabled_approval_status=getattr(
            user,
            "pre_disabled_approval_status",
            None,
        ),
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
)
async def get_admin_activity(
    current_user: User = Depends(require_operator_or_admin),
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
        recent_events=(
            await _latest_admin_activity_events(db)
            if is_effective_admin(current_user)
            else []
        ),
    )


def _admin_audit_event_payload(event: AdminActivityEvent) -> AdminAuditEventResponse:
    return AdminAuditEventResponse(
        id=event.id,
        occurred_at=event.created_at.isoformat(),
        action=event.action,
        outcome=event.outcome,
        actor_user_id=event.actor_user_id,
        actor_type=event.actor_type,
        actor_email_snapshot=event.actor_email_snapshot,
        actor_role_snapshot=event.actor_role_snapshot,
        actor_label=event.actor_label,
        target_user_id=event.target_user_id,
        target_email_snapshot=event.target_email,
        target_resource_type=event.target_resource_type,
        target_resource_id=event.target_resource_id,
        previous_state=event.previous_state,
        new_state=event.new_state,
        reason_code=event.reason_code,
        reason=event.reason,
        request_id=event.request_id,
        source=event.source,
        # Legacy rows predate payload validation and may contain obsolete
        # implementation details such as auth-version values. Keep them stored
        # unchanged, but do not expose their free-form metadata through the
        # canonical API.
        metadata=event.metadata_json if event.outcome is not None else None,
    )


@router.get("/audit-events", response_model=AdminAuditEventsPage)
async def get_admin_audit_events(
    actor_user_id: UUID | None = None,
    target_user_id: UUID | None = None,
    action: str | None = None,
    outcome: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminAuditEventsPage:
    """Return effective-admin-only, deterministic canonical audit history."""
    del current_user
    conditions: list[Any] = []
    if actor_user_id is not None:
        conditions.append(AdminActivityEvent.actor_user_id == actor_user_id)
    if target_user_id is not None:
        conditions.append(AdminActivityEvent.target_user_id == target_user_id)
    if action is not None:
        normalized_action = action.strip().upper()
        if not normalized_action:
            raise HTTPException(status_code=422, detail="action cannot be empty")
        conditions.append(AdminActivityEvent.action == normalized_action)
    if outcome is not None:
        normalized_outcome = outcome.strip().upper()
        if normalized_outcome not in {OUTCOME_SUCCESS, OUTCOME_DENIED, OUTCOME_FAILED}:
            raise HTTPException(status_code=422, detail="invalid audit outcome")
        conditions.append(AdminActivityEvent.outcome == normalized_outcome)

    count_query = select(func.count()).select_from(AdminActivityEvent)
    events_query = select(AdminActivityEvent)
    if conditions:
        count_query = count_query.where(*conditions)
        events_query = events_query.where(*conditions)
    total = int((await db.execute(count_query)).scalar_one() or 0)
    result = await db.execute(
        events_query
        .order_by(AdminActivityEvent.created_at.desc(), AdminActivityEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return AdminAuditEventsPage(
        items=[_admin_audit_event_payload(event) for event in result.scalars().all()],
        total=total,
        limit=limit,
        offset=offset,
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


def _display_role(user: User) -> str:
    if user.is_admin or user.platform_role == PLATFORM_ROLE_ADMIN:
        return "admin"
    if user.platform_role == PLATFORM_ROLE_OPERATOR:
        return "operator"
    return "user"


def _restore_target_status(user: User) -> str | None:
    if normalized_approval_status(user.approval_status) != USER_APPROVAL_DISABLED:
        return None
    previous = normalized_approval_status(
        getattr(user, "pre_disabled_approval_status", None)
    )
    return (
        previous
        if previous in USER_RESTORABLE_APPROVAL_STATUSES
        else USER_APPROVAL_PENDING
    )


def _allowed_account_actions(
    user: User,
    *,
    current_user: User,
) -> list[LifecycleAction]:
    if not is_effective_admin(current_user):
        return []
    state = normalized_approval_status(user.approval_status)
    if state == USER_APPROVAL_DISABLED:
        return ["restore"]
    actions: list[LifecycleAction] = [
        action
        for action, transitions in ALLOWED_USER_LIFECYCLE_TRANSITIONS.items()
        if state in transitions
    ]
    if user.id == current_user.id:
        actions = [action for action in actions if action not in {"reject", "disable"}]
    return actions


def _admin_account_payload(user: User, *, current_user: User) -> AdminAccountItem:
    return AdminAccountItem(
        id=user.id,
        name=user.name,
        email=user.email,
        approval_status=user.approval_status,
        role=_display_role(user),
        is_current_actor=user.id == current_user.id,
        restore_target_status=_restore_target_status(user),
        allowed_actions=_allowed_account_actions(user, current_user=current_user),
        company=_company_payload(user.company_profile),
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


@router.get("/accounts", response_model=AdminAccountsPage)
async def get_admin_accounts(
    approval_status: str | None = None,
    role: str | None = None,
    query: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_operator_or_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminAccountsPage:
    """Return a bounded account view with backend-derived UI capabilities."""
    conditions: list[Any] = []
    if approval_status is not None:
        normalized_status = normalized_approval_status(approval_status)
        if normalized_status not in USER_APPROVAL_STATUSES:
            raise HTTPException(status_code=422, detail="invalid account status")
        conditions.append(User.approval_status == normalized_status)
    if role is not None:
        normalized_role = role.strip().casefold()
        if normalized_role == "admin":
            conditions.append(
                or_(User.is_admin.is_(True), User.platform_role == PLATFORM_ROLE_ADMIN)
            )
        elif normalized_role == "operator":
            conditions.append(
                and_(
                    User.is_admin.is_(False),
                    User.platform_role == PLATFORM_ROLE_OPERATOR,
                )
            )
        elif normalized_role == "user":
            conditions.append(
                and_(
                    User.is_admin.is_(False),
                    User.platform_role.notin_((PLATFORM_ROLE_ADMIN, PLATFORM_ROLE_OPERATOR)),
                )
            )
        else:
            raise HTTPException(status_code=422, detail="invalid account role")
    if query is not None and (normalized_query := query.strip().casefold()):
        conditions.append(
            or_(
                func.lower(User.email).contains(normalized_query),
                func.lower(User.name).contains(normalized_query),
            )
        )

    count_query = select(func.count()).select_from(User)
    accounts_query = select(User).options(selectinload(User.company_profile))
    if conditions:
        count_query = count_query.where(*conditions)
        accounts_query = accounts_query.where(*conditions)
    total = int((await db.execute(count_query)).scalar_one() or 0)
    status_order = case(
        (User.approval_status == USER_APPROVAL_PENDING, 0),
        (User.approval_status == USER_APPROVAL_APPROVED, 1),
        (User.approval_status == USER_APPROVAL_REJECTED, 2),
        (User.approval_status == USER_APPROVAL_DISABLED, 3),
        else_=4,
    )
    result = await db.execute(
        accounts_query
        .order_by(status_order, User.created_at.desc(), User.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return AdminAccountsPage(
        items=[
            _admin_account_payload(user, current_user=current_user)
            for user in result.scalars().unique().all()
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


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
    return await _apply_user_lifecycle_action(
        db=db,
        current_user=current_user,
        user_id=user_id,
        action="approve",
        audit_reason="Admin approved user account.",
    )


@router.post("/users/{user_id}/reject", response_model=ApprovalQueueUser)
async def reject_user(
    user_id: UUID,
    payload: ApprovalActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ApprovalQueueUser:
    return await _apply_user_lifecycle_action(
        db=db,
        current_user=current_user,
        user_id=user_id,
        action="reject",
        audit_reason=_clean_reason(payload.reason) or "Admin rejected user account.",
        state_reason=_clean_reason(payload.reason),
    )


@router.post("/users/{user_id}/disable", response_model=ApprovalQueueUser)
async def disable_user(
    user_id: UUID,
    payload: ApprovalActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ApprovalQueueUser:
    return await _apply_user_lifecycle_action(
        db=db,
        current_user=current_user,
        user_id=user_id,
        action="disable",
        audit_reason=_clean_reason(payload.reason) or "Admin disabled user account.",
    )


@router.post("/users/{user_id}/restore", response_model=ApprovalQueueUser)
async def restore_user(
    user_id: UUID,
    payload: ApprovalActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ApprovalQueueUser:
    return await _apply_user_lifecycle_action(
        db=db,
        current_user=current_user,
        user_id=user_id,
        action="restore",
        audit_reason=_clean_reason(payload.reason) or "Admin restored user account.",
    )


async def _apply_user_lifecycle_action(
    *,
    db: AsyncSession,
    current_user: User,
    user_id: UUID,
    action: LifecycleAction,
    audit_reason: str,
    state_reason: str | None = None,
) -> ApprovalQueueUser:
    actor_user_id = current_user.id
    audit_action = {
        "approve": ACTION_USER_APPROVED,
        "reject": ACTION_USER_REJECTED,
        "disable": ACTION_USER_DISABLED,
        "restore": ACTION_USER_RESTORED,
    }[action]
    try:
        mutation = await apply_locked_user_lifecycle_mutation(
            db,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            action=action,
            reason=state_reason,
        )
    except AdminActorAuthorityLost as exc:
        await db.rollback()
        await record_independent_user_audit_event(
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            action=audit_action,
            outcome=OUTCOME_DENIED,
            source=SOURCE_ADMIN_API,
            reason_code=exc.reason_code,
            reason="Actor no longer had effective administrator authority.",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        ) from exc
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        ) from exc
    except AdminSurvivabilityViolation as exc:
        await db.rollback()
        await record_independent_user_audit_event(
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            action=audit_action,
            outcome=OUTCOME_DENIED,
            source=SOURCE_ADMIN_API,
            reason_code=exc.reason_code,
            reason=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except InvalidAccountLifecycleTransition as exc:
        await db.rollback()
        await record_independent_user_audit_event(
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            action=audit_action,
            outcome=OUTCOME_DENIED,
            source=SOURCE_ADMIN_API,
            reason_code=REASON_INVALID_LIFECYCLE_TRANSITION,
            reason=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    user = mutation.target
    actor = mutation.actor
    try:
        await record_admin_audit_event(
            db,
            action=audit_action,
            outcome=OUTCOME_SUCCESS,
            source=SOURCE_ADMIN_API,
            actor_user=actor,
            target_user=user,
            reason=audit_reason,
            previous_state=mutation.before,
            new_state=user_role_snapshot(user, credentials_invalidated=True),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        await record_independent_user_audit_event(
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            action=audit_action,
            outcome=OUTCOME_FAILED,
            source=SOURCE_ADMIN_API,
            reason_code=REASON_TRANSACTION_FAILED,
            reason="Administrative lifecycle transaction failed and was rolled back.",
        )
        raise
    return _user_payload(user)


async def _commit_company_audit(
    *,
    db: AsyncSession,
    actor: User,
    target: User,
    profile: CompanyProfile,
    action: str,
    reason: str,
    previous_state: dict[str, Any],
) -> None:
    actor_user_id = actor.id
    target_user_id = target.id
    try:
        await record_admin_audit_event(
            db,
            action=action,
            outcome=OUTCOME_SUCCESS,
            source=SOURCE_ADMIN_API,
            actor_user=actor,
            target_user=target,
            target_resource_type="COMPANY_PROFILE",
            target_resource_id=str(profile.id),
            reason=reason,
            previous_state=previous_state,
            new_state=company_role_snapshot(
                company_approval_status=profile.approval_status,
                user=target,
                credentials_invalidated=True,
            ),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        await record_independent_user_audit_event(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            action=action,
            outcome=OUTCOME_FAILED,
            source=SOURCE_ADMIN_API,
            reason_code=REASON_TRANSACTION_FAILED,
            reason="Administrative company transaction failed and was rolled back.",
            previous_state=previous_state,
        )
        raise


@router.post("/companies/{company_profile_id}/approve", response_model=ApprovalQueueCompany)
async def approve_company(
    company_profile_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApprovalQueueCompany:
    profile = await _get_company_or_404(db, company_profile_id)
    target_user = profile.user
    before = company_role_snapshot(
        company_approval_status=profile.approval_status,
        user=target_user,
    )
    profile.approval_status = COMPANY_APPROVAL_APPROVED
    profile.approved_at = _utcnow()
    profile.approved_by_user_id = current_user.id
    profile.rejected_at = None
    profile.rejection_reason = None
    bump_auth_version(target_user)
    await _commit_company_audit(
        db=db,
        actor=current_user,
        target=target_user,
        profile=profile,
        action=ACTION_COMPANY_APPROVED,
        reason="Admin approved company profile.",
        previous_state=before,
    )
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
    before = company_role_snapshot(
        company_approval_status=profile.approval_status,
        user=target_user,
    )
    profile.approval_status = COMPANY_APPROVAL_REJECTED
    profile.rejected_at = _utcnow()
    profile.rejection_reason = _clean_reason(payload.reason)
    bump_auth_version(target_user)
    await _commit_company_audit(
        db=db,
        actor=current_user,
        target=target_user,
        profile=profile,
        action=ACTION_COMPANY_REJECTED,
        reason=_clean_reason(payload.reason) or "Admin rejected company profile.",
        previous_state=before,
    )
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
    before = company_role_snapshot(
        company_approval_status=profile.approval_status,
        user=target_user,
    )
    profile.approval_status = COMPANY_APPROVAL_DISABLED
    profile.rejection_reason = _clean_reason(payload.reason)
    bump_auth_version(target_user)
    await _commit_company_audit(
        db=db,
        actor=current_user,
        target=target_user,
        profile=profile,
        action=ACTION_COMPANY_DISABLED,
        reason=_clean_reason(payload.reason) or "Admin disabled company profile.",
        previous_state=before,
    )
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


def _analysis_reproducibility_summary(
    analysis: TenderAnalysis,
    version: AnalysisVersion | None,
) -> dict[str, Any]:
    if version is None:
        return {
            "analysis_id": str(analysis.id),
            "created_at": analysis.created_at.isoformat(),
            "analysis_status": "integrity_anomaly",
            "version_number": None,
            "version_integrity": "ZERO_VERSION_PARENT",
            "content_hash": None,
            "override_seal": analysis.override_seal,
            "coverage_metadata": None,
            "reproducibility_snapshot": None,
            "extraction_artifacts_metadata": [],
            "requirement_fingerprints": _bucket_fingerprints({}),
            "requirement_route_summary": [],
        }

    analysis_data = version.result_snapshot or {}
    hybrid_compliance = analysis_data.get("hybrid_compliance")
    if not isinstance(hybrid_compliance, dict):
        hybrid_compliance = {}
    snapshot = analysis_data.get("reproducibility_snapshot")
    snapshot_routes = []
    if isinstance(snapshot, dict):
        raw_routes = snapshot.get("requirement_route_summary") or []
        snapshot_routes = [item for item in raw_routes if isinstance(item, dict)]

    integrity = verify_analysis_version_integrity(version)
    return {
        "analysis_id": str(analysis.id),
        "created_at": version.created_at.isoformat(),
        "analysis_status": analysis_data.get("analysis_status", "completed"),
        "version_number": version.version_number,
        "version_integrity": integrity.overall_status,
        "content_hash": version.input_hash,
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

    analysis_summaries: list[dict[str, Any]] = []
    for analysis in analyses:
        version = await get_latest_analysis_version_for_parent(
            db,
            analysis_id=analysis.id,
        )
        if version is None:
            logger.error(
                "analysis_version_zero_version_anomaly analysis_id=%s "
                "route=admin_reproducibility",
                analysis.id,
            )
        analysis_summaries.append(
            _analysis_reproducibility_summary(analysis, version)
        )

    return {
        "tender_id": str(tender.id),
        "source_system": tender.source_system,
        "external_id": tender.external_id,
        "latest_analyses": analysis_summaries,
    }
