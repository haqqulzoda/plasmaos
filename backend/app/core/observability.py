"""Error tracking (R3): Sentry for the API, Celery workers and Beat.

Off unless SENTRY_DSN_BACKEND is set: without it nothing is imported or initialised. When on,
release = the image's build SHA, environment = ENVIRONMENT, and every event and breadcrumb is
scrubbed before it leaves the host: no request bodies, cookies or auth headers, no local
variables, no performance traces, no user data, and messages/values with e-mail addresses,
tokens and quoted text (where document content shows up, e.g. a validation error's
input_value) redacted and truncated. Private document content must never reach Sentry.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

SENTRY_DSN_ENV = "SENTRY_DSN_BACKEND"
MAX_TEXT_LENGTH = 300
FILTERED = "[Filtered]"

# Request headers worth keeping (everything else, e.g. Authorization or Cookie, is dropped).
_SAFE_HEADERS = frozenset({
    "accept", "accept-language", "content-length", "content-type", "host", "user-agent",
    "x-request-id", "x-forwarded-proto",
})
# Dictionary keys whose values are never sent (credentials and anything that can hold text).
_SENSITIVE_KEY = re.compile(
    r"pass|secret|token|auth|cookie|session|csrf|api[_-]?key|access[_-]?key|dsn|credential|"
    r"private|signature|email|e_mail|phone|text|content|body|document|notice|prompt|payload|"
    r"file|excerpt|quote|snippet|answer|response",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL_CREDENTIALS = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@", re.IGNORECASE)
_AUTH_SCHEME = re.compile(r"\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}")
_ASSIGNED_SECRET = re.compile(
    r"\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|authorization|cookie|dsn|"
    r"signature|sig|key)(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s&,;)]+)",
    re.IGNORECASE,
)
# Hex/base64-looking secrets (UUIDs, split by hyphens, and URL paths, split by slashes, stay).
_LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9_+])[A-Za-z0-9_+]{32,}={0,2}")
# Validation errors echo the offending value: input_value='<the whole extracted passage>'.
_INPUT_VALUE = re.compile(
    r"input_value=('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|\{[^}]*\}?|\[[^\]]*\]?|\S+)", re.DOTALL
)
# Long quoted strings are where tender/private document text appears in messages.
_QUOTED_TEXT = re.compile(r"'(?:[^'\\]|\\.){40,}'|\"(?:[^\"\\]|\\.){40,}\"|“[^”]{40,}”", re.DOTALL)
# Prose: ten or more words in a row. Plasma's own error messages are short and keyed
# (operation_failed event=... error_type=...); a sentence-long run is document content.
_PROSE = re.compile(r"(?:[^\W\d_]{2,}[\s,;:.()'\"“”-]+){9,}[^\W\d_]{2,}[.,;:]?")


def scrub_text(value: Any, limit: int = MAX_TEXT_LENGTH) -> Any:
    """Redact e-mail addresses, credentials and quoted text; truncate to `limit` characters."""
    if not isinstance(value, str):
        return value
    text = _INPUT_VALUE.sub("input_value=[redacted]", value)
    text = _URL_CREDENTIALS.sub(r"\1[redacted]@", text)
    text = _AUTH_SCHEME.sub(r"\1 [redacted]", text)
    text = _JWT.sub("[redacted token]", text)
    text = _ASSIGNED_SECRET.sub(r"\1\2[redacted]", text)
    text = _EMAIL.sub("[email]", text)
    text = _QUOTED_TEXT.sub("'[redacted text]'", text)
    text = _PROSE.sub("[redacted text]", text)
    text = _LONG_TOKEN.sub("[redacted token]", text)
    if len(text) > limit:
        text = text[:limit] + "…[truncated]"
    return text


def scrub_data(value: Any, depth: int = 0) -> Any:
    """Recursively scrub a JSON-like structure: sensitive keys filtered, strings scrubbed."""
    if depth > 6:
        return FILTERED
    if isinstance(value, dict):
        return {
            key: FILTERED if isinstance(key, str) and _SENSITIVE_KEY.search(key) else scrub_data(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub_data(item, depth + 1) for item in list(value)[:50]]
    return scrub_text(value)


def _scrub_url(url: Any) -> Any:
    if not isinstance(url, str):
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return scrub_text(url)
    netloc = parts.netloc.rsplit("@", 1)[-1]
    return scrub_text(urlunsplit((parts.scheme, netloc, parts.path, "", "")))


def _scrub_request(request: dict[str, Any]) -> dict[str, Any]:
    headers = request.get("headers") or {}
    if isinstance(headers, dict):
        headers = {key: scrub_text(value) for key, value in headers.items() if key.lower() in _SAFE_HEADERS}
    else:
        headers = {}
    return {"method": request.get("method"), "url": _scrub_url(request.get("url")), "headers": headers}


def _scrub_stacktrace(stacktrace: Any) -> None:
    if not isinstance(stacktrace, dict):
        return
    for frame in stacktrace.get("frames") or []:
        if isinstance(frame, dict):
            frame.pop("vars", None)


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Sentry before_send: keep what locates the fault (type, stack, release); drop the rest."""
    del hint
    if "request" in event and isinstance(event["request"], dict):
        event["request"] = _scrub_request(event["request"])
    event.pop("user", None)
    for exception in (event.get("exception") or {}).get("values") or []:
        if isinstance(exception, dict):
            exception["value"] = scrub_text(exception.get("value"))
            _scrub_stacktrace(exception.get("stacktrace"))
    for thread in (event.get("threads") or {}).get("values") or []:
        if isinstance(thread, dict):
            _scrub_stacktrace(thread.get("stacktrace"))
    _scrub_stacktrace(event.get("stacktrace"))
    if "message" in event:
        event["message"] = scrub_text(event["message"])
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        for key in ("message", "formatted"):
            if key in logentry:
                logentry[key] = scrub_text(logentry[key])
        if "params" in logentry:
            logentry["params"] = scrub_data(logentry["params"])
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        breadcrumbs["values"] = [
            crumb for crumb in (scrub_breadcrumb(item) for item in breadcrumbs.get("values") or []) if crumb
        ]
    if isinstance(event.get("extra"), dict):
        event["extra"].pop("sys.argv", None)  # a process's command line is not diagnostic data here
    for key in ("extra", "contexts", "tags"):
        if isinstance(event.get(key), dict):
            event[key] = scrub_data(event[key])
    return event


