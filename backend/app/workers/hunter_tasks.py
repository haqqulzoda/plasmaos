from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.orm import configure_mappers, selectinload

# Ensure worker process loads SQLAlchemy mappings before running tasks.
import app.models  # noqa: F401
from app.models.all_models import Tender
from app.models.company import CompanyProfile
from app.models.taxonomy import TaxonomyNode, CompanyCredential

configure_mappers()

from app.core.agents.hunter import evaluate_tenders_batch
from app.core.celery_app import celery_app
from app.db.session import AsyncSessionLocal, engine
from app.models.audit import TenderRecommendation
from app.workers.tender_tasks import process_tender_docs

logger = logging.getLogger(__name__)

BATCH_SIZE = 25
MIN_MATCH_SCORE = 10


def _active_company_profiles_stmt():
    stmt = (
        select(CompanyProfile)
        .options(
            selectinload(CompanyProfile.certifications),
            selectinload(CompanyProfile.licenses),
            selectinload(CompanyProfile.financial_history),
        )
        .order_by(CompanyProfile.id)
    )

    is_active_column = getattr(CompanyProfile, "is_active", None)
    if is_active_column is not None:
        stmt = stmt.where(is_active_column.is_(True))

    return stmt


def _pending_tenders_stmt(profile_id: UUID, window_start: datetime):
    recommendation_exists = (
        select(1)
        .select_from(TenderRecommendation)
        .where(
            TenderRecommendation.tender_id == Tender.id,
            TenderRecommendation.company_profile_id == profile_id,
        )
    )

    return (
        select(Tender)
        .where(Tender.created_at >= window_start)
        .where(~exists(recommendation_exists))
        .order_by(Tender.created_at.desc())
    )


async def _run_hunter_sweep_async() -> dict[str, int]:
    stats = {
        "profiles_processed": 0,
        "tenders_evaluated": 0,
        "recommendations_saved": 0,
        "documents_dispatched": 0,
    }
    window_start = datetime.now(timezone.utc) - timedelta(hours=24)

    try:
        async with AsyncSessionLocal() as db:
            try:
                profiles_result = await db.execute(_active_company_profiles_stmt())
                profiles = profiles_result.scalars().all()
                dispatched_docs: set[UUID] = set()

                for profile in profiles:
                    stats["profiles_processed"] += 1

                    tenders_result = await db.execute(_pending_tenders_stmt(profile.id, window_start))
                    tenders = tenders_result.scalars().all()

                    for tender in tenders:
                        if tender.id in dispatched_docs:
                            continue

                        try:
                            process_tender_docs.delay(str(tender.id))
                            dispatched_docs.add(tender.id)
                            stats["documents_dispatched"] += 1
                        except Exception as exc:
                            logger.error(
                                "Failed to dispatch document processing for tender_id=%s: %s",
                                tender.id,
                                exc,
                            )

                    if not tenders:
                        continue

                    seen_tender_ids: set[UUID] = set()

                    for batch_start in range(0, len(tenders), BATCH_SIZE):
                        batch = tenders[batch_start : batch_start + BATCH_SIZE]
                        stats["tenders_evaluated"] += len(batch)

                        try:
                            recommendations = await evaluate_tenders_batch(
                                tenders=batch,
                                profile=profile,
                            )
                        except Exception:
                            logger.exception(
                                "Hunter evaluation failed for profile_id=%s batch_start=%s",
                                profile.id,
                                batch_start,
                            )
                            continue

                        batch_tender_ids = {tender.id for tender in batch}

                        for recommendation in recommendations:
                            score = int(recommendation["match_score"])
                            if score < MIN_MATCH_SCORE:
                                continue

                            try:
                                tender_id = UUID(str(recommendation["tender_id"]))
                            except ValueError:
                                continue

                            if tender_id not in batch_tender_ids:
                                continue
                            if tender_id in seen_tender_ids:
                                continue

                            rationale = recommendation["strategic_rationale"].strip()
                            if not rationale:
                                continue

                            db.add(
                                TenderRecommendation(
                                    tender_id=tender_id,
                                    company_profile_id=profile.id,
                                    match_score=score,
                                    strategic_rationale=rationale,
                                )
                            )
                            seen_tender_ids.add(tender_id)
                            stats["recommendations_saved"] += 1

                await db.commit()
                return stats
            except Exception:
                await db.rollback()
                raise
    finally:
        await engine.dispose()


@celery_app.task(name="app.workers.hunter_tasks.run_hunter_sweep", bind=True)
def run_hunter_sweep(self) -> dict[str, int]:
    logger.info("Starting Hunter sweep task")
    return asyncio.run(_run_hunter_sweep_async())
