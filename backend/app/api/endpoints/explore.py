"""P1: the Explore view (organizations that have not started a pilot yet).

Explore sees the opportunities feed and coverage (the explorer and source-catalog endpoints)
plus one guided demo analysis served here: a fixed, curated walkthrough of a real public
notice analysed for a fictional firm. It never reads another organization's data. The two
calls to action (book a call, start a pilot) alert the Plasma team.
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_explore_access
from app.core import rate_limit
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.services.admin_alerts import kick_admin_alerts, stage_admin_alert
from app.services.organization_context import organization_profile_context

router = APIRouter()

DEMO_PATH = Path(__file__).resolve().parents[2] / "services" / "explore_demo_analysis.json"
REQUEST_LIMIT_PER_DAY = 5


class ExploreOverview(BaseModel):
    organization_name: str | None = None
    organization_access_state: str | None = None
    book_call_url: str | None = None
    demo_available: bool


class ExploreRequest(BaseModel):
    request: Literal["pilot", "call"]
    message: str | None = Field(default=None, max_length=1000)
    phone: str | None = Field(default=None, max_length=40)


class ExploreRequestAccepted(BaseModel):
    status: str = "received"


@lru_cache(maxsize=1)
def demo_analysis() -> dict[str, Any] | None:
    try:
        data = json.loads(DEMO_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    required = {"tender", "firm", "steps"}
    return data if isinstance(data, dict) and required <= set(data) else None


def _book_call_url() -> str | None:
    value = (settings.PUBLIC_BOOK_CALL_URL or "").strip()
    return value if value.startswith("https://") else None


@router.get("/overview", response_model=ExploreOverview)
async def explore_overview(
    current_user: User = Depends(require_explore_access),
    db: AsyncSession = Depends(get_db),
) -> ExploreOverview:
    context = await organization_profile_context(db, user_id=current_user.id)
    return ExploreOverview(
        organization_name=context.organization.display_name if context is not None else None,
        organization_access_state=context.organization.access_state if context is not None else None,
        book_call_url=_book_call_url(),
        demo_available=demo_analysis() is not None,
    )


@router.get("/demo-analysis")
async def explore_demo_analysis(
    response: Response,
    _current_user: User = Depends(require_explore_access),
) -> dict[str, Any]:
    data = demo_analysis()
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Demo analysis unavailable")
    response.headers["Cache-Control"] = "private, max-age=300"
    return data


@router.post("/requests", response_model=ExploreRequestAccepted, status_code=status.HTTP_202_ACCEPTED)
async def explore_request(
    payload: ExploreRequest,
    current_user: User = Depends(require_explore_access),
    db: AsyncSession = Depends(get_db),
) -> ExploreRequestAccepted:
    """Book a call or start a pilot: one alert to the Plasma team (Telegram, else e-mail)."""
    retry_after = await rate_limit.hit(
        "explore_request", str(current_user.id), limit=REQUEST_LIMIT_PER_DAY, window_seconds=86400,
    )
    if retry_after is not None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests",
                            headers={"Retry-After": str(retry_after)})
    context = await organization_profile_context(db, user_id=current_user.id)
    from datetime import datetime, timezone
    from uuid import uuid4

    await stage_admin_alert(
        db, kind="PILOT_REQUEST", dedupe_key=f"admin-alert:request:{current_user.id}:{uuid4()}",
        payload={
            "request": payload.request, "email": current_user.email, "name": current_user.name,
            "organization_name": context.organization.display_name if context is not None else None,
            "organization_id": str(context.organization.id) if context is not None else None,
            "message": (payload.message or "").strip()[:1000] or None,
            "phone": (payload.phone or "").strip()[:40] or None,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    await db.commit()
    kick_admin_alerts()
    return ExploreRequestAccepted()