def scrub_breadcrumb(crumb: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Sentry before_breadcrumb: messages scrubbed, URLs without query or credentials."""
    del hint
    if not isinstance(crumb, dict):
        return None
    if "message" in crumb:
        crumb["message"] = scrub_text(crumb["message"])
    data = crumb.get("data")
    if isinstance(data, dict):
        url = data.get("url")
        data = scrub_data({key: value for key, value in data.items() if key != "url"})
        if url is not None:
            data["url"] = _scrub_url(url)
        crumb["data"] = data
    return crumb


def _drop_transaction(event: dict[str, Any], hint: dict[str, Any] | None = None) -> None:
    return None


def _release() -> str | None:
    value = (os.getenv("PLASMA_BUILD_SHA") or "").strip()
    return value if value and value != "unknown" else None


def error_tracking_dsn() -> str | None:
    value = (os.getenv(SENTRY_DSN_ENV) or "").strip()
    return value or None


def init_error_tracking(component: str, *, transport: Any = None) -> bool:
    """Start Sentry for `component` (backend, celery_worker, celery_beat...) when a DSN is set.

    Returns False (and imports nothing) without SENTRY_DSN_BACKEND. Never raises: error
    tracking must not stop the service from starting.
    """
    dsn = error_tracking_dsn()
    if dsn is None:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        integrations: list[Any] = [LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)]
        if component.startswith("celery") or component.startswith("worker"):
            from sentry_sdk.integrations.celery import CeleryIntegration

            integrations.append(CeleryIntegration(monitor_beat_tasks=False, propagate_traces=False))
        options: dict[str, Any] = {}
        if transport is not None:
            options["transport"] = transport
        sentry_sdk.init(
            dsn=dsn,
            release=_release(),
            environment=(os.getenv("ENVIRONMENT") or "production").strip(),
            server_name=component,
            integrations=integrations,
            send_default_pii=False,
            max_request_body_size="never",
            include_local_variables=False,
            attach_stacktrace=False,
            traces_sample_rate=0.0,
            before_send=scrub_event,
            before_send_transaction=_drop_transaction,
            before_breadcrumb=scrub_breadcrumb,
            max_breadcrumbs=30,
            **options,
        )
        sentry_sdk.set_tag("component", component)
    except Exception:  # noqa: BLE001 - never block startup on error tracking
        logger.warning("error_tracking_init_failed component=%s", component, exc_info=False)
        return False
    logger.info("error_tracking_enabled component=%s", component)
    return True
