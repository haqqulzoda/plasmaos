"""Sprint 1: award ledger reads, CSV exports, the firm export and market sizing.

Every read uses the newest snapshot of each notice (the ledger is append-only, so an older
snapshot of a re-published notice stays stored but is not counted). Exports carry public
notice data only: names, countries, notice ids/links, statuses, prices and reasons as
published. Individual consultants (published anonymised as "Individual Consultant") are
never in the firm export or the market sizing.
"""

from __future__ import annotations

import csv
import io
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.award_ledger import AwardNoticeSnapshot, AwardOutcome
from app.services.award_ledger import (
    CONSULTING_GROUP,
    DEFAULT_WINDOW_MONTHS,
    INDIVIDUAL_SELECTION_METHOD,
    window_start,
)
from app.services.award_ledger_fx import FX_DATE, FX_SOURCE, FX_URL, UZS_PER_UNIT, to_usd, usd_per_unit
from app.services.award_ledger_parser import name_flag, non_firm_reason, normalize_firm_name

LENDER_LABELS = {"WORLD_BANK": "World Bank", "ADB": "ADB", "EBRD": "EBRD"}
MARKET_SIZING_COUNTRIES = ("Uzbekistan", "Kyrgyz Republic", "Tajikistan", "Kazakhstan")
BID_BUCKETS = ((1, 1, "1"), (2, 2, "2"), (3, 5, "3-5"), (6, 10, "6-10"), (11, 10**9, "11+"))
# Bidder-country spellings that name the project country.
_COUNTRY_ALIASES = {
    "KYRGYZSTAN": "KYRGYZ REPUBLIC",
    "TURKEY": "TURKIYE",
    "REPUBLIC OF UZBEKISTAN": "UZBEKISTAN",
    "REPUBLIC OF KAZAKHSTAN": "KAZAKHSTAN",
}

OUTCOME_CSV_COLUMNS = (
    "lender", "country", "project_id", "project_name", "notice_id", "notice_url", "notice_date", "award_date",
    "package_reference", "package_title", "procurement_group", "procurement_method", "bid_ordinal",
    "member_ordinal", "member_count", "bidder_name", "bidder_name_normalized", "bidder_source_id",
    "bidder_country", "bidder_kind", "status", "evaluated_price_text", "evaluated_price_currency",
    "evaluated_price_amount", "signed_contract_price_text", "signed_contract_currency", "signed_contract_amount",
    "bid_price_at_opening_text", "rejection_reason", "retrieved_at", "content_hash", "parser_version",
)
FIRM_CSV_COLUMNS = (
    "normalized_name", "display_name", "country", "participations", "awards", "rejections", "lenders",
    "countries_bid", "procurement_groups", "sectors", "first_activity", "last_activity", "world_bank_supplier_ids",
    "example_1_title", "example_1_url", "example_2_title", "example_2_url", "example_3_title", "example_3_url",
)
MARKET_CSV_COLUMNS = ("metric", "category", "country", "lender", "sector", "segment", "value", "unit", "note")


def is_firm():
    """Firm rows only. Read-time too: rows stored before ICS rows were marked individual."""
    return and_(
        AwardOutcome.bidder_kind == "FIRM",
        func.coalesce(AwardOutcome.procurement_method, "") != INDIVIDUAL_SELECTION_METHOD,
    )


INDIVIDUAL_LABEL = "Individual consultant"
_MASKED_COLUMNS = ("bidder_name", "bidder_name_normalized", "bidder_source_id")


def is_individual_row(row: AwardOutcome) -> bool:
    return row.bidder_kind != "FIRM" or row.procurement_method == INDIVIDUAL_SELECTION_METHOD


def outcome_values(row: AwardOutcome, columns: Iterable[str]) -> dict[str, Any]:
    """A row for display or export: an individual consultant is never named (the raw notice keeps it)."""
    values = {column: getattr(row, column) for column in columns}
    if is_individual_row(row):
        for column in _MASKED_COLUMNS:
            if column in values:
                values[column] = INDIVIDUAL_LABEL if column == "bidder_name" else None
    return values


def country_key(value: str | None) -> str:
    key = re.sub(r"\s+", " ", (value or "").strip().upper())
    return _COUNTRY_ALIASES.get(key, key)


def latest_snapshot_ids() -> Select:
    # All descending so ix_award_notice_snapshots_lender_notice serves it as a backward
    # index-only scan (the snapshot rows themselves are wide: raw text and metadata).
    return (
        select(AwardNoticeSnapshot.id)
        .distinct(AwardNoticeSnapshot.lender, AwardNoticeSnapshot.notice_id)
        .order_by(
            AwardNoticeSnapshot.lender.desc(), AwardNoticeSnapshot.notice_id.desc(),
            AwardNoticeSnapshot.retrieved_at.desc(), AwardNoticeSnapshot.id.desc(),
        )
    )


@dataclass(frozen=True)
class OutcomeFilters:
    country: str | None = None
    status: str | None = None
    procurement_group: str | None = None
    lender: str | None = None
    q: str | None = None


def _filtered(statement: Select, filters: OutcomeFilters) -> Select:
    statement = statement.where(AwardOutcome.snapshot_id.in_(latest_snapshot_ids()))
    if filters.country:
        statement = statement.where(AwardOutcome.country == filters.country)
    if filters.status:
        statement = statement.where(AwardOutcome.status == filters.status)
    if filters.procurement_group:
        statement = statement.where(AwardOutcome.procurement_group == filters.procurement_group)
    if filters.lender:
        statement = statement.where(AwardOutcome.lender == filters.lender)
    if filters.q:
        pattern = f"%{filters.q.strip()}%"
        statement = statement.where(or_(
            AwardOutcome.bidder_name.ilike(pattern), AwardOutcome.package_title.ilike(pattern),
            AwardOutcome.notice_id.ilike(pattern), AwardOutcome.project_name.ilike(pattern),
            AwardOutcome.rejection_reason.ilike(pattern),
        ))
    return statement


async def ledger_summary(db: AsyncSession) -> dict[str, Any]:
    latest = latest_snapshot_ids()
    by_status = (await db.execute(
        select(AwardOutcome.country, AwardOutcome.status, func.count())
        .where(AwardOutcome.snapshot_id.in_(latest))
        .group_by(AwardOutcome.country, AwardOutcome.status)
    )).all()
    notices = (await db.execute(
        select(AwardNoticeSnapshot.country, AwardNoticeSnapshot.parse_status, func.count(),
               func.min(AwardNoticeSnapshot.notice_date), func.max(AwardNoticeSnapshot.notice_date),
               func.max(AwardNoticeSnapshot.retrieved_at))
        .where(AwardNoticeSnapshot.id.in_(latest))
        .group_by(AwardNoticeSnapshot.country, AwardNoticeSnapshot.parse_status)
    )).all()
    stored = await db.scalar(select(func.count()).select_from(AwardNoticeSnapshot))
    countries: dict[str, dict[str, Any]] = {}
    for country, status, count in by_status:
        entry = countries.setdefault(country or "", {"country": country or "", "rows": {}, "notices": 0,
                                                     "notices_without_bidders": 0})
        entry["rows"][status] = int(count)
    first: date | None = None
    last: date | None = None
    retrieved: datetime | None = None
    for country, parse_status, count, low, high, latest_retrieved in notices:
        entry = countries.setdefault(country or "", {"country": country or "", "rows": {}, "notices": 0,
                                                     "notices_without_bidders": 0})
        entry["notices"] += int(count)
        if parse_status == "NO_BIDDERS":
            entry["notices_without_bidders"] += int(count)
        first = low if first is None or (low and low < first) else first
        last = high if last is None or (high and high > last) else last
        retrieved = latest_retrieved if retrieved is None or (latest_retrieved and latest_retrieved > retrieved) else retrieved
    return {
        "countries": sorted(countries.values(), key=lambda item: item["country"]),
        "notice_count": sum(item["notices"] for item in countries.values()),
        "row_count": sum(sum(item["rows"].values()) for item in countries.values()),
        "stored_snapshot_count": int(stored or 0),
        "first_notice_date": first,
        "last_notice_date": last,
        "last_retrieved_at": retrieved,
    }


