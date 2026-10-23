"""P3: pursuit usage per organization and the extra allowances an admin grants."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OrganizationPursuitUsage(Base):
    """A pursuit counted against the plan: written once, when its first analysis starts."""

    __tablename__ = "organization_pursuit_usage"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pursuit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pursuit_analysis_runs.id", ondelete="RESTRICT")
    )
    plan: Mapped[str] = mapped_column(String(20), nullable=False)
    counted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "pursuit_id", name="uq_pursuit_usage_pursuit"),
        ForeignKeyConstraint(
            ["pursuit_id", "organization_id"],
            ["organization_pursuits.id", "organization_pursuits.organization_id"],
            name="fk_pursuit_usage_pursuit_organization", ondelete="RESTRICT",
        ),
        Index("ix_pursuit_usage_organization_counted", "organization_id", "counted_at"),
    )


class OrganizationPlanGrant(Base):
    """Extra pursuits or introductions for one plan period, granted by an admin (audited)."""

    __tablename__ = "organization_plan_grants"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("kind IN ('PURSUITS','INTRODUCTIONS')", name="ck_plan_grant_kind"),
        CheckConstraint("quantity BETWEEN 1 AND 1000", name="ck_plan_grant_quantity"),
        CheckConstraint("length(trim(reason)) >= 3", name="ck_plan_grant_reason"),
        Index("ix_plan_grants_organization_period", "organization_id", "period_start"),
    )
