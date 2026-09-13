"""Real PostgreSQL communications contracts, races, durable publication and scale."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4, UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text, func, update, event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.api.endpoints.communications import notifications_router, broadcasts_router
from app.api.endpoints import admin
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.all_models import User, Tender, AdminActivityEvent
from app.models.audit import TenderAnalysis, AnalysisVersion, TenderRecommendation
from app.models.company import CompanyProfile
from app.models.communications import (
    Broadcast,
    BroadcastRecipient,
    NotificationDelivery,
    NotificationEvent,
    NotificationOutbox,
)
from app.schemas.communications import BroadcastCreate
from app.services import notifications as n, broadcasts as b
from scripts import test_s0_5b4_baseline as support
from scripts.release_test_target import assert_local_test_target


@pytest.fixture(scope="module")
def database_url():
    assert_local_test_target()
    name = support.database_name("s105_contracts")
    asyncio.run(support.create_database(name))
    try:
        result = support.run_bootstrap(name)
        assert result.returncode == 0, result.stderr[-1500:]
        yield support.target_url(name)
    finally:
        asyncio.run(support.drop_database(name))


@asynccontextmanager
async def harness(url):
    engine = create_async_engine(url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(notifications_router, prefix="/api/v1/notifications")
    app.include_router(broadcasts_router, prefix="/api/v1/admin/broadcasts")
    app.include_router(admin.router, prefix="/api/v1/admin")

    async def dependency():
        async with sessions() as db:
            try:
                yield db
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = dependency
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://fixture.invalid"
    ) as client:
        try:
            yield sessions, client, engine
        finally:
            await engine.dispose()


async def user(sessions, *, role="pilot_user", status="approved"):
    async with sessions.begin() as db:
        u = User(
            id=uuid4(),
            google_id=str(uuid4()),
            email=f"{uuid4()}@example.invalid",
            name="Synthetic account",
            approval_status=status,
            platform_role=role,
            is_admin=role == "admin",
            auth_version=0,
        )
        db.add(u)
    return u


def headers(u, version=None):
    return {
        "Authorization": "Bearer "
        + create_access_token(
            {
                "sub": str(u.id),
                "auth_version": u.auth_version if version is None else version,
            }
        )
    }


async def make_broadcast(client, actor, recipients=None, **values):
    payload = {
        "subject": "Original عنوان — e’lon",
        "body": "Authored body\nkept verbatim.",
        "message_type": "ANNOUNCEMENT",
    }
    if recipients is not None:
        payload.update(
            audience_mode="SELECTED_USERS",
            selected_user_ids=[str(x.id) for x in recipients],
        )
    result = await client.post(
        "/api/v1/admin/broadcasts", json={**payload, **values}, headers=headers(actor)
    )
    assert result.status_code == 201, result.text
    return result.json()


def publication(u, key=None):
    return dict(
        user_id=u.id,
        event_type="RECOMMENDATION_CREATED",
        category="TENDER_ALERT",
        template_key="notifications.recommendation_created",
        payload={"recommendation_id": str(uuid4()), "tender_id": str(uuid4())},
        dedupe_key=key or str(uuid4()),
    )


def test_inbox_owned_cursor_filters_bulk_read_and_idempotent_emit(database_url):
    async def scenario():
        async with harness(database_url) as (sessions, c, _):
            a = await user(sessions)
            other = await user(sessions)
            async with sessions.begin() as db:
                first = publication(a, "stable")
                await n.emit_notification(db, **first)
                await n.emit_notification(db, **first)
                await n.emit_notifications(
                    db, [publication(a) for _ in range(60)] + [publication(other)]
                )
            path = "/api/v1/notifications"
            r = await c.get(
                path + "?limit=25&unread=true&category=TENDER_ALERT", headers=headers(a)
            )
            assert r.status_code == 200, r.text
            first_page = r.json()
            assert len(first_page["items"]) == 25 and first_page["next_cursor"]
            r = await c.get(
                path,
                params={
                    "limit": 25,
                    "unread": "true",
                    "category": "TENDER_ALERT",
                    "cursor": first_page["next_cursor"],
                },
                headers=headers(a),
            )
            second = r.json()
            assert not set(x["id"] for x in first_page["items"]) & set(
                x["id"] for x in second["items"]
            )
            assert (
                await c.get(
                    path,
                    params={"cursor": first_page["next_cursor"]},
                    headers=headers(other),
                )
            ).status_code == 422
            assert (
                await c.get(path + "?cursor=malformed", headers=headers(a))
            ).status_code == 422
            assert (
                await c.get(path + "?limit=101", headers=headers(a))
            ).status_code == 422
            assert (await c.get(path + "/unread-count", headers=headers(a))).json()[
                "unread_count"
            ] == 61
            item = first_page["items"][0]
            assert (
                item["subject"] is None
                and item["body"] is None
                and item["template_key"]
                and set(item["payload"]) == {"recommendation_id", "tender_id"}
            )
            assert (
                await c.patch(
                    path + "/" + item["id"],
                    json={"is_read": True},
                    headers=headers(other),
                )
            ).status_code == 404
            missing = (
                await c.patch(
                    path + "/" + str(uuid4()),
                    json={"is_read": True},
                    headers=headers(other),
                )
            ).json()
            foreign = (
                await c.patch(
                    path + "/" + item["id"],
                    json={"is_read": True},
                    headers=headers(other),
                )
            ).json()
            assert foreign == missing
            assert (
                await c.patch(
                    path + "/" + item["id"], json={"is_read": True}, headers=headers(a)
                )
            ).json()["is_read"]
            assert (await c.post(path + "/mark-all-read", headers=headers(a))).json()[
                "updated_count"
            ] == 60
            assert (await c.post(path + "/mark-all-read", headers=headers(a))).json()[
                "updated_count"
            ] == 0
            assert (await c.get(path + "/unread-count", headers=headers(other))).json()[
                "unread_count"
            ] == 1
            await asyncio.gather(
                *[
                    c.patch(
                        path + "/" + item["id"],
                        json={"is_read": bool(i % 2)},
                        headers=headers(a),
                    )
                    for i in range(10)
                ]
            )
            result = await c.patch(
                path + "/" + item["id"], json={"is_read": False}, headers=headers(a)
            )
            assert result.json()["read_at"] is None
            assert (await c.get(path + "/unread-count", headers=headers(a))).json()[
                "unread_count"
            ] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status,expected", [("pending", 403), ("disabled", 401), ("rejected", 401)]
)
def test_account_policy(database_url, status, expected):
    async def scenario():
        async with harness(database_url) as (sessions, c, _):
            u = await user(sessions, status=status, role="admin")
            assert (
                await c.get("/api/v1/notifications", headers=headers(u))
            ).status_code == expected
            assert (
                await c.get("/api/v1/admin/broadcasts", headers=headers(u))
            ).status_code == expected

    asyncio.run(scenario())


def test_admin_authorization_content_security_and_test_rate_limit(database_url):
    async def scenario():
        async with harness(database_url) as (sessions, c, _):
            ordinary = await user(sessions)
            actor = await user(sessions, role="admin")
            path = "/api/v1/admin/broadcasts"
            for method, tail in [
                ("GET", ""),
                ("POST", ""),
                ("GET", "/" + str(uuid4())),
                ("PATCH", "/" + str(uuid4())),
                ("POST", "/" + str(uuid4()) + "/audience-preview"),
                ("POST", "/" + str(uuid4()) + "/send-test"),
                ("POST", "/" + str(uuid4()) + "/send"),
            ]:
                r = await c.request(
                    method,
                    path + tail,
                    json=(
                        {"subject": "Title", "body": "Body"}
                        if tail == "" and method == "POST"
                        else {} if method == "PATCH" else None
                    ),
                    headers=headers(ordinary),
                )
                assert r.status_code == 403, (method, tail, r.text)
            assert (
                await c.get(path, headers=headers(actor, version=1))
            ).status_code == 401
            for bad in [
                "<script>alert(1)</script>",
                "<img src=x onerror=alert(1)>",
                "[link](javascript:alert(1))",
                "data:text/html,test",
                "onclick=bad",
            ]:
                r = await c.post(
                    path, json={"subject": "Safe", "body": bad}, headers=headers(actor)
                )
                assert r.status_code == 422
                assert bad not in r.text
            r = await c.post(
                path,
                json={"subject": "a" * 201, "body": "valid"},
                headers=headers(actor),
            )
            assert r.status_code == 422
            r = await c.post(
                path,
                json={"subject": "Safe", "body": "x" * 5001},
                headers=headers(actor),
            )
            assert r.status_code == 422
            record = await make_broadcast(c, actor, [ordinary])
            bid = record["id"]
            req = str(uuid4())
            before = (await c.get(path + "/" + bid, headers=headers(actor))).json()
            first = await c.post(
                path + "/" + bid + "/send-test",
                json={"request_id": req},
                headers=headers(actor),
            )
            assert first.status_code == 200, first.text
            repeat = await c.post(
                path + "/" + bid + "/send-test",
                json={"request_id": req},
                headers=headers(actor),
            )
            assert repeat.json() == first.json()
            for _ in range(5):
                assert (
                    await c.post(
                        path + "/" + bid + "/send-test", headers=headers(actor)
                    )
                ).status_code == 200
            assert (
                await c.post(path + "/" + bid + "/send-test", headers=headers(actor))
            ).status_code == 429
            assert (
                await c.get(path + "/" + bid, headers=headers(actor))
            ).json() == before
            async with sessions() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(BroadcastRecipient)
                        .where(BroadcastRecipient.broadcast_id == UUID(bid))
                    )
                    == 0
                )
                items = (
                    await c.get("/api/v1/notifications", headers=headers(actor))
                ).json()["items"]
                assert len(items) == 6 and all(
                    x["is_test"] and x["body"] == record["body"] for x in items
                )
                assert (
                    await c.get("/api/v1/notifications", headers=headers(ordinary))
                ).json()["items"] == []
                audits = (
                    await db.scalars(
                        select(AdminActivityEvent).where(
                            AdminActivityEvent.target_resource_id == bid
                        )
                    )
                ).all()
                assert len(audits) == 7
                assert record["body"] not in json.dumps(
                    [r.metadata_json for r in audits]
                )

    asyncio.run(scenario())


def test_concurrent_send_frozen_audience_duplicate_workers_and_retry(database_url):
    async def scenario():
        async with harness(database_url) as (sessions, c, engine):
            actor = await user(sessions, role="admin")
            a = await user(sessions)
            other = await user(sessions)
            pending = await user(sessions, status="pending")
            record = await make_broadcast(c, actor, [a, other, pending])
            bid = UUID(record["id"])
            path = f"/api/v1/admin/broadcasts/{bid}"
            async with sessions() as db:
                counts_before = [
                    await db.scalar(select(func.count()).select_from(model))
                    for model in [
                        BroadcastRecipient,
                        NotificationDelivery,
                        AdminActivityEvent,
                    ]
                ]
            preview = (
                await c.post(path + "/audience-preview", headers=headers(actor))
            ).json()
            assert preview["eligible_recipient_count"] == 2
            async with sessions() as db:
                assert counts_before == [
                    await db.scalar(select(func.count()).select_from(model))
                    for model in [
                        BroadcastRecipient,
                        NotificationDelivery,
                        AdminActivityEvent,
                    ]
                ]
            assert (
                await c.patch(
                    path, json={"subject": "Updated subject"}, headers=headers(actor)
                )
            ).status_code == 200
            sends = await asyncio.gather(
                c.post(path + "/send", headers=headers(actor)),
                c.post(path + "/send", headers=headers(actor)),
            )
            assert all(r.status_code == 202 for r in sends), [r.text for r in sends]
            assert sends[0].json() == sends[1].json()
            assert (
                sends[0].json()["recipient_count"] == 2
                and sends[0].json()["delivered_count"] == 0
            )
            assert (
                await c.patch(path, json={"body": "Changed"}, headers=headers(actor))
            ).status_code == 409
            async with sessions.begin() as db:
                await db.execute(
                    update(User)
                    .where(User.id == other.id)
                    .values(approval_status="disabled")
                )
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(BroadcastRecipient)
                        .where(BroadcastRecipient.broadcast_id == bid)
                    )
                    == 2
                )
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(NotificationDelivery)
                        .join(
                            NotificationEvent,
                            NotificationEvent.id == NotificationDelivery.event_id,
                        )
                        .where(NotificationEvent.broadcast_id == bid)
                    )
                    == 0
                )

            async def deliver():
                async with sessions.begin() as db:
                    return await b.deliver_broadcast_batch(db, bid)

            await asyncio.gather(deliver(), deliver())
            await deliver()
            final = (await c.get(path, headers=headers(actor))).json()
            assert (
                final["status"],
                final["delivered_count"],
                final["failed_count"],
            ) == ("PARTIAL", 1, 1)
            assert (
                await c.post(path + "/send", headers=headers(actor))
            ).json() == final
            async with sessions() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(NotificationDelivery)
                        .join(
                            NotificationEvent,
                            NotificationEvent.id == NotificationDelivery.event_id,
                        )
                        .where(NotificationEvent.broadcast_id == bid)
                    )
                    == 1
                )
                actions = (
                    await db.scalars(
                        select(AdminActivityEvent.action).where(
                            AdminActivityEvent.target_resource_id == str(bid)
                        )
                    )
                ).all()
                assert (
                    actions.count("BROADCAST_SEND_AUTHORIZED") == 1
                    and actions.count("BROADCAST_DELIVERY_TERMINAL") == 1
                )
            # SQL guards protect immutable content and snapshot even outside API.
            from sqlalchemy.exc import IntegrityError

            for sql in [
                "UPDATE broadcasts SET body='forbidden' WHERE id=:id",
                "UPDATE broadcasts SET delivered_count=0 WHERE id=:id",
                "DELETE FROM broadcast_recipients WHERE broadcast_id=:id",
            ]:
                async with sessions() as db:
                    with pytest.raises(IntegrityError):
                        await db.execute(text(sql), {"id": bid})
                    await db.rollback()

    asyncio.run(scenario())


def test_system_producers_only_publish_committed_durable_lifecycle_events(database_url):
    async def scenario():
        async with harness(database_url) as (sessions, c, _):
            actor = await user(sessions, role="admin")
            owner = await user(sessions)
            pending = await user(sessions, status="pending")
            async with sessions.begin() as db:
                profile = CompanyProfile(
                    id=uuid4(),
                    user_id=owner.id,
                    company_name="Synthetic",
                    approval_status="approved",
                )
                db.add(profile)
                tender = Tender(
                    id=uuid4(),
                    external_id=str(uuid4()),
                    source_system="world_bank",
                    canonical_source_key=str(uuid4()),
                    source_url="https://example.invalid/stored",
                    title="Original title",
                )
                db.add(tender)
                await db.flush()
                rec = TenderRecommendation(
                    id=uuid4(),
                    tender_id=tender.id,
                    company_profile_id=profile.id,
                    match_score=75,
                    strategic_rationale="Original rationale",
                )
                db.add(rec)
                parent = TenderAnalysis(
                    id=uuid4(),
                    tender_id=tender.id,
                    user_id=owner.id,
                    company_profile_id=profile.id,
                    ownership_state="OWNED",
                    company_name="Synthetic",
                    tender_file_name="local.txt",
                    raw_extracted_text="original",
                    analysis_json={},
                )
                db.add(parent)
                await db.flush()
                version = AnalysisVersion(
                    id=uuid4(),
                    analysis_id=parent.id,
                    version_number=1,
                    origin="RUNTIME_ANALYSIS",
                    status="COMPLETED",
                    analysis_language="en",
                    snapshot_completeness="COMPLETE",
                    tender_snapshot={},
                    company_snapshot={},
                    result_snapshot={},
                    evidence_snapshot={},
                    provenance_snapshot={},
                )
                db.add(version)
                await db.flush()
                # Separate transaction cannot see uncommitted publication intent.
                async with sessions() as other:
                    assert (
                        await other.scalar(
                            select(func.count())
                            .select_from(NotificationOutbox)
                            .where(NotificationOutbox.user_id == owner.id)
                        )
                        == 0
                    )
            async with sessions.begin() as db:
                loaded = await db.get(TenderRecommendation, rec.id)
                loaded.match_score = 80
                failed = AnalysisVersion(
                    id=uuid4(),
                    analysis_id=parent.id,
                    version_number=2,
                    supersedes_version_id=version.id,
                    origin="RUNTIME_REANALYSIS",
                    status="FAILED",
                    analysis_language="ru",
                    snapshot_completeness="PARTIAL",
                    tender_snapshot={},
                    company_snapshot={},
                    result_snapshot={},
                    evidence_snapshot={},
                    provenance_snapshot={},
                )
                db.add(failed)
            async with sessions() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(NotificationOutbox)
                        .where(NotificationOutbox.user_id == owner.id)
                    )
                    == 2
                )
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(NotificationDelivery)
                        .where(NotificationDelivery.user_id == owner.id)
                    )
                    == 0
                )
            # Actual canonical approval commits even while the downstream publisher is unavailable.
            with patch(
                "app.services.notifications.emit_notifications",
                side_effect=RuntimeError("unavailable"),
            ):
                r = await c.post(
                    f"/api/v1/admin/users/{pending.id}/approve", headers=headers(actor)
                )
                assert r.status_code == 200, r.text
                async with sessions.begin() as db:
                    with pytest.raises(RuntimeError):
                        await n.publish_outbox_batch(db)
                    await db.rollback()
            async with sessions() as db:
                assert (await db.get(User, pending.id)).approval_status == "approved"
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(NotificationOutbox)
                        .where(
                            NotificationOutbox.user_id == pending.id,
                            NotificationOutbox.published_at.is_(None),
                        )
                    )
                    == 1
                )

            async def publish():
                async with sessions.begin() as db:
                    return await n.publish_outbox_batch(db)

            await asyncio.gather(publish(), publish())
            await publish()
            async with sessions() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(NotificationDelivery)
                        .where(NotificationDelivery.user_id == owner.id)
                    )
                    == 2
                )
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(NotificationDelivery)
                        .where(NotificationDelivery.user_id == pending.id)
                    )
                    == 1
                )
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(NotificationOutbox)
                        .where(
                            NotificationOutbox.user_id == owner.id,
                            NotificationOutbox.published_at.is_(None),
                        )
                    )
                    == 0
                )
            # A rolled-back source event never reaches the outbox/inbox.
            async with sessions() as db:
                x = Tender(
                    id=uuid4(),
                    external_id=str(uuid4()),
                    source_system="world_bank",
                    canonical_source_key=str(uuid4()),
                    source_url="https://example.invalid/stored",
                    title="Rollback",
                )
                db.add(x)
                await db.flush()
                db.add(
                    TenderRecommendation(
                        id=uuid4(),
                        tender_id=x.id,
                        company_profile_id=profile.id,
                        match_score=90,
                        strategic_rationale="Rollback",
                    )
                )
                await db.flush()
                await db.rollback()
            async with sessions() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(NotificationOutbox)
                        .where(NotificationOutbox.user_id == owner.id)
                    )
                    == 2
                )

    asyncio.run(scenario())


def test_partial_batch_commit_restart_and_terminal_failure(database_url):
    async def scenario():
        async with harness(database_url) as (sessions, c, _):
            actor = await user(sessions, role="admin")
            users = [await user(sessions) for _ in range(3)]
            r = await make_broadcast(c, actor, users)
            bid = UUID(r["id"])
            path = f"/api/v1/admin/broadcasts/{bid}"
            assert (
                await c.post(path + "/send", headers=headers(actor))
            ).status_code == 202
            with patch.object(b, "DELIVERY_BATCH_SIZE", 1):
                async with sessions.begin() as db:
                    assert (await b.deliver_broadcast_batch(db, bid))[
                        "delivered_count"
                    ] == 1
                # Rollback after SQL delivery work models a crash before batch commit.
                async with sessions() as db:
                    await b.deliver_broadcast_batch(db, bid)
                    await db.rollback()
                async with sessions() as db:
                    assert (await db.get(Broadcast, bid)).delivered_count == 1
                async with sessions.begin() as db:
                    await b.deliver_broadcast_batch(db, bid)
                async with sessions.begin() as db:
                    await b.deliver_broadcast_batch(db, bid)
            assert (await c.get(path, headers=headers(actor))).json()[
                "status"
            ] == "SENT"
            r = await make_broadcast(c, actor, users)
            failed_id = UUID(r["id"])
            await c.post(
                f"/api/v1/admin/broadcasts/{failed_id}/send", headers=headers(actor)
            )
            for _ in range(5):
                async with sessions.begin() as db:
                    await b.record_batch_failure(db, failed_id)
            async with sessions() as db:
                record = await db.get(Broadcast, failed_id)
                assert record.status == "FAILED" and record.failed_count == 3
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(BroadcastRecipient)
                        .where(
                            BroadcastRecipient.broadcast_id == failed_id,
                            BroadcastRecipient.status == "PENDING",
                        )
                    )
                    == 0
                )

    asyncio.run(scenario())


def test_broker_loss_expiring_lease_and_worker_restart(database_url):
    async def scenario():
        from app.workers import communications_tasks as tasks
        from datetime import timedelta

        async with harness(database_url) as (sessions, c, engine):
            actor = await user(sessions, role="admin")
            recipient = await user(sessions)
            record = await make_broadcast(c, actor, [recipient])
            bid = UUID(record["id"])
            await c.post(f"/api/v1/admin/broadcasts/{bid}/send", headers=headers(actor))
            with patch.object(tasks, "AsyncSessionLocal", sessions), patch.object(
                tasks, "engine", engine
            ):
                with patch.object(
                    tasks.deliver_broadcast,
                    "apply_async",
                    side_effect=RuntimeError("broker unavailable"),
                ):
                    result = await tasks.dispatch_pending()
                    assert result["leased"] >= 1 and result["published"] == 0
                async with sessions.begin() as db:
                    row = await db.get(Broadcast, bid)
                    assert row.status == "QUEUED"
                    row.next_dispatch_at = b.utcnow() - timedelta(seconds=1)
                with patch.object(tasks.deliver_broadcast, "apply_async") as publish:
                    result = await tasks.dispatch_pending()
                    assert result["published"] >= 1
                    assert any(
                        call.kwargs["args"] == [str(bid)]
                        for call in publish.call_args_list
                    )
                # Execute the actual worker async entry twice with a new DB session.
                result = await tasks._deliver(bid)
                assert result["status"] == "SENT"
                assert (await tasks._deliver(bid))["processed"] == 0
            async with sessions() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(NotificationDelivery)
                        .where(NotificationDelivery.user_id == recipient.id)
                    )
                    == 1
                )

    asyncio.run(scenario())


def test_payload_registry_db_uniqueness_and_immutable_event(database_url):
    async def scenario():
        from sqlalchemy.exc import IntegrityError

        async with harness(database_url) as (sessions, c, engine):
            owner = await user(sessions)
            other = await user(sessions)
            item = publication(owner, "same-key")
            for payload in [
                {"token": "secret"},
                {"full_document": "text" * 10000},
                {"recommendation_id": "not-uuid", "tender_id": str(uuid4())},
            ]:
                async with sessions.begin() as db:
                    with pytest.raises(n.CommunicationsError):
                        await n.emit_notification(db, **{**item, "payload": payload})
            async with sessions.begin() as db:
                eid = await n.emit_notification(db, **item)
                await n.emit_notification(db, **{**item, "user_id": other.id})
            for query, args in [
                (
                    "INSERT INTO notification_deliveries(id,user_id,event_id,category) VALUES(:id,:user,:event,'TENDER_ALERT')",
                    {"id": uuid4(), "user": owner.id, "event": eid},
                ),
                (
                    "UPDATE notification_events SET payload='{}'::jsonb WHERE id=:id",
                    {"id": eid},
                ),
                (
                    "INSERT INTO notification_deliveries(id,user_id,event_id,category) VALUES(:id,:user,:event,'ADMIN')",
                    {"id": uuid4(), "user": other.id, "event": eid},
                ),
            ]:
                async with sessions() as db:
                    with pytest.raises(IntegrityError):
                        await db.execute(text(query), args)
                    await db.rollback()
            async with sessions() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(NotificationDelivery)
                        .where(NotificationDelivery.user_id.in_([owner.id, other.id]))
                    )
                    == 2
                )

    asyncio.run(scenario())
