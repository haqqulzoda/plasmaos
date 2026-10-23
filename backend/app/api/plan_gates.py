"""P3: turn a plan feature gate into the HTTP answer the frontend reads (403, code PLAN_FEATURE)."""

from __future__ import annotations

from fastapi import HTTPException

from app.services.plans import PlanFeatureError, require_feature


async def enforce_feature(db, context, feature: str):
    """The organization context, once its plan includes ``feature``."""
    try:
        await require_feature(db, context.organization, feature)
    except PlanFeatureError as exc:
        raise HTTPException(exc.status_code, detail=exc.detail()) from exc
    return context
