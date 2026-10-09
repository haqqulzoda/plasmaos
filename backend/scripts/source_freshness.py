"""Print the refresh freshness of every customer-visible source (scripts/ops/monitor.sh).

One line per source, from the same status the Explorer shows (app.services.source_refresh_activity):

    source=world_bank cadence_s=21600 last_success_age_s=1234 verdict=ok
    source=giz cadence_s=86400 last_success_age_s=-1 verdict=stale        (never succeeded)
    source=adb cadence_s=0 last_success_age_s=-1 verdict=unscheduled

verdict=stale when the last successful refresh (completed, or partial with data) is older than
twice the scheduled cadence. Read-only. Run it inside the backend container:
    docker exec plasma_backend python scripts/source_freshness.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def freshness_lines(items, now: datetime) -> list[str]:
    lines = []
    for item in items:
        cadence = item.scheduled_cadence_seconds or 0
        age = int((now - item.last_success_at).total_seconds()) if item.last_success_at else -1
        verdict = "unscheduled" if item.stale is None else ("stale" if item.stale else "ok")
        lines.append(f"source={item.source_system} cadence_s={cadence} last_success_age_s={age} verdict={verdict}")
    return lines


async def main() -> int:
    from app.db.session import AsyncSessionLocal, engine
    from app.services.source_refresh_activity import source_refresh_status

    try:
        async with AsyncSessionLocal() as db:
            items = await source_refresh_status(db)
    finally:
        await engine.dispose()
    print("\n".join(freshness_lines(items, datetime.now(timezone.utc))))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
