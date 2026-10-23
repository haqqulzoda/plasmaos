"""P2 partner finder: ranking rules first (pure), then the migration, then one Postgres scenario
(suggestions from the ledger, requests, the team queue, audit, isolation and team scenarios)."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import json
import random
import re
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException, Response
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.own_experience import terms
from app.services.partner_finder import (
    SOURCE_LABEL,
    AwardFact,
    GapFeatures,
    build_features,
    firm_key,
    gap_basis,
    is_person_or_agency,
    presence_requirement,
    rank_firms,
)

HEAD = "20261023_0001_p2_partner_finder"
P1_HEAD = "20261016_0002_p1_organization_access"
SUGGESTION_KEYS = {
    "rank", "firm_key", "firm_name", "firm_country", "presence", "presence_matches_gap", "match_strength",
    "in_procurement_category", "same_country", "matched_terms", "matched_sectors", "similar_award_count",
    "latest_award_year", "best_relevance", "awards", "source_label",
}
AWARD_KEYS = {
    "title", "project_name", "lender", "lender_label", "country", "year", "notice_id", "notice_url",
    "procurement_group", "joint_venture",
}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def _features(text: str, *, country: str | None = "Uzbekistan", presence: str = "ANY",
              group: str = "Consultant Services", sectors: tuple[str, ...] = ()) -> GapFeatures:
    words = {stem: stem for stem in terms(text)}
    return GapFeatures(
        category="PARTNER_FIRM", basis="EXPERIENCE", summary=text, keywords=tuple(sorted(words)),
        keyword_words=words, sectors=sectors, country=country, procurement_group=group, presence=presence,
    )


_counter = iter(range(1, 10**6))


def _award(name: str, title: str, *, country: str = "Uzbekistan", bidder_country: str | None = "Uzbekistan",
           group: str = "Consultant Services", year: int = 2025, lender: str = "WORLD_BANK", members: int = 1,
           notice: str | None = None, bid: int = 1, sectors: tuple[str, ...] = ()) -> AwardFact:
    notice = notice or f"OP{next(_counter):08d}"
    return AwardFact(
        lender=lender, notice_id=notice, notice_url=f"https://projects.worldbank.org/en/projects-operations/procurement-detail/{notice}",
        bid_ordinal=bid, country=country, project_name=f"{country} Project", package_title=title,
        procurement_group=group, award_date=date(year, 6, 1), notice_date=date(year, 6, 15), bidder_name=name,
        bidder_country=bidder_country, member_count=members, sectors=sectors,
    )


def _corpus() -> list[AwardFact]:
    """Background awards so word rarity (IDF) behaves like a real ledger."""
    filler = [
        _award(f"Filler Roads {index} LLC", f"Road rehabilitation design and supervision lot {index}", group="Works")
        for index in range(12)
    ] + [
        _award(f"Filler Schools {index} LLC", f"School construction supervision {index}") for index in range(8)
    ]
    return filler


def _names(result) -> list[str]:
    return [item["firm_name"] for item in result]


# ---- pure ranking rules --------------------------------------------------------------------------

def test_ranking_is_deterministic_for_any_input_order() -> None:
    features = _features("Insurance claims management and actuarial review for the state insurer")
    awards = _corpus() + [
        _award("Alpha Actuarial LLC", "Actuarial review of insurance claims reserves", year=2024),
        _award("Beta Insurance Advisory", "Insurance claims process audit", year=2025),
        _award("Gamma Consult", "Insurance claims process audit", year=2025),  # tie with Beta but for the name
        _award("Delta Partners", "Claims management system design", bidder_country="Turkiye"),
        _award("Epsilon LLC", "Water supply design"),  # nothing in common with the gap
    ]
    first = rank_firms(features, awards)
    for seed in range(5):
        shuffled = list(awards)
        random.Random(seed).shuffle(shuffled)
        assert json.dumps(rank_firms(features, shuffled), sort_keys=True) == json.dumps(first, sort_keys=True)
    assert "Epsilon LLC" not in _names(first)
    beta, gamma = (_names(first).index(name) for name in ("Beta Insurance Advisory", "Gamma Consult"))
    assert beta + 1 == gamma  # identical evidence: the name breaks the tie
    assert [item["rank"] for item in first] == list(range(1, len(first) + 1))
    assert all(item["source_label"] == SOURCE_LABEL == "From public award records, unverified" for item in first)


def test_public_bodies_projects_and_the_own_firm_are_never_suggested() -> None:
    features = _features("Hydrological monitoring network design")
    awards = _corpus() + [
        _award("Ministry of Water Resources", "Hydrological monitoring network design"),
        _award("PIU of the Irrigation Project", "Hydrological monitoring network design"),
        _award("Irrigation Project", "Hydrological monitoring network design"),
        _award("Silk Road Project", "Hydrological monitoring network design"),  # REVIEW tier: left out too
        _award("Hydro Monitoring LLC", "Hydrological monitoring network design"),
        _award("Our Own Firm LLC", "Hydrological monitoring network design"),
        _award("Rival Hydro GmbH", "Hydrological monitoring stations", bidder_country="Germany"),
    ]
    result = rank_firms(features, awards, exclude_names=["OUR OWN FIRM, LLC"])
    assert _names(result) == ["Hydro Monitoring LLC", "Rival Hydro GmbH"]


def test_activity_words_alone_are_not_a_similar_award_and_rarity_weighs() -> None:
    features = _features("Design and supervision of irrigation pumping stations")
    awards = _corpus() + [
        _award("Generic Design LLC", "Design and supervision of school buildings"),  # activity words only
        _award("Pump Engineering LLC", "Pumping stations rehabilitation design"),
        _award("Canal Works LLC", "Irrigation canal design"),
    ]
    result = rank_firms(features, awards)
    assert "Generic Design LLC" not in _names(result)
    pump = next(item for item in result if item["firm_name"] == "Pump Engineering LLC")
    assert pump["match_strength"] == "STRONG" and {"pumping", "station"} <= set(pump["matched_terms"])
    assert _names(result)[0] == "Pump Engineering LLC"


def test_people_and_intergovernmental_bodies_are_never_suggested() -> None:
    # Names seen as FIRM rows on non-ICS notices in the ledger (2026-10-23 preview database).
    for name, title in (
        ("TAYLAKOVA J.K.", "Author supervision for the rehabilitation of indoor sanitary facilities"),
        ("KARIMOVA MALIKA T.", "Author supervision"),
        ("NARGIS MUKHTAROVA", "Procurement Specialist"),
        ("John Smith", "Financial Management Specialist"),
        ("UNITED NATIONS CHILDREN'S FUND (UNICEF)", "Adaptive social protection strategy"),
        ("CAZACU ANGELA", "Two Project Assistants to support National Agency for Curriculum"),
        ("ROSU ALINA-DIANA", "Lead TEACH Ro consultant for training in the application of TEACH"),
    ):
        assert is_person_or_agency(name, title), name
    for name, title in (
        ("ERNST & YOUNG ADVISORY JV", "ESG diagnostics"), ("PKF MAK ALYANS LLC", "Financial audit"),
        ("KRESTON TASHKENT", "Audit of the project financial statements"), ("SMART ECO", "Safeguards support"),
        ("PO PESHSAF", "Disaster risk management training"), ("CENTER FOR PROGRESSIVE REFORMS NGO", "Social protection"),
        ("A.B.C. CONSULTING", "Design review"),
    ):
        assert not is_person_or_agency(name, title), name
    features = _features("Social protection supervision system")
    awards = _corpus() + [
        _award("KARIMOVA MALIKA T.", "Social protection supervision"),
        _award("Social Systems LLC", "Social protection supervision system"),
    ]
    assert _names(rank_firms(features, awards)) == ["Social Systems LLC"]


def test_an_award_from_another_sector_needs_specific_words_and_is_never_strong() -> None:
    features = _features("Supervision of continuous professional development for social workers",
                         sectors=("Social Protection",))
    awards = _corpus() + [
        _award("Water Supervision LLC", "Supervision of water supply for social institutions",
               sectors=("Water Supply",)),  # off-sector, no rare word in common
        _award("Social Work LLC", "Professional development for social workers", sectors=("Social Protection",)),
        _award("Workers Training LLC", "Training of social workers mentors", sectors=("Health",)),
    ]
    result = rank_firms(features, awards)
    assert _names(result) == ["Social Work LLC", "Workers Training LLC"]
    assert [item["match_strength"] for item in result] == ["STRONG", "MODERATE"]


def test_a_longer_award_word_ending_with_a_gap_word_matches() -> None:
    features = _features("Insurance claims management", sectors=("Financial Sector",))
    awards = _corpus() + [
        _award("Reinsurance Advisers LLC", "Development of the reinsurance program", sectors=("Financial Sector",)),
        _award("Generic Programs LLC", "Development of the training program", sectors=("Financial Sector",)),
    ]
    assert _names(rank_firms(features, awards)) == ["Reinsurance Advisers LLC"]


def test_one_shared_word_counts_only_when_it_is_rare_in_the_ledger() -> None:
    features = _features("Financial statements audit under ISA for the hydropower company")
    common = [_award(f"Finance {index} LLC", f"Financial management improvement {index}") for index in range(40)]
    awards = _corpus() + common + [
        _award("Hydro Audit LLC", "Hydropower plant performance review"),  # one rare word: similar
        _award("Statements Audit LLC", "Audit of financial statements"),  # two domain words: similar
    ]
    names = _names(rank_firms(features, awards, limit=50))
    assert names[:2] == ["Statements Audit LLC", "Hydro Audit LLC"]
    assert not any(name.startswith("Finance ") for name in names)  # "financial" alone is in every tenth award


def test_order_presence_then_consulting_then_strength_then_country_then_recency_then_count() -> None:
    text = "Tariff methodology and regulatory accounting for the electricity regulator"
    awards = _corpus() + [
        _award("Foreign Tariff GmbH", "Electricity tariff methodology", bidder_country="Germany", year=2025),
        _award("Local Tariff LLC", "Electricity tariff methodology", year=2023),
        _award("Works Tariff LLC", "Electricity tariff methodology metering works", group="Works", year=2026),
        _award("Kazakh Tariff LLP", "Electricity tariff methodology", country="Kazakhstan",
               bidder_country="Kazakhstan", year=2026),
        _award("Weak Match LLC", "Regulatory reporting templates", year=2026),
    ]
    # Local presence required: local firms first, whatever else they have.
    local = rank_firms(_features(text, presence="LOCAL"), awards)
    assert [item["presence"] for item in local[:3]] == ["LOCAL"] * 3
    assert _names(local)[:3] == ["Local Tariff LLC", "Weak Match LLC", "Works Tariff LLC"]
    assert _names(local)[3:] == ["Foreign Tariff GmbH", "Kazakh Tariff LLP"]
    # No presence rule: consulting before works, strong before moderate, the gap's country before others.
    neutral = rank_firms(_features(text), awards)
    assert _names(neutral) == [
        "Foreign Tariff GmbH", "Local Tariff LLC", "Kazakh Tariff LLP", "Weak Match LLC", "Works Tariff LLC",
    ]
    assert neutral[0]["latest_award_year"] == 2025 and neutral[0]["same_country"]
    assert not neutral[2]["same_country"] and neutral[-1]["in_procurement_category"] is False
    # A foreign partner wanted: foreign firms first.
    foreign = rank_firms(_features(text, presence="FOREIGN"), awards)
    assert _names(foreign)[:2] == ["Foreign Tariff GmbH", "Kazakh Tariff LLP"]
    # More similar awards win among otherwise equal firms (same relevance, same latest year).
    more = awards + [_award("Local Tariff LLC", "Electricity tariff methodology", year=2025)]
    assert _names(rank_firms(_features(text), more))[:2] == ["Local Tariff LLC", "Foreign Tariff GmbH"]


def test_joint_venture_awards_count_for_each_member_and_at_most_ten_firms() -> None:
    features = _features("Groundwater modelling")
    awards = _corpus() + [
        _award("JV Lead LLC", "Groundwater modelling study", members=2, notice="OP00999001"),
        _award("JV Partner GmbH", "Groundwater modelling study", members=2, notice="OP00999001",
               bidder_country="Germany"),
    ] + [_award(f"Modeller {index:02d} LLC", "Groundwater modelling") for index in range(15)]
    result = rank_firms(features, awards)
    assert len(result) == 10
    everything = rank_firms(features, awards, limit=50)
    jv = [item for item in everything if item["firm_name"] in {"JV Lead LLC", "JV Partner GmbH"}]
    assert len(jv) == 2 and all(item["awards"][0]["joint_venture"] for item in jv)


def test_suggestions_carry_public_notice_fields_only() -> None:
    features = _features("Energy audit of public buildings")
    awards = _corpus() + [_award("Audit Energy LLC", "Energy audit of hospitals", sectors=("Energy Efficiency",))]
    result = rank_firms(replace(features, sectors=("Energy Efficiency",)), awards)
    assert result and set(result[0]) == SUGGESTION_KEYS
    assert set(result[0]["awards"][0]) == AWARD_KEYS
    assert result[0]["matched_sectors"] == ["Energy Efficiency"]
    assert not EMAIL.search(json.dumps(result))
    assert result[0]["awards"][0]["notice_url"].startswith("https://projects.worldbank.org/")
    assert firm_key("Audit Energy, LLC", "Uzbekistan") == firm_key("AUDIT ENERGY LLC", "uzbekistan")


def test_presence_and_gap_basis_rules() -> None:
    assert presence_requirement("The consultant shall have a local presence in Uzbekistan") == "LOCAL"
    assert presence_requirement("Наличие местного офиса в Ташкенте") == "LOCAL"
    assert presence_requirement("International experience in at least two countries") == "FOREIGN"
    assert presence_requirement("At least 3 similar assignments") == "ANY"

    def gap(**values):
        base = dict(effective_coverage_state="GAP", effective_resolution_category="COMPANY_EVIDENCE")
        return SimpleNamespace(**{**base, **values})

    def requirement(text, category="EXPERIENCE", requirement_type="EXPERIENCE"):
        return SimpleNamespace(effective_normalized_requirement=text, original_quote=text, category=category,
                               requirement_type=requirement_type)

    experience = requirement("At least 3 similar assignments in insurance claims management in the last 5 years")
    assert gap_basis(gap(), experience, None) == "EXPERIENCE"
    assert gap_basis(gap(effective_resolution_category="PARTNER_FIRM"), experience, None) == "PARTNER_FIRM_RULE"
    assert gap_basis(gap(), requirement("The firm must have local presence in Uzbekistan", "LEGAL", "PRESENCE"), None) == "LOCAL_PRESENCE"
    assert gap_basis(gap(), requirement("Valid tax certificate", "LEGAL", "CERTIFICATION"), None) is None
    assert gap_basis(gap(effective_coverage_state="SUPPORTED"), experience, None) is None
    assert gap_basis(gap(effective_coverage_state="LATER_STAGE_OBLIGATION"), experience, None) is None
    assert gap_basis(gap(effective_resolution_category="EXPERT"), None, SimpleNamespace()) == "EXPERT"


def test_features_use_the_assignment_title_sectors_and_category_and_drop_country_words() -> None:
    tender = SimpleNamespace(
        title="Consulting services: Strengthening the management of insurance claims", country="Kyrgyz Republic",
        sector=None, procurement_category="Consultant Services", project_id="P000001",
        source_metadata_json={"sector": [{"sector_description": "Social Protection"}]},
    )
    gap = SimpleNamespace(missing_contribution="At least two similar assignments in the Kyrgyz Republic")
    requirement = SimpleNamespace(
        effective_normalized_requirement="At least two similar assignments in the Kyrgyz Republic",
        original_quote="at least two (2) similar assignments in the Kyrgyz Republic",
    )
    features = build_features(gap=gap, requirement=requirement, position=None, basis="EXPERIENCE", tender=tender,
                              project_sectors=["Public Administration - Social Protection"])
    assert {"insurance", "claim"} <= set(features.keywords)
    assert not {"kyrgyz", "republic", "consulting", "strengthening"} & set(features.keywords)
    assert features.sectors == ("Public Administration - Social Protection", "Social Protection")
    assert (features.country, features.procurement_group, features.presence) == (
        "Kyrgyz Republic", "Consultant Services", "ANY")


# ---- migration ------------------------------------------------------------------------------------

def test_p2_migration_is_additive_reversible_and_drift_free() -> None:
    from scripts import test_s0_5b4_baseline as support

    tables = ("partner_requests", "partner_request_events", "team_scenario_prospective_members")

    async def scenario() -> None:
        database = support.database_name("p2_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", P1_HEAD)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT version_num FROM alembic_version") == HEAD
                for table in tables:
                    assert await connection.fetchval("SELECT to_regclass($1)", table), table
                for index in ("uq_partner_request_gap_firm", "uq_partner_request_gap_sourcing", "uq_prospective_member_active"):
                    assert await connection.fetchval("SELECT to_regclass($1)", index), index
                kinds = await connection.fetchval(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_admin_alert_kind'")
                assert "PARTNER_REQUEST" in kinds
                # No column anywhere in the new tables can hold contact data for the suggested firm.
                columns = {row["column_name"] for row in await connection.fetch(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = ANY($1::text[])", list(tables))}
                assert not {name for name in columns if re.search(r"mail|phone|contact|address|website", name)}
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", P1_HEAD)
            connection = await support.database_connection(database)
            try:
                for table in tables:
                    assert await connection.fetchval("SELECT to_regclass($1)", table) is None, table
                kinds = await connection.fetchval(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_admin_alert_kind'")
                assert "PARTNER_REQUEST" not in kinds
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


# ---- Postgres scenario ----------------------------------------------------------------------------

CONTACT_TEXT = "Contact: Mr. Aliyev, E-mail: info@claims-advisory.uz, Tel: +998 71 200 00 00, 12 Amir Temur street"
TENDER_TITLE = "Consulting services for insurance claims management"
LINES = (
    "At least two similar assignments in insurance claims management completed in the last 5 years.",
    "The consultant shall have a local presence (registered office) in Uzbekistan.",
    "A valid tax registration certificate.",
    "Key expert: Actuarial expert with 10 years of experience in insurance claims actuarial analysis.",
)


def test_postgres_suggestions_requests_queue_isolation_and_scenarios(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import test_s0_5b4_baseline as support
    from test_w2_organization_pursuit_foundation import W1_HEAD, _seed_w1

    async def scenario() -> None:
        database = support.database_name("p2_partner_finder")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                organization_a = await connection.fetchval(
                    "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"])
                organization_b = await connection.fetchval(
                    "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_b"])
                owner_a = await connection.fetchval(
                    "SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", organization_a, ids["user_a"])
                await connection.execute(
                    "UPDATE tenders SET title=$2, country='Uzbekistan', procurement_category='Consultant Services' "
                    "WHERE id=$1", ids["tender"], TENDER_TITLE)
                ids["operator"] = uuid4()
                await connection.execute(
                    "INSERT INTO users(id,google_id,email,name,subscription_tier,is_admin,approval_status,platform_role,"
                    "auth_version) VALUES ($1,$2,'ops@plasma.invalid','Plasma Ops','SCOUT',true,'approved','admin',0)",
                    ids["operator"], f"p2-ops-{ids['operator']}")
            finally:
                await connection.close()

            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                await _seed_ledger(sessions)
                pursuit_id, run_id = await _analysis(sessions, ids, organization_a, owner_a, monkeypatch)
                await _suggestions(sessions, ids, organization_a, organization_b, pursuit_id, run_id)
                requests = await _requests(sessions, ids, organization_a, organization_b, pursuit_id, run_id, monkeypatch)
                await _queue(sessions, ids, organization_a, pursuit_id, requests)
                await _scenarios(sessions, ids, organization_a, organization_b, owner_a, pursuit_id, requests)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _seed_ledger(sessions) -> None:
    from app.models.award_ledger import AwardNoticeSnapshot, AwardOutcome

    now = datetime.now(timezone.utc)
    notices = [
        # (notice, title, group, method, project, year, [(name, bidder country, kind, status, bid)])
        ("OP09000001", "Insurance claims management advisory", "Consultant Services",
         "Quality And Cost-Based Selection", "P-W2-FOUNDATION", 2025,
         [("Claims Advisory LLC", "Uzbekistan", "FIRM", "AWARDED", 1),
          ("Loser Claims LLC", "Uzbekistan", "FIRM", "REJECTED", 2)]),
        ("OP09000002", "Actuarial review of insurance claims", "Consultant Services",
         "Consultant Qualification Selection", "P-W2-FOUNDATION", 2024,
         [("Global Actuaries GmbH", "Germany", "FIRM", "AWARDED", 1)]),
        ("OP09000003", "Insurance claims audit", "Consultant Services",
         "Consultant Qualification Selection", "P-W2-FOUNDATION", 2025,
         [("Ministry of Finance", "Uzbekistan", "FIRM", "AWARDED", 1)]),
        ("OP09000004", "Insurance claims trainer", "Consultant Services",
         "Individual Consultant Selection", "P-W2-FOUNDATION", 2025,
         [("Individual Consultant", "Uzbekistan", "INDIVIDUAL", "AWARDED", 1),
          ("Jane Claims Expert", "Uzbekistan", "FIRM", "AWARDED", 2)]),  # ICS: an individual whatever the kind says
        ("OP09000005", "Insurance claims data system", "Consultant Services",
         "Quality And Cost-Based Selection", "P-W2-FOUNDATION", 2025,
         [("Same Name Company LLC", "Uzbekistan", "FIRM", "AWARDED", 1)]),
        ("OP09000006", "Rural road rehabilitation", "Works", "Request for Bids", "P-OTHER", 2025,
         [("Roads LLC", "Uzbekistan", "FIRM", "AWARDED", 1)]),
    ]
    async with sessions() as db:
        for notice, title, group, method, project, year, bidders in notices:
            snapshot = AwardNoticeSnapshot(
                id=uuid4(), lender="WORLD_BANK", notice_id=notice,
                notice_url=f"https://projects.worldbank.org/en/projects-operations/procurement-detail/{notice}",
                notice_type="Contract Award", notice_date=date(year, 6, 1), award_date=date(year, 5, 20),
                country="Uzbekistan", project_id=project, project_name="Financial Sector Development Project",
                package_title=title, procurement_group=group, procurement_method=method,
                sectors=["Financial Sector"] if project == "P-W2-FOUNDATION" else ["Rural and Inter-Urban Roads"],
                raw_text=f"<p>{title}</p><p>{CONTACT_TEXT}</p>",
                raw_metadata={"contact_email": "info@claims-advisory.uz", "contact_phone": "+998 71 200 00 00"},
                content_hash=hashlib.sha256(notice.encode()).hexdigest(), parser_version="wb-award-v1",
                parse_status="PARSED", bidder_row_count=len(bidders), retrieved_at=now,
            )
            db.add(snapshot)
            await db.flush()
            for name, country, kind, status, bid in bidders:
                db.add(AwardOutcome(
                    snapshot_id=snapshot.id, lender="WORLD_BANK", country="Uzbekistan", project_id=project,
                    project_name=snapshot.project_name, notice_id=notice, notice_url=snapshot.notice_url,
                    notice_date=snapshot.notice_date, award_date=snapshot.award_date, package_title=title,
                    procurement_group=group, procurement_method=method, bid_ordinal=bid, member_ordinal=1,
                    member_count=1, bidder_name=name, bidder_name_normalized=name.upper(), bidder_country=country,
                    bidder_kind=kind, status=status, scores={}, content_hash=snapshot.content_hash,
                    parser_version="wb-award-v1", retrieved_at=now,
                ))
        await db.commit()


async def _analysis(sessions, ids, organization_a, owner_a, monkeypatch):
    from app.core.agents.pursuit_analyzer import ExtractedFact, PositionDetails, VerifiedFact
    from app.models.all_models import TenderDocument
    from app.models.base import TenderEngagementOrigin, TenderEngagementStatus
    from app.schemas.tenancy import PursuitAnalysisStartRequest
    from app.services import pursuit_analysis as analysis_service
    from app.services.private_documents import build_analysis_pack_candidate
    from app.services.pursuits import get_or_create_source_pursuit

    issued = "\n".join(LINES)
    async with sessions() as db:
        source = await get_or_create_source_pursuit(
            db, organization_id=organization_a, actor_user_id=ids["user_a"], actor_membership_id=owner_a,
            tender_id=ids["tender"], stage=TenderEngagementStatus.SAVED,
            legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
        )
        document = TenderDocument(
            tender_id=ids["tender"], file_url="p2-reoi.pdf", file_type="pdf",
            source_document_url="https://example.invalid/p2-reoi.pdf", source_document_type="REOI",
            sha256=hashlib.sha256(issued.encode()).hexdigest(), parsed_text=issued,
        )
        db.add(document)
        await db.commit()
        candidate = await build_analysis_pack_candidate(db, organization_id=organization_a, pursuit_id=source.pursuit.id)
        started = await analysis_service.create_analysis_run(
            db, organization_id=organization_a, pursuit_id=source.pursuit.id, membership_id=owner_a,
            request=PursuitAnalysisStartRequest(
                candidate_sha256=candidate.candidate_sha256, analysis_language="en", source_document_ids=[document.id],
            ),
        )

    def fact(line: str, **values) -> ExtractedFact:
        base = dict(kind="CORPORATE_REQUIREMENT", original_quote=line, normalized_text=line, category="EXPERIENCE",
                    requirement_type="SIMILAR_ASSIGNMENTS", stage_scope="EXPRESSION_OF_INTEREST",
                    distinction="MANDATORY")
        base.update(values)
        return ExtractedFact(**base)

    async def extracted(sealed, language):
        item = sealed[0]

        def verified(value: ExtractedFact) -> VerifiedFact:
            start = issued.index(value.original_quote)
            return VerifiedFact(item.pack_item_id, value, start, start + len(value.original_quote), 1, 1)

        return [
            verified(fact(LINES[0])),
            verified(fact(LINES[1], category="LEGAL", requirement_type="LOCAL_PRESENCE")),
            verified(fact(LINES[2], category="LEGAL", requirement_type="CERTIFICATION")),
            verified(fact(LINES[3], kind="POSITION", normalized_text="Actuarial expert", category="PERSONNEL",
                          requirement_type="KEY_EXPERT", position=PositionDetails(
                              title="Actuarial expert",
                              specific_experience="10 years of experience in insurance claims actuarial analysis"))),
        ]

    monkeypatch.setattr(analysis_service.pursuit_analyzer, "analyze_pack_items", extracted)
    async with sessions() as db:
        await analysis_service.process_analysis_run(db, started.analysis_run_id, worker_id="p2-worker")
    return source.pursuit.id, started.analysis_run_id


def _assert_public_only(payload, *, requester_email: str | None = None) -> None:
    """No contact data of a suggested firm; the only e-mail allowed is the requester's own (team alert)."""
    dumped = json.dumps(payload, default=str)
    for secret in ("info@claims-advisory.uz", "+998 71 200", "Amir Temur", "Aliyev"):
        assert secret not in dumped, secret
    assert {match for match in EMAIL.findall(dumped)} <= ({requester_email} if requester_email else set())


