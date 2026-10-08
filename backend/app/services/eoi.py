"""D2-05 Expression of Interest: passive suggestions, immutable drafts, staleness, downloads.

Every factual statement in a draft comes from a recorded fact (company profile,
the organization's own firm and its project references, partner firms and their
references, readiness records) or from a notice quote held by the analysis run.
The manifest stores each rendered fact with the id of its source. No pricing is
read or written. The only generated text is the optional relevance note, which is
validated against its inputs and labelled as a draft note in the document.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.private_storage import resolve_private_storage_key
from app.models.all_models import CompanyProfile, ReadinessDocument, Tender
from app.models.base import MembershipState
from app.models.candidate_retrieval import Firm, ProjectReference
from app.models.eoi import EoiDraft, EoiDraftArtifact
from app.models.private_documents import PursuitTenderContext
from app.models.pursuit_analysis import AnalysisPack, AnalysisRun
from app.models.tenancy import Membership, Organization, OrganizationPursuit
from app.schemas.eoi import (
    EoiArtifactResponse,
    EoiCriterion,
    EoiDefaults,
    EoiDraftCreateRequest,
    EoiDraftResponse,
    EoiDraftSummary,
    EoiLocator,
    EoiNote,
    EoiPartnerFirm,
    EoiReference,
    EoiSuggestionsResponse,
)
from app.services.candidate_retrieval import reference_evidence_basis
from app.services.eoi_document import docx_bytes, pdf_bytes
from app.services.eoi_notes import NoteRequest, ProviderCall, generate_relevance_notes
from app.services.own_experience import is_experience_requirement, match_own_references, requirement_statement
from app.services.private_documents import build_analysis_pack_candidate
from app.services.pursuit_analysis import company_evidence_state, get_analysis_run


MANIFEST_SCHEMA = "d2-05.eoi-manifest.v1"
MEDIA_TYPES = {
    "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "PDF": "application/pdf",
}
REGISTRATION_DOCUMENT_TYPES = {"registration_document"}

STALE_NEWER_ANALYSIS = "NEWER_ANALYSIS_RUN"
STALE_INPUTS_CHANGED = "ANALYSIS_INPUTS_CHANGED"
STALE_REFERENCE_SUPERSEDED = "REFERENCE_SUPERSEDED"
STALE_REFERENCE_ARCHIVED = "REFERENCE_ARCHIVED"


class EoiError(ValueError):
    pass


class EoiNotFoundError(EoiError):
    pass


class EoiConflictError(EoiError):
    pass


# ---- shared reads -----------------------------------------------------------------------------------

async def _pursuit(db: AsyncSession, organization_id: UUID, pursuit_id: UUID) -> OrganizationPursuit:
    pursuit = await db.get(OrganizationPursuit, pursuit_id)
    if pursuit is None or pursuit.organization_id != organization_id:
        raise EoiNotFoundError("Pursuit not found")
    return pursuit


async def _completed_run(db: AsyncSession, organization_id: UUID, pursuit_id: UUID, run_id: UUID) -> AnalysisRun:
    run = await db.scalar(select(AnalysisRun).where(
        AnalysisRun.id == run_id, AnalysisRun.organization_id == organization_id, AnalysisRun.pursuit_id == pursuit_id,
    ))
    if run is None:
        raise EoiNotFoundError("Analysis run not found")
    if run.status != "COMPLETED":
        raise EoiConflictError("The analysis run is not COMPLETED")
    return run


def _reference_facts(row: ProjectReference) -> dict[str, Any]:
    return {
        "id": str(row.id), "reference_id": str(row.id), "firm_id": str(row.firm_id),
        "project_name": row.project_name, "client_name": row.client_name, "country": row.country,
        "sector": row.sector, "service": row.service, "role": row.role,
        "contract_share_percent": str(row.contract_share_percent) if row.contract_share_percent is not None else None,
        "contract_value": str(row.contract_value) if row.contract_value is not None else None,
        "contract_currency": row.contract_currency, "value_basis": row.value_basis,
        "start_date": row.start_date.isoformat() if row.start_date else None,
        "completion_date": row.completion_date.isoformat() if row.completion_date else None,
        "completion_state": row.completion_state, "relevant_scope": row.relevant_scope,
        "evidence_state": row.evidence_state, "evidence_basis": reference_evidence_basis(row.evidence_provenance),
    }


async def _current_references(db: AsyncSession, firm_ids: list[UUID]) -> list[ProjectReference]:
    if not firm_ids:
        return []
    return list((await db.scalars(
        select(ProjectReference)
        .where(ProjectReference.firm_id.in_(firm_ids), ProjectReference.archived_at.is_(None))
        .order_by(ProjectReference.created_at, ProjectReference.id)
    )).all())


async def _successors(db: AsyncSession, ids: set[UUID]) -> dict[UUID, UUID]:
    """Each superseded reference id mapped to its latest successor (edits are supersedes)."""
    mapping: dict[UUID, UUID] = {}
    frontier = set(ids)
    for _ in range(20):
        if not frontier:
            break
        rows = (await db.execute(
            select(ProjectReference.supersedes_reference_id, ProjectReference.id)
            .where(ProjectReference.supersedes_reference_id.in_(frontier))
        )).all()
        step = {old: new for old, new in rows}
        for original, current in list(mapping.items()):
            if current in step:
                mapping[original] = step[current]
        for old, new in step.items():
            if old in ids:
                mapping[old] = new
        frontier = set(step.values())
    return mapping


LATER_STAGE_SCOPES = frozenset({"CONTRACT_EXECUTION", "POST_AWARD_OBLIGATION", "LATER_STAGE"})
# Requirement-type words that describe the consultant's tasks, not its qualifications.
_ASSIGNMENT_TYPE_TOKENS = frozenset({
    "SCOPE", "TASK", "TASKS", "DUTY", "DUTIES", "DELIVERABLE", "DELIVERABLES", "OBLIGATION", "OBLIGATIONS",
    "ACTIVITY", "ACTIVITIES", "OUTPUT", "OUTPUTS", "WORKPLAN", "TOR",
})
# ...unless the type also names a qualification ("SIMILAR_SCOPE_EXPERIENCE").
_QUALIFICATION_TYPE_TOKENS = frozenset({
    "EXPERIENCE", "QUALIFICATION", "QUALIFICATIONS", "ELIGIBILITY", "CAPACITY", "CAPABILITY", "CAPABILITIES",
    "LICENSE", "LICENCE", "LICENSING", "CERTIFICATION", "CERTIFICATE", "REGISTRATION", "FINANCIAL", "TURNOVER",
    "PERSONNEL", "STAFF", "REFERENCE", "REFERENCES", "TRACK", "RECORD", "EVALUATION", "SHORTLISTING",
})
# "The Consultant shall prepare …": a duty of the assignment, phrased as an obligation on the consultant.
_DUTY_WORDING = re.compile(
    r"^\W*(?:the\s+)?(?:selected\s+|successful\s+)?(?:consultants?|consulting\s+firm|firm|contractor)\s+"
    r"(?:shall|will|would|must|is\s+(?:expected|required)\s+to|are\s+(?:expected|required)\s+to)\s+"
    r"(?:also\s+)?(?:be\s+responsible\s+for\s+)?"
    r"(?:prepar|carry\s+out|carrie|conduct|undertak|perform|develop|design|review|supervis|assist|support|deliver|"
    r"implement|monitor|coordinat|ensur|produc|updat|draft|survey|establish|train|facilitat|manag|"
    r"provide\s+(?:services|support|assistance|technical\s+assistance|advice|training|inputs))",
    re.IGNORECASE,
)


# Participation and eligibility rules: who may take part and on what terms, not what the firm
# has done. They stay in Requirements/notes but are not shortlisting criteria of the EOI.
_PARTICIPATION_WORDING = re.compile(
    r"\bassociat\w*\s+with\s+other\s+firms\b|\bjoint(?:ly)?\s+and\s+several(?:ly)?\b|"
    r"\bjoint[\s-]+ventures?\b[^.;]{0,120}?\b(?:liab\w*|form|indicate|partners?|lead\s+member)\b|\bsub-?consultancy\b|"
    r"\bconflicts?\s+of\s+interest\b|\b(?:in)?eligib\w*\b|\bnationality\b|\bnationals?\s+of\b|\bcountry\s+of\s+origin\b|"
    r"\bfraud\w*\b|\bcorrupt\w*\b|\bsanction\w*\b|\bdebar\w*\b|\bprocurement\s+regulations\b|\banti-?corruption\b",
    re.IGNORECASE,
)
_PARTICIPATION_LABELS = (
    frozenset({"JOINT", "VENTURE"}), frozenset({"CONSORTIUM"}), frozenset({"CONFLICT"}), frozenset({"INTEGRITY"}),
    frozenset({"ETHICS"}), frozenset({"FRAUD"}), frozenset({"CORRUPTION"}), frozenset({"SANCTION"}),
    frozenset({"SANCTIONS"}), frozenset({"DEBARMENT"}), frozenset({"NATIONALITY"}),
)


def is_participation_rule(requirement: Any) -> bool:
    """A JV/association, conflict-of-interest, eligibility/nationality or fraud-and-corruption rule.

    An experience requirement that mentions a joint venture ("JV members may combine
    experience in similar contracts") is not one: it still asks for experience.
    """
    statement = " ".join(part for part in (requirement.original_quote, requirement.effective_normalized_requirement) if part)
    labels = {token for value in (requirement.category, requirement.requirement_type)
              for token in re.split(r"[^A-Z0-9]+", (value or "").upper()) if token}
    if not (_PARTICIPATION_WORDING.search(statement) or any(group <= labels for group in _PARTICIPATION_LABELS)):
        return False
    return not is_experience_requirement(requirement.category, requirement.requirement_type, statement)


def is_eoi_criterion(requirement: Any) -> bool:
    """Whether a requirement belongs in the EOI as a shortlisting criterion.

    Excluded: later-stage obligations (by coverage or stage scope), participation and
    eligibility rules (``is_participation_rule``), and duties of the assignment itself —
    requirement types naming tasks/scope/deliverables, or a quote worded as an obligation
    on the consultant to perform work. Deterministic; no AI.
    """
    if requirement.effective_coverage_state == "LATER_STAGE_OBLIGATION":
        return False
    if (requirement.stage_scope or "").upper() in LATER_STAGE_SCOPES:
        return False
    if is_participation_rule(requirement):
        return False
    tokens = {token for token in re.split(r"[^A-Z0-9]+", (requirement.requirement_type or "").upper()) if token}
    if tokens & _QUALIFICATION_TYPE_TOKENS:
        return True
    if tokens & _ASSIGNMENT_TYPE_TOKENS:
        return False
    text = " ".join(part for part in (requirement.original_quote, requirement.effective_normalized_requirement) if part)
    if is_experience_requirement(requirement.category, requirement.requirement_type, text):
        return True
    quotes = (requirement.original_quote or "", requirement.effective_normalized_requirement or "")
    return not any(_DUTY_WORDING.search(value) for value in quotes)


def eoi_criteria(requirements: list[Any]) -> list[Any]:
    return [item for item in requirements if is_eoi_criterion(item)]


def _criterion_text(requirement: Any) -> str:
    parts = (requirement.effective_normalized_requirement, requirement.original_quote, requirement.source_context)
    return " ".join(part for part in parts if part)


def _matches(
    criteria: list[Any], references: list[dict[str, Any]], recorded: dict[UUID, set[str]], as_of: date,
) -> dict[str, list[str]]:
    """reference id -> requirement ids it addresses (in criteria order).

    The run's recorded matches (mapped to the reference's current version) plus the
    same deterministic rule applied now, so references recorded after the analysis count.
    """
    by_reference: dict[str, set[str]] = defaultdict(set)
    known = {item["id"] for item in references}
    for criterion in criteria:
        requirement_id = str(criterion.requirement_id)
        statement = requirement_statement(criterion.effective_normalized_requirement, criterion.original_quote)
        if not is_experience_requirement(criterion.category, criterion.requirement_type, statement):
            continue  # matches an older run recorded outside the experience scope are not offered either
        for reference_id in recorded.get(criterion.requirement_id, set()):
            if reference_id in known:
                by_reference[reference_id].add(requirement_id)
        text = _criterion_text(criterion)
        if references:
            match = match_own_references(text=text, predicate=criterion.predicate, references=references, as_of=as_of)
            for reference_id in match.reference_ids:
                by_reference[reference_id].add(requirement_id)
    order = {str(criterion.requirement_id): index for index, criterion in enumerate(criteria)}
    return {key: sorted(values, key=order.__getitem__) for key, values in by_reference.items()}


def _ranked(references: list[dict[str, Any]], matched: dict[str, list[str]]) -> list[EoiReference]:
    def recency(item: dict[str, Any]) -> int:
        value = item.get("completion_date") or item.get("start_date")
        return date.fromisoformat(value).toordinal() if value else 0

    ordered = sorted(references, key=lambda item: (
        -len(matched.get(item["id"], [])), -recency(item), item["project_name"].casefold(), item["id"],
    ))
    return [EoiReference(
        **{key: value for key, value in item.items() if key not in {"id", "firm_id"}},
        matched_requirement_ids=matched.get(item["id"], []),
        suggested=bool(matched.get(item["id"])), rank=rank,
    ) for rank, item in enumerate(ordered, start=1)]


async def _defaults(
    db: AsyncSession, organization_id: UUID, pursuit: OrganizationPursuit, self_firm: Firm | None,
) -> tuple[EoiDefaults, dict[str, str]]:
    """Defaults and, for each, where it came from."""
    from app.api.endpoints.tenders import _contact_submission_response

    context = await db.get(PursuitTenderContext, pursuit.id)
    tender = await db.get(Tender, pursuit.source_tender_id) if pursuit.source_tender_id else None
    contact = _contact_submission_response(tender, source_url=tender.source_url, include_metadata=True) if tender else None
    organization = await db.get(Organization, organization_id)
    profile = await db.get(CompanyProfile, organization.legacy_company_profile_id) if organization else None

    def first(*pairs: tuple[Any, str]) -> tuple[str, str]:
        for value, source in pairs:
            if value and str(value).strip():
                return " ".join(str(value).split()), source
        return "", "NOT_RECORDED"

    title, title_source = first((getattr(context, "title", None), "PURSUIT_CONTEXT"),
                                (getattr(tender, "title", None), "SOURCE_TENDER"))
    reference, reference_source = first((getattr(context, "reference", None), "PURSUIT_CONTEXT"),
                                        (getattr(tender, "external_id", None), "SOURCE_TENDER"))
    buyer, buyer_source = first((getattr(context, "buyer", None), "PURSUIT_CONTEXT"),
                                (getattr(contact, "buyer_agency", None), "SOURCE_TENDER"),
                                (getattr(tender, "buyer", None), "SOURCE_TENDER"))
    firm_name, firm_source = first((getattr(self_firm, "display_name", None), "SELF_FIRM"),
                                   (getattr(organization, "display_name", None), "ORGANIZATION"),
                                   (getattr(profile, "company_name", None), "COMPANY_PROFILE"))
    defaults = EoiDefaults(
        assignment_title=title, reference_no=reference, addressee_organization=buyer,
        addressee_name=getattr(contact, "contact_person", None) or None,
        addressee_email=getattr(contact, "email", None) or None,
        firm_name=firm_name, firm_country=getattr(self_firm, "country", None) or None,
    )
    sources = {"assignment_title": title_source, "reference_no": reference_source,
               "addressee_organization": buyer_source, "firm_name": firm_source}
    return defaults, sources


async def _run_current(db: AsyncSession, organization_id: UUID, pursuit_id: UUID, run: AnalysisRun) -> list[str]:
    reasons: list[str] = []
    newer = await db.scalar(select(func.count(AnalysisRun.id)).where(
        AnalysisRun.organization_id == organization_id, AnalysisRun.pursuit_id == pursuit_id,
        AnalysisRun.status == "COMPLETED", AnalysisRun.created_at > run.created_at,
    ))
    if newer:
        reasons.append(STALE_NEWER_ANALYSIS)
    pack = await db.get(AnalysisPack, run.pack_id)
    current = await build_analysis_pack_candidate(db, organization_id=organization_id, pursuit_id=pursuit_id)
    if pack is None or current.candidate_sha256 != pack.candidate_sha256:
        reasons.append(STALE_INPUTS_CHANGED)
    return reasons


async def _partner_firms(db: AsyncSession, organization_id: UUID) -> list[Firm]:
    return list((await db.scalars(
        select(Firm).where(
            Firm.scope == "ORGANIZATION_PRIVATE", Firm.owner_organization_id == organization_id,
            Firm.organization_id.is_(None),
        ).order_by(Firm.display_name, Firm.id)
    )).all())


async def _suggestion_data(db: AsyncSession, organization_id: UUID, pursuit_id: UUID, run: AnalysisRun) -> dict[str, Any]:
    analysis = await get_analysis_run(db, organization_id=organization_id, pursuit_id=pursuit_id, run_id=run.id)
    if analysis is None:
        raise EoiNotFoundError("Analysis run not found")
    self_firm = await db.scalar(select(Firm).where(Firm.organization_id == organization_id))
    partners = await _partner_firms(db, organization_id)
    own_rows = await _current_references(db, [self_firm.id] if self_firm else [])
    partner_rows = await _current_references(db, [firm.id for firm in partners])
    recorded_ids = {value for item in analysis.requirements for value in item.matched_reference_ids}
    successors = await _successors(db, recorded_ids)
    recorded = {
        item.requirement_id: {str(successors.get(value, value)) for value in item.matched_reference_ids}
        for item in analysis.requirements
    }
    as_of = datetime.now(timezone.utc).date()
    own = [_reference_facts(row) for row in own_rows]
    partner_refs = [_reference_facts(row) for row in partner_rows]
    criteria = eoi_criteria(analysis.requirements)
    own_matches = _matches(criteria, own, recorded, as_of)
    partner_matches = _matches(criteria, partner_refs, {}, as_of)
    return {
        "analysis": analysis, "criteria": criteria, "self_firm": self_firm, "partners": partners, "own": own,
        "partner_refs": partner_refs, "own_matches": own_matches, "partner_matches": partner_matches,
        "recorded": recorded,
    }


# ---- suggestions (passive) --------------------------------------------------------------------------

async def eoi_suggestions(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, analysis_run_id: UUID,
) -> EoiSuggestionsResponse:
    """Everything the EOI builder needs, read only. No AI, no writes."""
    pursuit = await _pursuit(db, organization_id, pursuit_id)
    run = await _completed_run(db, organization_id, pursuit_id, analysis_run_id)
    data = await _suggestion_data(db, organization_id, pursuit_id, run)
    analysis = data["analysis"]
    defaults, _ = await _defaults(db, organization_id, pursuit, data["self_firm"])
    reasons = await _run_current(db, organization_id, pursuit_id, run)
    evidence = await company_evidence_state(db, organization_id=organization_id, run_id=run.id)
    own_ids_by_requirement: dict[str, list[str]] = defaultdict(list)
    for reference_id, requirement_ids in data["own_matches"].items():
        for requirement_id in requirement_ids:
            own_ids_by_requirement[requirement_id].append(reference_id)
    criteria = [EoiCriterion(
        requirement_id=item.requirement_id, statement=item.effective_normalized_requirement,
        original_quote=item.original_quote,
        locator=EoiLocator(
            page_number=(item.source_locator or {}).get("page_number"),
            paragraph_number=(item.source_locator or {}).get("paragraph_number"),
        ),
        effective_coverage_state=item.effective_coverage_state,
        matched_reference_ids=sorted(own_ids_by_requirement.get(str(item.requirement_id), [])),
    ) for item in data["criteria"]]
    notes = [EoiNote(
        requirement_id=item.requirement_id, note_kind=item.note_kind,
        statement=item.effective_normalized_requirement, original_quote=item.original_quote,
    ) for item in analysis.submission_and_notes]
    refs_by_firm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in data["partner_refs"]:
        refs_by_firm[item["firm_id"]].append(item)
    partner_firms = []
    for firm in data["partners"]:
        references = _ranked(refs_by_firm[str(firm.id)], data["partner_matches"])
        covers = {value for reference in references for value in reference.matched_requirement_ids}
        order = [criterion.requirement_id for criterion in criteria]
        partner_firms.append(EoiPartnerFirm(
            firm_id=firm.id, display_name=firm.display_name, country=firm.country, references=references,
            covers_requirement_ids=[value for value in order if value in covers],
        ))
    return EoiSuggestionsResponse(
        analysis_run_id=run.id, run_current=not reasons, defaults=defaults, criteria=criteria, notes=notes,
        company_evidence_changed=evidence.changed,
        company_evidence_change_reason=evidence.reason,
        company_evidence_changed_sections=list(evidence.sections),
        own_references=_ranked(data["own"], data["own_matches"]), partner_firms=partner_firms,
    )


# ---- drafts -------------------------------------------------------------------------------------------

def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


async def _active_membership(db: AsyncSession, organization_id: UUID, membership_id: UUID) -> None:
    membership = await db.get(Membership, membership_id)
    if membership is None or membership.organization_id != organization_id or membership.state != MembershipState.ACTIVE:
        raise EoiNotFoundError("Pursuit not found")


def _profile(firm: Firm | None, profile: CompanyProfile | None, name: str) -> list[dict[str, Any]]:
    firm_source = {"type": "SELF_FIRM" if firm is not None and firm.organization_id else "PARTNER_FIRM",
                   "id": str(firm.id)} if firm else None
    profile_source = {"type": "COMPANY_PROFILE", "id": str(profile.id)} if profile else None
    items = [{"field": "name", "value": name, "source": firm_source or profile_source}]

    def add(field: str, value: Any, source: dict[str, Any] | None) -> None:
        if value not in (None, "", []):
            items.append({"field": field, "value": value, "source": source})

    if firm is not None:
        add("legal_name", firm.legal_name, firm_source)
        add("country", firm.country, firm_source)
        add("services", [str(item) for item in firm.services], firm_source)
        add("sectors", [str(item) for item in firm.sectors], firm_source)
        add("regions", [str(item) for item in firm.regions], firm_source)
    if profile is not None:
        add("website", profile.website, profile_source)
    return items


async def create_eoi_draft(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, membership_id: UUID,
    request: EoiDraftCreateRequest, note_call: ProviderCall | None = None,
) -> EoiDraftResponse:
    await _active_membership(db, organization_id, membership_id)
    pursuit = await _pursuit(db, organization_id, pursuit_id)
    run = await _completed_run(db, organization_id, pursuit_id, request.analysis_run_id)
    data = await _suggestion_data(db, organization_id, pursuit_id, run)
    self_firm: Firm | None = data["self_firm"]
    own_by_id = {item["id"]: item for item in data["own"]}
    for reference_id in request.own_reference_ids:
        if str(reference_id) not in own_by_id:
            raise EoiConflictError("A selected reference is archived or is not the organization's own firm's")
    partners_by_id = {firm.id: firm for firm in data["partners"]}
    partner_refs = {item["id"]: item for item in data["partner_refs"]}
    for selection in request.partners:
        if self_firm is not None and selection.firm_id == self_firm.id:
            raise EoiConflictError("The organization's own firm cannot be a partner")
        firm = partners_by_id.get(selection.firm_id)
        if firm is None:
            raise EoiConflictError("A selected partner firm is not one of the organization's private partner firms")
        for reference_id in selection.reference_ids:
            item = partner_refs.get(str(reference_id))
            if item is None or item["firm_id"] != str(firm.id):
                raise EoiConflictError("A selected partner reference is archived or does not belong to that firm")

    defaults, default_sources = await _defaults(db, organization_id, pursuit, self_firm)
    organization = await db.get(Organization, organization_id)
    profile = await db.get(CompanyProfile, organization.legacy_company_profile_id) if organization else None
    lead_name = defaults.firm_name or "—"

    rows: list[dict[str, Any]] = []
    for reference_id in request.own_reference_ids:
        item = own_by_id[str(reference_id)]
        rows.append({**item, "firm_name": lead_name, "eoi_role": "LEAD", "recorded_role": item["role"],
                     "matched": data["own_matches"].get(item["id"], [])})
    partner_sections = []
    for selection in request.partners:
        firm = partners_by_id[selection.firm_id]
        partner_sections.append({
            "firm_id": str(firm.id), "display_name": firm.display_name, "role": selection.role,
            "profile": _profile(firm, None, firm.display_name),
        })
        for reference_id in selection.reference_ids:
            item = partner_refs[str(reference_id)]
            rows.append({**item, "firm_name": firm.display_name, "eoi_role": selection.role,
                         "recorded_role": item["role"], "matched": data["partner_matches"].get(item["id"], [])})
    for number, row in enumerate(rows, start=1):
        row["no"] = number

    criteria = data["criteria"]
    statements = {str(item.requirement_id): item.effective_normalized_requirement for item in criteria}
    note_outcome = None
    if request.include_relevance_notes:
        note_requests = [NoteRequest(
            key=row["no"], criterion_id=row["matched"][0], criterion_statement=statements[row["matched"][0]],
            reference=row, language=request.language,
        ) for row in rows if row["matched"]]
        note_outcome = await generate_relevance_notes(note_requests, note_call)

    experience = []
    for row in rows:
        note = note_outcome.notes.get(row["no"]) if note_outcome else None
        experience.append({
            "no": row["no"], "reference_id": row["reference_id"], "firm_id": row["firm_id"],
            "firm_name": row["firm_name"], "eoi_role": row["eoi_role"], "recorded_role": row["recorded_role"],
            **{key: row[key] for key in (
                "project_name", "client_name", "country", "sector", "service", "start_date", "completion_date",
                "completion_state", "contract_value", "contract_currency", "value_basis", "contract_share_percent",
                "relevant_scope", "evidence_state", "evidence_basis",
            )},
            "addresses_requirement_ids": row["matched"],
            "source": {"type": "PROJECT_REFERENCE", "id": row["reference_id"]},
            "relevance_note": {
                "text": note, "criterion_id": row["matched"][0], "source": {"type": "GENERATED_DRAFT_NOTE"},
            } if note else None,
        })
    criteria_rows = []
    for item in criteria:
        requirement_id = str(item.requirement_id)
        criteria_rows.append({
            "requirement_id": requirement_id, "statement": item.effective_normalized_requirement,
            "original_quote": item.original_quote,
            "locator": {"page_number": (item.source_locator or {}).get("page_number"),
                        "paragraph_number": (item.source_locator or {}).get("paragraph_number")},
            "addressed_by": [row["no"] for row in rows if requirement_id in row["matched"]],
            "source": {"type": "NOTICE_QUOTE", "id": requirement_id, "analysis_run_id": str(run.id)},
        })
    notes = [{
        "requirement_id": str(item.requirement_id), "note_kind": item.note_kind,
        "statement": item.effective_normalized_requirement, "original_quote": item.original_quote,
        "source": {"type": "NOTICE_QUOTE", "id": str(item.requirement_id)},
    } for item in data["analysis"].submission_and_notes]
    documents = [{
        "kind": "REFERENCE_PROOF", "row": row["no"], "name": row["project_name"], "reference_id": row["reference_id"],
        "status": "ON_RECORD" if row["evidence_basis"] == "FILE_BACKED" else "TO_ATTACH",
    } for row in rows]
    readiness = list((await db.scalars(select(ReadinessDocument).where(
        ReadinessDocument.company_profile_id == profile.id,
        ReadinessDocument.document_type.in_(REGISTRATION_DOCUMENT_TYPES),
    ).order_by(ReadinessDocument.document_name, ReadinessDocument.id))).all()) if profile else []
    documents += [{
        "kind": "REGISTRATION", "name": item.document_name, "readiness_document_id": str(item.id),
        "status": "ON_RECORD" if item.optional_file_url and item.status == "available" else "TO_ATTACH",
    } for item in readiness] or [{"kind": "REGISTRATION", "name": None, "status": "TO_ATTACH"}]

    addressed = sum(1 for item in criteria_rows if item["addressed_by"])
    summary = EoiDraftSummary(
        criteria_total=len(criteria_rows), criteria_with_references=addressed,
        criteria_without_references=len(criteria_rows) - addressed,
        own_reference_count=len(request.own_reference_ids), partner_count=len(request.partners),
        relevance_notes_generated=note_outcome.generated if note_outcome else 0,
        relevance_notes_dropped=note_outcome.dropped if note_outcome else 0,
    )
    letter = request.letter.model_dump()
    manifest = {
        "schema_version": MANIFEST_SCHEMA, "language": request.language,
        "analysis_run_id": str(run.id), "pursuit_id": str(pursuit_id),
        "notice": {
            "assignment_title": {"value": defaults.assignment_title, "source": default_sources["assignment_title"]},
            "reference_no": {"value": defaults.reference_no, "source": default_sources["reference_no"]},
        },
        "letter": {**letter, "source": "USER_INPUT"},
        "lead": {
            "firm_id": str(self_firm.id) if self_firm else None, "display_name": lead_name,
            "profile": _profile(self_firm, profile, lead_name),
        },
        "partners": partner_sections, "experience": experience, "criteria": criteria_rows,
        "notes": notes, "supporting_documents": documents, "summary": summary.model_dump(),
        "price_information_included": False,
    }
    manifest_sha = hashlib.sha256(_canonical(manifest)).hexdigest()
    inputs = request.model_dump(mode="json")

    contents = {"DOCX": docx_bytes(manifest), "PDF": pdf_bytes(manifest)}
    # Serialize versions per pursuit.
    await db.execute(select(OrganizationPursuit.id).where(OrganizationPursuit.id == pursuit_id).with_for_update())
    version = int(await db.scalar(select(func.max(EoiDraft.version)).where(EoiDraft.pursuit_id == pursuit_id)) or 0) + 1
    draft_id = uuid4()
    written: list[Path] = []
    try:
        draft = EoiDraft(
            id=draft_id, organization_id=organization_id, pursuit_id=pursuit_id, analysis_run_id=run.id,
            version=version, language=request.language, inputs=inputs, manifest=manifest,
            manifest_sha256=manifest_sha, created_by_membership_id=membership_id,
        )
        db.add(draft)
        await db.flush()
        for fmt, content in contents.items():
            artifact_id = uuid4()
            storage_key = f"eoi/{organization_id.hex}/{pursuit_id.hex}/{draft_id.hex}/{artifact_id.hex}.bin"
            written.append(_write_private(storage_key, content))
            db.add(EoiDraftArtifact(
                id=artifact_id, organization_id=organization_id, draft_id=draft_id, format=fmt,
                storage_key=storage_key, content_sha256=hashlib.sha256(content).hexdigest(),
                byte_size=len(content), media_type=MEDIA_TYPES[fmt],
            ))
        await _stage_draft_ready(db, organization_id, pursuit, draft_id, version, membership_id)
        await db.commit()
    except Exception:
        await db.rollback()
        for path in written:
            path.unlink(missing_ok=True)
        raise
    response = await get_eoi_draft(db, organization_id=organization_id, pursuit_id=pursuit_id, draft_id=draft_id)
    if response is None:
        raise RuntimeError("The EOI draft could not be read back")
    return response


async def _stage_draft_ready(
    db: AsyncSession, organization_id: UUID, pursuit: OrganizationPursuit, draft_id: UUID, version: int,
    membership_id: UUID,
) -> None:
    """R3 Task 4: the creator and the pursuit owner hear that the draft is ready."""
    from app.services.notifications import stage_system_outbox

    memberships = {membership_id, *([pursuit.owner_membership_id] if pursuit.owner_membership_id else [])}
    user_ids = set((await db.scalars(
        select(Membership.user_id).where(
            Membership.id.in_(memberships), Membership.organization_id == organization_id,
            Membership.state == MembershipState.ACTIVE,
        )
    )).all())
    for user_id in sorted(user_ids, key=str):
        await stage_system_outbox(
            db, user_id=user_id, event_type="EOI_DRAFT_READY",
            payload={
                "organization_id": str(organization_id), "pursuit_id": str(pursuit.id),
                "eoi_draft_id": str(draft_id), "version_number": int(version),
            },
            dedupe_key=f"eoi-draft:{draft_id}:{user_id}",
        )


def _write_private(storage_key: str, content: bytes) -> Path:
    target = resolve_private_storage_key(storage_key)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.exists():
        raise EoiConflictError("Private artifact storage identity already exists")
    staged: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix="eoi-", suffix=".tmp", delete=False) as stream:
            staged = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, target)
        target.chmod(0o600)
        return target
    except Exception:
        if staged is not None:
            staged.unlink(missing_ok=True)
        raise


# ---- projections --------------------------------------------------------------------------------------

async def _project(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, drafts: list[EoiDraft],
) -> list[EoiDraftResponse]:
    if not drafts:
        return []
    artifacts = list((await db.scalars(select(EoiDraftArtifact).where(
        EoiDraftArtifact.draft_id.in_([draft.id for draft in drafts]),
    ).order_by(EoiDraftArtifact.format))).all())
    by_draft: dict[UUID, list[EoiDraftArtifact]] = defaultdict(list)
    for artifact in artifacts:
        by_draft[artifact.draft_id].append(artifact)
    runs = {row.id: row for row in (await db.scalars(select(AnalysisRun).where(
        AnalysisRun.id.in_({draft.analysis_run_id for draft in drafts}),
    ))).all()}
    latest_completed = await db.scalar(select(func.max(AnalysisRun.created_at)).where(
        AnalysisRun.organization_id == organization_id, AnalysisRun.pursuit_id == pursuit_id,
        AnalysisRun.status == "COMPLETED",
    ))
    current = await build_analysis_pack_candidate(db, organization_id=organization_id, pursuit_id=pursuit_id)
    packs = {row.id: row.candidate_sha256 for row in (await db.scalars(select(AnalysisPack).where(
        AnalysisPack.id.in_({run.pack_id for run in runs.values()}),
    ))).all()}
    selected: set[UUID] = set()
    for draft in drafts:
        selected.update(UUID(value) for value in draft.inputs.get("own_reference_ids", []))
        for partner in draft.inputs.get("partners", []):
            selected.update(UUID(value) for value in partner.get("reference_ids", []))
    archived = {row.id for row in (await db.scalars(select(ProjectReference).where(
        ProjectReference.id.in_(selected), ProjectReference.archived_at.is_not(None),
    ))).all()} if selected else set()
    superseded = set((await db.scalars(select(ProjectReference.supersedes_reference_id).where(
        ProjectReference.supersedes_reference_id.in_(archived),
    ))).all()) if archived else set()

    responses = []
    for draft in drafts:
        run = runs[draft.analysis_run_id]
        reasons: list[str] = []
        if latest_completed and latest_completed > run.created_at:
            reasons.append(STALE_NEWER_ANALYSIS)
        if packs.get(run.pack_id) != current.candidate_sha256:
            reasons.append(STALE_INPUTS_CHANGED)
        ids = {UUID(value) for value in draft.inputs.get("own_reference_ids", [])}
        for partner in draft.inputs.get("partners", []):
            ids.update(UUID(value) for value in partner.get("reference_ids", []))
        if ids & superseded:
            reasons.append(STALE_REFERENCE_SUPERSEDED)
        if (ids & archived) - superseded:
            reasons.append(STALE_REFERENCE_ARCHIVED)
        responses.append(EoiDraftResponse(
            draft_id=draft.id, version=draft.version, created_at=draft.created_at,
            created_by_membership_id=draft.created_by_membership_id, analysis_run_id=draft.analysis_run_id,
            language=draft.language, current=not reasons, stale_reasons=reasons,
            artifacts=[EoiArtifactResponse(
                artifact_id=item.id, format=item.format, sha256=item.content_sha256, byte_size=item.byte_size,
            ) for item in by_draft[draft.id]],
            summary=EoiDraftSummary(**draft.manifest["summary"]),
        ))
    return responses


async def list_eoi_drafts(db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID) -> list[EoiDraftResponse]:
    await _pursuit(db, organization_id, pursuit_id)
    drafts = list((await db.scalars(select(EoiDraft).where(
        EoiDraft.organization_id == organization_id, EoiDraft.pursuit_id == pursuit_id,
    ).order_by(EoiDraft.version.desc()))).all())
    return await _project(db, organization_id=organization_id, pursuit_id=pursuit_id, drafts=drafts)


async def get_eoi_draft(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, draft_id: UUID,
) -> EoiDraftResponse | None:
    draft = await db.scalar(select(EoiDraft).where(
        EoiDraft.id == draft_id, EoiDraft.organization_id == organization_id, EoiDraft.pursuit_id == pursuit_id,
    ))
    if draft is None:
        return None
    return (await _project(db, organization_id=organization_id, pursuit_id=pursuit_id, drafts=[draft]))[0]


async def resolve_eoi_artifact(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, artifact_id: UUID, membership_id: UUID,
) -> tuple[EoiDraftArtifact, EoiDraft, Path]:
    await _active_membership(db, organization_id, membership_id)
    row = (await db.execute(
        select(EoiDraftArtifact, EoiDraft)
        .join(EoiDraft, and_(EoiDraft.id == EoiDraftArtifact.draft_id, EoiDraft.organization_id == EoiDraftArtifact.organization_id))
        .where(EoiDraftArtifact.id == artifact_id, EoiDraftArtifact.organization_id == organization_id,
               EoiDraft.pursuit_id == pursuit_id)
    )).one_or_none()
    if row is None:
        raise EoiNotFoundError("EOI artifact not found")
    artifact, draft = row
    path = resolve_private_storage_key(artifact.storage_key)
    if not path.is_file() or path.stat().st_size != artifact.byte_size:
        raise EoiNotFoundError("EOI artifact bytes are unavailable")
    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact.content_sha256:
        raise EoiConflictError("EOI artifact integrity check failed")
    return artifact, draft, path
