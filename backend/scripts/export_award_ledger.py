#!/usr/bin/env python3
"""Write award-ledger exports to files (Sprint 1). Read-only.

    python scripts/export_award_ledger.py --out-dir /tmp/ledger                # everything
    python scripts/export_award_ledger.py --out-dir /tmp/ledger --only market   # market sizing only
    python scripts/export_award_ledger.py --out-dir /tmp/ledger --only nameqa   # name-QA review lists
    python scripts/export_award_ledger.py --out-dir private/s1 --only targets  # PRIVATE outreach list

Files: award_outcomes.csv (every bidder row), firms.csv (one row per firm, outreach list:
keep it to admins), market_sizing.csv and market_sizing.md (Uzbekistan and Kazakhstan
consulting, 24 months). Name QA (S1-6): non_firm_review.csv (names flagged as a public body or a
project, left out of firm counts) and merge_candidates.csv (top same-country pairs that may be one
firm; for owner review, never merged). Outreach targets (S1-6, private: write them under the
gitignored private/ directory, never commit): outreach_targets.csv (every category, consulting first),
consulting_targets.csv (the consulting rows) and outreach_summary.md.
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
    merge_candidates,
    name_qa_csvs,
    non_firm_review,
    outcomes_csv,
    outreach_summary_markdown,
    outreach_targets,
    outreach_targets_csv,
)
from app.services.award_ledger import window_start


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    command.add_argument("--out-dir", type=Path, required=True)
    command.add_argument("--only", choices=("ledger", "firms", "market", "nameqa", "targets"), action="append", default=[])
    command.add_argument("--today", type=date.fromisoformat, default=None, help="Market-sizing window end.")
    return command


async def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    parts = set(args.only) or {"ledger", "firms", "market", "nameqa"}
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
            if "nameqa" in parts:
                non_firms, merges = await non_firm_review(db), await merge_candidates(db)
                non_firm_csv, merge_csv = name_qa_csvs(non_firms, merges)
                (args.out_dir / "non_firm_review.csv").write_text(non_firm_csv, encoding="utf-8")
                (args.out_dir / "merge_candidates.csv").write_text(merge_csv, encoding="utf-8")
                report["non_firm_names"] = len(non_firms)
                report["merge_candidates"] = len(merges)
            if "targets" in parts:
                targets = await outreach_targets(db, today=args.today)
                until = args.today or date.today()
                (args.out_dir / "outreach_targets.csv").write_text(outreach_targets_csv(targets), encoding="utf-8")
                consulting = [item for item in targets if item["consulting_target"] == "yes"]
                (args.out_dir / "consulting_targets.csv").write_text(outreach_targets_csv(consulting), encoding="utf-8")
                report["consulting_targets"] = len(consulting)
                (args.out_dir / "outreach_summary.md").write_text(
                    outreach_summary_markdown(targets, since=window_start(until), until=until), encoding="utf-8")
                report["outreach_targets"] = len(targets)
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
