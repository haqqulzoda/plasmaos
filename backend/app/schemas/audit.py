"""
Schemas for audit trail API requests.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class RiskAuthorizationRequest(BaseModel):
    """
    Payload sent by frontend when a user authorizes mitigation for a risk.
    """

    analysis_id: UUID
    risk_type: str
    user_id: str

