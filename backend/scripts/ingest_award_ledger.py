#!/usr/bin/env python3
"""Append World Bank contract-award notices to the award ledger (Sprint 1).

Reads the public World Bank procurement API (no credentials) for the ledger countries,
newest first, Consultant Services before every other group, and appends new or changed
notices. Re-running appends nothing for unchanged notices.

    python scripts/ingest_award_ledger.py --confirm INGEST_AWARD_LEDGER
    python scripts/ingest_award_ledger.py --confirm INGEST_AWARD_LEDGER --country Uzbekistan --consulting-only
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
import json
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models.all_models  # noqa: F401  (registers every mapper)
from app.db.session import AsyncSessionLocal, engine
from app.services.award_ledger import DEFAULT_WINDOW_MONTHS, LEDGER_COUNTRIES, ingest_world_bank_awards, window_start

CONFIRMATION = "INGEST_AWARD_LEDGER"


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    command.add_argument("--confirm", default="", help=f"Required: {CONFIRMATION}")
    command.add_argument("--country", action="append", default=[], help="Limit to a country (repeatable).")
    command.add_argument("--months", type=int, default=DEFAULT_WINDOW_MONTHS, help="Window in months (default 24).")
    command.add_argument("--since", type=date.fromisoformat, default=None, help="Window start (YYYY-MM-DD).")
    command.add_argument("--consulting-only", action="store_true", help="Consultant Services only.")
    return command


async def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.confirm != CONFIRMATION:
        print(f"Writing requires --confirm {CONFIRMATION}", file=sys.stderr)
        return 2
    countries = tuple(args.country) or LEDGER_COUNTRIES
    since = args.since or window_start(date.today(), args.months)
    try:
        async with AsyncSessionLocal() as db:
            report = await ingest_world_bank_awards(
                db, countries=countries, since=since, consulting_only=args.consulting_only,
            )
    finally:
        await engine.dispose()
    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
