"""W5 candidate supply, bounded retrieval, qualification, and review services."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import re
from typing import Any, Iterable
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_retrieval import (
    CVVersion,
    CandidateMatch,
    CandidateReviewDecision,
    CandidateSearchRun,
    Expert,
    Firm,
    ProjectReference,
)
from app.models.pursuit_analysis import (
    AnalysisPack,
    AnalysisReviewAssertion,
    AnalysisRun,
    PursuitGap,
    PursuitPosition,
    PursuitRequirement,
)
from app.schemas.candidate_retrieval import (
    CVVersionCreateRequest,
    CVVersionResponse,
    CandidateLibraryResponse,
    CandidateMatchResponse,
    CandidateReviewRequest,
    CandidateReviewResponse,
    CandidateSearchRequest,
    CandidateSearchRunResponse,
    ExpertCreateRequest,
    ExpertResponse,
    ExpertUpdateRequest,
    FirmCreateRequest,
    FirmResponse,
    FirmUpdateRequest,
    ProjectReferenceCreateRequest,
    ProjectReferenceResponse,
    ProjectReferenceUpdateRequest,
    SelfFirmUpsertRequest,
)
from app.models.company import CompanyProfile
from app.models.tenancy import Organization
from app.services.private_documents import build_analysis_pack_candidate


SEARCH_VERSION = "w5-postgres-structured-v1"
ELIGIBLE_COVERAGE = {"GAP", "PARTIAL", "EVIDENCE_MISSING"}
PROVEN_EVIDENCE = {"VERIFIED", "REVIEWED"}
MAX_RETRIEVAL_POOL = 100


class CandidateError(ValueError):
    """Base W5 domain error."""


class CandidateAccessError(CandidateError):
    pass


class CandidateNotFoundError(CandidateError):
    pass


class CandidateEligibilityError(CandidateError):
    pass


class CandidateValidationError(CandidateError):
    """The edited facts would not be a valid record (HTTP 422)."""


def _clean_list(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = " ".join(str(raw).split()).strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _canonical_payload(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten(item)}" for key, item in sorted(value.items()))
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten(item) for item in value)
    return str(value)


def _terms(value: Any) -> set[str]:
    # Keep semantic words and exclude generic procurement filler.
    stop = {
        "and", "the", "for", "with", "from", "that", "this", "must", "shall", "have", "has",
        "required", "requirement", "candidate", "project", "contract", "experience", "expert", "firm",
        "years", "year", "services", "service", "similar", "relevant", "role", "member", "team",
    }
    return {
        token for token in re.findall(r"[^\W_]{3,}", _flatten(value).casefold(), flags=re.UNICODE)
        if token not in stop
    }


def _visible(scope: Any, owner: Any, organization_id: UUID):
    return or_(
        and_(scope == "ORGANIZATION_PRIVATE", owner == organization_id),
        and_(scope == "NETWORK_SHARED", owner.is_(None)),
    )


def _assert_shared_authority(scope: str, *, operator: bool, permission_basis: str | None, consent: str | None = None) -> None:
    if scope != "NETWORK_SHARED":
        return
    if not operator:
        raise CandidateAccessError("Operator access is required to create or edit network-shared candidate data")
    if not (permission_basis or "").strip():
        raise CandidateEligibilityError("Network-shared candidate data requires an explicit permission basis")
    if consent is not None and consent not in {"EXPLICIT_CONSENT", "CONTRACTUAL_BASIS"}:
        raise CandidateEligibilityError("Network-shared experts require explicit consent or a contractual basis")


def _safe_shared_provenance(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"source", "source_url", "document_reference", "reviewed_at", "evidence_type"}
    return {key: item for key, item in value.items() if key in allowed}


# Provenance keys that name a document. Anything else is a recorded claim.
FILE_EVIDENCE_KEYS = ("document_reference", "file_reference", "file_url", "document_version_id", "private_document_id")


def reference_evidence_basis(provenance: dict[str, Any] | None) -> str:
    """FILE_BACKED when the provenance names a document, else METADATA_ONLY.

    File-backed is not verified: nothing here reads the document.
    """
    values = provenance or {}
    return "FILE_BACKED" if any(str(values.get(key) or "").strip() for key in FILE_EVIDENCE_KEYS) else "METADATA_ONLY"


def _reference_response(row: ProjectReference, *, shared: bool = False) -> ProjectReferenceResponse:
    return ProjectReferenceResponse(
        reference_id=row.id, firm_id=row.firm_id, project_name=row.project_name,
        client_name=row.client_name, country=row.country, service=row.service, sector=row.sector,
        role=row.role, contract_share_percent=row.contract_share_percent,
        contract_value=row.contract_value, contract_currency=row.contract_currency,
        value_basis=row.value_basis, start_date=row.start_date, completion_date=row.completion_date,
        completion_state=row.completion_state, relevant_scope=row.relevant_scope,
        evidence_provenance=_safe_shared_provenance(row.evidence_provenance) if shared else row.evidence_provenance,
        evidence_state=row.evidence_state,
        evidence_basis=reference_evidence_basis(row.evidence_provenance),
        supersedes_reference_id=row.supersedes_reference_id, archived_at=row.archived_at,
        created_at=row.created_at,
    )


def _firm_response(row: Firm, references: list[ProjectReference]) -> FirmResponse:
    """``references`` are the firm's current (non-archived) references."""
    return FirmResponse(
        firm_id=row.id, is_self_firm=row.organization_id is not None,
        scope=row.scope, canonical_name=row.canonical_name,
        display_name=row.display_name, legal_name=row.legal_name, country=row.country,
        regions=row.regions, services=row.services, capabilities=row.capabilities, sectors=row.sectors,
        source_type=row.source_type,
        source_provenance=_safe_shared_provenance(row.source_provenance) if row.scope == "NETWORK_SHARED" else row.source_provenance,
        evidence_state=row.evidence_state,
        project_references=[_reference_response(reference, shared=row.scope == "NETWORK_SHARED") for reference in references],
        created_at=row.created_at, updated_at=row.updated_at,
    )


