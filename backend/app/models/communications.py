"""Communications content, per-user state, frozen audiences and publication intents."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Broadcast(Base):
    __tablename__ = "broadcasts"
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(String(24), nullable=False)
    audience_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    selected_user_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="DRAFT", server_default="DRAFT"
    )
    recipient_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    delivered_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    next_dispatch_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','QUEUED','SENDING','SENT','PARTIAL','FAILED')",
            name="ck_broadcast_status",
        ),
        CheckConstraint(
            "message_type IN ('ANNOUNCEMENT','SYSTEM_ALERT')",
            name="ck_broadcast_message_type",
        ),
        CheckConstraint(
            "audience_mode IN ('ALL_ELIGIBLE_USERS','SELECTED_USERS')",
            name="ck_broadcast_audience",
        ),
        CheckConstraint(
            "length(subject) BETWEEN 1 AND 200 AND length(body) BETWEEN 1 AND 5000",
            name="ck_broadcast_content_size",
        ),
        CheckConstraint(
            "jsonb_typeof(selected_user_ids) = 'array' AND jsonb_array_length(selected_user_ids) <= 1000",
            name="ck_broadcast_selected_size",
        ),
        CheckConstraint(
            "recipient_count >= 0 AND delivered_count >= 0 AND failed_count >= 0 AND delivered_count + failed_count <= recipient_count AND retry_count >= 0",
            name="ck_broadcast_counts",
        ),
        Index("ix_broadcast_created", created_at.desc(), id.desc()),
        Index(
            "ix_broadcast_dispatch",
            "next_dispatch_at",
            postgresql_where=text("status IN ('QUEUED','SENDING')"),
        ),
    )


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    template_key: Mapped[str | None] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    broadcast_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="RESTRICT")
    )
    subject: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    message_type: Mapped[str | None] = mapped_column(String(24))
    is_test: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("id", "category", name="uq_notification_event_category"),
        CheckConstraint(
            "category IN ('SYSTEM','TENDER_ALERT','ADMIN')",
            name="ck_notification_category",
        ),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 4096",
            name="ck_notification_payload_size",
        ),
        CheckConstraint(
            "(broadcast_id IS NULL AND template_key IS NOT NULL AND subject IS NULL AND body IS NULL AND message_type IS NULL AND NOT is_test) OR (broadcast_id IS NOT NULL AND category = 'ADMIN' AND template_key IS NULL AND subject IS NOT NULL AND length(subject) BETWEEN 1 AND 200 AND body IS NOT NULL AND length(body) BETWEEN 1 AND 5000 AND message_type IN ('ANNOUNCEMENT','SYSTEM_ALERT'))",
            name="ck_notification_content_authority",
        ),
    )


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint(
            "user_id", "event_id", name="uq_notification_delivery_user_event"
        ),
        ForeignKeyConstraint(
            ["event_id", "category"],
            ["notification_events.id", "notification_events.category"],
            ondelete="CASCADE",
            name="fk_delivery_event_category",
        ),
        Index("ix_notification_inbox", "user_id", created_at.desc(), id.desc()),
        Index(
            "ix_notification_category_inbox",
            "user_id",
            "category",
            created_at.desc(),
            id.desc(),
        ),
        Index(
            "ix_notification_unread_count",
            "user_id",
            postgresql_where=text("read_at IS NULL"),
        ),
        Index(
            "ix_notification_unread",
            "user_id",
            "category",
            created_at.desc(),
            id.desc(),
            postgresql_where=text("read_at IS NULL"),
        ),
    )


class BroadcastRecipient(Base):
    __tablename__ = "broadcast_recipients"
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    broadcast_id: Mapped[UUID] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default="PENDING"
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("broadcast_id", "user_id", name="uq_broadcast_recipient_user"),
        CheckConstraint(
            "status IN ('PENDING','DELIVERED','FAILED')",
            name="ck_broadcast_recipient_status",
        ),
        Index(
            "ix_broadcast_pending",
            "broadcast_id",
            "id",
            postgresql_where=text("status = 'PENDING'"),
        ),
    )


class NotificationOutbox(Base):
    """Small committed publication intent; contains IDs, never message corpora."""

    __tablename__ = "notification_outbox"
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    template_key: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 4096",
            name="ck_notification_outbox_payload_size",
        ),
        Index(
            "ix_notification_outbox_pending",
            "created_at",
            "id",
            postgresql_where=text("published_at IS NULL"),
        ),
    )
