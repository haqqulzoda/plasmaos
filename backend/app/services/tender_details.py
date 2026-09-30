"""Read-only composition for the bounded, tenant-scoped Tender Details summary."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import TenderRecommendation
from app.schemas.explorer import ExplorerProfileMatch, ExplorerRecommendationSummary
from app.models.all_models import (
    Project,
    ProjectRoleAssignment,
    Proposal,
    Tender,
    TenderDocument,
    TenderProject,
    TenderSyncJob,
    TenderSyncStatus,
)
from app.core.storage_paths import storage_file_exists
from app.services.official_notice import not_official_notice, only_official_notice
from app.services.profile_match import profile_targets, tender_profile_match
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
    CompetitorIntelligenceSection,
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
    TenderOfficialNoticeSummary,
)
from app.schemas.tender import TenderCompetitorIntelligenceResponse
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
        not_official_notice()
        & TenderDocument.source_document_url.is_not(None)
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
    normalized_status = func.lower(
        func.coalesce(func.nullif(func.trim(TenderDocument.download_status), ""), "")
    )
    stored_condition = (
        TenderDocument.storage_path.is_not(None)
        & (func.length(func.trim(TenderDocument.storage_path)) > 0)
    )
    parsed_condition = (
        TenderDocument.parsed_text.is_not(None)
        & (func.length(func.trim(TenderDocument.parsed_text)) > 0)
    )
    failed_condition = normalized_status.in_(
        ("failed", "unavailable", "missing", "missing_file", "access_required")
    )
    ready_condition = stored_condition & (
        parsed_condition | normalized_status.in_(("processed", "parsed", "usable"))
    )
    processing_condition = stored_condition & ~ready_condition & ~failed_condition
    # One statement (the read model has a fixed query budget). The notice row is
    # excluded from every attachment count and reported through its own columns;
    # a unique index guarantees at most one such row per tender.
    notice_condition = only_official_notice() & parsed_condition
    counts = (
        await db.execute(
            select(
                func.count(TenderDocument.id).filter(public_condition),
                func.count(TenderDocument.id).filter(~public_condition & not_official_notice()),
                func.count(TenderDocument.id).filter(public_condition & ready_condition),
                func.count(TenderDocument.id).filter(public_condition & failed_condition),
                func.count(TenderDocument.id).filter(public_condition & processing_condition),
                func.min(cast(TenderDocument.id, String)).filter(notice_condition),
                func.min(TenderDocument.source_document_url).filter(notice_condition),
                func.max(func.length(TenderDocument.parsed_text)).filter(notice_condition),
                func.min(TenderDocument.created_at).filter(notice_condition),
            ).where(TenderDocument.tender_id == tender.id)
        )
    ).one()
    visible_total = int(counts[0] or 0)
    unknown_total = int(counts[1] or 0)
    ready_count = int(counts[2] or 0)
    failed_count = int(counts[3] or 0)
    processing_count = int(counts[4] or 0)
    remote_count = max(
        visible_total - ready_count - failed_count - processing_count,
        0,
    )
    latest_job = (
        await db.execute(
            select(TenderSyncJob)
            .where(TenderSyncJob.tender_id == tender.id)
            .order_by(TenderSyncJob.created_at.desc(), TenderSyncJob.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    job_state = (
        latest_job.status.value
        if latest_job is not None and hasattr(latest_job.status, "value")
        else str(latest_job.status) if latest_job is not None else None
    )
    if latest_job is not None and latest_job.status == TenderSyncStatus.PENDING:
        acquisition_state = "QUEUED"
    elif latest_job is not None and latest_job.status == TenderSyncStatus.IN_PROGRESS:
        acquisition_state = "PROCESSING" if latest_job.progress >= 60 else "DOWNLOADING"
    elif visible_total > 0 and ready_count == visible_total:
        acquisition_state = "READY"
    elif ready_count > 0:
        acquisition_state = "PARTIAL"
    elif latest_job is not None and latest_job.status == TenderSyncStatus.FAILED:
        acquisition_state = "FAILED"
    elif failed_count > 0:
        acquisition_state = "FAILED"
    elif processing_count > 0:
        acquisition_state = "PROCESSING"
    else:
        acquisition_state = "AVAILABLE_REMOTE"
    summary_fields = dict(
        acquisition_supported=tender.source_system in {"uzex", "giz"},
        acquisition_state=acquisition_state,
        job_id=latest_job.job_id if latest_job is not None else None,
        job_state=job_state,
        ready_count=ready_count,
        failed_count=failed_count,
        processing_count=processing_count,
        remote_count=remote_count,
    )
    official_notice = (
        TenderOfficialNoticeSummary(
            document_id=UUID(counts[5]),
            source_url=(
                counts[6]
                if counts[6] and counts[6].lower().startswith(("http://", "https://"))
                else None
            ),
            character_count=int(counts[7] or 0),
            created_at=counts[8],
        )
        if counts[5] is not None
        else None
    )
    summary_fields["official_notice"] = official_notice
    if visible_total == 0 and official_notice is not None:
        return TenderDocumentsSection(
            state=DetailsSectionState.AVAILABLE,
            data=TenderDocumentsSummary(
                visible_total_count=0,
                returned_count=0,
                omitted_unknown_count=unknown_total,
                truncated=False,
                **summary_fields,
            ),
        )
    if visible_total == 0:
        return TenderDocumentsSection(
            state=DetailsSectionState.EMPTY,
            data=TenderDocumentsSummary(
                visible_total_count=0,
                returned_count=0,
                omitted_unknown_count=unknown_total,
                truncated=False,
                **summary_fields,
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
                    not_official_notice(),
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
        stored = storage_file_exists(document.storage_path)
        parsed = bool(document.parsed_text and document.parsed_text.strip())
        ready = stored and (
            parsed or download_status in {"processed", "parsed", "usable"}
        )
        if ready:
            availability = "AVAILABLE"
            item_state = "READY"
        elif download_status in {
            "failed",
            "unavailable",
            "missing",
            "missing_file",
            "access_required",
        }:
            availability = "UNAVAILABLE"
            item_state = "FAILED"
        elif stored:
            availability = "AVAILABLE"
            item_state = "PROCESSING"
        else:
            availability = "METADATA_ONLY"
            if latest_job is not None and latest_job.status == TenderSyncStatus.PENDING:
                item_state = "QUEUED"
            elif latest_job is not None and latest_job.status == TenderSyncStatus.IN_PROGRESS:
                item_state = "PROCESSING" if latest_job.progress >= 60 else "DOWNLOADING"
            else:
                item_state = "AVAILABLE_REMOTE"
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
                acquisition_state=item_state,
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
            **summary_fields,
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


def _profile_match(tender: Tender, profile: CompanyProfile | None) -> ExplorerProfileMatch | None:
    """Why this tender matches the viewer's company profile: facts, not a score (D1-08)."""
    if profile is None:
        return None
    targets = profile_targets(
        getattr(profile, "target_countries", None),
        getattr(profile, "target_regions", None),
        getattr(profile, "target_services", None),
    )
    if targets.empty:
        return None
    country, services = tender_profile_match(tender, targets)
    return ExplorerProfileMatch(country=country, services=services) if country or services else None


