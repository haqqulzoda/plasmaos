"""Read-only composition for the bounded, tenant-scoped Tender Details summary."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import (
    Project,
    ProjectRoleAssignment,
    Proposal,
    Tender,
    TenderDocument,
    TenderProject,
)
from app.models.company import (
    Certification,
    CompanyProfile,
    FinancialHistory,
    License,
    ReadinessDocument,
)
from app.models.taxonomy import CompanyCredential
from app.schemas.tender_details import (
    BidPreparationSection,
    BidPreparationSummary,
    CompanyReadinessSection,
    CompanyReadinessSummary,
    ComplianceSection,
    ComplianceSummary,
    DetailsSectionState,
    ProcurementContactsSection,
    ProcurementContactsSummary,
    ProjectContextSection,
    ProjectContextSummary,
    ProjectLeadershipItem,
    ProjectLeadershipSection,
    ProjectLeadershipSummary,
    PursuitSection,
    PursuitSummary,
    RequirementSummaryItem,
    RequirementsSection,
    RequirementsSummary,
    TenderDetailsResponse,
    TenderDocumentSummaryItem,
    TenderDocumentsSection,
    TenderDocumentsSummary,
)
from app.services.analysis_aggregates import get_owned_analysis_parent_for_tender
from app.services.analysis_versions import (
    AnalysisVersionIntegrityError,
    require_latest_analysis_version,
)
from app.services.tender_engagements import (
    allowed_actions_for_status,
    get_tender_engagement,
)


logger = logging.getLogger(__name__)

PROJECT_ROLE_LIMIT = 12
DOCUMENT_LIMIT = 25
REQUIREMENT_LIMIT = 12


def _empty(section_type: type, reason_code: str):
    return section_type(state=DetailsSectionState.EMPTY, reason_code=reason_code)


def _safe_name_from_url(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    path = PurePosixPath(unquote(urlparse(value).path))
    name = path.name.strip()
    return name[:255] if name else fallback


def _public_document_condition():
    """Conservatively classify source metadata; ambiguous legacy rows stay hidden."""
    return (
        TenderDocument.source_document_url.is_not(None)
        & (
            TenderDocument.source_document_url.ilike("http://%")
            | TenderDocument.source_document_url.ilike("https://%")
        )
        & TenderDocument.source_document_type.is_not(None)
        & (func.length(func.trim(TenderDocument.source_document_type)) > 0)
    )


async def _project_sections(
    db: AsyncSession,
    *,
    tender_id: UUID,
) -> tuple[ProjectContextSection, ProjectLeadershipSection]:
    row = (
        await db.execute(
            select(Project)
            .join(TenderProject, TenderProject.project_id == Project.id)
            .where(TenderProject.tender_id == tender_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return (
            _empty(ProjectContextSection, "PROJECT_NOT_LINKED"),
            _empty(ProjectLeadershipSection, "PROJECT_NOT_LINKED"),
        )

    project_data = ProjectContextSummary(
        project_id=row.id,
        external_project_id=row.external_project_id,
        name=row.name,
        source_system=row.source_system,
        project_status=row.project_status,
        country=row.country,
        region=row.region,
        approval_date=row.approval_date,
        closing_date=row.closing_date,
        enrichment_state=row.enrichment_status,
        last_enriched_at=row.last_enriched_at,
    )
    degraded = row.enrichment_status in {"failed", "source_unavailable"}
    project_section = ProjectContextSection(
        state=(
            DetailsSectionState.UNAVAILABLE
            if degraded
            else DetailsSectionState.AVAILABLE
        ),
        data=project_data,
        reason_code="PROJECT_ENRICHMENT_UNAVAILABLE" if degraded else None,
    )

    total_count = int(
        await db.scalar(
            select(func.count(ProjectRoleAssignment.id)).where(
                ProjectRoleAssignment.project_id == row.id
            )
        )
        or 0
    )
    roles = list(
        (
            await db.execute(
                select(ProjectRoleAssignment)
                .where(ProjectRoleAssignment.project_id == row.id)
                .order_by(
                    ProjectRoleAssignment.is_current.desc(),
                    ProjectRoleAssignment.last_observed_at.desc(),
                    ProjectRoleAssignment.id.asc(),
                )
                .limit(PROJECT_ROLE_LIMIT)
            )
        ).scalars()
    )
    if not roles:
        leadership = _empty(ProjectLeadershipSection, "PROJECT_LEADERSHIP_NOT_AVAILABLE")
    else:
        items = [
            ProjectLeadershipItem(
                role_id=role.id,
                display_name=role.display_name,
                native_role=role.native_role,
                canonical_role=role.canonical_role,
                source_system=role.source_system,
                source_url=role.source_url,
                is_current=role.is_current,
                first_observed_at=role.first_observed_at,
                last_observed_at=role.last_observed_at,
                ended_at=role.ended_at,
            )
            for role in roles
        ]
        leadership = ProjectLeadershipSection(
            state=DetailsSectionState.AVAILABLE,
            data=ProjectLeadershipSummary(
                items=items,
                total_count=total_count,
                returned_count=len(items),
                truncated=total_count > len(items),
            ),
        )
    return project_section, leadership


async def _documents_section(
    db: AsyncSession,
    *,
    tender: Tender,
) -> TenderDocumentsSection:
    public_condition = _public_document_condition()
    counts = (
        await db.execute(
            select(
                func.count(TenderDocument.id).filter(public_condition),
                func.count(TenderDocument.id).filter(~public_condition),
            ).where(TenderDocument.tender_id == tender.id)
        )
    ).one()
    visible_total = int(counts[0] or 0)
    unknown_total = int(counts[1] or 0)
    if visible_total == 0:
        return TenderDocumentsSection(
            state=DetailsSectionState.EMPTY,
            data=TenderDocumentsSummary(
                visible_total_count=0,
                returned_count=0,
                omitted_unknown_count=unknown_total,
                truncated=False,
            ),
            reason_code=(
                "DOCUMENT_METADATA_CLASSIFICATION_UNAVAILABLE"
                if unknown_total
                else "DOCUMENTS_NOT_AVAILABLE"
            ),
        )

    documents = list(
        (
            await db.execute(
                select(TenderDocument)
                .where(
                    TenderDocument.tender_id == tender.id,
                    public_condition,
                )
                .order_by(TenderDocument.created_at.asc(), TenderDocument.id.asc())
                .limit(DOCUMENT_LIMIT)
            )
        ).scalars()
    )
    items = []
    for document in documents:
        download_status = (document.download_status or "").strip().lower()
        if download_status in {"failed", "unavailable", "missing"}:
            availability = "UNAVAILABLE"
        elif download_status in {"downloaded", "success", "available"}:
            availability = "AVAILABLE"
        else:
            availability = "METADATA_ONLY"
        items.append(
            TenderDocumentSummaryItem(
                document_id=document.id,
                display_name=_safe_name_from_url(
                    document.source_document_url,
                    document.source_document_type or document.file_type,
                ),
                document_type=document.source_document_type or document.file_type,
                metadata_classification="PUBLIC_SOURCE_METADATA",
                source_system=tender.source_system,
                availability=availability,
                file_size=document.file_size,
                content_type=document.mime_type,
                created_at=document.created_at,
            )
        )
    return TenderDocumentsSection(
        state=DetailsSectionState.AVAILABLE,
        data=TenderDocumentsSummary(
            items=items,
            visible_total_count=visible_total,
            returned_count=len(items),
            omitted_unknown_count=unknown_total,
            truncated=visible_total > len(items),
        ),
    )


def _bounded_text(value: Any, *, limit: int = 300) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    return normalized[:limit] or None


def _requirement_candidates(result_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: Any = result_snapshot.get("requirements")
    if isinstance(candidates, dict):
        for key in ("requirements", "items", "mandatory_requirements"):
            if isinstance(candidates.get(key), list):
                candidates = candidates[key]
                break
    if not isinstance(candidates, list):
        extracted = result_snapshot.get("extracted_requirements")
        candidates = extracted if isinstance(extracted, list) else []
    return [item for item in candidates if isinstance(item, dict)]


def _requirements_section(result_snapshot: dict[str, Any] | None) -> RequirementsSection:
    if result_snapshot is None:
        return _empty(RequirementsSection, "SOURCE_NATIVE_REQUIREMENTS_NOT_AVAILABLE")
    candidates = _requirement_candidates(result_snapshot)
    items: list[RequirementSummaryItem] = []
    for candidate in candidates[:REQUIREMENT_LIMIT]:
        label = _bounded_text(
            candidate.get("requirement")
            or candidate.get("description")
            or candidate.get("name")
            or candidate.get("text")
        )
        if not label:
            continue
        evidence = candidate.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        raw_page = evidence.get("page") or candidate.get("page")
        page = raw_page if isinstance(raw_page, int) and raw_page > 0 else None
        items.append(
            RequirementSummaryItem(
                label=label,
                source_type="ANALYSIS_DERIVED",
                document_name=_bounded_text(
                    evidence.get("document_name")
                    or evidence.get("source_filename")
                    or candidate.get("document_name"),
                    limit=255,
                ),
                page=page,
                section=_bounded_text(
                    evidence.get("section") or candidate.get("section"),
                    limit=160,
                ),
            )
        )
    if not items:
        return _empty(RequirementsSection, "STRUCTURED_REQUIREMENTS_NOT_AVAILABLE")
    return RequirementsSection(
        state=DetailsSectionState.AVAILABLE,
        data=RequirementsSummary(
            items=items,
            total_count=len(candidates),
            returned_count=len(items),
            truncated=len(candidates) > len(items),
        ),
    )


def _compliance_values(result_snapshot: dict[str, Any], *, failed: bool):
    hybrid = result_snapshot.get("hybrid_compliance")
    if not isinstance(hybrid, dict):
        hybrid = {}
    evaluation = result_snapshot.get("evaluation")
    if not isinstance(evaluation, dict):
        evaluation = {}
    decision = "FAILED" if failed else _bounded_text(
        hybrid.get("verdict_status")
        or hybrid.get("verdict")
        or evaluation.get("verdict")
        or result_snapshot.get("decision")
    )
    issue_count = hybrid.get("failed_count")
    if not isinstance(issue_count, int):
        issue_count = evaluation.get("missing_requirements_count")
    if not isinstance(issue_count, int):
        issue_count = None
    coverage = result_snapshot.get("coverage_metadata")
    if not isinstance(coverage, dict):
        coverage = result_snapshot.get("evidence_validation")
    coverage_signal = None
    if isinstance(coverage, dict):
        coverage_signal = _bounded_text(
            coverage.get("coverage_status")
            or coverage.get("status")
            or coverage.get("scope_review_status"),
            limit=100,
        )
    return decision, issue_count, coverage_signal


async def _private_sections(
    db: AsyncSession,
    *,
    tender_id: UUID,
    user_id: UUID,
    profile: CompanyProfile | None,
) -> tuple[
    ComplianceSection,
    RequirementsSection,
    CompanyReadinessSection,
    PursuitSection,
    BidPreparationSection,
]:
    if profile is None or profile.user_id != user_id:
        return (
            _empty(ComplianceSection, "COMPLIANCE_NOT_AVAILABLE"),
            _empty(RequirementsSection, "SOURCE_NATIVE_REQUIREMENTS_NOT_AVAILABLE"),
            _empty(CompanyReadinessSection, "COMPANY_PROFILE_NOT_AVAILABLE"),
            _empty(PursuitSection, "PURSUIT_NOT_RECORDED"),
            _empty(BidPreparationSection, "BID_PREPARATION_NOT_STARTED"),
        )

    analysis = await get_owned_analysis_parent_for_tender(
        db,
        user_id=user_id,
        company_profile_id=profile.id,
        tender_id=tender_id,
    )
    version = None
    if analysis is None:
        compliance = _empty(ComplianceSection, "COMPLIANCE_NOT_AVAILABLE")
    else:
        try:
            version = await require_latest_analysis_version(
                db,
                analysis_id=analysis.id,
                user_id=user_id,
                company_profile_id=profile.id,
            )
        except AnalysisVersionIntegrityError:
            logger.warning(
                "tender_details_zero_version_analysis user_id=%s profile_id=%s tender_id=%s analysis_id=%s",
                user_id,
                profile.id,
                tender_id,
                analysis.id,
            )
            compliance = ComplianceSection(
                state=DetailsSectionState.UNAVAILABLE,
                reason_code="COMPLIANCE_HISTORY_UNAVAILABLE",
            )
        else:
            result_snapshot = dict(version.result_snapshot or {})
            failed = version.status == "FAILED"
            decision, issue_count, coverage_signal = _compliance_values(
                result_snapshot,
                failed=failed,
            )
            compliance = ComplianceSection(
                state=(
                    DetailsSectionState.UNAVAILABLE
                    if failed
                    else DetailsSectionState.AVAILABLE
                ),
                data=ComplianceSummary(
                    analysis_id=analysis.id,
                    version_number=version.version_number,
                    analysis_language=version.analysis_language,
                    execution_state=version.status,
                    compliance_completeness=version.snapshot_completeness,
                    decision_label=decision,
                    key_issue_count=issue_count,
                    coverage_signal=coverage_signal,
                    version_origin=version.origin,
                    override_applied=bool(analysis.override_seal),
                    created_at=version.created_at,
                    completed_at=version.completed_at,
                ),
                reason_code="COMPLIANCE_EXECUTION_FAILED" if failed else None,
            )

    requirements = _requirements_section(
        dict(version.result_snapshot or {}) if version is not None else None
    )

    today = date.today()
    readiness = (
        await db.execute(
            select(
                select(func.count(Certification.id))
                .where(Certification.company_id == profile.id)
                .scalar_subquery(),
                select(func.count(Certification.id))
                .where(
                    Certification.company_id == profile.id,
                    Certification.expiry_date < today,
                )
                .scalar_subquery(),
                select(func.count(License.id))
                .where(License.company_id == profile.id)
                .scalar_subquery(),
                select(func.count(License.id))
                .where(License.company_id == profile.id, License.is_active.is_(True))
                .scalar_subquery(),
                select(func.count(CompanyCredential.id))
                .where(CompanyCredential.company_profile_id == profile.id)
                .scalar_subquery(),
                select(func.count(CompanyCredential.id))
                .where(
                    CompanyCredential.company_profile_id == profile.id,
                    CompanyCredential.expiration_date < today,
                )
                .scalar_subquery(),
                select(func.count(ReadinessDocument.id))
                .where(ReadinessDocument.company_profile_id == profile.id)
                .scalar_subquery(),
                *[
                    select(func.count(ReadinessDocument.id))
                    .where(
                        ReadinessDocument.company_profile_id == profile.id,
                        ReadinessDocument.status == readiness_status,
                    )
                    .scalar_subquery()
                    for readiness_status in ("available", "missing", "expired", "unknown")
                ],
                select(func.count(FinancialHistory.id))
                .where(FinancialHistory.company_id == profile.id)
                .scalar_subquery(),
            )
        )
    ).one()
    readiness_section = CompanyReadinessSection(
        state=DetailsSectionState.AVAILABLE,
        data=CompanyReadinessSummary(
            certifications_total=int(readiness[0] or 0),
            expired_certifications=int(readiness[1] or 0),
            licenses_total=int(readiness[2] or 0),
            active_licenses=int(readiness[3] or 0),
            credentials_total=int(readiness[4] or 0),
            expired_credentials=int(readiness[5] or 0),
            readiness_documents_total=int(readiness[6] or 0),
            readiness_documents_available=int(readiness[7] or 0),
            readiness_documents_missing=int(readiness[8] or 0),
            readiness_documents_expired=int(readiness[9] or 0),
            readiness_documents_unknown=int(readiness[10] or 0),
            financial_history_years=int(readiness[11] or 0),
        ),
    )

    engagement = await get_tender_engagement(
        db,
        user_id=user_id,
        company_profile_id=profile.id,
        tender_id=tender_id,
    )
    pursuit = (
        PursuitSection(
            state=DetailsSectionState.AVAILABLE,
            data=PursuitSummary(
                engagement_id=engagement.id,
                engagement_status=engagement.status,
                engagement_origin=engagement.origin,
                status_changed_at=engagement.status_changed_at,
                allowed_actions=list(allowed_actions_for_status(engagement.status)),
            ),
        )
        if engagement is not None
        else _empty(PursuitSection, "PURSUIT_NOT_RECORDED")
    )

    proposal = await db.scalar(
        select(Proposal).where(
            Proposal.user_id == user_id,
            Proposal.tender_id == tender_id,
        )
    )
    bid_preparation = (
        BidPreparationSection(
            state=DetailsSectionState.AVAILABLE,
            data=BidPreparationSummary(
                proposal_id=proposal.id,
                proposal_status=proposal.status,
                created_at=proposal.created_at,
                detail_route_id=proposal.id,
            ),
        )
        if proposal is not None
        else _empty(BidPreparationSection, "BID_PREPARATION_NOT_STARTED")
    )
    return compliance, requirements, readiness_section, pursuit, bid_preparation


async def compose_tender_details(
    db: AsyncSession,
    *,
    tender: Tender,
    user_id: UUID,
    procurement_contacts: ProcurementContactsSummary | None,
) -> TenderDetailsResponse:
    """Compose local canonical state sequentially; never flush, commit, or enqueue."""
    profile = await db.scalar(
        select(CompanyProfile).where(CompanyProfile.user_id == user_id)
    )
    project_context, project_leadership = await _project_sections(
        db,
        tender_id=tender.id,
    )
    documents = await _documents_section(db, tender=tender)
    compliance, requirements, readiness, pursuit, bid_preparation = (
        await _private_sections(
            db,
            tender_id=tender.id,
            user_id=user_id,
            profile=profile,
        )
    )
    contacts = (
        ProcurementContactsSection(
            state=DetailsSectionState.AVAILABLE,
            data=procurement_contacts,
        )
        if procurement_contacts is not None
        else _empty(ProcurementContactsSection, "PROCUREMENT_CONTACTS_NOT_AVAILABLE")
    )
    return TenderDetailsResponse(
        tender_id=tender.id,
        project_context=project_context,
        project_leadership=project_leadership,
        procurement_contacts=contacts,
        requirements=requirements,
        documents=documents,
        compliance=compliance,
        company_readiness=readiness,
        pursuit=pursuit,
        bid_preparation=bid_preparation,
    )
