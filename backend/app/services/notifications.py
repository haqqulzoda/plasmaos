"""Canonical idempotent notification publisher and passive inbox queries."""

import base64
from datetime import datetime
import hashlib
import hmac
import json
from uuid import UUID, uuid4

from sqlalchemy import select, update, func, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.communications import (
    NotificationDelivery,
    NotificationEvent,
    NotificationOutbox,
)
from app.schemas.communications import NotificationItem

PUBLICATION_BATCH_SIZE = 500
SYSTEM_TEMPLATES = {
    "RECOMMENDATION_CREATED": (
        "TENDER_ALERT",
        "notifications.recommendation_created",
        {"recommendation_id", "tender_id"},
    ),
    "ANALYSIS_COMPLETED": (
        "SYSTEM",
        "notifications.analysis_completed",
        {"analysis_id", "analysis_version_id", "version_number", "analysis_language"},
    ),
    "ACCOUNT_APPROVED": (
        "SYSTEM",
        "notifications.account_approved",
        {"approval_event_id"},
    ),
}


class CommunicationsError(Exception):
    def __init__(self, code: str, status_code: int = 422):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def encode_cursor(created_at: datetime, row_id: UUID, scope: str) -> str:
    raw = json.dumps(
        [created_at.isoformat(), str(row_id), scope], separators=(",", ":")
    ).encode()
    signature = hmac.new(settings.SECRET_KEY.encode(), raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature + raw).decode().rstrip("=")


def decode_cursor(cursor: str, scope: str):
    try:
        if len(cursor) > 1024:
            raise ValueError()
        data = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        sig, raw = data[:32], data[32:]
        if not hmac.compare_digest(
            sig, hmac.new(settings.SECRET_KEY.encode(), raw, hashlib.sha256).digest()
        ):
            raise ValueError()
        dt, row_id, bound_scope = json.loads(raw)
        dt = datetime.fromisoformat(dt)
        if bound_scope != scope or dt.tzinfo is None:
            raise ValueError()
        return dt, UUID(row_id)
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise CommunicationsError("communications_invalid_cursor") from None


def validate_system_event(*, event_type, category, template_key, payload, dedupe_key):
    contract = SYSTEM_TEMPLATES.get(event_type)
    if (
        not contract
        or (category, template_key) != (contract[0], contract[1])
        or set(payload) != contract[2]
    ):
        raise CommunicationsError("communications_invalid_event")
    if not isinstance(dedupe_key, str) or not 1 <= len(dedupe_key) <= 200:
        raise CommunicationsError("communications_invalid_event")
    try:
        for key, value in payload.items():
            if key.endswith("_id"):
                UUID(str(value))
            elif key == "version_number":
                if type(value) is not int or value < 1:
                    raise ValueError()
            elif key == "analysis_language":
                if value not in ("en", "uz", "ru", "ar", None):
                    raise ValueError()
        if len(json.dumps(payload).encode()) > 4096:
            raise ValueError()
    except (ValueError, TypeError):
        raise CommunicationsError("communications_invalid_event") from None


