"""
Plasma AI - Proposal Schemas

Pydantic models for proposal API requests and responses.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.all_models import ProposalStatus, TenderStatus


class ProposalCreate(BaseModel):
    """Request body for creating a proposal."""
    tender_id: UUID


class ProposalItemUpdate(BaseModel):
    """Schema for updating a single proposal item."""
    name: str
    unit: str
    quantity: float
    base_cost: float  # Cost per unit before margin


class ProposalUpdate(BaseModel):
    """Request body for updating proposal data."""
    structured_data: dict[str, Any] | None = None
    our_price: float | None = None
    delivery_days: int | None = None
    # Financial fields
    items: list[ProposalItemUpdate] | None = None
    margin_percent: float | None = None
    include_vat: bool | None = None


class ProposalResponse(BaseModel):
    """Response schema for proposal details."""
    id: UUID
    user_id: UUID
    tender_id: UUID
    status: ProposalStatus
    ai_confidence_score: int
    structured_data: dict[str, Any] | None
    final_pdf_url: str | None
    margin_percent: float
    include_vat: bool
    currency: str
    created_at: datetime
    
    model_config = {"from_attributes": True}


class ProposalWithTenderResponse(ProposalResponse):
    """Response schema including tender details."""
    tender_title: str
    tender_budget: float
    tender_currency: str
    tender_deadline: datetime | None
    tender_region: str | None
    tender_source_system: str = "uzex"
    tender_status: TenderStatus