async def list_outcomes(
    db: AsyncSession, *, filters: OutcomeFilters, limit: int = 100, offset: int = 0
) -> tuple[list[AwardOutcome], int]:
    total = await db.scalar(_filtered(select(func.count()).select_from(AwardOutcome), filters))
    rows = (await db.scalars(
        _filtered(select(AwardOutcome), filters)
        .order_by(AwardOutcome.notice_date.desc().nulls_last(), AwardOutcome.notice_id.desc(),
                  AwardOutcome.bid_ordinal, AwardOutcome.member_ordinal)
        .limit(max(1, min(limit, 500))).offset(max(0, offset))
    )).all()
    return list(rows), int(total or 0)


def _csv(columns: Iterable[str], rows: Iterable[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _cell(value) for key, value in row.items()})
    return buffer.getvalue()


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
        return "'" + value  # spreadsheet formula injection
    return value


async def outcomes_csv(db: AsyncSession, *, filters: OutcomeFilters) -> str:
    rows = (await db.scalars(
        _filtered(select(AwardOutcome), filters)
        .order_by(AwardOutcome.country, AwardOutcome.notice_date.desc().nulls_last(), AwardOutcome.notice_id,
                  AwardOutcome.bid_ordinal, AwardOutcome.member_ordinal)
    )).all()
    return _csv(OUTCOME_CSV_COLUMNS, (outcome_values(row, OUTCOME_CSV_COLUMNS) for row in rows))


async def _ledger_rows(
    db: AsyncSession, *, where: Any = None, include_non_firms: bool = False, include_flagged_notices: bool = False,
) -> list[tuple[AwardOutcome, list[str]]]:
    """Firm rows of the latest snapshots with their project sectors. Names flagged as a public body
    or a project (non_firm_reason) are left out unless asked for: they are reviewed, not counted.
    S1-7: notices that fail the country validation (award_ledger_validation) are left out too; they stay
    stored and readable in the ledger."""
    statement = (
        select(AwardOutcome, AwardNoticeSnapshot.sectors)
        .join(AwardNoticeSnapshot, AwardNoticeSnapshot.id == AwardOutcome.snapshot_id)
        .where(AwardOutcome.snapshot_id.in_(latest_snapshot_ids()), is_firm())
    )
    if where is not None:
        statement = statement.where(where)
    flagged: set[str] = set()
    if not include_flagged_notices:
        from app.services.award_ledger_validation import excluded_notice_ids

        flagged = await excluded_notice_ids(db)
    return [(row, list(sectors or [])) for row, sectors in (await db.execute(statement)).all()
            if (include_non_firms or non_firm_reason(row.bidder_name) is None) and row.notice_id not in flagged]


def _firm_key(row: AwardOutcome) -> tuple[str, str]:
    # Normalized on read: the ledger is append-only, so a better normalization applies to old rows too.
    return normalize_firm_name(row.bidder_name) or row.bidder_name.upper(), country_key(row.bidder_country)


async def firm_export(db: AsyncSession) -> list[dict[str, Any]]:
    """One row per firm (normalized name + country) across the whole ledger."""
    firms: dict[tuple[str, str], dict[str, Any]] = {}
    for row, sectors in await _ledger_rows(db):
        key = _firm_key(row)
        firm = firms.setdefault(key, {
            "normalized_name": key[0], "names": Counter(), "country": row.bidder_country or "",
            "bids": set(), "awards": set(), "rejections": set(), "lenders": set(), "countries_bid": set(),
            "groups": set(), "sectors": set(), "first": None, "last": None, "ids": set(), "examples": {},
        })
        firm["names"][row.bidder_name] += 1
        bid = (row.lender, row.notice_id, row.bid_ordinal)
        firm["bids"].add(bid)
        if row.status == "AWARDED":
            firm["awards"].add(bid)
        if row.status == "REJECTED":
            firm["rejections"].add(bid)
        firm["lenders"].add(LENDER_LABELS.get(row.lender, row.lender))
        if row.country:
            firm["countries_bid"].add(row.country)
        if row.procurement_group:
            firm["groups"].add(row.procurement_group)
        firm["sectors"].update(sectors)
        if row.bidder_source_id:
            firm["ids"].add(row.bidder_source_id)
        if row.notice_date:
            firm["first"] = row.notice_date if firm["first"] is None else min(firm["first"], row.notice_date)
            firm["last"] = row.notice_date if firm["last"] is None else max(firm["last"], row.notice_date)
        title = " — ".join(part for part in (row.project_name, row.package_title) if part)
        firm["examples"].setdefault(row.notice_id, (row.notice_date or date.min, title, row.notice_url))
    result = []
    for firm in firms.values():
        examples = sorted(firm["examples"].values(), key=lambda item: item[0], reverse=True)[:3]
        entry = {
            "normalized_name": firm["normalized_name"],
            "display_name": firm["names"].most_common(1)[0][0],
            "country": firm["country"],
            "participations": len(firm["bids"]),
            "awards": len(firm["awards"]),
            "rejections": len(firm["rejections"]),
            "lenders": "; ".join(sorted(firm["lenders"])),
            "countries_bid": "; ".join(sorted(firm["countries_bid"])),
            "procurement_groups": "; ".join(sorted(firm["groups"])),
            "sectors": "; ".join(sorted(firm["sectors"])),
            "first_activity": firm["first"],
            "last_activity": firm["last"],
            "world_bank_supplier_ids": "; ".join(sorted(firm["ids"])),
        }
        for index in range(3):
            entry[f"example_{index + 1}_title"] = examples[index][1] if index < len(examples) else None
            entry[f"example_{index + 1}_url"] = examples[index][2] if index < len(examples) else None
        result.append(entry)
    result.sort(key=lambda item: (-item["participations"], -item["awards"], item["normalized_name"]))
    return result


async def firm_export_csv(db: AsyncSession) -> tuple[str, int]:
    rows = await firm_export(db)
    return _csv(FIRM_CSV_COLUMNS, rows), len(rows)


# ---- market sizing (v2, S1-6: four Central Asian countries, a region total, every category) ----------

REGION = "Central Asia"
REGION_THRESHOLDS = (2, 3, 5)
ALL_CATEGORIES = "All categories"
# Section order of the document: the TAM view first, then the current segment, then the expansion path.
CATEGORY_SECTIONS = (
    (ALL_CATEGORIES, "All categories (TAM view)"),
    (CONSULTING_GROUP, "Consulting (current segment)"),
    ("Works", "Works"),
    ("Goods", "Goods"),
    ("Non-consulting Services", "Non-consulting services"),
)
GROUP_LABELS = {CONSULTING_GROUP: "Consultant Services", "Goods": "Goods", "Works": "Civil Works",
                "Non-consulting Services": "Non-consulting Services"}
# Currencies an award notice of each project country is expected to use: its own currency, a major
# international one, or a currency regional contractors are paid in (RUB, CNY, TRY). Anything else
# (e.g. BDT on an Uzbekistan notice) is a flagged source entry error.
LOCAL_CURRENCY = {"UZBEKISTAN": "UZS", "KYRGYZ REPUBLIC": "KGS", "TAJIKISTAN": "TJS", "KAZAKHSTAN": "KZT"}
INTERNATIONAL_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "RUB", "CNY", "TRY"}
# A contract worth less than this in USD is a published typo (e.g. "UZS 99,340"): flagged.
MIN_PLAUSIBLE_USD = Decimal("100")
SINGLE_FIRM_METHODS = ("Consultant Qualification Selection", "Direct Selection")
COMPETITIVE_METHODS = ("Quality And Cost-Based Selection", "Least Cost Selection", "Quality-Based Selection",
                       "Fixed Budget Selection")
BID_STATUSES = ("AWARDED", "EVALUATED", "REJECTED", "NOT_EVALUATED")
UNCOVERED_LAYERS = (
    "Asian Development Bank (ADB)",
    "European Bank for Reconstruction and Development (EBRD)",
    "Asian Infrastructure Investment Bank (AIIB)",
    "Islamic Development Bank (IsDB)",
    "National procurement: Uzbekistan's state procurement portals (e.g. the UzEx exchange and xarid.uzex.uz) and "
    "the national systems of Kyrgyz Republic, Tajikistan and Kazakhstan",
    "Other bilateral and multilateral financiers (e.g. KfW, JICA, AFD, EU-funded tenders)",
)


def _bucket(count: int) -> str:
    return next(label for low, high, label in BID_BUCKETS if low <= count <= high)


def _segment(row: AwardOutcome) -> str:
    if not row.bidder_country:
        return "unknown"
    return "local" if country_key(row.bidder_country) == country_key(row.country) else "foreign"


