"""Deadline time truth and deadline-derived open status (D1-05b, D1-05c, lenient zones).

Connectors store every deadline as the source's published *wall time* labelled UTC.
Whether that wall time is really UTC depends on the source (see
``SourceDefinition.deadline_time_basis``), so:

* display shows the published wall time unconverted, with its basis;
* every deadline has two instants:
  - ``effective_at`` for countdowns and urgency: never overstates the time left;
  - ``closes_at`` for the open/closed status: never closes a tender early.
  They are equal whenever the zone is known:
  - UTC: the stored instant;
  - EXPLICIT_TZ: the wall time interpreted in the source's zone;
  - COUNTRY_INFERRED: a source without a zone (SOURCE_LOCAL_UNSPECIFIED) whose tender
    country is known: the wall time in that country's capital zone
    (app.core.country_timezones);
  - SOURCE_LOCAL_UNSPECIFIED with no inferable zone: ``effective_at`` is the wall time
    at UTC+14 (the earliest zone on Earth) and ``closes_at`` the wall time at UTC-12
    (the latest). Between the two the tender stays open with
    ``status_reason = DEADLINE_VERIFY_ON_SOURCE`` ("Closing - verify on source");
  - DATE_ONLY: the end of the published date, in the source's zone, else in the
    country's inferred zone, else UTC+14 / UTC-12 as above.
* stored values are never rewritten; sorting still uses the stored column.

The Python functions and the SQL expressions below implement the same rules; tests
compare them on a real PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import json
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Time, and_, case, cast, func, literal, literal_column, or_, text

from app.core.country_timezones import COUNTRY_TIMEZONES, country_timezone
from app.models.base import TenderStatus
from app.services.source_registry import (
    SOURCE_REGISTRY,
    DateOnlyMarker,
    DeadlineTimeBasis,
)

EARLIEST_UTC_OFFSET = timedelta(hours=14)
LATEST_UTC_OFFSET = timedelta(hours=12)
DEADLINE_PASSED = "DEADLINE_PASSED"
DEADLINE_VERIFY_ON_SOURCE = "DEADLINE_VERIFY_ON_SOURCE"
_MARKER_TIMES = {DateOnlyMarker.END_OF_DAY: time.max, DateOnlyMarker.MIDNIGHT: time(0, 0)}
_UNKNOWN_ZONE_BASES = frozenset({DeadlineTimeBasis.SOURCE_LOCAL_UNSPECIFIED, DeadlineTimeBasis.DATE_ONLY})


@dataclass(frozen=True)
class DeadlineTime:
    """One tender deadline as customers may see it."""

    basis: DeadlineTimeBasis | None
    timezone: str | None
    published_local: str | None  # "YYYY-MM-DDTHH:MM" or "YYYY-MM-DD" (DATE_ONLY), never converted
    effective_at: datetime | None  # earliest possible instant: countdowns and urgency
    closes_at: datetime | None  # latest possible instant: open/closed status


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


def deadline_time(
    source_system: str | None,
    deadline: datetime | None,
    *,
    country: str | None = None,
) -> DeadlineTime:
    """The deadline's basis, zone and instants.

    ``country`` (the tender's country) is used only for sources that publish no zone.
    Callers that must stay byte-stable (the official notice header) omit it.
    """
    basis, zone = source_deadline_basis(source_system)
    if deadline is None:
        return DeadlineTime(None, None, None, None, None)
    wall = _as_utc(deadline).replace(tzinfo=None)
    inferred = country_timezone(country) if zone is None and basis in _UNKNOWN_ZONE_BASES else None
    if _is_date_only(source_system, wall):
        day_end = datetime.combine(wall.date(), time(0, 0)) + timedelta(days=1)
        known = zone or inferred
        if known:
            instant = day_end.replace(tzinfo=ZoneInfo(known)).astimezone(timezone.utc)
            return DeadlineTime(DeadlineTimeBasis.DATE_ONLY, known, wall.date().isoformat(), instant, instant)
        at_utc = day_end.replace(tzinfo=timezone.utc)
        return DeadlineTime(
            DeadlineTimeBasis.DATE_ONLY, None, wall.date().isoformat(),
            at_utc - EARLIEST_UTC_OFFSET, at_utc + LATEST_UTC_OFFSET,
        )
    published = wall.strftime("%Y-%m-%dT%H:%M")
    if basis is DeadlineTimeBasis.UTC:
        instant = wall.replace(tzinfo=timezone.utc)
        return DeadlineTime(basis, "UTC", published, instant, instant)
    if basis is DeadlineTimeBasis.EXPLICIT_TZ and zone:
        instant = wall.replace(tzinfo=ZoneInfo(zone)).astimezone(timezone.utc)
        return DeadlineTime(basis, zone, published, instant, instant)
    if inferred:
        instant = wall.replace(tzinfo=ZoneInfo(inferred)).astimezone(timezone.utc)
        return DeadlineTime(DeadlineTimeBasis.COUNTRY_INFERRED, inferred, published, instant, instant)
    at_utc = wall.replace(tzinfo=timezone.utc)
    return DeadlineTime(
        DeadlineTimeBasis.SOURCE_LOCAL_UNSPECIFIED, None, published,
        at_utc - EARLIEST_UTC_OFFSET, at_utc + LATEST_UTC_OFFSET,
    )


def effective_deadline(source_system: str | None, deadline: datetime | None, *, country: str | None = None) -> datetime | None:
    return deadline_time(source_system, deadline, country=country).effective_at


def closing_deadline(source_system: str | None, deadline: datetime | None, *, country: str | None = None) -> datetime | None:
    return deadline_time(source_system, deadline, country=country).closes_at


def deadline_passed(
    source_system: str | None,
    deadline: datetime | None,
    *,
    now: datetime | None = None,
    country: str | None = None,
) -> bool:
    """True once the deadline has passed in every zone it could be in (status semantics)."""
    closes = closing_deadline(source_system, deadline, country=country)
    return closes is not None and closes < _as_utc(now or datetime.now(timezone.utc))


def derived_status(
    status: Any,
    source_system: str | None,
    deadline: datetime | None,
    *,
    now: datetime | None = None,
    country: str | None = None,
) -> tuple[TenderStatus, str | None]:
    """Customer-facing lifecycle.

    A deadline that has passed everywhere closes an OPEN/UNKNOWN tender
    (DEADLINE_PASSED). One that has passed only in some possible zones leaves it
    open with DEADLINE_VERIFY_ON_SOURCE.
    """
    raw = str(getattr(status, "value", status) or "").strip().upper()
    try:
        stored = TenderStatus(raw)
    except ValueError:
        stored = TenderStatus.UNKNOWN
    if stored not in {TenderStatus.OPEN, TenderStatus.UNKNOWN}:
        return stored, None
    truth = deadline_time(source_system, deadline, country=country)
    if truth.closes_at is None:
        return stored, None
    reference = _as_utc(now or datetime.now(timezone.utc))
    if truth.closes_at < reference:
        return TenderStatus.CLOSED, DEADLINE_PASSED
    if truth.effective_at is not None and truth.effective_at < reference:
        return stored, DEADLINE_VERIFY_ON_SOURCE
    return stored, None


# ---- SQL -------------------------------------------------------------------------

# The country -> zone table as one constant JSONB literal: parsed once per statement at
# plan time, and a single keyed lookup per row (no bind parameter to re-parse).
_COUNTRY_ZONES_JSONB = literal_column(
    "'" + json.dumps(dict(COUNTRY_TIMEZONES), sort_keys=True, ensure_ascii=False).replace("'", "''") + "'::jsonb"
)


def country_timezone_sql(tender_model: Any):
    """PostgreSQL expression equal to ``country_timezone(tender.country)`` (NULL when unknown)."""
    return _COUNTRY_ZONES_JSONB.op("->>")(func.lower(func.btrim(tender_model.country)))


def _instant_sql(tender_model: Any, *, latest: bool):
    wall = func.timezone("UTC", tender_model.deadline)  # timestamp without time zone
    day_end = func.date_trunc("day", wall) + text("interval '1 day'")
    offset = text("interval '12 hours'") if latest else text("interval '-14 hours'")
    at_unknown = func.timezone("UTC", wall) + offset
    day_end_at_unknown = func.timezone("UTC", day_end) + offset
    inferred = country_timezone_sql(tender_model)
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
            if zone:
                value = func.timezone(zone, day_end)
            elif definition.deadline_time_basis in _UNKNOWN_ZONE_BASES:
                value = func.coalesce(func.timezone(inferred, day_end), day_end_at_unknown)
            else:
                value = day_end_at_unknown
            branches.append((and_(is_source, date_only_row), value))
        if definition.deadline_time_basis is DeadlineTimeBasis.UTC:
            branches.append((is_source, func.timezone("UTC", wall)))
        elif definition.deadline_time_basis is DeadlineTimeBasis.EXPLICIT_TZ and zone:
            branches.append((is_source, func.timezone(zone, wall)))
    # Sources without a zone (and unknown sources): the country's zone, else UTC+14/UTC-12.
    return case(*branches, else_=func.coalesce(func.timezone(inferred, wall), at_unknown))


def effective_deadline_sql(tender_model: Any):
    """PostgreSQL expression equal to ``effective_deadline`` for each row (NULL when no deadline)."""
    return _instant_sql(tender_model, latest=False)


def closing_deadline_sql(tender_model: Any):
    """PostgreSQL expression equal to ``closing_deadline`` for each row (NULL when no deadline)."""
    return _instant_sql(tender_model, latest=True)


def _reference(now: datetime | None):
    return literal(_as_utc(now)) if now is not None else func.now()


def deadline_not_passed_sql(tender_model: Any, *, now: datetime | None = None):
    """True when the deadline is unknown or has not passed everywhere (status semantics)."""
    return or_(tender_model.deadline.is_(None), closing_deadline_sql(tender_model) >= _reference(now))


def deadline_passed_sql(tender_model: Any, *, now: datetime | None = None):
    """True when the deadline has passed in every zone it could be in."""
    return and_(tender_model.deadline.is_not(None), closing_deadline_sql(tender_model) < _reference(now))


def deadline_uncertain_sql(tender_model: Any, *, now: datetime | None = None):
    """True in the "verify on source" window: passed in some possible zones, not all."""
    reference = _reference(now)
    return and_(
        tender_model.deadline.is_not(None),
        effective_deadline_sql(tender_model) < reference,
        closing_deadline_sql(tender_model) >= reference,
    )


def truth_fields(
    source_system: str | None,
    stored_status: Any,
    deadline: datetime | None,
    *,
    now: datetime | None = None,
    country: str | None = None,
) -> dict[str, Any]:
    """Values of app.schemas.tender.TenderTruthFields plus the derived ``status``."""
    truth = deadline_time(source_system, deadline, country=country)
    status_value, reason = derived_status(stored_status, source_system, deadline, now=now, country=country)
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
        "deadline_closes_at": truth.closes_at,
    }
