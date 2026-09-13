"""Bounded, plain-text communications contracts; system payloads are structured."""

from datetime import datetime
from enum import Enum
import re
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Category(str, Enum):
    SYSTEM = "SYSTEM"
    TENDER_ALERT = "TENDER_ALERT"
    ADMIN = "ADMIN"


class MessageType(str, Enum):
    ANNOUNCEMENT = "ANNOUNCEMENT"
    SYSTEM_ALERT = "SYSTEM_ALERT"


class AudienceMode(str, Enum):
    ALL_ELIGIBLE_USERS = "ALL_ELIGIBLE_USERS"
    SELECTED_USERS = "SELECTED_USERS"


class BroadcastStatus(str, Enum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    SENDING = "SENDING"
    SENT = "SENT"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


def validate_plain_text(value: str) -> str:
    # Reject active markup rather than sanitize or silently rewrite authored text.
    if (
        not value.strip()
        or re.search(
            r"<\s*/?\s*[a-z!]|(?:javascript|vbscript|data)\s*:|\bon\w+\s*=", value, re.I
        )
        or "\x00" in value
    ):
        raise ValueError("communications_unsafe_content")
    return value


class BroadcastCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    message_type: MessageType = MessageType.ANNOUNCEMENT
    audience_mode: AudienceMode = AudienceMode.ALL_ELIGIBLE_USERS
    selected_user_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    _safe_content = field_validator("subject", "body")(validate_plain_text)

    @model_validator(mode="after")
    def audience_consistent(self):
        self.selected_user_ids = list(dict.fromkeys(self.selected_user_ids))
        if (
            self.audience_mode == AudienceMode.ALL_ELIGIBLE_USERS
            and self.selected_user_ids
        ):
            raise ValueError("communications_invalid_audience")
        return self


class BroadcastPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=5000)
    message_type: MessageType | None = None
    audience_mode: AudienceMode | None = None
    selected_user_ids: list[UUID] | None = Field(default=None, max_length=1000)

    @field_validator("subject", "body")
    @classmethod
    def safe_content(cls, value):
        return validate_plain_text(value) if value is not None else value

    @model_validator(mode="after")
    def reject_null_updates(self):
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("communications_null_update")
        return self


class DeliveryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_read: bool = Field(strict=True)


class TestSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID = Field(default_factory=uuid4)


class NotificationItem(BaseModel):
    id: UUID
    event_id: UUID
    category: Category
    event_type: str
    template_key: str | None
    payload: dict
    subject: str | None
    body: str | None
    message_type: MessageType | None
    content_format: str = "plain_text"
    is_test: bool
    created_at: datetime
    read_at: datetime | None
    is_read: bool


class NotificationPage(BaseModel):
    items: list[NotificationItem]
    next_cursor: str | None


class BroadcastItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    subject: str
    body: str
    message_type: MessageType
    content_format: str = "plain_text"
    audience_mode: AudienceMode
    selected_user_count: int
    status: BroadcastStatus
    recipient_count: int
    delivered_count: int
    failed_count: int
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime
    queued_at: datetime | None
    completed_at: datetime | None


class BroadcastSummary(BaseModel):
    id: UUID
    subject: str
    message_type: MessageType
    audience_mode: AudienceMode
    status: BroadcastStatus
    recipient_count: int
    delivered_count: int
    failed_count: int
    created_at: datetime
    updated_at: datetime


class BroadcastPage(BaseModel):
    items: list[BroadcastSummary]
    next_cursor: str | None
