"""
Audit router for Sovereign Audit Trail actions.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.audit_trail import record_audit_action
from app.db.session import get_db
from app.schemas.audit import RiskAuthorizationRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/authorize")
async def authorize_risk(
    request: RiskAuthorizationRequest,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Record a mitigation authorization into the cryptographic ledger.

    The cryptographic chain logic is intentionally delegated to core service code.
    """
    try:
        audit_log = await record_audit_action(
            session=session,
            analysis_id=request.analysis_id,
            user_id=request.user_id,
            risk_type=request.risk_type,
        )
        return {
            "status": "success",
            "message": "Risk authorization recorded in audit ledger.",
            "current_hash": audit_log.current_hash,
            "timestamp": audit_log.timestamp.isoformat(),
        }
    except Exception as exc:
        logger.exception("Failed to record audit action")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record audit action: {exc}",
        ) from exc

