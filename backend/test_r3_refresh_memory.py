"""R3: a World Bank source refresh holds one listing page, not the whole listing.

Runs the real refresh path (sync: normalize, persist with the official-notice hook, project
links, documents; then the competitor-cache pass) against a disposable PostgreSQL database
with synthetic listing pages at two listing sizes, and asserts the traced Python peak does not
grow with the listing. Before R3 the whole listing, every normalized row and every ORM row
(and every competitor target) were held until the commit, so the peak grew with every page.
The production-shaped measurement (recorded pages, RSS) is in docs/ops/REFRESH_MEMORY.md.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import tracemalloc
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.endpoints import tenders
from app.services.tender_sources.world_bank import WorldBankTenderSource
from scripts import test_s0_5b4_baseline as support

ROWS_PER_PAGE = 100
NOTICE_TEXT_CHARS = 24_000  # a long World Bank REOI/IFB notice (production median ~40 KB of JSON per row)
SMALL_PAGES = 2
LARGE_PAGES = 8


def _notice(index: int) -> dict:
    deadline = datetime.now(timezone.utc).date() + timedelta(days=30 + index % 40)
    paragraph = (
        f"<p>Lot {index}: consulting services for design review, construction supervision and "
        "capacity building of the implementing agency, including environmental and social "
        "safeguards, quality assurance and reporting to the World Bank. </p>"
    )
    return {
        "id": f"OPR3{index:06d}",
        "notice_type": "Request for Expression of Interest",
        "notice_status": "Published",
        "noticetitle": f"Consulting services, lot {index}",
        "bid_description": f"Design and supervision consultant, lot {index}",
        "notice_text": (paragraph * (NOTICE_TEXT_CHARS // len(paragraph) + 1))[:NOTICE_TEXT_CHARS],
        "noticedate": "01-Oct-2026",
        "submission_date": "2026-10-01T00:00:00Z",
        "submission_deadline_date": f"{deadline.isoformat()}T00:00:00Z",
        "submission_deadline_time": "10:00",
        "project_ctry_name": "Uzbekistan",
        "regionname": "Europe and Central Asia",
        "sector": [{"sector_description": "Water Supply"}],
        "agency_name": "Ministry of Water Resources",
        "procurement_group_desc": "Consultant Services",
        "procurement_method_name": "Quality And Cost-Based Selection",
        "project_id": f"P9{index % 60:05d}",
    }


def _listing(first_index: int, pages: int):
    total = pages * ROWS_PER_PAGE

    async def get_json(self, client, params):  # built per request, like response.json()
        page = int(params["os"]) // ROWS_PER_PAGE
        if page >= pages:
            return {"procnotices": [], "total": total}
        start = first_index + page * ROWS_PER_PAGE
        return {"procnotices": [_notice(start + i) for i in range(ROWS_PER_PAGE)], "total": total}

    return get_json


async def _refresh_peak(sessions, *, first_index: int, pages: int) -> tuple[int, object, dict]:
    enrichment = AsyncMock(return_value=SimpleNamespace(claimed=0, enqueued=0, dispatch_failed=0))
    with (
        patch.object(WorldBankTenderSource, "_get_json", _listing(first_index, pages)),
        patch.object(tenders, "enqueue_world_bank_project_enrichment_batch", new=enrichment),
        patch.object(tenders, "_live_source_competitor_records", new=AsyncMock(return_value=[])),
    ):
        tracemalloc.start()
        try:
            async with sessions() as db:
                response = await tenders.sync_world_bank_tenders(
                    max_pages=25, rows=ROWS_PER_PAGE, active_only=True, dry_run=False, db=db,
                )
            async with sessions() as db:
                cache = await tenders._refresh_source_competitor_cache(db=db, source_system="world_bank")
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    return peak, response, cache


def test_world_bank_refresh_peak_does_not_grow_with_the_listing() -> None:
    async def run() -> tuple[int, int, object, object, dict]:
        database = support.database_name("r3_refresh_memory")
        await support.create_database(database)
        engine = None
        try:
            bootstrap = await asyncio.to_thread(support.run_bootstrap, database)
            assert bootstrap.returncode == 0, bootstrap.stderr or bootstrap.stdout
            engine = create_async_engine(support.target_url(database))
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            small, small_response, _ = await _refresh_peak(sessions, first_index=0, pages=SMALL_PAGES)
            large, large_response, cache = await _refresh_peak(sessions, first_index=10_000, pages=LARGE_PAGES)
            return small, large, small_response, large_response, cache
        finally:
            if engine is not None:
                await engine.dispose()
            await support.drop_database(database)

    small, large, small_response, large_response, cache = asyncio.run(run())

    # Same results as an unbounded refresh: every notice persisted, every visible target considered.
    assert (small_response.status, small_response.created_count) == ("success", SMALL_PAGES * ROWS_PER_PAGE)
    assert (large_response.status, large_response.created_count) == ("success", LARGE_PAGES * ROWS_PER_PAGE)
    assert large_response.fetched_count == LARGE_PAGES * ROWS_PER_PAGE and large_response.failed_count == 0
    assert cache["targets_considered"] == (SMALL_PAGES + LARGE_PAGES) * ROWS_PER_PAGE

    mib = 1024 * 1024
    print(f"R3 refresh traced peak: {small / mib:.1f} MiB ({SMALL_PAGES} pages), {large / mib:.1f} MiB ({LARGE_PAGES} pages)")
    extra_text = (LARGE_PAGES - SMALL_PAGES) * ROWS_PER_PAGE * NOTICE_TEXT_CHARS
    # Six more pages (14 MB more notice text, five times more competitor targets) may cost a
    # little (one page is ~2.4 MB of text), never the listing: unbounded, it grew by several
    # times the extra text.
    assert large - small < extra_text // 2, (
        f"refresh peak grew with the listing: {small / mib:.1f} MiB for {SMALL_PAGES} pages, "
        f"{large / mib:.1f} MiB for {LARGE_PAGES} pages"
    )
    assert large < 64 * mib, f"refresh peak {large / mib:.1f} MiB for {LARGE_PAGES} pages"
