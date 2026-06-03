"""Admin-only diagnostic endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.reproducibility import infer_source_system, requirement_route_records
from app.db.session import get_db
from app.models.audit import TenderAnalysis
from app.models.all_models import Tender, User

router = APIRouter(dependencies=[Depends(require_admin)])


def _bucket_fingerprints(hybrid_compliance: dict[str, Any] | None) -> dict[str, list[str]]:
    if not isinstance(hybrid_compliance, dict):
        return {}

    return {
        "failed": [
            str(item.get("requirement_fingerprint"))
            for item in hybrid_compliance.get("failed_dealbreakers") or []
            if isinstance(item, dict) and item.get("requirement_fingerprint")
        ],
        "manual": [
            str(item.get("requirement_fingerprint"))
            for item in hybrid_compliance.get("manual_reviews_required") or []
            if isinstance(item, dict) and item.get("requirement_fingerprint")
        ],
        "satisfied": [
            str(item.get("requirement_fingerprint"))
            for item in hybrid_compliance.get("satisfied_requirements") or []
            if isinstance(item, dict) and item.get("requirement_fingerprint")
        ],
        "recorded": [
            str(item.get("requirement_fingerprint"))
            for item in hybrid_compliance.get("recorded_obligations") or []
            if isinstance(item, dict) and item.get("requirement_fingerprint")
        ],
    }


def _analysis_reproducibility_summary(analysis: TenderAnalysis) -> dict[str, Any]:
    analysis_data = analysis.analysis_json or {}
    hybrid_compliance = analysis_data.get("hybrid_compliance")
    if not isinstance(hybrid_compliance, dict):
        hybrid_compliance = {}
    snapshot = analysis_data.get("reproducibility_snapshot")
    snapshot_routes = []
    if isinstance(snapshot, dict):
        raw_routes = snapshot.get("requirement_route_summary") or []
        snapshot_routes = [item for item in raw_routes if isinstance(item, dict)]

    return {
        "analysis_id": str(analysis.id),
        "created_at": analysis.created_at.isoformat(),
        "analysis_status": analysis_data.get("analysis_status", "completed"),
        "content_hash": analysis.content_hash,
        "override_seal": analysis.override_seal,
        "coverage_metadata": analysis_data.get("coverage_metadata"),
        "reproducibility_snapshot": snapshot,
        "extraction_artifacts_metadata": analysis_data.get(
            "extraction_artifacts_metadata"
        )
        or [],
        "requirement_fingerprints": _bucket_fingerprints(hybrid_compliance),
        "requirement_route_summary": snapshot_routes
        or requirement_route_records(hybrid_compliance),
    }


@router.get("/tenders/{source_system}/{external_id}/reproducibility")
async def get_tender_reproducibility(
    source_system: str,
    external_id: str,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Return admin-only compliance reproducibility diagnostics for a tender.

    This intentionally excludes raw compiled text, parsed document text, prompts,
    secrets, and filesystem paths.
    """
    del current_user

    result = await db.execute(
        select(Tender).where(Tender.external_id == external_id)
    )
    tender = result.scalar_one_or_none()
    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        )

    inferred_source_system = infer_source_system(tender.source_url)
    if source_system.casefold() != inferred_source_system.casefold():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found for source system",
        )

    analyses_result = await db.execute(
        select(TenderAnalysis)
        .where(TenderAnalysis.tender_id == tender.id)
        .order_by(TenderAnalysis.created_at.desc())
        .limit(10)
    )
    analyses = analyses_result.scalars().all()

    return {
        "tender_id": str(tender.id),
        "source_system": inferred_source_system,
        "external_id": tender.external_id,
        "latest_analyses": [
            _analysis_reproducibility_summary(analysis)
            for analysis in analyses
        ],
    }
