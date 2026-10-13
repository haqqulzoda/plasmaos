"""S1-8: prospect previews replayed on a closed notice.

A Loom preview may be built on a CLOSED World Bank REOI when no open one fits ("replay"). The preview
seed records each replayed tender in the preview organization's company-profile notes, and the pursuit
API derives ``replay_closed_on`` from that marker, so the workspace says "Replay on a closed notice
(closed <date>) — for illustration" and never implies the firm can still submit. Only preview
organizations carry the marker (the seed writes it; no user-facing form edits it).
"""

from __future__ import annotations

import re
from datetime import date

_MARKER = re.compile(r"\[plasma-replay (?P<key>\S+) closed (?P<closed>\d{4}-\d{2}-\d{2})\]")


def replay_text(closed_on: date) -> str:
    return f"Replay on a closed notice (closed {closed_on.isoformat()}) — for illustration"


def replay_marker(canonical_source_key: str, closed_on: date) -> str:
    return f"[plasma-replay {canonical_source_key} closed {closed_on.isoformat()}]"


def parse_replays(notes: str | None) -> dict[str, date]:
    """{canonical source key: closing date} for every replay marker in the notes."""
    return {match["key"]: date.fromisoformat(match["closed"]) for match in _MARKER.finditer(notes or "")}
