from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.access import (
    COMPANY_APPROVAL_PENDING,
    COMPANY_APPROVAL_STATUSES,
    COMPANY_PILOT_SCOPED,
    COMPANY_PILOT_STATUSES,
    sql_string_values,
)
from app.models.base import Base

READINESS_DOCUMENT_TYPES = (
    "license",
    "certificate",
    "tax_clearance",
    "financial_statement",
    "registration_document",
    "power_of_attorney",
    "personnel_document",
    "other",
)
READINESS_DOCUMENT_STATUSES = (
    "available",
    "missing",
    "expired",
    "unknown",
)


class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Root company profile fields
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    director_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone_contact: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfo: Mapped[str | None] = mapped_column(String(10), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    inn: Mapped[str | None] = mapped_column(String(15), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    target_regions: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    target_countries: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    target_services: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    pilot_status: Mapped[str] = mapped_column(
        String(30),
        default=COMPANY_PILOT_SCOPED,
        server_default=text(f"'{COMPANY_PILOT_SCOPED}'"),
        nullable=False,
    )
    approval_status: Mapped[str] = mapped_column(
        String(20),
        default=COMPANY_APPROVAL_PENDING,
        server_default=text(f"'{COMPANY_APPROVAL_PENDING}'"),
        nullable=False,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    approved_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(
        "User",
        back_populates="company_profile",
        foreign_keys=[user_id],
    )
    certifications: Mapped[list["Certification"]] = relationship(
        "Certification",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    licenses: Mapped[list["License"]] = relationship(
        "License",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    financial_history: Mapped[list["FinancialHistory"]] = relationship(
        "FinancialHistory",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    readiness_documents: Mapped[list["ReadinessDocument"]] = relationship(
        "ReadinessDocument",
        back_populates="company_profile",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            f"pilot_status IN ({sql_string_values(COMPANY_PILOT_STATUSES)})",
            name="ck_company_profiles_pilot_status_allowed",
        ),
        CheckConstraint(
            f"approval_status IN ({sql_string_values(COMPANY_APPROVAL_STATUSES)})",
            name="ck_company_profiles_approval_status_allowed",
        ),
        Index("ix_company_profiles_user_id", "user_id", unique=True),
        Index("ix_company_profiles_approval_status", "approval_status"),
        Index("ix_company_profiles_pilot_status", "pilot_status"),
    )


class Certification(Base):
    __tablename__ = "certifications"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("company_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    cert_type: Mapped[str] = mapped_column(String(100), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)

    company: Mapped["CompanyProfile"] = relationship(
        "CompanyProfile",
        back_populates="certifications",
    )

    __table_args__ = (
        Index("ix_certifications_company_id", "company_id"),
    )


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("company_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    license_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    company: Mapped["CompanyProfile"] = relationship(
        "CompanyProfile",
        back_populates="licenses",
    )

    __table_args__ = (
        Index("ix_licenses_company_id", "company_id"),
    )


class FinancialHistory(Base):
    __tablename__ = "financial_history"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("company_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    turnover_uzs: Mapped[int] = mapped_column(BigInteger, nullable=False)

    company: Mapped["CompanyProfile"] = relationship(
        "CompanyProfile",
        back_populates="financial_history",
    )

    __table_args__ = (
        UniqueConstraint("company_id", "year", name="uq_financial_history_company_year"),
        Index("ix_financial_history_company_id", "company_id"),
        Index("ix_financial_history_year", "year"),
    )


class ReadinessDocument(Base):
    __tablename__ = "readiness_documents"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    company_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("company_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default="unknown",
        server_default=text("'unknown'"),
        nullable=False,
    )
    related_service: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    optional_file_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    company_profile: Mapped["CompanyProfile"] = relationship(
        "CompanyProfile",
        back_populates="readiness_documents",
    )

    __table_args__ = (
        CheckConstraint(
            f"document_type IN ({sql_string_values(READINESS_DOCUMENT_TYPES)})",
            name="ck_readiness_documents_type_allowed",
        ),
        CheckConstraint(
            f"status IN ({sql_string_values(READINESS_DOCUMENT_STATUSES)})",
            name="ck_readiness_documents_status_allowed",
        ),
        Index("ix_readiness_documents_company_profile_id", "company_profile_id"),
        Index("ix_readiness_documents_document_type", "document_type"),
        Index("ix_readiness_documents_status", "status"),
    )