async def compose_tender_details(
    db: AsyncSession,
    *,
    tender: Tender,
    user_id: UUID,
    procurement_contacts: ProcurementContactsSummary | None,
    competitor_intelligence: TenderCompetitorIntelligenceResponse | None = None,
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
    competitors = (
        CompetitorIntelligenceSection(
            state=DetailsSectionState(competitor_intelligence.state),
            data=competitor_intelligence,
            reason_code=(
                None
                if competitor_intelligence.state == "AVAILABLE"
                else f"COMPETITOR_INTELLIGENCE_{competitor_intelligence.state}"
            ),
        )
        if competitor_intelligence is not None
        else CompetitorIntelligenceSection(
            state=DetailsSectionState.UNAVAILABLE,
            reason_code="COMPETITOR_INTELLIGENCE_UNAVAILABLE",
        )
    )
    # One bounded owned Recommendation read reuses the Explorer projection;
    # the page needs no extra list scan or generation request for its side rail.
    recommendation = await db.scalar(
        select(TenderRecommendation)
        .join(CompanyProfile, CompanyProfile.id == TenderRecommendation.company_profile_id)
        .where(
            TenderRecommendation.tender_id == tender.id,
            CompanyProfile.user_id == user_id,
        )
        .order_by(TenderRecommendation.created_at.desc(), TenderRecommendation.id.asc())
        .limit(1)
    ) if profile is not None else None
    return TenderDetailsResponse(
        recommendation=ExplorerRecommendationSummary(
            recommendation_id=recommendation.id,
            match_score=recommendation.match_score,
            rationale_summary=(recommendation.strategic_rationale or "")[:280],
            is_dismissed=recommendation.is_dismissed,
            created_at=recommendation.created_at,
        ) if recommendation is not None else None,
        profile_match=_profile_match(tender, profile),
        tender_id=tender.id,
        project_context=project_context,
        project_leadership=project_leadership,
        competitor_intelligence=competitors,
        procurement_contacts=contacts,
        requirements=requirements,
        documents=documents,
        compliance=compliance,
        company_readiness=readiness,
        pursuit=pursuit,
        bid_preparation=bid_preparation,
    )