async def _suggestions(sessions, ids, organization_a, organization_b, pursuit_id, run_id) -> None:
    from app.api.endpoints import partner_finder as endpoints
    from app.models.user import User
    from app.schemas.candidate_retrieval import CVVersionCreateRequest, ExpertCreateRequest
    from app.services.candidate_retrieval import create_cv_version, create_expert

    async with sessions() as db:
        user_a, user_b = await db.get(User, ids["user_a"]), await db.get(User, ids["user_b"])
        overview = await endpoints.partner_gaps(
            pursuit_id=pursuit_id, x_organization_id=organization_a, current_user=user_a, db=db)
        assert overview.analysis_run_id == run_id
        by_basis = {gap.features.basis: gap for gap in overview.gaps}
        assert set(by_basis) == {"EXPERIENCE", "LOCAL_PRESENCE", "EXPERT"}  # never the tax certificate
        assert by_basis["LOCAL_PRESENCE"].features.presence == "LOCAL"
        assert by_basis["EXPERIENCE"].features.sectors == ["Financial Sector"]
        assert {"insurance", "claims"} <= set(by_basis["EXPERIENCE"].features.keywords)

        experience = await endpoints.partner_suggestions(
            pursuit_id=pursuit_id, analysis_run_id=run_id, gap_id=by_basis["EXPERIENCE"].gap_id,
            x_organization_id=organization_a, current_user=user_a, db=db)
        names = [item.firm_name for item in experience.suggestions]
        # Awards only; no public body, no individual consultant, not the organization's own firm,
        # not the rejected bidder, not the works contractor.
        assert names == ["Claims Advisory LLC", "Global Actuaries GmbH"]
        assert experience.jv_rule_check and experience.source_label == SOURCE_LABEL
        first = experience.suggestions[0]
        assert (first.presence, first.same_country, first.match_strength) == ("LOCAL", True, "STRONG")
        assert first.awards[0].notice_url.endswith("OP09000001") and first.awards[0].year == 2025
        assert first.matched_sectors == ["Financial Sector"]
        _assert_public_only(experience.model_dump())
        again = await endpoints.partner_suggestions(
            pursuit_id=pursuit_id, analysis_run_id=run_id, gap_id=by_basis["EXPERIENCE"].gap_id,
            x_organization_id=organization_a, current_user=user_a, db=db)
        assert again.model_dump() == experience.model_dump()  # deterministic, passive

        local = await endpoints.partner_suggestions(
            pursuit_id=pursuit_id, analysis_run_id=run_id, gap_id=by_basis["LOCAL_PRESENCE"].gap_id,
            x_organization_id=organization_a, current_user=user_a, db=db)
        assert [item.presence for item in local.suggestions] == ["LOCAL", "FOREIGN"]
        assert local.suggestions[1].presence_matches_gap is False

        with pytest.raises(HTTPException) as expert_firms:
            await endpoints.partner_suggestions(
                pursuit_id=pursuit_id, analysis_run_id=run_id, gap_id=by_basis["EXPERT"].gap_id,
                x_organization_id=organization_a, current_user=user_a, db=db)
        assert expert_firms.value.status_code == 409

        # Organization B can neither read A's pursuit through its own context nor name A's context.
        for organization in (organization_b, organization_a):
            with pytest.raises(HTTPException) as isolated:
                await endpoints.partner_suggestions(
                    pursuit_id=pursuit_id, analysis_run_id=run_id, gap_id=by_basis["EXPERIENCE"].gap_id,
                    x_organization_id=organization, current_user=user_b, db=db)
            assert isolated.value.status_code == 404

        # Expert Gap: the organization's library and the shared network, never another organization's library.
        private = await create_expert(db, organization_id=organization_a, actor_user_id=ids["user_a"], operator=False,
                                      payload=ExpertCreateRequest(
                                          scope="ORGANIZATION_PRIVATE", display_name="Aziza Karimova",
                                          specializations=["Actuarial analysis", "Insurance claims"],
                                          consent_state="NOT_REQUIRED_PRIVATE", evidence_state="REVIEWED"))
        await create_cv_version(db, organization_id=organization_a, expert_id=private.expert_id, actor_user_id=ids["user_a"],
                                operator=False, payload=CVVersionCreateRequest(
                                    assignments=[{"title": "Actuarial review of insurance claims reserves"}],
                                    evidence_state="REVIEWED"))
        await create_expert(db, organization_id=organization_a, actor_user_id=ids["operator"], operator=True,
                            payload=ExpertCreateRequest(
                                scope="NETWORK_SHARED", display_name="Network Actuary",
                                specializations=["Actuarial analysis"], consent_state="EXPLICIT_CONSENT",
                                network_permission_basis="Signed network consent 2026-10", evidence_state="UNVERIFIED"))
        await create_expert(db, organization_id=organization_b, actor_user_id=ids["user_b"], operator=False,
                            payload=ExpertCreateRequest(
                                scope="ORGANIZATION_PRIVATE", display_name="Other Org Actuary",
                                specializations=["Actuarial analysis"], consent_state="NOT_REQUIRED_PRIVATE",
                                evidence_state="REVIEWED"))
        experts = await endpoints.expert_suggestions(
            pursuit_id=pursuit_id, analysis_run_id=run_id, gap_id=by_basis["EXPERT"].gap_id,
            x_organization_id=organization_a, current_user=user_a, db=db)
        assert {(item.display_name, item.scope) for item in experts.experts} == {
            ("Aziza Karimova", "ORGANIZATION_PRIVATE"), ("Network Actuary", "NETWORK_SHARED")}
        assert experts.experts[0].display_name == "Aziza Karimova" and experts.sourcing_request is None


