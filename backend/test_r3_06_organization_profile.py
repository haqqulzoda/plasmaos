"""R3 Task 6: one organization-level company profile for every ACTIVE member.

An invited MEMBER (no profile of their own) sees exactly what the OWNER sees: matches,
dismissals, dashboard profile, readiness, pursuits and My Tenders. Organizations never
leak into each other, a multi-organization user switches with X-Organization-ID, a
revoked member loses access at once, and a legacy single-user account is unchanged.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import deps
from app.api.endpoints import hunter as hunter_endpoints
from app.api.endpoints import my_tenders as my_tender_endpoints
from app.api.endpoints import organizations as org_endpoints
from app.api.endpoints import users as user_endpoints
from app.api.endpoints import vault as vault_endpoints
from app.core.organization_selection import OrganizationSelectionMiddleware, _selected
from app.models.all_models import Tender
from app.models.tenancy import Membership
from app.models.company import CompanyProfile
from app.models.organization_records import OrganizationRecordEvent
from app.models.user import User
from app.schemas.engagement import TenderEngagementActionRequest
from app.schemas.vault import CompanyVaultUpdate, ReadinessDocumentCreate, ReadinessDocumentUpdate
from app.services.explorer import ExplorerQuery, list_explorer_tenders
from app.services.memberships import activate_invitation, invite_member, revoke_membership
from app.services.organization_context import (
    SELECTED_ORGANIZATION,
    OrganizationAccessDeniedError,
    effective_company_profile,
    organization_profile_context,
)
from app.services.organization_records import changed_fields
from scripts import test_s0_5b4_baseline as support
from test_w2_organization_pursuit_foundation import W1_HEAD, _seed_w1


HEAD = "20261011_0001_r3_organization_record_events"
PREVIOUS = "20261010_0001_r3_email_notifications"


# ---- pure rules -----------------------------------------------------------------------------------

def test_header_parsing_and_field_diff() -> None:
    organization = uuid4()
    assert _selected({"headers": [(b"x-organization-id", str(organization).encode())]}) == organization
    assert _selected({"headers": [(b"x-organization-id", b"not-a-uuid")]}) is None
    assert _selected({"headers": []}) is None
    assert changed_fields({"a": 1, "b": [1]}, {"a": 1, "b": [2], "c": None}) == ["b"]
    assert changed_fields({}, {"c": "x"}) == ["c"]


def test_middleware_scopes_the_selection_to_one_request() -> None:
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(OrganizationSelectionMiddleware)

    @app.get("/probe")
    async def probe():
        value = SELECTED_ORGANIZATION.get()
        return {"selected": str(value) if value else None}

    client = TestClient(app)
    organization = uuid4()
    assert client.get("/probe", headers={"X-Organization-ID": str(organization)}).json() == {"selected": str(organization)}
    assert client.get("/probe").json() == {"selected": None}
    assert SELECTED_ORGANIZATION.get() is None


# ---- migration ------------------------------------------------------------------------------------

def test_r3_06_migration_is_additive_append_only_and_reversible() -> None:
    async def scenario() -> None:
        database = support.database_name("r3_06_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", PREVIOUS)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('organization_record_events')")
                assert await connection.fetchval(
                    "SELECT count(*) FROM pg_trigger WHERE tgname='organization_record_events_immutable'"
                ) == 1
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", PREVIOUS)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('organization_record_events')") is None
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


# ---- Postgres scenario ----------------------------------------------------------------------------

def test_every_member_sees_the_organization_profile() -> None:
    async def scenario() -> None:
        database = support.database_name("r3_06_org_profile")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                org_a = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"])
                org_b = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_b"])
                owner_a = await connection.fetchval("SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", org_a, ids["user_a"])
                owner_b = await connection.fetchval("SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", org_b, ids["user_b"])
                await connection.execute(
                    "UPDATE company_profiles SET target_countries='[\"Uzbekistan\"]'::json, company_name='Alpha LLC' WHERE id=$1",
                    ids["profile_a"],
                )
                await connection.execute(
                    "UPDATE company_profiles SET target_countries='[\"Kenya\"]'::json, company_name='Beta LLC' WHERE id=$1",
                    ids["profile_b"],
                )
                now = datetime.now(timezone.utc)
                for index, country in enumerate(["Uzbekistan"] * 4 + ["Kenya"] * 3):
                    await connection.execute(
                        """
                        INSERT INTO tenders(id,external_id,source_system,canonical_source_key,source_url,title,description,
                            budget,currency,category,status,deadline,country,created_at)
                        VALUES ($1,$2,'world_bank',$3,'https://example.invalid/t',$4,'Consulting services',
                            100000,'USD','Services','OPEN',$5,$6,$7)
                        """,
                        uuid4(), f"R306-{index}", f"world_bank:R306-{index}", f"R306 {country} {index}",
                        now + timedelta(days=30), country, now - timedelta(hours=index + 1),
                    )
                # A legacy single-user account: a profile that was never mapped to an organization.
                legacy_user = uuid4()
                await connection.execute(
                    "INSERT INTO users(id,google_id,email,name,subscription_tier,is_admin,approval_status,platform_role,auth_version)"
                    " VALUES ($1,'legacy-g','legacy@solo.invalid','Legacy','SCOUT',false,'approved','pilot_user',0)", legacy_user,
                )
                legacy_profile = uuid4()
                await connection.execute(
                    "INSERT INTO company_profiles(id,user_id,company_name,inn,pilot_status,approval_status,target_countries)"
                    " VALUES ($1,$2,'Solo LLC','SOLO','active_pilot','approved','[\"Kenya\"]'::json)", legacy_profile, legacy_user,
                )
            finally:
                await connection.close()
            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                await _flow(sessions, ids, org_a, org_b, owner_a, owner_b, legacy_user, legacy_profile)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


def _selected_org(value):
    """Run the following block as if the request carried X-Organization-ID."""
    class _Scope:
        def __enter__(self):
            self.token = SELECTED_ORGANIZATION.set(value)

        def __exit__(self, *_):
            SELECTED_ORGANIZATION.reset(self.token)

    return _Scope()


async def _matches(db, user_id) -> list[str]:
    result = await list_explorer_tenders(
        db, user_id=user_id, query=ExplorerQuery(view="recommended", q="R306", limit=50),
    )
    return sorted(item.tender.title for item in result.items)


async def _flow(sessions, ids, org_a, org_b, owner_a, owner_b, legacy_user, legacy_profile) -> None:
    # An invited MEMBER of A (no profile of their own) and a user in both A and B.
    for organization, owner, key in ((org_a, owner_a, "member"), (org_a, owner_a, "multi"), (org_b, owner_b, "multi")):
        async with sessions() as db, db.begin():
            invited = await invite_member(db, organization_id=organization, actor_membership_id=owner, user_id=ids[key])
        async with sessions() as db, db.begin():
            await activate_invitation(db, membership_id=invited.id, user_id=ids[key])
    async with sessions() as db:
        assert await db.scalar(select(CompanyProfile.id).where(CompanyProfile.user_id == ids["member"])) is None
        owner, member, owner_b_user, multi = [await db.get(User, ids[key]) for key in ("user_a", "member", "user_b", "multi")]

        # Matches: identical for the OWNER and the MEMBER; B sees only its own countries.
        owner_matches = await _matches(db, owner.id)
        assert owner_matches == [f"R306 Uzbekistan {n}" for n in range(4)]
        assert await _matches(db, member.id) == owner_matches
        assert await _matches(db, owner_b_user.id) == [f"R306 Kenya {n}" for n in range(4, 7)]

        # Dashboard profile and gates follow the organization.
        owner_company = await user_endpoints.get_company_profile(current_user=owner, db=db)
        member_company = await user_endpoints.get_company_profile(current_user=member, db=db)
        assert member_company.company_profile_id == owner_company.company_profile_id == ids["profile_a"]
        assert member_company.company_name == "Alpha LLC"
        assert (await user_endpoints.get_access_status(current_user=member, db=db)).access_allowed
        assert await deps.require_approved_pilot_access(current_user=member, db=db) is member
        assert await deps.require_explorer_access(current_user=member, db=db) is member

        # Readiness: one list for the team; a member's record is the organization's, audited.
        created = await vault_endpoints.create_readiness_document(
            payload=ReadinessDocumentCreate(document_type="license", document_name="Design licence", status="available"),
            current_user=member, db=db,
        )
        owner_list = await vault_endpoints.list_readiness_documents(current_user=owner, db=db, limit=25, offset=0, response=None)
        member_list = await vault_endpoints.list_readiness_documents(current_user=member, db=db, limit=25, offset=0, response=None)
        assert [item.id for item in owner_list] == [item.id for item in member_list] == [created.id]
        assert created.company_profile_id == ids["profile_a"]
        await vault_endpoints.update_readiness_document(
            document_id=created.id, payload=ReadinessDocumentUpdate(document_number="LIC-7"), current_user=owner, db=db,
        )
        b_list = await vault_endpoints.list_readiness_documents(current_user=owner_b_user, db=db, limit=25, offset=0, response=None)
        assert b_list == []
        with pytest.raises(HTTPException) as foreign_doc:
            await vault_endpoints.update_readiness_document(
                document_id=created.id, payload=ReadinessDocumentUpdate(document_number="X"), current_user=owner_b_user, db=db,
            )
        assert foreign_doc.value.status_code == 404

        # Profile writes: any ACTIVE member; approval/pilot fields are not member-writable.
        updated = await user_endpoints.update_company_profile(
            profile_data=user_endpoints.CompanyProfileUpdate(website="https://alpha.example", approval_status="rejected"),
            current_user=member, db=db,
        )
        assert updated.website == "https://alpha.example" and updated.approval_status == "approved"
        vault = await vault_endpoints.update_company_vault(
            payload=CompanyVaultUpdate(company_name="Alpha LLC", target_countries=["Uzbekistan"],
                                       licenses=[{"license_name": "Design", "is_active": True}]),
            current_user=member, db=db,
        )
        assert vault.id == ids["profile_a"] and [item.license_name for item in vault.licenses] == ["Design"]
        events = (await db.execute(
            select(OrganizationRecordEvent.record_type, OrganizationRecordEvent.action, OrganizationRecordEvent.changed_fields,
                   OrganizationRecordEvent.actor_user_id)
            .where(OrganizationRecordEvent.organization_id == org_a).order_by(OrganizationRecordEvent.created_at)
        )).all()
        summary = [(record_type, action, actor) for record_type, action, _fields, actor in events]
        assert summary == [
            ("READINESS_DOCUMENT", "CREATE", ids["member"]), ("READINESS_DOCUMENT", "UPDATE", ids["user_a"]),
            ("COMPANY_PROFILE", "UPDATE", ids["member"]), ("COMPANY_VAULT", "UPDATE", ids["member"]),
        ]
        assert events[1][2] == ["document_number"] and events[2][2] == ["website"]
        assert "licenses" in events[3][2] and "approval_status" not in str(events)
        listed = await org_endpoints.list_organization_record_events(organization_id=org_a, current_user=owner, db=db)
        assert len(listed) == 4 and listed[0].actor_name
        with pytest.raises(HTTPException) as members_cannot:
            await org_endpoints.list_organization_record_events(organization_id=org_a, current_user=member, db=db)
        assert members_cannot.value.status_code == 403

        # Pursuits and dismissals: one member's dismissal hides the tender for the team.
        dismissed_title = owner_matches[0]
        tender_id = await db.scalar(select(Tender.id).where(Tender.title == dismissed_title))
        saved = await my_tender_endpoints.save_tender_for_current_user(tender_id=tender_id, current_user=member, db=db)
        owner_list = await my_tender_endpoints.get_my_tenders(
            engagement_status="ACTIVE", source=None, tender_status=None, search=None, sort_by="recently_updated",
            offset=0, limit=25, current_user=owner, db=db,
        )
        member_list = await my_tender_endpoints.get_my_tenders(
            engagement_status="ACTIVE", source=None, tender_status=None, search=None, sort_by="recently_updated",
            offset=0, limit=25, current_user=member, db=db,
        )
        # The team's list (the seed already had one owner engagement): the same for both.
        owner_ids = [item.engagement_id for item in owner_list.items]
        assert owner_ids == [item.engagement_id for item in member_list.items]
        assert saved.engagement.engagement_id in owner_ids and len(owner_ids) == 2
        await my_tender_endpoints.apply_tender_engagement_action(
            engagement_id=saved.engagement.engagement_id, action="dismiss",
            command=TenderEngagementActionRequest(expected_status=saved.engagement.engagement_status),
            current_user=member, db=db,
        )
        assert dismissed_title not in await _matches(db, owner.id)
        assert await _matches(db, member.id) == await _matches(db, owner.id)
        assert len(await _matches(db, owner_b_user.id)) == 3  # B is untouched

        # Recommendations: empty, never an error, for invited members.
        assert await hunter_endpoints.list_recommendations(current_user=member, db=db) == []

        # Multi-organization user: the selected organization decides; default is the earliest.
        with _selected_org(org_b):
            assert (await effective_company_profile(db, user_id=multi.id)).id == ids["profile_b"]
            assert await _matches(db, multi.id) == [f"R306 Kenya {n}" for n in range(4, 7)]
        with _selected_org(org_a):
            assert await _matches(db, multi.id) == await _matches(db, owner.id)
        assert (await effective_company_profile(db, user_id=multi.id)).id == ids["profile_a"]
        # A member of A naming B is refused (the middleware answers 404).
        with _selected_org(org_b), pytest.raises(OrganizationAccessDeniedError):
            await organization_profile_context(db, user_id=member.id)
        await db.commit()

        member_a = await db.scalar(select(Membership.id).where(Membership.user_id == ids["member"]))

    # A revoked member loses access at once.
    async with sessions() as db, db.begin():
        await revoke_membership(db, organization_id=org_a, actor_membership_id=owner_a, membership_id=member_a)
    async with sessions() as db:
        member = await db.get(User, ids["member"])
        assert await effective_company_profile(db, user_id=member.id) is None
        with pytest.raises(HTTPException) as revoked:
            await deps.require_approved_pilot_access(current_user=member, db=db)
        assert revoked.value.status_code == 403
        assert (await user_endpoints.get_company_profile(current_user=member, db=db)).company_profile_id is None
        assert await _matches(db, member.id) == []

    # A legacy single-user account keeps its own profile.
    async with sessions() as db:
        legacy = await db.get(User, legacy_user)
        assert (await effective_company_profile(db, user_id=legacy.id)).id == legacy_profile
        assert await deps.require_approved_pilot_access(current_user=legacy, db=db) is legacy
        assert await _matches(db, legacy.id) == [f"R306 Kenya {n}" for n in range(4, 7)]
        assert await db.scalar(select(func.count(OrganizationRecordEvent.id))) == 4


# ---- the middleware through the real application --------------------------------------------------

def test_selection_header_through_the_real_app() -> None:
    """(1) a revoked member's stale header is 404; (2) an operator without membership gets
    no organization data through the header; (3) admin-only routes ignore the header."""
    import httpx

    from app.api.endpoints.auth import _token_payload
    from app.core.security import create_access_token
    from app.db.session import get_db
    from app.main import app

    async def scenario() -> None:
        database = support.database_name("r3_06_header")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                org_a = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"])
                org_b = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_b"])
                owner_a = await connection.fetchval("SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", org_a, ids["user_a"])
                await connection.execute("UPDATE users SET platform_role='admin', is_admin=true WHERE id=$1", ids["multi"])
                await connection.execute(
                    "INSERT INTO readiness_documents(id,company_profile_id,document_type,document_name,status)"
                    " VALUES ($1,$2,'license','A licence','available')", uuid4(), ids["profile_a"],
                )
            finally:
                await connection.close()
            engine = create_async_engine(support.target_url(database), pool_size=4)
            sessions = async_sessionmaker(engine, expire_on_commit=False)

            async def override():
                async with sessions() as session:
                    try:
                        yield session
                        await session.commit()
                    except Exception:
                        await session.rollback()
                        raise

            app.dependency_overrides[get_db] = override
            try:
                async with sessions() as db, db.begin():
                    invited = await invite_member(db, organization_id=org_a, actor_membership_id=owner_a, user_id=ids["member"])
                async with sessions() as db, db.begin():
                    await activate_invitation(db, membership_id=invited.id, user_id=ids["member"])

                async def bearer(key: str) -> dict[str, str]:
                    async with sessions() as db:
                        user = await db.get(User, ids[key])
                        profile = await effective_company_profile(db, user_id=user.id)
                        return {"Authorization": f"Bearer {create_access_token(_token_payload(user, profile))}"}

                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
                    member = await bearer("member")
                    selected = {**member, "X-Organization-ID": str(org_a)}
                    ok = await client.get("/api/v1/vault/readiness", headers=selected)
                    assert ok.status_code == 200 and [item["document_name"] for item in ok.json()] == ["A licence"]
                    assert (await client.get("/api/v1/vault/readiness", headers=member)).status_code == 200

                    # (1) Revoked: the stale header is 404 "Organization not found" (the client
                    # forgets it and retries once); without the header there is no organization.
                    async with sessions() as db, db.begin():
                        await revoke_membership(db, organization_id=org_a, actor_membership_id=owner_a, membership_id=invited.id)
                    stale = await client.get("/api/v1/vault/readiness", headers=selected)
                    assert stale.status_code == 404 and stale.json() == {"detail": "Organization not found"}
                    for path in ("/api/v1/users/me/company", "/api/v1/users/me/access-status", "/api/v1/my-tenders"):
                        response = await client.get(path, headers=selected)
                        assert response.status_code == 404 and response.json()["detail"] == "Organization not found", path
                    retried = await client.get("/api/v1/users/me/access-status", headers=member)
                    assert retried.status_code == 200 and retried.json()["access_allowed"] is False

                    # (2) An admin/operator who is not a member gets no organization data via the header.
                    admin = await bearer("multi")
                    for path in ("/api/v1/vault/readiness", "/api/v1/users/me/company", "/api/v1/candidates"):
                        response = await client.get(path, headers={**admin, "X-Organization-ID": str(org_a)})
                        assert response.status_code == 404, (path, response.status_code)
                        assert "A licence" not in response.text and "Same Name Company" not in response.text
                    company = await client.get("/api/v1/users/me/company", headers=admin)
                    assert company.status_code == 200 and company.json()["company_profile_id"] is None

                    # (3) Admin-only routes ignore the header: identical answers with or without it.
                    for path in ("/api/v1/admin/panels/organizations", "/api/v1/admin/accounts?limit=50"):
                        plain = await client.get(path, headers=admin)
                        widened = await client.get(path, headers={**admin, "X-Organization-ID": str(org_b)})
                        assert plain.status_code == widened.status_code == 200, path
                        assert plain.json() == widened.json(), path
                    member_admin = await client.get(
                        "/api/v1/admin/panels/organizations", headers={**await bearer("user_a"), "X-Organization-ID": str(org_a)}
                    )
                    assert member_admin.status_code == 403  # an organization header never grants admin access
            finally:
                app.dependency_overrides.pop(get_db, None)
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())
