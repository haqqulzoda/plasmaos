"""Internal API-ready schemas for canonical Projects and leadership roles."""

from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ProjectRoleAssignmentResponse(BaseModel):
    id: UUID
    role_type: Literal["PROJECT_LEADERSHIP"] = "PROJECT_LEADERSHIP"
    source_system: str
    source_person_id: str | None = None
    display_name: str
    native_role: str
    canonical_role: str
    email: str | None = None
    phone: str | None = None
    source_url: str | None = None
    source_document_id: str | None = None
    provenance: dict
    is_current: bool
    first_observed_at: datetime
    last_observed_at: datetime
    ended_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProjectResponse(BaseModel):
    id: UUID
    source_system: str
    external_project_id: str
    name: str | None = None
    country: str | None = None
    region: str | None = None
    project_status: str | None = None
    approval_date: date | None = None
    closing_date: date | None = None
    borrower: str | None = None
    implementing_agencies: list[str] | None = None
    source_url: str | None = None
    enrichment_status: str
    enrichment_last_attempted_at: datetime | None = None
    last_enriched_at: datetime | None = None
    roles: list[ProjectRoleAssignmentResponse] = Field(
        default_factory=list,
        validation_alias="role_assignments",
    )

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def expose_stale_success(self) -> "ProjectResponse":
        if self.enrichment_status != "successful" or self.last_enriched_at is None:
            return self
        enriched_at = self.last_enriched_at
        if enriched_at.tzinfo is None:
            enriched_at = enriched_at.replace(tzinfo=timezone.utc)
        if enriched_at < datetime.now(timezone.utc) - timedelta(days=7):
            self.enrichment_status = "stale"
        return self


class ProjectContextRoleResponse(BaseModel):
    """Presentation-safe Project leadership evidence for Tender Details."""

    role_type: Literal["PROJECT_LEADERSHIP"] = "PROJECT_LEADERSHIP"
    source_system: str
    display_name: str
    native_role: str
    canonical_role: str
    email: str | None = None
    phone: str | None = None
    source_url: str | None = None
    first_observed_at: datetime
    last_observed_at: datetime
    ended_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProjectContextProjectResponse(BaseModel):
    """Source-neutral, whitelisted Project context exposed through a Tender."""

    id: UUID
    source_system: str
    external_project_id: str
    name: str | None = None
    country: str | None = None
    region: str | None = None
    status: str | None = Field(default=None, validation_alias="project_status")
    approval_date: date | None = None
    closing_date: date | None = None
    borrower: str | None = None
    implementing_agencies: list[str] | None = None
    source_url: str | None = None
    enrichment_status: str
    last_successful_enrichment_at: datetime | None = Field(
        default=None,
        validation_alias="last_enriched_at",
    )
    source_freshness: Literal[
        "fresh",
        "stale",
        "incomplete",
        "unavailable",
        "pending",
    ] = "pending"

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def derive_source_freshness(self) -> "ProjectContextProjectResponse":
        status = self.enrichment_status
        if status == "successful":
            enriched_at = self.last_successful_enrichment_at
            if enriched_at is None:
                self.source_freshness = "incomplete"
                return self
            if enriched_at.tzinfo is None:
                enriched_at = enriched_at.replace(tzinfo=timezone.utc)
            if enriched_at < datetime.now(timezone.utc) - timedelta(days=7):
                self.enrichment_status = "stale"
                self.source_freshness = "stale"
            else:
                self.source_freshness = "fresh"
        elif status == "stale":
            self.source_freshness = "stale"
        elif status == "partial":
            self.source_freshness = "incomplete"
        elif status in {"source_unavailable", "failed"}:
            self.source_freshness = "unavailable"
        else:
            self.source_freshness = "pending"
        return self


class TenderProjectContextResponse(BaseModel):
    """Canonical Project and separately classified current/history roles."""

    project: ProjectContextProjectResponse
    current_roles: list[ProjectContextRoleResponse] = Field(default_factory=list)
    historical_roles: list[ProjectContextRoleResponse] = Field(default_factory=list)
