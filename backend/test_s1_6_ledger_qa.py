"""S1-6: firm-name QA, all-category market sizing v2 (USD equivalents, flags) and the outreach targets."""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.award_ledger import ingest_world_bank_awards
from app.services.award_ledger_fx import FX_DATE, FX_SOURCE, to_usd
from app.services.award_ledger_parser import name_flag, non_firm_reason, normalize_firm_name
from app.services.award_ledger_reports import (
    award_value_flag,
    market_sizing,
    market_sizing_csv,
    market_sizing_markdown,
    merge_candidates,
    non_firm_review,
    outreach_summary_markdown,
    outreach_targets,
)
from scripts import test_s0_5b4_baseline as support
from test_s1_award_ledger import HEAD, NOW, _html, _pages, _row

TODAY = date(2026, 10, 10)


# ---- pure ------------------------------------------------------------------------------------------

def test_role_markers_are_stripped_only_in_role_positions() -> None:
    assert normalize_firm_name("GOPA CONSULTANTS, LEAD") == normalize_firm_name("GOPA Consultants") == "GOPA CONSULTANTS"
    assert normalize_firm_name("Dorsch International - Lead Partner") == "DORSCH INTERNATIONAL"
    assert normalize_firm_name("Egis International (Lead)") == "EGIS INTERNATIONAL"
    assert normalize_firm_name("Hydroproject JSC, member") == "HYDROPROJECT"
    assert normalize_firm_name("ERNST & YOUNG ADVISORY JV") == "ERNST YOUNG ADVISORY"
    assert normalize_firm_name("ABC LLC IN ASSOCIATION WITH XYZ") == "ABC XYZ"
    assert normalize_firm_name("THE CONSORTIUM OF ALPHA S.R.L. (LEAD) AND BETA LLC") == "ALPHA BETA"
    assert normalize_firm_name('CONSORTIUM OOO "BEST STROY 2020" AND OOO "JASUR IMKON FAYZ"') == "BEST STROY 2020 JASUR IMKON FAYZ"
    assert normalize_firm_name("JOINT VENTURE OF ALPHA AND BETA") == "ALPHA BETA"
    # firm names that contain the words keep them
    for name, expected in (("LEADER HORSE", "LEADER HORSE"), ("LLC LEADER MEDICAL", "LEADER MEDICAL"),
                           ("ANINVER DEVELOPMENT PARTNERS", "ANINVER DEVELOPMENT PARTNERS"),
                           ("PARTNER BUILDING 2020", "PARTNER BUILDING 2020"), ("LEAD CONSULTING GROUP", "LEAD CONSULTING GROUP"),
                           ("MEGA-LEADER", "MEGA LEADER")):
        assert normalize_firm_name(name) == expected, name


def test_non_firm_names_have_two_tiers() -> None:
    assert name_flag("IRRIGATION PROJECT") == ("PROJECT", "EXCLUDED")
    assert name_flag("Ministry of Agriculture") == ("MINISTRY", "EXCLUDED")
    assert name_flag("Project Implementation Unit") == ("IMPLEMENTATION UNIT", "EXCLUDED")
    assert name_flag("Kazakh PIU")[1] == "EXCLUDED"
    assert name_flag("State Committee for Ecology")[1] == "EXCLUDED"
    assert name_flag("CENTER FOR SCIENTIFIC INFORMATION UNDER THE AGENCY OF INNOVATIVE DEVELOPMENT")[1] == "EXCLUDED"
    # a brand name with PROJECT or AGENCY is reviewed, not excluded
    assert name_flag("SILK ROAD PROJECT") == ("PROJECT", "REVIEW") and non_firm_reason("SILK ROAD PROJECT") is None
    assert name_flag("Agency for Strategic Reforms") == ("AGENCY", "REVIEW")
    # a legal form makes it a firm
    for name in ("PROJECT MANAGEMENT GROUP LLC", "Smart Project L.L.C.",
                 'CLOSED JOINT STOCK COMPANY "AGENCY FOR STRATEGIC AND ECONOMIC DEVELOPMENT"', "GOPA CONSULTANTS"):
        assert name_flag(name) is None, name


def _award(**values) -> SimpleNamespace:
    base = dict(country="Uzbekistan", signed_contract_currency=None, signed_contract_amount=None,
                evaluated_price_currency=None, evaluated_price_amount=None)
    base.update(values)
    return SimpleNamespace(**base)