async def _requests(sessions, ids, organization_a, organization_b, pursuit_id, run_id, monkeypatch):
    from app.api.endpoints import partner_finder as endpoints
    from app.models.admin_alerts import AdminAlert
    from app.models.all_models import AdminActivityEvent
    from app.models.email import EmailDelivery
    from app.models.partner_finder import PartnerRequest
    from app.models.user import User
    from app.schemas.partner_finder import PartnerRequestCreate
    from app.services.admin_alerts import render_alert

    kicks: list[int] = []
    monkeypatch.setattr(endpoints, "kick_admin_alerts", lambda: kicks.append(1))
    async with sessions() as db:
        user_a, user_b = await db.get(User, ids["user_a"]), await db.get(User, ids["user_b"])
        overview = await endpoints.partner_gaps(
            pursuit_id=pursuit_id, x_organization_id=organization_a, current_user=user_a, db=db)
        gaps = {gap.features.basis: gap.gap_id for gap in overview.gaps}
        suggestions = await endpoints.partner_suggestions(
            pursuit_id=pursuit_id, analysis_run_id=run_id, gap_id=gaps["EXPERIENCE"],
            x_organization_id=organization_a, current_user=user_a, db=db)
        claims, actuaries = suggestions.suggestions[0], suggestions.suggestions[1]
        emails_before = await db.scalar(select(func.count(EmailDelivery.id)))

        response = Response()
        created = await endpoints.request_introduction(
            pursuit_id=pursuit_id, response=response, payload=PartnerRequestCreate(
                analysis_run_id=run_id, gap_id=gaps["EXPERIENCE"], kind="INTRODUCTION", firm_key=claims.firm_key,
                note="We lead; we need their insurance claims references."),
            x_organization_id=organization_a, current_user=user_a, db=db)
        assert response.status_code == 201 and created.status == "REQUESTED" and kicks == [1]
        assert created.firm_name == "Claims Advisory LLC" and created.awards and created.source_label == SOURCE_LABEL
        assert [event.to_status for event in created.history] == ["REQUESTED"]
        _assert_public_only(created.model_dump())

        repeat = Response()
        again = await endpoints.request_introduction(
            pursuit_id=pursuit_id, response=repeat, payload=PartnerRequestCreate(
                analysis_run_id=run_id, gap_id=gaps["EXPERIENCE"], kind="INTRODUCTION", firm_key=claims.firm_key),
            x_organization_id=organization_a, current_user=user_a, db=db)
        assert repeat.status_code == 200 and again.request_id == created.request_id and kicks == [1]

        second = await endpoints.request_introduction(
            pursuit_id=pursuit_id, response=Response(), payload=PartnerRequestCreate(
                analysis_run_id=run_id, gap_id=gaps["EXPERIENCE"], kind="INTRODUCTION", firm_key=actuaries.firm_key),
            x_organization_id=organization_a, current_user=user_a, db=db)
        local = await endpoints.partner_suggestions(
            pursuit_id=pursuit_id, analysis_run_id=run_id, gap_id=gaps["LOCAL_PRESENCE"],
            x_organization_id=organization_a, current_user=user_a, db=db)
        same_firm_local = await endpoints.request_introduction(
            pursuit_id=pursuit_id, response=Response(), payload=PartnerRequestCreate(
                analysis_run_id=run_id, gap_id=gaps["LOCAL_PRESENCE"], kind="INTRODUCTION",
                firm_key=local.suggestions[0].firm_key),
            x_organization_id=organization_a, current_user=user_a, db=db)
        sourcing = await endpoints.request_introduction(
            pursuit_id=pursuit_id, response=Response(), payload=PartnerRequestCreate(
                analysis_run_id=run_id, gap_id=gaps["EXPERT"], kind="EXPERT_SOURCING",
                note="Russian-speaking actuary, 3 months"),
            x_organization_id=organization_a, current_user=user_a, db=db)
        assert sourcing.firm_name is None and sourcing.gap_category == "EXPERT"

        for payload, code in (
            (PartnerRequestCreate(analysis_run_id=run_id, gap_id=gaps["EXPERIENCE"], kind="INTRODUCTION",
                                  firm_key="MINISTRY OF FINANCE|UZBEKISTAN"), 404),  # never suggested
            (PartnerRequestCreate(analysis_run_id=run_id, gap_id=gaps["EXPERIENCE"], kind="EXPERT_SOURCING"), 409),
            (PartnerRequestCreate(analysis_run_id=run_id, gap_id=gaps["EXPERT"], kind="INTRODUCTION",
                                  firm_key=claims.firm_key), 409),
        ):
            with pytest.raises(HTTPException) as rejected:
                await endpoints.request_introduction(pursuit_id=pursuit_id, response=Response(), payload=payload,
                                                     x_organization_id=organization_a, current_user=user_a, db=db)
            assert rejected.value.status_code == code
        # Organization B cannot request on, or read, organization A's pursuit.
        with pytest.raises(HTTPException) as foreign:
            await endpoints.request_introduction(
                pursuit_id=pursuit_id, response=Response(), payload=PartnerRequestCreate(
                    analysis_run_id=run_id, gap_id=gaps["EXPERIENCE"], kind="INTRODUCTION", firm_key=claims.firm_key),
                x_organization_id=organization_b, current_user=user_b, db=db)
        assert foreign.value.status_code == 404
        with pytest.raises(HTTPException) as unreadable:
            await endpoints.partner_requests(pursuit_id=pursuit_id, x_organization_id=organization_b,
                                             current_user=user_b, db=db)
        assert unreadable.value.status_code == 404

        # One alert per new request to the Plasma team; nothing is e-mailed to anyone, least of all the firm.
        alerts = list((await db.scalars(select(AdminAlert).where(AdminAlert.kind == "PARTNER_REQUEST")
                                        .order_by(AdminAlert.created_at))).all())
        assert len(alerts) == 4 and kicks == [1, 1, 1, 1]
        assert await db.scalar(select(func.count(EmailDelivery.id))) == emails_before
        first_alert = next(alert for alert in alerts if alert.payload["request_id"] == str(created.request_id))
        subject, lines = render_alert(first_alert)
        assert "Claims Advisory LLC" in subject and any("Nothing has been sent to the firm" in line for line in lines)
        _assert_public_only([alert.payload for alert in alerts], requester_email="user_a@same-domain.invalid")
        assert await db.scalar(select(func.count(AdminActivityEvent.id)).where(
            AdminActivityEvent.action == "PARTNER_REQUEST_CREATED")) == 4
        # The database refuses a second request for the same Gap and firm.
        row = await db.get(PartnerRequest, created.request_id)
        with pytest.raises(Exception, match="uq_partner_request_gap_firm"):
            db.add(PartnerRequest(
                organization_id=row.organization_id, pursuit_id=row.pursuit_id, analysis_run_id=row.analysis_run_id,
                gap_id=row.gap_id, kind="INTRODUCTION", gap_category="PARTNER_FIRM", gap_summary="duplicate",
                firm_key=row.firm_key, firm_name=row.firm_name, suggestion_snapshot={},
                requester_membership_id=row.requester_membership_id, requester_user_id=row.requester_user_id,
                status="REQUESTED"))
            await db.commit()
        await db.rollback()
    return {"claims": created.request_id, "actuaries": second.request_id, "claims_local": same_firm_local.request_id,
            "sourcing": sourcing.request_id, "gaps": gaps}


