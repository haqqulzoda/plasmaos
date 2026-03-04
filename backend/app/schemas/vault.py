from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


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

    # Nested collections
    certifications: list[CertificationItem] = Field(default_factory=list)
    licenses: list[LicenseItem] = Field(default_factory=list)
    financial_history: list[FinancialHistoryItem] = Field(default_factory=list)

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

    # Nested collections
    certifications: list[CertificationUpdate] = Field(default_factory=list)
    licenses: list[LicenseUpdate] = Field(default_factory=list)
    financial_history: list[FinancialHistoryUpdate] = Field(default_factory=list)
