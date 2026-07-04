"""Storage path normalization shared by document status and workers."""

from __future__ import annotations

import re
from pathlib import Path

_WINDOWS_DRIVE_RE = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def normalize_storage_path(storage_path: str | Path | None) -> Path | None:
    """Resolve persisted storage paths across native Windows and WSL runtimes."""
    if storage_path is None:
        return None

    raw_path = str(storage_path).strip()
    if not raw_path:
        return None

    match = _WINDOWS_DRIVE_RE.match(raw_path)
    if match:
        drive = match.group(1).lower()
        rest = match.group(2).replace("\\", "/")
        return Path(f"/mnt/{drive}/{rest}")

    return Path(raw_path)


def storage_file_exists(storage_path: str | Path | None) -> bool:
    """Return whether a persisted document file exists without exposing its path."""
    resolved_path = normalize_storage_path(storage_path)
    if resolved_path is None:
        return False

    try:
        return resolved_path.is_file()
    except (OSError, TypeError, ValueError):
        return False