def _region_segment(row: AwardOutcome, countries: tuple[str, ...]) -> str:
    """Region-wide: a firm from one of the covered countries is local (regional), any other is foreign."""
    if not row.bidder_country:
        return "unknown"
    return "local" if country_key(row.bidder_country) in {country_key(c) for c in countries} else "foreign"


def award_value_flag(row: AwardOutcome) -> str | None:
    """Why an award's published value is left out of USD figures, or None."""
    currency, amount = _award_value(row)
    if currency is None or amount is None:
        return None
    if (row.signed_contract_amount is not None and row.signed_contract_amount == row.evaluated_price_amount
            and row.signed_contract_currency and row.evaluated_price_currency
            and row.signed_contract_currency != row.evaluated_price_currency):
        # e.g. "USD 9,541,788,388" signed and "UZS 9,541,788,388" evaluated: one of the labels is wrong.
        return (f"same amount published as {row.signed_contract_currency} (signed) and "
                f"{row.evaluated_price_currency} (evaluated)")
    expected = INTERNATIONAL_CURRENCIES | {LOCAL_CURRENCY.get(country_key(row.country), "")}
    if currency not in expected:
        return f"currency {currency} on a {row.country} notice"
    usd = to_usd(currency, amount)
    if usd is None:
        return f"currency {currency} not in the exchange-rate table"
    if usd < MIN_PLAUSIBLE_USD:
        return f"implausibly small: {currency} {amount:,.2f} is about USD {usd:,.2f}"
    return None


async def market_sizing(
    db: AsyncSession,
    *,
    countries: tuple[str, ...] = MARKET_SIZING_COUNTRIES,
    today: date | None = None,
    months: int = DEFAULT_WINDOW_MONTHS,
    include_flagged_notices: bool = False,
) -> dict[str, Any]:
    """World Bank award notices per country and region-wide over the window, for every procurement category.

    Individual consultants are excluded from every figure and reported only as a count."""
    today = today or datetime.now(timezone.utc).date()
    since = window_start(today, months)
    window = and_(AwardOutcome.country.in_(countries), AwardOutcome.notice_date >= since, AwardOutcome.notice_date <= today)
    rows = await _ledger_rows(db, where=window, include_flagged_notices=include_flagged_notices)
    individual_awards = {country: int(count) for country, count in (await db.execute(
        select(AwardOutcome.country, func.count(func.distinct(AwardOutcome.notice_id))).where(
            AwardOutcome.snapshot_id.in_(latest_snapshot_ids()), ~is_firm(), AwardOutcome.status == "AWARDED", window,
        ).group_by(AwardOutcome.country)
    )).all()}
    individual_awards[REGION] = sum(individual_awards.values())
    firm_groups: dict[tuple[str, str], set] = defaultdict(set)
    for row, _ in rows:
        firm_groups[_firm_key(row)].add(row.procurement_group or "Unspecified")
    columns = (*countries, REGION)
    detail: dict[str, dict[str, Any]] = {}
    for category, _title in CATEGORY_SECTIONS:
        scoped = rows if category == ALL_CATEGORIES else [item for item in rows if item[0].procurement_group == category]
        detail[category] = {}
        for column in columns:
            in_column = scoped if column == REGION else [item for item in scoped if item[0].country == column]
            detail[category][column] = _sizing_stats(in_column, region=countries if column == REGION else None,
                                                     firm_groups=firm_groups)
    out: list[dict[str, Any]] = []

    def emit(metric: str, category: str, country: str, value: Any, *, sector: str = "All", segment: str = "all",
             unit: str = "count", note: str = "") -> None:
        out.append({"metric": metric, "category": category, "country": country, "lender": "World Bank",
                    "sector": sector, "segment": segment, "value": value, "unit": unit, "note": note})

    for category, _title in CATEGORY_SECTIONS:
        for column in columns:
            stats = detail[category][column]
            once = "each firm counted once across the four countries" if column == REGION else ""
            if category == ALL_CATEGORIES:
                for group, count in sorted(stats["rows_by_group"].items()):
                    emit("bidder_rows", category, column, count, segment=group)
                emit("individual_consultant_awards", category, column, individual_awards.get(column, 0),
                     note="excluded from every firm figure")
            emit("contracts_with_award_notice", category, column, stats["notices"])
            emit("bids", category, column, stats["bids"], note="a joint venture is one bid")
            for status in BID_STATUSES:
                emit("bids_by_status", category, column, stats["bid_status"].get(status, 0), segment=status)
            for segment in ("all", "local", "foreign", "unknown"):
                emit("distinct_firms", category, column, stats["firms"][segment], segment=segment,
                     note="; ".join(part for part in (once, "joint-venture members counted as separate firms",
                                                      "local = from one of the four countries" if column == REGION else
                                                      "local = from the project country") if part))
            for threshold in REGION_THRESHOLDS:
                emit("firms_with_at_least_n_bids", category, column, stats["at_least"][threshold], segment=f">={threshold} bids")
            emit("median_bids_per_firm", category, column, stats["median_bids"]["all"], unit="bids")
            emit("firms_in_two_or_more_countries", category, column, stats["multi_country_firms"])
            emit("firms_in_two_or_more_categories", category, column, stats["multi_category_firms"])
            emit("awarded_contracts", category, column, stats["awards"])
            emit("awarded_contracts_with_published_value", category, column, stats["awards_with_value"])
            for currency, amount in sorted(stats["awarded_value"].items()):
                emit("awarded_value", category, column, format(amount, "f"), unit=currency, note="as published, every award")
            emit("awarded_value_usd_equivalent", category, column, format(stats["awarded_value_usd"], "f"), unit="USD",
                 note=f"at {FX_DATE} rates ({FX_SOURCE}); flagged source errors excluded")
            emit("median_award_usd_equivalent", category, column,
                 format(stats["median_award_usd"], "f") if stats["median_award_usd"] is not None else "", unit="USD",
                 note="median of awarded contracts with a usable published value")
            emit("flagged_award_values", category, column, len(stats["flagged_values"]))
            for method, method_stats in sorted(stats["methods"].items()):
                emit("contracts_by_method", category, column, method_stats["assignments"], segment=method)
                emit("bids_per_contract", category, column, f"{method_stats['mean_bids']:.2f}", segment=method, unit="bids")
            for reason, count in stats["rejection_reasons"].most_common():
                emit("rejection_reason", category, column, count, segment=reason, note="verbatim; one count per rejected bid")
            if category != ALL_CATEGORIES:
                for sector, sector_stats in sorted(stats["by_sector"].items()):
                    emit("distinct_firms", category, column, sector_stats["firms"], sector=sector,
                         note="sector as tagged on the project; a project can carry several")
                    emit("awarded_value_usd_equivalent", category, column, format(sector_stats["awarded_value_usd"], "f"),
                         sector=sector, unit="USD")
    if not include_flagged_notices:
        from app.services.award_ledger_validation import validation_rows

        validation = [row for row in await validation_rows(db) if row["ledger_country"] in countries]
    else:
        validation = []
    return {
        "since": since, "until": today, "months": months, "countries": list(countries), "columns": list(columns),
        "rows": out, "detail": detail, "individual_consultant_awards": individual_awards,
        "fx": {"date": FX_DATE, "source": FX_SOURCE, "url": FX_URL}, "validation": validation,
    }


