"""Canonical company/user engagement with a tender opportunity."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    TenderEngagementOrigin,
    TenderEngagementStatus,
)


class TenderEngagement(Base):
    """One current, explicitly owned engagement per user/profile/tender scope."""

    __tablename__ = "tender_engagements"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    company_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    tender_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[TenderEngagementStatus] = mapped_column(
        Enum(TenderEngagementStatus, name="tender_engagement_status"),
        nullable=False,
    )
    origin: Mapped[TenderEngagementOrigin] = mapped_column(
        Enum(TenderEngagementOrigin, name="tender_engagement_origin"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", viewonly=True)
    company_profile: Mapped["CompanyProfile"] = relationship(
        "CompanyProfile",
        viewonly=True,
    )
    tender: Mapped["Tender"] = relationship("Tender", viewonly=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["company_profile_id", "user_id"],
            ["company_profiles.id", "company_profiles.user_id"],
            name="fk_tender_engagements_profile_user",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "company_profile_id",
            "tender_id",
            name="uq_tender_engagements_owner_tender",
        ),
        Index("ix_tender_engagements_user_id", "user_id"),
        Index("ix_tender_engagements_company_profile_id", "company_profile_id"),
        Index("ix_tender_engagements_tender_id", "tender_id"),
        Index("ix_tender_engagements_status", "status"),
    )


# Type-only names are resolved by SQLAlchemy's registry at mapper configuration.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.all_models import Tender
    from app.models.company import CompanyProfile
    from app.models.user import User
