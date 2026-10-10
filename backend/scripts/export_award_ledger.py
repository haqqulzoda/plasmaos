#!/usr/bin/env python3
"""Write award-ledger exports to files (Sprint 1). Read-only.

    python scripts/export_award_ledger.py --out-dir /tmp/ledger                # everything
    python scripts/export_award_ledger.py --out-dir /tmp/ledger --only market   # market sizing only

Files: award_outcomes.csv (every bidder row), firms.csv (one row per firm, outreach list:
keep it to admins), market_sizing.csv and market_sizing.md (Uzbekistan and Kazakhstan
consulting, 24 months).
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
from app.services.award_ledger_reports import (
    OutcomeFilters,
    firm_export_csv,
    ledger_summary,
    market_sizing,
    market_sizing_csv,
    market_sizing_markdown,
    outcomes_csv,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    command.add_argument("--out-dir", type=Path, required=True)
    command.add_argument("--only", choices=("ledger", "firms", "market"), action="append", default=[])
    command.add_argument("--today", type=date.fromisoformat, default=None, help="Market-sizing window end.")
    return command


async def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    parts = set(args.only) or {"ledger", "firms", "market"}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {}
    try:
        async with AsyncSessionLocal() as db:
            report["summary"] = await ledger_summary(db)
            if "ledger" in parts:
                (args.out_dir / "award_outcomes.csv").write_text(await outcomes_csv(db, filters=OutcomeFilters()), encoding="utf-8")
            if "firms" in parts:
                content, count = await firm_export_csv(db)
                (args.out_dir / "firms.csv").write_text(content, encoding="utf-8")
                report["firm_count"] = count
            if "market" in parts:
                result = await market_sizing(db, today=args.today)
                (args.out_dir / "market_sizing.csv").write_text(market_sizing_csv(result), encoding="utf-8")
                (args.out_dir / "market_sizing.md").write_text(market_sizing_markdown(result), encoding="utf-8")
    finally:
        await engine.dispose()
    print(json.dumps(report, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