def _sizing_stats(
    rows: list[tuple[AwardOutcome, list[str]]], *, region: tuple[str, ...] | None = None,
    firm_groups: dict[tuple[str, str], set] | None = None,
) -> dict[str, Any]:
    firm_bids: dict[tuple[str, str], set] = defaultdict(set)
    firm_segment: dict[tuple[str, str], str] = {}
    firm_countries: dict[tuple[str, str], set] = defaultdict(set)
    bids: set = set()
    notices: dict[str, str] = {}
    notice_bids: dict[str, set] = defaultdict(set)
    notice_awards: dict[str, set] = defaultdict(set)
    bid_detail: dict[tuple, tuple[str, bool, str | None]] = {}  # bid -> (status, priced, rejection reason)
    awards: dict[tuple, AwardOutcome] = {}
    rows_by_group: Counter = Counter()
    sector_firms: dict[str, set] = defaultdict(set)
    sector_awards: dict[str, dict[tuple, AwardOutcome]] = defaultdict(dict)
    for row, sectors in rows:
        key = _firm_key(row)
        bid = (row.lender, row.notice_id, row.bid_ordinal)
        rows_by_group[row.procurement_group or "Unspecified"] += 1
        firm_bids[key].add(bid)
        firm_segment.setdefault(key, _region_segment(row, region) if region else _segment(row))
        if row.country:
            firm_countries[key].add(row.country)
        bids.add(bid)
        notices[row.notice_id] = row.procurement_method or "Unspecified"
        notice_bids[row.notice_id].add(bid)
        if row.member_ordinal == 1:
            bid_detail[bid] = (row.status, bool(row.evaluated_price_text or row.signed_contract_price_text
                                                or row.bid_price_at_opening_text), row.rejection_reason)
        if row.status == "AWARDED" and row.member_ordinal == 1:
            awards[bid] = row
            notice_awards[row.notice_id].add(bid)
        for sector in sectors or ["Unspecified"]:
            sector_firms[sector].add(key)
            if row.status == "AWARDED" and row.member_ordinal == 1:
                sector_awards[sector][bid] = row

    def published(rows_: Iterable[AwardOutcome]) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for award in _value_awards(rows_):
            currency, amount = _award_value(award)
            if currency and amount is not None:
                totals[currency] += amount
        return dict(totals)

    def usd_values(rows_: Iterable[AwardOutcome]) -> list[Decimal]:
        values = []
        for award in _value_awards(rows_):
            if award_value_flag(award) is None:
                value = to_usd(*_award_value(award))
                if value is not None:
                    values.append(value)
        return values

    segments = {"all": list(firm_bids)}
    for segment in ("local", "foreign", "unknown"):
        segments[segment] = [key for key in firm_bids if firm_segment[key] == segment]
    distribution, medians = {}, {}
    for segment in ("all", "local", "foreign"):
        counts = [len(firm_bids[key]) for key in segments[segment]]
        distribution[segment] = {label: sum(1 for value in counts if _bucket(value) == label) for *_, label in BID_BUCKETS}
        medians[segment] = statistics.median(counts) if counts else 0
    methods: dict[str, dict[str, Any]] = {}
    for notice_id, method in notices.items():
        entry = methods.setdefault(method, {"assignments": 0, "bids": 0, "counts": [], "multi_firm_bids": Counter()})
        entry["assignments"] += 1
        entry["bids"] += len(notice_bids[notice_id])
        entry["counts"].append(len(notice_bids[notice_id]))
        if len(notice_bids[notice_id]) > 1:
            for bid in notice_bids[notice_id]:
                status, priced, _reason = bid_detail.get(bid, ("UNKNOWN", False, None))
                entry["multi_firm_bids"][status] += 1
                entry["multi_firm_bids"][f"{status} priced"] += int(priced)
    for entry in methods.values():
        entry["multi_firm_bids"] = dict(entry["multi_firm_bids"])
        counts = entry.pop("counts")
        entry["mean_bids"] = entry["bids"] / entry["assignments"] if entry["assignments"] else 0.0
        entry["max_bids"] = max(counts, default=0)
        entry["distribution"] = {
            "1 firm": sum(1 for count in counts if count == 1), "2 firms": sum(1 for count in counts if count == 2),
            "3 firms": sum(1 for count in counts if count == 3), "4+ firms": sum(1 for count in counts if count >= 4),
        }
    flagged = []
    for award in awards.values():
        reason = award_value_flag(award)
        if reason:
            currency, amount = _award_value(award)
            flagged.append({"notice_id": award.notice_id, "country": award.country, "group": award.procurement_group,
                            "firm": award.bidder_name, "value": f"{currency} {amount:,.2f}", "reason": reason})
    country_counts = Counter(len(firm_countries[key]) for key in firm_bids)
    award_usd = usd_values(awards.values())
    bid_status = Counter(status for status, _priced, _reason in bid_detail.values())
    reasons = Counter((reason or "").strip() for status, _priced, reason in bid_detail.values()
                      if status == "REJECTED" and (reason or "").strip())
    return {
        "notices": len(notices),
        "bids": len(bids),
        "rows_by_group": dict(rows_by_group),
        "bid_status": dict(bid_status),
        "rejection_reasons": reasons,
        "rejected_without_reason": sum(1 for status, _priced, reason in bid_detail.values()
                                       if status == "REJECTED" and not (reason or "").strip()),
        "firms": {segment: len(keys) for segment, keys in segments.items()},
        "firm_segment_country": Counter(country_key(next(iter(firm_countries[key]), "")) for key in segments["local"]),
        "bid_distribution": distribution,
        "median_bids": medians,
        "at_least": {threshold: sum(1 for key in firm_bids if len(firm_bids[key]) >= threshold)
                     for threshold in REGION_THRESHOLDS},
        "bid_bands": {segment: {
            "1": sum(1 for key in segments[segment] if len(firm_bids[key]) == 1),
            "2-4": sum(1 for key in segments[segment] if 2 <= len(firm_bids[key]) <= 4),
            "5+": sum(1 for key in segments[segment] if len(firm_bids[key]) >= 5),
        } for segment in ("all", "local", "foreign")},
        "firms_by_country_count": dict(country_counts),
        "multi_country_firms": sum(count for countries, count in country_counts.items() if countries >= 2),
        "multi_category_firms": sum(1 for key in firm_bids if len((firm_groups or {}).get(key, ())) >= 2),
        "awards": len(awards),
        "awards_with_value": sum(1 for award in awards.values() if _award_value(award)[1] is not None),
        "awarded_value": published(awards.values()),
        "awarded_value_usd": sum(award_usd, Decimal("0")),
        "median_award_usd": statistics.median(award_usd).quantize(Decimal("1")) if award_usd else None,
        "flagged_values": sorted(flagged, key=lambda item: item["notice_id"]),
        "notices_by_method": {method: entry["assignments"] for method, entry in methods.items()},
        "methods": methods,
        "multiple_award_notices": sorted((notice_id, len(found)) for notice_id, found in notice_awards.items() if len(found) > 1),
        "notices_without_award": sorted(notice_id for notice_id in notices if not notice_awards.get(notice_id)),
        "by_sector": {
            sector: {"firms": len(sector_firms[sector]),
                     "awarded_value_usd": sum(usd_values(sector_awards[sector].values()), Decimal("0"))}
            for sector in sector_firms
        },
    }


def _value_awards(rows: Iterable[AwardOutcome]) -> list[AwardOutcome]:
    """Awards for value totals: two awarded entries on one notice with the same currency and amount are one
    contract published twice (e.g. OP00461417: two firms, USD 1,503,485 each), so the value counts once."""
    seen: set[tuple] = set()
    unique = []
    for award in sorted(rows, key=lambda item: (item.notice_id, item.bid_ordinal)):
        key = (award.notice_id, *_award_value(award))
        if key[2] is not None and key in seen:
            continue
        seen.add(key)
        unique.append(award)
    return unique


def _award_value(row: AwardOutcome) -> tuple[str | None, Decimal | None]:
    if row.signed_contract_amount is not None:
        return row.signed_contract_currency, row.signed_contract_amount
    if row.evaluated_price_amount is not None:
        return row.evaluated_price_currency, row.evaluated_price_amount
    return None, None


def market_sizing_csv(result: dict[str, Any]) -> str:
    return _csv(MARKET_CSV_COLUMNS, result["rows"])


def _money(values: dict[str, Decimal]) -> str:
    if not values:
        return "none published"
    return "; ".join(f"{currency} {amount:,.0f}" for currency, amount in sorted(values.items()))


def _usd(value: Decimal | None) -> str:
    return "—" if value is None else f"USD {value:,.0f}"


