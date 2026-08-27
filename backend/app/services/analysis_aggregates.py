"""Cross-process resolution of one customer/tender analysis aggregate."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import CompanyProfile, TenderAnalysis
from app.models.audit import ANALYSIS_OWNERSHIP_OWNED


logger = logging.getLogger(__name__)
ANALYSIS_AGGREGATE_LOCK_NAMESPACE = "plasma:tender-analysis-aggregate:v1"


class AnalysisAggregateOwnershipError(RuntimeError):
    """Raised when a proposed aggregate does not have a valid tenant tuple."""


@dataclass(frozen=True)
class AnalysisAggregateResolution:
    analysis: TenderAnalysis
    created: bool
    existing_parent_count: int


def analysis_aggregate_identity(
    *,
    user_id: UUID,
    company_profile_id: UUID,
    tender_id: UUID,
) -> str:
    """Return the exact ID-only logical scope used for the advisory lock."""
    return ":".join(
        (
            ANALYSIS_AGGREGATE_LOCK_NAMESPACE,
            str(user_id),
            str(company_profile_id),
            str(tender_id),
        )
    )


async def resolve_or_create_analysis_aggregate(
    db: AsyncSession,
    *,
    user_id: UUID,
    company_profile_id: UUID,
    tender_id: UUID,
    new_parent: TenderAnalysis,
) -> AnalysisAggregateResolution:
    """Serialize one logical scope and resolve/create its runtime parent.

    PostgreSQL transaction-level advisory locking protects the zero-parent race
    across API processes. Historical duplicate parents remain separate; the
    existing documented newest-parent runtime rule is retained without mutating
    or merging any historical row.
    """
    if (
        new_parent.user_id != user_id
        or new_parent.company_profile_id != company_profile_id
        or new_parent.tender_id != tender_id
        or new_parent.ownership_state != ANALYSIS_OWNERSHIP_OWNED
    ):
        raise AnalysisAggregateOwnershipError(
            "new analysis parent does not match the canonical tenant/tender scope"
        )

    valid_profile = await db.scalar(
        select(CompanyProfile.id).where(
            CompanyProfile.id == company_profile_id,
            CompanyProfile.user_id == user_id,
        )
    )
    if valid_profile is None:
        raise AnalysisAggregateOwnershipError(
            "company profile is not owned by the authenticated user"
        )

    identity = analysis_aggregate_identity(
        user_id=user_id,
        company_profile_id=company_profile_id,
        tender_id=tender_id,
    )
    await db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended(:aggregate_identity, 0))"
        ),
        {"aggregate_identity": identity},
    )

    existing = list(
        (
            await db.execute(
                select(TenderAnalysis)
                .where(
                    TenderAnalysis.tender_id == tender_id,
                    TenderAnalysis.user_id == user_id,
                    TenderAnalysis.company_profile_id == company_profile_id,
                    TenderAnalysis.ownership_state == ANALYSIS_OWNERSHIP_OWNED,
                )
                .order_by(
                    TenderAnalysis.created_at.desc(),
                    TenderAnalysis.id.desc(),
                )
                .with_for_update()
            )
        ).scalars()
    )
    if existing:
        if len(existing) > 1:
            logger.warning(
                "analysis_aggregate_historical_ambiguity "
                "user_id=%s company_profile_id=%s tender_id=%s parents=%s "
                "runtime_rule=newest_existing",
                user_id,
                company_profile_id,
                tender_id,
                len(existing),
            )
        return AnalysisAggregateResolution(
            analysis=existing[0],
            created=False,
            existing_parent_count=len(existing),
        )

    db.add(new_parent)
    await db.flush()
    return AnalysisAggregateResolution(
        analysis=new_parent,
        created=True,
        existing_parent_count=0,
    )
