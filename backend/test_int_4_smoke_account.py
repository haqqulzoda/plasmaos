"""Rollout step 10: the dedicated "Plasma Smoke Test" account for analysis_smoke.py --live.

On a disposable PostgreSQL: report only writes nothing; apply creates one approved user,
its approved profile and a single-member organization, idempotently; the minted token
passes the live smoke's own dedicated-organization guard through the real endpoints and
can open a source pursuit; the command refuses an e-mail it did not create and an
organization with a second member.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy import func, select

from app.api.endpoints import explorer, organizations, pursuits
from app.db.session import get_db
from app.models.all_models import Tender, User
from app.models.base import MembershipRole, MembershipState, TenderStatus
from app.models.tenancy import Membership
from scripts import analysis_smoke, smoke_account
from test_d1_04_05_freshness_truth import _database


def test_smoke_account_is_idempotent_single_member_and_passes_the_live_guard() -> None:
    async def scenario() -> None:
        async with _database("int_4_smoke") as (_name, ids, sessions, _engine):
            async with sessions() as db:
                users_before = await db.scalar(select(func.count(User.id)))
                report = await smoke_account.ensure_smoke_account(db)
                assert report["status"] == "would_create" and report["missing"] == ["user", "profile", "organization"]
            async with sessions() as db:
                assert await db.scalar(select(func.count(User.id))) == users_before
                with pytest.raises(smoke_account.SmokeAccountError, match="does not exist"):
                    await smoke_account.smoke_token(db)

            async with sessions() as db:
                created = await smoke_account.ensure_smoke_account(db, apply=True)
            assert created["status"] == "created" and created["organization_name"] == "Plasma Smoke Test"
            async with sessions() as db:
                again = await smoke_account.ensure_smoke_account(db, apply=True)
                assert again == {**created, "status": "no_op", "created": []}
                assert (await smoke_account.ensure_smoke_account(db))["status"] == "exists"
                tender = Tender(
                    source_system="world_bank", external_id="INT4-REOI", canonical_source_key="world_bank:INT4-REOI",
                    source_url="https://example.test/reoi", title="INT4 Request for Expression of Interest",
                    description="d", budget=0, currency="USD", status=TenderStatus.OPEN, category="Consulting",
                    deadline=datetime.now(UTC) + timedelta(days=20), country="Uzbekistan",
                )
                db.add(tender)
                await db.commit()
                tender_id = str(tender.id)
                token = await smoke_account.smoke_token(db)

            app = FastAPI()
            for module, prefix in ((organizations, "/api/v1/organizations"), (explorer, "/api/v1"), (pursuits, "/api/v1/pursuits")):
                app.include_router(module.router, prefix=prefix)

            async def session_dependency():
                async with sessions() as session:
                    yield session

            app.dependency_overrides[get_db] = session_dependency
            headers = {"Authorization": f"Bearer {token}", "X-Organization-ID": created["organization_id"]}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test/api/v1") as client:
                responses = {}
                for path in ("/organizations", f"/organizations/{created['organization_id']}/members"):
                    response = await client.get(path, headers=headers)
                    responses[("GET", path)] = (response.status_code, response.json())
                listed = await client.get("/explorer/tenders", params={"source_system": "world_bank", "q": "INT4", "limit": 5}, headers=headers)
                assert listed.status_code == 200 and listed.json()["items"][0]["tender"]["id"] == tender_id
                pursuit = await client.post("/pursuits/source", json={"tender_id": tender_id}, headers=headers)
                assert pursuit.status_code in (200, 201), pursuit.text

            class RecordedApi:
                organization_id = created["organization_id"]

                def call(self, method: str, path: str, payload: dict | None = None):
                    return responses[(method, path)]

            analysis_smoke.assert_dedicated_test_organization(RecordedApi(), "Plasma Smoke Test")
            with pytest.raises(analysis_smoke.LiveSmokeError, match="display name"):
                analysis_smoke.assert_dedicated_test_organization(RecordedApi(), "Some Customer")

            # A second active member makes the organization unusable for the smoke.
            async with sessions() as db:
                db.add(Membership(
                    organization_id=created["organization_id"], user_id=ids["user_b"],
                    role=MembershipRole.MEMBER, state=MembershipState.ACTIVE, activated_at=datetime.now(UTC),
                ))
                await db.commit()
            async with sessions() as db:
                with pytest.raises(smoke_account.SmokeAccountError, match="exactly one"):
                    await smoke_account.smoke_token(db)
            async with sessions() as db:
                with pytest.raises(smoke_account.SmokeAccountError, match="exactly one"):
                    await smoke_account.ensure_smoke_account(db, apply=True)

            # An e-mail that belongs to a real (Google) account is never adopted.
            async with sessions() as db:
                customer = await db.get(User, ids["user_a"])
                with pytest.raises(smoke_account.SmokeAccountError, match="did not create"):
                    await smoke_account.ensure_smoke_account(db, email=customer.email, apply=True)

    asyncio.run(scenario())


def test_cli_requires_confirmation_and_bounds_the_token_lifetime(capsys) -> None:
    assert asyncio.run(smoke_account.main(["ensure", "--apply"])) == 2
    assert "CREATE_SMOKE_ACCOUNT" in capsys.readouterr().err
    assert asyncio.run(smoke_account.main(["token", "--minutes", "0"])) == 2
    assert asyncio.run(smoke_account.main(["token", "--minutes", "481"])) == 2
