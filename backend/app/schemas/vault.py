from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.geography import normalize_target_countries, normalize_target_regions
from app.core.services import normalize_target_service, normalize_target_services
from app.models.company import READINESS_DOCUMENT_STATUSES, READINESS_DOCUMENT_TYPES


class CertificationItem(BaseModel):
    id: UUID | None = None
    cert_type: str
    issue_date: date
    expiry_date: date

    model_config = {"from_attributes": True}


class LicenseItem(BaseModel):
    id: UUID | None = None
    license_name: str
    is_active: bool

    model_config = {"from_attributes": True}


class FinancialHistoryItem(BaseModel):
    id: UUID | None = None
    year: int
    turnover_uzs: int

    model_config = {"from_attributes": True}


class CompanyVaultResponse(BaseModel):
    id: UUID
    user_id: UUID

    # Root company profile fields
    company_name: str | None = None
    director_name: str | None = None
    address: str | None = None
    phone_contact: str | None = None
    bank_name: str | None = None
    mfo: str | None = None
    account_number: str | None = None
    inn: str | None = None
    industry: str | None = None
    website: str | None = None
    target_regions: list[str] | None = None
    target_countries: list[str] | None = None
    target_services: list[str] | None = None
    notes: str | None = None
    pilot_status: str | None = None
    approval_status: str | None = None

    # Nested collections
    certifications: list[CertificationItem] = Field(default_factory=list)
    licenses: list[LicenseItem] = Field(default_factory=list)
    financial_history: list[FinancialHistoryItem] = Field(default_factory=list)

    @field_validator("target_regions")
    @classmethod
    def _normalize_response_target_regions(cls, value: list[str] | None) -> list[str] | None:
        return normalize_target_regions(value, reject_invalid=False)

    @field_validator("target_countries")
    @classmethod
    def _normalize_response_target_countries(cls, value: list[str] | None) -> list[str] | None:
        return normalize_target_countries(value, reject_invalid=False)

    @field_validator("target_services")
    @classmethod
    def _normalize_response_target_services(cls, value: list[str] | None) -> list[str] | None:
        return normalize_target_services(value, reject_invalid=False)

    model_config = {"from_attributes": True}


class CertificationUpdate(BaseModel):
    cert_type: str
    issue_date: date
    expiry_date: date


class LicenseUpdate(BaseModel):
    license_name: str
    is_active: bool


class FinancialHistoryUpdate(BaseModel):
    year: int
    turnover_uzs: int


class CompanyVaultUpdate(BaseModel):
    # Root company profile fields
    company_name: str | None = None
    director_name: str | None = None
    address: str | None = None
    phone_contact: str | None = None
    bank_name: str | None = None
    mfo: str | None = None
    account_number: str | None = None
    inn: str | None = None
    industry: str | None = None
    website: str | None = None
    target_regions: list[str] | None = None
    target_countries: list[str] | None = None
    target_services: list[str] | None = None
    notes: str | None = None

    # Nested collections
    certifications: list[CertificationUpdate] = Field(default_factory=list)
    licenses: list[LicenseUpdate] = Field(default_factory=list)
    financial_history: list[FinancialHistoryUpdate] = Field(default_factory=list)

    @field_validator("target_regions")
    @classmethod
    def _validate_target_regions(cls, value: list[str] | None) -> list[str] | None:
        return normalize_target_regions(value)

    @field_validator("target_countries")
    @classmethod
    def _validate_target_countries(cls, value: list[str] | None) -> list[str] | None:
        return normalize_target_countries(value)

    @field_validator("target_services")
    @classmethod
    def _validate_target_services(cls, value: list[str] | None) -> list[str] | None:
        return normalize_target_services(value)


class ReadinessDocumentBase(BaseModel):
    document_type: str
    document_name: str
    document_number: str | None = None
    issuer: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    status: str = "unknown"
    related_service: str | None = None
    notes: str | None = None
    optional_file_url: str | None = None

    @field_validator(
        "document_type",
        "document_name",
        "document_number",
        "issuer",
        "status",
        "related_service",
        "notes",
        "optional_file_url",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("document_type")
    @classmethod
    def _validate_document_type(cls, value: str | None) -> str:
        if value not in READINESS_DOCUMENT_TYPES:
            raise ValueError("Invalid readiness document type")
        return value

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str | None) -> str:
        normalized = value or "unknown"
        if normalized not in READINESS_DOCUMENT_STATUSES:
            raise ValueError("Invalid readiness document status")
        return normalized

    @field_validator("related_service")
    @classmethod
    def _validate_related_service(cls, value: str | None) -> str | None:
        return normalize_target_service(value)

    @field_validator("document_name")
    @classmethod
    def _validate_document_name(cls, value: str | None) -> str:
        if not value:
            raise ValueError("Document name is required")
        return value


class ReadinessDocumentCreate(ReadinessDocumentBase):
    pass


class ReadinessDocumentUpdate(BaseModel):
    document_type: str | None = None
    document_name: str | None = None
    document_number: str | None = None
    issuer: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    status: str | None = None
    related_service: str | None = None
    notes: str | None = None
    optional_file_url: str | None = None

    @field_validator(
        "document_type",
        "document_name",
        "document_number",
        "issuer",
        "status",
        "related_service",
        "notes",
        "optional_file_url",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("document_type")
    @classmethod
    def _validate_document_type(cls, value: str | None) -> str | None:
        if value is not None and value not in READINESS_DOCUMENT_TYPES:
            raise ValueError("Invalid readiness document type")
        return value

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in READINESS_DOCUMENT_STATUSES:
            raise ValueError("Invalid readiness document status")
        return value

    @field_validator("related_service")
    @classmethod
    def _validate_related_service(cls, value: str | None) -> str | None:
        return normalize_target_service(value)

    @model_validator(mode="after")
    def _validate_required_fields_when_present(self) -> "ReadinessDocumentUpdate":
        if "document_name" in self.model_fields_set and not self.document_name:
            raise ValueError("Document name is required")
        return self


class ReadinessDocumentResponse(ReadinessDocumentBase):
    id: UUID
    company_profile_id: UUID

    model_config = {"from_attributes": True}
