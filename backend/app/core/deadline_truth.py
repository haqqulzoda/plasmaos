"""Deadline time truth and deadline-derived open status (D1-05b, D1-05c).

Connectors store every deadline as the source's published *wall time* labelled UTC.
Whether that wall time is really UTC depends on the source (see
``SourceDefinition.deadline_time_basis``), so:

* display shows the published wall time unconverted, with its basis;
* countdowns, urgency and open/closed use one conservative *effective instant*
  that never overstates the time left:
  - UTC: the stored instant;
  - EXPLICIT_TZ: the wall time interpreted in the source's zone;
  - SOURCE_LOCAL_UNSPECIFIED: the wall time at UTC+14 (the earliest zone on Earth);
  - DATE_ONLY: the end of the published date, in the source's zone when known,
    else at UTC+14.
* stored values are never rewritten; sorting still uses the stored column.

The Python functions and the SQL expressions below implement the same rules; tests
compare them on a real PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Time, and_, case, cast, func, literal, or_, text

from app.models.base import TenderStatus
from app.services.source_registry import (
    SOURCE_REGISTRY,
    DateOnlyMarker,
    DeadlineTimeBasis,
)

EARLIEST_UTC_OFFSET = timedelta(hours=14)
DEADLINE_PASSED = "DEADLINE_PASSED"
_MARKER_TIMES = {DateOnlyMarker.END_OF_DAY: time.max, DateOnlyMarker.MIDNIGHT: time(0, 0)}


@dataclass(frozen=True)
class DeadlineTime:
    """One tender deadline as customers may see it."""

    basis: DeadlineTimeBasis | None
    timezone: str | None
    published_local: str | None  # "YYYY-MM-DDTHH:MM" or "YYYY-MM-DD" (DATE_ONLY), never converted
    effective_at: datetime | None  # conservative UTC instant for countdown/urgency/open status


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _definition(source_system: str | None):
    return SOURCE_REGISTRY.get(str(source_system or "").strip().casefold())


def source_deadline_basis(source_system: str | None) -> tuple[DeadlineTimeBasis, str | None]:
    """Registry basis of a source; unknown sources are treated as unspecified local time."""
    definition = _definition(source_system)
    if definition is None:
        return DeadlineTimeBasis.SOURCE_LOCAL_UNSPECIFIED, None
    return definition.deadline_time_basis, definition.deadline_timezone


def _is_date_only(source_system: str | None, wall: datetime) -> bool:
    definition = _definition(source_system)
    if definition is None:
        return False
    if definition.deadline_time_basis is DeadlineTimeBasis.DATE_ONLY:
        return True
    marker = definition.deadline_date_only_marker
    return marker is not None and wall.time() == _MARKER_TIMES[marker]


def deadline_time(source_system: str | None, deadline: datetime | None) -> DeadlineTime:
    basis, zone = source_deadline_basis(source_system)
    if deadline is None:
        return DeadlineTime(None, None, None, None)
    wall = _as_utc(deadline).replace(tzinfo=None)
    if _is_date_only(source_system, wall):
        day_end = datetime.combine(wall.date(), time(0, 0)) + timedelta(days=1)
        effective = (
            day_end.replace(tzinfo=ZoneInfo(zone)).astimezone(timezone.utc)
            if zone
            else day_end.replace(tzinfo=timezone.utc) - EARLIEST_UTC_OFFSET
        )
        return DeadlineTime(DeadlineTimeBasis.DATE_ONLY, zone, wall.date().isoformat(), effective)
    published = wall.strftime("%Y-%m-%dT%H:%M")
    if basis is DeadlineTimeBasis.UTC:
        return DeadlineTime(basis, "UTC", published, wall.replace(tzinfo=timezone.utc))
    if basis is DeadlineTimeBasis.EXPLICIT_TZ and zone:
        return DeadlineTime(basis, zone, published, wall.replace(tzinfo=ZoneInfo(zone)).astimezone(timezone.utc))
    return DeadlineTime(
        DeadlineTimeBasis.SOURCE_LOCAL_UNSPECIFIED, None, published,
        wall.replace(tzinfo=timezone.utc) - EARLIEST_UTC_OFFSET,
    )


def effective_deadline(source_system: str | None, deadline: datetime | None) -> datetime | None:
    return deadline_time(source_system, deadline).effective_at


def deadline_passed(source_system: str | None, deadline: datetime | None, *, now: datetime | None = None) -> bool:
    effective = effective_deadline(source_system, deadline)
    return effective is not None and effective < _as_utc(now or datetime.now(timezone.utc))


def derived_status(
    status: Any,
    source_system: str | None,
    deadline: datetime | None,
    *,
    now: datetime | None = None,
) -> tuple[TenderStatus, str | None]:
    """Customer-facing lifecycle: a passed deadline closes an OPEN/UNKNOWN tender."""
    raw = str(getattr(status, "value", status) or "").strip().upper()
    try:
        stored = TenderStatus(raw)
    except ValueError:
        stored = TenderStatus.UNKNOWN
    if stored in {TenderStatus.OPEN, TenderStatus.UNKNOWN} and deadline_passed(source_system, deadline, now=now):
        return TenderStatus.CLOSED, DEADLINE_PASSED
    return stored, None


# ---- SQL -------------------------------------------------------------------------


def effective_deadline_sql(tender_model: Any):
    """PostgreSQL expression equal to ``effective_deadline`` for each row (NULL when no deadline)."""
    wall = func.timezone("UTC", tender_model.deadline)  # timestamp without time zone
    day_end = func.date_trunc("day", wall) + text("interval '1 day'")
    at_earliest = func.timezone("UTC", wall) - text("interval '14 hours'")
    day_end_at_earliest = func.timezone("UTC", day_end) - text("interval '14 hours'")
    branches = []
    for key, definition in SOURCE_REGISTRY.items():
        zone = definition.deadline_timezone
        is_source = tender_model.source_system == key
        marker = definition.deadline_date_only_marker
        date_only_row = (
            literal(True)
            if definition.deadline_time_basis is DeadlineTimeBasis.DATE_ONLY
            else (cast(wall, Time) == literal(_MARKER_TIMES[marker], Time())) if marker is not None else None
        )
        if date_only_row is not None:
            branches.append((
                and_(is_source, date_only_row),
                func.timezone(zone, day_end) if zone else day_end_at_earliest,
            ))
        if definition.deadline_time_basis is DeadlineTimeBasis.UTC:
            branches.append((is_source, func.timezone("UTC", wall)))
        elif definition.deadline_time_basis is DeadlineTimeBasis.EXPLICIT_TZ and zone:
            branches.append((is_source, func.timezone(zone, wall)))
    return case(*branches, else_=at_earliest)


def deadline_not_passed_sql(tender_model: Any, *, now: datetime | None = None):
    """True when the deadline is unknown or its effective instant has not passed."""
    reference = literal(_as_utc(now)) if now is not None else func.now()
    return or_(tender_model.deadline.is_(None), effective_deadline_sql(tender_model) >= reference)


def deadline_passed_sql(tender_model: Any, *, now: datetime | None = None):
    reference = literal(_as_utc(now)) if now is not None else func.now()
    return and_(tender_model.deadline.is_not(None), effective_deadline_sql(tender_model) < reference)


def truth_fields(
    source_system: str | None,
    stored_status: Any,
    deadline: datetime | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Values of app.schemas.tender.TenderTruthFields plus the derived ``status``."""
    truth = deadline_time(source_system, deadline)
    status_value, reason = derived_status(stored_status, source_system, deadline, now=now)
    raw = str(getattr(stored_status, "value", stored_status) or "").strip().upper()
    try:
        source_status = TenderStatus(raw)
    except ValueError:
        source_status = TenderStatus.UNKNOWN
    return {
        "status": status_value,
        "source_status": source_status,
        "status_reason": reason,
        "deadline_time_basis": truth.basis.value if truth.basis is not None else None,
        "deadline_timezone": truth.timezone,
        "deadline_published_local": truth.published_local,
        "deadline_effective_at": truth.effective_at,
    }
