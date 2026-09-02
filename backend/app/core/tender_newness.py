"""Server-authoritative Tender first-discovery newness semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


TENDER_NEWNESS_WINDOW = timedelta(hours=24)


def utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class TenderNewness:
    created_at: datetime
    is_new: bool
    new_until: datetime


def tender_newness(created_at: datetime, *, server_time: datetime) -> TenderNewness:
    created = utc_datetime(created_at)
    reference = utc_datetime(server_time)
    new_until = created + TENDER_NEWNESS_WINDOW
    return TenderNewness(
        created_at=created,
        is_new=created <= reference < new_until,
        new_until=new_until,
    )
