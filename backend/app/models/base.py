import enum
from typing import Any

from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all database models."""

    type_annotation_map = {
        dict[str, Any]: JSON,
    }


class SubscriptionTier(str, enum.Enum):
    """User subscription tiers."""

    SCOUT = "SCOUT"
    AGENT = "AGENT"
    ENTERPRISE = "ENTERPRISE"


class TenderStatus(str, enum.Enum):
    """Status of tenders."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class ProposalStatus(str, enum.Enum):
    """Status of proposals."""

    DRAFT = "DRAFT"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    SUBMITTED = "SUBMITTED"


class TenderEngagementStatus(str, enum.Enum):
    """A company's explicit lifecycle state for one tender opportunity."""

    SAVED = "SAVED"
    EVALUATING = "EVALUATING"
    PREPARING = "PREPARING"
    SUBMITTED = "SUBMITTED"
    WON = "WON"
    LOST = "LOST"
    DISMISSED = "DISMISSED"


class TenderEngagementOrigin(str, enum.Enum):
    """The immutable reason an engagement first entered the workspace."""

    MANUAL_SAVE = "MANUAL_SAVE"
    MANUAL_EVALUATION = "MANUAL_EVALUATION"
    BID_PREPARATION = "BID_PREPARATION"
    LEGACY_PROPOSAL = "LEGACY_PROPOSAL"
    OTHER_EXPLICIT_USER_ACTION = "OTHER_EXPLICIT_USER_ACTION"
