"""Small, source-neutral helpers for safe connector failure diagnostics."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


RETRYABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class ConnectorFailureDetails:
    """Customer-safe classification for a connector exception."""

    failure_class: str
    http_status: int | None
    retryable: bool

    @property
    def status(self) -> str:
        return "source_unavailable" if self.retryable else "failed"


def connector_failure_details(exc: BaseException) -> ConnectorFailureDetails:
    """Classify transport/HTTP failures without exposing exception text or URLs."""
    http_status = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        http_status = int(http_status) if http_status is not None else None
    except (TypeError, ValueError):
        http_status = None

    retryable = http_status in RETRYABLE_HTTP_STATUS_CODES
    try:
        import httpx

        retryable = retryable or isinstance(
            exc,
            (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
            ),
        )
    except ImportError:  # pragma: no cover - connectors require httpx at runtime
        pass
    retryable = retryable or isinstance(exc, (TimeoutError, ConnectionError))
    return ConnectorFailureDetails(
        failure_class=type(exc).__name__,
        http_status=http_status,
        retryable=retryable,
    )


def retry_after_seconds(exc: BaseException, *, attempt: int) -> float:
    """Return bounded exponential backoff, respecting a numeric Retry-After."""
    headers: Any = getattr(getattr(exc, "response", None), "headers", None)
    retry_after = headers.get("retry-after") if headers is not None else None
    try:
        if retry_after is not None:
            return max(0.0, min(float(retry_after), 30.0))
    except (TypeError, ValueError):
        pass
    return min(0.5 * (2**attempt) + random.uniform(0.0, 0.25), 5.0)


def safe_failure_message(source_label: str, stage: str, exc: BaseException) -> str:
    """Build an actionable message that contains no raw response or secret data."""
    details = connector_failure_details(exc)
    status_suffix = (
        f", HTTP {details.http_status}" if details.http_status is not None else ""
    )
    condition = "source unavailable" if details.retryable else "connector failed"
    return (
        f"{source_label} {condition} during {stage} "
        f"({details.failure_class}{status_suffix}; retryable={str(details.retryable).lower()}). "
        "Existing tenders remain available."
    )
