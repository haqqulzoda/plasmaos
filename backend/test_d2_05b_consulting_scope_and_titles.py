"""D2-05 UI session: consulting-services scope for "Matches your profile", and the first
uploaded document's name on pursuit reads (title fallback)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.api.endpoints import pursuits as pursuits_endpoint
from app.core.config import settings
from app.core.private_storage import PDF_MEDIA_TYPE
from app.models.all_models import Tender, TenderStatus, User
from app.models.base import PrivateDocumentRole
from app.schemas.explorer import ExplorerView
from app.services.explorer import ExplorerQuery, list_explorer_tenders
from app.services.private_documents import persist_private_pack
from app.services.profile_match import (
    ProfileTargets,
    is_consulting_profile,
    is_consulting_scope,
    profile_match_condition,
    profile_targets,
    tender_profile_match,
)
from app.services.pursuits import create_upload_pursuit
from test_d1_03_official_notice import _database
from test_w3_private_document_foundation import _pdf_bytes, _stage


def test_consulting_profiles_are_recognized_from_their_services() -> None:
    assert is_consulting_profile(("consulting",))
    for service in ("Advisory", "Engineering design", "Construction supervision"):
        assert is_consulting_profile((service,)), service
    assert not is_consulting_profile(("construction", "medical", "IT"))
    assert profile_targets(["Uzbekistan"], [], ["consulting"]).consulting_only
    assert not profile_targets(["Uzbekistan"], [], ["construction"]).consulting_only


def test_consulting_scope_keeps_consulting_and_unknown_notices() -> None:
    def tender(category, notice=None):
        return SimpleNamespace(procurement_category=category, notice_type=notice)

    for category, notice in (("Consultant Services", None), ("Consultancy", None), ("Works,Consultancy", None),
                             ("Goods", "Request for Expression of Interest"), (None, None), ("Services", None),
                             ("", "Tender"), ("Kyrgyz Republic", None)):
        assert is_consulting_scope(tender(category, notice)), (category, notice)
    for category, notice in (("Goods", "Invitation for Bids"), ("Works", None), ("Non-consulting Services", None),
                             ("Goods,Works", "General Procurement Notice")):
        assert not is_consulting_scope(tender(category, notice)), (category, notice)


def test_matches_your_profile_is_limited_to_consulting_notices_for_a_consulting_firm() -> None:
    async def scenario() -> None:
        async with _database("d2_05b_consulting") as (_database_name, ids, sessions, _engine):
            now = datetime.now(timezone.utc)
            rows = {
                "C-CONSULTANT": ("world_bank", "Consultant Services", "Request for Expression of Interest"),
                "C-EBRD-MIXED": ("ebrd", "Works,Consultancy", "General Procurement Notice"),
                "C-GIZ-UNKNOWN": ("giz", None, "Tender"),
                "X-GOODS": ("world_bank", "Goods", "Invitation for Bids"),
                "X-WORKS": ("world_bank", "Works", "Invitation for Bids"),
                "X-NONCONSULTING": ("world_bank", "Non-consulting Services", "Invitation for Bids"),
            }
            async with sessions() as db:
                for external_id, (source, category, notice) in rows.items():
                    db.add(Tender(
                        source_system=source, external_id=external_id, canonical_source_key=f"{source}:{external_id}",
                        source_url=f"https://example.test/{external_id}", title=f"D205B {external_id}",
                        description="d", budget=0, currency="USD", category="Other", country="Uzbekistan",
                        procurement_category=category, notice_type=notice, status=TenderStatus.OPEN,
                        deadline=now + timedelta(days=10),
                    ))
                await db.execute(
                    text("UPDATE company_profiles SET target_countries = CAST(:c AS json), target_services = CAST(:s AS json) WHERE id = :id"),
                    {"c": '["Uzbekistan"]', "s": '["consulting"]', "id": ids["profile_a"]},
                )
                await db.execute(
                    text("UPDATE company_profiles SET target_countries = CAST(:c AS json), target_services = CAST(:s AS json) WHERE id = :id"),
                    {"c": '["Uzbekistan"]', "s": '["construction"]', "id": ids["profile_b"]},
                )
                await db.commit()

            async with sessions() as db:
                consulting = await list_explorer_tenders(db, user_id=ids["user_a"], query=ExplorerQuery(
                    view=ExplorerView.RECOMMENDED, q="D205B", limit=50))
                assert {item.tender.external_id for item in consulting.items} == {"C-CONSULTANT", "C-EBRD-MIXED", "C-GIZ-UNKNOWN"}
                assert consulting.counts.active_recommendations == 3
                everything = await list_explorer_tenders(db, user_id=ids["user_a"], query=ExplorerQuery(q="D205B", limit=50))
                facts = {item.tender.external_id: item.profile_match for item in everything.items}
                assert facts["X-GOODS"] is None and facts["C-CONSULTANT"].country == "Uzbekistan"  # chips follow the same rule
                other = await list_explorer_tenders(db, user_id=ids["user_b"], query=ExplorerQuery(
                    view=ExplorerView.RECOMMENDED, q="D205B", limit=50))
                assert {item.tender.external_id for item in other.items} == set(rows)  # no restriction for a non-consulting firm

                # SQL and Python evaluate the same scope.
                targets = ProfileTargets(("Uzbekistan",), ("consulting",), True)
                tender_rows = list((await db.scalars(select(Tender).where(Tender.title.like("D205B%")))).all())
                sql = set((await db.scalars(select(Tender.external_id).where(
                    Tender.title.like("D205B%"), profile_match_condition(targets),
                ))).all())
                python = {row.external_id for row in tender_rows if any(tender_profile_match(row, targets))}
                assert sql == python == {"C-CONSULTANT", "C-EBRD-MIXED", "C-GIZ-UNKNOWN"}

    asyncio.run(scenario())


def test_pursuit_reads_carry_the_first_uploaded_document_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PRIVATE_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private"))

    async def scenario() -> None:
        async with _database("d2_05b_titles") as (database, ids, sessions, _engine):
            connection_org = None
            async with sessions() as db:
                user = await db.get(User, ids["user_a"])
                row = (await db.execute(text(
                    "SELECT o.id, m.id FROM organizations o JOIN memberships m ON m.organization_id=o.id "
                    "WHERE o.legacy_company_profile_id=:p AND m.user_id=:u"
                ), {"p": ids["profile_a"], "u": ids["user_a"]})).one()
                connection_org, membership = row
                pursuit = await create_upload_pursuit(db, organization_id=connection_org, actor_user_id=ids["user_a"],
                                                      actor_membership_id=membership)
                await persist_private_pack(db, pursuit=pursuit, membership_id=membership, files=[
                    _stage(tmp_path / "a.pdf", _pdf_bytes("A"), "Terms of Reference - LOT 4.pdf", PDF_MEDIA_TYPE, PrivateDocumentRole.TOR),
                    _stage(tmp_path / "b.pdf", _pdf_bytes("B"), "Annex.pdf", PDF_MEDIA_TYPE, PrivateDocumentRole.ANNEX),
                ])
                empty = await create_upload_pursuit(db, organization_id=connection_org, actor_user_id=ids["user_a"],
                                                    actor_membership_id=membership)
                listing = await pursuits_endpoint.list_pursuits(
                    origin=None, x_organization_id=connection_org, offset=0, limit=25, current_user=user, db=db,
                )
                names = {item.pursuit_id: item.first_document_name for item in listing.items}
                assert names[pursuit.id] in {"Terms of Reference - LOT 4.pdf", "Annex.pdf"}
                assert names[empty.id] is None
                detail = await pursuits_endpoint.get_pursuit(
                    pursuit_id=pursuit.id, x_organization_id=connection_org, current_user=user, db=db,
                )
                assert detail.first_document_name == names[pursuit.id]

    asyncio.run(scenario())
