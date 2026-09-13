"""Account-scoped inbox and effective-admin broadcast APIs; no UI routes."""

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_approved_user
from app.db.session import get_db
from app.models.all_models import User
from app.schemas.communications import (
    BroadcastCreate,
    BroadcastPatch,
    BroadcastItem,
    BroadcastPage,
    BroadcastStatus,
    Category,
    DeliveryPatch,
    NotificationPage,
    TestSendRequest,
)
from app.services import broadcasts, notifications

logger = logging.getLogger(__name__)


class CommunicationsRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except notifications.CommunicationsError as exc:
                return JSONResponse(
                    status_code=exc.status_code, content={"detail": {"code": exc.code}}
                )
            except RequestValidationError:
                return JSONResponse(
                    status_code=422,
                    content={"detail": {"code": "communications_invalid_request"}},
                )
            except SQLAlchemyError as exc:
                logger.warning(
                    "communications_database_unavailable error_type=%s",
                    type(exc).__name__,
                )
                return JSONResponse(
                    status_code=503,
                    content={"detail": {"code": "communications_unavailable"}},
                )
            except HTTPException:
                raise
            except Exception as exc:
                logger.error(
                    "communications_internal_error error_type=%s", type(exc).__name__
                )
                return JSONResponse(
                    status_code=500,
                    content={"detail": {"code": "communications_internal_error"}},
                )

        return safe_handler


notifications_router = APIRouter(route_class=CommunicationsRoute)
broadcasts_router = APIRouter(route_class=CommunicationsRoute)


@notifications_router.get("", response_model=NotificationPage)
async def inbox(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1024),
    unread: bool | None = None,
    category: Category | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_approved_user),
):
    return await notifications.list_notifications(
        db,
        user.id,
        limit=limit,
        cursor=cursor,
        unread=unread,
        category=category.value if category else None,
    )


@notifications_router.get("/unread-count")
async def unread_total(
    category: Category | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_approved_user),
):
    return {
        "unread_count": await notifications.unread_count(
            db, user.id, category.value if category else None
        )
    }


@notifications_router.post("/mark-all-read")
async def read_all(
    db: AsyncSession = Depends(get_db), user: User = Depends(require_approved_user)
):
    result = await notifications.mark_all_read(db, user.id)
    await db.commit()
    return result


@notifications_router.patch("/{delivery_id}")
async def read_delivery(
    delivery_id: UUID,
    payload: DeliveryPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_approved_user),
):
    result = await notifications.set_read(db, user.id, delivery_id, payload.is_read)
    await db.commit()
    return result


@broadcasts_router.get("", response_model=BroadcastPage)
async def broadcast_list(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1024),
    status: BroadcastStatus | None = None,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin),
):
    return await broadcasts.list_broadcasts(
        db, limit=limit, cursor=cursor, status=status.value if status else None
    )


@broadcasts_router.post("", response_model=BroadcastItem, status_code=201)
async def broadcast_create(
    payload: BroadcastCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin),
):
    b = await broadcasts.create_broadcast(db, actor, payload)
    await db.commit()
    return broadcasts.broadcast_item(b)


@broadcasts_router.get("/{broadcast_id}", response_model=BroadcastItem)
async def broadcast_detail(
    broadcast_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin),
):
    return broadcasts.broadcast_item(await broadcasts.get_broadcast(db, broadcast_id))


@broadcasts_router.patch("/{broadcast_id}", response_model=BroadcastItem)
async def broadcast_update(
    broadcast_id: UUID,
    payload: BroadcastPatch,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin),
):
    b = await broadcasts.patch_broadcast(db, actor, broadcast_id, payload)
    await db.commit()
    return broadcasts.broadcast_item(b)


@broadcasts_router.post("/{broadcast_id}/audience-preview")
async def preview(
    broadcast_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin),
):
    return await broadcasts.audience_preview(db, broadcast_id)


@broadcasts_router.post("/{broadcast_id}/send-test")
async def test_send(
    broadcast_id: UUID,
    payload: TestSendRequest | None = None,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin),
):
    result = await broadcasts.send_test(
        db, actor, broadcast_id, payload.request_id if payload else uuid4()
    )
    await db.commit()
    return result


@broadcasts_router.post(
    "/{broadcast_id}/send", response_model=BroadcastItem, status_code=202
)
async def final_send(
    broadcast_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin),
):
    b = await broadcasts.queue_broadcast(db, actor, broadcast_id)
    await db.commit()
    return broadcasts.broadcast_item(b)
