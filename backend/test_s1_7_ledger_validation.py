"""S1-7: notice-country validation (Projects API cache, foreign bidder sections) and legal forms in words."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.all_models import Project
from app.services.award_ledger import ingest_world_bank_awards
from app.services.award_ledger_parser import normalize_firm_name, transliterate
from app.services.award_ledger_reports import list_outcomes, market_sizing, outreach_targets, OutcomeFilters
from app.services.award_ledger_validation import (
    FLAG_DUPLICATE, FLAG_FOREIGN_BIDDERS, FLAG_PROJECT_COUNTRY, FLAG_PROJECT_UNRESOLVED, is_regional, notice_flags,
    resolve_ledger_projects, validation_rows,
)
from app.services.world_bank_projects import WorldBankProjectSourceError
from scripts import test_s0_5b4_baseline as support
from test_s1_award_ledger import HEAD, NOW, _html, _pages, _row


# ---- pure ------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("a", "b"), [
    ("NEW TECH SAMARKAND, MASULIYATI CHEKLANGAN JAMIYATI", "New Tech Samarkand LLC"),
    ("KRANTASLIZING, MAS'ULIYATI CHEKLANGAN JAMIYATI", "Krantaslizing MChJ"),
    ("O ZELEKTROAPPARAT-ELECTROSHIELD, AKSIYADORLIK JAMIYATI", "JSC O'ZELEKTROAPPARAT-ELECTROSHIELD"),
    ("Xususiy korxona Nur Baraka", "NUR BARAKA XK"),
    ("“ASPMK-519” LIMITED LIABILITY PARTNERSHIP", 'TOO "ASPMK-519"'),
    ('ООО "PROSPEROUSTORE"', "Prosperoustore LLC"),
    ("Общество с ограниченной ответственностью «Строй Мастер»", "OOO Stroy Master"),
    ("Obshchestvo s ogranichennoy otvetstvennostyu Alfa", "Alfa LLC"),
    ('АКЦИОНЕРНОЕ ОБЩЕСТВО "УЗБЕКЭНЕРГО"', "AO UZBEKENERGO"),
    ('OPEN JOINT STOCK COMPANY "TAJIKSGEM"', "TAJIKSGEM OJSC"),
])
def test_legal_forms_in_words_and_cyrillic(a: str, b: str) -> None:
    assert normalize_firm_name(a) == normalize_firm_name(b) != ""


def test_short_words_are_not_taken_for_legal_forms() -> None:
    for name, expected in (("I-TECH", "I TECH"), ("OK STROY", "OK STROY"), ("LEADER HORSE", "LEADER HORSE"),
                           ("AKSIYA GROUP", "AKSIYA GROUP")):
        assert normalize_firm_name(name) == expected
    assert transliterate("ЎЗБЕКИСТОН ҚУРИЛИШ") == "OZBEKISTON QURILISH"


def test_regional_projects_are_not_mismatches() -> None:
    assert is_regional("Central Asia") and is_regional("Western and Central Africa") and not is_regional("Uzbekistan")


# ---- disposable database -------------------------------------------------------------------------

def names_of(targets: list[dict]) -> set[str]:
    return {item["normalized_name"] for item in targets}


def _notice(notice_id: str, project_id: str, *, bidders: list[tuple[str, str]], price: str, country: str = "Uzbekistan",
            group: str = "Works") -> dict:
    sections = [("Awarded", [([bidders[0]], price, None)])]
    if len(bidders) > 1:
        sections.append(("Rejected", [([item], price.split()[0], "Non Responsive") for item in bidders[1:]]))
    return dict(_row(notice_id, country=country, noticedate="01-Sep-2026", group=group, text_html=_html(*sections)),
                project_id=project_id)


ROWS = [
    _notice("OK-1", "P100001", bidders=[("LOCAL BUILDER LLC (100)", "Uzbekistan"), ("SECOND LOCAL (110)", "Uzbekistan")],
            price="UZS 1000000000.00"),
    # a genuine Uzbekistan package whose whole award section is another country's procurement
    _notice("ETB-1", "P100001", bidders=[("NO MISS CONSTRUCTION PLC (200)", "Ethiopia"), ("WAKA CONSTRUCTION (210)", "Ethiopia")],
            price="ETB 86724005.62"),
    # a currency label error with local bidders: the notice stays, only the value is flagged
    _notice("AED-1", "P100001", bidders=[("MUKAMMAL DIZAYN LOYIHA (300)", "Uzbekistan")], price="AED 100000000.00"),
    # a notice on a project of another country
    _notice("KZP-1", "P200002", bidders=[("STEPPE ROADS (400)", "Uzbekistan")], price="USD 500000.00"),
    # a project the Projects API does not return: flagged, kept
    _notice("NEW-1", "P300003", bidders=[("NEW PROJECT FIRM LLC (500)", "Uzbekistan")], price="USD 70000.00",
            group="Consultant Services"),
    # the same award published again under another notice id (same package reference and title, firm,
    # award date, price): the newer notice id is kept
    dict(_notice("OK-2", "P100001", bidders=[("LOCAL BUILDER LLC (100)", "Uzbekistan"), ("SECOND LOCAL (110)", "Uzbekistan")],
                 price="UZS 1000000000.00"), bid_reference_no="REF-OK-1", bid_description="Assignment OK-1"),
    # two lots awarded in one notice; a later notice repeats only the first lot: the later one is the duplicate,
    # the two-lot notice is kept (its second lot is an award of its own)
    dict(_row("LOT-A", country="Uzbekistan", noticedate="01-Sep-2026", group="Goods", text_html=_html(
        ("Awarded", [([("PREMIER UNITED (700)", "Uzbekistan")], "USD 100000.00", None),
                     ([("KRORAINA TRADE (710)", "Uzbekistan")], "USD 200000.00", None)]))),
         project_id="P100001", bid_reference_no="REF-LOT", bid_description="Supply of lab equipment"),
    dict(_row("LOT-B", country="Uzbekistan", noticedate="01-Sep-2026", group="Goods", text_html=_html(
        ("Awarded", [([("PREMIER UNITED (700)", "Uzbekistan")], "USD 100000.00", None)]))),
         project_id="P100001", bid_reference_no="REF-LOT", bid_description="Supply of lab equipment"),
    # a regional project
    _notice("REG-1", "P400004", bidders=[("REGIONAL FIRM (600)", "Uzbekistan")], price="USD 80000.00"),
]


class FakeProjectsClient:
    countries = {"P100001": "Uzbekistan", "P200002": "Kazakhstan", "P400004": "Central Asia"}

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch_project(self, external_id: str) -> dict:
        self.calls.append(external_id)
        if external_id not in self.countries:
            raise WorldBankProjectSourceError("no record", failure_class="empty_authoritative_response",
                                              retryable=False, status="failed")
        return {"id": external_id, "countryshortname": self.countries[external_id],
                "project_name": f"Project {external_id}", "projectstatusdisplay": "Active"}


def test_notice_country_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        database = support.database_name("s1_7_validation")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            engine = create_async_engine(support.target_url(database), pool_size=4)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                await _flow(sessions)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _flow(sessions) -> None:
    async with sessions() as db:
        await ingest_world_bank_awards(db, fetch=_pages(ROWS)[0], countries=("Uzbekistan",), since=date(2024, 10, 10),
                                       now=NOW, request_delay_seconds=0)
        # before any project is resolved, every notice is unverified (nothing is excluded for that); the
        # duplicate needs no project
        early = {notice_id: flag.flag for notice_id, flag in (await notice_flags(db)).items()}
        assert early.pop("OK-1") == early.pop("LOT-B") == FLAG_DUPLICATE
        assert set(early.values()) == {FLAG_PROJECT_UNRESOLVED} and "LOT-A" in early

        client = FakeProjectsClient()
        counts = await resolve_ledger_projects(db, client=client, delay_seconds=0)
        assert counts == {"projects": 4, "fetched": 3, "cached": 0, "failed": 1, "invalid": 0}
        again = await resolve_ledger_projects(db, client=client, delay_seconds=0)  # cached in projects
        assert (again["cached"], again["fetched"]) == (3, 0) and client.calls.count("P100001") == 1
        assert await db.scalar(select(Project.country).where(Project.external_project_id == "P200002")) == "Kazakhstan"

        flags = {notice_id: flag.flag for notice_id, flag in (await notice_flags(db)).items()}
        assert flags == {"ETB-1": FLAG_FOREIGN_BIDDERS, "KZP-1": FLAG_PROJECT_COUNTRY, "NEW-1": FLAG_PROJECT_UNRESOLVED,
                         "OK-1": FLAG_DUPLICATE, "LOT-B": FLAG_DUPLICATE}
        rows = {row["notice_id"]: row for row in await validation_rows(db)}
        assert rows["ETB-1"]["excluded"] and rows["ETB-1"]["currency"] == "ETB" and rows["ETB-1"]["firm"] == "NO MISS CONSTRUCTION PLC"
        assert rows["KZP-1"]["excluded"] and rows["KZP-1"]["project_country"] == "Kazakhstan"
        assert not rows["NEW-1"]["excluded"] and "P300003" in rows["NEW-1"]["detail"]
        assert rows["OK-1"]["excluded"] and rows["OK-1"]["detail"].startswith("same award as OK-2: package REF-OK-1")
        assert rows["LOT-B"]["detail"].startswith("same award as LOT-A: package REF-LOT, awarded ")
        assert "PREMIER" not in rows["LOT-B"]["detail"] and rows["LOT-B"]["firm"] == "PREMIER UNITED"

        # excluded from sizing and targets, still in the ledger
        sizing = await market_sizing(db, today=date(2026, 10, 10))
        uz = sizing["detail"]["All categories"]["Uzbekistan"]
        assert uz["notices"] == 5  # OK-2 (OK-1 is its duplicate), LOT-A (LOT-B is its duplicate), AED-1, NEW-1, REG-1
        before = await market_sizing(db, today=date(2026, 10, 10), include_flagged_notices=True)
        assert before["detail"]["All categories"]["Uzbekistan"]["notices"] == 9
        assert [row["notice_id"] for row in sizing["validation"] if row["excluded"]] == ["ETB-1", "KZP-1", "LOT-B", "OK-1"]
        assert "KRORAINA TRADE" in names_of(await outreach_targets(db, today=date(2026, 10, 10)))
        names = {item["normalized_name"] for item in await outreach_targets(db, today=date(2026, 10, 10))}
        assert "NO MISS CONSTRUCTION" not in names and "STEPPE ROADS" not in names and "LOCAL BUILDER" in names
        _items, total = await list_outcomes(db, filters=OutcomeFilters(q="ETB-1"))
        assert total == 2  # kept in the ledger
        assert await db.scalar(select(func.count()).select_from(Project)) >= 4
