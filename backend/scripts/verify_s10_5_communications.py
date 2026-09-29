#!/usr/bin/env python3
"""Disposable migration paths, indexed inbox scale, and 10k-recipient batch proof."""

import asyncio
import json
from pathlib import Path
import sys
import time
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import event, select, text, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from app.models.all_models import User
from app.models.communications import (
    Broadcast,
    NotificationDelivery,
    BroadcastRecipient,
)
from app.schemas.communications import BroadcastCreate
from app.services import broadcasts as b, notifications as n
from scripts import test_s0_5b4_baseline as support
from scripts.release_test_target import assert_local_test_target

HEAD = "20261003_0001_d1_03_official_notice_unique"
PREVIOUS = "20260904_0001_s8_2_analysis_language"
OUT = Path(__file__).resolve().parents[2] / "docs/audits/s10_5"


async def migrations():
    name = support.database_name("s105_migrations")
    await support.create_database(name)
    evidence = []
    try:
        r = await asyncio.to_thread(support.run_bootstrap, name)
        assert r.returncode == 0, r.stderr[-1500:]
        evidence.append("fresh bootstrap")
        for args in [
            ("downgrade", PREVIOUS),
            ("upgrade", HEAD),
            ("current",),
            ("heads",),
            ("check",),
        ]:
            r = await asyncio.to_thread(support.alembic, name, *args)
            assert r.returncode == 0, (args, r.stderr[-1500:])
            if args[0] in ("current", "heads"):
                assert r.stdout.count(HEAD) == 1, r.stdout
            evidence.append(" ".join(args))
        # Non-empty previous-head upgrade preserves existing account rows.
        await asyncio.to_thread(support.alembic, name, "downgrade", PREVIOUS)
        c = await support.database_connection(name)
        uid = uuid4()
        await c.execute(
            "INSERT INTO users(id,google_id,email,name,subscription_tier,is_admin,approval_status,platform_role) VALUES($1,$2,$3,'Preserved','SCOUT',false,'approved','pilot_user')",
            uid,
            str(uid),
            f"{uid}@fixture.invalid",
        )
        await c.close()
        r = await asyncio.to_thread(support.alembic, name, "upgrade", HEAD)
        assert r.returncode == 0, r.stderr[-1500:]
        c = await support.database_connection(name)
        assert (
            await c.fetchval("SELECT name FROM users WHERE id=$1", uid) == "Preserved"
        )
        assert await c.fetchval("SELECT count(*) FROM notification_outbox") == 0
        await c.close()
        evidence.append("nonempty previous-head upgrade; no historical publication")
        import subprocess

        r = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "scripts/run_s0_3_schema_data_preflight.py", "--compact"],
            cwd=support.BACKEND_DIR,
            env=support.environment(name),
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr[-1500:]
        evidence.append("schema preflight")
        return {"status": "passed", "head": HEAD, "paths": evidence}
    finally:
        await support.drop_database(name)