async def emit_notifications(db: AsyncSession, publications: list[dict]) -> list[UUID]:
    """Stage at most 500 structured events/deliveries; caller owns the commit.

    Dedupe keys are user-scoped to prevent one user's key suppressing another's.
    Existing immutable event content wins on replay.
    """
    if len(publications) > PUBLICATION_BATCH_SIZE:
        raise CommunicationsError("communications_batch_too_large")
    if not publications:
        return []
    rows = []
    by_key = {}
    for item in publications:
        validate_system_event(
            **{
                k: item[k]
                for k in (
                    "event_type",
                    "category",
                    "template_key",
                    "payload",
                    "dedupe_key",
                )
            }
        )
        key = f"system:{item['user_id']}:{hashlib.sha256(item['dedupe_key'].encode()).hexdigest()}"
        by_key[key] = item
        rows.append(
            {
                "id": uuid4(),
                "dedupe_key": key,
                "event_type": item["event_type"],
                "category": item["category"],
                "template_key": item["template_key"],
                "payload": item["payload"],
            }
        )
    await db.execute(
        insert(NotificationEvent)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    events = (
        await db.execute(
            select(
                NotificationEvent.id,
                NotificationEvent.dedupe_key,
                NotificationEvent.category,
            ).where(NotificationEvent.dedupe_key.in_(by_key))
        )
    ).all()
    deliveries = [
        {
            "id": uuid4(),
            "user_id": by_key[e.dedupe_key]["user_id"],
            "event_id": e.id,
            "category": e.category,
        }
        for e in events
    ]
    await db.execute(
        insert(NotificationDelivery)
        .values(deliveries)
        .on_conflict_do_nothing(index_elements=["user_id", "event_id"])
    )
    return [e.id for e in events]


async def emit_notification(
    db: AsyncSession,
    *,
    user_id: UUID,
    event_type: str,
    category: str,
    template_key: str,
    payload: dict,
    dedupe_key: str,
) -> UUID:
    return (
        await emit_notifications(
            db,
            [
                dict(
                    user_id=user_id,
                    event_type=event_type,
                    category=category,
                    template_key=template_key,
                    payload=payload,
                    dedupe_key=dedupe_key,
                )
            ],
        )
    )[0]


async def publish_outbox_batch(db: AsyncSession) -> int:
    """Read only committed intents; locks/insert constraints tolerate replay."""
    rows = (
        await db.scalars(
            select(NotificationOutbox)
            .where(NotificationOutbox.published_at.is_(None))
            .order_by(NotificationOutbox.created_at, NotificationOutbox.id)
            .limit(PUBLICATION_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
    ).all()
    if not rows:
        return 0
    await emit_notifications(
        db,
        [
            {
                key: getattr(row, key)
                for key in (
                    "user_id",
                    "event_type",
                    "category",
                    "template_key",
                    "payload",
                    "dedupe_key",
                )
            }
            for row in rows
        ],
    )
    await db.execute(
        update(NotificationOutbox)
        .where(NotificationOutbox.id.in_([r.id for r in rows]))
        .values(published_at=func.clock_timestamp())
    )
    return len(rows)


def notification_item(delivery, event):
    return NotificationItem(
        id=delivery.id,
        event_id=event.id,
        category=delivery.category,
        event_type=event.event_type,
        template_key=event.template_key,
        payload=event.payload,
        subject=event.subject,
        body=event.body,
        message_type=event.message_type,
        is_test=event.is_test,
        created_at=delivery.created_at,
        read_at=delivery.read_at,
        is_read=delivery.read_at is not None,
    )


async def list_notifications(
    db, user_id, *, limit=50, cursor=None, unread=None, category=None
):
    scope = f"inbox:{user_id}:{unread}:{category}"
    stmt = (
        select(NotificationDelivery, NotificationEvent)
        .join(NotificationEvent, NotificationEvent.id == NotificationDelivery.event_id)
        .where(NotificationDelivery.user_id == user_id)
    )
    if category:
        stmt = stmt.where(NotificationDelivery.category == category)
    if unread is not None:
        stmt = stmt.where(
            NotificationDelivery.read_at.is_(None)
            if unread
            else NotificationDelivery.read_at.is_not(None)
        )
    if cursor:
        stmt = stmt.where(
            tuple_(NotificationDelivery.created_at, NotificationDelivery.id)
            < decode_cursor(cursor, scope)
        )
    rows = (
        await db.execute(
            stmt.order_by(
                NotificationDelivery.created_at.desc(), NotificationDelivery.id.desc()
            ).limit(limit + 1)
        )
    ).all()
    items = [notification_item(d, e) for d, e in rows[:limit]]
    return {
        "items": items,
        "next_cursor": (
            encode_cursor(items[-1].created_at, items[-1].id, scope)
            if len(rows) > limit
            else None
        ),
    }


async def unread_count(db, user_id, category=None):
    stmt = (
        select(func.count())
        .select_from(NotificationDelivery)
        .where(
            NotificationDelivery.user_id == user_id,
            NotificationDelivery.read_at.is_(None),
        )
    )
    if category:
        stmt = stmt.where(NotificationDelivery.category == category)
    return await db.scalar(stmt)


async def set_read(db, user_id, delivery_id, is_read):
    row = (
        await db.execute(
            update(NotificationDelivery)
            .where(
                NotificationDelivery.id == delivery_id,
                NotificationDelivery.user_id == user_id,
            )
            .values(
                read_at=(
                    func.coalesce(NotificationDelivery.read_at, func.clock_timestamp())
                    if is_read
                    else None
                )
            )
            .returning(NotificationDelivery.id, NotificationDelivery.read_at)
        )
    ).first()
    if row is None:
        raise CommunicationsError("notification_not_found", 404)
    return {"id": row.id, "is_read": row.read_at is not None, "read_at": row.read_at}


async def mark_all_read(db, user_id):
    result = await db.execute(
        update(NotificationDelivery)
        .where(
            NotificationDelivery.user_id == user_id,
            NotificationDelivery.read_at.is_(None),
        )
        .values(read_at=func.clock_timestamp())
    )
    return {"updated_count": result.rowcount}
