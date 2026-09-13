"""Draft commands, durable recipient authorization and bounded inbox fan-out."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update, func, text, tuple_
from sqlalchemy.dialects.postgresql import insert

from app.core.access import is_effective_admin
from app.models.all_models import User
from app.models.communications import (
    Broadcast,
    BroadcastRecipient,
    NotificationDelivery,
    NotificationEvent,
)
from app.schemas.communications import BroadcastCreate, BroadcastItem, BroadcastSummary
from app.services.admin_activity import record_admin_audit_event, ACTOR_SYSTEM
from app.services.notifications import CommunicationsError, encode_cursor, decode_cursor

DELIVERY_BATCH_SIZE = 500
MAX_BATCH_FAILURES = 5
TEST_SEND_LIMIT_PER_HOUR = 6


def utcnow():
    return datetime.now(timezone.utc)


async def lock_admin(db, actor):
    expected_version = actor.auth_version
    fresh = await db.scalar(
        select(User)
        .where(User.id == actor.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        fresh is None
        or not is_effective_admin(fresh)
        or fresh.auth_version != expected_version
    ):
        raise CommunicationsError("communications_admin_required", 403)
    return fresh


async def audit(db, broadcast, action, *, actor=None, metadata=None, outcome="SUCCESS"):
    # Existing ledger requires a target email. A non-PII resource sentinel is used
    # instead of persisting a recipient dump or attributing the resource to a user.
    await record_admin_audit_event(
        db,
        action=action,
        outcome=outcome,
        source="COMMUNICATIONS",
        target_user=None,
        target_email="broadcast@resource.invalid",
        target_resource_type="BROADCAST",
        target_resource_id=str(broadcast.id),
        actor_user=actor,
        actor_type="USER" if actor is not None else ACTOR_SYSTEM,
        actor_label=None if actor else "communications_worker",
        metadata=metadata,
    )


def broadcast_item(b):
    fields = {
        name: getattr(b, name)
        for name in BroadcastItem.model_fields
        if name not in ("content_format", "selected_user_count")
    }
    return BroadcastItem(**fields, selected_user_count=len(b.selected_user_ids))


async def get_broadcast(db, broadcast_id, *, lock=False):
    stmt = select(Broadcast).where(Broadcast.id == broadcast_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    b = await db.scalar(stmt)
    if b is None:
        raise CommunicationsError("broadcast_not_found", 404)
    return b


async def list_broadcasts(db, *, limit=50, cursor=None, status=None):
    scope = f"broadcasts:{status}"
    columns = [getattr(Broadcast, name) for name in BroadcastSummary.model_fields]
    stmt = select(*columns)
    if status:
        stmt = stmt.where(Broadcast.status == status)
    if cursor:
        stmt = stmt.where(
            tuple_(Broadcast.created_at, Broadcast.id) < decode_cursor(cursor, scope)
        )
    rows = (
        (
            await db.execute(
                stmt.order_by(Broadcast.created_at.desc(), Broadcast.id.desc()).limit(
                    limit + 1
                )
            )
        )
        .mappings()
        .all()
    )
    items = [BroadcastSummary(**r) for r in rows[:limit]]
    return {
        "items": items,
        "next_cursor": (
            encode_cursor(items[-1].created_at, items[-1].id, scope)
            if len(rows) > limit
            else None
        ),
    }


async def create_broadcast(db, actor, payload):
    actor = await lock_admin(db, actor)
    b = Broadcast(created_by_user_id=actor.id, **payload.model_dump(mode="json"))
    db.add(b)
    await db.flush()
    await audit(
        db,
        b,
        "BROADCAST_DRAFT_CREATED",
        actor=actor,
        metadata={"message_type": b.message_type, "audience_mode": b.audience_mode},
    )
    return b


async def patch_broadcast(db, actor, broadcast_id, payload):
    actor = await lock_admin(db, actor)
    b = await get_broadcast(db, broadcast_id, lock=True)
    if b.status != "DRAFT":
        raise CommunicationsError("broadcast_immutable", 409)
    before = {
        k: getattr(b, k)
        for k in (
            "subject",
            "body",
            "message_type",
            "audience_mode",
            "selected_user_ids",
        )
    }
    changes = payload.model_dump(mode="json", exclude_unset=True)
    merged = {**before, **changes}
    if (
        merged["audience_mode"] == "ALL_ELIGIBLE_USERS"
        and "selected_user_ids" not in changes
    ):
        merged["selected_user_ids"] = []
    try:
        validated = BroadcastCreate(**merged).model_dump(mode="json")
    except ValueError:
        raise CommunicationsError("communications_invalid_audience") from None
    changed = [key for key, value in validated.items() if value != before[key]]
    if changed:
        for key, value in validated.items():
            setattr(b, key, value)
        b.updated_at = utcnow()
        await db.flush()
        await audit(
            db,
            b,
            "BROADCAST_DRAFT_UPDATED",
            actor=actor,
            metadata={"changed_fields": changed},
        )
    return b


def eligible_users(b):
    stmt = select(User.id).where(User.approval_status == "approved")
    if b.audience_mode == "SELECTED_USERS":
        stmt = stmt.where(User.id.in_([UUID(i) for i in b.selected_user_ids]))
    return stmt


async def audience_preview(db, broadcast_id):
    b = await get_broadcast(db, broadcast_id)
    count = await db.scalar(
        select(func.count()).select_from(eligible_users(b).subquery())
    )
    return {
        "eligible_recipient_count": count,
        "audience_mode": b.audience_mode,
        "selected_user_count": len(b.selected_user_ids),
        "snapshot_frozen": b.status != "DRAFT",
        "frozen_recipient_count": b.recipient_count if b.status != "DRAFT" else None,
        "eligibility": "APPROVED_ACCOUNTS_ONLY",
    }


async def broadcast_event(db, b, *, dedupe_key, is_test=False):
    event_id = uuid4()
    await db.execute(
        insert(NotificationEvent)
        .values(
            id=event_id,
            dedupe_key=dedupe_key,
            event_type="ADMIN_BROADCAST_TEST" if is_test else "ADMIN_BROADCAST",
            category="ADMIN",
            template_key=None,
            payload={},
            broadcast_id=b.id,
            subject=b.subject,
            body=b.body,
            message_type=b.message_type,
            is_test=is_test,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    return await db.scalar(
        select(NotificationEvent.id).where(NotificationEvent.dedupe_key == dedupe_key)
    )


async def send_test(db, actor, broadcast_id, request_id):
    actor = await lock_admin(db, actor)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"broadcast-test:{actor.id}"},
    )
    b = await get_broadcast(db, broadcast_id, lock=True)
    if b.status != "DRAFT":
        raise CommunicationsError("broadcast_immutable", 409)
    key = f"broadcast-test:{actor.id}:{request_id}"
    existing = (
        await db.execute(
            select(NotificationDelivery.id, NotificationEvent.broadcast_id)
            .join(
                NotificationEvent, NotificationEvent.id == NotificationDelivery.event_id
            )
            .where(
                NotificationDelivery.user_id == actor.id,
                NotificationEvent.dedupe_key == key,
            )
        )
    ).first()
    if existing:
        if existing.broadcast_id != b.id:
            raise CommunicationsError("communications_idempotency_conflict", 409)
        return {"delivery_id": existing.id, "is_test": True}
    count = await db.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .join(NotificationEvent, NotificationEvent.id == NotificationDelivery.event_id)
        .where(
            NotificationDelivery.user_id == actor.id,
            NotificationEvent.is_test.is_(True),
            NotificationDelivery.created_at >= utcnow() - timedelta(hours=1),
        )
    )
    if count >= TEST_SEND_LIMIT_PER_HOUR:
        raise CommunicationsError("broadcast_test_rate_limited", 429)
    event_id = await broadcast_event(db, b, dedupe_key=key, is_test=True)
    delivery_id = uuid4()
    await db.execute(
        insert(NotificationDelivery).values(
            id=delivery_id, user_id=actor.id, event_id=event_id, category="ADMIN"
        )
    )
    await audit(
        db,
        b,
        "BROADCAST_TEST_SENT",
        actor=actor,
        metadata={"test_request_id": str(request_id)},
    )
    return {"delivery_id": delivery_id, "is_test": True}


async def queue_broadcast(db, actor, broadcast_id):
    actor = await lock_admin(db, actor)
    b = await get_broadcast(db, broadcast_id, lock=True)
    if b.status != "DRAFT":
        return b  # Same send identity in every subsequent state.
    b.status = "QUEUED"
    b.queued_at = utcnow()
    b.updated_at = b.queued_at
    b.next_dispatch_at = b.queued_at
    await db.flush()
    # INSERT..SELECT freezes the eligible set with one statement, without
    # Python materialization or synchronous per-user inbox fan-out.
    recipients = eligible_users(b).with_for_update(read=True)
    await db.execute(
        insert(BroadcastRecipient).from_select(
            ["broadcast_id", "user_id"],
            select(
                func.cast(str(b.id), BroadcastRecipient.broadcast_id.type),
                recipients.subquery().c.id,
            ),
            include_defaults=False,
        )
    )
    b.recipient_count = await db.scalar(
        select(func.count())
        .select_from(BroadcastRecipient)
        .where(BroadcastRecipient.broadcast_id == b.id)
    )
    if not b.recipient_count:
        raise CommunicationsError("broadcast_empty_audience", 409)
    await db.flush()
    await broadcast_event(db, b, dedupe_key=f"broadcast:{b.id}:final")
    await audit(
        db,
        b,
        "BROADCAST_SEND_AUTHORIZED",
        actor=actor,
        metadata={
            "recipient_count": b.recipient_count,
            "audience_mode": b.audience_mode,
        },
    )
    # QUEUED + next_dispatch_at is the durable job. Beat republishes if broker
    # publication or a worker is interrupted; no broker call inside this transaction.
    return b


async def deliver_broadcast_batch(db, broadcast_id):
    b = await db.scalar(
        select(Broadcast)
        .where(Broadcast.id == broadcast_id)
        .with_for_update(skip_locked=True)
    )
    if b is None or b.status not in ("QUEUED", "SENDING"):
        return {"processed": 0}
    recipients = (
        await db.execute(
            select(
                BroadcastRecipient.id, BroadcastRecipient.user_id, User.approval_status
            )
            .join(User, User.id == BroadcastRecipient.user_id)
            .where(
                BroadcastRecipient.broadcast_id == b.id,
                BroadcastRecipient.status == "PENDING",
            )
            .order_by(BroadcastRecipient.id)
            .limit(DELIVERY_BATCH_SIZE)
            .with_for_update(read=True, of=User)
        )
    ).all()
    event_id = await db.scalar(
        select(NotificationEvent.id).where(
            NotificationEvent.dedupe_key == f"broadcast:{b.id}:final"
        )
    )
    if event_id is None:
        raise CommunicationsError("broadcast_event_unavailable", 500)
    eligible = [r for r in recipients if r.approval_status == "approved"]
    ineligible = [r for r in recipients if r.approval_status != "approved"]
    if eligible:
        await db.execute(
            insert(NotificationDelivery)
            .values(
                [
                    dict(
                        id=uuid4(),
                        user_id=r.user_id,
                        event_id=event_id,
                        category="ADMIN",
                    )
                    for r in eligible
                ]
            )
            .on_conflict_do_nothing(index_elements=["user_id", "event_id"])
        )
        await db.execute(
            update(BroadcastRecipient)
            .where(
                BroadcastRecipient.id.in_([r.id for r in eligible]),
                BroadcastRecipient.status == "PENDING",
            )
            .values(status="DELIVERED", delivered_at=func.clock_timestamp())
        )
    if ineligible:
        await db.execute(
            update(BroadcastRecipient)
            .where(
                BroadcastRecipient.id.in_([r.id for r in ineligible]),
                BroadcastRecipient.status == "PENDING",
            )
            .values(status="FAILED", error_code="ACCOUNT_INELIGIBLE")
        )
    b.delivered_count += len(eligible)
    b.failed_count += len(ineligible)
    b.retry_count = 0
    b.last_error_code = None
    b.updated_at = utcnow()
    b.next_dispatch_at = utcnow()
    if b.delivered_count + b.failed_count == b.recipient_count:
        b.status = (
            "SENT"
            if b.failed_count == 0
            else ("PARTIAL" if b.delivered_count else "FAILED")
        )
        b.completed_at = utcnow()
        await audit(
            db,
            b,
            "BROADCAST_DELIVERY_TERMINAL",
            metadata={
                "status": b.status,
                "recipient_count": b.recipient_count,
                "delivered_count": b.delivered_count,
                "failed_count": b.failed_count,
            },
        )
    else:
        b.status = "SENDING"
    await db.flush()
    return {
        "processed": len(recipients),
        "status": b.status,
        "delivered_count": b.delivered_count,
        "failed_count": b.failed_count,
    }


async def record_batch_failure(db, broadcast_id):
    b = await get_broadcast(db, broadcast_id, lock=True)
    if b.status not in ("QUEUED", "SENDING"):
        return
    b.retry_count += 1
    b.last_error_code = "BROADCAST_DELIVERY_FAILED"
    b.next_dispatch_at = utcnow() + timedelta(seconds=min(300, 10 * 2**b.retry_count))
    b.updated_at = utcnow()
    if b.retry_count >= MAX_BATCH_FAILURES:
        await db.execute(
            update(BroadcastRecipient)
            .where(
                BroadcastRecipient.broadcast_id == b.id,
                BroadcastRecipient.status == "PENDING",
            )
            .values(status="FAILED", error_code="BROADCAST_DELIVERY_FAILED")
        )
        b.failed_count = b.recipient_count - b.delivered_count
        b.status = "FAILED"
        b.completed_at = utcnow()
        await audit(
            db,
            b,
            "BROADCAST_DELIVERY_TERMINAL",
            outcome="FAILED",
            metadata={
                "status": b.status,
                "recipient_count": b.recipient_count,
                "delivered_count": b.delivered_count,
                "failed_count": b.failed_count,
                "error_code": b.last_error_code,
            },
        )