async def _queue(sessions, ids, organization_a, pursuit_id, requests) -> None:
    from app.api.endpoints import partner_finder as endpoints
    from app.models.all_models import AdminActivityEvent
    from app.models.user import User
    from app.schemas.partner_finder import PartnerRequestStatusChange

    async with sessions() as db:
        operator, user_a = await db.get(User, ids["operator"]), await db.get(User, ids["user_a"])
        queue = await endpoints.admin_partner_requests(status_filter=None, db=db)
        assert {item.request_id for item in queue} == {
            requests[key] for key in ("claims", "actuaries", "claims_local", "sourcing")}
        claims = next(item for item in queue if item.request_id == requests["claims"])
        assert claims.organization_name and claims.requester_email == "user_a@same-domain.invalid"
        assert claims.tender_title == TENDER_TITLE and claims.next_statuses == ["CONTACTED", "DECLINED"]
        assert len(await endpoints.admin_partner_requests(status_filter="REQUESTED", db=db)) == 4

        with pytest.raises(HTTPException) as skipped:
            await endpoints.admin_change_status(request_id=requests["claims"], payload=PartnerRequestStatusChange(
                status="ACCEPTED"), current_user=operator, db=db)
        assert skipped.value.status_code == 409
        for request, steps in (
            ("claims", [("CONTACTED", "Called their director"), ("ACCEPTED", "They will join as JV member")]),
            ("claims_local", [("CONTACTED", None), ("ACCEPTED", None), ("INTRODUCED", "E-mail introduction sent")]),
            ("actuaries", [("DECLINED", "No capacity until 2027")]),
        ):
            for status, message in steps:
                changed = await endpoints.admin_change_status(
                    request_id=requests[request], payload=PartnerRequestStatusChange(status=status, message=message),
                    current_user=operator, db=db)
                assert changed.status == status
        with pytest.raises(HTTPException) as terminal:
            await endpoints.admin_change_status(request_id=requests["actuaries"], payload=PartnerRequestStatusChange(
                status="CONTACTED"), current_user=operator, db=db)
        assert terminal.value.status_code == 409
        assert await db.scalar(select(func.count(AdminActivityEvent.id)).where(
            AdminActivityEvent.action == "PARTNER_REQUEST_STATUS_CHANGED")) == 6
        event = await db.scalar(select(AdminActivityEvent).where(
            AdminActivityEvent.action == "PARTNER_REQUEST_STATUS_CHANGED",
            AdminActivityEvent.target_resource_id == str(requests["actuaries"])))
        assert (event.previous_state, event.new_state, event.actor_user_id) == (
            {"status": "REQUESTED"}, {"status": "DECLINED"}, ids["operator"])

        # The requester sees the status and the team's messages.
        mine = {item.request_id: item for item in await endpoints.partner_requests(
            pursuit_id=pursuit_id, x_organization_id=organization_a, current_user=user_a, db=db)}
        assert mine[requests["claims"]].status == "ACCEPTED"
        assert [(event.to_status, event.message) for event in mine[requests["claims"]].history] == [
            ("REQUESTED", None), ("CONTACTED", "Called their director"), ("ACCEPTED", "They will join as JV member")]
        assert mine[requests["actuaries"]].status == "DECLINED"