def test_usd_equivalents_and_value_flags() -> None:
    assert FX_DATE == "2026-10-09" and "Central Bank of the Republic of Uzbekistan" in FX_SOURCE
    assert to_usd("USD", Decimal("100")) == Decimal("100.00")
    assert to_usd("UZS", Decimal("11846.57")) == Decimal("1.00")
    assert to_usd("XXX", Decimal("1")) is None
    assert award_value_flag(_award(signed_contract_currency="USD", signed_contract_amount=Decimal("250000"))) is None
    assert award_value_flag(_award(signed_contract_currency="RUB", signed_contract_amount=Decimal("4464778"),
                                   country="Kyrgyz Republic")) is None  # a contractor currency
    assert "BDT" in award_value_flag(_award(signed_contract_currency="BDT", signed_contract_amount=Decimal("191779521")))
    assert "same amount" in award_value_flag(_award(
        signed_contract_currency="USD", signed_contract_amount=Decimal("9541788388"),
        evaluated_price_currency="UZS", evaluated_price_amount=Decimal("9541788388")))
    assert "implausibly small" in award_value_flag(_award(signed_contract_currency="UZS", signed_contract_amount=Decimal("65000")))


# ---- disposable database -------------------------------------------------------------------------

def _cqs(row: dict) -> dict:
    return dict(row, procurement_method_name="Consultant Qualification Selection")


ROWS = [
    # consulting, Uzbekistan: a JV whose lead is written with a role marker; a public-body name; a review-tier brand
    _row("C-1", country="Uzbekistan", noticedate="01-Sep-2026", text_html=_html(
        ("Awarded", [([("ALPHA CONSULT, LEAD (100)", "Uzbekistan"), ("BETA ADVISORY (200)", "Germany")], "USD 400000.00", None)]),
        ("Rejected", [([("IRRIGATION PROJECT (300)", "Uzbekistan")], "USD", "Non-compliance"),
                      ([("SILK ROAD PROJECT (310)", "Uzbekistan")], "USD", "Non Responsive")]),
    )),
    _cqs(_row("C-2", country="Uzbekistan", noticedate="01-Aug-2026", text_html=_html(
        ("Awarded", [([("ALPHA CONSULT LLC (100)", "Uzbekistan")], "UZS 1184657000.00", None)]),
    ))),
    # one contract published as two awarded entries with the same price: the value counts once
    _row("C-3", country="Tajikistan", noticedate="05-Aug-2026", text_html=_html(
        ("Awarded", [([("GAMMA NGO (400)", "Tajikistan")], "USD 150000.00", None),
                     ([("BETA ADVISORY GMBH (201)", "Germany")], "USD 150000.00", None)]),
        ("Evaluated", [([("DELTA (500)", "Tajikistan")], "USD 160000.00", None)]),
    )),
    # works, Uzbekistan: the consulting firm also bids works (two categories); a BDT entry error
    _row("W-1", country="Uzbekistan", noticedate="02-Sep-2026", group="Works", text_html=_html(
        ("Awarded", [([("BUILDER LLC (600)", "Uzbekistan")], "BDT 5000000.00", None)]),
        ("Rejected", [([("ALPHA CONSULT (100)", "Uzbekistan")], "USD", "Bid Security not Provided")]),
    )),
    # goods, Kyrgyz Republic: the same amount under two currencies
    _row("G-1", country="Kyrgyz Republic", noticedate="03-Sep-2026", group="Goods",
         text_html=_html(("Awarded", [([("SUPPLY CO (700)", "Kyrgyz Republic")], "USD 99972.86", None)])).replace(
             "<b>Signed Contract Price</b><br/>USD 99972.86", "<b>Signed Contract Price</b><br/>USD 99972.86").replace(
             "<b>Final Evaluation Price</b><br/>USD 99972.86", "<b>Final Evaluation Price</b><br/>KGS 99972.86")),
]
ICS = dict(_row("I-1", country="Uzbekistan", noticedate="04-Sep-2026", text_html=_html(
    ("Awarded", [([("JOHN SMITH (900)", "Uzbekistan")], "USD 20000.00", None)]),
)), procurement_method_name="Individual Consultant Selection")


