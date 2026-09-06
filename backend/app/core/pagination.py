"""Additive pagination for legacy list responses (no eager all-pages adapter)."""
from fastapi import Response


def page_rows(rows: list, *, limit: int, offset: int, response: Response | None) -> list:
    if response is not None:
        more = len(rows) > limit
        response.headers["X-Has-More"] = str(more).lower()
        response.headers["X-Next-Offset"] = str(offset + limit) if more else ""
        response.headers["X-Page-Limit"] = str(limit)
    return rows[:limit]
