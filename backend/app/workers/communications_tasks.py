"""At-least-once communications jobs, backed by durable database work state."""

import asyncio
from datetime import timedelta
import logging
from uuid import UUID

from sqlalchemy import select

from app.core.celery_app import celery_app
from app.db.session import AsyncSessionLocal, engine
from app.models.communications import Broadcast
from app.services.broadcasts import (
    deliver_broadcast_batch,
    record_batch_failure,
    utcnow,
)
from app.services.notifications import publish_outbox_batch

logger = logging.getLogger(__name__)


async def _publish_outbox():
    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                return await publish_outbox_batch(db)
    finally:
        await engine.dispose()


@celery_app.task(
    bind=True,
    name="app.workers.communications_tasks.publish_notifications",
    max_retries=5,
    acks_late=True,
)
def publish_notifications(self):
    try:
        return asyncio.run(_publish_outbox())
    except Exception as exc:
        logger.warning(
            "notification_publication_retry error_type=%s", type(exc).__name__
        )
        # Unpublished intents survive retry exhaustion; the next Beat tick retries.
        raise self.retry(countdown=30) from None


async def _deliver(broadcast_id):
    try:
        async with AsyncSessionLocal() as db:
            try:
                async with db.begin():
                    return await deliver_broadcast_batch(db, broadcast_id)
            except Exception as exc:
                logger.warning(
                    "broadcast_batch_retry broadcast_id=%s error_type=%s",
                    broadcast_id,
                    type(exc).__name__,
                )
                async with db.begin():
                    await record_batch_failure(db, broadcast_id)
                return {"retry_scheduled": True}
    finally:
        await engine.dispose()


@celery_app.task(
    bind=True,
    name="app.workers.communications_tasks.deliver_broadcast",
    max_retries=5,
    acks_late=True,
)
def deliver_broadcast(self, broadcast_id):
    try:
        return asyncio.run(_deliver(UUID(broadcast_id)))
    except Exception as exc:
        logger.warning("broadcast_worker_retry error_type=%s", type(exc).__name__)
        raise self.retry(countdown=30) from None


async def dispatch_pending():
    """Lease at most 25 durable jobs; failed/lost publication expires in 60s."""
    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                jobs = (
                    await db.scalars(
                        select(Broadcast)
                        .where(
                            Broadcast.status.in_(["QUEUED", "SENDING"]),
                            Broadcast.next_dispatch_at <= utcnow(),
                        )
                        .order_by(Broadcast.next_dispatch_at, Broadcast.id)
                        .limit(25)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
                ids = [str(b.id) for b in jobs]
                for b in jobs:
                    b.next_dispatch_at = utcnow() + timedelta(seconds=60)
        published = 0
        for broadcast_id in ids:
            try:
                deliver_broadcast.apply_async(args=[broadcast_id])
                published += 1
            except Exception as exc:
                logger.warning(
                    "broadcast_dispatch_retry broadcast_id=%s error_type=%s",
                    broadcast_id,
                    type(exc).__name__,
                )
        return {"leased": len(ids), "published": published}
    finally:
        await engine.dispose()


@celery_app.task(name="app.workers.communications_tasks.dispatch_broadcasts")
def dispatch_broadcasts():
    return asyncio.run(dispatch_pending())


# ---- R3 Task 4: SMTP e-mail channel ----------------------------------------------------------------


async def _send_emails():
    from app.services.email_notifications import send_due_emails

    try:
        async with AsyncSessionLocal() as db:
            return await send_due_emails(db)
    finally:
        await engine.dispose()


@celery_app.task(name="app.workers.communications_tasks.send_emails")
def send_emails():
    return asyncio.run(_send_emails())


async def _stage_digests():
    from app.services.email_notifications import stage_daily_digests

    try:
        async with AsyncSessionLocal() as db:
            staged = await stage_daily_digests(db)
            await db.commit()
            return {"staged": staged}
    finally:
        await engine.dispose()


@celery_app.task(name="app.workers.communications_tasks.stage_daily_digests")
def stage_daily_digests_task():
    return asyncio.run(_stage_digests())
