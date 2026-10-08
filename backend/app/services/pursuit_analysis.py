"""W4 pack admission, durable analysis, projections, review, and lineage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents import pursuit_analyzer
from app.core.analysis_languages import resolve_analysis_language
from app.models.candidate_retrieval import Firm, ProjectReference
from app.models.company import Certification, CompanyProfile, FinancialHistory, License, ReadinessDocument
from app.models.private_documents import DocumentProcessingJob, DocumentProcessingResult, DocumentVersion, PrivateDocument
from app.models.pursuit_analysis import (
    AnalysisCompanySnapshot,
    AnalysisItemLineage,
    AnalysisPack,
    AnalysisPackItem,
    AnalysisReviewAssertion,
    AnalysisRun,
    PursuitGap,
    PursuitPosition,
    PursuitRequirement,
)
from app.models.all_models import TenderDocument
from app.models.tenancy import Membership, Organization, OrganizationPursuit
from app.schemas.tenancy import (
    AnalysisLineageRequest,
    AnalysisLineageResponse,
    AnalysisReviewAssertionRequest,
    AnalysisReviewAssertionResponse,
    PursuitAnalysisPackItemResponse,
    PursuitAnalysisResponse,
    PursuitAnalysisStartRequest,
    PursuitAnalysisStartResponse,
    PursuitGapResponse,
    PursuitPositionResponse,
    PursuitRequirementResponse,
    PursuitSubmissionNoteResponse,
)
from app.services.candidate_retrieval import reference_evidence_basis
from app.services.own_experience import (
    is_experience_requirement, match_own_references, note_kind, requirement_statement,
)
from app.services.private_documents import build_analysis_pack_candidate


PACK_SCHEMA_VERSION = "pursuit_analysis_pack_w4_v1"
PAGE_LIMIT = 500
# Conservative equivalence: 500 pages at no more than 3,000 extracted characters/page.
UNKNOWN_PAGE_CHARACTER_LIMIT = 1_500_000
LEASE_SECONDS = 300
PROCUREMENT_SIGNALS = (
    "QUALIFICATIONS",
    "REQUIRED",
    "MUST",
    "SHALL",
    "MINIMUM",
    "BIDDER",
    "PROPOSAL",
    "SUBMIT",
    "REFERENCES",
    "DEADLINE",
)


PROVIDER_UNAVAILABLE_MESSAGE = "The analysis provider is temporarily unavailable. Plasma has been notified."


def classify_analysis_failure(exc: Exception) -> tuple[str, str | None]:
    """Customer-safe failure_reason and an operator code for an extraction exception.

    Provider account/billing rejections never reach the customer as raw detail.
    Everything else keeps the existing behavior (the exception text, bounded).
    """
    if isinstance(exc, pursuit_analyzer.ProviderAccountError):
        return PROVIDER_UNAVAILABLE_MESSAGE, exc.code
    if isinstance(exc, pursuit_analyzer.RunBudgetExceeded):
        return str(exc)[:1000], exc.code
    return str(exc)[:1000], None


def is_terminal_analysis_failure(exc: Exception) -> bool:
    """Failures that no further run attempt can fix (provider account or billing rejection)."""
    return isinstance(exc, pursuit_analyzer.ProviderAccountError)


class AnalysisAdmissionError(ValueError):
    """Selection cannot be sealed into a safe FULL analysis pack."""


class AnalysisNotFoundError(LookupError):
    pass


def assess_extraction_quality(
    texts: list[str],
    *,
    requirement_count: int,
    position_count: int,
    failed: bool = False,
) -> tuple[str, str, dict[str, Any]]:
    """Assess coverage without inventing findings or re-running extraction."""
    character_count = sum(len(value) for value in texts)
    signal_counts = {
        signal: min(
            50,
            sum(len(re.findall(rf"\b{re.escape(signal)}\b", value, re.IGNORECASE)) for value in texts),
        )
        for signal in PROCUREMENT_SIGNALS
    }
    distinct_signals = sum(bool(count) for count in signal_counts.values())
    finding_count = requirement_count + position_count
    materially_non_empty = character_count >= 500
    procurement_likely = materially_non_empty and distinct_signals >= 3
    expected_minimum = 2 if character_count >= 4_000 and distinct_signals >= 5 else 1
    diagnostics = {
        "input_character_count": character_count,
        "procurement_signal_counts": signal_counts,
        "distinct_procurement_signal_count": distinct_signals,
        "materially_non_empty": materially_non_empty,
        "procurement_likely": procurement_likely,
        "minimum_expected_finding_count": expected_minimum,
        "finding_count": finding_count,
    }
    if failed:
        return "FAILED", "The analysis worker failed before a reviewable extraction was available.", diagnostics
    if finding_count == 0:
        return (
            "NEEDS_ATTENTION",
            "Plasma processed the document but did not identify enough procurement requirements to produce a reliable gap assessment.",
            diagnostics,
        )
    if procurement_likely and finding_count < expected_minimum:
        return (
            "NEEDS_ATTENTION",
            "The document contains multiple procurement signals, but the extracted coverage is implausibly sparse.",
            diagnostics,
        )
    return "READY_FOR_REVIEW", "Extraction is materially populated and ready for human review.", diagnostics


def _sha(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _processing_result_hash(result: DocumentProcessingResult) -> str:
    return _sha(
        {
            "id": str(result.id),
            "job_id": str(result.job_id),
            "document_version_id": str(result.document_version_id),
            "malware_scan_status": result.malware_scan_status,
            "page_count": result.page_count,
            "page_count_status": result.page_count_status,
            "extracted_sha256": result.extracted_sha256,
            "parser_name": result.parser_name,
            "parser_version": result.parser_version,
            "extraction_error_code": result.extraction_error_code,
        }
    )


async def _company_snapshot(db: AsyncSession, organization_id: UUID) -> tuple[UUID, dict[str, Any], int, int]:
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise AnalysisAdmissionError("Organization no longer exists")
    profile = await db.get(CompanyProfile, organization.legacy_company_profile_id)
    if profile is None:
        raise AnalysisAdmissionError("Company profile no longer exists")
    certifications = list((await db.scalars(select(Certification).where(Certification.company_id == profile.id))).all())
    licenses = list((await db.scalars(select(License).where(License.company_id == profile.id))).all())
    financial = list((await db.scalars(select(FinancialHistory).where(FinancialHistory.company_id == profile.id))).all())
    readiness = list((await db.scalars(select(ReadinessDocument).where(ReadinessDocument.company_profile_id == profile.id))).all())
    self_firm = await db.scalar(select(Firm).where(Firm.organization_id == organization_id))
    own_references = list((await db.scalars(
        select(ProjectReference)
        .where(ProjectReference.firm_id == self_firm.id, ProjectReference.archived_at.is_(None))
        .order_by(ProjectReference.created_at, ProjectReference.id)
    )).all()) if self_firm else []
    profile_fields = {
        key: _json_value(getattr(profile, key))
        for key in (
            "company_name", "director_name", "address", "phone_contact", "bank_name",
            "mfo", "account_number", "inn", "industry", "website", "target_regions",
            "target_countries", "target_services", "notes",
        )
    }
    snapshot = {
        "truth_notice": "Recorded organization claims; a file reference does not mean its contents were verified.",
        "profile": {"id": str(profile.id), "evidence_basis": "METADATA_ONLY", **profile_fields},
        "certifications": [
            {"id": str(row.id), "cert_type": row.cert_type, "issue_date": row.issue_date.isoformat(), "expiry_date": row.expiry_date.isoformat(), "evidence_basis": "METADATA_ONLY"}
            for row in certifications
        ],
        "licenses": [
            {"id": str(row.id), "license_name": row.license_name, "is_active": row.is_active, "evidence_basis": "METADATA_ONLY"}
            for row in licenses
        ],
        "financial_history": [
            {"id": str(row.id), "year": row.year, "turnover_uzs": row.turnover_uzs, "evidence_basis": "METADATA_ONLY"}
            for row in financial
        ],
        "readiness_documents": [
            {
                "id": str(row.id), "document_type": row.document_type, "document_name": row.document_name,
                "document_number": row.document_number, "issuer": row.issuer,
                "issue_date": _json_value(row.issue_date), "expiry_date": _json_value(row.expiry_date),
                "status": row.status, "related_service": row.related_service, "notes": row.notes,
                "file_reference": row.optional_file_url,
                "evidence_basis": "FILE_BACKED" if row.optional_file_url else "METADATA_ONLY",
            }
            for row in readiness
        ],
        # The organization's own firm and its current project references (D2-01).
        "self_firm": {"id": str(self_firm.id), "display_name": self_firm.display_name} if self_firm else None,
        "own_project_references": [_own_reference_snapshot(row) for row in own_references],
    }
    file_backed = sum(1 for row in readiness if row.optional_file_url) + sum(
        1 for item in snapshot["own_project_references"] if item["evidence_basis"] == "FILE_BACKED"
    )
    metadata_only = (
        1 + len(certifications) + len(licenses) + len(financial) + len(readiness)
        + len(own_references) - file_backed
    )
    return profile.id, snapshot, metadata_only, file_backed


# R3 Task 2: which recorded company evidence a sealed run used, by banner section.
COMPANY_EVIDENCE_SECTIONS: dict[str, tuple[str, ...]] = {
    "OWN_EXPERIENCE": ("self_firm", "own_project_references"),
    "COMPANY_PROFILE": ("profile",),
    "READINESS_RECORDS": ("readiness_documents", "certifications", "licenses", "financial_history"),
}
COMPANY_EVIDENCE_REASONS = {
    "OWN_EXPERIENCE": "Your own firm or its project references changed since this analysis.",
    "COMPANY_PROFILE": "Your company profile changed since this analysis.",
    "READINESS_RECORDS": "Your readiness documents, certifications, licenses or financial records changed since this analysis.",
}


@dataclass(frozen=True)
class CompanyEvidenceState:
    changed: bool
    reason: str | None = None
    sections: tuple[str, ...] = ()


def _section_value(snapshot: dict[str, Any], key: str, *, sealed: bool) -> Any:
    value = snapshot.get(key)
    # A run sealed before a section existed recorded nothing for it: an empty current
    # value is no change.
    if sealed and key not in snapshot:
        return None
    return value or None


def compare_company_evidence(sealed_sha256: str, sealed: dict[str, Any], current: dict[str, Any]) -> CompanyEvidenceState:
    """Pure comparison of a run's sealed company snapshot with the current records."""
    if _sha(current) == sealed_sha256:
        return CompanyEvidenceState(changed=False)
    sections = tuple(
        name for name, keys in COMPANY_EVIDENCE_SECTIONS.items()
        if any(
            _sha(_section_value(sealed, key, sealed=True)) != _sha(_section_value(current, key, sealed=False))
            for key in keys
        )
    )
    if not sections:
        return CompanyEvidenceState(changed=False)
    return CompanyEvidenceState(changed=True, reason=COMPANY_EVIDENCE_REASONS[sections[0]], sections=sections)


