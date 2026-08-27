"""Customer-safe AnalysisVersion read schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AnalysisVersionIntegrityResponse(BaseModel):
    overall_status: Literal["VERIFIED", "PARTIAL", "MISMATCH"]
    output_hash_status: Literal["VERIFIED", "MISMATCH", "NOT_AVAILABLE"]
    evidence_hash_status: Literal["VERIFIED", "MISMATCH", "NOT_AVAILABLE"]
    document_set_hash_status: Literal["VERIFIED", "MISMATCH", "NOT_AVAILABLE"]
    version_hash_status: Literal["VERIFIED", "MISMATCH", "NOT_AVAILABLE"]
    snapshot_completeness: Literal["COMPLETE", "PARTIAL", "LEGACY_BACKFILL"]
    missing_fields: list[str] = Field(default_factory=list)


class AnalysisVersionMetadataResponse(BaseModel):
    analysis_id: UUID
    version_number: int
    supersedes_version_id: UUID | None = None
    origin: str
    status: str
    snapshot_completeness: str
    analysis_schema_version: str | None = None
    pipeline_version: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    prompt_template_version: str | None = None
    prompt_template_hash: str | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    evidence_hash: str | None = None
    document_set_hash: str | None = None
    version_hash: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class AnalysisVersionDocumentResponse(BaseModel):
    source_system: str
    source_document_key: str | None = None
    source_url: str | None = None
    filename: str | None = None
    media_type: str | None = None
    content_hash: str | None = None
    fetched_at: datetime | None = None
    observed_at: datetime | None = None
    snapshot_availability: Literal["HASHED", "METADATA_ONLY", "UNKNOWN"]


class AnalysisVersionDetailResponse(BaseModel):
    metadata: AnalysisVersionMetadataResponse
    result_snapshot: dict[str, Any]
    evidence_snapshot: dict[str, Any]
    tender_snapshot: dict[str, Any]
    company_snapshot: dict[str, Any]
    provenance: dict[str, Any]
    documents: list[AnalysisVersionDocumentResponse] = Field(default_factory=list)
    integrity: AnalysisVersionIntegrityResponse
