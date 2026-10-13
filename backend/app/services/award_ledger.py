"""Sprint 1: award ledger v0 ingestion (World Bank contract-award notices).

The World Bank connector skips "Contract Award" notices (they are not opportunities). This
service reads exactly those notices from the same public procurement API, newest first, and
appends them to the ledger: one raw snapshot per notice and content hash, and one row per
bidder parsed deterministically by ``award_ledger_parser``. Re-running is idempotent: an
unchanged notice (same content hash) is skipped; a changed one is a new snapshot.

The API has no date filter, so each country is paged by notice date (newest first) until a
whole page is older than the window. Consultant Services are read first, then every other
procurement group.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, AsyncIterator, Awaitable, Callable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.award_ledger import AwardNoticeSnapshot, AwardOutcome
from app.services.award_ledger_parser import (
    KIND_INDIVIDUAL,
    PARSER_VERSION,
    normalize_firm_name,
    parse_money,
    parse_world_bank_award_notice,
)
from app.services.tender_sources.world_bank import (
    WORLD_BANK_PROC_DETAIL_URL,
    WORLD_BANK_PROC_NOTICES_URL,
    parse_world_bank_publication_date,
)

logger = logging.getLogger(__name__)

LENDER_WORLD_BANK = "WORLD_BANK"
AWARD_NOTICE_TYPE = "Contract Award"
LEDGER_COUNTRIES = ("Uzbekistan", "Kazakhstan", "Kyrgyz Republic", "Tajikistan")
CONSULTING_GROUP_CODE = "CS"
CONSULTING_GROUP = "Consultant Services"
# Individual Consultant Selection awards go to a person; some notices name them. Every bidder of
# such a notice is an individual, whatever the notice prints, and never enters a firm list.
INDIVIDUAL_SELECTION_METHOD = "Individual Consultant Selection"
DEFAULT_WINDOW_MONTHS = 24
PAGE_ROWS = 100
MAX_PAGES_PER_PASS = 60
# api_modified_date changes on re-indexing without any change to the notice itself.
_VOLATILE_KEYS = {"api_modified_date"}

FetchPage = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def window_start(today: date, months: int = DEFAULT_WINDOW_MONTHS) -> date:
    return today - timedelta(days=round(months * 365.25 / 12))


def content_hash(row: dict[str, Any]) -> str:
    stable = {key: value for key, value in row.items() if key not in _VOLATILE_KEYS}
    canonical = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _text(value: Any, limit: int | None = None) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    return text[:limit] if limit else text


def _sectors(row: dict[str, Any]) -> list[str]:
    values = row.get("sector")
    if not isinstance(values, list):
        return []
    names = [_text(item.get("sector_description"), 120) for item in values if isinstance(item, dict)]
    return list(dict.fromkeys(name for name in names if name))


def build_snapshot(row: dict[str, Any], *, retrieved_at: datetime) -> tuple[AwardNoticeSnapshot, list[AwardOutcome]]:
    """Pure: one API row -> the snapshot and its bidder rows (not added to a session)."""
    notice_id = _text(row.get("id"), 64)
    if not notice_id:
        raise ValueError("World Bank notice id is required")
    raw_text = row.get("notice_text")
    parsed = parse_world_bank_award_notice(raw_text)
    published = parse_world_bank_publication_date(row)
    digest = content_hash(row)
    common = {
        "lender": LENDER_WORLD_BANK,
        "country": _text(row.get("project_ctry_name"), 120),
        "project_id": _text(row.get("project_id"), 40),
        "project_name": _text(row.get("project_name"), 500),
        "notice_id": notice_id,
        "notice_url": WORLD_BANK_PROC_DETAIL_URL.format(id=notice_id),
        "notice_date": published.date() if published else None,
        "award_date": parsed.award_date,
        "package_reference": _text(row.get("bid_reference_no"), 200),
        "package_title": _text(row.get("bid_description") or row.get("noticetitle")),
        "procurement_group": _text(row.get("procurement_group_desc"), 80),
        "procurement_method": _text(row.get("procurement_method_name"), 120),
    }
    snapshot = AwardNoticeSnapshot(
        **common,
        notice_type=_text(row.get("notice_type"), 80),
        notice_version=_text(parsed.notice_version or row.get("notice_version_no"), 20),
        market_approach=_text(row.get("market_approach_region_name") or row.get("market_approach_name"), 80),
        contract_duration=parsed.contract_duration,
        sectors=_sectors(row),
        raw_text=str(raw_text) if raw_text else None,
        raw_metadata={key: value for key, value in row.items() if key != "notice_text"},
        content_hash=digest,
        parser_version=PARSER_VERSION,
        parse_status="PARSED" if parsed.bids else "NO_BIDDERS",
        retrieved_at=retrieved_at,
    )
    snapshot.id = uuid4()
    outcomes: list[AwardOutcome] = []
    individual_selection = common["procurement_method"] == INDIVIDUAL_SELECTION_METHOD
    for bid_ordinal, bid in enumerate(parsed.bids, start=1):
        evaluated_currency, evaluated_amount = parse_money(bid.evaluated_price)
        signed_currency, signed_amount = parse_money(bid.signed_contract_price)
        for member_ordinal, member in enumerate(bid.members, start=1):
            outcomes.append(AwardOutcome(
                **common,
                snapshot_id=snapshot.id,
                bid_ordinal=bid_ordinal,
                member_ordinal=member_ordinal,
                member_count=len(bid.members),
                bidder_name=member.name[:500],
                bidder_name_normalized=normalize_firm_name(member.name)[:500],
                bidder_source_id=member.source_id,
                bidder_country=member.country,
                bidder_kind=KIND_INDIVIDUAL if individual_selection else member.kind,
                status=bid.status,
                evaluated_price_text=bid.evaluated_price,
                evaluated_price_currency=evaluated_currency,
                evaluated_price_amount=evaluated_amount,
                signed_contract_price_text=bid.signed_contract_price,
                signed_contract_currency=signed_currency,
                signed_contract_amount=signed_amount,
                bid_price_at_opening_text=bid.bid_price_at_opening,
                scores=dict(bid.scores),
                rejection_reason=bid.rejection_reason,
                content_hash=digest,
                parser_version=PARSER_VERSION,
                retrieved_at=retrieved_at,
            ))
    snapshot.bidder_row_count = len(outcomes)
    return snapshot, outcomes


@dataclass
class IngestReport:
    since: date
    countries: tuple[str, ...]
    pages_fetched: int = 0
    notices_seen: int = 0
    notices_undated: int = 0
    snapshots_created: int = 0
    snapshots_unchanged: int = 0
    notices_without_bidders: int = 0
    rows_inserted: int = 0
    rows_by_country_status: Counter = field(default_factory=Counter)
    rows_by_country_group: Counter = field(default_factory=Counter)
    truncated_passes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "since": self.since.isoformat(),
            "countries": list(self.countries),
            "pages_fetched": self.pages_fetched,
            "notices_seen": self.notices_seen,
            "notices_undated": self.notices_undated,
            "snapshots_created": self.snapshots_created,
            "snapshots_unchanged": self.snapshots_unchanged,
            "notices_without_bidders": self.notices_without_bidders,
            "rows_inserted": self.rows_inserted,
            "rows_by_country_status": {
                f"{country}|{status}": count for (country, status), count in sorted(self.rows_by_country_status.items())
            },
            "rows_by_country_group": {
                f"{country}|{group}": count for (country, group), count in sorted(self.rows_by_country_group.items())
            },
            "truncated_passes": self.truncated_passes,
        }


def world_bank_fetch_page(*, timeout_seconds: float = 60.0, max_retries: int = 2) -> FetchPage:
    """One GET of the public procurement-notices API with the connector's retry shape."""

    async def fetch(params: dict[str, Any]) -> dict[str, Any]:
        import httpx

        attempt = 0
        async with httpx.AsyncClient(
            timeout=timeout_seconds, headers={"User-Agent": "PlasmaOS AwardLedger/1.0"}
        ) as client:
            while True:
                try:
                    response = await client.get(WORLD_BANK_PROC_NOTICES_URL, params=params)
                    response.raise_for_status()
                    payload = response.json()
                    return payload if isinstance(payload, dict) else {}
                except Exception:
                    if attempt >= max_retries:
                        raise
                    attempt += 1
                    await asyncio.sleep(1.0 * attempt)

    return fetch


