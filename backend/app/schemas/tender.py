"""
Plasma AI - Tender Schemas

Pydantic models for tender API requests and responses.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

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
    source_system: str = "uzex"
    canonical_source_key: str
    source_url: str | None = None
    country: str | None = None
    sector: str | None = None
    buyer: str | None = None
    procurement_category: str | None = None
    procurement_method: str | None = None
    notice_type: str | None = None
    project_id: str | None = None
    publication_date: datetime | None = None
    price_amount: float | None = None
    price_currency: str | None = None
    price_display: str | None = None
    has_compiled_text: bool = False
    document_status: str = "no_documents_found"
    document_count: int = 0
    available_document_count: int = 0
    metadata_only_document_count: int = 0
    failed_document_count: int = 0
    compliance_analysis_available: bool = False
    compliance_unavailable_reason: str | None = None
    created_at: datetime
    
    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def populate_price_fields(self) -> "TenderResponse":
        if self.price_amount is not None or self.price_display is not None:
            return self
        try:
            amount = float(self.budget or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if amount <= 0:
            self.price_amount = None
            self.price_currency = None
            self.price_display = None
            return self

        currency = (self.currency or "").strip().upper() or None
        amount_display = f"{amount:,.2f}".rstrip("0").rstrip(".")
        self.price_amount = amount
        self.price_currency = currency
        self.price_display = (
            f"{amount_display} {currency}" if currency else amount_display
        )
        return self


class TenderDocumentResponse(BaseModel):
    """Safe tender document metadata for frontend previews."""

    id: UUID
    file_type: str
    display_name: str
    download_url: str
    download_status: str = "metadata_only"
    original_filename: str | None = None
    storage_filename: str | None = None
    parsed_source_filenames: list[str] = Field(default_factory=list)
    archive_inner_filenames: list[str] = Field(default_factory=list)
    file_size: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
