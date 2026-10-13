"""S1-7: notice-country validation for the award ledger.

Two checks per notice (latest snapshot), both kept as flags: the ledger is append-only and every
notice stays stored and readable; flagged notices are left out of every sizing figure and target list.

1. **Project country.** The notice's World Bank project id is resolved against the World Bank Projects
   API (``WORLD_BANK_PROJECTS_API_URL``: https://search.worldbank.org/api/v2/projects?format=json&id=<P…>)
   through the existing project-enrichment pipeline, so responses are cached in ``projects`` (country,
   raw provenance, enrichment status and time). A notice is flagged when the project's country is a
   specific country other than the ledger country, or when the project cannot be resolved. A regional
   project (e.g. "Central Asia", "Western and Central Africa") is not a mismatch.
2. **Foreign bidder section.** The notice is priced in a currency that is neither the project country's
   own nor an international/contractor currency (USD, EUR, GBP, JPY, CHF, RUB, CNY, TRY), and every bidder
   with a published country is from outside the four ledger countries. Seen on genuine Uzbekistan
   packages whose whole award section lists, e.g., Ethiopian contractors bidding in ETB: the award record
   of another country's procurement attached to the package at publication.
3. **Duplicate award notice.** Every award of the notice (country, package reference and title, awarded
   firm, award date, published price) is published again in another notice, e.g. OP00424867 and
   OP00425438 (one Uzbekistan audit, USD 33,000, 2026-01-23). The notice with more awards, else the newest
   notice id, is kept; the others are flagged. A notice with an award of its own (another lot) is kept.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import Project
from app.models.award_ledger import AwardNoticeSnapshot, AwardOutcome

PROJECTS_ENDPOINT = "https://search.worldbank.org/api/v2/projects?format=json&id=<project id>&rows=1"
LEDGER_COUNTRY_KEYS = {"UZBEKISTAN", "KYRGYZ REPUBLIC", "TAJIKISTAN", "KAZAKHSTAN"}
LOCAL_CURRENCY = {"UZBEKISTAN": "UZS", "KYRGYZ REPUBLIC": "KGS", "TAJIKISTAN": "TJS", "KAZAKHSTAN": "KZT"}
INTERNATIONAL_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "RUB", "CNY", "TRY"}
# Project "countries" that name a region: a notice of any member country may sit on them.
_REGIONAL_WORDS = ("central asia", "europe and central asia", "africa", "world", "region", "western", "eastern",
                   "southern", "multi", "south asia", "middle east")
_COUNTRY_ALIASES = {"KYRGYZSTAN": "KYRGYZ REPUBLIC", "REPUBLIC OF UZBEKISTAN": "UZBEKISTAN",
                    "REPUBLIC OF KAZAKHSTAN": "KAZAKHSTAN", "REPUBLIC OF TAJIKISTAN": "TAJIKISTAN"}

FLAG_PROJECT_COUNTRY = "PROJECT_COUNTRY_MISMATCH"
FLAG_PROJECT_UNRESOLVED = "PROJECT_NOT_RESOLVABLE"
FLAG_FOREIGN_BIDDERS = "FOREIGN_BIDDER_SECTION"
FLAG_DUPLICATE = "DUPLICATE_AWARD_NOTICE"
# Mis-tagged notices are left out of sizing figures and target lists. A project the Projects API does not
# return (preparation-stage or very new projects: total 0 on v2 and v3) is flagged and reported, not excluded:
# nothing says the notice belongs elsewhere.
EXCLUDED_FLAGS = {FLAG_PROJECT_COUNTRY, FLAG_FOREIGN_BIDDERS, FLAG_DUPLICATE}


def _key(value: str | None) -> str:
    key = " ".join((value or "").upper().split())
    return _COUNTRY_ALIASES.get(key, key)


def is_regional(country: str | None) -> bool:
    value = (country or "").casefold()
    return any(word in value for word in _REGIONAL_WORDS) or ";" in value


@dataclass(frozen=True)
class NoticeFlag:
    notice_id: str
    flag: str
    ledger_country: str | None
    project_id: str | None
    project_country: str | None
    detail: str


async def resolve_ledger_projects(db: AsyncSession, *, client=None, max_age_days: int = 30,
                                  delay_seconds: float = 0.2) -> dict[str, int]:
    """Make sure every ledger project id has a cached World Bank project record (country) in ``projects``."""
    import asyncio

    from app.services.project_enrichment import apply_world_bank_project_snapshot, mark_project_enrichment_failure
    from app.services.projects import resolve_or_create_project
    from app.services.world_bank_projects import (
        WorldBankProjectsClient, WorldBankProjectSourceError, normalize_world_bank_project_record,
    )

    client = client or WorldBankProjectsClient()
    project_ids = sorted({value for value in (await db.scalars(
        select(AwardNoticeSnapshot.project_id).where(AwardNoticeSnapshot.project_id.is_not(None)).distinct()
    )).all() if value})
    fresh_after = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    counts = {"projects": len(project_ids), "fetched": 0, "cached": 0, "failed": 0, "invalid": 0}
    for external_id in project_ids:
        try:
            project, _created = await resolve_or_create_project(db, source_system="world_bank", external_project_id=external_id)
        except ValueError:
            counts["invalid"] += 1
            continue
        if project.country and project.last_enriched_at and project.last_enriched_at >= fresh_after:
            counts["cached"] += 1
            continue
        try:
            record = await client.fetch_project(external_id)
            snapshot = normalize_world_bank_project_record(external_id, record)
            await apply_world_bank_project_snapshot(db, project_id=project.id, snapshot=snapshot)
            counts["fetched"] += 1
        except WorldBankProjectSourceError as exc:
            await mark_project_enrichment_failure(db, project_id=project.id, status=exc.status,
                                                  failure_class=exc.failure_class)
            counts["failed"] += 1
        await db.commit()
        if delay_seconds:
            await asyncio.sleep(delay_seconds)
    return counts


async def notice_flags(db: AsyncSession) -> dict[str, NoticeFlag]:
    """Flags for the latest snapshot of every notice (read-only; uses the cached project records)."""
    from app.services.award_ledger_reports import latest_snapshot_ids

    snapshots = (await db.execute(
        select(AwardNoticeSnapshot.notice_id, AwardNoticeSnapshot.country, AwardNoticeSnapshot.project_id,
               AwardNoticeSnapshot.project_name)
        .where(AwardNoticeSnapshot.id.in_(latest_snapshot_ids()))
    )).all()
    projects = {row.external_project_id: row for row in (await db.scalars(
        select(Project).where(Project.source_system == "world_bank"))).all()}
    priced: dict[str, set[str]] = defaultdict(set)
    bidder_countries: dict[str, set[str]] = defaultdict(set)
    for notice_id, evaluated, signed, bidder_country in (await db.execute(
        select(AwardOutcome.notice_id, AwardOutcome.evaluated_price_currency, AwardOutcome.signed_contract_currency,
               AwardOutcome.bidder_country).where(AwardOutcome.snapshot_id.in_(latest_snapshot_ids()))
    )).all():
        priced[notice_id].update(value for value in (evaluated, signed) if value)
        if bidder_country:
            bidder_countries[notice_id].add(_key(bidder_country))
    flags: dict[str, NoticeFlag] = {}
    for notice_id, country, project_id, project_name in snapshots:
        project = projects.get(project_id or "")
        project_country = project.country if project else None
        if project is None or not project_country:
            named = " (the notice's project name names the ledger country)" if country and project_name and                 country.split()[0].casefold()[:5] in project_name.casefold() else ""
            flags[notice_id] = NoticeFlag(notice_id, FLAG_PROJECT_UNRESOLVED, country, project_id, None,
                                          (f"Projects API returns no record for {project_id}: {project_name}{named}"
                                           if project_id else "notice has no project id"))
            continue
        if not is_regional(project_country) and _key(project_country) != _key(country):
            flags[notice_id] = NoticeFlag(notice_id, FLAG_PROJECT_COUNTRY, country, project_id, project_country,
                                          f"project {project_id} is in {project_country}")
            continue
        expected = INTERNATIONAL_CURRENCIES | {LOCAL_CURRENCY.get(_key(country), "")}
        foreign = sorted(priced.get(notice_id, set()) - expected)
        bidders = bidder_countries.get(notice_id, set())
        if foreign and bidders and not (bidders & LEDGER_COUNTRY_KEYS):
            flags[notice_id] = NoticeFlag(
                notice_id, FLAG_FOREIGN_BIDDERS, country, project_id, project_country,
                f"priced in {', '.join(foreign)}; every bidder from {', '.join(sorted(bidders)).title()}")
    for notice_id, (kept, detail) in (await duplicate_award_notices(db)).items():
        if notice_id in flags and flags[notice_id].flag in EXCLUDED_FLAGS:
            continue
        snapshot = next((row for row in snapshots if row.notice_id == notice_id), None)
        flags[notice_id] = NoticeFlag(notice_id, FLAG_DUPLICATE, snapshot.country if snapshot else None,
                                      snapshot.project_id if snapshot else None,
                                      flags[notice_id].project_country if notice_id in flags else None,
                                      f"same award as {kept}: {detail}")
    return flags


async def duplicate_award_notices(db: AsyncSession) -> dict[str, tuple[str, str]]:
    """Notices whose every award is published again in another notice: {notice id: (kept id, detail)}.

    An award is (country, package reference and title, awarded firm, award date, published price). A notice
    is a duplicate when all its awards are in another notice that has more awards, or the same awards and a
    newer notice id; a notice with an award of its own (another lot) is never a duplicate."""
    from app.services.award_ledger_reports import latest_snapshot_ids

    awards: dict[str, set[tuple]] = defaultdict(set)
    for row in (await db.execute(
        select(AwardOutcome.notice_id, AwardOutcome.country, AwardOutcome.package_reference, AwardOutcome.package_title,
               AwardOutcome.bidder_name_normalized, AwardOutcome.award_date, AwardOutcome.signed_contract_price_text,
               AwardOutcome.evaluated_price_text)
        .where(AwardOutcome.snapshot_id.in_(latest_snapshot_ids()), AwardOutcome.status == "AWARDED",
               AwardOutcome.member_ordinal == 1)
    )).all():
        if not (row.package_reference or "").strip() or row.award_date is None:
            continue
        price = row.signed_contract_price_text or row.evaluated_price_text or ""
        awards[row.notice_id].add((row.country, row.package_reference.strip(), (row.package_title or "").strip().casefold(),
                                   row.bidder_name_normalized, row.award_date, price))
    by_award: dict[tuple, set[str]] = defaultdict(set)
    for notice_id, keys in awards.items():
        for key in keys:
            by_award[key].add(notice_id)
    duplicates: dict[str, tuple[str, str]] = {}
    for notice_id, keys in awards.items():
        others = set.intersection(*(by_award[key] for key in keys)) - {notice_id}  # notices holding every award
        covering = [other for other in others if len(awards[other]) > len(keys) or other > notice_id]
        if not covering:
            continue
        kept = max(covering, key=lambda other: (len(awards[other]), other))
        _country, reference, _title, _bidder, awarded, price = sorted(keys)[0]
        more = f" (+{len(keys) - 1} more awards)" if len(keys) > 1 else ""
        # no firm name in the detail: some awardees are natural persons (the firm column of the report carries it)
        duplicates[notice_id] = (kept, f"package {reference}, awarded {awarded.isoformat()}, {price}".strip(", ") + more)
    # a chain (A in B in C) keeps only notices nobody covers
    for notice_id, (kept, detail) in list(duplicates.items()):
        seen = {notice_id}
        while kept in duplicates and kept not in seen:
            seen.add(kept)
            kept = duplicates[kept][0]
        duplicates[notice_id] = (kept, detail)
    return duplicates


async def excluded_notice_ids(db: AsyncSession) -> set[str]:
    return {notice_id for notice_id, flag in (await notice_flags(db)).items() if flag.flag in EXCLUDED_FLAGS}


async def validation_rows(db: AsyncSession) -> list[dict[str, Any]]:
    """Every flagged notice with its awarded firm and currency, for the report."""
    from app.services.award_ledger_reports import latest_snapshot_ids

    flags = await notice_flags(db)
    awards: dict[str, tuple[str, str | None]] = {}
    for notice_id, name, signed, evaluated in (await db.execute(
        select(AwardOutcome.notice_id, AwardOutcome.bidder_name, AwardOutcome.signed_contract_currency,
               AwardOutcome.evaluated_price_currency)
        .where(AwardOutcome.snapshot_id.in_(latest_snapshot_ids()), AwardOutcome.notice_id.in_(list(flags)),
               AwardOutcome.status == "AWARDED", AwardOutcome.member_ordinal == 1)
    )).all():
        awards.setdefault(notice_id, (name, signed or evaluated))
    rows = []
    for notice_id, flag in sorted(flags.items()):
        firm, currency = awards.get(notice_id, ("", None))
        rows.append({"notice_id": notice_id, "flag": flag.flag, "excluded": flag.flag in EXCLUDED_FLAGS,
                     "ledger_country": flag.ledger_country,
                     "project_id": flag.project_id, "project_country": flag.project_country, "firm": firm,
                     "currency": currency or "", "detail": flag.detail})
    return rows
