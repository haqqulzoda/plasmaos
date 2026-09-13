#!/usr/bin/env python3
"""Exercise real Celery transport on an explicitly disposable local Redis broker."""

import asyncio
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.celery_app import celery_app
from app.models.all_models import User
from app.models.communications import Broadcast, NotificationOutbox
from app.schemas.communications import BroadcastCreate
from app.services.broadcasts import create_broadcast, queue_broadcast
from app.workers.communications_tasks import (
    dispatch_broadcasts,
    deliver_broadcast,
    publish_notifications,
)
from scripts import test_s0_5b4_baseline as support
from scripts.release_test_target import assert_local_test_target

OUT = Path(__file__).resolve().parents[2] / "docs/audits/s10_5"


async def main():
    assert_local_test_target()
    # This smoke test intentionally consumes the default queue. Require a
    # dedicated broker URL rather than risking consumption of application jobs.
    import os

    broker = os.environ.get("PLASMA_COMMUNICATIONS_TEST_BROKER")
    from urllib.parse import urlsplit

    parsed = urlsplit(broker or "")
    if parsed.scheme != "redis" or parsed.hostname not in ("127.0.0.1", "localhost"):
        raise RuntimeError(
            "Set PLASMA_COMMUNICATIONS_TEST_BROKER to disposable local Redis"
        )
    os.environ["CELERY_BROKER_URL"] = broker
    os.environ["CELERY_RESULT_BACKEND"] = broker
    celery_app.conf.broker_url = broker
    celery_app.conf.result_backend = broker
    name = support.database_name("s105_celery")
    await support.create_database(name)
    worker = engine = None
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        bootstrap = await asyncio.to_thread(support.run_bootstrap, name)
        assert bootstrap.returncode == 0, bootstrap.stderr[-1000:]
        engine = create_async_engine(support.target_url(name), poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db, db.begin():
            uid = uuid4()
            actor = User(
                id=uid,
                google_id=str(uid),
                email=f"{uid}@fixture.invalid",
                name="Synthetic worker admin",
                approval_status="approved",
                platform_role="admin",
                is_admin=True,
            )
            db.add(actor)
            await db.flush()
            db.add(
                NotificationOutbox(
                    user_id=uid,
                    dedupe_key=f"worker-smoke:{uid}",
                    event_type="ACCOUNT_APPROVED",
                    category="SYSTEM",
                    template_key="notifications.account_approved",
                    payload={"approval_event_id": str(uuid4())},
                )
            )
            broadcast = await create_broadcast(
                db,
                actor,
                BroadcastCreate(
                    subject="Synthetic transport proof", body="Plain text worker proof."
                ),
            )
            await queue_broadcast(db, actor, broadcast.id)
            broadcast_id = broadcast.id
        env = support.environment(name)
        env.update(CELERY_BROKER_URL=broker, CELERY_RESULT_BACKEND=broker)
        with (OUT / "celery-worker.log").open("w") as log:
            worker = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "celery",
                    "-A",
                    "app.core.celery_app:celery_app",
                    "worker",
                    "--pool=solo",
                    "--concurrency=1",
                    "--queues=celery",
                    "--loglevel=WARNING",
                    "--without-mingle",
                    "--without-gossip",
                    "--without-heartbeat",
                ],
                cwd=support.BACKEND_DIR,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            published = await asyncio.to_thread(
                publish_notifications.delay().get, timeout=45
            )
            assert published == 1, published
            dispatched = await asyncio.to_thread(
                dispatch_broadcasts.delay().get, timeout=30
            )
            assert dispatched == {"leased": 1, "published": 1}, dispatched
            # FIFO solo worker executes the dispatched delivery before this replay.
            replay = await asyncio.to_thread(
                deliver_broadcast.delay(str(broadcast_id)).get, timeout=30
            )
            assert replay == {"processed": 0}, replay
            assert (
                await asyncio.to_thread(publish_notifications.delay().get, timeout=30)
                == 0
            )
            async with sessions() as db:
                current = await db.scalar(
                    select(Broadcast).where(Broadcast.id == broadcast_id)
                )
                assert (
                    current.status,
                    current.recipient_count,
                    current.delivered_count,
                    current.failed_count,
                ) == ("SENT", 1, 1, 0)
            result = {
                "status": "passed",
                "transport": "real Redis + Celery solo worker",
                "outbox_published": published,
                "dispatch": dispatched,
                "broadcast": "SENT",
                "replay": replay,
                "publication_replay": 0,
            }
            (OUT / "celery-proof.json").write_text(json.dumps(result, indent=2) + "\n")
            print("Real Redis/Celery publication, dispatch, delivery and replay PASS")
    finally:
        if worker:
            worker.terminate()
            try:
                await asyncio.to_thread(worker.wait, timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill()
                await asyncio.to_thread(worker.wait)
        if engine:
            await engine.dispose()
        await support.drop_database(name)


if __name__ == "__main__":
    asyncio.run(main())
