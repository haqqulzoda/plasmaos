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
    # Terms §1: every paid plan includes partner and expert search (RC-5: per-tender too).
    PLAN_PER_TENDER: Plan(PLAN_PER_TENDER, PERIOD_LIFETIME, 1, 0, None, True, True, True, INTELLIGENCE_NONE),
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


# B1: prices and what can be bought in the app. One table for the gates above and for billing.
# Amounts are USD cents; invoices to Uzbek residents show UZS at the CBU rate of the issue date.
CURRENCY = "USD"

BILLING_FREE = "free"
BILLING_ONE_TIME = "one_time"
BILLING_ANNUAL = "annual"
BILLING_CONTACT = "contact"  # "Talk to us": quoted and invoiced by the team


@dataclass(frozen=True)
class Price:
    plan: str
    amount_cents: int  # the list price for the term (pilot: 3 months; annual plans: a year)
    billing: str
    monthly_cents: int | None = None
    from_price: bool = False  # Enterprise: "from"


PRICES: dict[str, Price] = {
    PLAN_EXPLORE: Price(PLAN_EXPLORE, 0, BILLING_FREE),
    PLAN_PILOT: Price(PLAN_PILOT, 90_000, BILLING_ONE_TIME, monthly_cents=30_000),
    PLAN_PURSUIT_DESK: Price(PLAN_PURSUIT_DESK, 600_000, BILLING_ANNUAL),
    PLAN_AGENT: Price(PLAN_AGENT, 1_800_000, BILLING_CONTACT),
    PLAN_ENTERPRISE: Price(PLAN_ENTERPRISE, 3_600_000, BILLING_CONTACT, from_price=True),
    PLAN_PER_TENDER: Price(PLAN_PER_TENDER, 40_000, BILLING_CONTACT),
}

PRODUCT_PILOT = "pilot"
PRODUCT_PURSUIT_DESK = "pursuit_desk"
PRODUCT_EXTRA_PURSUIT = "extra_pursuit"
PRODUCT_PER_TENDER = "per_tender"
PRODUCTS_FOR_SALE = (PRODUCT_PILOT, PRODUCT_PURSUIT_DESK, PRODUCT_EXTRA_PURSUIT)  # self-serve
# Not self-serve: an admin sends a one-use checkout link (an offer) or issues the invoice.
ADMIN_PRODUCTS = (PRODUCT_PER_TENDER,)


@dataclass(frozen=True)
class Product:
    """A checkout product (/billing/start?plan=<code>)."""

    code: str
    plan: str | None  # the plan a payment activates; None: an add-on
    amount_cents: int
    billing: str
    term_months: int | None
    extra_pursuits: int = 0


PRODUCTS: dict[str, Product] = {
    PRODUCT_PILOT: Product(PRODUCT_PILOT, PLAN_PILOT, PRICES[PLAN_PILOT].amount_cents, BILLING_ONE_TIME, 3),
    PRODUCT_PURSUIT_DESK: Product(
        PRODUCT_PURSUIT_DESK, PLAN_PURSUIT_DESK, PRICES[PLAN_PURSUIT_DESK].amount_cents, BILLING_ANNUAL, 12
    ),
    PRODUCT_EXTRA_PURSUIT: Product(PRODUCT_EXTRA_PURSUIT, None, 20_000, BILLING_ONE_TIME, None, extra_pursuits=1),
    # One pursuit end to end and a review call; each purchase adds one to the per-tender plan's limit.
    PRODUCT_PER_TENDER: Product(PRODUCT_PER_TENDER, PLAN_PER_TENDER, PRICES[PLAN_PER_TENDER].amount_cents, BILLING_ONE_TIME, None),
}

# The Plasma Pilot and Subscription Terms, version 1 (effective 26 Oct 2026), set the numbers below.
# §5: the paid pilot is credited once, in full, to the first annual-plan order placed within 30 days after the
# pilot ends (a one-time $900 off Pursuit Desk).
PILOT_CREDIT_CENTS = PRICES[PLAN_PILOT].amount_cents
PILOT_CREDIT_WINDOW_DAYS = 30
PILOT_GUARANTEE_DAYS = 30  # §6: full pilot refund if asked within 30 days of activation
ANNUAL_REFUND_DAYS = 14  # §6: annual fees not refundable after 14 days from activation
ANNUAL_OFFER_DAY = 75  # the in-app Pursuit Desk offer from the pilot's 75th day
BANK_TRANSFER_REMINDER_DAYS = (3, 6)
BANK_TRANSFER_DUE_DAYS = 7  # §4: payment due within 7 days
BANK_TRANSFER_SUSPEND_DAY = 10  # §4: still unpaid 10 days after issue: back to Explore


def product_for(code: str | None) -> Product | None:
    return PRODUCTS.get(code or "")
