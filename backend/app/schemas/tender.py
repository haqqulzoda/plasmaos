"""
Plasma AI - Tender Schemas

Pydantic models for tender API requests and responses.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

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
    source_url: str | None = None
    created_at: datetime
    
    model_config = {"from_attributes": True}


class TenderDocumentResponse(BaseModel):
    """Safe tender document metadata for frontend previews."""

    id: UUID
    file_url: str
    file_type: str
    display_name: str
    original_filename: str | None = None
    storage_filename: str | None = None
    parsed_source_filenames: list[str] = Field(default_factory=list)
    archive_inner_filenames: list[str] = Field(default_factory=list)
    file_size: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