async def scale():
    name = support.database_name("s105_scale")
    await support.create_database(name)
    engine = None
    try:
        r = await asyncio.to_thread(support.run_bootstrap, name)
        assert r.returncode == 0, r.stderr[-1000:]
        c = await support.database_connection(name)
        actor_id = uuid4()
        tag = uuid4().hex
        await c.execute(
            "INSERT INTO users(id,google_id,email,name,subscription_tier,is_admin,approval_status,platform_role) VALUES($1,$2,$3,'Synthetic admin','SCOUT',true,'approved','admin')",
            actor_id,
            str(actor_id),
            f"{actor_id}@fixture.invalid",
        )
        await c.execute(
            "INSERT INTO users(id,google_id,email,name,subscription_tier,is_admin,approval_status,platform_role) SELECT gen_random_uuid(),$1||i::text,$1||i::text||'@fixture.invalid','Synthetic','SCOUT',false,'approved','pilot_user' FROM generate_series(1,9999) i",
            tag,
        )
        await c.execute(
            "INSERT INTO users(id,google_id,email,name,subscription_tier,is_admin,approval_status,platform_role) SELECT gen_random_uuid(),'ineligible-'||$1||i::text,'ineligible-'||$1||i::text||'@fixture.invalid','Synthetic','SCOUT',false,CASE WHEN i%3=0 THEN 'pending' WHEN i%3=1 THEN 'disabled' ELSE 'rejected' END,'pilot_user' FROM generate_series(1,99) i",
            tag,
        )
        owner_id = await c.fetchval(
            "SELECT id FROM users WHERE id<>$1 AND approval_status='approved' LIMIT 1",
            actor_id,
        )
        engine = create_async_engine(support.target_url(name), poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        statements = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", record)
        inbox = []
        for start, size in [(0, 1000), (1000, 10000), (10000, 100000)]:
            await c.execute(
                "INSERT INTO notification_events(id,dedupe_key,event_type,category,template_key,payload) SELECT gen_random_uuid(),'inbox:'||i::text,'ACCOUNT_APPROVED','SYSTEM','notifications.account_approved',jsonb_build_object('approval_event_id',gen_random_uuid()) FROM generate_series($1::int,$2::int) i",
                start + 1,
                size,
            )
            await c.execute(
                "INSERT INTO notification_deliveries(id,user_id,event_id,category) SELECT gen_random_uuid(),$1,e.id,'SYSTEM' FROM notification_events e WHERE NOT EXISTS(SELECT 1 FROM notification_deliveries d WHERE d.user_id=$1 AND d.event_id=e.id)",
                owner_id,
            )
            await c.execute("VACUUM (ANALYZE) notification_deliveries")
            await c.execute("ANALYZE notification_events")
            statements.clear()
            before = time.perf_counter()
            async with sessions() as db:
                page = await n.list_notifications(
                    db, owner_id, limit=50, unread=True, category="SYSTEM"
                )
                count = await n.unread_count(db, owner_id)
            ms = round((time.perf_counter() - before) * 1000, 2)
            assert len(page["items"]) == 50 and count == size and len(statements) == 2
            plans = {}
            for key, sql in [
                (
                    "inbox",
                    "SELECT id,event_id FROM notification_deliveries WHERE user_id=$1 AND read_at IS NULL AND category='SYSTEM' ORDER BY created_at DESC,id DESC LIMIT 51",
                ),
                (
                    "unread_count",
                    "SELECT count(*) FROM notification_deliveries WHERE user_id=$1 AND read_at IS NULL",
                ),
            ]:
                plans[key] = json.loads(
                    await c.fetchval(
                        "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + sql, owner_id
                    )
                )
            inbox.append(
                {
                    "deliveries": size,
                    "query_count": len(statements),
                    "rows_returned": 50,
                    "unread_count": count,
                    "elapsed_ms": ms,
                    "plans": plans,
                }
            )
        # 100k read-state changes use one bulk UPDATE, not per-delivery requests.
        statements.clear()
        async with sessions.begin() as db:
            marked = await n.mark_all_read(db, owner_id)
        assert marked["updated_count"] == 100000 and len(statements) == 1
        statements.clear()
        before = time.perf_counter()
        async with sessions.begin() as db:
            actor = await db.get(User, actor_id)
            draft = await b.create_broadcast(
                db,
                actor,
                BroadcastCreate(
                    subject="10k synthetic scale", body="Authored plain text."
                ),
            )
            bid = draft.id
        async with sessions.begin() as db:
            actor = await db.get(User, actor_id)
            queued = await b.queue_broadcast(db, actor, bid)
            assert queued.recipient_count == 10000
        send_queries = len(statements)
        queue_ms = round((time.perf_counter() - before) * 1000, 2)
        assert (
            await c.fetchval(
                "SELECT count(*) FROM notification_deliveries d JOIN notification_events e ON e.id=d.event_id WHERE e.broadcast_id=$1",
                bid,
            )
            == 0
        )
        batches = []
        before = time.perf_counter()
        while True:
            statements.clear()
            async with sessions.begin() as db:
                result = await b.deliver_broadcast_batch(db, bid)
            batches.append({**result, "queries": len(statements)})
            assert result["processed"] <= 500 and len(statements) <= 10, batches[-1]
            if result["status"] == "SENT":
                break
            assert len(batches) <= 20
        elapsed = round((time.perf_counter() - before) * 1000, 2)
        async with sessions.begin() as db:
            assert (await b.deliver_broadcast_batch(db, bid))["processed"] == 0
        count = await c.fetchval(
            "SELECT count(*) FROM notification_deliveries d JOIN notification_events e ON e.id=d.event_id WHERE e.broadcast_id=$1",
            bid,
        )
        distinct = await c.fetchval(
            "SELECT count(DISTINCT user_id) FROM broadcast_recipients WHERE broadcast_id=$1",
            bid,
        )
        assert count == distinct == 10000 and len(batches) == 20
        await c.close()
        return {
            "status": "passed",
            "inbox": inbox,
            "mark_all_read": {"updated": 100000, "queries": 1},
            "broadcast": {
                "eligible": 10000,
                "excluded": 99,
                "deliveries": count,
                "distinct_recipients": distinct,
                "status": "SENT",
                "queue_and_create_queries": send_queries,
                "queue_and_create_ms": queue_ms,
                "delivery_ms": elapsed,
                "batch_size": 500,
                "batches": batches,
                "replay_new_deliveries": 0,
            },
            "note": "Loopback PostgreSQL 16, disposable synthetic rows; timings are environment-specific. COUNT scans unread index entries, not constant-time.",
        }
    finally:
        if engine:
            await engine.dispose()
        await support.drop_database(name)


async def main():
    assert_local_test_target()
    OUT.mkdir(parents=True, exist_ok=True)
    migration = await migrations()
    (OUT / "migration-proof.json").write_text(json.dumps(migration, indent=2) + "\n")
    print("Migration paths PASS", flush=True)
    result = await scale()
    (OUT / "scale-proof.json").write_text(json.dumps(result, indent=2) + "\n")
    print("Inbox 1k/10k/100k and broadcast 10k PASS", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