def _share(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "—"


def _method_finding(method: str, entry: dict[str, Any]) -> str:
    """What the award notices of one selection method list, in numbers (no assumption about why)."""
    single, total = entry["distribution"]["1 firm"], entry["assignments"]
    multi = total - single
    other = entry["multi_firm_bids"]

    def part(status: str, word: str) -> str:
        count = other.get(status, 0)
        return f"{count} {word} ({other.get(f'{status} priced', 0)} with a published price)" if count else ""

    listed = ", ".join(item for item in (part("AWARDED", "awarded"), part("EVALUATED", "evaluated"),
                                         part("REJECTED", "rejected")) if item)
    if method in SINGLE_FIRM_METHODS:
        if multi == 0:
            return f"- {method}: confirmed: all {total} notices list exactly one firm."
        return (f"- {method}: {single} of {total} notices ({single / total:.0%}) list one firm, as the method implies. "
                f"The other {multi} list several firms (up to {entry['max_bids']} per notice): {listed}. These notices "
                "are counted as published, each listed firm as a bid.")
    return (f"- {method}: confirmed for {multi} of {total} notices, which list several proposals ({entry['mean_bids']:.2f} "
            f"per assignment on average, at most {entry['max_bids']}): {listed}. {single} list a single firm.")


def _section(result: dict[str, Any], category: str, title: str, number: int) -> list[str]:
    columns = result["columns"]
    stats = {column: result["detail"][category][column] for column in columns}
    region = stats[REGION]
    noun = "assignments" if category == CONSULTING_GROUP else "contracts"
    lines = [f"## {number}. {title}", "", "| | " + " | ".join(columns) + " |", "|---|" + "---|" * len(columns)]

    def row(label: str, value) -> None:
        lines.append(f"| {label} | " + " | ".join(value(stats[column]) for column in columns) + " |")

    if category == ALL_CATEGORIES:
        for group in (CONSULTING_GROUP, "Works", "Goods", "Non-consulting Services"):
            row(f"Bidder rows: {GROUP_LABELS[group]}", lambda s, g=group: str(s["rows_by_group"].get(g, 0)))
        row("Bidder rows: all categories", lambda s: str(sum(s["rows_by_group"].values())))
    row(f"{noun.capitalize()} with a published award notice", lambda s: str(s["notices"]))
    row("Bids (a joint venture is one bid)", lambda s: str(s["bids"]))
    row("— awarded", lambda s: f"{s['bid_status'].get('AWARDED', 0)} ({_share(s['bid_status'].get('AWARDED', 0), s['bids'])})")
    row("— evaluated, not awarded", lambda s: f"{s['bid_status'].get('EVALUATED', 0)} ({_share(s['bid_status'].get('EVALUATED', 0), s['bids'])})")
    row("— rejected", lambda s: f"{s['bid_status'].get('REJECTED', 0)} ({_share(s['bid_status'].get('REJECTED', 0), s['bids'])})")
    if any(s["bid_status"].get("NOT_EVALUATED") for s in stats.values()):
        row("— not evaluated", lambda s: f"{s['bid_status'].get('NOT_EVALUATED', 0)} ({_share(s['bid_status'].get('NOT_EVALUATED', 0), s['bids'])})")
    row("Distinct firms (Central Asia: each firm once)", lambda s: str(s["firms"]["all"]))
    row("— local¹", lambda s: str(s["firms"]["local"]))
    row("— foreign¹", lambda s: str(s["firms"]["foreign"]))
    if any(s["firms"]["unknown"] for s in stats.values()):
        row("— country not published", lambda s: str(s["firms"]["unknown"]))
    for threshold in REGION_THRESHOLDS:
        row(f"Firms with ≥{threshold} bids", lambda s, t=threshold: str(s["at_least"][t]))
    row("Firms active in ≥2 countries", lambda s: str(s["multi_country_firms"]))
    row("Firms active in ≥2 categories", lambda s: str(s["multi_category_firms"]))
    row("Awarded contracts (firms)", lambda s: str(s["awards"]))
    row("Awarded value, USD equivalent²", lambda s: _usd(s["awarded_value_usd"]))
    row("Median award, USD equivalent²", lambda s: _usd(s["median_award_usd"]))
    row("Awarded value as published", lambda s: _money(s["awarded_value"]))
    if category == ALL_CATEGORIES:
        lines.append("| Individual-consultant awards (excluded everywhere) | " + " | ".join(
            str(result["individual_consultant_awards"].get(column, 0)) for column in columns) + " |")
    lines += ["", f"Bids per {noun[:-1]}, by procurement method (Central Asia):", "",
              "| Method | " + noun.capitalize() + " | Bids | Bids per " + noun[:-1] + " | 1 firm listed | 2 | 3 | 4+ |",
              "|---|---|---|---|---|---|---|---|"]
    for method, entry in sorted(region["methods"].items(), key=lambda item: (-item[1]["assignments"], item[0])):
        dist = entry["distribution"]
        lines.append(f"| {method} | {entry['assignments']} | {entry['bids']} | {entry['mean_bids']:.2f} | "
                     f"{dist['1 firm']} | {dist['2 firms']} | {dist['3 firms']} | {dist['4+ firms']} |")
    lines.append("")
    if category == CONSULTING_GROUP:
        lines += ["What the notices list, by selection method (CQS note):", ""]
        for method in (*SINGLE_FIRM_METHODS, *COMPETITIVE_METHODS):
            entry = region["methods"].get(method)
            if entry:
                lines.append(_method_finding(method, entry))
        lines += [
            "- Expression-of-interest submissions are not published, so firms that submitted an EOI but were not "
            "shortlisted or invited are invisible; Consultant Qualification Selection is decided at the EOI stage.",
            "",
        ]
        notes = []
        for column in columns:
            if column == REGION:
                continue
            s = stats[column]
            extra = []
            if s["multiple_award_notices"]:
                extra.append("more than one awarded bid on " + ", ".join(f"{n} ({c})" for n, c in s["multiple_award_notices"]))
            if s["notices_without_award"]:
                extra.append("no awarded firm on " + ", ".join(s["notices_without_award"]))
            notes.append(f"{column} {s['notices']} assignments / {s['awards']} awarded contracts"
                         + (f" ({'; '.join(extra)})" if extra else ""))
        lines += ["Assignments versus awarded contracts: " + "; ".join(notes) + ". An assignment is one award "
                  "notice and an awarded contract is one awarded entry as published. Where a notice lists two awarded "
                  "entries with the same currency and amount (OP00461417: two firms, USD 1,503,485 each, read as one "
                  "joint-venture contract), both stay in the counts but the value is counted once.", ""]
    total_rejected = region["bid_status"].get("REJECTED", 0)
    lines += [f"Rejection reasons, verbatim (Central Asia, {total_rejected} rejected bids; "
              f"{region['rejected_without_reason']} with no reason published; top 15, every reason in the CSV):", "",
              "| Reason as published | Bids |", "|---|---|"]
    for reason, count in region["rejection_reasons"].most_common(15):
        lines.append(f"| {reason.replace('|', '/')[:200]} | {count} |")
    lines.append("")
    return lines


def market_sizing_markdown(result: dict[str, Any], *, generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now(timezone.utc)
    columns = result["columns"]
    region_all = result["detail"][ALL_CATEGORIES][REGION]
    lines = [
        "# MDB procurement market sizing — Central Asia",
        "",
        f"Uzbekistan, Kyrgyz Republic, Tajikistan and Kazakhstan; every procurement category. Window: World Bank "
        f"award notices published {result['since'].isoformat()} to {result['until'].isoformat()} "
        f"({result['months']} months). Generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')} from the PlasmaOS award "
        f"ledger. USD equivalents use one exchange-rate table: {result['fx']['source']}, rates of {result['fx']['date']} "
        f"({result['fx']['url']}).",
        "",
        "**Every figure is a floor.** The ledger holds World Bank award notices only; the uncovered layers are listed "
        "under Caveats and are not estimated.",
        "",
        "¹ Per country: local = the firm's published country is the project country. Central Asia column: local = the "
        "firm is from one of the four countries; a firm is counted once however many countries it bid in.",
        "² Flagged source errors (listed below) are left out of USD figures; the as-published row includes them.",
        "",
    ]
    lines += headline_markdown(headline_figures(result))
    for number, (category, title) in enumerate(CATEGORY_SECTIONS, start=1):
        lines += _section(result, category, title, number)
    lines += ["## Median award value, USD equivalent", "",
              "| Category | " + " | ".join(columns) + " |", "|---|" + "---|" * len(columns)]
    for category, title in CATEGORY_SECTIONS:
        lines.append(f"| {title} | " + " | ".join(_usd(result["detail"][category][c]["median_award_usd"]) for c in columns) + " |")
    lines += [
        "",
        "## Exchange rates",
        "",
        f"{result['fx']['source']}, rates of {result['fx']['date']}: {result['fx']['url']}. USD equivalent = amount × "
        "(UZS per unit of the currency) ÷ (UZS per USD).",
        "",
        "| Currency | UZS per unit | USD per unit |",
        "|---|---|---|",
    ]
    for currency in sorted(region_all["awarded_value"]):
        rate = UZS_PER_UNIT.get(currency)
        lines.append(f"| {currency} | {rate:,.4f} | {usd_per_unit(currency):.6f} |" if rate is not None else f"| {currency} | — | — |")
    if result.get("validation"):
        from app.services.award_ledger_validation import FLAG_DUPLICATE

        excluded = [row for row in result["validation"] if row["excluded"] and row["flag"] != FLAG_DUPLICATE]
        duplicates = [row for row in result["validation"] if row["flag"] == FLAG_DUPLICATE]
        kept = [row for row in result["validation"] if not row["excluded"]]
        lines += ["", "## Notice-country validation", "",
                  "Every notice's World Bank project id was resolved against the World Bank Projects API "
                  "(https://search.worldbank.org/api/v2/projects?format=json&id=<project id>; responses cached in the "
                  "project table). No notice sits on a project of another country. Three kinds of flag:", "",
                  f"- **Excluded from every figure ({len(excluded)} notices): foreign bidder section.** A genuine "
                  "package of the project country whose whole award section lists bidders from one other country "
                  "priced in that country's currency (for example Ethiopian contractors in ETB on a Fergana "
                  "electricity package): the award record of another country's procurement attached at publication. "
                  "Kept in the ledger, flagged.", "",
                  "| Notice | Ledger country | Project | Awarded firm | Currency | Evidence |", "|---|---|---|---|---|---|"]
        lines += [f"| {row['notice_id']} | {row['ledger_country']} | {row['project_id']} ({row['project_country']}) | "
                  f"{row['firm']} | {row['currency']} | {row['detail']} |" for row in excluded]
        lines += ["", f"- **Excluded from every figure ({len(duplicates)} notices): duplicate award notice.** Every "
                  "award of the notice (package reference and title, awarded firm, award date, published price) is "
                  "published again in another notice; that notice (more awards, else the newest id) is counted, the "
                  "repeat is kept in the ledger, flagged. A notice with an award of its own (another lot) is counted.", "",
                  "| Notice | Ledger country | Evidence |", "|---|---|---|"]
        # no awardee names here: some are natural persons (sole proprietors on goods RFQs)
        lines += [f"| {row['notice_id']} | {row['ledger_country']} | {row['detail']} |" for row in duplicates]
        lines += ["", f"- **Flagged, kept ({len(kept)} notices): project not returned by the Projects API** (total 0 on "
                  "v2 and v3: preparation-stage or very new projects). Every one names the ledger country in its own "
                  "project name, so nothing says the notice belongs elsewhere.", "",
                  "| Notice | Ledger country | Project | Currency |", "|---|---|---|---|"]
        lines += [f"| {row['notice_id']} | {row['ledger_country']} | {row['project_id']} | {row['currency']} |" for row in kept]
    lines += ["", "## Flagged source errors (left out of USD figures)", ""]
    if region_all["flagged_values"]:
        # no awardee names: some awardees are natural persons; the notice id leads to the record
        lines += ["| Notice | Country | Category | Value as published | Why flagged |", "|---|---|---|---|---|"]
        for item in region_all["flagged_values"]:
            lines.append(f"| {item['notice_id']} | {item['country']} | {item['group']} | {item['value']} | {item['reason']} |")
    else:
        lines.append("None.")
    lines += [
        "",
        "## Method",
        "",
        "- Source: World Bank procurement-notice API, notice type \"Contract Award\", project country Uzbekistan, "
        "Kyrgyz Republic, Tajikistan or Kazakhstan, every procurement group, notice date inside the window. Each notice "
        "is stored verbatim (raw text, retrieval time, content hash) and parsed deterministically: the Awarded, "
        "Evaluated and Rejected sections list every firm the notice names; firms listed together before one "
        "score/price block are one joint-venture bid. Completeness was checked against the API per country and group.",
        "- A bid is one proposal or bid on one contract. A firm is a normalized name (upper-case, punctuation, legal "
        "forms such as LLC/LTD/JSC and joint-venture role markers such as \", LEAD\", \"(JV)\", \"CONSORTIUM OF\" "
        "removed) plus the firm's published country; a firm in a joint venture is counted as a bidder on that bid.",
        "- Individual consultants are excluded from every figure and reported only as a count. Names that are a public "
        "body or a project (ministries, PIUs, implementation units, committees, bodies \"under\" a ministry or agency, "
        "a bare \"<sector> PROJECT\") are left out of firm counts and listed for review; other names with PROJECT or "
        "AGENCY stay counted (many registered firms carry these words).",
        "- Awarded value = the signed contract price, or the awarded bid's final evaluated price when no signed price "
        "is published; counted once per joint venture. Median award = median USD equivalent of awarded contracts with "
        "a usable published value.",
        "",
        "## Caveats",
        "",
        "- World Bank only. These layers are not in the ledger and are not estimated, so every figure is a floor:",
        *(f"  - {layer}" for layer in UNCOVERED_LAYERS),
        "- Only contracts whose award notice is published are counted; cancelled procurements and awards not yet "
        "published are missing.",
        "- Expression-of-interest submissions are not published (consulting): firms that submitted an EOI but were not "
        "invited are invisible.",
        "- Direct Selection and direct contracting awards have one firm and no competition; they are included.",
        "- Kazakhstan's World Bank volume is small, so its figures rest on few notices.",
        "- Name normalization can split one firm written two ways (see the merge-candidate review list), or (rarely) "
        "merge two firms with the same normalized name and country.",
        "- USD equivalents use one date's rates for awards signed over two years; they size the market, they are not "
        "the dollar value at signing.",
        "",
    ]
    return "\n".join(lines)


# ---- name QA (S1-6) ----------------------------------------------------------------------------------

NON_FIRM_CSV_COLUMNS = (
    "bidder_name", "bidder_country", "flag", "tier", "counted_as_firm", "world_bank_supplier_ids",
    "participations", "statuses",
    "project_countries", "procurement_groups", "notice_ids",
)
MERGE_CSV_COLUMNS = (
    "rank", "country", "evidence", "similarity", "name_a", "name_b", "raw_names_a", "raw_names_b",
    "supplier_ids_a", "supplier_ids_b", "participations_a", "participations_b",
)
# Frequent words that do not tell firms apart: never enough on their own to pair two names.
_GENERIC_TOKENS = {
    "CONSULTING", "CONSULTANTS", "CONSULTANT", "CONSULT", "ENGINEERING", "GROUP", "INTERNATIONAL", "SERVICES",
    "SERVICE", "DEVELOPMENT", "STROY", "QURILISH", "SERVIS", "TRADE", "TRADING", "INVEST", "MANAGEMENT",
    "COMPANY", "TECHNOLOGIES", "TECHNOLOGY", "SOLUTIONS", "SYSTEMS", "GLOBAL", "PROJECT", "CENTER", "CENTRE",
    "UZBEKISTAN", "KAZAKHSTAN", "TAJIKISTAN", "KYRGYZSTAN", "ASIA", "CENTRAL", "NATIONAL", "BUILDING",
}


async def non_firm_review(db: AsyncSession) -> list[dict[str, Any]]:
    """Bidder names flagged as a public body or a project, grouped by name and country, for owner review.
    EXCLUDED names are left out of firm counts; REVIEW names stay counted until the owner decides."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row, _ in await _ledger_rows(db, include_non_firms=True):
        flagged = name_flag(row.bidder_name)
        if flagged is None:
            continue
        entry = groups.setdefault((row.bidder_name, row.bidder_country or ""), {
            "bidder_name": row.bidder_name, "bidder_country": row.bidder_country or "", "flag": flagged[0],
            "tier": flagged[1],
            "ids": set(), "bids": set(), "statuses": Counter(), "countries": set(), "groups": set(), "notices": set(),
        })
        if row.bidder_source_id:
            entry["ids"].add(row.bidder_source_id)
        entry["bids"].add((row.lender, row.notice_id, row.bid_ordinal))
        entry["statuses"][row.status] += 1
        entry["countries"].add(row.country or "")
        entry["groups"].add(row.procurement_group or "")
        entry["notices"].add(row.notice_id)
    result = [{
        "bidder_name": entry["bidder_name"], "bidder_country": entry["bidder_country"], "flag": entry["flag"],
        "tier": entry["tier"], "counted_as_firm": "no" if entry["tier"] == "EXCLUDED" else "yes",
        "world_bank_supplier_ids": "; ".join(sorted(entry["ids"])), "participations": len(entry["bids"]),
        "statuses": "; ".join(f"{status} {count}" for status, count in sorted(entry["statuses"].items())),
        "project_countries": "; ".join(sorted(entry["countries"])),
        "procurement_groups": "; ".join(sorted(entry["groups"])), "notice_ids": "; ".join(sorted(entry["notices"])),
    } for entry in groups.values()]
    result.sort(key=lambda item: (item["tier"] != "EXCLUDED", -item["participations"], item["bidder_name"]))
    return result


def _similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    tokens_a, tokens_b = set(a.split()), set(b.split())
    jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b) if tokens_a and tokens_b else 0.0
    return max(SequenceMatcher(None, a, b).ratio(), jaccard)


async def merge_candidates(db: AsyncSession, *, limit: int = 50, minimum: float = 0.75) -> list[dict[str, Any]]:
    """Same-country firm pairs that may be one firm written two ways, for owner review (never merged).

    Evidence, strongest first: the same World Bank supplier id under two normalized names, then name
    similarity (character ratio or shared-word share). Two names are only compared when they share a
    distinctive word, so common words alone never pair firms."""
    firms: dict[tuple[str, str], dict[str, Any]] = {}
    for row, _ in await _ledger_rows(db):
        key = _firm_key(row)
        firm = firms.setdefault(key, {"names": Counter(), "ids": set(), "bids": set()})
        firm["names"][row.bidder_name] += 1
        firm["bids"].add((row.lender, row.notice_id, row.bid_ordinal))
        if row.bidder_source_id:
            firm["ids"].add(row.bidder_source_id)
    pairs: dict[tuple, tuple[str, float]] = {}
    by_country: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in firms:
        by_country[key[1]].append(key)
    for keys in by_country.values():
        by_id: dict[str, list[tuple[str, str]]] = defaultdict(list)
        by_token: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for key in keys:
            for source_id in firms[key]["ids"]:
                by_id[source_id].append(key)
            for token in set(key[0].split()):
                if len(token) >= 4 and token not in _GENERIC_TOKENS:
                    by_token[token].append(key)
        for members in by_id.values():
            for index, a in enumerate(members):
                for b in members[index + 1:]:
                    pairs[tuple(sorted((a, b)))] = ("same World Bank supplier id", _similarity(a[0], b[0]))
        for members in by_token.values():
            if len(members) > 60:
                continue
            for index, a in enumerate(members):
                for b in members[index + 1:]:
                    pair = tuple(sorted((a, b)))
                    if pair in pairs:
                        continue
                    score = _similarity(a[0], b[0])
                    if score >= minimum:
                        pairs[pair] = ("similar name", score)
    ranked = sorted(pairs.items(), key=lambda item: (item[1][0] != "same World Bank supplier id", -item[1][1], item[0]))
    result = []
    for rank, ((a, b), (evidence, score)) in enumerate(ranked[:limit], start=1):
        result.append({
            "rank": rank, "country": a[1], "evidence": evidence, "similarity": f"{score:.2f}",
            "name_a": a[0], "name_b": b[0],
            "raw_names_a": "; ".join(name for name, _ in firms[a]["names"].most_common()),
            "raw_names_b": "; ".join(name for name, _ in firms[b]["names"].most_common()),
            "supplier_ids_a": "; ".join(sorted(firms[a]["ids"])), "supplier_ids_b": "; ".join(sorted(firms[b]["ids"])),
            "participations_a": len(firms[a]["bids"]), "participations_b": len(firms[b]["bids"]),
        })
    return result


def name_qa_csvs(non_firms: list[dict[str, Any]], merges: list[dict[str, Any]]) -> tuple[str, str]:
    return _csv(NON_FIRM_CSV_COLUMNS, non_firms), _csv(MERGE_CSV_COLUMNS, merges)


# ---- outreach targets (S1-6, private: never committed) ---------------------------------------------

TARGET_CSV_COLUMNS = (
    "normalized_name", "raw_name_variants", "published_country", "local_or_foreign_by_country", "bids", "awards",
    "evaluated_not_awarded", "rejected", "rejection_reasons", "top_sectors", "selection_methods", "countries_bid_in",
    "first_notice_date", "last_notice_date", "notice_ids", "awarded_value_as_published", "awarded_value_usd_equivalent",
    "jv_partners_seen", "procurement_groups_bid_in", "bids_by_group", "awards_by_group", "consulting_target",
    "name_review_flag",
)


async def outreach_targets(
    db: AsyncSession,
    *,
    countries: tuple[str, ...] = MARKET_SIZING_COUNTRIES,
    today: date | None = None,
    months: int = DEFAULT_WINDOW_MONTHS,
) -> list[dict[str, Any]]:
    """Firms with >= 1 award or >= 2 bids, any procurement category, in the four countries over the window.

    Consulting firms (>= 1 consulting award or >= 2 consulting bids: this week's outreach) come first, then
    every other firm by bids.

    Public notice data only (no contact data): names as published, statuses, verbatim rejection reasons,
    values as published plus a USD equivalent. Individual consultants and names excluded as public bodies
    or projects are never listed; names on the REVIEW tier are listed with their flag. A joint-venture
    award counts in full for each member firm."""
    today = today or datetime.now(timezone.utc).date()
    since = window_start(today, months)
    rows = await _ledger_rows(db, where=and_(
        AwardOutcome.country.in_(countries), AwardOutcome.notice_date >= since, AwardOutcome.notice_date <= today,
    ))
    bid_members: dict[tuple, list[str]] = defaultdict(list)
    for row, _ in rows:
        bid_members[(row.lender, row.notice_id, row.bid_ordinal)].append(row.bidder_name)
    firms: dict[tuple[str, str], dict[str, Any]] = {}
    for row, sectors in rows:
        key = _firm_key(row)
        bid = (row.lender, row.notice_id, row.bid_ordinal)
        firm = firms.setdefault(key, {
            "names": Counter(), "countries_published": Counter(), "segments": {}, "bids": set(), "awards": {},
            "evaluated": set(), "rejected": set(), "reasons": [], "sectors": Counter(), "methods": set(),
            "first": None, "last": None, "notices": set(), "partners": set(), "flag": name_flag(row.bidder_name),
            "group_bids": defaultdict(set), "group_awards": defaultdict(set),
        })
        group = row.procurement_group or "Unspecified"
        firm["group_bids"][group].add(bid)
        if row.status == "AWARDED":
            firm["group_awards"][group].add(bid)
        firm["names"][row.bidder_name] += 1
        if row.bidder_country:
            firm["countries_published"][row.bidder_country] += 1
        firm["segments"][row.country] = _segment(row)
        if bid not in firm["bids"]:
            firm["sectors"].update(sectors or [])
        firm["bids"].add(bid)
        if row.status == "AWARDED":
            firm["awards"][bid] = row
        elif row.status == "EVALUATED":
            firm["evaluated"].add(bid)
        elif row.status == "REJECTED":
            firm["rejected"].add(bid)
            if row.rejection_reason and row.rejection_reason not in firm["reasons"]:
                firm["reasons"].append(row.rejection_reason)
        if row.procurement_method:
            firm["methods"].add(row.procurement_method)
        if row.notice_date:
            firm["first"] = row.notice_date if firm["first"] is None else min(firm["first"], row.notice_date)
            firm["last"] = row.notice_date if firm["last"] is None else max(firm["last"], row.notice_date)
        firm["notices"].add(row.notice_id)
        firm["partners"].update(name for name in bid_members[bid] if name != row.bidder_name)
    result = []
    for key, firm in firms.items():
        if not (firm["awards"] or len(firm["bids"]) >= 2):
            continue
        published: dict[str, Decimal] = defaultdict(Decimal)
        usd_total, flagged = Decimal("0"), 0
        for award in firm["awards"].values():
            currency, amount = _award_value(award)
            if currency and amount is not None:
                published[currency] += amount
                if award_value_flag(award) is None:
                    usd_total += to_usd(currency, amount) or Decimal("0")
                else:
                    flagged += 1
        result.append({
            "normalized_name": key[0],
            "raw_name_variants": " | ".join(name for name, _ in firm["names"].most_common()),
            "published_country": firm["countries_published"].most_common(1)[0][0] if firm["countries_published"] else "",
            "local_or_foreign_by_country": "; ".join(f"{country}: {segment}" for country, segment in sorted(firm["segments"].items())),
            "bids": len(firm["bids"]),
            "awards": len(firm["awards"]),
            "evaluated_not_awarded": len(firm["evaluated"]),
            "rejected": len(firm["rejected"]),
            "rejection_reasons": " | ".join(firm["reasons"]),
            "top_sectors": "; ".join(sector for sector, _ in firm["sectors"].most_common(3)),
            "selection_methods": "; ".join(sorted(firm["methods"])),
            "countries_bid_in": "; ".join(sorted(firm["segments"])),
            "first_notice_date": firm["first"],
            "last_notice_date": firm["last"],
            "notice_ids": "; ".join(sorted(firm["notices"])),
            "awarded_value_as_published": _money(dict(published)) if published else "",
            "awarded_value_usd_equivalent": format(usd_total, "f") + (f" ({flagged} flagged value(s) left out)" if flagged else ""),
            "jv_partners_seen": " | ".join(sorted(firm["partners"])),
            "procurement_groups_bid_in": "; ".join(sorted(firm["group_bids"])),
            "bids_by_group": "; ".join(f"{group}: {len(found)}" for group, found in sorted(firm["group_bids"].items())),
            "awards_by_group": "; ".join(f"{group}: {len(found)}" for group, found in sorted(firm["group_awards"].items())),
            "consulting_target": "yes" if (firm["group_awards"].get(CONSULTING_GROUP)
                                           or len(firm["group_bids"].get(CONSULTING_GROUP, ())) >= 2) else "no",
            "name_review_flag": firm["flag"][0] if firm["flag"] else "",
        })
    result.sort(key=lambda item: (item["consulting_target"] != "yes", -item["bids"], -item["awards"], item["normalized_name"]))
    return result


def outreach_summary_markdown(targets: list[dict[str, Any]], *, since: date, until: date) -> str:
    """One page of counts for the private target list."""
    def bid_in(item: dict[str, Any], country: str) -> bool:
        return country in item["countries_bid_in"].split("; ")

    consulting = [item for item in targets if item["consulting_target"] == "yes"]
    local_uz = [item for item in targets if country_key(item["published_country"]) == "UZBEKISTAN"]
    foreign_uz = [item for item in targets if bid_in(item, "Uzbekistan") and country_key(item["published_country"]) != "UZBEKISTAN"]
    regional = [item for item in targets if len(item["countries_bid_in"].split("; ")) >= 2]
    by_country = Counter(item["published_country"] or "not published" for item in targets)
    lines = [
        "# Outreach targets — summary (private)",
        "",
        f"World Bank award notices, every procurement category, Uzbekistan, Kyrgyz Republic, Tajikistan and "
        f"Kazakhstan, {since.isoformat()} to {until.isoformat()}. Firms with at least one award or at least two bids "
        "in any category; no individual consultants, no names excluded as public bodies or projects. Public notice "
        "data only: no contact data, no web or LinkedIn lookups. Consulting targets (at least one consulting award or "
        "two consulting bids) are listed first and copied to consulting_targets.csv.",
        "",
        f"- Firms on the list: {len(targets)} (with an award: {sum(1 for item in targets if item['awards'])}; "
        f"two or more bids: {sum(1 for item in targets if item['bids'] >= 2)}).",
        f"- Consulting targets: {len(consulting)}; also active in another category: "
        f"{sum(1 for item in consulting if ';' in item['procurement_groups_bid_in'])}.",
        "- Firms by category bid in (a firm can bid in several): " + ", ".join(
            f"{group} {count}" for group, count in Counter(
                group for item in targets for group in item["procurement_groups_bid_in"].split("; ")).most_common()) + ".",
        f"- Local Uzbek firms (published country Uzbekistan): {len(local_uz)}; with an award: "
        f"{sum(1 for item in local_uz if item['awards'])}.",
        f"- Foreign firms active in Uzbekistan: {len(foreign_uz)}; with an award there or elsewhere in the region: "
        f"{sum(1 for item in foreign_uz if item['awards'])}.",
        f"- Multi-country regional firms (bid in two or more of the four countries): {len(regional)}.",
        f"- Names listed with a review flag (PROJECT/AGENCY in the name): {sum(1 for item in targets if item['name_review_flag'])}.",
        "",
        "## Firms by published country",
        "",
        "| Country | Firms |",
        "|---|---|",
        *(f"| {country} | {count} |" for country, count in by_country.most_common()),
        "",
        "## Top 15 consulting targets by bids",
        "",
        "| Firm | Country | Bids | Awards | Countries bid in |",
        "|---|---|---|---|---|",
        *(f"| {item['raw_name_variants'].split(' | ')[0]} | {item['published_country']} | {item['bids']} | {item['awards']} | "
          f"{item['countries_bid_in']} |" for item in consulting[:15]),
        "",
    ]
    return "\n".join(lines)


def outreach_targets_csv(targets: list[dict[str, Any]]) -> str:
    return _csv(TARGET_CSV_COLUMNS, targets)


# ---- headline figures (S1-7: the five figure groups at the top of the document) ---------------------

HEADLINE_CATEGORIES = (
    (ALL_CATEGORIES, "All categories"), ("Works", "Works"), ("Goods", "Goods"),
    (CONSULTING_GROUP, "Consulting"), ("Non-consulting Services", "Non-consulting services"),
)
CQS_METHOD = "Consultant Qualification Selection"


def headline_figures(result: dict[str, Any]) -> dict[str, Any]:
    """a. rejected / all bids, Uzbekistan, per category; b. top 3 rejection reasons, Uzbekistan; c. CQS share of
    Uzbekistan consulting assignments; d. median USD award, Uzbekistan, consulting/works/goods; e. Uzbekistan and
    Kyrgyz Republic, all categories and consulting: firms local/foreign and with exactly 1, 2-4, >=5 bids."""
    detail = result["detail"]
    uz = "Uzbekistan"
    figures: dict[str, Any] = {"a": {}, "b": [], "c": {}, "d": {}, "e": {}}
    for category, label in HEADLINE_CATEGORIES:
        stats = detail[category][uz]
        rejected = stats["bid_status"].get("REJECTED", 0)
        figures["a"][label] = {"rejected": rejected, "bids": stats["bids"],
                               "share": round(100 * rejected / stats["bids"], 1) if stats["bids"] else None}
    figures["b"] = [[reason, count] for reason, count in detail[ALL_CATEGORIES][uz]["rejection_reasons"].most_common(3)]
    consulting = detail[CONSULTING_GROUP][uz]
    cqs = consulting["notices_by_method"].get(CQS_METHOD, 0)
    figures["c"] = {"cqs": cqs, "assignments": consulting["notices"],
                    "share": round(100 * cqs / consulting["notices"], 1) if consulting["notices"] else None}
    for category, label in ((CONSULTING_GROUP, "Consulting"), ("Works", "Works"), ("Goods", "Goods")):
        value = detail[category][uz]["median_award_usd"]
        figures["d"][label] = int(value) if value is not None else None
    for country in ("Uzbekistan", "Kyrgyz Republic"):
        for category, label in ((ALL_CATEGORIES, "All categories"), (CONSULTING_GROUP, "Consulting")):
            stats = detail[category][country]
            figures["e"][f"{country} — {label}"] = {
                "firms": stats["firms"]["all"], "local": stats["firms"]["local"], "foreign": stats["firms"]["foreign"],
                "bids_1": stats["bid_bands"]["all"]["1"], "bids_2_4": stats["bid_bands"]["all"]["2-4"],
                "bids_5_plus": stats["bid_bands"]["all"]["5+"],
            }
    return figures


def headline_markdown(figures: dict[str, Any]) -> list[str]:
    lines = ["## Headline figures", "", "a. **Uzbekistan: rejected bids / all bids**", "",
             "| Category | Rejected | All bids | Share |", "|---|---|---|---|"]
    for label, item in figures["a"].items():
        lines.append(f"| {label} | {item['rejected']:,} | {item['bids']:,} | {item['share']}% |")
    lines += ["", "b. **Top 3 published rejection reasons, Uzbekistan, all categories**", ""]
    lines += [f"{index}. {reason} — {count:,} bids" for index, (reason, count) in enumerate(figures["b"], start=1)]
    c = figures["c"]
    lines += ["", f"c. **CQS share of Uzbekistan consulting assignments:** {c['cqs']} of {c['assignments']} "
              f"({c['share']}%)", "", "d. **Median award, USD equivalent, Uzbekistan:** " + "; ".join(
                  f"{label} USD {value:,}" if value is not None else f"{label} —" for label, value in figures["d"].items()),
              "", "e. **Distinct firms and how often they bid**", "",
              "| Country — scope | Firms | Local | Foreign | Exactly 1 bid | 2–4 bids | ≥5 bids |",
              "|---|---|---|---|---|---|---|"]
    for label, item in figures["e"].items():
        lines.append(f"| {label} | {item['firms']} | {item['local']} | {item['foreign']} | {item['bids_1']} | "
                     f"{item['bids_2_4']} | {item['bids_5_plus']} |")
    lines.append("")
    return lines
