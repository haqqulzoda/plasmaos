"""
Plasma AI - Tender Schemas

Pydantic models for tender API requests and responses.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.all_models import TenderStatus


class TenderBase(BaseModel):
    """Base schema for tender data."""
    title: str
    description: str | None = None
    budget: float
    currency: str = "UZS"
    deadline: datetime | None = None
    region: str | None = None
    status: TenderStatus = TenderStatus.OPEN
    category: str = "Other"


class TenderResponse(TenderBase):
    """Response schema for tender details."""
    id: UUID
    external_id: str
    source_url: str
    created_at: datetime
    
    model_config = {"from_attributes": True}

