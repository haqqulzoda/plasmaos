"""Shared legacy-compatible pursuit stage transition contract."""

from app.models.base import TenderEngagementStatus


NORMAL_TRANSITIONS: dict[TenderEngagementStatus, frozenset[TenderEngagementStatus]] = {
    TenderEngagementStatus.SAVED: frozenset({TenderEngagementStatus.EVALUATING, TenderEngagementStatus.PREPARING, TenderEngagementStatus.DISMISSED}),
    TenderEngagementStatus.EVALUATING: frozenset({TenderEngagementStatus.SAVED, TenderEngagementStatus.PREPARING, TenderEngagementStatus.DISMISSED}),
    TenderEngagementStatus.PREPARING: frozenset({TenderEngagementStatus.SAVED, TenderEngagementStatus.EVALUATING, TenderEngagementStatus.SUBMITTED, TenderEngagementStatus.DISMISSED}),
    TenderEngagementStatus.SUBMITTED: frozenset({TenderEngagementStatus.WON, TenderEngagementStatus.LOST}),
    TenderEngagementStatus.WON: frozenset(),
    TenderEngagementStatus.LOST: frozenset(),
    TenderEngagementStatus.DISMISSED: frozenset({TenderEngagementStatus.SAVED, TenderEngagementStatus.EVALUATING, TenderEngagementStatus.PREPARING}),
}

CORRECTION_TRANSITIONS: dict[TenderEngagementStatus, frozenset[TenderEngagementStatus]] = {
    TenderEngagementStatus.SUBMITTED: frozenset({TenderEngagementStatus.PREPARING}),
    TenderEngagementStatus.WON: frozenset({TenderEngagementStatus.SUBMITTED, TenderEngagementStatus.LOST}),
    TenderEngagementStatus.LOST: frozenset({TenderEngagementStatus.SUBMITTED, TenderEngagementStatus.WON}),
}


def transition_is_allowed(current: TenderEngagementStatus, target: TenderEngagementStatus, *, correction: bool = False) -> bool:
    matrix = CORRECTION_TRANSITIONS if correction else NORMAL_TRANSITIONS
    return target in matrix.get(current, frozenset())
