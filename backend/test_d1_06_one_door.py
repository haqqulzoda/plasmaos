"""D1-06 one door (idempotent create-or-resolve) and D1-08 "Matches your profile" (no score).

Unit checks run anywhere. The database scenario builds one disposable PostgreSQL database
(the W-series harness) and never touches the configured application database.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import Response
from sqlalchemy import func, select, text

from app.api.endpoints import pursuits as pursuits_endpoint
from app.main import app
from app.models.all_models import Tender, TenderStatus, User
from app.models.audit import TenderRecommendation
from app.models.base import TenderEngagementStatus
from app.models.tenancy import OrganizationPursuit, PursuitLifecycleEvent
from app.schemas.explorer import ExplorerTenderItem, ExplorerView
from app.schemas.tenancy import SourcePursuitCreateRequest
from app.schemas.tender_details import TenderDetailsResponse
from app.services.explorer import ExplorerQuery, list_explorer_tenders
from app.services.profile_match import (
    ProfileTargets,
    profile_match_condition,
    profile_targets,
    tender_profile_match,
)
from app.services.tender_details import compose_tender_details
from test_d1_03_official_notice import _database

BACKEND_DIR = Path(__file__).resolve().parent
UTC = timezone.utc


# ---- D1-08 deterministic profile match ----------------------------------------------------------


def test_profile_targets_expand_regions_and_ignore_unknown_shapes() -> None:
    targets = profile_targets(["Uzbekistan", " uzbekistan ", 7], ["Central Asia"], ["consulting", "Consulting", None])
    assert targets.countries[0] == "Uzbekistan"
    assert "Kazakhstan" in targets.countries  # the region was expanded to its countries
    assert len({country.casefold() for country in targets.countries}) == len(targets.countries)
    assert targets.services == ("consulting",)
    assert profile_targets(None, "Central Asia", {"a": 1}).empty
    assert profile_match_condition(ProfileTargets()) is None


def test_profile_match_uses_word_boundaries_so_every_chip_is_a_true_fact() -> None:
    targets = ProfileTargets(countries=("Uzbekistan", "Niger"), services=("consulting", "IT", "construction"))
    consulting = SimpleNamespace(
        country="Republic of Uzbekistan", title="Technical assistance for energy reform", description=None,
        sector=None, category="Other", procurement_category=None, procurement_method=None, notice_type="REOI",
    )
    assert tender_profile_match(consulting, targets) == ("Uzbekistan", ["consulting"])
    goods = SimpleNamespace(
        country="Mongolia", title="Supply of office furniture", description="desks", sector=None,
        category="Goods", procurement_category=None, procurement_method=None, notice_type=None,
    )
    # "IT" is not in "furniture", nor the pronoun "it"; "road" is not in "broadband".
    assert tender_profile_match(goods, targets) == (None, [])
    for title, expected in [
        ("Upgrade of IT systems", ["IT"]),
        ("ICT equipment for schools", ["IT"]),
        ("District heating: it is restricted", []),
        ("Broadband rollout abroad", []),
        ("Rehabilitation of rural roads", ["construction"]),
        ("Строительство автомобильной дороги", ["construction"]),
        ("Consultancy: feasibility study", ["consulting"]),
    ]:
        tender = SimpleNamespace(
            country="Nigeria", title=title, description=None, sector=None, category=None,
            procurement_category=None, procurement_method=None, notice_type=None,
        )
        assert tender_profile_match(tender, targets) == (None, expected), title  # "Niger" is not "Nigeria"
    niger = SimpleNamespace(country="Republic of Niger", title="x", description=None, sector=None, category=None,
                            procurement_category=None, procurement_method=None, notice_type=None)
    assert tender_profile_match(niger, targets)[0] == "Niger"
    sql = str(profile_match_condition(targets).compile(compile_kwargs={"literal_binds": True}))
    assert "tenders.country ~* " in sql and "tenders.title ~ " in sql  # acronyms are case-sensitive


def test_explorer_and_details_expose_facts_and_the_source_endpoint_documents_both_statuses() -> None:
    assert "profile_match" in ExplorerTenderItem.model_fields
    assert "profile_match" in TenderDetailsResponse.model_fields
    responses = app.openapi()["paths"]["/api/v1/pursuits/source"]["post"]["responses"]
    assert {"200", "201"} <= set(responses)
    service = (BACKEND_DIR / "app/services/pursuits.py").read_text(encoding="utf-8")
    assert "on_conflict_do_nothing" in service and "if inserted_id == pursuit_id:" in service


# ---- database scenario --------------------------------------------------------------------------


def test_one_door_is_idempotent_and_matches_view_is_deterministic_on_postgres() -> None:
    async def scenario() -> None:
        async with _database("d1_06_one_door") as (database, ids, sessions, _engine):
            now = datetime.now(UTC)
            rows = {
                "M-COUNTRY": dict(country="Uzbekistan", title="D106 Supply of pumps", deadline=now + timedelta(days=10)),
                "M-SERVICE": dict(country="Kenya", title="D106 Technical assistance for water utilities", deadline=now + timedelta(days=3)),
                "M-NO-DEADLINE": dict(country="Uzbekistan", title="D106 Framework notice", deadline=None),
                "NO-MATCH": dict(country="Kenya", title="D106 Supply of office furniture", deadline=now + timedelta(days=1)),
                "PASSED": dict(country="Uzbekistan", title="D106 Passed deadline", deadline=now - timedelta(days=1)),
                "CLOSED": dict(country="Uzbekistan", title="D106 Closed tender", deadline=now + timedelta(days=2), status=TenderStatus.CLOSED),
            }
            tender_ids = {}
            async with sessions() as db:
                for external_id, values in rows.items():
                    tender = Tender(
                        source_system="world_bank", external_id=external_id,
                        canonical_source_key=f"world_bank:{external_id}", source_url=f"https://example.test/{external_id}",
                        description="d", budget=0, currency="USD", category="Other",
                        notice_type="Request for Expression of Interest",
                        status=values.pop("status", TenderStatus.OPEN), **values,
                    )
                    db.add(tender)
                    await db.flush()
                    tender_ids[external_id] = tender.id
                # A stored Hunter recommendation with a high score for a non-matching tender.
                db.add(TenderRecommendation(
                    tender_id=tender_ids["NO-MATCH"], company_profile_id=ids["profile_a"],
                    match_score=99, strategic_rationale="generated rationale", is_dismissed=False,
                ))
                await db.execute(
                    text("UPDATE company_profiles SET target_countries = CAST(:c AS json), target_services = CAST(:s AS json) WHERE id = :id"),
                    {"c": '["Uzbekistan"]', "s": '["consulting"]', "id": ids["profile_a"]},
                )
                await db.commit()

            # SQL and Python evaluate the same word-boundary rule: compare them row by row.
            parity_targets = ProfileTargets(countries=("Uzbekistan", "Niger"), services=("consulting", "IT", "construction"))
            parity_rows = [
                ("Nigeria", "PARITY Supply of office furniture"),
                ("Nigeria", "PARITY Upgrade of IT systems"),
                ("Nigeria", "PARITY District heating: it is restricted"),
                ("Nigeria", "PARITY Broadband rollout abroad"),
                ("Nigeria", "PARITY Rehabilitation of rural roads"),
                ("Nigeria", "PARITY Строительство автомобильной дороги"),
                ("Republic of Niger", "PARITY Goods"),
                ("Uzbekistan", "PARITY Goods"),
                (None, "PARITY ICT equipment"),
            ]
            async with sessions() as db:
                parity_ids = []
                for index, (country, title) in enumerate(parity_rows):
                    tender = Tender(
                        source_system="world_bank", external_id=f"PARITY-{index}",
                        canonical_source_key=f"world_bank:PARITY-{index}", title=title, country=country,
                        source_url=f"https://example.test/PARITY-{index}",
                        description=None, budget=0, currency="USD", category="Other", status=TenderStatus.OPEN,
                    )
                    db.add(tender)
                    await db.flush()
                    parity_ids.append(tender.id)
                await db.commit()
                sql_matches = set((await db.execute(
                    select(Tender.id).where(Tender.id.in_(parity_ids), profile_match_condition(parity_targets))
                )).scalars().all())
                python_matches = set()
                for tender_id in parity_ids:
                    country, services = tender_profile_match(await db.get(Tender, tender_id), parity_targets)
                    if country or services:
                        python_matches.add(tender_id)
                assert sql_matches == python_matches
                expected = {parity_ids[i] for i in (1, 4, 5, 6, 7, 8)}
                assert sql_matches == expected, [parity_rows[parity_ids.index(i)] for i in sql_matches ^ expected]

            async with sessions() as db:
                stored_before = await db.scalar(select(func.count(TenderRecommendation.id)))
                matches = await list_explorer_tenders(db, user_id=ids["user_a"], query=ExplorerQuery(
                    view=ExplorerView.RECOMMENDED, q="D106", limit=50))
                # >= 1 country or service match, deadline-open, soonest deadline first (no deadline last).
                assert [item.tender.external_id for item in matches.items] == ["M-SERVICE", "M-COUNTRY", "M-NO-DEADLINE"]
                assert matches.counts.active_recommendations == 3 and matches.total == 3
                by_id = {item.tender.external_id: item for item in matches.items}
                assert by_id["M-SERVICE"].profile_match.model_dump() == {"country": None, "services": ["consulting"]}
                assert by_id["M-COUNTRY"].profile_match.model_dump() == {"country": "Uzbekistan", "services": []}
                assert all(item.recommendation is None for item in matches.items)  # no score, no rationale
                assert by_id["M-COUNTRY"].tender.notice_type == "Request for Expression of Interest"
                legacy_sort = await list_explorer_tenders(db, user_id=ids["user_a"], query=ExplorerQuery(
                    view=ExplorerView.RECOMMENDED, q="D106", sort="best_match", limit=50))
                assert [item.tender.external_id for item in legacy_sort.items] == ["M-SERVICE", "M-COUNTRY", "M-NO-DEADLINE"]

                everything = await list_explorer_tenders(db, user_id=ids["user_a"], query=ExplorerQuery(q="D106", limit=50))
                all_items = {item.tender.external_id: item for item in everything.items}
                assert all_items["NO-MATCH"].profile_match is None
                assert all_items["NO-MATCH"].recommendation is None  # the stored 99 is not surfaced
                assert all_items["M-COUNTRY"].profile_match.country == "Uzbekistan"

                # A profile without targets has no matches (and no fabricated ones).
                empty = await list_explorer_tenders(db, user_id=ids["user_b"], query=ExplorerQuery(
                    view=ExplorerView.RECOMMENDED, q="D106", limit=50))
                assert empty.items == [] and empty.counts.active_recommendations == 0

                tender = await db.get(Tender, tender_ids["M-COUNTRY"])
                details = await compose_tender_details(db, tender=tender, user_id=ids["user_a"], procurement_contacts=None)
                assert details.profile_match.model_dump() == {"country": "Uzbekistan", "services": []}
                # Stored recommendation data is kept, just not surfaced.
                assert await db.scalar(select(func.count(TenderRecommendation.id))) == stored_before

            # One door: create-or-resolve is idempotent per (organization, tender).
            async with sessions() as db:
                organization_id = await db.scalar(
                    text("SELECT id FROM organizations WHERE legacy_company_profile_id = :p"), {"p": ids["profile_a"]})
                user = await db.get(User, ids["user_a"])
                payload = SourcePursuitCreateRequest(tender_id=tender_ids["M-COUNTRY"])

                async def post() -> tuple[int | None, object]:
                    response = Response()
                    response.status_code = None  # FastAPI applies the route default (201) when untouched
                    result = await pursuits_endpoint.create_source_pursuit(
                        payload, response, x_organization_id=organization_id, current_user=user, db=db)
                    await db.commit()
                    return response.status_code, result

                first_status, first = await post()
                second_status, second = await post()
                assert (first_status, second_status) == (None, 200)  # created (route default 201), then resolved
                assert first.pursuit_id == second.pursuit_id and second.stage == TenderEngagementStatus.SAVED

                pursuit = await db.get(OrganizationPursuit, first.pursuit_id)
                pursuit.stage = TenderEngagementStatus.EVALUATING
                await db.commit()
                third_status, third = await post()
                assert third_status == 200 and third.pursuit_id == first.pursuit_id
                assert third.stage == TenderEngagementStatus.EVALUATING  # an existing pursuit is never reset

                assert await db.scalar(select(func.count(OrganizationPursuit.id)).where(
                    OrganizationPursuit.source_tender_id == tender_ids["M-COUNTRY"])) == 1
                events = (await db.execute(select(PursuitLifecycleEvent.action).where(
                    PursuitLifecycleEvent.pursuit_id == first.pursuit_id))).scalars().all()
                assert events == ["CREATE"]  # one ledger entry, no duplicate CREATE
                index = await db.scalar(text(
                    "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_organization_pursuits_source'"))
                assert "UNIQUE" in index and "origin" in index  # the partial unique index is intact

    asyncio.run(scenario())
