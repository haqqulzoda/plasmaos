"""Shared tender lifecycle semantics for current-action workflows."""

from __future__ import annotations

from typing import Any

from app.models.base import TenderStatus


TENDER_NOT_ACTIONABLE_DETAIL = (
    "Tender is not currently actionable. Only OPEN tenders can start a new "
    "compliance or bid workflow."
)


def actionable_tender_condition(tender_model: Any) -> Any:
    """Return the SQL predicate for an affirmatively actionable tender."""
    return tender_model.status == TenderStatus.OPEN


def is_tender_actionable(tender: Any) -> bool:
    """Return true only when a tender has the affirmative OPEN lifecycle state."""
    status = tender if isinstance(tender, (str, TenderStatus)) else getattr(tender, "status", None)
    raw_status = getattr(status, "value", status)
    return str(raw_status or "").strip().upper() == TenderStatus.OPEN.value
