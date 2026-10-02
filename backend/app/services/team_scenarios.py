"""Deterministic W7 team scenario creation, assessment, and projection."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
import hashlib
import json
import re
from typing import Any, Iterable
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import MembershipState
from app.models.candidate_retrieval import CandidateMatch, CandidateSearchRun, Firm
from app.models.pursuit_analysis import AnalysisReviewAssertion, AnalysisRun
from app.models.team_scenarios import (
    ScenarioGapAssessment,
    ScenarioIssue,
    TeamScenario,
    TeamScenarioContribution,
    TeamScenarioDecision,
    TeamScenarioParticipant,
    TeamScenarioRevision,
)
from app.models.tenancy import Membership
from app.schemas.participation import CandidateParticipationResponse
from app.schemas.team_scenarios import (
    ProposalHandoffResponse,
    ScenarioContributionResponse,
    ScenarioGapAssessmentResponse,
    ScenarioIssueResponse,
    ScenarioParticipantResponse,
    TeamScenarioCreateRequest,
    TeamScenarioDecisionCreateRequest,
    TeamScenarioDecisionResponse,
    TeamScenarioResponse,
    TeamScenarioRevisionCreateRequest,
    TeamScenarioRevisionResponse,
)
from app.services.participation import list_participation
from app.services.pursuit_analysis import get_analysis_run


ASSESSMENT_SCHEMA_VERSION = "w7-team-scenario-v1"
CURRENT_GAP_STATES = {"PARTIAL", "GAP", "EVIDENCE_MISSING", "NEEDS_INTERPRETATION"}
NONCANDIDATE_RESOLUTIONS = {"COMPANY_EVIDENCE", "CLARIFICATION", "HUMAN_INTERPRETATION"}


class TeamScenarioError(ValueError):
    pass


class TeamScenarioNotFoundError(TeamScenarioError):
    pass


class TeamScenarioEligibilityError(TeamScenarioError):
    pass


async def _require_active_membership(
    db: AsyncSession, *, organization_id: UUID, membership_id: UUID,
) -> None:
    row = await db.scalar(select(Membership).where(
        Membership.id == membership_id,
        Membership.organization_id == organization_id,
        Membership.state == MembershipState.ACTIVE,
    ))
    if row is None:
        raise TeamScenarioEligibilityError("An active Organization Membership is required")


async def _owned_scenario(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, scenario_id: UUID,
) -> TeamScenario:
    row = await db.scalar(select(TeamScenario).where(
        TeamScenario.id == scenario_id,
        TeamScenario.organization_id == organization_id,
        TeamScenario.pursuit_id == pursuit_id,
    ))
    if row is None:
        raise TeamScenarioNotFoundError("Team scenario not found")
    return row


def _selection_hash(analysis_run_id: UUID, record_ids: Iterable[UUID]) -> str:
    payload = {
        "analysis_run_id": str(analysis_run_id),
        "participation_record_ids": sorted(str(item) for item in record_ids),
        "schema": ASSESSMENT_SCHEMA_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _evidence_identities(match: CandidateMatch) -> list[dict[str, str]]:
    identities: list[dict[str, str]] = []
    for value in match.provenance.get("reference_ids", []) or []:
        identities.append({"type": "PROJECT_REFERENCE", "id": str(value)})
    if match.provenance.get("cv_version_id"):
        identities.append({"type": "CV_VERSION", "id": str(match.provenance["cv_version_id"])})
    return identities


def _parse_assignment_dates(value: str | None) -> tuple[date, date] | None:
    if not value:
        return None
    found = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", value)
    if len(found) != 2:
        return None
    try:
        start, end = date.fromisoformat(found[0]), date.fromisoformat(found[1])
    except ValueError:
        return None
    return (start, end) if end >= start else None


def _overlap(left: tuple[date, date], right: tuple[date, date]) -> bool:
    return max(left[0], right[0]) <= min(left[1], right[1])


def _contribution_issue_specs(record: CandidateParticipationResponse) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    if record.upstream_stale:
        issues.append(("UPSTREAM_STALE", "BLOCKING"))
    if record.w5_qualification_state != "SUPPORTED_BY_EVIDENCE":
        issues.append(("PARTIAL_CANDIDATE_EVIDENCE", "REVIEW"))
    availability = record.latest_availability
    if availability is None or availability.effective_status in {"UNKNOWN", "TENTATIVE"}:
        issues.append(("UNCONFIRMED_AVAILABILITY", "REVIEW"))
    elif availability.effective_status == "EXPIRED":
        issues.append(("EXPIRED_AVAILABILITY", "BLOCKING"))
    elif availability.effective_status == "UNAVAILABLE":
        issues.append(("UNAVAILABLE_PARTICIPANT", "BLOCKING"))
    interest = record.latest_interest
    if interest and interest.effective_status == "DECLINED":
        issues.append(("DECLINED_INTEREST", "BLOCKING"))
    participation = record.latest_participation
    if participation is None or participation.effective_state in {"UNCONFIRMED", "TENTATIVE"}:
        issues.append(("UNCONFIRMED_PARTICIPANT", "REVIEW"))
    elif participation.effective_state == "NEEDS_RECONFIRMATION":
        issues.append(("NEEDS_RECONFIRMATION", "BLOCKING"))
    elif participation.effective_state in {"DECLINED", "WITHDRAWN"}:
        issues.append(("PARTICIPATION_UNAVAILABLE", "BLOCKING"))
    if record.candidate_kind == "EXPERT" or record.assignment_dates:
        if record.assignment_window_coverage == "NO_OVERLAP":
            issues.append(("NO_WINDOW_OVERLAP", "BLOCKING"))
        elif record.assignment_window_coverage == "PARTIAL_WINDOW":
            issues.append(("PARTIAL_WINDOW", "REVIEW"))
        elif record.assignment_window_coverage == "UNKNOWN_DATES":
            issues.append(("UNKNOWN_ASSIGNMENT_WINDOW", "REVIEW"))
    return issues


def _fully_supports(record: CandidateParticipationResponse, issue_specs: list[tuple[str, str]]) -> bool:
    return (
        record.w5_qualification_state == "SUPPORTED_BY_EVIDENCE"
        and record.effective_shortlist_state == "SHORTLISTED"
        and record.latest_availability is not None
        and record.latest_availability.effective_status in {"AVAILABLE", "PARTIALLY_AVAILABLE"}
        and record.latest_participation is not None
        and record.latest_participation.effective_state == "CONFIRMED"
        and (
            record.assignment_window_coverage == "FULL_WINDOW"
            or (record.candidate_kind == "FIRM" and not record.assignment_dates)
        )
        and not issue_specs
    )


async def _build_revision(
    db: AsyncSession, *, scenario: TeamScenario, membership_id: UUID,
    participation_record_ids: list[UUID],
) -> TeamScenarioRevision:
    participation = await list_participation(
        db, organization_id=scenario.organization_id, pursuit_id=scenario.pursuit_id,
    )
    by_id = {item.participation_record_id: item for item in participation}
    missing = [item for item in participation_record_ids if item not in by_id]
    if missing:
        raise TeamScenarioNotFoundError("One or more participation records were not found in this Organization and Pursuit")
    selected = [by_id[item] for item in participation_record_ids]
    analysis_ids = {item.analysis_run_id for item in selected}
    if len(analysis_ids) > 1:
        raise TeamScenarioEligibilityError("One revision cannot mix participation records from different W4 analyses")
    requested_analysis_id = next(iter(analysis_ids), None)
    analysis = await get_analysis_run(
        db, organization_id=scenario.organization_id, pursuit_id=scenario.pursuit_id,
        run_id=requested_analysis_id,
    )
    if analysis is None or analysis.status != "COMPLETED":
        raise TeamScenarioEligibilityError("A completed W4 analysis is required")

    match_ids = [item.candidate_match_id for item in selected]
    match_rows = list((await db.scalars(
        select(CandidateMatch).where(CandidateMatch.id.in_(match_ids))
    )).all()) if match_ids else []
    matches = {item.id: item for item in match_rows}
    search_ids = {item.candidate_search_run_id for item in match_rows}
    search_rows = list((await db.scalars(
        select(CandidateSearchRun).where(CandidateSearchRun.id.in_(search_ids))
    )).all()) if search_ids else []
    searches = {item.id: item for item in search_rows}
    if len(matches) != len(selected):
        raise TeamScenarioEligibilityError("CandidateMatch lineage is incomplete")
    firm_ids = {item.firm_id for item in match_rows if item.firm_id}
    if firm_ids and await db.scalar(
        select(func.count(Firm.id)).where(Firm.id.in_(firm_ids), Firm.organization_id.is_not(None))
    ):
        # The lead organization is the scenario's owner, never one of its participants.
        raise TeamScenarioEligibilityError(
            "The organization's own firm is the lead organization and cannot be a scenario participant"
        )

    prior_version = await db.scalar(select(func.max(TeamScenarioRevision.version_number)).where(
        TeamScenarioRevision.scenario_id == scenario.id
    ))
    revision_id = uuid4()
    participant_rows: list[TeamScenarioParticipant] = []
    contribution_rows: list[TeamScenarioContribution] = []
    issue_rows: list[ScenarioIssue] = []
    issue_keys: set[tuple[Any, ...]] = set()
    participant_by_identity: dict[tuple[str, UUID], TeamScenarioParticipant] = {}
    record_by_contribution: dict[UUID, CandidateParticipationResponse] = {}

    def add_issue(
        code: str, severity: str, *, gap_id: UUID | None = None,
        participant_id: UUID | None = None, contribution_id: UUID | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        key = (code, gap_id, participant_id, contribution_id)
        if key in issue_keys:
            return
        issue_keys.add(key)
        issue_rows.append(ScenarioIssue(
            id=uuid4(), organization_id=scenario.organization_id, revision_id=revision_id,
            issue_code=code, severity=severity, gap_id=gap_id,
            participant_id=participant_id, contribution_id=contribution_id,
            details=details or {},
        ))

    for record in selected:
        match = matches[record.candidate_match_id]
        search = searches.get(match.candidate_search_run_id)
        if search is None or search.analysis_run_id != analysis.analysis_run_id or search.gap_id != record.gap_id:
            raise TeamScenarioEligibilityError("Selected participation does not belong to the revision's exact W4 chain")
        identity = (record.candidate_kind, record.candidate_id)
        participant = participant_by_identity.get(identity)
        if participant is None:
            participant = TeamScenarioParticipant(
                id=uuid4(), organization_id=scenario.organization_id, revision_id=revision_id,
                participant_type="PARTNER_FIRM" if record.candidate_kind == "FIRM" else "EXPERT",
                firm_id=record.candidate_id if record.candidate_kind == "FIRM" else None,
                expert_id=record.candidate_id if record.candidate_kind == "EXPERT" else None,
                display_name_snapshot=record.candidate_name,
            )
            participant_by_identity[identity] = participant
            participant_rows.append(participant)
        availability = record.latest_availability
        interest = record.latest_interest
        decision = record.latest_participation
        contribution = TeamScenarioContribution(
            id=uuid4(), organization_id=scenario.organization_id, revision_id=revision_id,
            analysis_run_id=analysis.analysis_run_id,
            participant_id=participant.id, candidate_match_id=record.candidate_match_id,
            participation_record_id=record.participation_record_id, gap_id=record.gap_id,
            requirement_id=search.requirement_id, position_id=search.position_id,
            shortlist_decision_id=record.effective_shortlist_decision_id or record.shortlist_decision_id,
            shortlist_decision_state_snapshot=record.effective_shortlist_state or "UNKNOWN",
            proposed_contribution_snapshot=record.proposed_contribution,
            contribution_rule_snapshot=search.contribution_rule,
            qualification_state_snapshot=record.w5_qualification_state,
            candidate_evidence_state_snapshot=record.w5_candidate_evidence_state,
            evidence_identities_snapshot=_evidence_identities(match),
            strongest_evidence_snapshot=record.w5_strongest_evidence,
            availability_fact_id=availability.fact_id if availability else None,
            availability_recorded_state=availability.status if availability else None,
            availability_effective_state=availability.effective_status if availability else None,
            availability_window_start=availability.window_start if availability else None,
            availability_window_end=availability.window_end if availability else None,
            availability_effort_percent=availability.effort_percent if availability else None,
            availability_capacity_snapshot=availability.capacity_description if availability else None,
            availability_valid_until=availability.valid_until if availability else None,
            interest_fact_id=interest.fact_id if interest else None,
            interest_recorded_state=interest.status if interest else None,
            interest_effective_state=interest.effective_status if interest else None,
            interest_conditions_snapshot=interest.conditions if interest else None,
            participation_decision_id=decision.decision_id if decision else None,
            participation_recorded_state=decision.state if decision else None,
            participation_effective_state=decision.effective_state if decision else None,
            confirmation_source_snapshot=decision.confirmation_source if decision else None,
            confirmation_observed_at=decision.observed_at if decision else None,
            reconfirm_by=decision.reconfirm_by if decision else None,
            confirmation_conditions_snapshot=decision.conditions_summary if decision else None,
            assignment_dates_snapshot=record.assignment_dates,
            assignment_window_result=record.assignment_window_coverage,
            upstream_stale_snapshot=record.upstream_stale,
        )
        contribution_rows.append(contribution)
        record_by_contribution[contribution.id] = record
        for code, severity in _contribution_issue_specs(record):
            add_issue(
                code, severity, gap_id=record.gap_id, participant_id=participant.id,
                contribution_id=contribution.id,
                details={"participation_record_id": str(record.participation_record_id)},
            )
        if record.candidate_kind == "FIRM" and not search.contribution_rule.strip():
            add_issue(
                "CONTRIBUTION_RULE_UNCLEAR", "REVIEW", gap_id=record.gap_id,
                participant_id=participant.id, contribution_id=contribution.id,
            )

    contributions_by_gap: dict[UUID, list[TeamScenarioContribution]] = defaultdict(list)
    contributions_by_participant: dict[UUID, list[TeamScenarioContribution]] = defaultdict(list)
    for contribution in contribution_rows:
        contributions_by_gap[contribution.gap_id].append(contribution)
        contributions_by_participant[contribution.participant_id].append(contribution)

    for participant in participant_rows:
        contributions = contributions_by_participant[participant.id]
        if len(contributions) < 2:
            continue
        signatures = {
            (
                item.availability_effective_state, item.interest_effective_state,
                item.participation_effective_state, item.interest_conditions_snapshot,
                item.confirmation_conditions_snapshot,
            ) for item in contributions
        }
        if len(signatures) > 1:
            add_issue(
                "CONFLICTING_PARTICIPATION_FACTS", "REVIEW", participant_id=participant.id,
                details={"contribution_ids": [str(item.id) for item in contributions]},
            )
        if participant.participant_type != "EXPERT":
            continue
        for index, left in enumerate(contributions):
            for right in contributions[index + 1:]:
                left_dates = _parse_assignment_dates(left.assignment_dates_snapshot)
                right_dates = _parse_assignment_dates(right.assignment_dates_snapshot)
                if left_dates is None or right_dates is None:
                    add_issue(
                        "UNKNOWN_EFFORT", "REVIEW", participant_id=participant.id,
                        details={"reason": "assignment_dates", "contribution_ids": [str(left.id), str(right.id)]},
                    )
                    continue
                if not _overlap(left_dates, right_dates):
                    continue
                if left.availability_effort_percent is None or right.availability_effort_percent is None:
                    capacity = " ".join(filter(None, [
                        left.availability_capacity_snapshot,
                        right.availability_capacity_snapshot,
                    ])).lower().replace("-", " ")
                    add_issue(
                        "CONCURRENT_FULL_TIME_CONFLICT" if "full time" in capacity else "UNKNOWN_EFFORT",
                        "BLOCKING" if "full time" in capacity else "REVIEW",
                        participant_id=participant.id,
                        details={"reason": "effort_percent", "contribution_ids": [str(left.id), str(right.id)]},
                    )
                elif left.availability_effort_percent + right.availability_effort_percent > Decimal("100"):
                    add_issue(
                        "EXPERT_DOUBLE_COUNT", "BLOCKING", participant_id=participant.id,
                        details={
                            "combined_effort_percent": str(left.availability_effort_percent + right.availability_effort_percent),
                            "contribution_ids": [str(left.id), str(right.id)],
                        },
                    )

    if analysis.inputs_changed:
        add_issue("UPSTREAM_STALE", "BLOCKING", details={"reason": analysis.stale_reason or "W4 inputs changed"})

    requirement_by_id = {item.requirement_id: item for item in analysis.requirements}
    position_by_id = {item.position_id: item for item in analysis.positions}
    assertion_rows = list((await db.scalars(select(AnalysisReviewAssertion).where(
        AnalysisReviewAssertion.analysis_run_id == analysis.analysis_run_id,
        AnalysisReviewAssertion.target_kind == "GAP",
    ).order_by(AnalysisReviewAssertion.created_at, AnalysisReviewAssertion.id))).all())
    latest_gap_assertion: dict[UUID, AnalysisReviewAssertion] = {}
    for assertion in assertion_rows:
        if assertion.gap_id:
            latest_gap_assertion[assertion.gap_id] = assertion
    gap_rows: list[ScenarioGapAssessment] = []
    unresolved_later = 0
    for gap in analysis.gaps:
        target = requirement_by_id.get(gap.requirement_id) or position_by_id.get(gap.position_id)
        later_stage = gap.effective_coverage_state == "LATER_STAGE_OBLIGATION"
        not_applicable = gap.effective_coverage_state == "NOT_APPLICABLE"
        current_stage = not later_stage and not not_applicable
        blocking = current_stage and getattr(target, "distinction", None) == "MANDATORY"
        gap_contributions = contributions_by_gap.get(gap.gap_id, [])
        if current_stage and gap.effective_review_state not in {"CONFIRMED", "CORRECTED"}:
            state, rationale = "NEEDS_REVIEW", "W4_GAP_NOT_REVIEWED"
            add_issue("UNREVIEWED_GAP", "REVIEW", gap_id=gap.gap_id)
        elif later_stage:
            state, rationale = "UNRESOLVED", "LATER_STAGE_OBLIGATION"
            unresolved_later += 1
        elif not_applicable or gap.effective_coverage_state == "SUPPORTED":
            state, rationale = "COVERED", "W4_ALREADY_RESOLVED"
            blocking = False
        elif gap.effective_resolution_category in NONCANDIDATE_RESOLUTIONS:
            state, rationale = "UNRESOLVED", "NONCANDIDATE_GAP"
            add_issue("UNRESOLVED_GAP", "REVIEW", gap_id=gap.gap_id, details={"resolution_category": gap.effective_resolution_category})
        elif not gap_contributions:
            state, rationale = "UNRESOLVED", "NO_SELECTED_CONTRIBUTION"
            add_issue("UNRESOLVED_GAP", "REVIEW", gap_id=gap.gap_id)
        else:
            support = []
            explicit_block = False
            for contribution in gap_contributions:
                record = record_by_contribution[contribution.id]
                specs = _contribution_issue_specs(record)
                support.append(_fully_supports(record, specs))
                explicit_block = explicit_block or any(severity == "BLOCKING" for _, severity in specs)
            if explicit_block:
                state, rationale = "BLOCKED", "CONTRIBUTION_INCOMPATIBLE"
            elif any(support):
                state, rationale = "COVERED", "SUPPORTED_CONFIRMED_CONTRIBUTION"
            elif any(item.qualification_state_snapshot in {"PARTIAL", "EVIDENCE_MISSING", "NEEDS_REVIEW"} for item in gap_contributions):
                state, rationale = "PARTIAL", "CANDIDATE_EVIDENCE_INCOMPLETE"
            else:
                state, rationale = "NEEDS_REVIEW", "CONTRIBUTION_FACTS_INCOMPLETE"
        gap_rows.append(ScenarioGapAssessment(
            id=uuid4(), organization_id=scenario.organization_id, revision_id=revision_id,
            analysis_run_id=analysis.analysis_run_id,
            gap_id=gap.gap_id, requirement_id=gap.requirement_id, position_id=gap.position_id,
            review_assertion_id=(latest_gap_assertion.get(gap.gap_id).id if latest_gap_assertion.get(gap.gap_id) else None),
            w4_coverage_state_snapshot=gap.effective_coverage_state,
            w4_review_state_snapshot=gap.effective_review_state,
            resolution_category_snapshot=gap.effective_resolution_category,
            state=state, is_current_stage=current_stage, is_blocking=blocking,
            rationale_code=rationale,
        ))

    blocking_issues = sum(item.severity == "BLOCKING" for item in issue_rows)
    review_issues = sum(item.severity == "REVIEW" for item in issue_rows)
    blocking_gap_failure = any(item.is_blocking and item.state != "COVERED" for item in gap_rows)
    unresolved_current = any(item.is_current_stage and item.state != "COVERED" for item in gap_rows)
    if blocking_issues or any(item.state == "BLOCKED" for item in gap_rows):
        assessment = "BLOCKED"
    elif not contribution_rows:
        assessment = "DRAFT"
    elif review_issues or blocking_gap_failure or unresolved_current:
        assessment = "NEEDS_REVIEW"
    else:
        assessment = "VIABLE"

    provenance = [item.provenance for item in analysis.pack_items]
    current_gap_rows = [item for item in gap_rows if item.is_current_stage]
    confirmed_participants = {
        participant.id for participant in participant_rows
        if contributions_by_participant[participant.id]
        and all(item.participation_effective_state == "CONFIRMED" for item in contributions_by_participant[participant.id])
    }
    revision = TeamScenarioRevision(
        id=revision_id, organization_id=scenario.organization_id, scenario_id=scenario.id,
        version_number=(prior_version or 0) + 1, analysis_run_id=analysis.analysis_run_id,
        analysis_pack_id=analysis.analysis_pack_id, created_by_membership_id=membership_id,
        selection_sha256=_selection_hash(analysis.analysis_run_id, participation_record_ids),
        assessment_schema_version=ASSESSMENT_SCHEMA_VERSION, assessment_state=assessment,
        gap_count=len(current_gap_rows),
        covered_gap_count=sum(item.state == "COVERED" for item in current_gap_rows),
        unresolved_gap_count=sum(item.is_current_stage and item.state != "COVERED" for item in gap_rows),
        participant_count=len(participant_rows), confirmed_participant_count=len(confirmed_participants),
        issue_count=len(issue_rows), blocking_issue_count=blocking_issues,
        unresolved_later_stage_count=unresolved_later,
        source_provenance_count=provenance.count("SHARED_SOURCE"),
        private_provenance_count=provenance.count("ORGANIZATION_PRIVATE_UPLOAD"),
    )
    # These immutable rows use composite lineage FKs without ORM relationships.
    # Flush each dependency layer explicitly so PostgreSQL sees the sealed parent
    # before its descendants, independent of mapper insert ordering.
    db.add(revision)
    await db.flush()
    db.add_all([*participant_rows, *gap_rows])
    await db.flush()
    db.add_all(contribution_rows)
    await db.flush()
    db.add_all(issue_rows)
    return revision


async def create_team_scenario(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, membership_id: UUID,
    request: TeamScenarioCreateRequest,
) -> TeamScenarioResponse:
    await _require_active_membership(db, organization_id=organization_id, membership_id=membership_id)
    scenario = TeamScenario(
        id=uuid4(), organization_id=organization_id, pursuit_id=pursuit_id,
        title=request.title.strip(), created_by_membership_id=membership_id,
    )
    db.add(scenario)
    await _build_revision(
        db, scenario=scenario, membership_id=membership_id,
        participation_record_ids=request.participation_record_ids,
    )
    await db.commit()
    return await _required_scenario(db, organization_id, pursuit_id, scenario.id)


async def revise_team_scenario(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, scenario_id: UUID,
    membership_id: UUID, request: TeamScenarioRevisionCreateRequest,
) -> TeamScenarioResponse:
    await _require_active_membership(db, organization_id=organization_id, membership_id=membership_id)
    scenario = await _owned_scenario(
        db, organization_id=organization_id, pursuit_id=pursuit_id, scenario_id=scenario_id,
    )
    if scenario.archived_at is not None:
        raise TeamScenarioEligibilityError("Archived team scenarios cannot be revised")
    await _build_revision(
        db, scenario=scenario, membership_id=membership_id,
        participation_record_ids=request.participation_record_ids,
    )
    await db.commit()
    return await _required_scenario(db, organization_id, pursuit_id, scenario.id)


def _contribution_response(item: TeamScenarioContribution) -> ScenarioContributionResponse:
    return ScenarioContributionResponse(
        contribution_id=item.id, candidate_match_id=item.candidate_match_id,
        participation_record_id=item.participation_record_id, gap_id=item.gap_id,
        requirement_id=item.requirement_id, position_id=item.position_id,
        shortlist_decision_id=item.shortlist_decision_id,
        shortlist_decision_state=item.shortlist_decision_state_snapshot,
        proposed_contribution=item.proposed_contribution_snapshot,
        contribution_rule=item.contribution_rule_snapshot,
        qualification_state=item.qualification_state_snapshot,
        candidate_evidence_state=item.candidate_evidence_state_snapshot,
        evidence_identities=item.evidence_identities_snapshot,
        strongest_evidence=item.strongest_evidence_snapshot,
        availability_fact_id=item.availability_fact_id,
        availability_recorded_state=item.availability_recorded_state,
        availability_effective_state=item.availability_effective_state,
        availability_window_start=item.availability_window_start,
        availability_window_end=item.availability_window_end,
        availability_effort_percent=item.availability_effort_percent,
        availability_capacity=item.availability_capacity_snapshot,
        availability_valid_until=item.availability_valid_until,
        interest_fact_id=item.interest_fact_id,
        interest_recorded_state=item.interest_recorded_state,
        interest_effective_state=item.interest_effective_state,
        interest_conditions=item.interest_conditions_snapshot,
        participation_decision_id=item.participation_decision_id,
        participation_recorded_state=item.participation_recorded_state,
        participation_effective_state=item.participation_effective_state,
        confirmation_source=item.confirmation_source_snapshot,
        confirmation_observed_at=item.confirmation_observed_at,
        reconfirm_by=item.reconfirm_by,
        confirmation_conditions=item.confirmation_conditions_snapshot,
        assignment_dates=item.assignment_dates_snapshot,
        assignment_window_result=item.assignment_window_result,
        upstream_stale=item.upstream_stale_snapshot,
    )


async def _project_scenarios(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, scenarios: list[TeamScenario],
) -> list[TeamScenarioResponse]:
    if not scenarios:
        return []
    scenario_ids = [item.id for item in scenarios]
    revisions = list((await db.scalars(select(TeamScenarioRevision).where(
        TeamScenarioRevision.scenario_id.in_(scenario_ids),
        TeamScenarioRevision.organization_id == organization_id,
    ).order_by(TeamScenarioRevision.scenario_id, TeamScenarioRevision.version_number).limit(1000))).all())
    revision_ids = [item.id for item in revisions]
    participants = list((await db.scalars(select(TeamScenarioParticipant).where(
        TeamScenarioParticipant.revision_id.in_(revision_ids)
    ).order_by(TeamScenarioParticipant.created_at, TeamScenarioParticipant.id))).all()) if revision_ids else []
    contributions = list((await db.scalars(select(TeamScenarioContribution).where(
        TeamScenarioContribution.revision_id.in_(revision_ids)
    ).order_by(TeamScenarioContribution.created_at, TeamScenarioContribution.id))).all()) if revision_ids else []
    gaps = list((await db.scalars(select(ScenarioGapAssessment).where(
        ScenarioGapAssessment.revision_id.in_(revision_ids)
    ).order_by(ScenarioGapAssessment.created_at, ScenarioGapAssessment.id))).all()) if revision_ids else []
    issues = list((await db.scalars(select(ScenarioIssue).where(
        ScenarioIssue.revision_id.in_(revision_ids)
    ).order_by(ScenarioIssue.created_at, ScenarioIssue.id))).all()) if revision_ids else []
    decisions = list((await db.scalars(select(TeamScenarioDecision).where(
        TeamScenarioDecision.scenario_id.in_(scenario_ids),
        TeamScenarioDecision.organization_id == organization_id,
    ).order_by(TeamScenarioDecision.created_at.desc(), TeamScenarioDecision.id.desc()).limit(5000))).all())
    decisions.sort(key=lambda item: (item.created_at, str(item.id)))

    current_analysis = await get_analysis_run(
        db, organization_id=organization_id, pursuit_id=pursuit_id,
    )
    current_participation = await list_participation(
        db, organization_id=organization_id, pursuit_id=pursuit_id,
    )
    current_gap_assertions: dict[UUID, UUID] = {}
    if current_analysis is not None:
        rows = list((await db.scalars(select(AnalysisReviewAssertion).where(
            AnalysisReviewAssertion.analysis_run_id == current_analysis.analysis_run_id,
            AnalysisReviewAssertion.target_kind == "GAP",
        ).order_by(AnalysisReviewAssertion.created_at, AnalysisReviewAssertion.id))).all())
        for row in rows:
            if row.gap_id:
                current_gap_assertions[row.gap_id] = row.id
    current_by_record = {item.participation_record_id: item for item in current_participation}
    revisions_by_scenario: dict[UUID, list[TeamScenarioRevision]] = defaultdict(list)
    participants_by_revision: dict[UUID, list[TeamScenarioParticipant]] = defaultdict(list)
    contributions_by_revision: dict[UUID, list[TeamScenarioContribution]] = defaultdict(list)
    contributions_by_participant: dict[UUID, list[TeamScenarioContribution]] = defaultdict(list)
    gaps_by_revision: dict[UUID, list[ScenarioGapAssessment]] = defaultdict(list)
    issues_by_revision: dict[UUID, list[ScenarioIssue]] = defaultdict(list)
    decisions_by_revision: dict[UUID, list[TeamScenarioDecision]] = defaultdict(list)
    for item in revisions: revisions_by_scenario[item.scenario_id].append(item)
    for item in participants: participants_by_revision[item.revision_id].append(item)
    for item in contributions:
        contributions_by_revision[item.revision_id].append(item)
        contributions_by_participant[item.participant_id].append(item)
    for item in gaps: gaps_by_revision[item.revision_id].append(item)
    for item in issues: issues_by_revision[item.revision_id].append(item)
    for item in decisions: decisions_by_revision[item.revision_id].append(item)

    def revision_response(revision: TeamScenarioRevision) -> TeamScenarioRevisionResponse:
        reasons: list[str] = []
        if current_analysis is None or current_analysis.analysis_run_id != revision.analysis_run_id:
            reasons.append("A newer W4 analysis run is current.")
        elif current_analysis.inputs_changed:
            reasons.append(current_analysis.stale_reason or "Current inputs differ from the sealed W4 analysis pack.")
        if current_analysis and current_analysis.analysis_run_id == revision.analysis_run_id:
            current_gaps = {item.gap_id: item for item in current_analysis.gaps}
            snapshot_gaps = {item.gap_id for item in gaps_by_revision[revision.id]}
            if set(current_gaps) != snapshot_gaps:
                reasons.append("The reviewed W4 Gap set changed for this analysis run.")
            for snapshot in gaps_by_revision[revision.id]:
                current_gap = current_gaps.get(snapshot.gap_id)
                if current_gap is None or (
                    current_gap.effective_coverage_state,
                    current_gap.effective_review_state,
                    current_gap.effective_resolution_category,
                    current_gap_assertions.get(snapshot.gap_id),
                ) != (
                    snapshot.w4_coverage_state_snapshot,
                    snapshot.w4_review_state_snapshot,
                    snapshot.resolution_category_snapshot,
                    snapshot.review_assertion_id,
                ):
                    reasons.append(f"W4 review facts changed for Gap {snapshot.gap_id}.")
        for contribution in contributions_by_revision[revision.id]:
            current = current_by_record.get(contribution.participation_record_id)
            if current is None:
                reasons.append(f"Participation record {contribution.participation_record_id} is no longer available.")
                continue
            expected = (
                contribution.candidate_match_id, contribution.shortlist_decision_id,
                contribution.shortlist_decision_state_snapshot,
                contribution.availability_fact_id, contribution.interest_fact_id,
                contribution.participation_decision_id, contribution.availability_effective_state,
                contribution.interest_effective_state, contribution.participation_effective_state,
                contribution.assignment_window_result,
            )
            actual = (
                current.candidate_match_id, current.effective_shortlist_decision_id,
                current.effective_shortlist_state,
                current.latest_availability.fact_id if current.latest_availability else None,
                current.latest_interest.fact_id if current.latest_interest else None,
                current.latest_participation.decision_id if current.latest_participation else None,
                current.latest_availability.effective_status if current.latest_availability else None,
                current.latest_interest.effective_status if current.latest_interest else None,
                current.latest_participation.effective_state if current.latest_participation else None,
                current.assignment_window_coverage,
            )
            if current.upstream_stale or expected != actual:
                reasons.append(f"W5 or W6 facts changed for participation record {contribution.participation_record_id}.")
        reasons = list(dict.fromkeys(reasons))
        participant_responses = [ScenarioParticipantResponse(
            participant_id=item.id, participant_type=item.participant_type,
            candidate_id=item.firm_id or item.expert_id, display_name=item.display_name_snapshot,
            contributions=[_contribution_response(value) for value in contributions_by_participant[item.id]],
        ) for item in participants_by_revision[revision.id]]
        gap_responses = [ScenarioGapAssessmentResponse(
            gap_assessment_id=item.id, gap_id=item.gap_id,
            requirement_id=item.requirement_id, position_id=item.position_id,
            review_assertion_id=item.review_assertion_id,
            w4_coverage_state=item.w4_coverage_state_snapshot,
            w4_review_state=item.w4_review_state_snapshot,
            resolution_category=item.resolution_category_snapshot,
            state=item.state, is_current_stage=item.is_current_stage,
            is_blocking=item.is_blocking, rationale_code=item.rationale_code,
        ) for item in gaps_by_revision[revision.id]]
        issue_responses = [ScenarioIssueResponse(
            issue_id=item.id, issue_code=item.issue_code, severity=item.severity,
            gap_id=item.gap_id, participant_id=item.participant_id,
            contribution_id=item.contribution_id, details=item.details,
        ) for item in issues_by_revision[revision.id]]
        decision_responses = [TeamScenarioDecisionResponse(
            decision_id=item.id, revision_id=item.revision_id, decision=item.decision,
            reason=item.reason, explicit_confirmation=item.explicit_confirmation,
            actor_membership_id=item.actor_membership_id, created_at=item.created_at,
        ) for item in decisions_by_revision[revision.id]]
        return TeamScenarioRevisionResponse(
            revision_id=revision.id, version_number=revision.version_number,
            analysis_run_id=revision.analysis_run_id, analysis_pack_id=revision.analysis_pack_id,
            selection_sha256=revision.selection_sha256,
            assessment_schema_version=revision.assessment_schema_version,
            assessment_state=revision.assessment_state,
            current_assessment_state=(
                revision.assessment_state
                if not reasons or revision.assessment_state in {"DRAFT", "BLOCKED"}
                else "NEEDS_REVIEW"
            ),
            scenario_current=not reasons, stale_reasons=reasons,
            gap_count=revision.gap_count, covered_gap_count=revision.covered_gap_count,
            unresolved_gap_count=revision.unresolved_gap_count,
            participant_count=revision.participant_count,
            confirmed_participant_count=revision.confirmed_participant_count,
            issue_count=revision.issue_count, blocking_issue_count=revision.blocking_issue_count,
            unresolved_later_stage_count=revision.unresolved_later_stage_count,
            source_provenance_count=revision.source_provenance_count,
            private_provenance_count=revision.private_provenance_count,
            participants=participant_responses, gap_assessments=gap_responses,
            issues=issue_responses, decisions=decision_responses,
            created_by_membership_id=revision.created_by_membership_id,
            created_at=revision.created_at,
        )

    result: list[TeamScenarioResponse] = []
    for scenario in scenarios:
        revision_responses = [revision_response(item) for item in revisions_by_scenario[scenario.id]]
        result.append(TeamScenarioResponse(
            scenario_id=scenario.id, organization_id=scenario.organization_id,
            pursuit_id=scenario.pursuit_id, lead_organization_id=scenario.organization_id,
            title=scenario.title, archived_at=scenario.archived_at,
            latest_revision=revision_responses[-1] if revision_responses else None,
            revisions=revision_responses, created_by_membership_id=scenario.created_by_membership_id,
            created_at=scenario.created_at,
        ))
    return result


async def list_team_scenarios(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
) -> list[TeamScenarioResponse]:
    rows = list((await db.scalars(select(TeamScenario).where(
        TeamScenario.organization_id == organization_id,
        TeamScenario.pursuit_id == pursuit_id,
    ).order_by(TeamScenario.created_at, TeamScenario.id).limit(50))).all())
    return await _project_scenarios(
        db, organization_id=organization_id, pursuit_id=pursuit_id, scenarios=rows,
    )


async def get_team_scenario(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, scenario_id: UUID,
) -> TeamScenarioResponse | None:
    row = await db.scalar(select(TeamScenario).where(
        TeamScenario.id == scenario_id,
        TeamScenario.organization_id == organization_id,
        TeamScenario.pursuit_id == pursuit_id,
    ))
    if row is None:
        return None
    projected = await _project_scenarios(
        db, organization_id=organization_id, pursuit_id=pursuit_id, scenarios=[row],
    )
    return projected[0]


async def _required_scenario(
    db: AsyncSession, organization_id: UUID, pursuit_id: UUID, scenario_id: UUID,
) -> TeamScenarioResponse:
    result = await get_team_scenario(
        db, organization_id=organization_id, pursuit_id=pursuit_id, scenario_id=scenario_id,
    )
    if result is None:
        raise RuntimeError("Team scenario projection failed")
    return result


async def append_team_scenario_decision(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, scenario_id: UUID,
    revision_id: UUID, membership_id: UUID, request: TeamScenarioDecisionCreateRequest,
) -> TeamScenarioResponse:
    await _require_active_membership(db, organization_id=organization_id, membership_id=membership_id)
    await _owned_scenario(
        db, organization_id=organization_id, pursuit_id=pursuit_id, scenario_id=scenario_id,
    )
    projection = await _required_scenario(db, organization_id, pursuit_id, scenario_id)
    revision = next((item for item in projection.revisions if item.revision_id == revision_id), None)
    if revision is None:
        raise TeamScenarioNotFoundError("Team scenario revision not found")
    if request.decision == "APPROVED_FOR_PROPOSAL":
        if not request.explicit_confirmation:
            raise TeamScenarioEligibilityError("Proposal approval requires explicit confirmation")
        if not revision.scenario_current or revision.current_assessment_state != "VIABLE":
            raise TeamScenarioEligibilityError("Proposal approval requires a current VIABLE revision")
    db.add(TeamScenarioDecision(
        organization_id=organization_id, scenario_id=scenario_id, revision_id=revision_id,
        actor_membership_id=membership_id, decision=request.decision,
        reason=request.reason.strip(), explicit_confirmation=request.explicit_confirmation,
    ))
    await db.commit()
    return await _required_scenario(db, organization_id, pursuit_id, scenario_id)


async def get_proposal_handoff(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID,
    scenario_id: UUID, revision_id: UUID,
) -> ProposalHandoffResponse:
    projection = await _required_scenario(db, organization_id, pursuit_id, scenario_id)
    revision = next((item for item in projection.revisions if item.revision_id == revision_id), None)
    if revision is None:
        raise TeamScenarioNotFoundError("Team scenario revision not found")
    latest_decision = revision.decisions[-1] if revision.decisions else None
    if latest_decision is None or latest_decision.decision != "APPROVED_FOR_PROPOSAL":
        raise TeamScenarioEligibilityError("The current decision for this exact revision is not proposal approval")
    if not revision.scenario_current or revision.current_assessment_state != "VIABLE":
        raise TeamScenarioEligibilityError("A stale or non-VIABLE revision cannot authorize a proposal handoff")
    return ProposalHandoffResponse(
        scenario_id=scenario_id, revision_id=revision_id,
        approval_decision_id=latest_decision.decision_id,
        analysis_run_id=revision.analysis_run_id, analysis_pack_id=revision.analysis_pack_id,
        scenario_current=revision.scenario_current, assessment_state=revision.current_assessment_state,
        gap_assessments=revision.gap_assessments, participants=revision.participants,
        unresolved_later_stage_count=revision.unresolved_later_stage_count,
        source_provenance_count=revision.source_provenance_count,
        private_provenance_count=revision.private_provenance_count,
    )