async def company_evidence_state(db: AsyncSession, *, organization_id: UUID, run_id: UUID) -> CompanyEvidenceState:
    """Passive: recompute the company snapshot (reads only) and compare with the sealed one."""
    sealed = await db.scalar(select(AnalysisCompanySnapshot).where(AnalysisCompanySnapshot.analysis_run_id == run_id))
    if sealed is None:
        return CompanyEvidenceState(changed=False)
    try:
        _, current, _, _ = await _company_snapshot(db, organization_id)
    except AnalysisAdmissionError:
        return CompanyEvidenceState(changed=False)
    return compare_company_evidence(sealed.snapshot_sha256, sealed.snapshot_json, current)


def _own_reference_snapshot(row: ProjectReference) -> dict[str, Any]:
    return {
        "id": str(row.id), "project_name": row.project_name, "client_name": row.client_name,
        "country": row.country, "sector": row.sector, "service": row.service, "role": row.role,
        "start_date": _json_value(row.start_date), "completion_date": _json_value(row.completion_date),
        "completion_state": row.completion_state,
        "contract_value": str(row.contract_value) if row.contract_value is not None else None,
        "contract_currency": row.contract_currency, "value_basis": row.value_basis,
        "contract_share_percent": str(row.contract_share_percent) if row.contract_share_percent is not None else None,
        "relevant_scope": row.relevant_scope, "evidence_state": row.evidence_state,
        "evidence_basis": reference_evidence_basis(row.evidence_provenance),
    }


