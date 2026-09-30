"""Shared tender lifecycle semantics for current-action workflows."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.deadline_truth import deadline_not_passed_sql, derived_status
from app.models.base import TenderStatus


TENDER_NOT_ACTIONABLE_DETAIL = (
    "Tender is not currently actionable. Only OPEN tenders can start a new "
    "compliance or bid workflow."
)


def actionable_tender_condition(tender_model: Any, *, now: datetime | None = None) -> Any:
    """SQL predicate for an affirmatively actionable tender.

    The stored source status must be OPEN *and* the deadline, read conservatively
    for its source (app.core.deadline_truth), must not have passed (D1-05c).
    """
    return (tender_model.status == TenderStatus.OPEN) & deadline_not_passed_sql(tender_model, now=now)


def is_tender_actionable(tender: Any, *, now: datetime | None = None) -> bool:
    """True only for an OPEN tender whose deadline has not passed.

    A bare status (str or TenderStatus) carries no deadline and is judged on status alone.
    """
    if isinstance(tender, (str, TenderStatus)):
        raw_status = getattr(tender, "value", tender)
        return str(raw_status or "").strip().upper() == TenderStatus.OPEN.value
    status, _reason = derived_status(
        getattr(tender, "status", None),
        getattr(tender, "source_system", None),
        getattr(tender, "deadline", None),
        now=now,
    )
    return status is TenderStatus.OPEN


def lifecycle_condition(tender_model: Any, lifecycle_status: TenderStatus, *, now: datetime | None = None) -> Any:
    """SQL filter for a customer lifecycle value, derived from the deadline (D1-05c).

    OPEN is the actionable set; CLOSED includes OPEN/UNKNOWN rows whose deadline has
    passed; UNKNOWN excludes them; CANCELLED is the stored value.
    """
    from sqlalchemy import and_, or_

    from app.core.deadline_truth import deadline_passed_sql

    if lifecycle_status == TenderStatus.OPEN:
        return actionable_tender_condition(tender_model, now=now)
    if lifecycle_status == TenderStatus.CLOSED:
        return or_(
            tender_model.status == TenderStatus.CLOSED,
            and_(
                tender_model.status.in_((TenderStatus.OPEN, TenderStatus.UNKNOWN)),
                deadline_passed_sql(tender_model, now=now),
            ),
        )
    if lifecycle_status == TenderStatus.UNKNOWN:
        return and_(tender_model.status == TenderStatus.UNKNOWN, deadline_not_passed_sql(tender_model, now=now))
    return tender_model.status == lifecycle_status
