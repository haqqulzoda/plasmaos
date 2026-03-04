from __future__ import annotations

import enum
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class TaxonomyCategory(str, enum.Enum):
    """Top-level compliance taxonomy categories."""

    LICENSE = "LICENSE"
    CERTIFICATION = "CERTIFICATION"
    FINANCIAL = "FINANCIAL"
    ESG = "ESG"
    TECHNICAL = "TECHNICAL"
    PERSONNEL = "PERSONNEL"


class TaxonomyNode(Base):
    """Canonical compliance requirement node."""

    __tablename__ = "taxonomy_nodes"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    category: Mapped[TaxonomyCategory] = mapped_column(
        Enum(TaxonomyCategory, name="taxonomy_category"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact_weight: Mapped[int] = mapped_column(Integer, nullable=False)
    is_fatal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    company_credentials: Mapped[list["CompanyCredential"]] = relationship(
        "CompanyCredential",
        back_populates="taxonomy_node",
        cascade="all, delete-orphan",
    )
    tender_requirements: Mapped[list["TenderRequirement"]] = relationship(
        "TenderRequirement",
        back_populates="taxonomy_node",
        cascade="all, delete-orphan",
    )
    missing_in_overrides: Mapped[list["RiskOverrideLog"]] = relationship(
        "RiskOverrideLog",
        back_populates="missing_node",
    )

    __table_args__ = (
        CheckConstraint(
            "impact_weight >= 0 AND impact_weight <= 100",
            name="ck_taxonomy_nodes_impact_weight_range",
        ),
        Index("ix_taxonomy_nodes_category", "category"),
        Index("ix_taxonomy_nodes_name", "name", unique=True),
    )


class CompanyCredential(Base):
    """Credential currently held by a company profile."""

    __tablename__ = "company_credentials"

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
    taxonomy_node_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("taxonomy_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    company_profile: Mapped["CompanyProfile"] = relationship("CompanyProfile")
    taxonomy_node: Mapped["TaxonomyNode"] = relationship(
        "TaxonomyNode",
        back_populates="company_credentials",
    )

    __table_args__ = (
        UniqueConstraint(
            "company_profile_id",
            "taxonomy_node_id",
            name="uq_company_credentials_profile_taxonomy_node",
        ),
        Index("ix_company_credentials_company_profile_id", "company_profile_id"),
        Index("ix_company_credentials_taxonomy_node_id", "taxonomy_node_id"),
    )


class TenderRequirement(Base):
    """Taxonomy requirement extracted for a specific tender."""

    __tablename__ = "tender_requirements"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tender_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenders.id", ondelete="CASCADE"),
        nullable=False,
    )
    taxonomy_node_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("taxonomy_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    tender: Mapped["Tender"] = relationship("Tender")
    taxonomy_node: Mapped["TaxonomyNode"] = relationship(
        "TaxonomyNode",
        back_populates="tender_requirements",
    )

    __table_args__ = (
        UniqueConstraint(
            "tender_id",
            "taxonomy_node_id",
            name="uq_tender_requirements_tender_taxonomy_node",
        ),
        Index("ix_tender_requirements_tender_id", "tender_id"),
        Index("ix_tender_requirements_taxonomy_node_id", "taxonomy_node_id"),
    )


class RiskOverrideLog(Base):
    """Append-only liability handshake ledger."""

    __tablename__ = "risk_override_logs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    tender_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenders.id", ondelete="CASCADE"),
        nullable=False,
    )
    analysis_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tender_analyses.id", ondelete="CASCADE"),
        nullable=True,
    )
    missing_node_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("taxonomy_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User")
    tender: Mapped["Tender"] = relationship("Tender")
    analysis: Mapped["TenderAnalysis"] = relationship("TenderAnalysis")
    missing_node: Mapped["TaxonomyNode"] = relationship(
        "TaxonomyNode",
        back_populates="missing_in_overrides",
    )

    __table_args__ = (
        Index("ix_risk_override_logs_user_id", "user_id"),
        Index("ix_risk_override_logs_tender_id", "tender_id"),
        Index("ix_risk_override_logs_analysis_id", "analysis_id"),
        Index("ix_risk_override_logs_missing_node_id", "missing_node_id"),
        Index("ix_risk_override_logs_created_at", "created_at"),
    )
