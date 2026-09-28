"""W6 participation commands, current-state projections, and stale-chain guards."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import re
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import MembershipState
from app.models.candidate_retrieval import (
    CandidateMatch,
    CandidateReviewDecision,
    CandidateSearchRun,
    Expert,
    Firm,
)
from app.models.participation import (
    CandidateAvailabilityFact,
    CandidateInterestFact,
    CandidateParticipationDecision,
    CandidateParticipationRecord,
)
from app.models.private_documents import DocumentVersion, PrivateDocument
from app.models.pursuit_analysis import PursuitPosition
from app.models.tenancy import Membership
from app.schemas.participation import (
    AvailabilityFactCreateRequest,
    AvailabilityFactResponse,
    CandidateParticipationResponse,
    InterestFactCreateRequest,
    InterestFactResponse,
    ParticipationDecisionCreateRequest,
    ParticipationDecisionResponse,
    ParticipationHistoryEvent,
    ParticipationStartRequest,
)
from app.services.candidate_retrieval import _stale_search_runs


POSITIVE_AVAILABILITY = {"TENTATIVE", "AVAILABLE", "PARTIALLY_AVAILABLE"}
POSITIVE_INTEREST = {"INTERESTED", "CONDITIONAL"}
POSITIVE_PARTICIPATION = {"TENTATIVE", "CONFIRMED"}


class ParticipationError(ValueError):
    pass


class ParticipationNotFoundError(ParticipationError):
    pass


class ParticipationEligibilityError(ParticipationError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ParticipationEligibilityError(f"{label} must include a timezone")


async def _require_active_membership(
    db: AsyncSession, *, organization_id: UUID, membership_id: UUID,
) -> Membership:
    row = await db.scalar(select(Membership).where(
        Membership.id == membership_id,
        Membership.organization_id == organization_id,
        Membership.state == MembershipState.ACTIVE,
    ))
    if row is None:
        raise ParticipationEligibilityError("An active Organization Membership is required")
    return row


async def _match_chain(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, candidate_match_id: UUID,
) -> tuple[CandidateMatch, CandidateSearchRun, CandidateReviewDecision | None]:
    pair = (await db.execute(
        select(CandidateMatch, CandidateSearchRun)
        .join(CandidateSearchRun, CandidateSearchRun.id == CandidateMatch.candidate_search_run_id)
        .where(
            CandidateMatch.id == candidate_match_id,
            CandidateSearchRun.organization_id == organization_id,
            CandidateSearchRun.pursuit_id == pursuit_id,
        )
    )).one_or_none()
    if pair is None:
        raise ParticipationNotFoundError("CandidateMatch not found in this Organization Pursuit")
    match, search = pair
    latest = await db.scalar(
        select(CandidateReviewDecision)
        .where(CandidateReviewDecision.candidate_match_id == match.id)
        .order_by(CandidateReviewDecision.created_at.desc(), CandidateReviewDecision.id.desc())
        .limit(1)
    )
    return match, search, latest


async def _current_chain(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, candidate_match_id: UUID,
) -> tuple[CandidateMatch, CandidateSearchRun, CandidateReviewDecision]:
    match, search, latest = await _match_chain(
        db, organization_id=organization_id, pursuit_id=pursuit_id,
        candidate_match_id=candidate_match_id,
    )
    if latest is None or latest.decision != "SHORTLISTED":
        raise ParticipationEligibilityError("Current W5 candidate decision must be SHORTLISTED")
    stale = await _stale_search_runs(
        db, organization_id=organization_id, pursuit_id=pursuit_id, searches=[search]
    )
    if stale[search.id][0]:
        raise ParticipationEligibilityError(stale[search.id][1] or "The W4/W5 chain is stale")
    return match, search, latest


async def _owned_record(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, participation_record_id: UUID,
) -> CandidateParticipationRecord:
    row = await db.scalar(select(CandidateParticipationRecord).where(
        CandidateParticipationRecord.id == participation_record_id,
        CandidateParticipationRecord.organization_id == organization_id,
        CandidateParticipationRecord.pursuit_id == pursuit_id,
    ))
    if row is None:
        raise ParticipationNotFoundError("Participation record not found")
    return row


async def _validate_document(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
    document_version_id: UUID | None,
) -> None:
    if document_version_id is None:
        return
    found = await db.scalar(
        select(DocumentVersion.id)
        .join(PrivateDocument, PrivateDocument.id == DocumentVersion.private_document_id)
        .where(
            DocumentVersion.id == document_version_id,
            DocumentVersion.organization_id == organization_id,
            PrivateDocument.organization_id == organization_id,
            PrivateDocument.pursuit_id == pursuit_id,
        )
    )
    if found is None:
        raise ParticipationEligibilityError("Supporting DocumentVersion is not owned by this Organization Pursuit")


def _assignment_window(value: str | None) -> tuple[date, date] | None:
    if not value:
        return None
    parsed: list[date] = []
    for token in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", value):
        try:
            parsed.append(date.fromisoformat(token))
        except ValueError:
            continue
    if len(parsed) < 2:
        return None
    return parsed[0], parsed[1]


def assignment_window_coverage(
    assignment_dates: str | None, window_start: date | None, window_end: date | None,
) -> str:
    assignment = _assignment_window(assignment_dates)
    if assignment is None or window_start is None or window_end is None:
        return "UNKNOWN_DATES"
    assignment_start, assignment_end = assignment
    if window_end < assignment_start or window_start > assignment_end:
        return "NO_OVERLAP"
    if window_start <= assignment_start and window_end >= assignment_end:
        return "FULL_WINDOW"
    return "PARTIAL_WINDOW"


async def start_participation(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
    candidate_match_id: UUID, membership_id: UUID, request: ParticipationStartRequest,
) -> CandidateParticipationResponse:
    await _require_active_membership(db, organization_id=organization_id, membership_id=membership_id)
    match, _, latest = await _current_chain(
        db, organization_id=organization_id, pursuit_id=pursuit_id,
        candidate_match_id=candidate_match_id,
    )
    if latest.id != request.shortlist_decision_id:
        raise ParticipationEligibilityError("The supplied shortlist decision is not the current W5 decision")
    existing = await db.scalar(select(CandidateParticipationRecord).where(
        CandidateParticipationRecord.candidate_match_id == match.id,
    ))
    if existing is not None:
        if existing.organization_id != organization_id or existing.pursuit_id != pursuit_id:
            raise ParticipationNotFoundError("Participation record not found")
        projected = await get_participation(
            db, organization_id=organization_id, pursuit_id=pursuit_id,
            participation_record_id=existing.id,
        )
        if projected is None:
            raise RuntimeError("Participation record projection failed")
        return projected
    corrections = list((await db.scalars(
        select(CandidateReviewDecision)
        .where(CandidateReviewDecision.candidate_match_id == match.id)
        .order_by(CandidateReviewDecision.created_at.desc(), CandidateReviewDecision.id.desc())
    )).all())
    contribution = next(
        (row.corrected_contribution for row in corrections if row.corrected_contribution),
        match.proposed_contribution,
    )
    row = CandidateParticipationRecord(
        organization_id=organization_id, pursuit_id=pursuit_id,
        candidate_match_id=match.id, shortlist_decision_id=latest.id,
        proposed_contribution_snapshot=contribution,
        created_by_membership_id=membership_id,
    )
    db.add(row)
    await db.commit()
    result = await get_participation(
        db, organization_id=organization_id, pursuit_id=pursuit_id,
        participation_record_id=row.id,
    )
    if result is None:
        raise RuntimeError("Participation record projection failed")
    return result


async def append_availability(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
    participation_record_id: UUID, membership_id: UUID,
    request: AvailabilityFactCreateRequest,
) -> CandidateParticipationResponse:
    await _require_active_membership(db, organization_id=organization_id, membership_id=membership_id)
    _require_aware(request.observed_at, "observed-at")
    if request.valid_until:
        _require_aware(request.valid_until, "valid-until")
    record = await _owned_record(
        db, organization_id=organization_id, pursuit_id=pursuit_id,
        participation_record_id=participation_record_id,
    )
    if request.status in POSITIVE_AVAILABILITY:
        match, search, _ = await _current_chain(
            db, organization_id=organization_id, pursuit_id=pursuit_id,
            candidate_match_id=record.candidate_match_id,
        )
        position = await db.get(PursuitPosition, search.position_id) if match.expert_id and search.position_id else None
        if position and _assignment_window(position.assignment_dates) and not request.window_start:
            raise ParticipationEligibilityError("Known assignment dates require an explicit availability window")
    await _validate_document(
        db, organization_id=organization_id, pursuit_id=pursuit_id,
        document_version_id=request.supporting_document_version_id,
    )
    if request.supersedes_fact_id is not None:
        corrected = await db.get(CandidateAvailabilityFact, request.supersedes_fact_id)
        if corrected is None or corrected.participation_record_id != record.id:
            raise ParticipationEligibilityError("Corrected availability fact is not in this participation trail")
    db.add(CandidateAvailabilityFact(
        organization_id=organization_id, participation_record_id=record.id,
        actor_membership_id=membership_id, **request.model_dump(),
    ))
    await db.commit()
    return await _required_projection(db, organization_id, pursuit_id, record.id)


async def append_interest(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
    participation_record_id: UUID, membership_id: UUID,
    request: InterestFactCreateRequest,
) -> CandidateParticipationResponse:
    await _require_active_membership(db, organization_id=organization_id, membership_id=membership_id)
    _require_aware(request.observed_at, "observed-at")
    if request.valid_until:
        _require_aware(request.valid_until, "valid-until")
    record = await _owned_record(
        db, organization_id=organization_id, pursuit_id=pursuit_id,
        participation_record_id=participation_record_id,
    )
    if request.status in POSITIVE_INTEREST:
        await _current_chain(
            db, organization_id=organization_id, pursuit_id=pursuit_id,
            candidate_match_id=record.candidate_match_id,
        )
    await _validate_document(
        db, organization_id=organization_id, pursuit_id=pursuit_id,
        document_version_id=request.supporting_document_version_id,
    )
    if request.supersedes_fact_id is not None:
        corrected = await db.get(CandidateInterestFact, request.supersedes_fact_id)
        if corrected is None or corrected.participation_record_id != record.id:
            raise ParticipationEligibilityError("Corrected interest fact is not in this participation trail")
    db.add(CandidateInterestFact(
        organization_id=organization_id, participation_record_id=record.id,
        actor_membership_id=membership_id, **request.model_dump(),
    ))
    await db.commit()
    return await _required_projection(db, organization_id, pursuit_id, record.id)


async def append_participation_decision(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
    participation_record_id: UUID, membership_id: UUID,
    request: ParticipationDecisionCreateRequest,
) -> CandidateParticipationResponse:
    await _require_active_membership(db, organization_id=organization_id, membership_id=membership_id)
    _require_aware(request.observed_at, "observed-at")
    if request.reconfirm_by:
        _require_aware(request.reconfirm_by, "reconfirm-by")
    record = await _owned_record(
        db, organization_id=organization_id, pursuit_id=pursuit_id,
        participation_record_id=participation_record_id,
    )
    if request.state in POSITIVE_PARTICIPATION:
        await _current_chain(
            db, organization_id=organization_id, pursuit_id=pursuit_id,
            candidate_match_id=record.candidate_match_id,
        )
    latest_interest = await db.scalar(
        select(CandidateInterestFact).where(CandidateInterestFact.participation_record_id == record.id)
        .order_by(CandidateInterestFact.created_at.desc(), CandidateInterestFact.id.desc()).limit(1)
    )
    latest_availability = await db.scalar(
        select(CandidateAvailabilityFact).where(CandidateAvailabilityFact.participation_record_id == record.id)
        .order_by(CandidateAvailabilityFact.created_at.desc(), CandidateAvailabilityFact.id.desc()).limit(1)
    )
    latest_decision = await db.scalar(
        select(CandidateParticipationDecision)
        .where(CandidateParticipationDecision.participation_record_id == record.id)
        .order_by(CandidateParticipationDecision.created_at.desc(), CandidateParticipationDecision.id.desc()).limit(1)
    )
    now = _now()
    if request.state == "CONFIRMED":
        if latest_interest and latest_interest.status == "DECLINED":
            raise ParticipationEligibilityError("Confirmed participation conflicts with declined interest")
        if latest_availability is None or latest_availability.status not in {"AVAILABLE", "PARTIALLY_AVAILABLE"}:
            raise ParticipationEligibilityError("Confirmed participation requires current available or partially available status")
        if latest_availability.valid_until is None or latest_availability.valid_until < now:
            raise ParticipationEligibilityError("Confirmed participation requires unexpired availability")
        if latest_availability.status == "PARTIALLY_AVAILABLE" and not (request.conditions_summary or "").strip():
            raise ParticipationEligibilityError("Partial availability requires explicit confirmation conditions")
    if request.state == "WITHDRAWN" and (
        latest_decision is None or latest_decision.state not in {"TENTATIVE", "CONFIRMED"}
    ):
        raise ParticipationEligibilityError("Withdrawal requires a prior tentative or confirmed participation decision")
    await _validate_document(
        db, organization_id=organization_id, pursuit_id=pursuit_id,
        document_version_id=request.supporting_document_version_id,
    )
    db.add(CandidateParticipationDecision(
        organization_id=organization_id, participation_record_id=record.id,
        actor_membership_id=membership_id,
        supersedes_decision_id=latest_decision.id if latest_decision else None,
        **request.model_dump(),
    ))
    await db.commit()
    return await _required_projection(db, organization_id, pursuit_id, record.id)


def _availability_response(row: CandidateAvailabilityFact, now: datetime) -> AvailabilityFactResponse:
    expired = row.valid_until is not None and row.valid_until < now
    return AvailabilityFactResponse(
        fact_id=row.id, status=row.status, effective_status="EXPIRED" if expired else row.status,
        is_expired=expired, window_start=row.window_start, window_end=row.window_end,
        effort_percent=row.effort_percent, capacity_description=row.capacity_description,
        location_travel_constraints=row.location_travel_constraints,
        confirmation_source=row.confirmation_source, observed_at=row.observed_at,
        valid_until=row.valid_until, supporting_document_version_id=row.supporting_document_version_id,
        supersedes_fact_id=row.supersedes_fact_id, actor_membership_id=row.actor_membership_id,
        created_at=row.created_at,
    )


def _interest_response(row: CandidateInterestFact, now: datetime) -> InterestFactResponse:
    expired = row.valid_until is not None and row.valid_until < now
    return InterestFactResponse(
        fact_id=row.id, status=row.status, effective_status="EXPIRED" if expired else row.status,
        is_expired=expired, confirmation_source=row.confirmation_source,
        observed_at=row.observed_at, valid_until=row.valid_until, conditions=row.conditions,
        supporting_document_version_id=row.supporting_document_version_id,
        supersedes_fact_id=row.supersedes_fact_id, actor_membership_id=row.actor_membership_id,
        created_at=row.created_at,
    )


def _decision_response(row: CandidateParticipationDecision, now: datetime) -> ParticipationDecisionResponse:
    needs = row.state in {"TENTATIVE", "CONFIRMED"} and row.reconfirm_by is not None and row.reconfirm_by < now
    return ParticipationDecisionResponse(
        decision_id=row.id, state=row.state,
        effective_state="NEEDS_RECONFIRMATION" if needs else row.state,
        needs_reconfirmation=needs, confirmation_source=row.confirmation_source,
        observed_at=row.observed_at, reconfirm_by=row.reconfirm_by,
        conditions_summary=row.conditions_summary, reason=row.reason,
        supporting_document_version_id=row.supporting_document_version_id,
        supersedes_decision_id=row.supersedes_decision_id,
        actor_membership_id=row.actor_membership_id, created_at=row.created_at,
    )


def _history(
    availability: Iterable[CandidateAvailabilityFact], interest: Iterable[CandidateInterestFact],
    decisions: Iterable[CandidateParticipationDecision],
) -> list[ParticipationHistoryEvent]:
    events = [
        ParticipationHistoryEvent(
            event_kind="AVAILABILITY", event_id=row.id, recorded_state=row.status,
            confirmation_source=row.confirmation_source, observed_at=row.observed_at,
            actor_membership_id=row.actor_membership_id, supersedes_id=row.supersedes_fact_id,
            created_at=row.created_at,
        ) for row in availability
    ] + [
        ParticipationHistoryEvent(
            event_kind="INTEREST", event_id=row.id, recorded_state=row.status,
            confirmation_source=row.confirmation_source, observed_at=row.observed_at,
            actor_membership_id=row.actor_membership_id, supersedes_id=row.supersedes_fact_id,
            created_at=row.created_at,
        ) for row in interest
    ] + [
        ParticipationHistoryEvent(
            event_kind="PARTICIPATION", event_id=row.id, recorded_state=row.state,
            confirmation_source=row.confirmation_source, observed_at=row.observed_at,
            actor_membership_id=row.actor_membership_id, supersedes_id=row.supersedes_decision_id,
            created_at=row.created_at,
        ) for row in decisions
    ]
    return sorted(events, key=lambda item: (item.created_at, str(item.event_id)))


async def _project_records(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
    records: list[CandidateParticipationRecord],
) -> list[CandidateParticipationResponse]:
    if not records:
        return []
    record_ids = [row.id for row in records]
    match_ids = [row.candidate_match_id for row in records]
    pairs = (await db.execute(
        select(CandidateMatch, CandidateSearchRun)
        .join(CandidateSearchRun, CandidateSearchRun.id == CandidateMatch.candidate_search_run_id)
        .where(CandidateMatch.id.in_(match_ids))
    )).all()
    matches = {match.id: match for match, _ in pairs}
    searches = {search.id: search for _, search in pairs}
    reviews = list((await db.scalars(
        select(CandidateReviewDecision).where(CandidateReviewDecision.candidate_match_id.in_(match_ids))
        .order_by(CandidateReviewDecision.created_at, CandidateReviewDecision.id)
    )).all())
    availability = list((await db.scalars(
        select(CandidateAvailabilityFact).where(CandidateAvailabilityFact.participation_record_id.in_(record_ids))
        .order_by(CandidateAvailabilityFact.created_at, CandidateAvailabilityFact.id)
    )).all())
    interest = list((await db.scalars(
        select(CandidateInterestFact).where(CandidateInterestFact.participation_record_id.in_(record_ids))
        .order_by(CandidateInterestFact.created_at, CandidateInterestFact.id)
    )).all())
    decisions = list((await db.scalars(
        select(CandidateParticipationDecision).where(CandidateParticipationDecision.participation_record_id.in_(record_ids))
        .order_by(CandidateParticipationDecision.created_at, CandidateParticipationDecision.id)
    )).all())
    latest_review: dict[UUID, CandidateReviewDecision] = {}
    for row in reviews:
        latest_review[row.candidate_match_id] = row
    availability_by: dict[UUID, list[CandidateAvailabilityFact]] = defaultdict(list)
    interest_by: dict[UUID, list[CandidateInterestFact]] = defaultdict(list)
    decisions_by: dict[UUID, list[CandidateParticipationDecision]] = defaultdict(list)
    for row in availability:
        availability_by[row.participation_record_id].append(row)
    for row in interest:
        interest_by[row.participation_record_id].append(row)
    for row in decisions:
        decisions_by[row.participation_record_id].append(row)
    firm_ids = {row.firm_id for row in matches.values() if row.firm_id}
    expert_ids = {row.expert_id for row in matches.values() if row.expert_id}
    firms = {row.id: row for row in (await db.scalars(select(Firm).where(Firm.id.in_(firm_ids)))).all()} if firm_ids else {}
    experts = {row.id: row for row in (await db.scalars(select(Expert).where(Expert.id.in_(expert_ids)))).all()} if expert_ids else {}
    position_ids = {search.position_id for search in searches.values() if search.position_id}
    positions = {row.id: row for row in (await db.scalars(select(PursuitPosition).where(PursuitPosition.id.in_(position_ids)))).all()} if position_ids else {}
    stale = await _stale_search_runs(
        db, organization_id=organization_id, pursuit_id=pursuit_id, searches=list(searches.values())
    )
    pursuit_candidate_rows = (await db.execute(
        select(
            CandidateParticipationRecord.id,
            CandidateMatch.firm_id,
            CandidateMatch.expert_id,
        )
        .join(CandidateMatch, CandidateMatch.id == CandidateParticipationRecord.candidate_match_id)
        .where(
            CandidateParticipationRecord.organization_id == organization_id,
            CandidateParticipationRecord.pursuit_id == pursuit_id,
        )
    )).all()
    candidate_records: dict[tuple[str, UUID], list[UUID]] = defaultdict(list)
    for record_id, firm_id, expert_id in pursuit_candidate_rows:
        key = ("FIRM", firm_id) if firm_id else ("EXPERT", expert_id)
        candidate_records[key].append(record_id)  # type: ignore[arg-type]
    now = _now()
    results: list[CandidateParticipationResponse] = []
    for record in records:
        match = matches.get(record.candidate_match_id)
        if match is None:
            continue
        search = searches[match.candidate_search_run_id]
        review = latest_review.get(match.id)
        chain_stale, chain_reason = stale[search.id]
        if review is None or review.decision != "SHORTLISTED":
            chain_stale = True
            chain_reason = "The latest W5 candidate decision is no longer SHORTLISTED."
        av_rows = availability_by[record.id]
        int_rows = interest_by[record.id]
        dec_rows = decisions_by[record.id]
        latest_av = _availability_response(av_rows[-1], now) if av_rows else None
        latest_int = _interest_response(int_rows[-1], now) if int_rows else None
        latest_dec = _decision_response(dec_rows[-1], now) if dec_rows else None
        if match.firm_id:
            candidate = firms[match.firm_id]
            candidate_kind, candidate_id = "FIRM", match.firm_id
        else:
            candidate = experts[match.expert_id]  # type: ignore[index]
            candidate_kind, candidate_id = "EXPERT", match.expert_id
        position = positions.get(search.position_id)
        assignment_dates = position.assignment_dates if position else None
        key = (candidate_kind, candidate_id)
        results.append(CandidateParticipationResponse(
            participation_record_id=record.id, organization_id=record.organization_id,
            pursuit_id=record.pursuit_id, candidate_match_id=match.id,
            shortlist_decision_id=record.shortlist_decision_id,
            effective_shortlist_decision_id=review.id if review else None,
            effective_shortlist_state=review.decision if review else None,
            candidate_search_run_id=search.id, analysis_run_id=search.analysis_run_id,
            gap_id=match.gap_id, candidate_kind=candidate_kind,
            candidate_id=candidate_id, candidate_name=candidate.display_name,
            proposed_contribution=record.proposed_contribution_snapshot,
            w5_qualification_state=match.qualification_state,
            w5_candidate_evidence_state=candidate.evidence_state,
            w5_strongest_evidence=match.strongest_evidence,
            w5_missing_or_weak_evidence=match.missing_or_weak_evidence,
            assignment_dates=assignment_dates,
            assignment_window_coverage=assignment_window_coverage(
                assignment_dates, latest_av.window_start if latest_av else None,
                latest_av.window_end if latest_av else None,
            ),
            latest_availability=latest_av, latest_interest=latest_int,
            latest_participation=latest_dec, upstream_stale=chain_stale,
            upstream_stale_reason=chain_reason,
            same_candidate_record_ids=[item for item in candidate_records[key] if item != record.id],
            history=_history(av_rows, int_rows, dec_rows),
            created_by_membership_id=record.created_by_membership_id,
            created_at=record.created_at,
        ))
    return results


async def list_participation(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
) -> list[CandidateParticipationResponse]:
    rows = list((await db.scalars(
        select(CandidateParticipationRecord).where(
            CandidateParticipationRecord.organization_id == organization_id,
            CandidateParticipationRecord.pursuit_id == pursuit_id,
        ).order_by(CandidateParticipationRecord.created_at, CandidateParticipationRecord.id).limit(100)
    )).all())
    return await _project_records(
        db, organization_id=organization_id, pursuit_id=pursuit_id, records=rows
    )


async def get_participation(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
    participation_record_id: UUID,
) -> CandidateParticipationResponse | None:
    row = await db.scalar(select(CandidateParticipationRecord).where(
        CandidateParticipationRecord.id == participation_record_id,
        CandidateParticipationRecord.organization_id == organization_id,
        CandidateParticipationRecord.pursuit_id == pursuit_id,
    ))
    if row is None:
        return None
    results = await _project_records(
        db, organization_id=organization_id, pursuit_id=pursuit_id, records=[row]
    )
    return results[0]


async def _required_projection(
    db: AsyncSession, organization_id: UUID, pursuit_id: UUID, record_id: UUID,
) -> CandidateParticipationResponse:
    result = await get_participation(
        db, organization_id=organization_id, pursuit_id=pursuit_id,
        participation_record_id=record_id,
    )
    if result is None:
        raise RuntimeError("Participation projection failed")
    return result
