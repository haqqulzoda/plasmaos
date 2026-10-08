"""R3 email invitations to an organization, bound to a verified Google e-mail at sign-in."""

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
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, MembershipRole


INVITATION_TTL_DAYS = 14


class PendingInvitation(Base):
    """One OWNER-issued invitation for an exact lower-case e-mail address.

    Only the SHA-256 of the one-time token is stored. An invitation is open while it is
    neither accepted, revoked nor expired; at most one unaccepted, unrevoked row exists per
    organization and e-mail.
    """

    __tablename__ = "pending_invitations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, name="membership_role", create_type=False), nullable=False
    )
    invited_by_membership_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text(f"now() + interval '{INVITATION_TTL_DAYS} days'"),
    )
    send_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"), default=1)
    last_sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    accepted_membership_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("memberships.id", ondelete="RESTRICT"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["invited_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_pending_invitation_inviter_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "email = lower(email) AND email = btrim(email) AND email ~ '^[^@\\s]+@[^@\\s]+$'",
            name="ck_pending_invitation_email",
        ),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_pending_invitation_token_hash"),
        CheckConstraint("send_count >= 1", name="ck_pending_invitation_send_count"),
        CheckConstraint(
            "NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_pending_invitation_terminal",
        ),
        CheckConstraint(
            "(accepted_at IS NULL) = (accepted_membership_id IS NULL)",
            name="ck_pending_invitation_accepted_membership",
        ),
        Index(
            "uq_pending_invitation_open_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
        Index(
            "ix_pending_invitations_email_open",
            "email",
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
        Index("ix_pending_invitations_organization_created", "organization_id", "created_at"),
    )
