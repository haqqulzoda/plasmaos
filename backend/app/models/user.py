from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.access import (
    PLATFORM_ROLE_PILOT_USER,
    PLATFORM_ROLES,
    USER_APPROVAL_PENDING,
    USER_APPROVAL_STATUSES,
    sql_string_values,
)
from app.models.base import Base, SubscriptionTier


class User(Base):
    """
    Users authenticated via Google OAuth 2.0.
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    google_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Company Profile Fields (for PDF generation)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    director_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone_contact: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfo: Mapped[str | None] = mapped_column(String(10), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    inn: Mapped[str | None] = mapped_column(String(15), nullable=True)

    # SaaS Tier
    subscription_tier: Mapped[SubscriptionTier] = mapped_column(
        Enum(SubscriptionTier, name="subscription_tier"),
        default=SubscriptionTier.SCOUT,
        nullable=False,
    )

    # Admin flag for Concierge upsell
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    approval_status: Mapped[str] = mapped_column(
        String(20),
        default=USER_APPROVAL_PENDING,
        server_default=text(f"'{USER_APPROVAL_PENDING}'"),
        nullable=False,
    )
    platform_role: Mapped[str] = mapped_column(
        String(30),
        default=PLATFORM_ROLE_PILOT_USER,
        server_default=text(f"'{PLATFORM_ROLE_PILOT_USER}'"),
        nullable=False,
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
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    proposals: Mapped[list["Proposal"]] = relationship(
        "Proposal",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    company_profile: Mapped["CompanyProfile | None"] = relationship(
        "CompanyProfile",
        back_populates="user",
        foreign_keys="CompanyProfile.user_id",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # Indexes
    __table_args__ = (
        CheckConstraint(
            f"approval_status IN ({sql_string_values(USER_APPROVAL_STATUSES)})",
            name="ck_users_approval_status_allowed",
        ),
        CheckConstraint(
            f"platform_role IN ({sql_string_values(PLATFORM_ROLES)})",
            name="ck_users_platform_role_allowed",
        ),
        Index("ix_users_google_id", "google_id"),
        Index("ix_users_email", "email"),
        Index("ix_users_approval_status", "approval_status"),
        Index("ix_users_platform_role", "platform_role"),
    )
