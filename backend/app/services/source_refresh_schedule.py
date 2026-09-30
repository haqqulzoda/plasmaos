"""Scheduled source refresh (D1-04): cadence parsing, Beat entries, due checks, staleness.

``SOURCE_REFRESH_SCHEDULE`` lists ``source=cadence`` pairs, e.g.
``world_bank=6h,uzex=6h,ebrd=24h,giz=24h`` (the default when unset). An empty value
disables scheduling. Parsing is strict: an unknown, hidden, refresh-disabled or
repeated source, or a malformed cadence, raises at import of the Celery app so a
bad deployment fails at startup instead of silently not refreshing.

Beat does not own the cadence: each scheduled source gets one Beat entry that ticks
every ``SOURCE_REFRESH_SCHEDULE_TICK_SECONDS`` (default 300) and starts a refresh
only when the source's latest refresh attempt (any trigger) is at least one cadence
old. The decision is taken from the database, so Beat restarts neither skip nor
double a refresh, and an operator or customer refresh postpones the next scheduled one.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.services.source_registry import SOURCE_REGISTRY, SourceDefinition

DEFAULT_SOURCE_REFRESH_SCHEDULE = "world_bank=6h,uzex=6h,ebrd=24h,giz=24h"
DEFAULT_TICK_SECONDS = 300
MIN_CADENCE = timedelta(minutes=15)
STALE_CADENCE_MULTIPLIER = 2
SCHEDULED_REFRESH_TASK = "app.workers.source_refresh_tasks.dispatch_scheduled_source_refresh"
BEAT_ENTRY_PREFIX = "scheduled-source-refresh-"
_ENTRY = re.compile(r"^(?P<key>[a-z_]+)=(?P<amount>[1-9][0-9]*)(?P<unit>[mhd])$")
_UNITS = {"m": "minutes", "h": "hours", "d": "days"}


class SourceRefreshScheduleError(ValueError):
    """SOURCE_REFRESH_SCHEDULE cannot be honoured exactly as written."""


def parse_source_refresh_schedule(
    raw: str,
    registry: Mapping[str, SourceDefinition] = SOURCE_REGISTRY,
) -> dict[str, timedelta]:
    schedule: dict[str, timedelta] = {}
    text = (raw or "").strip()
    if not text:
        return schedule
    for item in text.split(","):
        entry = item.strip().casefold()
        match = _ENTRY.match(entry)
        if match is None:
            raise SourceRefreshScheduleError(
                f"SOURCE_REFRESH_SCHEDULE entry {item.strip()!r} is not <source>=<N>m|h|d"
            )
        key = match["key"]
        definition = registry.get(key)
        if definition is None:
            raise SourceRefreshScheduleError(f"SOURCE_REFRESH_SCHEDULE names unknown source {key!r}")
        if not definition.customer_visible:
            raise SourceRefreshScheduleError(f"SOURCE_REFRESH_SCHEDULE names hidden source {key!r}")
        if not definition.refresh_enabled or not definition.operator_visible:
            raise SourceRefreshScheduleError(f"SOURCE_REFRESH_SCHEDULE names refresh-disabled source {key!r}")
        if key in schedule:
            raise SourceRefreshScheduleError(f"SOURCE_REFRESH_SCHEDULE lists {key!r} twice")
        cadence = timedelta(**{_UNITS[match["unit"]]: int(match["amount"])})
        if cadence < MIN_CADENCE:
            raise SourceRefreshScheduleError(
                f"SOURCE_REFRESH_SCHEDULE cadence for {key!r} is below {int(MIN_CADENCE.total_seconds() // 60)} minutes"
            )
        schedule[key] = cadence
    return schedule


def configured_source_refresh_schedule(environ: Mapping[str, str] | None = None) -> dict[str, timedelta]:
    env = os.environ if environ is None else environ
    raw = env.get("SOURCE_REFRESH_SCHEDULE")
    return parse_source_refresh_schedule(DEFAULT_SOURCE_REFRESH_SCHEDULE if raw is None else raw)


def schedule_tick_seconds(environ: Mapping[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    try:
        return max(60, int(env.get("SOURCE_REFRESH_SCHEDULE_TICK_SECONDS", DEFAULT_TICK_SECONDS)))
    except (TypeError, ValueError) as exc:
        raise SourceRefreshScheduleError("SOURCE_REFRESH_SCHEDULE_TICK_SECONDS must be an integer") from exc


def build_beat_schedule(
    schedule: Mapping[str, timedelta],
    *,
    tick_seconds: int = DEFAULT_TICK_SECONDS,
) -> dict[str, dict[str, Any]]:
    """One Beat entry per scheduled source; each tick asks the database whether it is due."""
    return {
        f"{BEAT_ENTRY_PREFIX}{key}": {
            "task": SCHEDULED_REFRESH_TASK,
            "schedule": timedelta(seconds=tick_seconds),
            "args": (key,),
            "options": {"queue": "celery", "routing_key": "celery", "expires": tick_seconds},
        }
        for key in sorted(schedule)
    }


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def refresh_is_due(
    *,
    last_attempt_at: datetime | None,
    cadence: timedelta,
    now: datetime,
) -> bool:
    """Due when no refresh was ever attempted or the latest attempt is one cadence old."""
    last = _utc(last_attempt_at)
    return last is None or _utc(now) - last >= cadence


def is_stale(
    *,
    last_success_at: datetime | None,
    cadence: timedelta | None,
    now: datetime,
) -> bool | None:
    """Stale when the last successful refresh is older than twice the cadence.

    None when the source is not scheduled (there is no cadence to be late against).
    """
    if cadence is None:
        return None
    last = _utc(last_success_at)
    return last is None or _utc(now) - last > STALE_CADENCE_MULTIPLIER * cadence
