from __future__ import annotations

from collections.abc import Iterable


REGION_OPTIONS: tuple[str, ...] = (
    "Central Asia",
    "Asia",
    "Europe",
    "Africa",
    "North America",
    "Latin America",
)

CENTRAL_ASIA_REGION = "Central Asia"

CENTRAL_ASIA_COUNTRIES: tuple[str, ...] = (
    "Uzbekistan",
    "Kazakhstan",
    "Kyrgyzstan",
    "Tajikistan",
    "Turkmenistan",
)

COUNTRIES_BY_REGION: dict[str, tuple[str, ...]] = {
    CENTRAL_ASIA_REGION: CENTRAL_ASIA_COUNTRIES,
    "Asia": (),
    "Europe": (),
    "Africa": (),
    "North America": (),
    "Latin America": (),
}


def _canonical_lookup(values: Iterable[str]) -> dict[str, str]:
    return {value.casefold(): value for value in values}


def normalize_allowed_values(
    values: Iterable[str],
    allowed_values: Iterable[str],
    *,
    label: str,
    reject_invalid: bool = True,
) -> list[str]:
    """Trim, dedupe, and canonicalize values against a known option list."""
    lookup = _canonical_lookup(allowed_values)
    normalized: list[str] = []
    seen: set[str] = set()

    for item in values:
        if not isinstance(item, str):
            if reject_invalid:
                raise ValueError(f"Invalid {label}: {item}")
            continue

        cleaned = item.strip()
        if not cleaned:
            continue

        canonical = lookup.get(cleaned.casefold())
        if canonical is None:
            if reject_invalid:
                raise ValueError(f"Invalid {label}: {cleaned}")
            continue

        key = canonical.casefold()
        if key not in seen:
            normalized.append(canonical)
            seen.add(key)

    return normalized


def normalize_target_regions(
    values: Iterable[str] | None,
    *,
    reject_invalid: bool = True,
) -> list[str] | None:
    if values is None:
        return None
    return normalize_allowed_values(
        values,
        REGION_OPTIONS,
        label="target region",
        reject_invalid=reject_invalid,
    )


def normalize_target_countries(
    values: Iterable[str] | None,
    *,
    reject_invalid: bool = True,
) -> list[str] | None:
    if values is None:
        return None
    return normalize_allowed_values(
        values,
        CENTRAL_ASIA_COUNTRIES,
        label="target country",
        reject_invalid=reject_invalid,
    )


def geography_meta_payload() -> dict[str, object]:
    return {
        "regions": list(REGION_OPTIONS),
        "countries_by_region": {
            region: list(COUNTRIES_BY_REGION.get(region, ()))
            for region in REGION_OPTIONS
        },
        "central_asia_countries": list(CENTRAL_ASIA_COUNTRIES),
    }
