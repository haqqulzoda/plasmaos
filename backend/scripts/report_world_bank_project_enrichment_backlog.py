#!/usr/bin/env python3
"""Read-only aggregate diagnostics for World Bank Project enrichment."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import AsyncSessionLocal, engine
from app.services.project_enrichment import world_bank_project_backlog_snapshot


async def main() -> int:
    try:
        async with AsyncSessionLocal() as db:
            snapshot = await world_bank_project_backlog_snapshot(db)
            await db.rollback()
        print(json.dumps(asdict(snapshot), sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
