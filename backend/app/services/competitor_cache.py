"""Canonical persisted cache for public competitor evidence.

The cache lives in the existing Tender source metadata JSON so Tender Details
can remain a read-only, network-free projection. Population is owned by the
explicit source-refresh lifecycle; source payloads cannot accidentally opt in
because the key is Plasma-namespaced and every record is schema-validated.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from pydantic import ValidationError

from app.schemas.tender import TenderCompetitorResponse


COMPETITOR_CACHE_METADATA_KEY = "_plasma_competitor_intelligence_v1"
COMPETITOR_CACHE_VERSION = 1
COMPETITOR_CACHE_MAX_RECORDS = 30


def cached_competitor_records(
    metadata: Mapping[str, Any] | None,
) -> list[TenderCompetitorResponse]:
    """Return only valid, bounded records from Plasma-owned cache metadata."""
    if not isinstance(metadata, Mapping):
        return []
    payload = metadata.get(COMPETITOR_CACHE_METADATA_KEY)
    if not isinstance(payload, Mapping):
        return []
    if payload.get("version") != COMPETITOR_CACHE_VERSION:
        return []
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        return []

    records: list[TenderCompetitorResponse] = []
    for raw_record in raw_records[:COMPETITOR_CACHE_MAX_RECORDS]:
        if not isinstance(raw_record, Mapping):
            continue
        try:
            records.append(TenderCompetitorResponse.model_validate(raw_record))
        except ValidationError:
            continue
    return records


def competitor_cache_was_evaluated(metadata: Mapping[str, Any] | None) -> bool:
    """Distinguish a completed empty refresh from an unpopulated cache."""
    if not isinstance(metadata, Mapping):
        return False
    payload = metadata.get(COMPETITOR_CACHE_METADATA_KEY)
    return bool(
        isinstance(payload, Mapping)
        and payload.get("version") == COMPETITOR_CACHE_VERSION
        and payload.get("evaluated") is True
        and isinstance(payload.get("records"), list)
    )


def metadata_with_competitor_cache(
    metadata: Mapping[str, Any] | None,
    records: Iterable[TenderCompetitorResponse],
    *,
    source_system: str,
    refreshed_at: datetime | None = None,
    lookup_strategy: str | None = None,
) -> dict[str, Any]:
    """Return a copy of metadata containing a canonical bounded cache."""
    timestamp = refreshed_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)
    bounded = list(records)[:COMPETITOR_CACHE_MAX_RECORDS]
    updated = dict(metadata or {})
    updated[COMPETITOR_CACHE_METADATA_KEY] = {
        "version": COMPETITOR_CACHE_VERSION,
        "source_system": str(source_system or "").strip().casefold(),
        "refreshed_at": timestamp.isoformat(),
        "evaluated": True,
        "records": [record.model_dump(mode="json") for record in bounded],
    }
    if lookup_strategy:
        updated[COMPETITOR_CACHE_METADATA_KEY]["lookup_strategy"] = lookup_strategy
    return updated
