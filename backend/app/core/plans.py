"""P3: organization plans, their limits and feature gates (the pricing table of 23 Oct 2026).

A *pursuit* counts once, when its first analysis starts; re-analysis (an amendment, a retry) never
counts again. Browsing and saving tenders is unlimited. ``None`` means unlimited.
"""

from __future__ import annotations

from dataclasses import dataclass

PLAN_EXPLORE = "explore"
PLAN_PILOT = "pilot"
PLAN_PURSUIT_DESK = "pursuit_desk"
PLAN_AGENT = "agent"
PLAN_ENTERPRISE = "enterprise"
PLAN_PER_TENDER = "per_tender"
PLANS = (PLAN_EXPLORE, PLAN_PILOT, PLAN_PURSUIT_DESK, PLAN_AGENT, PLAN_ENTERPRISE, PLAN_PER_TENDER)

# How a plan's counting period is drawn.
PERIOD_CALENDAR_MONTH = "calendar_month"
PERIOD_PLAN_TERM = "plan_term"  # plan_started_on .. plan_ends_on (the 3-month pilot)
PERIOD_PLAN_YEAR = "plan_year"  # yearly from plan_started_on
PERIOD_LIFETIME = "lifetime"  # per-tender reviews: everything bought since plan_started_on

FEATURE_TENDER_CHECK = "tender_check"  # requirements with source quotes and eligibility gaps
FEATURE_EOI = "eoi"
FEATURE_OWN_EVIDENCE = "own_evidence"  # company records: own firm, references, experts, CVs, team matching
FEATURE_PARTNER_SEARCH = "partner_search"  # network and public-award suggestions, introductions
FEATURE_COMPETITOR_INTELLIGENCE = "competitor_intelligence"  # who bid and won similar tenders
FEATURES = (FEATURE_TENDER_CHECK, FEATURE_EOI, FEATURE_OWN_EVIDENCE, FEATURE_PARTNER_SEARCH,
            FEATURE_COMPETITOR_INTELLIGENCE)

INTELLIGENCE_NONE = "none"
INTELLIGENCE_SECTOR_HEADLINES = "sector_headlines"
INTELLIGENCE_SECTOR = "sector"
INTELLIGENCE_FULL = "full"


@dataclass(frozen=True)
class Plan:
    code: str
    period: str
    pursuit_limit: int | None
    introduction_limit: int | None
    user_limit: int | None
    eoi: bool
    own_evidence: bool
    partner_search: bool
    intelligence: str

    def has(self, feature: str) -> bool:
        if feature == FEATURE_TENDER_CHECK:
            return True
        if feature == FEATURE_COMPETITOR_INTELLIGENCE:
            return self.intelligence == INTELLIGENCE_FULL
        return bool(getattr(self, feature))


CATALOG: dict[str, Plan] = {
    # Free: one tender check a calendar month, requirements view only; two users.
    PLAN_EXPLORE: Plan(PLAN_EXPLORE, PERIOD_CALENDAR_MONTH, 1, 0, 2, False, False, False,
                       INTELLIGENCE_SECTOR_HEADLINES),
    PLAN_PILOT: Plan(PLAN_PILOT, PERIOD_PLAN_TERM, 6, 1, None, True, True, True, INTELLIGENCE_NONE),
    PLAN_PURSUIT_DESK: Plan(PLAN_PURSUIT_DESK, PERIOD_PLAN_YEAR, 24, 2, None, True, True, True, INTELLIGENCE_SECTOR),
    PLAN_AGENT: Plan(PLAN_AGENT, PERIOD_PLAN_YEAR, 60, 12, None, True, True, True, INTELLIGENCE_FULL),
    # Enterprise: the pursuit number comes from the agreement (pursuit_limit_override); 150 until set.
    PLAN_ENTERPRISE: Plan(PLAN_ENTERPRISE, PERIOD_PLAN_YEAR, 150, None, None, True, True, True, INTELLIGENCE_FULL),
    # Per-tender review ($400): one pursuit end to end per purchase (pursuit_limit_override = purchases).
    PLAN_PER_TENDER: Plan(PLAN_PER_TENDER, PERIOD_LIFETIME, 1, 0, None, True, True, False, INTELLIGENCE_NONE),
}

# The P1 access state each plan implies (the company approval follows it); "disabled" is separate.
ACCESS_STATE_FOR_PLAN = {
    PLAN_EXPLORE: "explore",
    PLAN_PILOT: "pilot",
    PLAN_PURSUIT_DESK: "paid",
    PLAN_AGENT: "paid",
    PLAN_ENTERPRISE: "paid",
    PLAN_PER_TENDER: "paid",
}

NEAR_LIMIT_SHARE = 0.8


def plan_for(code: str | None) -> Plan:
    return CATALOG.get(code or PLAN_EXPLORE, CATALOG[PLAN_EXPLORE])