async def create_analysis_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    pursuit_id: UUID,
    membership_id: UUID,
    request: PursuitAnalysisStartRequest,
) -> PursuitAnalysisStartResponse:
    """Revalidate a reviewed selection, seal it, snapshot company claims, and persist a job."""
    membership = await db.get(Membership, membership_id)
    if membership is None or membership.organization_id != organization_id or membership.state.value != "ACTIVE":
        raise AnalysisAdmissionError("An active organization Membership is required")
    pursuit = await db.get(OrganizationPursuit, pursuit_id)
    if pursuit is None or pursuit.organization_id != organization_id:
        raise AnalysisNotFoundError("Pursuit not found")

    candidate = await build_analysis_pack_candidate(db, organization_id=organization_id, pursuit_id=pursuit_id)
    if candidate.candidate_sha256 != request.candidate_sha256:
        raise AnalysisAdmissionError("Analysis inputs changed after review; reload the pack and review the selection again")
    source_ids = request.source_document_ids
    private_ids = request.private_version_ids
    if not source_ids and not private_ids:
        raise AnalysisAdmissionError("Select at least one document for analysis")
    if len(set(source_ids)) != len(source_ids) or len(set(private_ids)) != len(private_ids):
        raise AnalysisAdmissionError("The selection contains a duplicate document identity")
    source_candidates = {item.tender_document_id: item for item in candidate.source_documents}
    private_candidates = {item.document_version_id: item for item in candidate.private_versions}
    if any(item_id not in source_candidates for item_id in source_ids) or any(item_id not in private_candidates for item_id in private_ids):
        raise AnalysisAdmissionError("The submitted selection is not part of the reviewed candidate")
    selected_candidates = [*(source_candidates[item_id] for item_id in source_ids), *(private_candidates[item_id] for item_id in private_ids)]
    unready = [item.display_name for item in selected_candidates if not item.parse_ready]
    if unready:
        raise AnalysisAdmissionError("FULL analysis requires READY, complete, malware-clean text: " + ", ".join(unready))

    language = resolve_analysis_language(request.analysis_language, None).value
    sealed_items: list[dict[str, Any]] = []
    for source_id in source_ids:
        snapshot = source_candidates[source_id]
        row = await db.get(TenderDocument, source_id)
        if row is None or pursuit.source_tender_id is None or row.tender_id != pursuit.source_tender_id:
            raise AnalysisAdmissionError("A selected source document is no longer accessible")
        analyzed_text = row.parsed_text or ""
        text_hash = hashlib.sha256(analyzed_text.encode()).hexdigest()
        if text_hash != snapshot.analyzed_text_sha256:
            raise AnalysisAdmissionError("A selected source snapshot changed after review")
        sealed_items.append(
            {
                "item_kind": "SOURCE", "provenance": "SHARED_SOURCE", "display_name": snapshot.display_name,
                "role": snapshot.role, "file_type": snapshot.file_type, "tender_document_id": row.id,
                "identity_sha256": snapshot.snapshot_sha256, "content_sha256": snapshot.content_sha256,
                "analyzed_text": analyzed_text, "analyzed_text_sha256": text_hash,
                "source_url": snapshot.source_url, "captured_at": snapshot.captured_at,
                "page_count": snapshot.page_count, "page_count_known": snapshot.page_count_known,
                "locator_type": "PAGE" if snapshot.page_count_known else "PARAGRAPH",
                "locator_metadata": {"rendered_page_count_measurable": snapshot.page_count_known},
            }
        )

    for version_id in private_ids:
        snapshot = private_candidates[version_id]
        row = (
            await db.execute(
                select(PrivateDocument, DocumentVersion, DocumentProcessingJob, DocumentProcessingResult)
                .join(DocumentVersion, DocumentVersion.private_document_id == PrivateDocument.id)
                .join(DocumentProcessingJob, DocumentProcessingJob.document_version_id == DocumentVersion.id)
                .join(DocumentProcessingResult, DocumentProcessingResult.document_version_id == DocumentVersion.id)
                .where(
                    PrivateDocument.organization_id == organization_id,
                    PrivateDocument.pursuit_id == pursuit_id,
                    PrivateDocument.state == "ACTIVE",
                    PrivateDocument.current_version_id == DocumentVersion.id,
                    DocumentVersion.id == version_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise AnalysisAdmissionError("A selected private version is no longer the reviewed current version")
        document, version, job, result = row
        analyzed_text = result.extracted_text or ""
        text_hash = hashlib.sha256(analyzed_text.encode()).hexdigest()
        result_hash = _processing_result_hash(result)
        if (
            version.sha256 != snapshot.content_sha256
            or result.id != snapshot.processing_result_id
            or result_hash != snapshot.processing_result_sha256
            or result.extracted_sha256 != text_hash
            or result.malware_scan_status != "CLEAN"
            or job.state.value != "READY"
        ):
            raise AnalysisAdmissionError("A selected private version or processing result changed after review")
        sealed_items.append(
            {
                "item_kind": "PRIVATE", "provenance": "ORGANIZATION_PRIVATE_UPLOAD",
                "display_name": document.display_name, "role": document.role.value, "file_type": version.media_type,
                "private_document_id": document.id, "document_version_id": version.id,
                "version_number": version.version_number, "processing_result_id": result.id,
                "processing_result_sha256": result_hash,
                "identity_sha256": _sha(["PRIVATE", str(version.id), version.sha256, str(result.id), result_hash]),
                "content_sha256": version.sha256, "analyzed_text": analyzed_text,
                "analyzed_text_sha256": text_hash, "source_url": None, "captured_at": result.updated_at,
                "page_count": result.page_count, "page_count_known": result.page_count_status == "KNOWN",
                "locator_type": "PAGE" if result.page_count_status == "KNOWN" else "PARAGRAPH",
                "locator_metadata": {"parser_name": result.parser_name, "parser_version": result.parser_version, "rendered_page_count_measurable": result.page_count_status == "KNOWN"},
            }
        )

    total_known_pages = sum(int(item["page_count"] or 0) for item in sealed_items)
    page_count_known = all(bool(item["page_count_known"]) for item in sealed_items)
    character_count = sum(len(item["analyzed_text"]) for item in sealed_items)
    if total_known_pages > PAGE_LIMIT:
        raise AnalysisAdmissionError(f"Selected PDFs total {total_known_pages} pages; the FULL analysis limit is {PAGE_LIMIT}")
    if not page_count_known and character_count > UNKNOWN_PAGE_CHARACTER_LIMIT:
        raise AnalysisAdmissionError(
            f"Rendered page count is unknown and extracted content has {character_count} characters; "
            f"reduce the pack below the safe {UNKNOWN_PAGE_CHARACTER_LIMIT}-character alternate limit"
        )
    disclosure = (
        f"Exact rendered page total {total_known_pages}/{PAGE_LIMIT}."
        if page_count_known
        else f"Rendered page count could not be measured for one or more inputs; FULL analysis admitted under the documented {UNKNOWN_PAGE_CHARACTER_LIMIT}-character alternate limit ({character_count} selected)."
    )
    selection_payload = {
        "schema_version": PACK_SCHEMA_VERSION,
        "candidate_sha256": candidate.candidate_sha256,
        "analysis_language": language,
        "items": [{key: _json_value(value) for key, value in item.items() if key != "analyzed_text"} for item in sealed_items],
    }
    selected_sha = _sha(selection_payload)
    pack = AnalysisPack(
        organization_id=organization_id, pursuit_id=pursuit_id, requested_by_membership_id=membership_id,
        schema_version=PACK_SCHEMA_VERSION, candidate_sha256=candidate.candidate_sha256,
        selected_pack_sha256=selected_sha, analysis_language=language, admission_decision="ADMITTED",
        total_known_pages=total_known_pages, page_count_known=page_count_known, page_limit=PAGE_LIMIT,
        alternate_character_count=character_count if not page_count_known else 0,
        alternate_character_limit=UNKNOWN_PAGE_CHARACTER_LIMIT, limit_disclosure=disclosure,
    )
    db.add(pack)
    await db.flush()
    for ordinal, values in enumerate(sealed_items, start=1):
        db.add(AnalysisPackItem(pack_id=pack.id, ordinal=ordinal, **values))

    run = AnalysisRun(
        organization_id=organization_id, pursuit_id=pursuit_id, pack_id=pack.id,
        requested_by_membership_id=membership_id, analysis_language=language, status="QUEUED",
        model_provider=pursuit_analyzer.MODEL_PROVIDER,
        model_name=pursuit_analyzer.route_for(character_count).models[0],
        prompt_version=pursuit_analyzer.PROMPT_VERSION, prompt_sha256=pursuit_analyzer.PROMPT_SHA256,
        schema_version=pursuit_analyzer.SCHEMA_VERSION, pipeline_version=pursuit_analyzer.PIPELINE_VERSION,
    )
    db.add(run)
    await db.flush()
    profile_id, snapshot, metadata_only, file_backed = await _company_snapshot(db, organization_id)
    captured_at = datetime.now(timezone.utc)
    db.add(
        AnalysisCompanySnapshot(
            analysis_run_id=run.id, legacy_company_profile_id=profile_id,
            snapshot_json=snapshot, snapshot_sha256=_sha(snapshot), metadata_only_count=metadata_only,
            file_backed_count=file_backed, captured_at=captured_at,
        )
    )
    await db.commit()
    return PursuitAnalysisStartResponse(
        analysis_run_id=run.id, analysis_pack_id=pack.id, status=run.status,
        selected_pack_sha256=selected_sha, page_count_known=page_count_known,
        total_known_pages=total_known_pages, limit_disclosure=disclosure,
    )


NOTE_RATIONALES = {
    "INFORMATIONAL": "An informational statement: it asks nothing of the bidder, so no company evidence is expected.",
    "SUBMISSION_INSTRUCTION": "A submission instruction (how, where or when to submit): followed when submitting, not proven with company evidence.",
}


@dataclass(frozen=True)
class RequirementAssessment:
    coverage: str
    rationale: str
    matched_reference_ids: tuple[str, ...] = ()
    note_kind: str | None = None


@dataclass(frozen=True)
class OwnExperienceMatchResult:
    ids: tuple[str, ...]
    rationale: str

    @classmethod
    def empty(cls) -> "OwnExperienceMatchResult":
        return cls((), "")


def _coverage_for_requirement(
    fact: pursuit_analyzer.ExtractedFact, snapshot: dict[str, Any], *, as_of: date | None = None,
) -> tuple[str, str]:
    assessment = _assess_requirement(fact, snapshot, as_of=as_of)
    return assessment.coverage, assessment.rationale


def _assess_requirement(
    fact: pursuit_analyzer.ExtractedFact, snapshot: dict[str, Any], *, as_of: date | None = None,
) -> RequirementAssessment:
    """Deterministic coverage of one corporate requirement; no AI.

    Order: later-stage duty, informational/submission note (no evidence expected),
    human interpretation, the organization's own project references (experience
    requirements only; PARTIAL at most), readiness records, else EVIDENCE_MISSING.
    """
    scope = fact.stage_scope.upper()
    if scope in {"CONTRACT_EXECUTION", "POST_AWARD_OBLIGATION", "LATER_STAGE"}:
        return RequirementAssessment("LATER_STAGE_OBLIGATION", "The cited duty applies after the current bid decision.")
    kind = note_kind(fact.distinction, fact.requirement_type)
    if kind:
        return RequirementAssessment("NOT_APPLICABLE", NOTE_RATIONALES[kind], note_kind=kind)
    own = OwnExperienceMatchResult.empty()
    references = snapshot.get("own_project_references") or []
    text = " ".join(value for value in (fact.normalized_text, fact.original_quote, fact.source_context) if value)
    statement = requirement_statement(fact.normalized_text, fact.original_quote)
    if references and is_experience_requirement(fact.category, fact.requirement_type, statement):
        predicate = fact.predicate.model_dump(exclude_none=True) if fact.predicate else None
        match = match_own_references(
            text=text, predicate=predicate, references=references,
            as_of=as_of or datetime.now(timezone.utc).date(),
        )
        if match.matched:
            own = OwnExperienceMatchResult(tuple(match.reference_ids), match.rationale())
    interpretation = _interpretation_needed(fact)
    if interpretation:
        rationale = interpretation + (f" {own.rationale}" if own.ids else "")
        return RequirementAssessment("NEEDS_INTERPRETATION", rationale, own.ids)
    if own.ids:
        return RequirementAssessment("PARTIAL", own.rationale, own.ids)
    coverage, rationale = _coverage_from_readiness(fact, snapshot)
    return RequirementAssessment(coverage, rationale)


def _interpretation_needed(fact: pursuit_analyzer.ExtractedFact) -> str | None:
    if fact.complex_rule:
        return "The cited rule is conditional or complex and requires a human interpretation."
    contribution = (fact.contribution_rule or "").casefold()
    if contribution and any(term in contribution for term in ("unclear", "ambiguous", "interpret")):
        return "Contribution eligibility is not explicit enough for an automatic conclusion."
    if contribution and any(term in contribution for term in ("joint venture", "consortium", "member", "subconsultant")):
        clearly_lead_only = any(term in contribution for term in ("lead only", "lead firm", "must be met by the lead"))
        clearly_shared = any(term in contribution for term in ("any member", "combined", "collectively", "partner may"))
        if not clearly_lead_only and not clearly_shared:
            return "The issued document mentions a contributor but does not resolve lead/member eligibility."
    return None


def _coverage_from_readiness(fact: pursuit_analyzer.ExtractedFact, snapshot: dict[str, Any]) -> tuple[str, str]:
    needle = fact.normalized_text.casefold()
    readiness = snapshot.get("readiness_documents", [])
    generic_terms = {
        "applicant", "bidder", "company", "consultant", "document", "evidence",
        "provide", "requirement", "required", "shall", "submit", "tender",
    }
    for record in readiness:
        haystack = " ".join(str(record.get(key) or "") for key in ("document_type", "document_name", "document_number", "issuer", "related_service", "notes")).casefold()
        keywords = {
            word for word in re_words(needle)
            if len(word) >= 5 and word not in generic_terms
        }
        matched = {word for word in keywords if word in haystack}
        # Prefer a false-negative EVIDENCE_MISSING result over a weak lexical
        # match that could invent company support for an unrelated record.
        strong_match = len(matched) >= 2 or any(len(word) >= 10 for word in matched)
        if strong_match:
            if record.get("status") in {"missing", "expired"}:
                return "GAP", "A matching recorded company item explicitly indicates missing or expired support."
            if record.get("status") == "available" and record.get("evidence_basis") == "FILE_BACKED":
                return "PARTIAL", "A matching file-backed record exists, but W4 has not verified that its contents prove this requirement."
            return "PARTIAL", "A matching recorded claim exists, but it is metadata-only or incomplete."
    return "EVIDENCE_MISSING", "No current company record proves or disproves this requirement."


def re_words(value: str) -> list[str]:
    import re
    return re.findall(r"[^\W\d_]+", value, flags=re.UNICODE)


def _gap_resolution(coverage: str, contribution_rule: str | None, *, position: bool) -> str:
    if position:
        return "EXPERT"
    if coverage == "NEEDS_INTERPRETATION":
        return "HUMAN_INTERPRETATION"
    rule = (contribution_rule or "").casefold()
    if rule and any(term in rule for term in ("joint venture", "consortium", "member", "subconsultant")):
        if any(term in rule for term in ("lead only", "lead firm", "must be met by the lead")):
            return "COMPANY_EVIDENCE"
        if any(term in rule for term in ("any member", "combined", "collectively", "partner may")):
            return "PARTNER_FIRM"
        return "HUMAN_INTERPRETATION"
    return "COMPANY_EVIDENCE"


def _coverage_for_position(fact: pursuit_analyzer.ExtractedFact) -> tuple[str, str, str]:
    if fact.stage_scope.upper() in {"CONTRACT_EXECUTION", "POST_AWARD_OBLIGATION", "LATER_STAGE"}:
        return "LATER_STAGE_OBLIGATION", "EXPERT", "The cited role applies after the current bid decision."
    ambiguous = fact.complex_rule or bool(
        fact.contribution_rule
        and any(term in fact.contribution_rule.casefold() for term in ("unclear", "ambiguous", "interpret"))
    )
    if ambiguous:
        return (
            "NEEDS_INTERPRETATION",
            "HUMAN_INTERPRETATION",
            "The RFP permits an individual and/or firm, so a reviewer must confirm how the role applies before candidate matching.",
        )
    return (
        "EVIDENCE_MISSING",
        "EXPERT",
        "No personal CV evidence is inferred from corporate records; expert matching begins in W5.",
    )


async def process_analysis_run(db: AsyncSession, run_id: UUID, *, worker_id: str) -> None:
    """Lease and execute one durable run. Replays are terminally idempotent."""
    now = datetime.now(timezone.utc)
    run = (
        await db.scalars(select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update())
    ).one_or_none()
    if run is None or run.status in {"COMPLETED", "FAILED"}:
        return
    if run.status == "RUNNING" and run.lease_until and run.lease_until > now and run.lease_owner != worker_id:
        return
    if run.attempt_count >= run.max_attempts:
        run.status = "FAILED"
        run.failure_stage = "LEASE"
        run.failure_reason = "Retry limit exhausted before a worker could complete the run"
        run.completed_at = now
        await db.commit()
        return
    run.status = "RUNNING"
    run.attempt_count += 1
    run.started_at = run.started_at or now
    run.lease_owner = worker_id
    run.heartbeat_at = now
    run.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    await db.commit()

    input_texts: list[str] = []
    input_page_count = 0
    input_page_count_known = False
    try:
        items = list((await db.scalars(select(AnalysisPackItem).where(AnalysisPackItem.pack_id == run.pack_id).order_by(AnalysisPackItem.ordinal))).all())
        # Retain only primitive, count-safe diagnostics before provider work.
        # A rollback expires ORM instances, so failure handling must not read
        # AnalysisPackItem attributes after the rollback boundary.
        input_texts = [item.analyzed_text for item in items]
        input_page_count = sum(int(item.page_count or 0) for item in items)
        input_page_count_known = bool(items) and all(item.page_count_known for item in items)
        sealed = [
            pursuit_analyzer.SealedTextInput(
                item.id,
                item.display_name,
                item.analyzed_text,
                page_count=item.page_count,
                page_count_known=item.page_count_known,
            )
            for item in items
        ]
        facts = await pursuit_analyzer.analyze_pack_items(sealed, run.analysis_language)
        analyzer_diagnostics = dict(getattr(facts, "diagnostics", {}))
        if not analyzer_diagnostics:
            analyzer_diagnostics = {
                "raw_requirement_count": sum(item.fact.kind == "CORPORATE_REQUIREMENT" for item in facts),
                "raw_position_count": sum(item.fact.kind == "POSITION" for item in facts),
                "schema_rejected_count": 0,
                "provenance_rejected_count": 0,
                "normalization_dropped_count": 0,
                "duplicate_count": 0,
            }
        snapshot_row = await db.scalar(select(AnalysisCompanySnapshot).where(AnalysisCompanySnapshot.analysis_run_id == run.id))
        if snapshot_row is None:
            raise RuntimeError("Company snapshot is missing")
        requirements: list[PursuitRequirement] = []
        positions: list[PursuitPosition] = []
        persisted_gap_count = 0
        note_count = 0
        own_experience_partial_count = 0
        as_of = snapshot_row.captured_at.date()
        for verified in facts:
            fact = verified.fact
            locator = {
                "char_start": verified.char_start, "char_end": verified.char_end,
                "page_number": verified.page_number, "paragraph_number": verified.paragraph_number,
                "page_number_source_verified": verified.page_number is not None,
                # How source_context was obtained: MODEL_VERBATIM, SOURCE_WINDOW (exact
                # sealed-text window replacing a non-verbatim model context) or NONE.
                "context_origin": getattr(verified, "context_origin", None)
                or ("MODEL_VERBATIM" if fact.source_context else "NONE"),
            }
            span = f"characters {verified.char_start}-{verified.char_end}"
            if fact.kind == "CORPORATE_REQUIREMENT":
                assessment = _assess_requirement(fact, snapshot_row.snapshot_json, as_of=as_of)
                coverage, rationale = assessment.coverage, assessment.rationale
                if assessment.matched_reference_ids:
                    # The self-firm references this deterministic match named (D2-01).
                    locator = {**locator, "matched_reference_ids": list(assessment.matched_reference_ids)}
                    own_experience_partial_count += coverage == "PARTIAL"
                note_count += assessment.note_kind is not None
                requirement = PursuitRequirement(
                    analysis_run_id=run.id, pack_item_id=verified.pack_item_id,
                    source_span=span, source_locator=locator, original_quote=fact.original_quote,
                    source_context=fact.source_context,
                    normalized_requirement=fact.normalized_text, category=fact.category,
                    requirement_type=fact.requirement_type, stage_scope=fact.stage_scope,
                    distinction=fact.distinction, predicate_json=fact.predicate.model_dump(exclude_none=True) if fact.predicate else None,
                    contribution_rule=fact.contribution_rule, coverage_state=coverage, review_state="PROVISIONAL",
                    extraction_confidence=fact.confidence, generated_interpretation=fact.generated_interpretation,
                )
                db.add(requirement)
                await db.flush()
                requirements.append(requirement)
                if coverage in {"PARTIAL", "GAP", "EVIDENCE_MISSING", "NEEDS_INTERPRETATION"}:
                    db.add(PursuitGap(
                        analysis_run_id=run.id, requirement_id=requirement.id,
                        source_pack_item_id=verified.pack_item_id,
                        missing_contribution=fact.normalized_text, coverage_state=coverage,
                        resolution_category=_gap_resolution(coverage, fact.contribution_rule, position=False),
                        review_state="PROVISIONAL", rationale=rationale,
                    ))
                    persisted_gap_count += 1
            else:
                position_data = fact.position
                if position_data is None:
                    continue
                coverage, position_resolution, position_rationale = _coverage_for_position(fact)
                position = PursuitPosition(
                    analysis_run_id=run.id, pack_item_id=verified.pack_item_id,
                    title=position_data.title, quantity=position_data.quantity,
                    distinction="SCORED" if fact.distinction == "SCORED" else "MANDATORY",
                    education_qualification=position_data.education_qualification,
                    general_experience=position_data.general_experience,
                    specific_experience=position_data.specific_experience,
                    relevant_assignments=position_data.relevant_assignments,
                    languages=position_data.languages, certifications=position_data.certifications,
                    location_travel=position_data.location_travel, expected_effort=position_data.expected_effort,
                    assignment_dates=position_data.assignment_dates, source_span=span,
                    qualification_criteria=[
                        criterion.model_dump() for criterion in position_data.qualification_criteria
                    ],
                    source_locator=locator, original_quote=fact.original_quote,
                    source_context=fact.source_context,
                    coverage_state=coverage, review_state="PROVISIONAL",
                    extraction_confidence=fact.confidence, generated_interpretation=fact.generated_interpretation,
                )
                db.add(position)
                await db.flush()
                positions.append(position)
                if coverage != "LATER_STAGE_OBLIGATION":
                    db.add(PursuitGap(
                        analysis_run_id=run.id, position_id=position.id,
                        source_pack_item_id=verified.pack_item_id,
                        missing_contribution=position.title, coverage_state=coverage,
                        resolution_category=position_resolution,
                        review_state="PROVISIONAL",
                        rationale=position_rationale,
                    ))
                    persisted_gap_count += 1
        run = await db.get(AnalysisRun, run_id, with_for_update=True)
        if run is None or run.status == "COMPLETED":
            await db.rollback()
            return
        run.status = "COMPLETED"
        run.result_completeness = "FULL"
        # A fallback model may have produced some chunks; record what actually did.
        accepted_model_name = analyzer_diagnostics.get("model_name")
        if accepted_model_name:
            run.model_name = str(accepted_model_name)[:200]
        quality_state, quality_summary, quality_diagnostics = assess_extraction_quality(
            input_texts,
            requirement_count=len(requirements),
            position_count=len(positions),
        )
        run.quality_state = quality_state
        run.extraction_diagnostics = {
            **analyzer_diagnostics,
            **quality_diagnostics,
            "input_page_count": input_page_count,
            "input_page_count_known": input_page_count_known,
            "persisted_requirement_count": len(requirements),
            "persisted_position_count": len(positions),
            "persisted_gap_count": persisted_gap_count,
            "submission_and_notes_count": note_count,
            "own_experience_partial_count": own_experience_partial_count,
            "quality_state": quality_state,
            "quality_summary": quality_summary,
        }
        run.completed_at = datetime.now(timezone.utc)
        run.heartbeat_at = run.completed_at
        run.lease_until = None
        run.lease_owner = None
        run.failure_stage = None
        run.failure_reason = None
        await db.commit()
    except Exception as exc:
        await db.rollback()
        run = await db.get(AnalysisRun, run_id, with_for_update=True)
        if run is not None and run.status not in {"COMPLETED", "FAILED"}:
            # A provider account/billing rejection (HTTP 401/402/403) cannot succeed on a
            # later attempt: the run is terminal at once (fix 3c). Other failures retry
            # until max_attempts as before.
            if is_terminal_analysis_failure(exc) or run.attempt_count >= run.max_attempts:
                run.status = "FAILED"
                run.completed_at = datetime.now(timezone.utc)
            else:
                run.status = "QUEUED"
                run.next_dispatch_at = datetime.now(timezone.utc) + timedelta(seconds=30)
            run.failure_stage = "EXTRACTION"
            failure_reason, failure_code = classify_analysis_failure(exc)
            run.failure_reason = failure_reason
            quality_state, quality_summary, quality_diagnostics = assess_extraction_quality(
                input_texts,
                requirement_count=0,
                position_count=0,
                failed=True,
            )
            run.quality_state = quality_state
            run.extraction_diagnostics = {
                **quality_diagnostics,
                "input_page_count": input_page_count,
                "input_page_count_known": input_page_count_known,
                "raw_requirement_count": 0,
                "raw_position_count": 0,
                "schema_rejected_count": 1 if type(exc).__name__ in {"JSONDecodeError", "ValidationError"} else 0,
                "provenance_rejected_count": 0,
                "normalization_dropped_count": 0,
                "persisted_requirement_count": 0,
                "persisted_position_count": 0,
                "persisted_gap_count": 0,
                "quality_state": quality_state,
                "quality_summary": quality_summary,
                "error_type": type(exc).__name__,
                **({"failure_code": failure_code} if failure_code else {}),
            }
            run.lease_until = None
            run.lease_owner = None
            await db.commit()
        raise


async def due_analysis_run_ids(db: AsyncSession, *, limit: int = 25) -> list[UUID]:
    now = datetime.now(timezone.utc)
    rows = list((await db.scalars(
        select(AnalysisRun)
        .where(
            AnalysisRun.attempt_count < AnalysisRun.max_attempts,
            or_(
                and_(AnalysisRun.status == "QUEUED", AnalysisRun.next_dispatch_at <= now),
                and_(AnalysisRun.status == "RUNNING", AnalysisRun.lease_until < now),
            ),
        )
        .order_by(AnalysisRun.next_dispatch_at, AnalysisRun.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )).all())
    for row in rows:
        row.dispatch_attempt_count += 1
        row.dispatched_at = now
        # Publication failure remains recoverable on the next bounded sweep.
        row.next_dispatch_at = now + timedelta(seconds=10)
    await db.commit()
    return [row.id for row in rows]


async def renew_analysis_lease(db: AsyncSession, run_id: UUID, *, worker_id: str) -> bool:
    now = datetime.now(timezone.utc)
    run = await db.scalar(
        select(AnalysisRun)
        .where(
            AnalysisRun.id == run_id,
            AnalysisRun.status == "RUNNING",
            AnalysisRun.lease_owner == worker_id,
        )
        .with_for_update()
    )
    if run is None:
        return False
    run.heartbeat_at = now
    run.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    await db.commit()
    return True


async def _latest_assertions(db: AsyncSession, run_id: UUID) -> dict[tuple[str, UUID], AnalysisReviewAssertion]:
    rows = list((await db.scalars(
        select(AnalysisReviewAssertion)
        .where(AnalysisReviewAssertion.analysis_run_id == run_id)
        .order_by(AnalysisReviewAssertion.created_at, AnalysisReviewAssertion.id)
    )).all())
    latest: dict[tuple[str, UUID], AnalysisReviewAssertion] = {}
    for row in rows:
        target_id = row.requirement_id or row.position_id or row.gap_id
        if target_id:
            latest[(row.target_kind, target_id)] = row
    return latest


async def get_analysis_run(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, run_id: UUID | None = None,
    include_company_evidence: bool = False,
) -> PursuitAnalysisResponse | None:
    """One run with effective review state. ``include_company_evidence`` (the customer
    analysis reads) also rebuilds the company snapshot to flag changed experience (R3)."""
    statement = select(AnalysisRun).where(
        AnalysisRun.organization_id == organization_id, AnalysisRun.pursuit_id == pursuit_id
    )
    if run_id is not None:
        statement = statement.where(AnalysisRun.id == run_id)
    else:
        statement = statement.order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc()).limit(1)
    run = await db.scalar(statement)
    if run is None:
        return None
    pack = await db.get(AnalysisPack, run.pack_id)
    if pack is None:
        raise RuntimeError("Sealed analysis pack is missing")
    items = list((await db.scalars(select(AnalysisPackItem).where(AnalysisPackItem.pack_id == pack.id).order_by(AnalysisPackItem.ordinal))).all())
    requirements = list((await db.scalars(select(PursuitRequirement).where(PursuitRequirement.analysis_run_id == run.id).order_by(PursuitRequirement.created_at, PursuitRequirement.id))).all())
    positions = list((await db.scalars(select(PursuitPosition).where(PursuitPosition.analysis_run_id == run.id).order_by(PursuitPosition.created_at, PursuitPosition.id))).all())
    gaps = list((await db.scalars(select(PursuitGap).where(PursuitGap.analysis_run_id == run.id).order_by(PursuitGap.created_at, PursuitGap.id))).all())
    assertions = await _latest_assertions(db, run.id)
    current = await build_analysis_pack_candidate(db, organization_id=organization_id, pursuit_id=pursuit_id)
    inputs_changed = current.candidate_sha256 != pack.candidate_sha256
    stale_reason = "Current candidate identities or content differ from the sealed pack." if inputs_changed else None
    derived_quality, derived_summary, _ = assess_extraction_quality(
        [item.analyzed_text for item in items],
        requirement_count=len(requirements),
        position_count=len(positions),
        failed=run.status == "FAILED",
    )
    quality_state = run.quality_state or derived_quality
    quality_summary = str(
        (run.extraction_diagnostics or {}).get("quality_summary") or derived_summary
    )

    def effective(kind: str, item_id: UUID, coverage: str, review: str) -> tuple[str, str]:
        assertion = assertions.get((kind, item_id))
        return (assertion.new_coverage_state, assertion.new_review_state) if assertion else (coverage, review)

    requirement_responses = []
    note_responses = []
    matched_by_requirement: dict[UUID, list[UUID]] = {}
    for item in requirements:
        coverage, review = effective("REQUIREMENT", item.id, item.coverage_state, item.review_state)
        assertion = assertions.get(("REQUIREMENT", item.id))
        effective_normalized = (
            str(assertion.corrected_fields.get("normalized_text"))
            if assertion and assertion.corrected_fields.get("normalized_text")
            else item.normalized_requirement
        )
        matched = _matched_reference_ids(item.source_locator)
        matched_by_requirement[item.id] = matched
        fields = dict(
            requirement_id=item.id, pack_item_id=item.pack_item_id, original_quote=item.original_quote,
            source_context=item.source_context,
            normalized_requirement=item.normalized_requirement,
            effective_normalized_requirement=effective_normalized, category=item.category,
            requirement_type=item.requirement_type, stage_scope=item.stage_scope, distinction=item.distinction,
            predicate=item.predicate_json, contribution_rule=item.contribution_rule,
            coverage_state=item.coverage_state, effective_coverage_state=coverage,
            review_state=item.review_state, effective_review_state=review,
            source_locator=item.source_locator, generated_interpretation=item.generated_interpretation,
            matched_reference_ids=matched,
        )
        # Machine NOT_APPLICABLE is written only for informational statements and
        # submission instructions; a reviewer who re-states coverage takes it back.
        kind = note_kind(item.distinction, item.requirement_type) if item.coverage_state == "NOT_APPLICABLE" else None
        if kind and coverage == "NOT_APPLICABLE":
            note_responses.append(PursuitSubmissionNoteResponse(**fields, note_kind=kind))
        else:
            requirement_responses.append(PursuitRequirementResponse(**fields))
    position_responses = []
    for item in positions:
        coverage, review = effective("POSITION", item.id, item.coverage_state, item.review_state)
        assertion = assertions.get(("POSITION", item.id))
        effective_title = (
            str(assertion.corrected_fields.get("normalized_text"))
            if assertion and assertion.corrected_fields.get("normalized_text")
            else item.title
        )
        position_responses.append(PursuitPositionResponse(
            position_id=item.id, pack_item_id=item.pack_item_id, title=item.title,
            effective_title=effective_title, quantity=item.quantity,
            distinction=item.distinction, education_qualification=item.education_qualification,
            general_experience=item.general_experience, specific_experience=item.specific_experience,
            relevant_assignments=item.relevant_assignments, languages=item.languages,
            certifications=item.certifications, location_travel=item.location_travel,
            expected_effort=item.expected_effort, assignment_dates=item.assignment_dates,
            qualification_criteria=item.qualification_criteria,
            original_quote=item.original_quote, coverage_state=item.coverage_state,
            source_context=item.source_context,
            effective_coverage_state=coverage, review_state=item.review_state,
            effective_review_state=review, source_locator=item.source_locator,
            generated_interpretation=item.generated_interpretation,
        ))
    gap_responses = []
    for item in gaps:
        coverage, review = effective("GAP", item.id, item.coverage_state, item.review_state)
        assertion = assertions.get(("GAP", item.id))
        effective_resolution = (
            str(assertion.corrected_fields.get("resolution_category")).upper()
            if assertion and assertion.corrected_fields.get("resolution_category")
            else item.resolution_category
        )
        gap_responses.append(PursuitGapResponse(
            gap_id=item.id, requirement_id=item.requirement_id, position_id=item.position_id,
            source_pack_item_id=item.source_pack_item_id, missing_contribution=item.missing_contribution,
            coverage_state=item.coverage_state, effective_coverage_state=coverage,
            resolution_category=item.resolution_category,
            effective_resolution_category=effective_resolution,
            review_state=item.review_state,
            effective_review_state=review, rationale=item.rationale,
            matched_reference_ids=matched_by_requirement.get(item.requirement_id, []) if item.requirement_id else [],
        ))
    evidence = (
        await company_evidence_state(db, organization_id=organization_id, run_id=run.id)
        if include_company_evidence else CompanyEvidenceState(changed=False)
    )
    return PursuitAnalysisResponse(
        company_evidence_changed=evidence.changed,
        company_evidence_change_reason=evidence.reason,
        company_evidence_changed_sections=list(evidence.sections),
        analysis_run_id=run.id, analysis_pack_id=pack.id, status=run.status,
        result_completeness=run.result_completeness, analysis_language=run.analysis_language,
        quality_state=quality_state, quality_summary=quality_summary,
        model_provider=run.model_provider, model_name=run.model_name, prompt_version=run.prompt_version,
        schema_version=run.schema_version, pipeline_version=run.pipeline_version,
        created_at=run.created_at, completed_at=run.completed_at,
        failure_stage=run.failure_stage, failure_reason=run.failure_reason,
        inputs_changed=inputs_changed, stale_reason=stale_reason,
        page_count_known=pack.page_count_known, limit_disclosure=pack.limit_disclosure,
        pack_items=[PursuitAnalysisPackItemResponse(
            pack_item_id=item.id, item_kind=item.item_kind, provenance=item.provenance,
            display_name=item.display_name, role=item.role, version_number=item.version_number,
            page_count=item.page_count, page_count_known=item.page_count_known,
            content_sha256=item.content_sha256, source_url=item.source_url,
            tender_document_id=item.tender_document_id, document_version_id=item.document_version_id,
        ) for item in items],
        requirements=requirement_responses, positions=position_responses, gaps=gap_responses,
        submission_and_notes=note_responses,
    )


def _matched_reference_ids(locator: dict[str, Any] | None) -> list[UUID]:
    values = (locator or {}).get("matched_reference_ids") or []
    result: list[UUID] = []
    for value in values:
        try:
            result.append(UUID(str(value)))
        except ValueError:
            continue
    return result


async def append_review_assertion(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, run_id: UUID,
    membership_id: UUID, request: AnalysisReviewAssertionRequest,
) -> AnalysisReviewAssertionResponse:
    run = await db.scalar(select(AnalysisRun).where(
        AnalysisRun.id == run_id, AnalysisRun.organization_id == organization_id,
        AnalysisRun.pursuit_id == pursuit_id, AnalysisRun.status == "COMPLETED",
    ))
    if run is None:
        raise AnalysisNotFoundError("Completed analysis run not found")
    model = {"REQUIREMENT": PursuitRequirement, "POSITION": PursuitPosition, "GAP": PursuitGap}[request.target_kind]
    target = await db.get(model, request.target_id)
    if target is None or target.analysis_run_id != run.id:
        raise AnalysisNotFoundError("Analysis review target not found")
    forbidden = {"original_quote", "source_span", "source_locator", "pack_item_id", "analysis_run_id"}
    if forbidden.intersection(request.corrected_fields):
        raise AnalysisAdmissionError("Source evidence and machine identity cannot be corrected in place")
    latest = await db.scalar(
        select(AnalysisReviewAssertion)
        .where(
            AnalysisReviewAssertion.analysis_run_id == run.id,
            getattr(AnalysisReviewAssertion, request.target_kind.casefold() + "_id") == request.target_id,
        )
        .order_by(AnalysisReviewAssertion.created_at.desc(), AnalysisReviewAssertion.id.desc())
        .limit(1)
    )
    prior_coverage = latest.new_coverage_state if latest else target.coverage_state
    prior_review = latest.new_review_state if latest else target.review_state
    assertion = AnalysisReviewAssertion(
        organization_id=organization_id, analysis_run_id=run.id, target_kind=request.target_kind,
        requirement_id=request.target_id if request.target_kind == "REQUIREMENT" else None,
        position_id=request.target_id if request.target_kind == "POSITION" else None,
        gap_id=request.target_id if request.target_kind == "GAP" else None,
        actor_membership_id=membership_id, supersedes_assertion_id=latest.id if latest else None,
        prior_coverage_state=prior_coverage, new_coverage_state=request.new_coverage_state,
        prior_review_state=prior_review, new_review_state=request.new_review_state,
        corrected_fields=request.corrected_fields, reason=request.reason,
    )
    db.add(assertion)
    await db.commit()
    await db.refresh(assertion)
    return AnalysisReviewAssertionResponse(
        assertion_id=assertion.id, analysis_run_id=run.id, target_kind=request.target_kind,
        target_id=request.target_id, prior_coverage_state=prior_coverage,
        new_coverage_state=assertion.new_coverage_state, prior_review_state=prior_review,
        new_review_state=assertion.new_review_state, corrected_fields=assertion.corrected_fields,
        reason=assertion.reason, actor_membership_id=membership_id, created_at=assertion.created_at,
    )


async def append_lineage(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, membership_id: UUID,
    request: AnalysisLineageRequest,
) -> AnalysisLineageResponse:
    model = PursuitRequirement if request.target_kind == "REQUIREMENT" else PursuitPosition
    prior = await db.get(model, request.prior_item_id)
    current = await db.get(model, request.current_item_id)
    if prior is None or current is None or prior.analysis_run_id == current.analysis_run_id:
        raise AnalysisAdmissionError("Lineage requires distinct items from distinct analysis runs")
    runs = list((await db.scalars(select(AnalysisRun).where(
        AnalysisRun.id.in_([prior.analysis_run_id, current.analysis_run_id]),
        AnalysisRun.organization_id == organization_id, AnalysisRun.pursuit_id == pursuit_id,
    ))).all())
    if len(runs) != 2:
        raise AnalysisNotFoundError("Lineage items not found in this pursuit")
    by_id = {row.id: row for row in runs}
    if by_id[prior.analysis_run_id].created_at >= by_id[current.analysis_run_id].created_at:
        raise AnalysisAdmissionError("Lineage must point from an older run to a newer run")
    lineage = AnalysisItemLineage(
        organization_id=organization_id, target_kind=request.target_kind,
        prior_requirement_id=request.prior_item_id if request.target_kind == "REQUIREMENT" else None,
        current_requirement_id=request.current_item_id if request.target_kind == "REQUIREMENT" else None,
        prior_position_id=request.prior_item_id if request.target_kind == "POSITION" else None,
        current_position_id=request.current_item_id if request.target_kind == "POSITION" else None,
        actor_membership_id=membership_id, rationale=request.rationale,
    )
    db.add(lineage)
    await db.commit()
    await db.refresh(lineage)
    return AnalysisLineageResponse(
        lineage_id=lineage.id, target_kind=lineage.target_kind,
        prior_item_id=request.prior_item_id, current_item_id=request.current_item_id,
        actor_membership_id=membership_id, rationale=lineage.rationale, created_at=lineage.created_at,
    )
