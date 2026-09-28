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


class MembershipRole(str, enum.Enum):
    """Organization-scoped authorization role."""

    OWNER = "OWNER"
    MEMBER = "MEMBER"


class MembershipState(str, enum.Enum):
    """Durable membership lifecycle state."""

    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class PursuitOrigin(str, enum.Enum):
    """Authority that established a pursuit identity."""

    SOURCE = "SOURCE"
    UPLOAD = "UPLOAD"


class PrivateDocumentRole(str, enum.Enum):
    """Controlled role of an organization-private tender document."""

    RFP = "RFP"
    TOR = "TOR"
    NOTICE = "NOTICE"
    ADDENDUM = "ADDENDUM"
    CLARIFICATION = "CLARIFICATION"
    FORM = "FORM"
    ANNEX = "ANNEX"
    OTHER = "OTHER"


class PrivateDocumentState(str, enum.Enum):
    """Logical lifecycle of a private document identity."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class DocumentProcessingState(str, enum.Enum):
    """Truthful durable state for private document processing."""

    UPLOADING = "UPLOADING"
    QUEUED = "QUEUED"
    CHECKING = "CHECKING"
    EXTRACTING = "EXTRACTING"
    READY = "READY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class PursuitAnalysisStatus(str, enum.Enum):
    """Durable lifecycle for a sealed pursuit analysis run."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CoverageState(str, enum.Enum):
    """Reviewed W4 coverage semantics, separate from legacy Compliance."""

    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    GAP = "GAP"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    NEEDS_INTERPRETATION = "NEEDS_INTERPRETATION"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    LATER_STAGE_OBLIGATION = "LATER_STAGE_OBLIGATION"
