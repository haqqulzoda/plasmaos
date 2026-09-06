"""Small read-only dependency and queue diagnostics; never dispatches work."""
import asyncio
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy import func, select, text

from app.api.deps import require_admin
from app.db.session import engine, get_db
from app.models.all_models import Project, SourceRefreshJob

router = APIRouter()


def redis_client():
    return Redis.from_url(os.environ.get("AUTH_REPLAY_REDIS_URL", "redis://127.0.0.1:6379/0"),
                          socket_connect_timeout=2, socket_timeout=2)


async def dependency_status():
    async def database():
        try:
            async with asyncio.timeout(2), engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
    async def redis():
        try:
            async with asyncio.timeout(2), redis_client() as client:
                return bool(await client.ping())
        except Exception:
            return False
    db_ok, redis_ok = await asyncio.gather(database(), redis())
    return {"database": db_ok, "redis": redis_ok}


@router.get("/health/ready")
async def readiness():
    from fastapi.responses import JSONResponse
    dependencies = await dependency_status()
    ready = all(dependencies.values())
    return JSONResponse({"ready": ready, "dependencies": dependencies}, status_code=200 if ready else 503)


@router.get("/api/v1/admin/operations", dependencies=[Depends(require_admin)])
async def operations(db=Depends(get_db)):
    try:
        async with asyncio.timeout(5):
            # Fixed projection and sample bound; never returns job options/messages.
            jobs = (await db.execute(select(SourceRefreshJob.status, SourceRefreshJob.created_at,
                SourceRefreshJob.retryable).order_by(SourceRefreshJob.created_at.desc(), SourceRefreshJob.id).limit(100))).all()
            oldest = await db.scalar(select(func.min(SourceRefreshJob.created_at)).where(SourceRefreshJob.status == "queued"))
            wb = (await db.execute(select(Project.enrichment_status, func.count()).where(
                Project.source_system == "world_bank").group_by(Project.enrichment_status))).all()
            async with redis_client() as client:
                queues = {name: await client.llen(name) for name in ("celery", "ai_fast_queue", "heavy_dl_queue")}
    except Exception:
        raise HTTPException(503, detail="Operational diagnostics temporarily unavailable") from None
    return {"queues": queues, "oldest_source_queue_age_seconds":
            max(0, int((datetime.now(timezone.utc) - oldest).total_seconds())) if oldest else None,
            "recent_source_sample_size": len(jobs), "recent_source_failures": sum(row.status == "failed" for row in jobs),
            "recent_source_retryable": sum(row.retryable is True for row in jobs),
            "world_bank_enrichment": {row[0]: row[1] for row in wb}}
