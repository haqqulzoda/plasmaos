"""Dependency-free tender source key helpers."""

VALID_SOURCE_SYSTEMS = frozenset({"uzex", "world_bank", "adb"})


def normalize_source_system(source_system: str) -> str:
    """Normalize and validate a source-system identifier."""
    normalized = (source_system or "").strip().casefold()
    if normalized not in VALID_SOURCE_SYSTEMS:
        raise ValueError(f"Unsupported tender source_system: {source_system!r}")
    return normalized


def canonical_source_key(source_system: str, external_id: str) -> str:
    """Build the stable cross-source tender key."""
    normalized_source = normalize_source_system(source_system)
    normalized_external_id = str(external_id or "").strip()
    if not normalized_external_id:
        raise ValueError("external_id is required for canonical_source_key")
    return f"{normalized_source}:{normalized_external_id}"
