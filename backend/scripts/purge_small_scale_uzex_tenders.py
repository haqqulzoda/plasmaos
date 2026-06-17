#!/usr/bin/env python3
"""Report or purge confirmed small-scale UzEx tenders from the active DB."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, func, select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import AsyncSessionLocal
from app.models import all_models as _all_models  # noqa: F401
from app.models.all_models import Proposal, Tender, TenderDocument, TenderSyncJob
from app.models.audit import AuditLog, TenderAnalysis, TenderRecommendation
from app.models.taxonomy import RiskOverrideLog, TenderRequirement
from app.services.tender_sources.uzex_scope import (
    customer_visible_tender_condition,
    uzex_source_metadata,
    uzex_enterprise_tender_condition,
    uzex_small_scale_tender_condition,
)
from app.services.tender_sources.uzex_constants import (
    UZEX_ENTERPRISE_ROUTE,
    UZEX_ENTERPRISE_TYPE_ID,
    UZEX_SMALL_SCALE_ROUTE,
    UZEX_SMALL_SCALE_TYPE_ID,
)


DEPENDENT_MODELS = (
    ("documents", TenderDocument),
    ("analyses", TenderAnalysis),
    ("proposals", Proposal),
    ("sync_jobs", TenderSyncJob),
    ("recommendations", TenderRecommendation),
    ("requirements", TenderRequirement),
    ("risk_overrides", RiskOverrideLog),
)

Classification = str
UZEX_LARGE_SUPPORTED: Classification = "uzex_large_supported"
UZEX_SMALL_UNSUPPORTED: Classification = "uzex_small_unsupported"
UZEX_UNKNOWN: Classification = "uzex_unknown"


async def _count(session: Any, statement: Any) -> int:
    result = await session.execute(statement)
    return int(result.scalar_one() or 0)


async def _dependent_counts(session: Any, tender_ids: list[Any]) -> dict[str, int]:
    if not tender_ids:
        return {
            "documents": 0,
            "analyses": 0,
            "proposals": 0,
            "sync_jobs": 0,
            "recommendations": 0,
            "requirements": 0,
            "risk_overrides": 0,
            "audit_logs": 0,
        }
    counts: dict[str, int] = {}
    for label, model in DEPENDENT_MODELS:
        counts[label] = await _count(
            session,
            select(func.count()).select_from(model).where(model.tender_id.in_(tender_ids)),
        )
    counts["audit_logs"] = await _count(
        session,
        select(func.count())
        .select_from(AuditLog)
        .join(TenderAnalysis, AuditLog.analysis_id == TenderAnalysis.id)
        .where(TenderAnalysis.tender_id.in_(tender_ids)),
    )
    return counts


async def _fetch_live_uzex_ids(type_id: int, *, limit: int = 5000) -> tuple[set[str], int]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://apietender.uzex.uz/api/common/TradeList",
            json={
                "TypeId": type_id,
                "From": 1,
                "To": limit,
                "System_Id": 0,
            },
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list):
        return set(), 0
    return {
        str(row.get("id")).strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }, len(rows)


def _metadata_text(metadata: Any) -> str:
    if metadata is None:
        return ""
    try:
        return json.dumps(metadata, ensure_ascii=False).casefold()
    except TypeError:
        return str(metadata).casefold()


def _metadata_type_id(metadata: Any) -> int | None:
    if not isinstance(metadata, dict):
        return None
    for key in ("uzex_type_id", "type_id", "typeid", "TypeId"):
        value = metadata.get(key)
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _classify_uzex_tender(
    tender: Tender,
    *,
    type1_ids: set[str],
    type2_ids: set[str],
) -> tuple[Classification, str]:
    source_url = (tender.source_url or "").casefold()
    metadata = tender.source_metadata_json
    metadata_text = _metadata_text(metadata)
    metadata_type_id = _metadata_type_id(metadata)
    external_id = str(tender.external_id or "").strip()

    small_evidence = (
        UZEX_SMALL_SCALE_ROUTE in source_url
        or UZEX_SMALL_SCALE_ROUTE in metadata_text
        or metadata_type_id == UZEX_SMALL_SCALE_TYPE_ID
        or external_id in type1_ids
    )
    large_evidence = (
        UZEX_ENTERPRISE_ROUTE in source_url
        or UZEX_ENTERPRISE_ROUTE in metadata_text
        or metadata_type_id == UZEX_ENTERPRISE_TYPE_ID
        or external_id in type2_ids
    )

    if small_evidence and large_evidence:
        return UZEX_UNKNOWN, "conflicting small and large evidence"
    if small_evidence:
        return UZEX_SMALL_UNSUPPORTED, "matched /lots/1/ route metadata or live TypeId=1"
    if large_evidence:
        return UZEX_LARGE_SUPPORTED, "matched /lots/2/ route metadata or live TypeId=2"
    return UZEX_UNKNOWN, "no route/type evidence found"


def _metadata_with_classification(
    existing: Any,
    *,
    classification: Classification,
    type_id: int,
    evidence: str,
) -> dict[str, Any]:
    metadata = dict(existing) if isinstance(existing, dict) else {}
    metadata.update(uzex_source_metadata(type_id=type_id))
    metadata["uzex_scope_classification"] = classification
    metadata["uzex_scope_evidence"] = evidence
    return metadata


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Classify stored UzEx tenders and optionally hard-delete confirmed "
            "small-scale /lots/1/ rows. Unknown rows are never deleted."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the hard delete. Without this flag the script reports only.",
    )
    parser.add_argument(
        "--show-ids",
        type=int,
        default=50,
        help="Maximum matching tender IDs to print before deletion.",
    )
    parser.add_argument(
        "--live-limit",
        type=int,
        default=5000,
        help="Maximum rows to ask UzEx TradeList for each TypeId.",
    )
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        type1_ids, type1_rows = await _fetch_live_uzex_ids(
            UZEX_SMALL_SCALE_TYPE_ID,
            limit=args.live_limit,
        )
        type2_ids, type2_rows = await _fetch_live_uzex_ids(
            UZEX_ENTERPRISE_TYPE_ID,
            limit=args.live_limit,
        )

        source_counts = {
            "uzex_lots_1_route_tagged": await _count(
                session,
                select(func.count()).select_from(Tender).where(
                    uzex_small_scale_tender_condition(Tender)
                ),
            ),
            "uzex_lots_2_route_tagged": await _count(
                session,
                select(func.count()).select_from(Tender).where(
                    uzex_enterprise_tender_condition(Tender)
                ),
            ),
            "world_bank": await _count(
                session,
                select(func.count()).select_from(Tender).where(
                    Tender.source_system == "world_bank"
                ),
            ),
            "adb": await _count(
                session,
                select(func.count()).select_from(Tender).where(
                    Tender.source_system == "adb"
                ),
            ),
            "customer_visible_after_filter": await _count(
                session,
                select(func.count()).select_from(Tender).where(
                    customer_visible_tender_condition(Tender)
                ),
            ),
        }

        result = await session.execute(
            select(Tender)
            .where(Tender.source_system == "uzex")
            .order_by(Tender.created_at.asc())
        )
        uzex_tenders = list(result.scalars().all())
        classified: dict[Classification, list[tuple[Tender, str]]] = {
            UZEX_LARGE_SUPPORTED: [],
            UZEX_SMALL_UNSUPPORTED: [],
            UZEX_UNKNOWN: [],
        }
        for tender in uzex_tenders:
            classification, evidence = _classify_uzex_tender(
                tender,
                type1_ids=type1_ids,
                type2_ids=type2_ids,
            )
            classified[classification].append((tender, evidence))

        small_matches = classified[UZEX_SMALL_UNSUPPORTED]
        large_matches = classified[UZEX_LARGE_SUPPORTED]
        unknown_matches = classified[UZEX_UNKNOWN]
        tender_ids = [tender.id for tender, _ in small_matches]

        print("Source counts:")
        for label, count in source_counts.items():
            print(f"  {label}: {count}")

        print("\nLive UzEx TradeList evidence:")
        print(f"  TypeId=1 rows: {type1_rows} unique_ids: {len(type1_ids)}")
        print(f"  TypeId=2 rows: {type2_rows} unique_ids: {len(type2_ids)}")

        print("\nStored UzEx classification:")
        print(f"  {UZEX_SMALL_UNSUPPORTED}: {len(small_matches)}")
        print(f"  {UZEX_LARGE_SUPPORTED}: {len(large_matches)}")
        print(f"  {UZEX_UNKNOWN}: {len(unknown_matches)}")

        print(f"\nSmall-scale UzEx tenders matched for deletion: {len(small_matches)}")
        for tender, evidence in small_matches[: max(args.show_ids, 0)]:
            print(
                f"  {tender.id} external_id={tender.external_id} "
                f"source_url={tender.source_url} evidence={evidence}"
            )
        if args.show_ids >= 0 and len(small_matches) > args.show_ids:
            print(f"  ... {len(small_matches) - args.show_ids} more")

        if unknown_matches:
            print("\nUnknown UzEx rows left untouched and hidden from customer APIs:")
            for tender, evidence in unknown_matches[: max(args.show_ids, 0)]:
                print(
                    f"  {tender.id} external_id={tender.external_id} "
                    f"source_url={tender.source_url} evidence={evidence}"
                )
            if args.show_ids >= 0 and len(unknown_matches) > args.show_ids:
                print(f"  ... {len(unknown_matches) - args.show_ids} more")

        dependent_counts = await _dependent_counts(session, tender_ids)
        print("\nDependent rows covered by tender FK cascades:")
        for label, count in dependent_counts.items():
            print(f"  {label}: {count}")

        if not args.apply:
            await session.rollback()
            print("\nDry run only. Re-run with --apply to delete these tenders.")
            return

        for tender, evidence in large_matches:
            tender.source_metadata_json = _metadata_with_classification(
                tender.source_metadata_json,
                classification=UZEX_LARGE_SUPPORTED,
                type_id=UZEX_ENTERPRISE_TYPE_ID,
                evidence=evidence,
            )

        if tender_ids:
            await session.execute(delete(Tender).where(Tender.id.in_(tender_ids)))
        await session.commit()
        print(f"\nDeleted {len(tender_ids)} small-scale UzEx tenders.")
        print(f"Tagged {len(large_matches)} confirmed enterprise UzEx tenders.")


if __name__ == "__main__":
    asyncio.run(main())
