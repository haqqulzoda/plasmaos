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
from app.services.award_ledger_parser import normalize_firm_name

LENDER_LABELS = {"WORLD_BANK": "World Bank", "ADB": "ADB", "EBRD": "EBRD"}
MARKET_SIZING_COUNTRIES = ("Uzbekistan", "Kazakhstan")
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
MARKET_CSV_COLUMNS = ("metric", "country", "lender", "sector", "segment", "value", "unit", "note")


def is_firm():
    """Firm rows only. Read-time too: rows stored before ICS rows were marked individual."""
    return and_(
        AwardOutcome.bidder_kind == "FIRM",
        func.coalesce(AwardOutcome.procurement_method, "") != INDIVIDUAL_SELECTION_METHOD,
    )


def country_key(value: str | None) -> str:
    key = re.sub(r"\s+", " ", (value or "").strip().upper())
    return _COUNTRY_ALIASES.get(key, key)


def latest_snapshot_ids() -> Select:
    return (
        select(AwardNoticeSnapshot.id)
        .distinct(AwardNoticeSnapshot.lender, AwardNoticeSnapshot.notice_id)
        .order_by(
            AwardNoticeSnapshot.lender, AwardNoticeSnapshot.notice_id,
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
    return _csv(OUTCOME_CSV_COLUMNS, ({column: getattr(row, column) for column in OUTCOME_CSV_COLUMNS} for row in rows))


async def _ledger_rows(db: AsyncSession, *, where: Any = None) -> list[tuple[AwardOutcome, list[str]]]:
    statement = (
        select(AwardOutcome, AwardNoticeSnapshot.sectors)
        .join(AwardNoticeSnapshot, AwardNoticeSnapshot.id == AwardOutcome.snapshot_id)
        .where(AwardOutcome.snapshot_id.in_(latest_snapshot_ids()), is_firm())
    )
    if where is not None:
        statement = statement.where(where)
    return [(row, list(sectors or [])) for row, sectors in (await db.execute(statement)).all()]


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


# ---- market sizing ----------------------------------------------------------------------------------

def _bucket(count: int) -> str:
    return next(label for low, high, label in BID_BUCKETS if low <= count <= high)


def _segment(row: AwardOutcome) -> str:
    if not row.bidder_country:
        return "unknown"
    return "local" if country_key(row.bidder_country) == country_key(row.country) else "foreign"


async def market_sizing(
    db: AsyncSession,
    *,
    countries: tuple[str, ...] = MARKET_SIZING_COUNTRIES,
    today: date | None = None,
    months: int = DEFAULT_WINDOW_MONTHS,
) -> dict[str, Any]:
    """Firms that bid on consulting assignments per country over the window, by lender and sector."""
    today = today or datetime.now(timezone.utc).date()
    since = window_start(today, months)
    rows = await _ledger_rows(db, where=and_(
        AwardOutcome.country.in_(countries), AwardOutcome.procurement_group == CONSULTING_GROUP,
        AwardOutcome.notice_date >= since, AwardOutcome.notice_date <= today,
    ))
    individual_awards = {country: int(count) for country, count in (await db.execute(
        select(AwardOutcome.country, func.count(func.distinct(AwardOutcome.notice_id))).where(
            AwardOutcome.snapshot_id.in_(latest_snapshot_ids()), ~is_firm(),
            AwardOutcome.status == "AWARDED", AwardOutcome.country.in_(countries),
            AwardOutcome.procurement_group == CONSULTING_GROUP,
            AwardOutcome.notice_date >= since, AwardOutcome.notice_date <= today,
        ).group_by(AwardOutcome.country)
    )).all()}
    out: list[dict[str, Any]] = []
    detail: dict[str, Any] = {}

    def emit(metric: str, country: str, value: Any, *, lender: str = "World Bank", sector: str = "All",
             segment: str = "all", unit: str = "count", note: str = "") -> None:
        out.append({"metric": metric, "country": country, "lender": lender, "sector": sector, "segment": segment,
                    "value": value, "unit": unit, "note": note})

    for country in countries:
        country_rows = [(row, sectors) for row, sectors in rows if row.country == country]
        lenders = sorted({LENDER_LABELS.get(row.lender, row.lender) for row, _ in country_rows}) or ["World Bank"]
        for lender in lenders:
            scoped = [(row, sectors) for row, sectors in country_rows if LENDER_LABELS.get(row.lender, row.lender) == lender]
            stats = _sizing_stats(scoped)
            detail.setdefault(country, {})[lender] = stats
            emit("assignments_with_award_notice", country, stats["notices"], lender=lender)
            emit("bids", country, stats["bids"], lender=lender, note="a joint venture is one bid")
            for segment in ("all", "local", "foreign", "unknown"):
                emit("distinct_firms", country, stats["firms"][segment], lender=lender, segment=segment,
                     note="joint-venture members counted as separate firms")
            for segment in ("all", "local", "foreign"):
                for label, count in stats["bid_distribution"][segment].items():
                    emit("firms_by_bid_count", country, count, lender=lender, segment=f"{segment}:{label} bids")
                emit("median_bids_per_firm", country, stats["median_bids"][segment], lender=lender, segment=segment,
                     unit="bids")
            emit("awarded_contracts", country, stats["awards"], lender=lender)
            emit("individual_consultant_awards", country, individual_awards.get(country, 0), lender=lender,
                 note="excluded from every firm count")
            emit("awarded_contracts_with_published_value", country, stats["awards_with_value"], lender=lender)
            for currency, amount in sorted(stats["awarded_value"].items()):
                emit("awarded_value", country, format(amount, "f"), lender=lender, unit=currency,
                     note="signed contract price, else the awarded bid's evaluated price; not converted")
            for method, count in sorted(stats["notices_by_method"].items()):
                emit("assignments_by_method", country, count, lender=lender, segment=method)
            for sector, sector_stats in sorted(stats["by_sector"].items()):
                emit("distinct_firms", country, sector_stats["firms"], lender=lender, sector=sector,
                     note="sector as tagged on the project; a project can carry several")
                emit("bids", country, sector_stats["bids"], lender=lender, sector=sector)
                emit("awarded_contracts", country, sector_stats["awards"], lender=lender, sector=sector)
                for currency, amount in sorted(sector_stats["awarded_value"].items()):
                    emit("awarded_value", country, format(amount, "f"), lender=lender, sector=sector, unit=currency)
    return {
        "since": since, "until": today, "months": months, "countries": list(countries),
        "rows": out, "detail": detail, "individual_consultant_awards": individual_awards,
    }


def _sizing_stats(rows: list[tuple[AwardOutcome, list[str]]]) -> dict[str, Any]:
    firm_bids: dict[tuple[str, str], set] = defaultdict(set)
    firm_segment: dict[tuple[str, str], str] = {}
    bids: set = set()
    notices: dict[str, str] = {}
    awards: dict[tuple, AwardOutcome] = {}
    sector_firms: dict[str, set] = defaultdict(set)
    sector_bids: dict[str, set] = defaultdict(set)
    sector_awards: dict[str, dict[tuple, AwardOutcome]] = defaultdict(dict)
    for row, sectors in rows:
        key = _firm_key(row)
        bid = (row.lender, row.notice_id, row.bid_ordinal)
        firm_bids[key].add(bid)
        firm_segment.setdefault(key, _segment(row))
        bids.add(bid)
        notices[row.notice_id] = row.procurement_method or "Unspecified"
        if row.status == "AWARDED" and row.member_ordinal == 1:
            awards[bid] = row
        for sector in sectors or ["Unspecified"]:
            sector_firms[sector].add(key)
            sector_bids[sector].add(bid)
            if row.status == "AWARDED" and row.member_ordinal == 1:
                sector_awards[sector][bid] = row

    def values(rows_: Iterable[AwardOutcome]) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for award in rows_:
            currency, amount = _award_value(award)
            if currency and amount is not None:
                totals[currency] += amount
        return dict(totals)

    segments = {"all": list(firm_bids)}
    for segment in ("local", "foreign", "unknown"):
        segments[segment] = [key for key in firm_bids if firm_segment[key] == segment]
    distribution = {}
    medians = {}
    for segment in ("all", "local", "foreign"):
        counts = [len(firm_bids[key]) for key in segments[segment]]
        distribution[segment] = {label: sum(1 for value in counts if _bucket(value) == label) for *_, label in BID_BUCKETS}
        medians[segment] = statistics.median(counts) if counts else 0
    return {
        "notices": len(notices),
        "bids": len(bids),
        "firms": {segment: len(keys) for segment, keys in segments.items()},
        "bid_distribution": distribution,
        "median_bids": medians,
        "awards": len(awards),
        "awards_with_value": sum(1 for award in awards.values() if _award_value(award)[1] is not None),
        "awarded_value": values(awards.values()),
        "notices_by_method": dict(Counter(notices.values())),
        "by_sector": {
            sector: {
                "firms": len(sector_firms[sector]), "bids": len(sector_bids[sector]),
                "awards": len(sector_awards[sector]), "awarded_value": values(sector_awards[sector].values()),
            }
            for sector in sector_firms
        },
        "top_firms": sorted(
            ((len(firm_bids[key]), key[0], key[1], firm_segment[key]) for key in firm_bids), reverse=True
        )[:10],
    }


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


def market_sizing_markdown(result: dict[str, Any], *, generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now(timezone.utc)
    lines = [
        "# MDB consulting market sizing — Uzbekistan and Kazakhstan",
        "",
        f"Window: award notices published {result['since'].isoformat()} to {result['until'].isoformat()} "
        f"({result['months']} months). Generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')} from the PlasmaOS "
        "award ledger.",
        "",
        "## Results (World Bank consulting assignments)",
        "",
        "| | " + " | ".join(result["countries"]) + " |",
        "|---|" + "---|" * len(result["countries"]),
    ]
    stats = {country: result["detail"].get(country, {}).get("World Bank") for country in result["countries"]}

    def row(label: str, value) -> None:
        lines.append(f"| {label} | " + " | ".join(value(stats[c]) if stats[c] else "0" for c in result["countries"]) + " |")

    row("Assignments with a published award notice", lambda s: str(s["notices"]))
    row("Bids (a joint venture is one bid)", lambda s: str(s["bids"]))
    row("Distinct firms that bid", lambda s: str(s["firms"]["all"]))
    row("— local firms", lambda s: str(s["firms"]["local"]))
    row("— foreign firms", lambda s: str(s["firms"]["foreign"]))
    row("— country not published", lambda s: str(s["firms"]["unknown"]))
    row("Median bids per firm", lambda s: f"{s['median_bids']['all']:g}")
    for *_, label in BID_BUCKETS:
        row(f"Firms with {label} bid(s)", lambda s, label=label: str(s["bid_distribution"]["all"][label]))
    row("Awarded contracts (firms)", lambda s: str(s["awards"]))
    row("— with a published value", lambda s: str(s["awards_with_value"]))
    row("Awarded value (as published, not converted)", lambda s: _money(s["awarded_value"]))
    lines.append("| Individual-consultant awards (excluded above) | " + " | ".join(
        str(result["individual_consultant_awards"].get(country, 0)) for country in result["countries"]) + " |")
    lines.append("")
    for country in result["countries"]:
        s = stats[country]
        if not s:
            continue
        lines += [f"### {country}: selection methods", ""]
        lines += [f"- {method}: {count}" for method, count in sorted(s["notices_by_method"].items(), key=lambda x: -x[1])]
        lines += ["", f"### {country}: by sector (project sector tags; a project can carry several)", "",
                  "| Sector | Firms | Bids | Awards | Awarded value |", "|---|---|---|---|---|"]
        for sector, sector_stats in sorted(s["by_sector"].items(), key=lambda item: -item[1]["bids"]):
            lines.append(f"| {sector} | {sector_stats['firms']} | {sector_stats['bids']} | {sector_stats['awards']} | "
                         f"{_money(sector_stats['awarded_value'])} |")
        lines.append("")
    lines += [
        "## Method",
        "",
        "- Source: World Bank procurement-notice API, notice type \"Contract Award\", project country Uzbekistan or "
        "Kazakhstan, procurement group \"Consultant Services\", notice date inside the window. Each notice is stored "
        "verbatim (raw text, retrieval time, content hash) and parsed deterministically: the Awarded, Evaluated and "
        "Rejected sections list every firm whose proposal was opened; firms listed together before one score/price "
        "block are one joint-venture bid.",
        "- A bid is one proposal on one assignment. A firm is a normalized name (upper-case, punctuation and legal "
        "forms such as LLC/LTD/JSC removed) plus the firm's published country; a firm in a joint venture is counted "
        "as a bidder on that bid.",
        "- Local = the firm's published country is the project country; foreign = any other country.",
        "- Awarded value = the signed contract price, or the awarded bid's final evaluated price when no signed price "
        "is published; counted once per joint venture; amounts are summed per currency and not converted.",
        "",
        "## Caveats",
        "",
        "- Coverage is World Bank contract-award notices only. ADB and EBRD consulting awards are not in the ledger "
        "(ADB and EBRD publish winners and contract values but not the other firms that bid; see "
        "docs/audits/s1/ADB_EBRD_REJECTED_BIDDER_DISCLOSURE.md): these counts are a floor for the MDB market, not its "
        "size.",
        "- Only assignments whose award notice is published are counted; shortlisting-only stages (expressions of "
        "interest that never reached proposals), cancelled selections and awards not yet published are missing.",
        "- Direct Selection awards have one firm and no competition; they are included (see methods).",
        "- Kazakhstan's World Bank consulting volume is small, so its figures rest on few notices.",
        "- Name normalization can split one firm written two ways, or (rarely) merge two firms with the same "
        "normalized name and country.",
        "- Sector figures overlap: a project tagged with several sectors counts in each.",
        "- Values are as published, in the currency of the notice; a few notices publish multi-currency prices, "
        "which are kept as text and not summed. Source entry errors are kept as published (for example a BDT "
        "amount on an Uzbekistan notice).",
        "",
    ]
    return "\n".join(lines)
