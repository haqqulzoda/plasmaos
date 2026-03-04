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


class ProposalStatus(str, enum.Enum):
    """Status of proposals."""

    DRAFT = "DRAFT"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    SUBMITTED = "SUBMITTED"
