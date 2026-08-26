#!/usr/bin/env python3
"""Bounded operator reconciliation for linked World Bank Projects."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import AsyncSessionLocal, engine
from app.services.project_enrichment import (
    WORLD_BANK_ENRICHMENT_BATCH_SIZE,
    claim_world_bank_projects_for_enrichment,
    enqueue_world_bank_project_enrichment_batch,
)


CONFIRMATION = "ENQUEUE_WORLD_BANK_PROJECT_ENRICHMENT"


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description=(
            "Claim and enqueue one bounded batch of linked, never-enriched or "
            "stale World Bank Projects through the existing Celery worker."
        )
    )
    command.add_argument(
        "--limit",
        type=int,
        default=WORLD_BANK_ENRICHMENT_BATCH_SIZE,
        help=f"Batch size from 1 to {WORLD_BANK_ENRICHMENT_BATCH_SIZE}.",
    )
    command.add_argument(
        "--apply",
        action="store_true",
        help="Publish the claimed batch. Without this flag the transaction rolls back.",
    )
    command.add_argument(
        "--confirm",
        default="",
        help=f"Required with --apply: {CONFIRMATION}",
    )
    return command


async def run(args: argparse.Namespace) -> dict[str, int | str | bool]:
    if not 1 <= args.limit <= WORLD_BANK_ENRICHMENT_BATCH_SIZE:
        raise ValueError(
            f"limit must be between 1 and {WORLD_BANK_ENRICHMENT_BATCH_SIZE}"
        )
    if args.apply and args.confirm != CONFIRMATION:
        raise ValueError(f"confirmation must be exactly {CONFIRMATION}")

    async with AsyncSessionLocal() as db:
        if not args.apply:
            project_ids = await claim_world_bank_projects_for_enrichment(
                db,
                limit=args.limit,
            )
            await db.rollback()
            return {
                "mode": "dry_run",
                "limit": args.limit,
                "eligible_in_batch": len(project_ids),
                "database_mutated": False,
            }

        result = await enqueue_world_bank_project_enrichment_batch(
            db,
            limit=args.limit,
        )
        return {
            "mode": "apply",
            "limit": args.limit,
            "claimed": result.claimed,
            "enqueued": result.enqueued,
            "dispatch_failed": result.dispatch_failed,
        }


async def main() -> int:
    args = parser().parse_args()
    try:
        result = await run(args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
