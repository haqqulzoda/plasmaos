"""
Audit router for Sovereign Audit Trail actions.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_approved_pilot_access
from app.core.security.audit_trail import record_audit_action
from app.db.session import get_db
from app.models.all_models import User
from app.models.audit import TenderAnalysis
from app.models.company import CompanyProfile
from app.schemas.audit import RiskAuthorizationRequest

logger = logging.getLogger(__name__)

router = APIRouter()


def _analysis_owner_key(
    *,
    current_user: User,
    profile: CompanyProfile | None,
) -> str:
    profile_token = str(profile.id) if profile is not None else "no-profile"
    return f"{current_user.id}:{profile_token}"


@router.post("/authorize")
async def authorize_risk(
    request: RiskAuthorizationRequest,
    current_user: User = Depends(require_approved_pilot_access),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Record a mitigation authorization into the cryptographic ledger.

    The cryptographic chain logic is intentionally delegated to core service code.
    """
    try:
        profile_result = await session.execute(
            select(CompanyProfile).where(CompanyProfile.user_id == current_user.id)
        )
        profile = profile_result.scalar_one_or_none()
        owner_key = _analysis_owner_key(current_user=current_user, profile=profile)

        analysis_result = await session.execute(
            select(TenderAnalysis.id).where(
                TenderAnalysis.id == request.analysis_id,
                TenderAnalysis.company_name == owner_key,
            )
        )
        if analysis_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Analysis not found",
            )

        audit_log = await record_audit_action(
            session=session,
            analysis_id=request.analysis_id,
            user_id=str(current_user.id),
            risk_type=request.risk_type,
        )
        return {
            "status": "success",
            "message": "Risk authorization recorded in audit ledger.",
            "current_hash": audit_log.current_hash,
            "timestamp": audit_log.timestamp.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to record audit action")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record audit action: {exc}",
        ) from exc