async def iter_award_notices(
    fetch: FetchPage,
    *,
    country: str,
    since: date,
    procurement_group_code: str | None = None,
    request_delay_seconds: float = 0.25,
    report: IngestReport | None = None,
) -> AsyncIterator[list[dict[str, Any]]]:
    """Pages of award notices for one country, newest first, dated on or after ``since``."""
    for page_index in range(MAX_PAGES_PER_PASS):
        params: dict[str, Any] = {
            "format": "json", "apilang": "en", "fl": "*", "rows": PAGE_ROWS, "os": page_index * PAGE_ROWS,
            "notice_type_exact": AWARD_NOTICE_TYPE, "project_ctry_name_exact": country,
            "srt": "noticedate", "order": "desc",
        }
        if procurement_group_code:
            params["procurement_group_exact"] = procurement_group_code
        payload = await fetch(params)
        if report is not None:
            report.pages_fetched += 1
        rows = [row for row in (payload.get("procnotices") or []) if isinstance(row, dict)]
        in_window: list[dict[str, Any]] = []
        older = 0
        for row in rows:
            published = parse_world_bank_publication_date(row)
            if published is None:
                if report is not None:
                    report.notices_undated += 1
                continue
            if published.date() < since:
                older += 1
                continue
            in_window.append(row)
        if in_window:
            yield in_window
        if not rows or len(rows) < PAGE_ROWS or older == len(rows):
            return
        if request_delay_seconds:
            await asyncio.sleep(request_delay_seconds)
    if report is not None:
        report.truncated_passes.append(f"{country}|{procurement_group_code or 'ALL'}")


