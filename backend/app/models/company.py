from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


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

    user: Mapped["User"] = relationship(
        "User",
        back_populates="company_profile",
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

    __table_args__ = (
        Index("ix_company_profiles_user_id", "user_id", unique=True),
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