def _cv_response(row: CVVersion, *, shared: bool = False) -> CVVersionResponse:
    return CVVersionResponse(
        cv_version_id=row.id, expert_id=row.expert_id, version_number=row.version_number,
        education=row.education, qualifications=row.qualifications, certifications=row.certifications,
        assignments=row.assignments, languages=row.languages,
        evidence_provenance=_safe_shared_provenance(row.evidence_provenance) if shared else row.evidence_provenance,
        evidence_state=row.evidence_state,
        structured_sha256=row.structured_sha256, created_at=row.created_at,
    )


def _expert_response(row: Expert, versions: list[CVVersion]) -> ExpertResponse:
    return ExpertResponse(
        expert_id=row.id, scope=row.scope, display_name=row.display_name,
        qualifications=row.qualifications, languages=row.languages,
        specializations=row.specializations, consent_state=row.consent_state,
        evidence_state=row.evidence_state,
        source_provenance=_safe_shared_provenance(row.source_provenance) if row.scope == "NETWORK_SHARED" else row.source_provenance,
        cv_versions=[_cv_response(version, shared=row.scope == "NETWORK_SHARED") for version in versions],
        created_at=row.created_at, updated_at=row.updated_at,
    )


async def create_firm(
    db: AsyncSession, *, organization_id: UUID, actor_user_id: UUID,
    payload: FirmCreateRequest, operator: bool,
) -> FirmResponse:
    _assert_shared_authority(
        payload.scope, operator=operator, permission_basis=payload.network_permission_basis
    )
    row = Firm(
        scope=payload.scope,
        owner_organization_id=organization_id if payload.scope == "ORGANIZATION_PRIVATE" else None,
        canonical_name=" ".join(payload.canonical_name.split()),
        display_name=" ".join(payload.display_name.split()), legal_name=payload.legal_name,
        country=payload.country, regions=_clean_list(payload.regions), services=_clean_list(payload.services),
        capabilities=_clean_list(payload.capabilities), sectors=_clean_list(payload.sectors),
        source_type=payload.source_type, source_provenance=payload.source_provenance,
        evidence_state=payload.evidence_state,
        network_permission_basis=payload.network_permission_basis,
        private_notes=payload.private_notes, created_by_user_id=actor_user_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _firm_response(row, [])


async def update_firm(
    db: AsyncSession, *, organization_id: UUID, firm_id: UUID,
    payload: FirmUpdateRequest, operator: bool,
) -> FirmResponse:
    row = await db.scalar(select(Firm).where(Firm.id == firm_id, _visible(Firm.scope, Firm.owner_organization_id, organization_id)))
    if row is None:
        raise CandidateNotFoundError("Firm not found")
    if row.scope == "NETWORK_SHARED" and not operator:
        raise CandidateAccessError("Operator access is required to edit network-shared candidate data")
    values = payload.model_dump(exclude_unset=True)
    if "network_permission_basis" in values and row.scope == "NETWORK_SHARED":
        _assert_shared_authority(row.scope, operator=operator, permission_basis=values["network_permission_basis"])
    for key in ("regions", "services", "capabilities", "sectors"):
        if key in values and values[key] is not None:
            values[key] = _clean_list(values[key])
    for key, value in values.items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return _firm_response(row, await _current_references(db, row.id))


async def _current_references(db: AsyncSession, firm_id: UUID) -> list[ProjectReference]:
    return list((await db.scalars(
        select(ProjectReference)
        .where(ProjectReference.firm_id == firm_id, ProjectReference.archived_at.is_(None))
        .order_by(ProjectReference.created_at, ProjectReference.id)
    )).all())


async def get_self_firm(db: AsyncSession, *, organization_id: UUID) -> FirmResponse | None:
    """The organization's own firm with its current references. Passive: never creates."""
    row = await db.scalar(select(Firm).where(Firm.organization_id == organization_id))
    if row is None:
        return None
    return _firm_response(row, await _current_references(db, row.id))


async def _organization_name(db: AsyncSession, organization_id: UUID) -> str:
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise CandidateNotFoundError("Organization not found")
    name = " ".join((organization.display_name or "").split())
    if len(name) < 2:
        profile = await db.get(CompanyProfile, organization.legacy_company_profile_id)
        name = " ".join((getattr(profile, "company_name", None) or "").split())
    return name if len(name) >= 2 else "Our company"


async def upsert_self_firm(
    db: AsyncSession, *, organization_id: UUID, actor_user_id: UUID, payload: SelfFirmUpsertRequest,
) -> FirmResponse:
    """Create the organization's own firm, or apply the provided fields to it.

    Always ORGANIZATION_PRIVATE and owned by the organization; the partial unique
    index keeps it to one per organization under concurrent first saves.
    """
    values = payload.model_dump(exclude_unset=True)
    for key in ("canonical_name", "display_name", "source_type", "evidence_state"):
        if key in values and values[key] is None:
            raise CandidateValidationError(f"{key} cannot be empty")
    for key in ("regions", "services", "capabilities", "sectors"):
        if key in values:
            values[key] = _clean_list(values[key] or [])
    for key in ("canonical_name", "display_name"):
        if key in values:
            values[key] = " ".join(values[key].split())
    if "source_provenance" in values and values["source_provenance"] is None:
        values["source_provenance"] = {}

    row = await db.scalar(select(Firm).where(Firm.organization_id == organization_id).with_for_update())
    if row is None:
        display_name = values.get("display_name") or await _organization_name(db, organization_id)
        created = {
            "canonical_name": display_name, "regions": [], "services": [], "capabilities": [], "sectors": [],
            "source_type": "MANUAL", "source_provenance": {}, "evidence_state": "UNVERIFIED",
            **values, "display_name": display_name,
        }
        row = Firm(
            scope="ORGANIZATION_PRIVATE", owner_organization_id=organization_id,
            organization_id=organization_id, created_by_user_id=actor_user_id, **created,
        )
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            # A concurrent first save won the unique index; apply this request to that row.
            await db.rollback()
            row = await db.scalar(select(Firm).where(Firm.organization_id == organization_id).with_for_update())
            if row is None:
                raise
            for key, value in values.items():
                setattr(row, key, value)
            await db.commit()
    else:
        for key, value in values.items():
            setattr(row, key, value)
        await db.commit()
    await db.refresh(row)
    return _firm_response(row, await _current_references(db, row.id))


async def _editable_reference(
    db: AsyncSession, *, organization_id: UUID, firm_id: UUID, reference_id: UUID, operator: bool,
) -> tuple[Firm, ProjectReference]:
    firm = await db.scalar(select(Firm).where(Firm.id == firm_id, _visible(Firm.scope, Firm.owner_organization_id, organization_id)))
    if firm is None:
        raise CandidateNotFoundError("Firm not found")
    if firm.scope == "NETWORK_SHARED" and not operator:
        raise CandidateAccessError("Operator access is required to edit network-shared evidence")
    row = await db.scalar(
        select(ProjectReference)
        .where(ProjectReference.id == reference_id, ProjectReference.firm_id == firm.id)
        .with_for_update()
    )
    if row is None:
        raise CandidateNotFoundError("Project reference not found")
    return firm, row


REFERENCE_FACT_FIELDS = tuple(ProjectReferenceCreateRequest.model_fields)


async def update_project_reference(
    db: AsyncSession, *, organization_id: UUID, firm_id: UUID, reference_id: UUID,
    actor_user_id: UUID, payload: ProjectReferenceUpdateRequest, operator: bool,
) -> ProjectReferenceResponse:
    """Edit by supersede: the changed facts become a new reference; the old row is archived.

    Candidate matches, scenario contributions and proposal evidence packs cite a
    reference by id and are immutable, so the cited row's facts are never rewritten.
    A request that changes nothing returns the reference as it is.
    """
    firm, row = await _editable_reference(
        db, organization_id=organization_id, firm_id=firm_id, reference_id=reference_id, operator=operator,
    )
    if row.archived_at is not None:
        raise CandidateEligibilityError("An archived project reference cannot be edited")
    current = {key: getattr(row, key) for key in REFERENCE_FACT_FIELDS}
    merged = {**current, **payload.model_dump(exclude_unset=True)}
    try:
        facts = ProjectReferenceCreateRequest(**merged).model_dump()
    except ValidationError as exc:
        problems = "; ".join(str(error.get("msg", "invalid value")) for error in exc.errors()[:5])
        raise CandidateValidationError(f"The edited project reference is not valid: {problems}") from exc
    if facts == ProjectReferenceCreateRequest(**current).model_dump():
        return _reference_response(row, shared=firm.scope == "NETWORK_SHARED")
    row.archived_at = datetime.now(timezone.utc)
    row.archived_by_user_id = actor_user_id
    successor = ProjectReference(
        firm_id=firm.id, created_by_user_id=actor_user_id, supersedes_reference_id=row.id, **facts
    )
    db.add(successor)
    await db.commit()
    await db.refresh(successor)
    return _reference_response(successor, shared=firm.scope == "NETWORK_SHARED")


async def archive_project_reference(
    db: AsyncSession, *, organization_id: UUID, firm_id: UUID, reference_id: UUID,
    actor_user_id: UUID, operator: bool,
) -> ProjectReferenceResponse:
    """Retire a reference from the library, new searches and new analyses. Idempotent.

    The row stays, so history that cites it still resolves.
    """
    firm, row = await _editable_reference(
        db, organization_id=organization_id, firm_id=firm_id, reference_id=reference_id, operator=operator,
    )
    if row.archived_at is None:
        row.archived_at = datetime.now(timezone.utc)
        row.archived_by_user_id = actor_user_id
        await db.commit()
        await db.refresh(row)
    return _reference_response(row, shared=firm.scope == "NETWORK_SHARED")


async def create_project_reference(
    db: AsyncSession, *, organization_id: UUID, firm_id: UUID, actor_user_id: UUID,
    payload: ProjectReferenceCreateRequest, operator: bool,
) -> ProjectReferenceResponse:
    firm = await db.scalar(select(Firm).where(Firm.id == firm_id, _visible(Firm.scope, Firm.owner_organization_id, organization_id)))
    if firm is None:
        raise CandidateNotFoundError("Firm not found")
    if firm.scope == "NETWORK_SHARED" and not operator:
        raise CandidateAccessError("Operator access is required to add network-shared evidence")
    row = ProjectReference(
        firm_id=firm.id, created_by_user_id=actor_user_id, **payload.model_dump()
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _reference_response(row)


async def create_expert(
    db: AsyncSession, *, organization_id: UUID, actor_user_id: UUID,
    payload: ExpertCreateRequest, operator: bool,
) -> ExpertResponse:
    _assert_shared_authority(
        payload.scope, operator=operator, permission_basis=payload.network_permission_basis,
        consent=payload.consent_state,
    )
    row = Expert(
        scope=payload.scope,
        owner_organization_id=organization_id if payload.scope == "ORGANIZATION_PRIVATE" else None,
        display_name=" ".join(payload.display_name.split()),
        qualifications=_clean_list(payload.qualifications), languages=_clean_list(payload.languages),
        specializations=_clean_list(payload.specializations), consent_state=payload.consent_state,
        network_permission_basis=payload.network_permission_basis, evidence_state=payload.evidence_state,
        source_provenance=payload.source_provenance, private_notes=payload.private_notes,
        created_by_user_id=actor_user_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _expert_response(row, [])


async def update_expert(
    db: AsyncSession, *, organization_id: UUID, expert_id: UUID,
    payload: ExpertUpdateRequest, operator: bool,
) -> ExpertResponse:
    row = await db.scalar(select(Expert).where(Expert.id == expert_id, _visible(Expert.scope, Expert.owner_organization_id, organization_id)))
    if row is None:
        raise CandidateNotFoundError("Expert not found")
    if row.scope == "NETWORK_SHARED" and not operator:
        raise CandidateAccessError("Operator access is required to edit network-shared candidate data")
    values = payload.model_dump(exclude_unset=True)
    next_consent = values.get("consent_state", row.consent_state)
    next_basis = values.get("network_permission_basis", row.network_permission_basis)
    _assert_shared_authority(row.scope, operator=operator, permission_basis=next_basis, consent=next_consent)
    for key in ("qualifications", "languages", "specializations"):
        if key in values and values[key] is not None:
            values[key] = _clean_list(values[key])
    for key, value in values.items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    versions = list((await db.scalars(select(CVVersion).where(CVVersion.expert_id == row.id).order_by(CVVersion.version_number))).all())
    return _expert_response(row, versions)


async def create_cv_version(
    db: AsyncSession, *, organization_id: UUID, expert_id: UUID, actor_user_id: UUID,
    payload: CVVersionCreateRequest, operator: bool,
) -> CVVersionResponse:
    expert = await db.scalar(
        select(Expert).where(Expert.id == expert_id, _visible(Expert.scope, Expert.owner_organization_id, organization_id)).with_for_update()
    )
    if expert is None:
        raise CandidateNotFoundError("Expert not found")
    if expert.scope == "NETWORK_SHARED" and not operator:
        raise CandidateAccessError("Operator access is required to add network-shared CV facts")
    current = await db.scalar(select(func.max(CVVersion.version_number)).where(CVVersion.expert_id == expert.id))
    facts = payload.model_dump()
    digest = hashlib.sha256(_canonical_payload(facts).encode("utf-8")).hexdigest()
    row = CVVersion(
        expert_id=expert.id, version_number=int(current or 0) + 1,
        structured_sha256=digest, created_by_user_id=actor_user_id, **facts,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _cv_response(row)


async def list_candidate_library(db: AsyncSession, *, organization_id: UUID) -> CandidateLibraryResponse:
    # The organization's own firm sorts first so the page limit can never drop it.
    visible = list((await db.scalars(
        select(Firm).where(_visible(Firm.scope, Firm.owner_organization_id, organization_id))
        .order_by(Firm.organization_id.is_(None), Firm.display_name, Firm.id).limit(101)
    )).all())
    self_firm = next((row for row in visible if row.organization_id is not None), None)
    firms = [row for row in visible if row.organization_id is None][:100]
    experts = list((await db.scalars(
        select(Expert).where(_visible(Expert.scope, Expert.owner_organization_id, organization_id))
        .order_by(Expert.display_name, Expert.id).limit(100)
    )).all())
    references = list((await db.scalars(
        select(ProjectReference).where(
            ProjectReference.firm_id.in_([row.id for row in visible]), ProjectReference.archived_at.is_(None),
        ).order_by(ProjectReference.created_at, ProjectReference.id)
    )).all()) if visible else []
    versions = list((await db.scalars(
        select(CVVersion).where(CVVersion.expert_id.in_([row.id for row in experts]))
        .order_by(CVVersion.expert_id, CVVersion.version_number)
    )).all()) if experts else []
    refs_by_firm: dict[UUID, list[ProjectReference]] = defaultdict(list)
    versions_by_expert: dict[UUID, list[CVVersion]] = defaultdict(list)
    for row in references:
        refs_by_firm[row.firm_id].append(row)
    for row in versions:
        versions_by_expert[row.expert_id].append(row)
    return CandidateLibraryResponse(
        self_firm=_firm_response(self_firm, refs_by_firm[self_firm.id]) if self_firm else None,
        firms=[_firm_response(row, refs_by_firm[row.id]) for row in firms],
        experts=[_expert_response(row, versions_by_expert[row.id]) for row in experts],
    )


def _contribution_explicitly_allowed(value: str | None) -> bool:
    normalized = (value or "").strip().casefold()
    if not normalized or any(term in normalized for term in ("unclear", "ambiguous", "interpret")):
        return False
    return any(term in normalized for term in (
        "joint venture", "jv", "consortium", "partner", "member", "subconsultant",
        "sub-consultant", "collectively", "combined", "may satisfy", "is allowed", "are allowed",
    ))


async def _eligible_gap(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, request: CandidateSearchRequest,
) -> tuple[AnalysisRun, AnalysisPack, PursuitGap, AnalysisReviewAssertion, PursuitRequirement | PursuitPosition, str, str]:
    run = await db.scalar(select(AnalysisRun).where(
        AnalysisRun.id == request.analysis_run_id,
        AnalysisRun.organization_id == organization_id,
        AnalysisRun.pursuit_id == pursuit_id,
        AnalysisRun.status == "COMPLETED",
    ))
    if run is None:
        raise CandidateNotFoundError("Completed W4 analysis run not found")
    pack = await db.get(AnalysisPack, run.pack_id)
    if pack is None:
        raise CandidateNotFoundError("Sealed W4 analysis pack not found")
    current = await build_analysis_pack_candidate(db, organization_id=organization_id, pursuit_id=pursuit_id)
    if current.candidate_sha256 != pack.candidate_sha256:
        raise CandidateEligibilityError("The W4 analysis run is stale; refresh the analysis before searching candidates")
    gap = await db.scalar(select(PursuitGap).where(
        PursuitGap.id == request.gap_id, PursuitGap.analysis_run_id == run.id
    ))
    if gap is None:
        raise CandidateNotFoundError("W4 Gap not found in this analysis run")
    assertion = await db.scalar(
        select(AnalysisReviewAssertion)
        .where(
            AnalysisReviewAssertion.analysis_run_id == run.id,
            AnalysisReviewAssertion.target_kind == "GAP",
            AnalysisReviewAssertion.gap_id == gap.id,
        )
        .order_by(AnalysisReviewAssertion.created_at.desc(), AnalysisReviewAssertion.id.desc()).limit(1)
    )
    if assertion is None or assertion.new_review_state not in {"CONFIRMED", "CORRECTED"}:
        raise CandidateEligibilityError("Candidate retrieval requires an effective reviewed W4 Gap")
    if assertion.new_coverage_state not in ELIGIBLE_COVERAGE:
        raise CandidateEligibilityError("The effective W4 Gap state is not eligible for candidate retrieval")
    resolution = str(assertion.corrected_fields.get("resolution_category") or gap.resolution_category).upper()
    if resolution not in {"PARTNER_FIRM", "EXPERT"}:
        raise CandidateEligibilityError("This W4 resolution category cannot start candidate retrieval")
    if resolution == "PARTNER_FIRM":
        if gap.requirement_id is None or gap.position_id is not None:
            raise CandidateEligibilityError("PARTNER_FIRM retrieval requires a corporate Requirement Gap")
        target = await db.get(PursuitRequirement, gap.requirement_id)
        if target is None or target.analysis_run_id != run.id:
            raise CandidateNotFoundError("W4 Requirement not found")
        requirement_assertion = await db.scalar(
            select(AnalysisReviewAssertion).where(
                AnalysisReviewAssertion.analysis_run_id == run.id,
                AnalysisReviewAssertion.target_kind == "REQUIREMENT",
                AnalysisReviewAssertion.requirement_id == target.id,
            ).order_by(AnalysisReviewAssertion.created_at.desc(), AnalysisReviewAssertion.id.desc()).limit(1)
        )
        contribution = str(
            assertion.corrected_fields.get("contribution_rule")
            or (requirement_assertion.corrected_fields.get("contribution_rule") if requirement_assertion else None)
            or target.contribution_rule or ""
        ).strip()
        if not _contribution_explicitly_allowed(contribution):
            raise CandidateEligibilityError("PARTNER_FIRM retrieval requires an explicit reviewed or issued contribution rule")
        return run, pack, gap, assertion, target, resolution, contribution
    if gap.position_id is None or gap.requirement_id is not None:
        raise CandidateEligibilityError("EXPERT retrieval requires a Position Gap")
    target = await db.get(PursuitPosition, gap.position_id)
    if target is None or target.analysis_run_id != run.id:
        raise CandidateNotFoundError("W4 Position not found")
    contribution = str(assertion.corrected_fields.get("proposed_contribution") or target.title or gap.missing_contribution).strip()
    return run, pack, gap, assertion, target, resolution, contribution


def _predicate_satisfied(predicate: dict[str, Any] | None, count: int) -> tuple[bool | None, str | None]:
    if not predicate:
        return None, None
    unit = str(predicate.get("unit", "")).casefold()
    threshold_raw = predicate.get("threshold")
    if "contract" not in unit or not isinstance(threshold_raw, (int, float)):
        return None, "The structured threshold is not a comparable-contract count and needs review."
    threshold = float(threshold_raw)
    operator = predicate.get("operator")
    checks = {">=": count >= threshold, ">": count > threshold, "=": count == threshold, "==": count == threshold}
    if operator not in checks:
        return None, "The structured contract-count operator needs review."
    return checks[operator], f"{count} reviewed completed reference(s) against {operator} {threshold:g}."


def _evaluate_firms(
    firms: list[Firm], references: list[ProjectReference], target: PursuitRequirement,
    gap: PursuitGap, contribution: str, limit: int,
) -> list[dict[str, Any]]:
    refs_by_firm: dict[UUID, list[ProjectReference]] = defaultdict(list)
    for reference in references:
        refs_by_firm[reference.firm_id].append(reference)
    target_terms = _terms([
        target.normalized_requirement, target.category, target.requirement_type,
        target.predicate_json, gap.missing_contribution,
    ])
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for firm in firms:
        firm_refs = refs_by_firm[firm.id]
        profile_terms = _terms([firm.services, firm.capabilities, firm.sectors, firm.country, firm.regions])
        reviewed_refs = [row for row in firm_refs if row.evidence_state in PROVEN_EVIDENCE]
        reference_terms = _terms([
            [row.project_name, row.client_name, row.country, row.service, row.sector, row.relevant_scope, row.role]
            for row in reviewed_refs
        ])
        overlap = target_terms.intersection(profile_terms | reference_terms)
        potential_overlap = target_terms.intersection(_terms([
            firm.services, firm.capabilities, firm.sectors,
            [[row.service, row.sector, row.relevant_scope, row.project_name] for row in firm_refs],
        ]))
        if not overlap and not potential_overlap:
            continue
        comparable = [row for row in reviewed_refs if row.completion_state == "COMPLETED" and target_terms.intersection(_terms([
            row.project_name, row.country, row.service, row.sector, row.relevant_scope,
        ]))]
        predicate_ok, predicate_detail = _predicate_satisfied(target.predicate_json, len(comparable))
        strongest = [{
            "type": "PROJECT_REFERENCE", "reference_id": str(row.id), "project_name": row.project_name,
            "role": row.role, "completion_state": row.completion_state, "evidence_state": row.evidence_state,
            "value": str(row.contract_value) if row.contract_value is not None else None,
            "currency": row.contract_currency, "value_basis": row.value_basis,
        } for row in comparable[:3]]
        relevant = [{
            "reference_id": str(row.id), "service": row.service, "sector": row.sector,
            "country": row.country, "relevant_scope": row.relevant_scope,
        } for row in reviewed_refs[:5]]
        missing: list[str] = []
        if firm.evidence_state not in PROVEN_EVIDENCE:
            missing.append("Firm capability descriptors have not been evidence-reviewed.")
        if not reviewed_refs:
            missing.append("No reviewed project reference is available.")
        if predicate_ok is False:
            missing.append(predicate_detail or "The comparable-contract threshold is not met by reviewed evidence.")
        elif predicate_ok is None and target.predicate_json:
            missing.append(predicate_detail or "The structured predicate needs human review.")
        if not comparable:
            missing.append("No reviewed completed reference directly supports the exact gap.")
        if not reviewed_refs or firm.evidence_state in {"UNVERIFIED", "EVIDENCE_MISSING"}:
            state = "EVIDENCE_MISSING"
        elif predicate_ok is False or missing:
            state = "PARTIAL"
        elif predicate_ok is None and target.predicate_json:
            state = "NEEDS_REVIEW"
        else:
            state = "SUPPORTED_BY_EVIDENCE"
        score = len(overlap) * 10 + len(comparable) * 4 + len(reviewed_refs)
        rationale = (
            f"Retrieved on {len(overlap or potential_overlap)} exact-gap term(s); "
            f"{len(comparable)} reviewed completed reference(s) support comparison."
        )
        ranked.append((score, firm.display_name.casefold(), {
            "firm": firm, "proposed_contribution": contribution, "strongest_evidence": strongest,
            "relevant_evidence": relevant, "missing": missing, "state": state,
            "rationale": rationale,
            "provenance": {"candidate_scope": firm.scope, "candidate_source_type": firm.source_type,
                           "firm_id": str(firm.id), "reference_ids": [str(row.id) for row in reviewed_refs]},
        }))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[:limit]]


def _latest_versions(versions: list[CVVersion]) -> dict[UUID, CVVersion]:
    latest: dict[UUID, CVVersion] = {}
    for row in versions:
        if row.expert_id not in latest or row.version_number > latest[row.expert_id].version_number:
            latest[row.expert_id] = row
    return latest


def _evaluate_experts(
    experts: list[Expert], versions: list[CVVersion], target: PursuitPosition,
    gap: PursuitGap, contribution: str, limit: int,
) -> list[dict[str, Any]]:
    latest = _latest_versions(versions)
    target_terms = _terms([
        target.title, target.education_qualification, target.general_experience,
        target.specific_experience, target.relevant_assignments, target.languages,
        target.certifications, target.location_travel, gap.missing_contribution,
    ])
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for expert in experts:
        cv = latest.get(expert.id)
        profile_terms = _terms([expert.qualifications, expert.languages, expert.specializations])
        cv_terms = _terms([
            cv.education, cv.qualifications, cv.certifications, cv.assignments, cv.languages
        ]) if cv else set()
        overlap = target_terms.intersection(profile_terms | cv_terms)
        if not overlap:
            continue
        reviewed_cv = cv if cv and cv.evidence_state in PROVEN_EVIDENCE else None
        strongest: list[dict[str, Any]] = []
        relevant: list[dict[str, Any]] = []
        missing: list[str] = []
        if reviewed_cv:
            relevant = [{
                "type": "CV_VERSION", "cv_version_id": str(reviewed_cv.id),
                "version_number": reviewed_cv.version_number, "evidence_state": reviewed_cv.evidence_state,
                "structured_sha256": reviewed_cv.structured_sha256,
            }]
            for kind, facts in (
                ("EDUCATION", reviewed_cv.education), ("QUALIFICATION", reviewed_cv.qualifications),
                ("CERTIFICATION", reviewed_cv.certifications), ("ASSIGNMENT", reviewed_cv.assignments),
                ("LANGUAGE", reviewed_cv.languages),
            ):
                for fact in facts:
                    if target_terms.intersection(_terms(fact)):
                        strongest.append({"type": kind, "fact": fact, "cv_version_id": str(reviewed_cv.id)})
                        if len(strongest) >= 5:
                            break
                if len(strongest) >= 5:
                    break
        else:
            missing.append("No reviewed immutable CV version supports the profile facts.")
        criteria = [
            (target.education_qualification, reviewed_cv.education if reviewed_cv else [], "Education evidence is missing."),
            (target.relevant_assignments or target.specific_experience, reviewed_cv.assignments if reviewed_cv else [], "Relevant assignment evidence is missing."),
            (target.languages, reviewed_cv.languages if reviewed_cv else [], "Language evidence is missing."),
            (target.certifications, reviewed_cv.certifications if reviewed_cv else [], "Certification evidence is missing."),
        ]
        for required, facts, message in criteria:
            if required and not target_terms.intersection(_terms(facts)):
                missing.append(message)
        if target.general_experience:
            missing.append("General experience duration needs review; overlapping assignment periods were not summed.")
        if expert.evidence_state not in PROVEN_EVIDENCE:
            missing.append("Expert profile descriptors have not been evidence-reviewed.")
        if not reviewed_cv:
            state = "EVIDENCE_MISSING"
        elif missing:
            state = "PARTIAL"
        elif strongest:
            state = "SUPPORTED_BY_EVIDENCE"
        else:
            state = "NEEDS_REVIEW"
        score = len(overlap) * 10 + len(strongest) * 3
        rationale = (
            f"Retrieved on {len(overlap)} exact-position term(s); "
            f"{len(strongest)} fact(s) from the latest reviewed CV version support comparison."
        )
        ranked.append((score, expert.display_name.casefold(), {
            "expert": expert, "proposed_contribution": contribution,
            "strongest_evidence": strongest, "relevant_evidence": relevant,
            "missing": list(dict.fromkeys(missing)), "state": state, "rationale": rationale,
            "provenance": {"candidate_scope": expert.scope, "expert_id": str(expert.id),
                           "cv_version_id": str(cv.id) if cv else None},
        }))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[:limit]]


async def create_candidate_search(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
    membership_id: UUID, request: CandidateSearchRequest,
) -> CandidateSearchRunResponse:
    run, pack, gap, assertion, target, resolution, contribution = await _eligible_gap(
        db, organization_id=organization_id, pursuit_id=pursuit_id, request=request
    )
    if resolution == "PARTNER_FIRM":
        # A partner search never proposes the organization's own firm, and reads
        # current references only.
        candidates = list((await db.scalars(
            select(Firm).where(
                _visible(Firm.scope, Firm.owner_organization_id, organization_id),
                Firm.organization_id.is_(None),
            ).order_by(Firm.updated_at.desc(), Firm.id).limit(MAX_RETRIEVAL_POOL)
        )).all())
        references = list((await db.scalars(
            select(ProjectReference).where(
                ProjectReference.firm_id.in_([row.id for row in candidates]),
                ProjectReference.archived_at.is_(None),
            ).order_by(ProjectReference.firm_id, ProjectReference.created_at.desc())
        )).all()) if candidates else []
        evaluated = _evaluate_firms(candidates, references, target, gap, contribution, request.result_limit)  # type: ignore[arg-type]
    else:
        candidates = list((await db.scalars(
            select(Expert).where(
                _visible(Expert.scope, Expert.owner_organization_id, organization_id),
                Expert.consent_state != "WITHDRAWN",
            ).order_by(Expert.updated_at.desc(), Expert.id).limit(MAX_RETRIEVAL_POOL)
        )).all())
        versions = list((await db.scalars(
            select(CVVersion).where(CVVersion.expert_id.in_([row.id for row in candidates]))
            .order_by(CVVersion.expert_id, CVVersion.version_number.desc())
        )).all()) if candidates else []
        evaluated = _evaluate_experts(candidates, versions, target, gap, contribution, request.result_limit)  # type: ignore[arg-type]
    now = datetime.now(timezone.utc)
    search = CandidateSearchRun(
        organization_id=organization_id, pursuit_id=pursuit_id, analysis_run_id=run.id,
        gap_id=gap.id, target_kind="FIRM" if resolution == "PARTNER_FIRM" else "EXPERT",
        requirement_id=gap.requirement_id, position_id=gap.position_id,
        review_assertion_id=assertion.id, effective_coverage_state=assertion.new_coverage_state,
        effective_review_state=assertion.new_review_state, resolution_category=resolution,
        contribution_rule=contribution, search_version=SEARCH_VERSION,
        search_parameters={
            "result_limit": request.result_limit, "retrieval_pool_limit": MAX_RETRIEVAL_POOL,
            "source": "POSTGRES_ONLY", "no_source_scraping": True,
            "analysis_pack_candidate_sha256": pack.candidate_sha256,
        },
        result_limit=request.result_limit, actor_membership_id=membership_id,
        status="COMPLETED", completed_at=now,
    )
    db.add(search)
    await db.flush()
    for rank, item in enumerate(evaluated, start=1):
        db.add(CandidateMatch(
            candidate_search_run_id=search.id, gap_id=gap.id,
            firm_id=item["firm"].id if "firm" in item else None,
            expert_id=item["expert"].id if "expert" in item else None,
            proposed_contribution=item["proposed_contribution"],
            strongest_evidence=item["strongest_evidence"], relevant_evidence=item["relevant_evidence"],
            missing_or_weak_evidence=item["missing"], qualification_state=item["state"],
            rationale=item["rationale"], provenance=item["provenance"], retrieval_rank=rank,
        ))
    await db.commit()
    response = await get_candidate_search(
        db, organization_id=organization_id, pursuit_id=pursuit_id, search_run_id=search.id
    )
    if response is None:
        raise RuntimeError("Completed candidate search could not be projected")
    return response


async def _stale_search_runs(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
    searches: list[CandidateSearchRun],
) -> dict[UUID, tuple[bool, str | None]]:
    if not searches:
        return {}
    latest_run_id = await db.scalar(
        select(AnalysisRun.id).where(
            AnalysisRun.organization_id == organization_id,
            AnalysisRun.pursuit_id == pursuit_id,
        ).order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc()).limit(1)
    )
    current = await build_analysis_pack_candidate(db, organization_id=organization_id, pursuit_id=pursuit_id)
    pack_ids = {row.analysis_run_id for row in searches}
    pairs = (await db.execute(
        select(AnalysisRun.id, AnalysisPack.candidate_sha256)
        .join(AnalysisPack, AnalysisPack.id == AnalysisRun.pack_id)
        .where(AnalysisRun.id.in_(pack_ids))
    )).all()
    hashes = {run_id: digest for run_id, digest in pairs}
    result: dict[UUID, tuple[bool, str | None]] = {}
    for row in searches:
        if row.analysis_run_id != latest_run_id:
            result[row.id] = (True, "A newer W4 analysis run exists; this search remains historical.")
        elif hashes.get(row.analysis_run_id) != current.candidate_sha256:
            result[row.id] = (True, "Current pursuit inputs differ from the bound W4 analysis pack.")
        else:
            result[row.id] = (False, None)
    return result


async def _project_searches(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
    searches: list[CandidateSearchRun],
) -> list[CandidateSearchRunResponse]:
    if not searches:
        return []
    search_ids = [row.id for row in searches]
    matches = list((await db.scalars(
        select(CandidateMatch).where(CandidateMatch.candidate_search_run_id.in_(search_ids))
        .order_by(CandidateMatch.candidate_search_run_id, CandidateMatch.retrieval_rank)
    )).all())
    match_ids = [row.id for row in matches]
    decisions = list((await db.scalars(
        select(CandidateReviewDecision).where(CandidateReviewDecision.candidate_match_id.in_(match_ids))
        .order_by(CandidateReviewDecision.created_at, CandidateReviewDecision.id)
    )).all()) if match_ids else []
    latest_decision: dict[UUID, CandidateReviewDecision] = {}
    for row in decisions:
        latest_decision[row.candidate_match_id] = row
    firm_ids = {row.firm_id for row in matches if row.firm_id}
    expert_ids = {row.expert_id for row in matches if row.expert_id}
    firms = {row.id: row for row in (await db.scalars(select(Firm).where(Firm.id.in_(firm_ids)))).all()} if firm_ids else {}
    experts = {row.id: row for row in (await db.scalars(select(Expert).where(Expert.id.in_(expert_ids)))).all()} if expert_ids else {}
    matches_by_search: dict[UUID, list[CandidateMatchResponse]] = defaultdict(list)
    for row in matches:
        candidate = firms.get(row.firm_id) if row.firm_id else experts.get(row.expert_id)
        if candidate is None:
            continue
        # A match can only name a candidate that was visible when captured. Network/private
        # fields are already narrowed to the safe response projection below.
        decision = latest_decision.get(row.id)
        latest_review = CandidateReviewResponse(
            decision_id=decision.id, candidate_search_run_id=decision.candidate_search_run_id,
            candidate_match_id=decision.candidate_match_id, decision=decision.decision,
            corrected_contribution=decision.corrected_contribution, reason=decision.reason,
            actor_membership_id=decision.actor_membership_id, created_at=decision.created_at,
        ) if decision else None
        matches_by_search[row.candidate_search_run_id].append(CandidateMatchResponse(
            candidate_match_id=row.id, gap_id=row.gap_id,
            candidate_kind="FIRM" if row.firm_id else "EXPERT",
            candidate_id=candidate.id, candidate_name=candidate.display_name,
            candidate_scope=candidate.scope, candidate_evidence_state=candidate.evidence_state,
            proposed_contribution=row.proposed_contribution,
            strongest_evidence=row.strongest_evidence, relevant_evidence=row.relevant_evidence,
            missing_or_weak_evidence=row.missing_or_weak_evidence,
            qualification_state=row.qualification_state, rationale=row.rationale,
            provenance=row.provenance, retrieval_rank=row.retrieval_rank,
            latest_review=latest_review,
        ))
    stale = await _stale_search_runs(
        db, organization_id=organization_id, pursuit_id=pursuit_id, searches=searches
    )
    return [CandidateSearchRunResponse(
        candidate_search_run_id=row.id, organization_id=row.organization_id, pursuit_id=row.pursuit_id,
        analysis_run_id=row.analysis_run_id, gap_id=row.gap_id, target_kind=row.target_kind,
        requirement_id=row.requirement_id, position_id=row.position_id,
        review_assertion_id=row.review_assertion_id,
        effective_coverage_state=row.effective_coverage_state,
        effective_review_state=row.effective_review_state,
        resolution_category=row.resolution_category, contribution_rule=row.contribution_rule,
        search_version=row.search_version, search_parameters=row.search_parameters,
        result_limit=row.result_limit, status=row.status, created_at=row.created_at,
        completed_at=row.completed_at, is_stale=stale[row.id][0], stale_reason=stale[row.id][1],
        matches=matches_by_search[row.id],
    ) for row in searches]


async def list_candidate_searches(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
) -> list[CandidateSearchRunResponse]:
    rows = list((await db.scalars(
        select(CandidateSearchRun).where(
            CandidateSearchRun.organization_id == organization_id,
            CandidateSearchRun.pursuit_id == pursuit_id,
        ).order_by(CandidateSearchRun.created_at.desc(), CandidateSearchRun.id.desc()).limit(50)
    )).all())
    return await _project_searches(db, organization_id=organization_id, pursuit_id=pursuit_id, searches=rows)


async def get_candidate_search(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, search_run_id: UUID,
) -> CandidateSearchRunResponse | None:
    row = await db.scalar(select(CandidateSearchRun).where(
        CandidateSearchRun.id == search_run_id,
        CandidateSearchRun.organization_id == organization_id,
        CandidateSearchRun.pursuit_id == pursuit_id,
    ))
    if row is None:
        return None
    results = await _project_searches(db, organization_id=organization_id, pursuit_id=pursuit_id, searches=[row])
    return results[0]


async def append_candidate_review(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
    search_run_id: UUID, match_id: UUID, membership_id: UUID,
    request: CandidateReviewRequest,
) -> CandidateReviewResponse:
    search = await db.scalar(select(CandidateSearchRun).where(
        CandidateSearchRun.id == search_run_id,
        CandidateSearchRun.organization_id == organization_id,
        CandidateSearchRun.pursuit_id == pursuit_id,
    ))
    if search is None:
        raise CandidateNotFoundError("Candidate search run not found")
    match = await db.scalar(select(CandidateMatch).where(
        CandidateMatch.id == match_id, CandidateMatch.candidate_search_run_id == search.id,
    ))
    if match is None:
        raise CandidateNotFoundError("Candidate match not found")
    latest = await db.scalar(
        select(CandidateReviewDecision).where(CandidateReviewDecision.candidate_match_id == match.id)
        .order_by(CandidateReviewDecision.created_at.desc(), CandidateReviewDecision.id.desc()).limit(1)
    )
    row = CandidateReviewDecision(
        organization_id=organization_id, candidate_search_run_id=search.id,
        candidate_match_id=match.id, actor_membership_id=membership_id,
        supersedes_decision_id=latest.id if latest else None,
        decision=request.decision, corrected_contribution=request.corrected_contribution,
        reason=request.reason.strip(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return CandidateReviewResponse(
        decision_id=row.id, candidate_search_run_id=row.candidate_search_run_id,
        candidate_match_id=row.candidate_match_id, decision=row.decision,
        corrected_contribution=row.corrected_contribution, reason=row.reason,
        actor_membership_id=row.actor_membership_id, created_at=row.created_at,
    )

