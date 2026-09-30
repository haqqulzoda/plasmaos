"""Integration fix 3d: "Matches your profile" and the Explorer service filter.

* Tenders the viewer's organization has DISMISSED (pursuit stage) are not offered in
  "Matches your profile" (list and count); another organization's dismissal does not
  hide them.
* The Explorer service filter and the profile match use the same whole-word rule:
  "IT" matches "IT equipment", not "Furniture supply".
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.api.endpoints.tenders import _service_predicate
from app.models.all_models import Tender
from app.models.base import TenderEngagementOrigin, TenderEngagementStatus, TenderStatus
from app.models.tenancy import OrganizationPursuit
from app.services.explorer import ExplorerQuery, ExplorerView, list_explorer_tenders
from app.services.profile_match import ProfileTargets, profile_match_condition, service_match_condition
from app.services.pursuits import get_or_create_source_pursuit
from test_d1_04_05_freshness_truth import _database


def test_dismissed_pursuits_are_not_offered_and_filter_matches_profile_rule() -> None:
    async def scenario() -> None:
        async with _database("int_3d_profile") as (_name, ids, sessions, _engine):
            deadline = datetime.now(UTC) + timedelta(days=30)
            titles = {
                "KEEP": "INT3D IT equipment for schools",
                "DISMISSED": "INT3D IT network upgrade",
                "OTHER-ORG-DISMISSED": "INT3D software licences",
                "FURNITURE": "INT3D Furniture supply",
                "BROADBAND": "INT3D broadband rollout",
            }
            tender_ids = {}
            async with sessions() as db:
                for key, title in titles.items():
                    tender = Tender(
                        source_system="world_bank", external_id=f"INT3D-{key}",
                        canonical_source_key=f"world_bank:INT3D-{key}",
                        source_url=f"https://example.test/{key}", title=title, description="d", budget=0,
                        currency="USD", status=TenderStatus.OPEN, category="Other", deadline=deadline,
                        country="Uzbekistan",
                    )
                    db.add(tender)
                    await db.flush()
                    tender_ids[key] = tender.id
                await db.commit()

            # Whole-word rule, identical for the filter and the profile match.
            async with sessions() as db:
                scoped = Tender.id.in_(tender_ids.values())
                by_filter = set((await db.scalars(select(Tender.title).where(scoped, _service_predicate(["IT"])))).all())
                by_profile = set((await db.scalars(select(Tender.title).where(
                    scoped, profile_match_condition(ProfileTargets(services=("IT",)))))).all())
                assert by_filter == by_profile == {titles["KEEP"], titles["DISMISSED"], titles["OTHER-ORG-DISMISSED"]}
                assert titles["FURNITURE"] not in by_filter and titles["BROADBAND"] not in by_filter
                assert service_match_condition([]) is None

            connection = await __import__("scripts.test_s0_5b4_baseline", fromlist=["x"]).database_connection(_name)
            try:
                memberships = {}
                for user, profile in (("user_a", "profile_a"), ("user_b", "profile_b")):
                    await connection.execute(
                        "UPDATE company_profiles SET target_services='[\"IT\"]'::json, target_countries='[]'::json WHERE id=$1",
                        ids[profile])
                    organization = await connection.fetchval(
                        "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids[profile])
                    memberships[user] = (organization, await connection.fetchval(
                        "SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", organization, ids[user]))
            finally:
                await connection.close()

            async with sessions() as db:
                for user, key in (("user_a", "DISMISSED"), ("user_b", "OTHER-ORG-DISMISSED")):
                    organization, membership = memberships[user]
                    resolution = await get_or_create_source_pursuit(
                        db, organization_id=organization, actor_user_id=ids[user], actor_membership_id=membership,
                        tender_id=tender_ids[key], stage=TenderEngagementStatus.SAVED,
                        legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
                    )
                    pursuit = await db.get(OrganizationPursuit, resolution.pursuit.id)
                    pursuit.stage = TenderEngagementStatus.DISMISSED
                await db.commit()

            async with sessions() as db:
                matches = await list_explorer_tenders(db, user_id=ids["user_a"], query=ExplorerQuery(
                    view=ExplorerView.RECOMMENDED, q="INT3D", limit=50))
                listed = {item.tender.title for item in matches.items}
                assert listed == {titles["KEEP"], titles["OTHER-ORG-DISMISSED"]}
                assert matches.counts.active_recommendations == 2
                # The other organization sees its own dismissal excluded, not user_a's.
                theirs = await list_explorer_tenders(db, user_id=ids["user_b"], query=ExplorerQuery(
                    view=ExplorerView.RECOMMENDED, q="INT3D", limit=50))
                assert {item.tender.title for item in theirs.items} == {titles["KEEP"], titles["DISMISSED"]}
                # The Explorer filter (all view) still lists dismissed tenders: dismissal only
                # removes them from "Matches your profile".
                filtered = await list_explorer_tenders(db, user_id=ids["user_a"], query=ExplorerQuery(
                    q="INT3D", services=["IT"], limit=50))
                assert {item.tender.title for item in filtered.items} == {
                    titles["KEEP"], titles["DISMISSED"], titles["OTHER-ORG-DISMISSED"]}

    asyncio.run(scenario())
