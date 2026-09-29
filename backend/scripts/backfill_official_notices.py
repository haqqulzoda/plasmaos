#!/usr/bin/env python3
"""Idempotent backfill of system-generated OFFICIAL_NOTICE tender documents (D1-03).

Uses the same set-wise function as source refresh, so a re-run creates nothing,
rewrites nothing whose text is unchanged, and never deletes. Without --apply the
run only reports what it would do.

    python scripts/backfill_official_notices.py                 # report only
    python scripts/backfill_official_notices.py --apply --confirm BACKFILL_OFFICIAL_NOTICES
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
import json
from pathlib import Path
import sys
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import func, select
from sqlalchemy.orm import load_only

from app.db.session import AsyncSessionLocal, engine
from app.models.all_models import Tender, TenderDocument, TenderStatus
from app.services.official_notice import (
    OFFICIAL_NOTICE_BATCH_SIZE,
    OFFICIAL_NOTICE_MIN_CHARS,
    OfficialNoticeSyncResult,
    only_official_notice,
    sync_official_notices,
)

CONFIRMATION = "BACKFILL_OFFICIAL_NOTICES"
TENDER_COLUMNS = (
    Tender.id, Tender.source_system, Tender.external_id, Tender.canonical_source_key,
    Tender.source_url, Tender.title, Tender.description, Tender.notice_type,
    Tender.buyer, Tender.country, Tender.publication_date, Tender.deadline,
    Tender.source_metadata_json, Tender.status,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    command.add_argument("--apply", action="store_true", help="Write the documents. Default is report only.")
    command.add_argument("--confirm", default="", help=f"Required with --apply: {CONFIRMATION}")
    command.add_argument("--source", action="append", default=[], help="Limit to a source_system (repeatable).")
    command.add_argument("--include-closed", action="store_true", help="Also cover tenders that are not OPEN.")
    command.add_argument("--batch-size", type=int, default=200, help="Tenders per transaction (1-%d)." % OFFICIAL_NOTICE_BATCH_SIZE)
    command.add_argument("--json", action="store_true", help="Print the report as JSON.")
    return command


def _scope(statement, *, sources: list[str], include_closed: bool):
    if not include_closed:
        statement = statement.where(Tender.status == TenderStatus.OPEN)
    if sources:
        statement = statement.where(Tender.source_system.in_(sources))
    return statement


async def backfill(
    *, apply: bool, sources: list[str], include_closed: bool, batch_size: int
) -> dict[str, Any]:
    per_source: dict[str, OfficialNoticeSyncResult] = defaultdict(OfficialNoticeSyncResult)
    async with AsyncSessionLocal() as db:
        last_id = None
        while True:
            statement = _scope(
                select(Tender).options(load_only(*TENDER_COLUMNS)),
                sources=sources,
                include_closed=include_closed,
            ).order_by(Tender.id).limit(batch_size)
            if last_id is not None:
                statement = statement.where(Tender.id > last_id)
            batch = list((await db.execute(statement)).scalars())
            if not batch:
                break
            last_id = batch[-1].id
            grouped: dict[str, list[Tender]] = defaultdict(list)
            for tender in batch:
                grouped[tender.source_system].append(tender)
            for source, tenders in grouped.items():
                per_source[source] = per_source[source] + await sync_official_notices(
                    db, tenders, dry_run=not apply, batch_size=batch_size
                )
            if apply:
                await db.commit()
            else:
                await db.rollback()
            db.expunge_all()

        open_counts = dict(
            (
                await db.execute(
                    _scope(
                        select(Tender.source_system, func.count(Tender.id)),
                        sources=sources,
                        include_closed=include_closed,
                    ).group_by(Tender.source_system)
                )
            ).all()
        )
        covered_counts = dict(
            (
                await db.execute(
                    _scope(
                        select(Tender.source_system, func.count(TenderDocument.id))
                        .join(TenderDocument, TenderDocument.tender_id == Tender.id)
                        .where(only_official_notice()),
                        sources=sources,
                        include_closed=include_closed,
                    ).group_by(Tender.source_system)
                )
            ).all()
        )
    report: dict[str, Any] = {
        "mode": "apply" if apply else "report-only",
        "scope": "all statuses" if include_closed else "open tenders",
        "min_notice_chars": OFFICIAL_NOTICE_MIN_CHARS,
        "sources": {},
    }
    for source in sorted(set(open_counts) | set(per_source)):
        result = per_source[source]
        report["sources"][source] = {
            "tenders": int(open_counts.get(source, 0)),
            "substantive_notice": result.created + result.updated + result.unchanged,
            "created": result.created,
            "updated": result.updated,
            "unchanged": result.unchanged,
            "below_threshold_or_empty": result.skipped,
            "failed": result.failed,
            "with_notice_document_now": int(covered_counts.get(source, 0)),
        }
    return report


def render(report: dict[str, Any]) -> str:
    columns = (
        "tenders", "substantive_notice", "created", "updated", "unchanged",
        "below_threshold_or_empty", "failed", "with_notice_document_now",
    )
    lines = [
        f"OFFICIAL_NOTICE backfill ({report['mode']}; {report['scope']}; notice >= {report['min_notice_chars']} chars)",
        f"{'source':<14}" + "".join(f"{name:>26}" for name in columns),
    ]
    for source, values in report["sources"].items():
        lines.append(f"{source:<14}" + "".join(f"{values[name]:>26}" for name in columns))
    lines.append(
        f"{'TOTAL':<14}" + "".join(
            f"{sum(v[name] for v in report['sources'].values()):>26}" for name in columns
        )
    )
    if report["mode"] == "report-only":
        lines.append("Report only: nothing was written. Re-run with --apply --confirm %s." % CONFIRMATION)
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not 1 <= args.batch_size <= OFFICIAL_NOTICE_BATCH_SIZE:
        print(f"--batch-size must be between 1 and {OFFICIAL_NOTICE_BATCH_SIZE}", file=sys.stderr)
        return 2
    if args.apply and args.confirm != CONFIRMATION:
        print(f"--apply requires --confirm {CONFIRMATION}", file=sys.stderr)
        return 2
    try:
        report = await backfill(
            apply=args.apply,
            sources=[item.strip().casefold() for item in args.source if item.strip()],
            include_closed=args.include_closed,
            batch_size=args.batch_size,
        )
    finally:
        await engine.dispose()
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
