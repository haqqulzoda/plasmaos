"""Sprint 1: award ledger v0 (World Bank contract-award notices).

Deterministic parsing of real notice formats (fixtures are public notices with the ownership
tables redacted), append-only storage, idempotent and versioned ingestion, latest-snapshot
reads, the firm export, market sizing, and admin-only downloads.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import deps
from app.api.endpoints import admin_award_ledger as endpoints
from app.models.award_ledger import AwardNoticeSnapshot, AwardOutcome
from app.models.user import User
from app.services import award_ledger
from app.services.award_ledger import build_snapshot, ingest_world_bank_awards
from app.services.award_ledger_parser import (
    normalize_firm_name,
    notice_lines,
    parse_money,
    parse_world_bank_award_notice,
)
from app.services.award_ledger_reports import (
    OutcomeFilters,
    firm_export,
    firm_export_csv,
    ledger_summary,
    list_outcomes,
    market_sizing,
    market_sizing_csv,
    market_sizing_markdown,
    outcomes_csv,
)
from scripts import test_s0_5b4_baseline as support


HEAD = "20261023_0001_p2_partner_finder"
LEDGER_REVISION = "20261012_0001_s1_award_ledger"
PREVIOUS = "20261011_0001_r3_organization_record_events"
FIXTURES = {row["id"]: row for row in json.loads(
    (Path(__file__).parent / "fixtures" / "s1_award_notices.json").read_text(encoding="utf-8")
)}
NOW = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)


def _members(bid) -> list[tuple[str, str | None, str | None]]:
    return [(member.name, member.source_id, member.country) for member in bid.members]


# ---- parser --------------------------------------------------------------------------------------------

def test_consulting_notice_joint_ventures_evaluated_and_rejected() -> None:
    parsed = parse_world_bank_award_notice(FIXTURES["OP00472568"]["notice_text"])
    assert parsed.award_date == date(2026, 6, 30)
    assert parsed.contract_duration == "18 Month(s)"
    assert parsed.minimum_qualifying_score == "75"
    assert [bid.status for bid in parsed.bids] == ["AWARDED", "EVALUATED", "EVALUATED", "REJECTED"]
    awarded, idom, ars, rejected = parsed.bids
    # Three firms before one score/price block are one joint venture; ownership blocks between
    # them neither split the bid nor add a bidder.
    assert _members(awarded) == [
        ("ARUP INTERNATIONAL PROJECTS LTD", "539411", "United Kingdom"),
        ("ISLOHOTKONSALTSERVIS LTD., (IKS CONSULTING)", "470308", "Uzbekistan"),
        ("ARUP MHENDISLIK VE MAVIRLIK LTD. TI.", "666322", "Turkiye"),
    ]
    assert awarded.evaluated_price == "USD 2236567.27"
    assert awarded.signed_contract_price == "USD 2236567.27"
    assert awarded.scores["Technical"] == "88.23" and awarded.scores["Rank"] == "1"
    assert awarded.rejection_reason is None
    assert _members(idom) == [("IDOM, CONSULTING, ENGINEERING AND ARCHITECTURE, SAU (IDOM)", "455708", "Spain")]
    assert idom.evaluated_price == "USD 1913906.90"
    assert [name for name, _, _ in _members(ars)] == [
        "A.R.S PROGETTI", "SUPERWIEN URBANISM ZT OG", "ARCHERITAGE ADVISORS LLC"]
    assert ars.evaluated_price == "USD 2532302.38"
    assert _members(rejected) == [
        ("CHINA URBAN CONSTRUCTION DESIGN AND RESEARCH INSTITUTE CO.,LTD", "353926", "China")]
    assert rejected.rejection_reason == "Non-compliance"
    assert rejected.evaluated_price is None  # the label is published with no value


def test_works_notice_rejections_are_verbatim_and_prices_parsed() -> None:
    parsed = parse_world_bank_award_notice(FIXTURES["OP00469964"]["notice_text"])
    statuses = [bid.status for bid in parsed.bids]
    assert statuses == ["AWARDED"] + ["REJECTED"] * 9
    assert parsed.bids[0].evaluated_price == "UZS 6941682566.00"
    assert parsed.bids[0].bid_price_at_opening == "UZS"
    assert {bid.rejection_reason for bid in parsed.bids[1:]} == {"Failure to meet minimum technical score"}
    assert all(len(bid.members) == 1 for bid in parsed.bids)
    quotations = parse_world_bank_award_notice(FIXTURES["OP00467845"]["notice_text"])
    assert [(bid.status, bid.members[0].name, bid.evaluated_price, bid.rejection_reason) for bid in quotations.bids] == [
        ("AWARDED", "SKB ENERGETIKA ASBOB USKUNALARINI TAKOMILLASHTIRISH BO`YICHA MARKAZIY KONSRTUKTORLIK BYUROSI",
         "UZS 790000000.00", None),
        ("EVALUATED", "ENERGY POWER SOLUTION", "UZS 1185800000.00", None),
        ("REJECTED", "MAXSUS ENERGO AUDIT FE LLC", "UZS 600000000.00", "Non Responsive"),
        ("REJECTED", "TREST-5", "UZS", "Non Responsive"),
    ]


def test_ownership_repeats_and_declarations_are_not_bidders_or_reasons() -> None:
    goods = parse_world_bank_award_notice(FIXTURES["OP00431777"]["notice_text"])
    # The awarded firm's name is repeated in its ownership block: still one bidder.
    assert [(bid.status, [m.name for m in bid.members]) for bid in goods.bids] == [
        ("AWARDED", ["YEO TEKNOLOJI ENERJI VE ENDUSTRI ANONIM SIRKETI (A.S.)"]),
        ("REJECTED", ["KONTROLMATIK TECHNOLOJI ENERJI VE MUHENDISLIK A.S."]),
        ("REJECTED", ["Nari Technology Co.,Ltd."]),
    ]
    assert goods.bids[0].signed_contract_price == "UZS 74462524391.54; USD 30532398.34"
    assert parse_money(goods.bids[0].signed_contract_price) == (None, None)  # multi-currency stays text
    assert goods.bids[1].rejection_reason == "Does not meet Eligibility Requirements"
    declaration = parse_world_bank_award_notice(FIXTURES["OP00463854"]["notice_text"])
    assert len(declaration.bids) == 1
    assert [m.name for m in declaration.bids[0].members] == ["PROGRESS SOLUTION TECHNOLOGIES", "UZINFOCOM"]
    assert declaration.bids[0].rejection_reason is None  # "Summary of Reason" is an ownership declaration
    # Ownership tables (personal data) are never read.
    assert not any("REDACTED" in line for line, _ in notice_lines(FIXTURES["OP00472568"]["notice_text"]))


def test_individual_consultant_and_missing_text() -> None:
    parsed = parse_world_bank_award_notice(FIXTURES["OP00410040"]["notice_text"])
    assert [(bid.status, bid.members[0].kind, bid.members[0].name, bid.members[0].source_id) for bid in parsed.bids] == [
        ("AWARDED", "INDIVIDUAL", "Individual Consultant", None)]
    assert parse_world_bank_award_notice(None).bids == []
    snapshot, rows = build_snapshot(FIXTURES["OP00431313"], retrieved_at=NOW)
    assert snapshot.parse_status == "NO_BIDDERS" and rows == [] and snapshot.raw_text is None


def test_money_and_name_normalization() -> None:
    assert parse_money("USD 2236567.27") == ("USD", Decimal("2236567.27"))
    assert parse_money("UZS") == ("UZS", None)
    assert parse_money("1,000") == (None, None)
    assert normalize_firm_name("PE KELAJAK-S") == normalize_firm_name("Kelajak S LLC") == "KELAJAK S"
    assert normalize_firm_name('"BUNYODKOR MUZAFFAR" LLC') == "BUNYODKOR MUZAFFAR"
    assert normalize_firm_name("Eptisa Servicios de Ingeniería, S.L.") == "EPTISA SERVICIOS DE INGENIERIA"


def test_snapshot_rows_carry_provenance() -> None:
    snapshot, rows = build_snapshot(FIXTURES["OP00472568"], retrieved_at=NOW)
    assert snapshot.lender == "WORLD_BANK" and snapshot.country == "Uzbekistan"
    assert snapshot.notice_url.endswith("/procurement-detail/OP00472568")
    assert snapshot.raw_text == FIXTURES["OP00472568"]["notice_text"]
    assert "notice_text" not in snapshot.raw_metadata
    assert len(rows) == 3 + 1 + 3 + 1
    assert {(row.bid_ordinal, row.member_ordinal, row.member_count) for row in rows if row.bid_ordinal == 1} == {
        (1, 1, 3), (1, 2, 3), (1, 3, 3)}
    assert all(row.content_hash == snapshot.content_hash and row.retrieved_at == NOW for row in rows)
    assert rows[0].evaluated_price_currency == "USD" and rows[0].evaluated_price_amount == Decimal("2236567.27")
    assert {row.bidder_kind for row in rows} == {"FIRM"}
    # Individual Consultant Selection: whoever the notice names is a person, never a firm.
    named = dict(FIXTURES["OP00472568"], procurement_method_name="Individual Consultant Selection")
    assert {row.bidder_kind for row in build_snapshot(named, retrieved_at=NOW)[1]} == {"INDIVIDUAL"}
    # A re-index that only touches api_modified_date is the same content.
    touched = dict(FIXTURES["OP00472568"], api_modified_date="2027-01-01T00:00:00Z")
    assert build_snapshot(touched, retrieved_at=NOW)[0].content_hash == snapshot.content_hash


# ---- storage, ingestion and reads ---------------------------------------------------------------------

def _row(notice_id: str, *, country: str, noticedate: str, group: str = "Consultant Services", text_html: str,
         sector: str | None = "Tourism") -> dict:
    row = {
        "id": notice_id, "notice_type": "Contract Award", "noticedate": noticedate, "notice_status": "Published",
        "project_ctry_name": country, "project_id": "P000001", "project_name": f"{country} Project",
        "bid_reference_no": f"REF-{notice_id}", "bid_description": f"Assignment {notice_id}",
        "procurement_group_desc": group, "procurement_method_name": "Quality And Cost-Based Selection",
        "notice_text": text_html,
    }
    if sector:
        row["sector"] = [{"sector_description": sector}]
    return row


def _html(*sections: tuple[str, list[tuple[list[tuple[str, str]], str, str | None]]]) -> str:
    """sections: (status word, [(members [(name (id), country)], price, reason)])."""
    parts = ["<div><h4>Contract Award</h4><p><b>Notice Version No:</b>0</p></div>",
             "<div><b>Date Notification of Award Issued</b><br/>(YYYY/MM/DD)<br/>2026/05/01<br/></div>"]
    for word, bids in sections:
        parts.append(f"<div><u><b>{word} Firm(s):</b></u></div>")
        for members, price, reason in bids:
            for name, country in members:
                parts.append(f"<div><b>{name}</b><br/>Country: {country}<br/></div>")
            parts.append(f"<div><b>Final Evaluation Price</b><br/>{price}<br/>")
            if word == "Awarded":
                parts.append(f"<b>Signed Contract Price</b><br/>{price}<br/>")
            if reason:
                parts.append(f"<b>Reason for Rejection</b><br/>{reason}")
            parts.append("</div>")
    return "".join(parts)


def _pages(rows: list[dict]):
    calls: list[dict] = []

    async def fetch(params: dict) -> dict:
        calls.append(dict(params))
        selected = [row for row in rows if row["project_ctry_name"] == params["project_ctry_name_exact"]]
        if params.get("procurement_group_exact") == "CS":
            selected = [row for row in selected if row["procurement_group_desc"] == "Consultant Services"]
        start = params["os"]
        return {"total": len(selected), "procnotices": selected[start:start + params["rows"]]}

    return fetch, calls


UZ_A = _row("UZ-1", country="Uzbekistan", noticedate="01-Sep-2026", text_html=_html(
    ("Awarded", [([("LOCAL CONSULT LLC (100)", "Uzbekistan"), ("GLOBAL ADVISORS LTD (200)", "United Kingdom")],
                  "USD 500000.00", None)]),
    ("Evaluated", [([("Global Advisors Limited (201)", "United Kingdom")], "USD 450000.00", None)]),
    ("Rejected", [([("THIRD FIRM (300)", "Turkey")], "USD", "Non-compliance")]),
))
UZ_B = _row("UZ-2", country="Uzbekistan", noticedate="01-Aug-2026", text_html=_html(
    ("Awarded", [([("LOCAL CONSULT (100)", "Uzbekistan")], "UZS 1000000.00", None)]),
), sector=None)
UZ_WORKS = _row("UZ-W", country="Uzbekistan", noticedate="02-Sep-2026", group="Works", text_html=_html(
    ("Awarded", [([("BUILDER LLC (400)", "Uzbekistan")], "UZS 9.00", None)]),
))
UZ_OLD = _row("UZ-OLD", country="Uzbekistan", noticedate="01-Jan-2024", text_html=_html(
    ("Awarded", [([("OLD FIRM (500)", "Uzbekistan")], "USD 1.00", None)]),
))
KZ_A = _row("KZ-1", country="Kazakhstan", noticedate="15-Jul-2026", text_html=_html(
    ("Awarded", [([("STEPPE ADVISORY (600)", "Kazakhstan")], "KZT 3000000.00", None)]),
))


def test_ledger_ingestion_storage_reads_and_exports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(award_ledger, "PAGE_ROWS", 2)

    async def scenario() -> None:
        database = support.database_name("s1_award_ledger")
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
            # Reversible: down past the ledger and up again.
            await asyncio.to_thread(support.alembic, database, "downgrade", PREVIOUS)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('award_outcomes')") is None
                assert await connection.fetchval("SELECT to_regclass('product_events')") is None
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _flow(sessions) -> None:
    rows = [UZ_WORKS, UZ_A, UZ_B, UZ_OLD, KZ_A]
    fetch, calls = _pages(rows)
    async with sessions() as db:
        report = await ingest_world_bank_awards(
            db, fetch=fetch, countries=("Uzbekistan", "Kazakhstan"), since=date(2024, 10, 10), now=NOW,
            request_delay_seconds=0,
        )
    # Consulting first, then the remaining groups; the old notice is outside the window.
    assert [call.get("procurement_group_exact") for call in calls if call["project_ctry_name_exact"] == "Uzbekistan"][0] == "CS"
    assert report.snapshots_created == 4 and report.notices_seen == 4
    assert report.rows_inserted == 4 + 1 + 1 + 1
    assert report.rows_by_country_status[("Uzbekistan", "REJECTED")] == 1
    assert not report.truncated_passes

    async with sessions() as db:
        again = await ingest_world_bank_awards(
            db, fetch=_pages(rows)[0], countries=("Uzbekistan", "Kazakhstan"), since=date(2024, 10, 10), now=NOW,
            request_delay_seconds=0,
        )
        assert (again.snapshots_created, again.snapshots_unchanged, again.rows_inserted) == (0, 4, 0)

        # A re-published notice with changed text is a new snapshot; reads use the newest.
        changed = dict(UZ_B, notice_text=UZ_B["notice_text"].replace("UZS 1000000.00", "UZS 2000000.00"))
        later = datetime(2026, 10, 11, tzinfo=timezone.utc)
        third = await ingest_world_bank_awards(
            db, fetch=_pages([UZ_WORKS, UZ_A, changed, KZ_A])[0], countries=("Uzbekistan",),
            since=date(2024, 10, 10), now=later, request_delay_seconds=0,
        )
        assert third.snapshots_created == 1
        assert await db.scalar(select(func.count()).select_from(AwardNoticeSnapshot)) == 5

        # Append-only.
        for statement in ("UPDATE award_outcomes SET status='AWARDED'", "DELETE FROM award_notice_snapshots"):
            with pytest.raises(Exception) as blocked:
                async with db.begin_nested():
                    await db.execute(text(statement))
            assert "award_ledger_immutable" in str(blocked.value)
        await db.rollback()

        summary = await ledger_summary(db)
        assert summary["notice_count"] == 4 and summary["stored_snapshot_count"] == 5
        uz = next(item for item in summary["countries"] if item["country"] == "Uzbekistan")
        assert uz["rows"] == {"AWARDED": 4, "EVALUATED": 1, "REJECTED": 1}

        items, total = await list_outcomes(db, filters=OutcomeFilters(country="Uzbekistan", status="REJECTED"))
        assert total == 1 and items[0].rejection_reason == "Non-compliance" and items[0].bidder_country == "Turkey"
        latest_b = (await list_outcomes(db, filters=OutcomeFilters(q="UZ-2")))[0]
        assert [row.evaluated_price_text for row in latest_b] == ["UZS 2000000.00"]
        exported = list(csv.DictReader(io.StringIO(await outcomes_csv(db, filters=OutcomeFilters()))))
        assert len(exported) == 7 and {row["notice_id"] for row in exported} == {"UZ-1", "UZ-2", "UZ-W", "KZ-1"}

        firms = {(row["normalized_name"], row["country"]): row for row in await firm_export(db)}
        local = firms[("LOCAL CONSULT", "Uzbekistan")]  # "LOCAL CONSULT LLC" and "LOCAL CONSULT" are one firm
        assert (local["participations"], local["awards"]) == (2, 2)
        assert local["world_bank_supplier_ids"] == "100"
        assert local["example_1_url"].endswith("/procurement-detail/UZ-1")
        global_ = firms[("GLOBAL ADVISORS", "United Kingdom")]  # two supplier ids, one normalized firm
        assert (global_["participations"], global_["awards"], global_["world_bank_supplier_ids"]) == (2, 1, "200; 201")
        content, count = await firm_export_csv(db)
        assert count == len(firms) and content.splitlines()[0].startswith("normalized_name,display_name,country")

        sizing = await market_sizing(db, today=date(2026, 10, 10))
        uz_stats = sizing["detail"]["Consultant Services"]["Uzbekistan"]
        assert uz_stats["notices"] == 2  # works and the old notice are out
        assert uz_stats["bids"] == 4
        assert uz_stats["firms"] == {"all": 3, "local": 1, "foreign": 2, "unknown": 0}
        assert uz_stats["bid_distribution"]["all"]["2"] == 2
        assert uz_stats["awards"] == 2
        assert uz_stats["awarded_value"] == {"USD": Decimal("500000.00"), "UZS": Decimal("2000000.00")}
        assert set(uz_stats["by_sector"]) == {"Tourism", "Unspecified"}
        assert sizing["detail"]["Consultant Services"]["Kazakhstan"]["firms"]["local"] == 1
        # S1-6: every category; the works notice is in the TAM view, not in consulting.
        assert sizing["detail"]["All categories"]["Uzbekistan"]["notices"] == 3
        assert sizing["detail"]["Works"]["Uzbekistan"]["firms"]["all"] == 1
        sizing_rows = list(csv.DictReader(io.StringIO(market_sizing_csv(sizing))))
        assert {"metric": "distinct_firms", "category": "Consultant Services", "country": "Uzbekistan", "segment": "foreign",
                "value": "2"}.items() <= next(
            row for row in sizing_rows if row["metric"] == "distinct_firms" and row["segment"] == "foreign"
            and row["country"] == "Uzbekistan" and row["sector"] == "All" and row["category"] == "Consultant Services").items()
        markdown = market_sizing_markdown(sizing, generated_at=NOW)
        consulting = markdown.split("## 2. Consulting (current segment)")[1].split("## 3. Works")[0]
        # columns: Uzbekistan, Kyrgyz Republic, Tajikistan, Kazakhstan, Central Asia (each firm once)
        assert "| Distinct firms (Central Asia: each firm once) | 3 | 0 | 0 | 1 | 4 |" in consulting
        assert "World Bank only" in markdown and "every figure is a floor" in markdown.lower()


def test_ledger_routes_are_operator_reads_and_admin_downloads() -> None:
    assert deps.require_operator in [dependency.dependency for dependency in endpoints.router.dependencies]
    admin_only = {"/firms.csv", "/market-sizing.csv", "/market-sizing.md"}
    for route in endpoints.router.routes:
        dependencies = {dependency.dependency for dependency in route.dependencies}
        assert (deps.require_admin in dependencies) == (route.path in admin_only), route.path
        assert route.methods == {"GET"}

    async def check() -> None:
        operator = User(email="op@example.org", name="Op", google_id="o", approval_status="approved",
                        platform_role="operator", is_admin=False)
        with pytest.raises(HTTPException) as denied:
            await deps.require_admin(current_user=operator)
        assert denied.value.status_code == 403

    asyncio.run(check())


def test_individual_consultants_are_never_named_in_views_or_exports() -> None:
    from app.services.award_ledger_reports import OUTCOME_CSV_COLUMNS, outcome_values

    named = dict(FIXTURES["OP00472568"], procurement_method_name="Individual Consultant Selection")
    rows = build_snapshot(named, retrieved_at=NOW)[1]
    values = outcome_values(rows[0], OUTCOME_CSV_COLUMNS)
    assert (values["bidder_name"], values["bidder_name_normalized"], values["bidder_source_id"]) == (
        "Individual consultant", None, None)
    assert values["status"] == "AWARDED" and values["evaluated_price_text"] == "USD 2236567.27"
    firm = outcome_values(build_snapshot(FIXTURES["OP00472568"], retrieved_at=NOW)[1][0], OUTCOME_CSV_COLUMNS)
    assert firm["bidder_name"] == "ARUP INTERNATIONAL PROJECTS LTD"
