"""
Plasma AI - Database Models

Defines all SQLAlchemy ORM models for the Autonomous Tender Officer SaaS platform.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, ProposalStatus, SubscriptionTier, TenderStatus


# ============================================================================
# Models
# ============================================================================


class Tender(Base):
    """
    Public procurement tenders from UzEx/Etender.
    The core feed that users interact with.
    """
    
    __tablename__ = "tenders"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    external_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Aggregated NLP-ready text compiled from scraped/parsed documents.
    compiled_master_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="UZS", nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[TenderStatus] = mapped_column(
        Enum(TenderStatus, name="tender_status"),
        default=TenderStatus.OPEN,
        nullable=False,
    )
    category: Mapped[str] = mapped_column(
        String(50),
        default="Other",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    # Relationships
    documents: Mapped[list["TenderDocument"]] = relationship(
        "TenderDocument",
        back_populates="tender",
        cascade="all, delete-orphan",
    )
    proposals: Mapped[list["Proposal"]] = relationship(
        "Proposal",
        back_populates="tender",
        cascade="all, delete-orphan",
    )
    analyses: Mapped[list["TenderAnalysis"]] = relationship(
        "TenderAnalysis",
        back_populates="tender",
        cascade="all, delete-orphan",
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_tenders_external_id", "external_id"),
        Index("ix_tenders_status", "status"),
        Index("ix_tenders_deadline", "deadline"),
    )


class TenderDocument(Base):
    """
    Documents attached to tenders.
    Contains parsed text for AI processing.
    """
    
    __tablename__ = "tender_documents"
    
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
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    parsed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    # Relationships
    tender: Mapped["Tender"] = relationship(
        "Tender",
        back_populates="documents",
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_tender_documents_tender_id", "tender_id"),
    )


class Proposal(Base):
    """
    AI-generated proposals for tenders.
    The core value proposition of the platform.
    """
    
    __tablename__ = "proposals"
    
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
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus, name="proposal_status"),
        default=ProposalStatus.DRAFT,
        nullable=False,
    )
    ai_confidence_score: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    structured_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    final_pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    # Financial fields
    margin_percent: Mapped[float] = mapped_column(
        Float,
        default=20.0,
        nullable=False,
    )
    include_vat: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(10),
        default="UZS",
        nullable=False,
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="proposals",
    )
    tender: Mapped["Tender"] = relationship(
        "Tender",
        back_populates="proposals",
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_proposals_user_id", "user_id"),
        Index("ix_proposals_tender_id", "tender_id"),
        Index("ix_proposals_status", "status"),
    )


# Import modular models so Alembic autogenerate sees the full metadata graph.
from app.models.audit import AuditLog, TenderAnalysis, TenderRecommendation  # noqa: E402,F401
from app.models.company import Certification, CompanyProfile, FinancialHistory, License  # noqa: E402,F401
from app.models.taxonomy import (  # noqa: E402,F401
    CompanyCredential,
    RiskOverrideLog,
    TaxonomyCategory,
    TaxonomyNode,
    TenderRequirement,
)
from app.models.user import User  # noqa: E402,F401


__all__ = [
    "Base",
    "SubscriptionTier",
    "TenderStatus",
    "ProposalStatus",
    "User",
    "Tender",
    "TenderDocument",
    "Proposal",
    "CompanyProfile",
    "Certification",
    "License",
    "FinancialHistory",
    "TaxonomyCategory",
    "TaxonomyNode",
    "CompanyCredential",
    "TenderRequirement",
    "RiskOverrideLog",
    "TenderAnalysis",
    "TenderRecommendation",
    "AuditLog",
]
