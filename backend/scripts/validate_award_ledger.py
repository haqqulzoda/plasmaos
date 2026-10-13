#!/usr/bin/env python3
"""S1-7: validate every ledger notice's country against its World Bank project (and flag foreign bidder sections).

Resolves each ledger project id against the World Bank Projects API
(https://search.worldbank.org/api/v2/projects?format=json&id=<project id>), caching the records in
``projects`` through the existing project-enrichment pipeline (re-fetched after 30 days), then prints every
flagged notice. Flagged notices stay in the ledger and are left out of sizing figures and target lists.

    python scripts/validate_award_ledger.py --confirm VALIDATE_AWARD_LEDGER          # resolve + report
    python scripts/validate_award_ledger.py --report-only                            # read-only report
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models.all_models  # noqa: F401,E402
from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.services.award_ledger_validation import resolve_ledger_projects, validation_rows  # noqa: E402

CONFIRMATION = "VALIDATE_AWARD_LEDGER"


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm", default="")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.report_only and args.confirm != CONFIRMATION:
        print(f"Resolving projects writes the project cache: --confirm {CONFIRMATION} (or --report-only)", file=sys.stderr)
        return 2
    try:
        async with AsyncSessionLocal() as db:
            resolved = None if args.report_only else await resolve_ledger_projects(db)
            rows = await validation_rows(db)
    finally:
        await engine.dispose()
    print(json.dumps({"projects": resolved, "flagged_notices": len(rows),
                      "by_flag": dict(Counter(row["flag"] for row in rows)), "notices": rows},
                     indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