def test_ledger_qa_sizing_and_targets() -> None:
    async def scenario() -> None:
        database = support.database_name("s1_6_ledger_qa")
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
    countries = ("Uzbekistan", "Kyrgyz Republic", "Tajikistan", "Kazakhstan")
    async with sessions() as db:
        report = await ingest_world_bank_awards(db, fetch=_pages([*ROWS, ICS])[0], countries=countries,
                                                since=date(2024, 10, 10), now=NOW, request_delay_seconds=0)
        assert report.snapshots_created == 6 and not report.truncated_passes
        again = await ingest_world_bank_awards(db, fetch=_pages([*ROWS, ICS])[0], countries=countries,
                                               since=date(2024, 10, 10), now=NOW, request_delay_seconds=0)
        assert (again.snapshots_created, again.rows_inserted) == (0, 0)

        # ---- name QA -----------------------------------------------------------------------------------
        review = {row["bidder_name"]: row for row in await non_firm_review(db)}
        assert review["IRRIGATION PROJECT"]["tier"] == "EXCLUDED" and review["IRRIGATION PROJECT"]["counted_as_firm"] == "no"
        assert review["SILK ROAD PROJECT"]["tier"] == "REVIEW" and review["SILK ROAD PROJECT"]["counted_as_firm"] == "yes"
        merges = await merge_candidates(db)
        # "BETA ADVISORY" (200) and "BETA ADVISORY GMBH" (201) normalize to one firm: no pair; nothing is merged here
        assert all(item["evidence"] in {"same World Bank supplier id", "similar name"} for item in merges)

        # ---- market sizing -----------------------------------------------------------------------------
        sizing = await market_sizing(db, today=TODAY)
        consulting = sizing["detail"]["Consultant Services"]
        uz = consulting["Uzbekistan"]
        # ALPHA CONSULT (", LEAD", "LLC", plain) is one firm; IRRIGATION PROJECT is out; SILK ROAD PROJECT is counted
        assert uz["firms"]["all"] == 3 and uz["bids"] == 3  # ALPHA, BETA (JV bid), SILK ROAD; the excluded bid is gone
        assert uz["bid_status"] == {"AWARDED": 2, "REJECTED": 1}
        assert uz["rejection_reasons"] == {"Non Responsive": 1}
        assert uz["awarded_value_usd"] == Decimal("500000.00")  # USD 400,000 + UZS 1,184,657,000 (= USD 100,000)
        assert uz["methods"]["Consultant Qualification Selection"]["distribution"]["1 firm"] == 1
        tj = consulting["Tajikistan"]
        assert tj["awards"] == 2 and tj["awarded_value_usd"] == Decimal("150000.00")  # one contract, value once
        region = consulting["Central Asia"]
        assert region["firms"]["all"] == 5  # BETA counted once across Uzbekistan and Tajikistan
        assert region["multi_country_firms"] == 1
        everything = sizing["detail"]["All categories"]
        assert everything["Central Asia"]["multi_category_firms"] == 1  # ALPHA CONSULT: consulting and works
        assert everything["Uzbekistan"]["rows_by_group"] == {"Consultant Services": 4, "Works": 2}  # excluded name and individual out
        works = sizing["detail"]["Works"]["Uzbekistan"]
        assert works["awarded_value"] == {"BDT": Decimal("5000000.00")} and works["awarded_value_usd"] == 0
        assert [item["reason"] for item in works["flagged_values"]] == ["currency BDT on a Uzbekistan notice"]
        goods = sizing["detail"]["Goods"]["Kyrgyz Republic"]
        assert "same amount" in goods["flagged_values"][0]["reason"] and goods["median_award_usd"] is None
        assert sizing["individual_consultant_awards"] == {"Uzbekistan": 1, "Central Asia": 1}
        assert consulting["Uzbekistan"]["median_award_usd"] == Decimal("250000")
        rows = list(csv.DictReader(io.StringIO(market_sizing_csv(sizing))))
        assert {row["category"] for row in rows} == {"All categories", "Consultant Services", "Works", "Goods",
                                                    "Non-consulting Services"}
        assert any(row["metric"] == "rejection_reason" and row["segment"] == "Bid Security not Provided" for row in rows)
        markdown = market_sizing_markdown(sizing)
        order = [markdown.index(title) for title in ("## 1. All categories (TAM view)", "## 2. Consulting (current segment)",
                                                     "## 3. Works", "## 4. Goods", "## 5. Non-consulting services")]
        assert order == sorted(order)
        assert "CQS note" in markdown.split("## 3. Works")[0] and "Asian Infrastructure Investment Bank" in markdown
        assert "Islamic Development Bank" in markdown and "## Median award value, USD equivalent" in markdown

        # ---- outreach targets --------------------------------------------------------------------------
        targets = await outreach_targets(db, today=TODAY)
        names = [item["normalized_name"] for item in targets]
        assert "IRRIGATION PROJECT" not in names and "JOHN SMITH" not in names  # excluded body, individual
        consulting_first = [item["consulting_target"] for item in targets]
        assert consulting_first == sorted(consulting_first, key=lambda value: value != "yes")
        alpha = next(item for item in targets if item["normalized_name"] == "ALPHA CONSULT")
        assert alpha["consulting_target"] == "yes" and alpha["bids"] == 3 and alpha["awards"] == 2
        assert alpha["procurement_groups_bid_in"] == "Consultant Services; Works"
        assert alpha["bids_by_group"] == "Consultant Services: 2; Works: 1"
        assert alpha["rejection_reasons"] == "Bid Security not Provided"
        assert "BETA ADVISORY (200)" not in alpha["jv_partners_seen"] and "BETA ADVISORY" in alpha["jv_partners_seen"]
        assert {"BUILDER", "SUPPLY"} <= set(names)  # works and goods firms with an award are on the list
        assert not any(key in item for item in targets for key in ("email", "phone", "contact"))
        summary = outreach_summary_markdown(targets, since=date(2024, 10, 10), until=TODAY)
        assert "Consulting targets:" in summary and "no contact data" in summary
