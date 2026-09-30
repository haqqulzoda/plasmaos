"""Integration fix 3a: lenient open/closed truth for deadlines published without a zone.

* A World Bank/GIZ deadline (no zone) is read in the capital zone of the tender's
  country (COUNTRY_INFERRED); countdown and status then use that one instant.
* With no inferable zone the countdown still uses UTC+14 (never overstates time left)
  but the tender stays open, "Closing - verify on source", until UTC-12 has passed.
* Python and PostgreSQL agree; sources with a zone ignore the country; the official
  notice header (part of sealed analysis inputs) is unchanged.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, literal, literal_column, select

from app.core import deadline_truth as truth
from app.core.country_timezones import COUNTRY_TIMEZONES, country_timezone
from app.core.tender_actionability import is_tender_actionable, lifecycle_condition
from app.models.all_models import Tender
from app.models.base import TenderStatus
from app.services.official_notice import _format_deadline
from app.services.source_registry import DeadlineTimeBasis
from test_d1_04_05_freshness_truth import _database


def test_country_table_covers_source_spellings_capitals_and_skips_regions() -> None:
    expected = {
        "Mongolia": "Asia/Ulaanbaatar", "Uzbekistan": "Asia/Tashkent", "Kyrgyz Republic": "Asia/Bishkek",
        "Congo, Democratic Republic of": "Africa/Kinshasa", "Congo, Republic of": "Africa/Brazzaville",
        "Turkiye": "Europe/Istanbul", "Cote d'Ivoire": "Africa/Abidjan", "Gambia, The": "Africa/Banjul",
        "Lao People's Democratic Republic": "Asia/Vientiane", "Laos": "Asia/Vientiane",
        "Micronesia, Federated States of": "Pacific/Pohnpei", "West Bank and Gaza": "Asia/Hebron",
        "Kosovo": "Europe/Belgrade", "Viet Nam": "Asia/Ho_Chi_Minh", "Tanzania": "Africa/Dar_es_Salaam",
        "Egypt, Arab Republic of": "Africa/Cairo", "Yemen, Republic of": "Asia/Aden",
        # multi-zone countries: the capital's zone
        "Brazil": "America/Sao_Paulo", "Indonesia": "Asia/Jakarta", "United States": "America/New_York",
        "Russian Federation": "Europe/Moscow", "Kazakhstan": "Asia/Almaty", "Australia": "Australia/Sydney",
        "Mexico": "America/Mexico_City", "Ukraine": "Europe/Kyiv",
    }
    for name, zone in expected.items():
        assert country_timezone(name) == zone, name
        assert country_timezone(f"  {name.upper()} ") == zone, name
    for region in ("Central Asia", "Western and Central Africa", "Eastern and Southern Africa", "Pacific 1", "", None):
        assert country_timezone(region) is None, region
    for zone in set(COUNTRY_TIMEZONES.values()):
        ZoneInfo(zone)
    assert len(COUNTRY_TIMEZONES) >= 280


def test_country_inferred_deadline_uses_one_instant() -> None:
    wall = datetime(2026, 10, 16, 17, 0, tzinfo=UTC)  # "17:00" as published
    result = truth.deadline_time("world_bank", wall, country="Mongolia")
    assert result.basis is DeadlineTimeBasis.COUNTRY_INFERRED
    assert result.timezone == "Asia/Ulaanbaatar"
    assert result.published_local == "2026-10-16T17:00"
    assert result.effective_at == result.closes_at == datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
    giz = truth.deadline_time("giz", datetime(2026, 10, 1, 12, 0, tzinfo=UTC), country="Ghana")
    assert (giz.basis, giz.timezone, giz.closes_at) == (
        DeadlineTimeBasis.COUNTRY_INFERRED, "Africa/Accra", datetime(2026, 10, 1, 12, 0, tzinfo=UTC))


def test_unknown_zone_counts_down_to_the_earliest_and_closes_at_the_latest_instant() -> None:
    wall = datetime(2026, 10, 16, 17, 0, tzinfo=UTC)
    result = truth.deadline_time("world_bank", wall, country="Central Asia")
    assert result.basis is DeadlineTimeBasis.SOURCE_LOCAL_UNSPECIFIED and result.timezone is None
    assert result.effective_at == wall - timedelta(hours=14)
    assert result.closes_at == wall + timedelta(hours=12)
    before, window, after = wall - timedelta(hours=15), wall, wall + timedelta(hours=13)
    status = lambda now, stored="OPEN": truth.derived_status(stored, "world_bank", wall, now=now, country="Central Asia")  # noqa: E731
    assert status(before) == (TenderStatus.OPEN, None)
    assert status(window) == (TenderStatus.OPEN, truth.DEADLINE_VERIFY_ON_SOURCE)
    assert status(window, "UNKNOWN") == (TenderStatus.UNKNOWN, truth.DEADLINE_VERIFY_ON_SOURCE)
    assert status(after) == (TenderStatus.CLOSED, truth.DEADLINE_PASSED)
    assert status(window, "CANCELLED") == (TenderStatus.CANCELLED, None)
    # Still actionable (listed as open) inside the window, not after it.
    row = SimpleNamespace(status=TenderStatus.OPEN, source_system="world_bank", deadline=wall, country=None)
    assert is_tender_actionable(row, now=window) and not is_tender_actionable(row, now=after)
    fields = truth.truth_fields("world_bank", "OPEN", wall, now=window)
    assert (fields["status"], fields["status_reason"]) == (TenderStatus.OPEN, "DEADLINE_VERIFY_ON_SOURCE")
    assert fields["deadline_effective_at"] < window <= fields["deadline_closes_at"]


def test_date_only_deadlines_use_the_country_zone_else_the_whole_day_everywhere() -> None:
    date_only = datetime(2026, 10, 16, 23, 59, 59, 999999, tzinfo=UTC)  # World Bank "no time" marker
    known = truth.deadline_time("world_bank", date_only, country="Uzbekistan")
    assert (known.basis, known.timezone, known.published_local) == (DeadlineTimeBasis.DATE_ONLY, "Asia/Tashkent", "2026-10-16")
    assert known.effective_at == known.closes_at == datetime(2026, 10, 16, 19, 0, tzinfo=UTC)
    unknown = truth.deadline_time("world_bank", date_only)
    assert unknown.timezone is None
    assert unknown.effective_at == datetime(2026, 10, 16, 10, 0, tzinfo=UTC)   # end of day at UTC+14
    assert unknown.closes_at == datetime(2026, 10, 17, 12, 0, tzinfo=UTC)      # end of day at UTC-12


def test_sources_with_a_zone_ignore_the_country() -> None:
    uzex = datetime(2026, 9, 29, 8, 17, 30, tzinfo=UTC)
    assert truth.deadline_time("uzex", uzex, country="Mongolia") == truth.deadline_time("uzex", uzex)
    ebrd = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    assert truth.deadline_time("ebrd", ebrd, country="Kazakhstan") == truth.deadline_time("ebrd", ebrd)


def test_official_notice_header_is_unchanged_by_country_inference() -> None:
    wall = datetime(2026, 10, 16, 17, 0, tzinfo=UTC)
    assert _format_deadline(wall, "world_bank") == "2026-10-16 17:00 local time (as published)"


@pytest.mark.parametrize("latest", [False, True])
def test_sql_matches_python_for_every_source_country_and_time(latest: bool) -> None:
    async def scenario() -> None:
        async with _database("int_3a_sql") as (_database_name, _ids, sessions, _engine):
            stamps = (
                datetime(2026, 10, 16, 17, 0, tzinfo=UTC),
                datetime(2026, 10, 16, 23, 59, 59, 999999, tzinfo=UTC),  # World Bank date-only marker
                datetime(2026, 10, 1, 0, 0, tzinfo=UTC),                   # GIZ/EBRD/ADB date-only marker
                datetime(2026, 3, 29, 1, 30, tzinfo=UTC),                   # DST transition in Europe
            )
            countries = (None, "Mongolia", "  brazil ", "Kyrgyz Republic", "Central Asia", "Cote d'Ivoire", "Nowhere")
            python = truth.closing_deadline if latest else truth.effective_deadline
            sql = truth.closing_deadline_sql if latest else truth.effective_deadline_sql
            async with sessions() as db:
                for source in ("world_bank", "giz", "uzex", "ebrd", "adb", "unknown_source"):
                    for stored in stamps:
                        for country in countries:
                            probe = SimpleNamespace(
                                source_system=literal(source),
                                deadline=literal_column(f"TIMESTAMPTZ '{stored.isoformat()}'"),
                                country=literal(country) if country is not None else literal_column("NULL::varchar"),
                            )
                            value = await db.scalar(select(sql(probe)))
                            assert value == python(source, stored, country=country), (source, stored, country)

    asyncio.run(scenario())


def test_open_lists_keep_window_tenders_and_close_them_after_the_latest_instant() -> None:
    async def scenario() -> None:
        async with _database("int_3a_lists") as (_database_name, _ids, sessions, _engine):
            now = datetime.now(UTC)
            rows = {
                # no zone: earliest passed 2 h ago, latest 24 h ahead -> open, verify on source
                "WINDOW": ("world_bank", now + timedelta(hours=12), "Central Asia"),
                # no zone: latest passed -> closed
                "GONE": ("world_bank", now - timedelta(hours=13), None),
                # Kyrgyz Republic (UTC+6): 3 h ahead in Bishkek -> closed 3 h ago
                "BISHKEK-PASSED": ("world_bank", now + timedelta(hours=3), "Kyrgyz Republic"),
                "BISHKEK-OPEN": ("world_bank", now + timedelta(hours=9), "Kyrgyz Republic"),
            }
            ids = {}
            async with sessions() as db:
                for external_id, (source, deadline, country) in rows.items():
                    tender = Tender(
                        source_system=source, external_id=external_id, canonical_source_key=f"{source}:{external_id}",
                        source_url=f"https://example.test/{external_id}", title=f"INT3A {external_id}",
                        description="d", budget=0, currency="USD", status=TenderStatus.OPEN, category="Other",
                        deadline=deadline, country=country,
                    )
                    db.add(tender)
                    await db.flush()
                    ids[external_id] = tender.id
                await db.commit()
            async with sessions() as db:
                scoped = Tender.id.in_(ids.values())
                open_rows = set((await db.scalars(
                    select(Tender.external_id).where(scoped, lifecycle_condition(Tender, TenderStatus.OPEN, now=now)))).all())
                closed_rows = set((await db.scalars(
                    select(Tender.external_id).where(scoped, lifecycle_condition(Tender, TenderStatus.CLOSED, now=now)))).all())
                uncertain = set((await db.scalars(
                    select(Tender.external_id).where(scoped, truth.deadline_uncertain_sql(Tender, now=now)))).all())
                assert open_rows == {"WINDOW", "BISHKEK-OPEN"}
                assert closed_rows == {"GONE", "BISHKEK-PASSED"}
                assert uncertain == {"WINDOW"}
                assert await db.scalar(select(func.count()).where(scoped, truth.deadline_passed_sql(Tender, now=now))) == 2
                for tender in (await db.scalars(select(Tender).where(scoped))).all():
                    status, reason = truth.derived_status(tender.status, tender.source_system, tender.deadline,
                                                          now=now, country=tender.country)
                    assert (status is TenderStatus.OPEN) == (tender.external_id in open_rows), tender.external_id
                    assert (reason == truth.DEADLINE_VERIFY_ON_SOURCE) == (tender.external_id in uncertain)

    asyncio.run(scenario())
