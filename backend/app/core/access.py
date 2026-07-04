"""Access-control constants and small helpers for pilot approvals."""

from __future__ import annotations

from typing import Iterable

USER_APPROVAL_PENDING = "pending"
USER_APPROVAL_APPROVED = "approved"
USER_APPROVAL_REJECTED = "rejected"
USER_APPROVAL_DISABLED = "disabled"
USER_APPROVAL_STATUSES = (
    USER_APPROVAL_PENDING,
    USER_APPROVAL_APPROVED,
    USER_APPROVAL_REJECTED,
    USER_APPROVAL_DISABLED,
)

PLATFORM_ROLE_ADMIN = "admin"
PLATFORM_ROLE_OPERATOR = "operator"
PLATFORM_ROLE_PILOT_USER = "pilot_user"
PLATFORM_ROLES = (
    PLATFORM_ROLE_ADMIN,
    PLATFORM_ROLE_OPERATOR,
    PLATFORM_ROLE_PILOT_USER,
)

COMPANY_PILOT_LEAD = "lead"
COMPANY_PILOT_SCOPED = "scoped_pilot"
COMPANY_PILOT_ACTIVE = "active_pilot"
COMPANY_PILOT_AT_RISK = "at_risk"
COMPANY_PILOT_CONVERTED = "converted"
COMPANY_PILOT_PAUSED = "paused"
COMPANY_PILOT_STATUSES = (
    COMPANY_PILOT_LEAD,
    COMPANY_PILOT_SCOPED,
    COMPANY_PILOT_ACTIVE,
    COMPANY_PILOT_AT_RISK,
    COMPANY_PILOT_CONVERTED,
    COMPANY_PILOT_PAUSED,
)

COMPANY_APPROVAL_PENDING = USER_APPROVAL_PENDING
COMPANY_APPROVAL_APPROVED = USER_APPROVAL_APPROVED
COMPANY_APPROVAL_REJECTED = USER_APPROVAL_REJECTED
COMPANY_APPROVAL_DISABLED = USER_APPROVAL_DISABLED
COMPANY_APPROVAL_STATUSES = USER_APPROVAL_STATUSES


def sql_string_values(values: Iterable[str]) -> str:
    """Return a SQL-safe comma list for static check constraints."""
    return ", ".join(f"'{value}'" for value in values)


def parse_email_allowlist(raw_emails: str | None) -> set[str]:
    """Parse comma-separated email allowlists consistently."""
    return {
        email.strip().lower()
        for email in (raw_emails or "").split(",")
        if email.strip()
    }
