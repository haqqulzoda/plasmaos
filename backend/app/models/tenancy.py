"""Organization tenancy and canonical pursuit ownership models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    MembershipRole,
    MembershipState,
    PursuitOrigin,
    TenderEngagementOrigin,
    TenderEngagementStatus,
)


class Organization(Base):
    """Canonical private tenancy root for one legacy company profile."""

    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    legacy_company_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("company_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    memberships: Mapped[list["Membership"]] = relationship(
        "Membership", back_populates="organization", passive_deletes=True
    )
    pursuits: Mapped[list["OrganizationPursuit"]] = relationship(
        "OrganizationPursuit", back_populates="organization", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_organizations_legacy_profile", "legacy_company_profile_id", unique=True),
    )


class Membership(Base):
    """One durable organization/user relationship."""

    __tablename__ = "memberships"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, name="membership_role"), nullable=False
    )
    state: Mapped[MembershipState] = mapped_column(
        Enum(MembershipState, name="membership_state"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship("Organization", back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_memberships_organization_user"),
        UniqueConstraint("id", "organization_id", name="uq_memberships_id_organization"),
        CheckConstraint(
            "(state = 'ACTIVE' AND activated_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(state = 'INVITED' AND activated_at IS NULL AND revoked_at IS NULL) OR "
            "(state = 'REVOKED' AND revoked_at IS NOT NULL)",
            name="ck_memberships_lifecycle_timestamps",
        ),
        Index("ix_memberships_user_state", "user_id", "state"),
        Index("ix_memberships_organization_state", "organization_id", "state"),
    )


class OrganizationPursuit(Base):
    """Canonical organization-owned lifecycle for a source or uploaded opportunity."""

    __tablename__ = "organization_pursuits"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_tender_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenders.id", ondelete="RESTRICT"), nullable=True
    )
    origin: Mapped[PursuitOrigin] = mapped_column(
        Enum(PursuitOrigin, name="pursuit_origin"), nullable=False
    )
    legacy_engagement_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, unique=True
    )
    legacy_origin: Mapped[TenderEngagementOrigin | None] = mapped_column(
        Enum(TenderEngagementOrigin, name="tender_engagement_origin", create_type=False),
        nullable=True,
    )
    owner_membership_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    stage: Mapped[TenderEngagementStatus] = mapped_column(
        Enum(TenderEngagementStatus, name="tender_engagement_status", create_type=False),
        nullable=False,
    )
    internal_target_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    stage_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped[Organization] = relationship("Organization", back_populates="pursuits")
    source_tender: Mapped["Tender | None"] = relationship("Tender", viewonly=True)
    owner_membership: Mapped[Membership | None] = relationship("Membership", viewonly=True)
    lifecycle_events: Mapped[list["PursuitLifecycleEvent"]] = relationship(
        "PursuitLifecycleEvent", back_populates="pursuit", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_organization_pursuits_id_organization"),
        ForeignKeyConstraint(
            ["owner_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_pursuit_owner_same_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(origin = 'SOURCE' AND source_tender_id IS NOT NULL) OR "
            "(origin = 'UPLOAD' AND source_tender_id IS NULL)",
            name="ck_organization_pursuits_origin_source",
        ),
        CheckConstraint(
            "legacy_engagement_id IS NULL OR origin = 'SOURCE'",
            name="ck_organization_pursuits_legacy_source",
        ),
        CheckConstraint(
            "legacy_engagement_id IS NULL OR legacy_engagement_id <> id",
            name="ck_organization_pursuits_distinct_legacy_id",
        ),
        Index("ix_organization_pursuits_organization_stage", "organization_id", "stage"),
        Index("ix_organization_pursuits_source_tender", "source_tender_id"),
        Index("ix_organization_pursuits_owner", "owner_membership_id"),
        Index(
            "uq_organization_pursuits_source",
            "organization_id",
            "source_tender_id",
            unique=True,
            postgresql_where=(origin == PursuitOrigin.SOURCE),
        ),
    )


class PursuitLifecycleEvent(Base):
    """Append-only record of explicit pursuit lifecycle transitions."""

    __tablename__ = "pursuit_lifecycle_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    pursuit_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization_pursuits.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_membership_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL"), nullable=True
    )
    previous_stage: Mapped[TenderEngagementStatus | None] = mapped_column(
        Enum(TenderEngagementStatus, name="tender_engagement_status", create_type=False),
        nullable=True,
    )
    new_stage: Mapped[TenderEngagementStatus] = mapped_column(
        Enum(TenderEngagementStatus, name="tender_engagement_status", create_type=False),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    pursuit: Mapped[OrganizationPursuit] = relationship(
        "OrganizationPursuit", back_populates="lifecycle_events"
    )

    __table_args__ = (
        Index("ix_pursuit_lifecycle_events_pursuit_created", "pursuit_id", "created_at"),
    )


class TenancyBackfillException(Base):
    """Non-destructive quarantine report for legacy rows that cannot be mapped exactly."""

    __tablename__ = "tenancy_backfill_exceptions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    legacy_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("entity_type", "legacy_id", "reason", name="uq_tenancy_backfill_exception"),
        Index("ix_tenancy_backfill_exceptions_entity", "entity_type", "reason"),
    )


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.all_models import Tender