async def ingest_world_bank_awards(
    db: AsyncSession,
    *,
    fetch: FetchPage | None = None,
    countries: tuple[str, ...] = LEDGER_COUNTRIES,
    since: date | None = None,
    consulting_only: bool = False,
    now: datetime | None = None,
    request_delay_seconds: float = 0.25,
) -> IngestReport:
    """Append new and changed award notices; commit once per page."""
    now = now or datetime.now(timezone.utc)
    since = since or window_start(now.date())
    fetch = fetch or world_bank_fetch_page()
    report = IngestReport(since=since, countries=tuple(countries))
    for country in countries:
        seen: set[str] = set()
        passes: list[str | None] = [CONSULTING_GROUP_CODE] if consulting_only else [CONSULTING_GROUP_CODE, None]
        for group_code in passes:
            async for page in iter_award_notices(
                fetch, country=country, since=since, procurement_group_code=group_code,
                request_delay_seconds=request_delay_seconds, report=report,
            ):
                fresh = [row for row in page if str(row.get("id") or "").strip() not in seen]
                seen.update(str(row.get("id") or "").strip() for row in page)
                if not fresh:
                    continue
                await _append_page(db, fresh, retrieved_at=now, report=report)
    return report


async def _append_page(
    db: AsyncSession, rows: list[dict[str, Any]], *, retrieved_at: datetime, report: IngestReport
) -> None:
    built = []
    for row in rows:
        try:
            built.append(build_snapshot(row, retrieved_at=retrieved_at))
        except ValueError:
            continue
    report.notices_seen += len(built)
    if not built:
        return
    keys = {(snapshot.notice_id, snapshot.content_hash) for snapshot, _ in built}
    existing = set((await db.execute(
        select(AwardNoticeSnapshot.notice_id, AwardNoticeSnapshot.content_hash).where(
            AwardNoticeSnapshot.lender == LENDER_WORLD_BANK,
            AwardNoticeSnapshot.notice_id.in_([notice_id for notice_id, _ in keys]),
        )
    )).all())
    for snapshot, outcomes in built:
        if (snapshot.notice_id, snapshot.content_hash) in existing:
            report.snapshots_unchanged += 1
            continue
        existing.add((snapshot.notice_id, snapshot.content_hash))
        db.add(snapshot)
        report.snapshots_created += 1
        if not outcomes:
            report.notices_without_bidders += 1
        for outcome in outcomes:
            db.add(outcome)
            report.rows_inserted += 1
            report.rows_by_country_status[(outcome.country or "", outcome.status)] += 1
            report.rows_by_country_group[(outcome.country or "", outcome.procurement_group or "")] += 1
        await db.flush()
    await db.commit()