async def _scenarios(sessions, ids, organization_a, organization_b, owner_a, pursuit_id, requests) -> None:
    from app.api.endpoints import partner_finder as endpoints
    from app.models.user import User
    from app.schemas.partner_finder import ProspectiveMemberCreate
    from app.schemas.team_scenarios import TeamScenarioCreateRequest
    from app.services.partner_finder import PartnerFinderNotFoundError, add_prospective_member
    from app.services.team_scenarios import create_team_scenario, get_team_scenario

    async with sessions() as db:
        user_a = await db.get(User, ids["user_a"])
        scenario = await create_team_scenario(
            db, organization_id=organization_a, pursuit_id=pursuit_id, membership_id=owner_a,
            request=TeamScenarioCreateRequest(title="Lead + local claims partner"))
        assert scenario.prospective_members == []
        base = scenario.latest_revision
        for request in ("actuaries", "sourcing"):  # declined; not an introduction
            with pytest.raises(HTTPException) as refused:
                await endpoints.add_prospective_member(
                    pursuit_id=pursuit_id, scenario_id=scenario.scenario_id,
                    payload=ProspectiveMemberCreate(partner_request_id=requests[request]),
                    x_organization_id=organization_a, current_user=user_a, db=db)
            assert refused.value.status_code == 409
        with pytest.raises(PartnerFinderNotFoundError):  # another organization cannot use A's request
            await add_prospective_member(db, organization_id=organization_b, pursuit_id=pursuit_id,
                                         scenario_id=scenario.scenario_id, membership_id=owner_a,
                                         partner_request_id=requests["claims"])
        for _ in range(2):  # idempotent
            await endpoints.add_prospective_member(
                pursuit_id=pursuit_id, scenario_id=scenario.scenario_id,
                payload=ProspectiveMemberCreate(partner_request_id=requests["claims"]),
                x_organization_id=organization_a, current_user=user_a, db=db)
        projected = await get_team_scenario(db, organization_id=organization_a, pursuit_id=pursuit_id,
                                            scenario_id=scenario.scenario_id)
        [member] = projected.prospective_members
        assert member.display_name == "Claims Advisory LLC" and member.confirmation == "NOT_YET_CONFIRMED"
        # Accepted for the experience Gap and introduced for the local-presence Gap: it would close both.
        assert set(member.would_close_gap_ids) == {requests["gaps"]["EXPERIENCE"], requests["gaps"]["LOCAL_PRESENCE"]}
        revision = projected.latest_revision
        assert revision.revision_id == base.revision_id and revision.assessment_state == base.assessment_state
        assert projected.prospective_covered_gap_count == revision.covered_gap_count + 2

        await endpoints.remove_prospective_member(
            pursuit_id=pursuit_id, scenario_id=scenario.scenario_id, member_id=member.prospective_member_id,
            x_organization_id=organization_a, current_user=user_a, db=db)
        projected = await get_team_scenario(db, organization_id=organization_a, pursuit_id=pursuit_id,
                                            scenario_id=scenario.scenario_id)
        assert projected.prospective_members == []
        assert projected.prospective_covered_gap_count == revision.covered_gap_count
        await endpoints.add_prospective_member(
            pursuit_id=pursuit_id, scenario_id=scenario.scenario_id,
            payload=ProspectiveMemberCreate(partner_request_id=requests["claims_local"]),
            x_organization_id=organization_a, current_user=user_a, db=db)
        projected = await get_team_scenario(db, organization_id=organization_a, pursuit_id=pursuit_id,
                                            scenario_id=scenario.scenario_id)
        assert len(projected.prospective_members) == 1
