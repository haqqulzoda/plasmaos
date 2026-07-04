from __future__ import annotations

from collections.abc import Iterable


TARGET_SERVICE_VALUES: tuple[str, ...] = (
    "construction",
    "medical",
    "IT",
    "industrial services",
    "consulting",
    "equipment supply",
    "other",
)

TARGET_SERVICE_LABELS: dict[str, str] = {
    "construction": "Construction",
    "medical": "Medical",
    "IT": "IT",
    "industrial services": "Industrial Services",
    "consulting": "Consulting",
    "equipment supply": "Equipment Supply",
    "other": "Other",
}

_TARGET_SERVICE_LOOKUP = {
    value.casefold(): value
    for value in TARGET_SERVICE_VALUES
}


def _normalize_target_service_value(
    value: object,
    *,
    reject_invalid: bool = True,
) -> str | None:
    if not isinstance(value, str):
        if value is not None and reject_invalid:
            raise ValueError(f"Invalid target service: {value}")
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    canonical = _TARGET_SERVICE_LOOKUP.get(cleaned.casefold())
    if canonical is None:
        if reject_invalid:
            raise ValueError(f"Invalid target service: {cleaned}")
        return None

    return canonical


def normalize_target_service(
    value: object,
    *,
    reject_invalid: bool = True,
) -> str | None:
    return _normalize_target_service_value(value, reject_invalid=reject_invalid)


def normalize_target_services(
    values: Iterable[object] | None,
    *,
    reject_invalid: bool = True,
) -> list[str] | None:
    if values is None:
        return None

    normalized: list[str] = []
    seen: set[str] = set()

    for item in values:
        canonical = _normalize_target_service_value(
            item,
            reject_invalid=reject_invalid,
        )
        if canonical is None:
            continue

        key = canonical.casefold()
        if key not in seen:
            normalized.append(canonical)
            seen.add(key)

    return normalized


def service_label(value: str) -> str:
    return TARGET_SERVICE_LABELS.get(value, value)


def services_meta_payload() -> list[dict[str, str]]:
    return [
        {
            "value": value,
            "label": service_label(value),
        }
        for value in TARGET_SERVICE_VALUES
    ]
