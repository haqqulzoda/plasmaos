"""D2-05 Expression of Interest contracts (frontend session B builds against these)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EoiLocator(BaseModel):
    page_number: int | None = None
    paragraph_number: int | None = None


class EoiDefaults(BaseModel):
    assignment_title: str
    reference_no: str
    addressee_organization: str
    addressee_name: str | None = None
    addressee_email: str | None = None
    firm_name: str
    firm_country: str | None = None


class EoiCriterion(BaseModel):
    requirement_id: UUID
    statement: str
    original_quote: str
    locator: EoiLocator
    effective_coverage_state: str
    matched_reference_ids: list[UUID] = Field(default_factory=list)


class EoiNote(BaseModel):
    requirement_id: UUID
    note_kind: str
    statement: str
    original_quote: str


class EoiReference(BaseModel):
    reference_id: UUID
    project_name: str
    client_name: str | None = None
    country: str | None = None
    sector: str | None = None
    service: str | None = None
    role: str
    contract_share_percent: Decimal | None = None
    contract_value: Decimal | None = None
    contract_currency: str | None = None
    value_basis: str
    start_date: date | None = None
    completion_date: date | None = None
    completion_state: str
    relevant_scope: str | None = None
    evidence_state: str
    evidence_basis: str
    matched_requirement_ids: list[UUID] = Field(default_factory=list)
    suggested: bool
    rank: int


class EoiPartnerFirm(BaseModel):
    firm_id: UUID
    display_name: str
    country: str | None = None
    references: list[EoiReference] = Field(default_factory=list)
    covers_requirement_ids: list[UUID] = Field(default_factory=list)


class EoiSuggestionsResponse(BaseModel):
    analysis_run_id: UUID
    run_current: bool
    defaults: EoiDefaults
    criteria: list[EoiCriterion] = Field(default_factory=list)
    notes: list[EoiNote] = Field(default_factory=list)
    own_references: list[EoiReference] = Field(default_factory=list)
    partner_firms: list[EoiPartnerFirm] = Field(default_factory=list)


def _unique(values: list[UUID]) -> list[UUID]:
    if len(set(values)) != len(values):
        raise ValueError("duplicate ids are not allowed")
    return values


def _required_text(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("must not be blank")
    return value


class EoiPartnerSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    firm_id: UUID
    role: Literal["JV_MEMBER", "SUBCONSULTANT"]
    reference_ids: list[UUID] = Field(default_factory=list, max_length=15)

    @field_validator("reference_ids")
    @classmethod
    def unique_references(cls, value: list[UUID]) -> list[UUID]:
        return _unique(value)


class EoiLetter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    addressee_organization: str = Field(min_length=2, max_length=500)
    addressee_name: str | None = Field(default=None, max_length=300)
    signatory_name: str = Field(min_length=2, max_length=300)
    signatory_title: str = Field(min_length=2, max_length=300)
    contact_email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    contact_phone: str | None = Field(default=None, max_length=100)
    contact_address: str | None = Field(default=None, max_length=1000)

    @field_validator("addressee_organization", "signatory_name", "signatory_title")
    @classmethod
    def required_text(cls, value: str) -> str:
        return _required_text(value)


class EoiDraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_run_id: UUID
    language: Literal["en", "ru"]
    own_reference_ids: list[UUID] = Field(min_length=1, max_length=30)
    partners: list[EoiPartnerSelection] = Field(default_factory=list, max_length=5)
    letter: EoiLetter
    include_relevance_notes: bool = True

    @field_validator("own_reference_ids")
    @classmethod
    def unique_own(cls, value: list[UUID]) -> list[UUID]:
        return _unique(value)

    @model_validator(mode="after")
    def distinct_partners(self):
        firm_ids = [partner.firm_id for partner in self.partners]
        if len(set(firm_ids)) != len(firm_ids):
            raise ValueError("a partner firm can be selected once")
        return self


class EoiArtifactResponse(BaseModel):
    artifact_id: UUID
    format: Literal["DOCX", "PDF"]
    sha256: str
    byte_size: int


class EoiDraftSummary(BaseModel):
    criteria_total: int
    criteria_with_references: int
    criteria_without_references: int
    own_reference_count: int
    partner_count: int
    relevance_notes_generated: int
    relevance_notes_dropped: int


class EoiDraftResponse(BaseModel):
    draft_id: UUID
    version: int
    created_at: datetime
    created_by_membership_id: UUID
    analysis_run_id: UUID
    language: str
    current: bool
    stale_reasons: list[str] = Field(default_factory=list)
    artifacts: list[EoiArtifactResponse] = Field(default_factory=list)
    summary: EoiDraftSummary
