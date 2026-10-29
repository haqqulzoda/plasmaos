"""B1: billing and the instant pilot.

Checkout (/billing/start?plan=pilot|pursuit_desk|extra_pursuit): company details, the Pilot Terms
accepted (version + SHA-256 of the exact text + user + time + IP), then

- card: a Polar checkout (metadata organization_id, order_id); the ``order.paid`` webhook activates
  the plan, ``order.refunded`` (full) returns it to Explore, ``subscription.*`` follow the annual plan;
- bank transfer: an invoice PL-YYYY-NNN (UZS at the CBU rate of the day for residents, USD
  otherwise) e-mailed as a PDF, the plan active at once with billing status ``awaiting_payment``,
  reminders on days 3 and 6, back to Explore on day 10 unpaid; an admin marks it paid.

Activation: plan and dates (pilot: today + 3 months; Pursuit Desk: + 12 months) through the P1/P3
access writer, a welcome e-mail with the kickoff link, a team alert, an onboarding task. An extra
pursuit adds one pursuit to the current period. A paid pilot is credited once ($900) to the first
Pursuit Desk order. Every change is an administrative audit event. Callers commit.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.plans import (
    ACCESS_STATE_FOR_PLAN,
    ANNUAL_OFFER_DAY,
    ANNUAL_REFUND_DAYS,
    BANK_TRANSFER_DUE_DAYS,
    BANK_TRANSFER_REMINDER_DAYS,
    BANK_TRANSFER_SUSPEND_DAY,
    PILOT_CREDIT_CENTS,
    PILOT_CREDIT_WINDOW_DAYS,
    PILOT_GUARANTEE_DAYS,
    PERIOD_LIFETIME,
    PERIOD_PLAN_TERM,
    PERIOD_PLAN_YEAR,
    PLAN_EXPLORE,
    PLAN_PILOT,
    PLAN_PURSUIT_DESK,
    PRICES,
    ADMIN_PRODUCTS,
    PLAN_PER_TENDER,
    PRODUCT_EXTRA_PURSUIT,
    PRODUCT_PER_TENDER,
    PRODUCT_PILOT,
    PRODUCT_PURSUIT_DESK,
    PRODUCTS,
    PRODUCTS_FOR_SALE,
    CATALOG,
)
from app.models.billing import (
    BillingCustomer,
    BillingEvent,
    BillingOffer,
    BillingInvoice,
    BillingOrder,
    BillingPayment,
    OnboardingTask,
    PilotCreditRedemption,
    TermsAcceptance,
)
from app.models.company import CompanyProfile
from app.models.tenancy import Organization
from app.models.user import User
from app.services import billing_polar
from app.services.admin_activity import (
    ACTION_BILLING_CANCEL_CONFIRMED,
    ACTION_BILLING_CANCEL_REQUESTED,
    ACTION_BILLING_CREDIT_APPLIED,
    ACTION_BILLING_OFFER_CREATED,
    ACTION_BILLING_CUSTOMER_UPDATED,
    ACTION_BILLING_INVOICE_ISSUED,
    ACTION_BILLING_ONBOARDING_COMPLETED,
    ACTION_BILLING_ORDER_CREATED,
    ACTION_BILLING_PAYMENT_RECORDED,
    ACTION_BILLING_PLAN_ACTIVATED,
    ACTION_BILLING_PLAN_SUSPENDED,
    ACTION_BILLING_REFUND_RECORDED,
    ACTION_BILLING_STATUS_CHANGED,
    ACTION_BILLING_TERMS_ACCEPTED,
    ACTOR_SYSTEM,
    ACTOR_USER,
    OUTCOME_SUCCESS,
    SOURCE_BILLING,
    record_admin_audit_event,
)
from app.services.admin_alerts import stage_admin_alert
from app.services.billing_fx import FxUnavailableError, usd_rate
from app.services.billing_invoice_pdf import bank_lines
from app.services.email_notifications import stage_email, user_locale

# The Plasma Pilot and Subscription Terms, version 1, effective 26 Oct 2026 (owner-approved text; the PDF is the
# same text, attached to the activation e-mail). Every acceptance stores the SHA-256 of the Markdown shown.
TERMS_VERSION = "PILOT_TERMS_v1"
TASHKENT = ZoneInfo("Asia/Tashkent")
TERMS_PATH = Path(__file__).resolve().parents[1] / "legal" / "PILOT_TERMS_v1.md"
TERMS_PDF_PATH = TERMS_PATH.with_suffix(".pdf")
TERMS_PDF_NAME = "Plasma-Pilot-and-Subscription-Terms-v1.pdf"
PAID_PLANS = ("pursuit_desk", "agent", "enterprise", "per_tender")
OFFER_DAYS = 14
ATTRIBUTION_KEYS = ("ref", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")
METHOD_CARD = "card"
METHOD_BANK = "bank_transfer"
ACTOR_WEBHOOK = "billing:polar-webhook"
ACTOR_SCHEDULE = "billing:schedule"
ACTOR_CHECKOUT = "billing:checkout"
ACTOR_RECONCILE = "reconcile"  # scripts/billing/reconcile_polar.py (Deploy 5.1)
ORDER_PAID_ALERT_HOURS = 24
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TIN = re.compile(r"^(\d{9}|\d{14})$")


class BillingError(Exception):
    status_code = 422

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class BillingNotFoundError(BillingError):
    status_code = 404


class BillingConflictError(BillingError):
    status_code = 409


class BillingUnavailableError(BillingError):
    status_code = 503


def _now() -> datetime:
    return datetime.now(timezone.utc)


def billing_today() -> date:
    """The business date in Tashkent: invoice dates, the CBU rate of the day, plan start dates, the day count."""
    return datetime.now(TASHKENT).date()


def _local_date(moment: datetime | None) -> date | None:
    return moment.astimezone(TASHKENT).date() if moment is not None else None


def add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def terms() -> dict[str, str]:
    """The Pilot Terms as shown at checkout; the hash is over this exact text (LF line ends)."""
    markdown = TERMS_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    return {"version": TERMS_VERSION, "sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            "markdown": markdown}


def bank_transfer_available(currency: str) -> bool:
    """Bank details for the invoice currency are set; USD also needs INVOICE_USD_ENABLED (RC-5)."""
    if currency == "USD" and not settings.INVOICE_USD_ENABLED:
        return False
    return bool(bank_lines(currency))


def catalog() -> dict[str, Any]:
    """Plans (prices, limits, features) and the checkout products: one table for the gates and billing."""
    plans = []
    for code, plan in CATALOG.items():
        price = PRICES[code]
        plans.append({
            "code": code, "price_cents": price.amount_cents, "monthly_cents": price.monthly_cents,
            "billing": price.billing, "from_price": price.from_price, "pursuit_limit": plan.pursuit_limit,
            "introduction_limit": plan.introduction_limit, "user_limit": plan.user_limit, "period": plan.period,
            "features": {"eoi": plan.eoi, "own_evidence": plan.own_evidence, "partner_search": plan.partner_search,
                         "competitor_intelligence": plan.has("competitor_intelligence")},
            "intelligence": plan.intelligence,
        })
    products = [{
        "code": product.code, "plan": product.plan, "amount_cents": product.amount_cents,
        "billing": product.billing, "term_months": product.term_months, "extra_pursuits": product.extra_pursuits,
        "card_available": billing_polar.card_available(product.code),
    } for product in PRODUCTS.values() if product.code in PRODUCTS_FOR_SALE]
    return {"currency": "USD", "plans": plans, "products": products, "pilot_credit_cents": PILOT_CREDIT_CENTS,
            "bank_transfer": {"UZS": bank_transfer_available("UZS"), "USD": bank_transfer_available("USD")},
            "polar_env": settings.POLAR_ENV}


# ---- audit, alerts, e-mail ---------------------------------------------------------------------

async def _owner(db: AsyncSession, organization: Organization) -> User | None:
    profile = await db.get(CompanyProfile, organization.legacy_company_profile_id)
    return await db.get(User, profile.user_id) if profile is not None else None


async def _audit(
    db: AsyncSession, organization: Organization, action: str, *, actor_user: User | None, actor_label: str | None,
    resource_type: str, resource_id: Any, new_state: dict[str, Any] | None = None,
    previous_state: dict[str, Any] | None = None, reason: str | None = None,
) -> None:
    target = await _owner(db, organization)
    await record_admin_audit_event(
        db, action=action, outcome=OUTCOME_SUCCESS, source=SOURCE_BILLING,
        actor_user=actor_user, actor_type=ACTOR_USER if actor_user is not None else ACTOR_SYSTEM,
        actor_label=None if actor_user is not None else (actor_label or "billing"),
        target_user=target, target_email=None if target is not None else "organization@plasma.invalid",
        target_resource_type=resource_type, target_resource_id=str(resource_id),
        previous_state=previous_state, new_state=new_state, reason=(reason or "")[:500] or None,
        metadata={"organization_id": str(organization.id)},
    )


async def _alert(
    db: AsyncSession, organization: Organization, event: str, order: BillingOrder | None, **extra: Any,
) -> None:
    payload = {
        "event": event, "organization_id": str(organization.id), "organization_name": _display(organization),
        "plan": organization.plan, "billing_status": organization.billing_status,
        "at": _now().isoformat(timespec="seconds"),
    }
    if order is not None:
        payload.update({"order_id": str(order.id), "product": order.product, "method": order.method,
                        "amount_cents": order.amount_cents, "credit_cents": order.credit_cents})
    payload.update({key: value for key, value in extra.items() if value is not None})
    key = order.id if order is not None else f"{organization.id}:{organization.plan_ends_on}"
    await stage_admin_alert(db, kind="BILLING", dedupe_key=f"admin-alert:billing:{event}:{key}", payload=payload)


async def _recipient(db: AsyncSession, order: BillingOrder) -> tuple[str | None, str, UUID | None]:
    customer = await db.scalar(select(BillingCustomer).where(BillingCustomer.organization_id == order.organization_id))
    buyer = await db.get(User, order.created_by_user_id) if order.created_by_user_id else None
    email = customer.billing_email if customer is not None else (buyer.email if buyer is not None else None)
    return email, user_locale(buyer), buyer.id if buyer is not None else None


async def _email(db: AsyncSession, order: BillingOrder, kind: str, dedupe: str, payload: dict[str, Any]) -> None:
    email, locale, user_id = await _recipient(db, order)
    if email:
        await stage_email(db, dedupe_key=f"email:billing:{dedupe}", kind=kind, category="BILLING",
                          recipient_email=email, locale=locale, payload=payload, user_id=user_id)


def _display(organization: Organization) -> str:
    return (organization.display_name or "").strip() or "Organization"


def kickoff_url() -> str | None:
    return (settings.BILLING_KICKOFF_URL or settings.PUBLIC_BOOK_CALL_URL or "").strip() or None


# ---- customers and terms -----------------------------------------------------------------------

def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


async def get_customer(db: AsyncSession, organization_id: UUID) -> BillingCustomer | None:
    return await db.scalar(select(BillingCustomer).where(BillingCustomer.organization_id == organization_id))


def customer_view(customer: BillingCustomer | None) -> dict[str, Any] | None:
    if customer is None:
        return None
    return {"legal_name": customer.legal_name, "tin": customer.tin, "country": customer.country,
            "address": customer.address, "billing_email": customer.billing_email, "resident": customer.resident,
            "updated_at": customer.updated_at}


async def save_customer(
    db: AsyncSession, *, organization: Organization, user: User, data: dict[str, Any],
) -> BillingCustomer:
    legal_name = _clean(data.get("legal_name"), 300)
    country = _clean(data.get("country"), 2).upper()
    address = _clean(data.get("address"), 500)
    email = _clean(data.get("billing_email"), 255).lower()
    tin = re.sub(r"\s", "", str(data.get("tin") or ""))[:40] or None
    resident = bool(data.get("resident"))
    if len(legal_name) < 2:
        raise BillingError("customer_invalid", "Enter the company's legal name")
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise BillingError("customer_invalid", "Choose the country")
    if len(address) < 5:
        raise BillingError("customer_invalid", "Enter the company's legal address")
    if not _EMAIL.match(email):
        raise BillingError("customer_invalid", "Enter a valid billing e-mail")
    if resident and country != "UZ":
        raise BillingError("customer_invalid", "A resident of Uzbekistan has the country Uzbekistan")
    if resident and (tin is None or not _TIN.match(tin)):
        raise BillingError("customer_invalid", "Enter the 9-digit TIN (STIR) of the company")
    customer = await get_customer(db, organization.id)
    before = customer_view(customer)
    if customer is None:
        customer = BillingCustomer(organization_id=organization.id)
        db.add(customer)
    customer.legal_name, customer.tin, customer.country = legal_name, tin, country
    customer.address, customer.billing_email, customer.resident = address, email, resident
    customer.updated_by_user_id = user.id
    await db.flush()
    after = {"legal_name": legal_name, "tin_set": tin is not None, "country": country, "resident": resident}
    await _audit(db, organization, ACTION_BILLING_CUSTOMER_UPDATED, actor_user=user, actor_label=None,
                 resource_type="BILLING_CUSTOMER", resource_id=customer.id, new_state=after,
                 previous_state=None if before is None else {
                     "legal_name": before["legal_name"], "tin_set": before["tin"] is not None,
                     "country": before["country"], "resident": before["resident"]},
                 reason="Billing details saved.")
    return customer


# ---- eligibility -------------------------------------------------------------------------------

async def pilot_credit_source(db: AsyncSession, organization_id: UUID, *, on: date | None = None) -> BillingOrder | None:
    """The paid pilot not yet credited, for an annual order placed ``on`` that date (terms §5: within 30 days after
    the pilot ends). None when there is none, the credit was used, or the window has closed."""
    on = on or billing_today()
    used = await db.scalar(select(PilotCreditRedemption.id).where(PilotCreditRedemption.organization_id == organization_id))
    if used is not None:
        return None
    pilot = await db.scalar(
        select(BillingOrder).where(
            BillingOrder.organization_id == organization_id, BillingOrder.product == PRODUCT_PILOT,
            BillingOrder.status == "paid",
        ).order_by(BillingOrder.paid_at).limit(1)
    )
    if pilot is None or (pilot.plan_ends_on is not None
                         and on > pilot.plan_ends_on + timedelta(days=PILOT_CREDIT_WINDOW_DAYS)):
        return None
    return pilot


async def checkout_blocker(
    db: AsyncSession, organization: Organization, product: str, *, offer: BillingOffer | None = None,
) -> str | None:
    """Why this organization cannot buy ``product`` now (a code), or None. An admin-sold product needs a
    valid offer (a one-use link) or an admin-issued invoice."""
    if product in ADMIN_PRODUCTS and offer is None:
        return "offer_required"
    if product not in PRODUCTS_FOR_SALE and product not in ADMIN_PRODUCTS:
        return "unknown_product"
    if organization.access_state == "disabled":
        return "organization_disabled"
    open_order = await db.scalar(select(BillingOrder.id).where(
        BillingOrder.organization_id == organization.id, BillingOrder.product == product,
        BillingOrder.status == "awaiting_payment",
    ))
    if open_order is not None and product != PRODUCT_EXTRA_PURSUIT:
        return "awaiting_payment"
    if product == PRODUCT_PILOT:
        if organization.plan in PAID_PLANS:
            return "already_paid_plan"
        earlier = await db.scalar(select(BillingOrder.id).where(
            BillingOrder.organization_id == organization.id, BillingOrder.product == PRODUCT_PILOT,
            BillingOrder.status.in_(("awaiting_payment", "paid", "lapsed", "refunded")),
        ))
        if earlier is not None:
            return "pilot_used"
    if product == PRODUCT_PURSUIT_DESK:
        if organization.plan in ("agent", "enterprise"):
            return "already_higher_plan"
        if organization.plan == PLAN_PURSUIT_DESK and organization.billing_status in ("paid", "awaiting_payment"):
            return "already_on_plan"
    if product == PRODUCT_EXTRA_PURSUIT and organization.plan == PLAN_EXPLORE:
        return "plan_required"
    if product == PRODUCT_PER_TENDER and organization.plan not in (PLAN_EXPLORE, PLAN_PER_TENDER):
        return "per_tender_on_plan"  # on a pilot or a plan: an extra pursuit instead
    return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def find_offer(
    db: AsyncSession, organization_id: UUID, token: str | None, product: str, *, lock: bool = False,
) -> BillingOffer | None:
    """The unused, unexpired offer behind ``token`` for this organization and product, or None."""
    if not token or len(token) > 200:
        return None
    statement = select(BillingOffer).where(
        BillingOffer.token_sha256 == _token_hash(token), BillingOffer.organization_id == organization_id,
        BillingOffer.product == product, BillingOffer.order_id.is_(None), BillingOffer.expires_at > _now(),
    )
    return await db.scalar(statement.with_for_update() if lock else statement)


async def create_offer(
    db: AsyncSession, *, organization: Organization, product: str, actor_user: User, note: str | None = None,
    days: int = OFFER_DAYS,
) -> tuple[BillingOffer, str]:
    """A one-use checkout link for an admin-sold product; returns the offer and the token (shown once)."""
    if product not in ADMIN_PRODUCTS:
        raise BillingError("unknown_product", "Only an admin-sold product needs an offer")
    blocker = await checkout_blocker(db, organization, product, offer=BillingOffer())
    if blocker:
        raise BillingConflictError(blocker, _BLOCKER_MESSAGES.get(blocker, "This cannot be offered now"))
    token = secrets.token_urlsafe(24)
    offer = BillingOffer(
        organization_id=organization.id, product=product, token_sha256=_token_hash(token),
        note=_clean(note, 1000) or None, expires_at=_now() + timedelta(days=max(1, min(days, 60))),
        created_by_user_id=actor_user.id,
    )
    db.add(offer)
    await db.flush()
    await _audit(db, organization, ACTION_BILLING_OFFER_CREATED, actor_user=actor_user, actor_label=None,
                 resource_type="BILLING_OFFER", resource_id=offer.id,
                 new_state={"product": product, "expires_at": offer.expires_at.isoformat(timespec="seconds")},
                 reason=offer.note or f"Checkout link for {product}.")
    return offer, token


def clean_attribution(values: dict[str, Any] | None) -> dict[str, str] | None:
    """ref and utm_* only, short strings; anything else is dropped."""
    cleaned = {key: _clean(values[key], 200) for key in ATTRIBUTION_KEYS
               if values and isinstance(values.get(key), str) and _clean(values[key], 200)}
    return cleaned or None


async def quote(
    db: AsyncSession, organization: Organization, product_code: str, *, today: date | None = None,
    offer_token: str | None = None,
) -> dict[str, Any]:
    product = PRODUCTS.get(product_code)
    if product is None:
        raise BillingNotFoundError("unknown_product", "This product is not sold in the app")
    offer = await find_offer(db, organization.id, offer_token, product.code) if product.code in ADMIN_PRODUCTS else None
    credit = 0
    if product.code == PRODUCT_PURSUIT_DESK and await pilot_credit_source(db, organization.id, on=today) is not None:
        credit = min(PILOT_CREDIT_CENTS, product.amount_cents)
    customer = await get_customer(db, organization.id)
    currency = "UZS" if customer is not None and customer.resident else "USD"
    return {
        "product": product.code, "plan": product.plan, "list_amount_cents": product.amount_cents,
        "credit_cents": credit, "amount_cents": product.amount_cents - credit, "billing": product.billing,
        "term_months": product.term_months,
        "blocker": await checkout_blocker(db, organization, product.code, offer=offer),
        "methods": {"card": billing_polar.card_available(product.code), "bank_transfer": bank_transfer_available(currency)},
        "invoice_currency": currency,
    }


# ---- checkout ----------------------------------------------------------------------------------

async def accept_terms(
    db: AsyncSession, *, organization: Organization, user: User, version: str, sha256: str,
    ip_address: str | None, user_agent: str | None, signed_note: str | None = None,
) -> TermsAcceptance:
    """Online: the customer's user, the text hash shown, IP. Signed: an admin records the signed order form
    (``user`` is the admin; no customer user, no IP)."""
    current = terms()
    if version != current["version"] or sha256 != current["sha256"]:
        raise BillingConflictError("terms_changed", "The terms changed: read and accept the current version")
    signed = signed_note is not None
    acceptance = TermsAcceptance(
        organization_id=organization.id, user_id=None if signed else user.id, terms_version=version,
        text_sha256=sha256, ip_address=None if signed else (ip_address or "")[:64] or None,
        user_agent=None if signed else (user_agent or "")[:300] or None,
        accepted_via="signed" if signed else "online", note=_clean(signed_note, 1000) or None if signed else None,
    )
    db.add(acceptance)
    await db.flush()
    await _audit(db, organization, ACTION_BILLING_TERMS_ACCEPTED, actor_user=user, actor_label=None,
                 resource_type="TERMS_ACCEPTANCE", resource_id=acceptance.id,
                 new_state={"terms_version": version, "text_sha256": sha256, "ip_address": acceptance.ip_address,
                            "accepted_via": acceptance.accepted_via},
                 reason=acceptance.note or f"{version} accepted.")
    return acceptance


async def start_checkout(
    db: AsyncSession, *, organization: Organization, user: User, product_code: str, method: str,
    terms_version: str, terms_sha256: str, accepted: bool, ip_address: str | None, user_agent: str | None,
    success_url: str, today: date | None = None, offer_token: str | None = None,
    attribution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    today = today or billing_today()
    if method not in (METHOD_CARD, METHOD_BANK):
        raise BillingError("method_invalid", "Choose card or bank transfer")
    sale_offer = (await find_offer(db, organization.id, offer_token, product_code, lock=True)
                  if product_code in ADMIN_PRODUCTS else None)
    offer = await quote(db, organization, product_code, today=today, offer_token=offer_token)
    if offer["blocker"]:
        raise BillingConflictError(offer["blocker"], _BLOCKER_MESSAGES.get(offer["blocker"], "This cannot be bought now"))
    customer = await get_customer(db, organization.id)
    if customer is None:
        raise BillingError("customer_required", "Enter the company details first")
    if not accepted:
        raise BillingError("terms_not_accepted", "Accept the Pilot Terms to continue")
    if not offer["methods"]["card" if method == METHOD_CARD else "bank_transfer"]:
        raise BillingUnavailableError("method_unavailable", "This payment method is not available yet")
    acceptance = await accept_terms(db, organization=organization, user=user, version=terms_version,
                                    sha256=terms_sha256, ip_address=ip_address, user_agent=user_agent)
    product = PRODUCTS[product_code]
    order = BillingOrder(
        organization_id=organization.id, product=product.code, plan=product.plan, method=method,
        status="pending" if method == METHOD_CARD else "awaiting_payment", currency="USD",
        list_amount_cents=product.amount_cents, credit_cents=offer["credit_cents"], amount_cents=offer["amount_cents"],
        terms_acceptance_id=acceptance.id, created_by_user_id=user.id, attribution=clean_attribution(attribution),
    )
    db.add(order)
    await db.flush()
    if sale_offer is not None:
        sale_offer.order_id = order.id  # used: the link works once
    await _audit(db, organization, ACTION_BILLING_ORDER_CREATED, actor_user=user, actor_label=None,
                 resource_type="BILLING_ORDER", resource_id=order.id,
                 new_state={"product": order.product, "method": method, "status": order.status,
                            "list_amount_cents": order.list_amount_cents, "credit_cents": order.credit_cents,
                            "amount_cents": order.amount_cents, "attribution": order.attribution},
                 reason=f"Checkout: {product.code} by {method}.")
    if method == METHOD_CARD:
        return await _card_checkout(db, organization=organization, customer=customer, order=order, success_url=success_url)
    invoice = await _bank_transfer(db, organization=organization, customer=customer, order=order, today=today)
    return {"order_id": order.id, "method": method, "status": order.status, "invoice_id": invoice.id,
            "invoice_number": invoice.number, "checkout_url": None}


_BLOCKER_MESSAGES = {
    "unknown_product": "This product is not sold in the app",
    "organization_disabled": "This organization is disabled",
    "awaiting_payment": "An invoice for this is waiting for payment",
    "already_paid_plan": "Your organization is already on a paid plan",
    "pilot_used": "Your organization has already had a pilot",
    "already_higher_plan": "Your organization is on a larger plan: talk to us",
    "already_on_plan": "Your organization is already on Pursuit Desk",
    "plan_required": "Extra pursuits are for a pilot or a paid plan: start a pilot first",
    "offer_required": "This is sold through a link from our team: ask us for one",
    "per_tender_on_plan": "Your organization is on a plan: add an extra pursuit instead",
}


async def admin_invoice(
    db: AsyncSession, *, organization: Organization, product_code: str, actor_user: User, signed_note: str,
    today: date | None = None,
) -> dict[str, Any]:
    """An admin-sold product by bank transfer: the signed order form recorded as the terms acceptance, then the
    usual invoice, activation and e-mails."""
    today = today or billing_today()
    if product_code not in ADMIN_PRODUCTS:
        raise BillingError("unknown_product", "Admin invoices are for admin-sold products")
    if len(_clean(signed_note, 1000)) < 3:
        raise BillingError("note_required", "Describe the signed order form (date, signatory)")
    blocker = await checkout_blocker(db, organization, product_code, offer=BillingOffer())
    if blocker:
        raise BillingConflictError(blocker, _BLOCKER_MESSAGES.get(blocker, "This cannot be invoiced now"))
    customer = await get_customer(db, organization.id)
    if customer is None:
        raise BillingError("customer_required", "Enter the company details first")
    currency = "UZS" if customer.resident else "USD"
    if not bank_transfer_available(currency):
        raise BillingUnavailableError("method_unavailable", f"Bank transfer in {currency} is not available yet")
    current = terms()
    acceptance = await accept_terms(db, organization=organization, user=actor_user, version=current["version"],
                                    sha256=current["sha256"], ip_address=None, user_agent=None, signed_note=signed_note)
    product = PRODUCTS[product_code]
    order = BillingOrder(
        organization_id=organization.id, product=product.code, plan=product.plan, method=METHOD_BANK,
        status="awaiting_payment", currency="USD", list_amount_cents=product.amount_cents, credit_cents=0,
        amount_cents=product.amount_cents, terms_acceptance_id=acceptance.id, created_by_user_id=actor_user.id,
    )
    db.add(order)
    await db.flush()
    await _audit(db, organization, ACTION_BILLING_ORDER_CREATED, actor_user=actor_user, actor_label=None,
                 resource_type="BILLING_ORDER", resource_id=order.id,
                 new_state={"product": order.product, "method": METHOD_BANK, "status": order.status,
                            "amount_cents": order.amount_cents}, reason=f"Admin invoice: {product.code}.")
    invoice = await _bank_transfer(db, organization=organization, customer=customer, order=order, today=today)
    return {"order_id": order.id, "invoice_id": invoice.id, "invoice_number": invoice.number}


async def _card_checkout(
    db: AsyncSession, *, organization: Organization, customer: BillingCustomer, order: BillingOrder, success_url: str,
) -> dict[str, Any]:
    client = billing_polar.polar_client()
    product_id = billing_polar.product_ids()[order.product]
    metadata = {"organization_id": str(organization.id), "order_id": str(order.id), "product": order.product}
    try:
        if order.credit_cents:
            order.provider_discount_id = await client.create_discount(
                product_id=product_id, amount_cents=order.credit_cents,
                name=f"Pilot credit {_display(organization)}"[:100], metadata=metadata,
            )
        checkout = await client.create_checkout(
            product_id=product_id, success_url=success_url, metadata=metadata,
            customer_email=customer.billing_email, external_customer_id=str(organization.id),
            customer_name=customer.legal_name, country=customer.country,
            discount_id=order.provider_discount_id,
        )
    except billing_polar.PolarError as exc:
        raise BillingUnavailableError("card_unavailable", "Card payment is not available right now: try bank transfer or later") from exc
    order.provider_checkout_id = checkout["id"]
    order.provider_checkout_url = checkout["url"]
    await db.flush()
    return {"order_id": order.id, "method": METHOD_CARD, "status": order.status, "invoice_id": None,
            "invoice_number": None, "checkout_url": checkout["url"]}


async def next_invoice_number(db: AsyncSession, year: int) -> str:
    """PL-YYYY-NNN, gapless: the counter row stays locked until the issuing transaction ends."""
    number = await db.scalar(text(
        "INSERT INTO billing_invoice_counters (year, last_number) VALUES (:year, 1) "
        "ON CONFLICT (year) DO UPDATE SET last_number = billing_invoice_counters.last_number + 1 "
        "RETURNING last_number"
    ), {"year": year})
    return f"PL-{year}-{int(number):03d}"


async def _bank_transfer(
    db: AsyncSession, *, organization: Organization, customer: BillingCustomer, order: BillingOrder, today: date,
) -> BillingInvoice:
    if order.credit_cents:
        await _redeem_credit(db, organization=organization, order=order, actor_user=None, actor_label=ACTOR_CHECKOUT)
    await activate_order(db, order=order, organization=organization, billing_status="awaiting_payment",
                         today=today, actor_label=ACTOR_CHECKOUT)
    invoice = await issue_invoice(db, organization=organization, customer=customer, order=order, today=today)
    await _email(db, order, "BILLING_INVOICE", f"invoice:{invoice.id}", _invoice_payload(invoice, order))
    return invoice


async def issue_invoice(
    db: AsyncSession, *, organization: Organization, customer: BillingCustomer, order: BillingOrder, today: date,
) -> BillingInvoice:
    currency = "UZS" if customer.resident else "USD"
    rate = total_uzs = rate_date = None
    if currency == "UZS":
        try:
            rate = await usd_rate(db, today)
        except FxUnavailableError as exc:
            raise BillingUnavailableError("fx_unavailable", "Today's Central Bank rate is not available yet: try again shortly") from exc
        rate_date = today
        total_uzs = (Decimal(order.amount_cents) / 100 * rate).quantize(Decimal("0.01"))
    invoice = BillingInvoice(
        number=await next_invoice_number(db, today.year), organization_id=organization.id, order_id=order.id,
        customer={"legal_name": customer.legal_name, "tin": customer.tin, "country": customer.country,
                  "address": customer.address, "billing_email": customer.billing_email, "resident": customer.resident},
        currency=currency, list_amount_cents=order.list_amount_cents, credit_cents=order.credit_cents,
        total_usd_cents=order.amount_cents, fx_rate=rate, fx_rate_date=rate_date, total_uzs=total_uzs,
        issued_on=today, due_on=today + timedelta(days=BANK_TRANSFER_DUE_DAYS), status="issued",
    )
    db.add(invoice)
    await db.flush()
    await _audit(db, organization, ACTION_BILLING_INVOICE_ISSUED, actor_user=None, actor_label=ACTOR_CHECKOUT,
                 resource_type="BILLING_INVOICE", resource_id=invoice.id,
                 new_state={"number": invoice.number, "currency": currency, "total_usd_cents": invoice.total_usd_cents,
                            "total_uzs": str(total_uzs) if total_uzs is not None else None,
                            "fx_rate": str(rate) if rate is not None else None, "due_on": invoice.due_on.isoformat()},
                 reason=f"Invoice {invoice.number} issued.")
    return invoice


def _invoice_payload(invoice: BillingInvoice, order: BillingOrder) -> dict[str, Any]:
    return {
        "invoice_id": str(invoice.id), "number": invoice.number, "product": order.product,
        "currency": invoice.currency, "total_usd": f"{invoice.total_usd_cents / 100:,.2f}",
        "total_uzs": f"{invoice.total_uzs:,.2f}".replace(",", " ") if invoice.total_uzs is not None else None,
        "due_on": invoice.due_on.isoformat(), "pilot": order.product == PRODUCT_PILOT,
        "explore_on": (invoice.issued_on + timedelta(days=BANK_TRANSFER_SUSPEND_DAY)).isoformat(),
    }


async def _redeem_credit(
    db: AsyncSession, *, organization: Organization, order: BillingOrder, actor_user: User | None, actor_label: str,
) -> bool:
    """Record the pilot credit on ``order``; False when it was already used (the order keeps its figures).
    The window is judged on the date the order was placed, not the date the payment arrives."""
    source = await pilot_credit_source(db, organization.id, on=_local_date(order.created_at))
    if source is None:
        return False
    inserted = await db.scalar(
        pg_insert(PilotCreditRedemption).values(
            organization_id=organization.id, pilot_order_id=source.id, order_id=order.id, amount_cents=order.credit_cents,
        ).on_conflict_do_nothing().returning(PilotCreditRedemption.id)
    )
    if inserted is None:
        return False
    await _audit(db, organization, ACTION_BILLING_CREDIT_APPLIED, actor_user=actor_user, actor_label=actor_label,
                 resource_type="BILLING_ORDER", resource_id=order.id,
                 new_state={"credit_cents": order.credit_cents, "pilot_order_id": str(source.id)},
                 reason="Paid pilot credited to the first annual order.")
    return True


# ---- activation --------------------------------------------------------------------------------

async def _set_plan(
    db: AsyncSession, *, organization: Organization, plan: str, start: date | None, end: date | None,
    actor_user: User | None, actor_label: str, reason: str, reset_overrides: bool = True,
) -> None:
    """Through the P1/P3 access writer (audited). A bought plan starts without admin overrides."""
    from app.services.organization_access import set_organization_access

    state = "disabled" if organization.access_state == "disabled" else ACCESS_STATE_FOR_PLAN[plan]
    overrides = {"pursuit_limit_override": None, "introduction_limit_override": None} if reset_overrides else {}
    await set_organization_access(
        db, organization=organization, state=state, plan=plan, plan_started_on=start, plan_ends_on=end,
        actor_user=actor_user, actor_label=actor_label, reason=reason, source=SOURCE_BILLING,
        actor_type=ACTOR_SYSTEM, **overrides,
    )


async def activate_order(
    db: AsyncSession, *, order: BillingOrder, organization: Organization, billing_status: str, today: date,
    actor_label: str,
) -> None:
    """Give the organization what it bought (once per order) and start onboarding."""
    if order.activated_at is not None:
        return
    product = PRODUCTS[order.product]
    if product.code == PRODUCT_PER_TENDER:
        from app.services.organization_access import set_organization_access

        again = organization.plan == PLAN_PER_TENDER
        purchases = (organization.pursuit_limit_override or 0) + 1 if again else 1
        start = organization.plan_started_on if again and organization.plan_started_on else today
        await set_organization_access(
            db, organization=organization, state="disabled" if organization.access_state == "disabled" else "paid",
            plan=PLAN_PER_TENDER, plan_started_on=start, plan_ends_on=None, pursuit_limit_override=purchases,
            actor_user=None, actor_label=actor_label, reason=f"Per-tender review bought ({order.method}).",
            source=SOURCE_BILLING, actor_type=ACTOR_SYSTEM,
        )
        organization.billing_status = billing_status
        order.plan_started_on, order.plan_ends_on = start, None
        await db.execute(
            pg_insert(OnboardingTask).values(organization_id=organization.id, order_id=order.id, status="open")
            .on_conflict_do_nothing(index_elements=["order_id"])
        )
        await _email(db, order, "BILLING_WELCOME", f"welcome:{order.id}", {
            "plan": PLAN_PER_TENDER, "starts_on": today.isoformat(), "ends_on": None, "kickoff_url": kickoff_url(),
            "awaiting_payment": billing_status == "awaiting_payment", "terms_version": TERMS_VERSION,
        })
    elif product.plan is not None:
        start, end = today, add_months(today, product.term_months or 12)
        await _set_plan(db, organization=organization, plan=product.plan, start=start, end=end, actor_user=None,
                        actor_label=actor_label, reason=f"{product.code} bought ({order.method}).")
        organization.billing_status = billing_status
        order.plan_started_on, order.plan_ends_on = start, end
        await db.execute(
            pg_insert(OnboardingTask).values(organization_id=organization.id, order_id=order.id, status="open")
            .on_conflict_do_nothing(index_elements=["order_id"])
        )
        await _email(db, order, "BILLING_WELCOME", f"welcome:{order.id}", {
            "plan": product.plan, "starts_on": start.isoformat(), "ends_on": end.isoformat(),
            "kickoff_url": kickoff_url(), "awaiting_payment": billing_status == "awaiting_payment",
            "terms_version": TERMS_VERSION,
        })
    else:
        from app.services.plans import GRANT_PURSUITS, add_grant

        await add_grant(db, organization=organization, kind=GRANT_PURSUITS, quantity=product.extra_pursuits,
                        reason=f"Extra pursuit bought (order {str(order.id)[:8]})", actor_user=None,
                        actor_label=actor_label, source=SOURCE_BILLING, today=today)
    order.activated_at = _now()
    await db.flush()
    await _audit(db, organization, ACTION_BILLING_PLAN_ACTIVATED, actor_user=None, actor_label=actor_label,
                 resource_type="BILLING_ORDER", resource_id=order.id,
                 new_state={"product": order.product, "plan": organization.plan, "billing_status": organization.billing_status,
                            "plan_started_on": order.plan_started_on.isoformat() if order.plan_started_on else None,
                            "plan_ends_on": order.plan_ends_on.isoformat() if order.plan_ends_on else None},
                 reason=f"{order.product} activated.")
    await _alert(db, organization, "activated", order)


async def current_plan_order(db: AsyncSession, organization_id: UUID) -> BillingOrder | None:
    """The plan order the organization's current plan came from (the latest activated one)."""
    return await db.scalar(
        select(BillingOrder).where(
            BillingOrder.organization_id == organization_id, BillingOrder.plan.is_not(None),
            BillingOrder.activated_at.is_not(None),
        ).order_by(BillingOrder.activated_at.desc(), BillingOrder.created_at.desc()).limit(1)
    )


async def _is_current(db: AsyncSession, organization: Organization, order: BillingOrder) -> bool:
    if order.plan is None or organization.plan != order.plan:
        return False
    current = await current_plan_order(db, organization.id)
    return current is not None and (current.id == order.id or current.renewal_of_order_id == order.id
                                    or order.renewal_of_order_id == current.id)


async def _record_payment(
    db: AsyncSession, *, organization: Organization, order: BillingOrder, invoice: BillingInvoice | None,
    method: str, amount_cents: int, currency: str, provider_payment_id: str | None, reference: str | None,
    actor_user: User | None, actor_label: str, note: str | None = None, paid_at: datetime | None = None,
) -> BillingPayment:
    payment = BillingPayment(
        organization_id=organization.id, order_id=order.id, invoice_id=invoice.id if invoice else None,
        method=method, provider_payment_id=provider_payment_id, reference=reference, amount_cents=amount_cents,
        currency=currency, status="paid", paid_at=paid_at or _now(),
        recorded_by_user_id=actor_user.id if actor_user is not None else None, note=note,
    )
    db.add(payment)
    await db.flush()
    await _audit(db, organization, ACTION_BILLING_PAYMENT_RECORDED, actor_user=actor_user, actor_label=actor_label,
                 resource_type="BILLING_PAYMENT", resource_id=payment.id,
                 new_state={"order_id": str(order.id), "method": method, "amount_cents": amount_cents,
                            "currency": currency, "reference": reference, "provider_payment_id": provider_payment_id},
                 reason=note or "Payment recorded.")
    return payment


# ---- Polar webhooks ----------------------------------------------------------------------------

def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


async def _order_from(db: AsyncSession, data: dict[str, Any]) -> BillingOrder | None:
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    order_id, organization_id = _uuid(metadata.get("order_id")), _uuid(metadata.get("organization_id"))
    if order_id is not None:
        order = await db.get(BillingOrder, order_id, with_for_update=True)
        if order is not None and (organization_id is None or order.organization_id == organization_id):
            return order
        return None
    if data.get("checkout_id"):
        return await db.scalar(select(BillingOrder).where(
            BillingOrder.provider_checkout_id == str(data["checkout_id"])).with_for_update())
    return None


async def _subscription_order(db: AsyncSession, subscription_id: Any) -> BillingOrder | None:
    if not subscription_id:
        return None
    return await db.scalar(
        select(BillingOrder).where(BillingOrder.provider_subscription_id == str(subscription_id),
                                   BillingOrder.renewal_of_order_id.is_(None))
        .order_by(BillingOrder.created_at).limit(1).with_for_update()
    )


async def _on_order_paid(
    db: AsyncSession, data: dict[str, Any], today: date, *, actor_label: str = ACTOR_WEBHOOK,
    note: str = "Polar order.paid",
) -> tuple[str, UUID | None]:
    """The order.paid webhook; reconciliation runs the same path with its own actor and note."""
    polar_order_id = str(data.get("id") or "")
    if not polar_order_id:
        return "invalid_payload", None
    known = await db.scalar(select(BillingPayment).where(BillingPayment.provider_payment_id == polar_order_id))
    if known is not None:
        return "duplicate_payment", known.organization_id
    amount = int(data.get("total_amount") or data.get("net_amount") or data.get("amount") or 0)
    currency = str(data.get("currency") or "usd").upper()[:3]
    order = await _order_from(db, data)
    if order is None or (order.status == "paid" and data.get("subscription_id")):
        # A renewal: a new Polar order on the subscription (it carries the first checkout's metadata).
        base = await _subscription_order(db, data.get("subscription_id")) or order
        if base is None or not data.get("subscription_id"):
            return "unmatched_order", None
        return await _renew(db, base, data, polar_order_id, amount, currency, today)
    organization = await db.get(Organization, order.organization_id, with_for_update=True)
    if order.status in ("refunded", "canceled"):
        await _alert(db, organization, "paid_after_close", order, polar_order_id=polar_order_id)
        return "paid_after_close", organization.id
    await _record_payment(db, organization=organization, order=order, invoice=None, method=METHOD_CARD,
                          amount_cents=amount, currency=currency, provider_payment_id=polar_order_id, reference=None,
                          actor_user=None, actor_label=actor_label, note=note)
    order.status, order.paid_at = "paid", _now()
    if data.get("subscription_id"):
        order.provider_subscription_id = str(data["subscription_id"])
    if order.credit_cents and not await _redeem_credit(db, organization=organization, order=order, actor_user=None,
                                                       actor_label=actor_label):
        await _alert(db, organization, "credit_already_used", order)
    if order.activated_at is None:
        await activate_order(db, order=order, organization=organization, billing_status="paid", today=today,
                             actor_label=actor_label)
    elif await _is_current(db, organization, order):
        organization.billing_status = "paid"
    await db.flush()
    return "activated", organization.id


async def _renew(
    db: AsyncSession, base: BillingOrder, data: dict[str, Any], polar_order_id: str, amount: int, currency: str,
    today: date,
) -> tuple[str, UUID | None]:
    """A subscription renewal order: record it and extend the plan by a year."""
    organization = await db.get(Organization, base.organization_id, with_for_update=True)
    previous_end = organization.plan_ends_on or base.plan_ends_on or today
    renewal = BillingOrder(
        organization_id=organization.id, product=base.product, plan=base.plan, method=METHOD_CARD, status="paid",
        currency="USD", list_amount_cents=amount, credit_cents=0, amount_cents=amount, paid_at=_now(),
        provider_subscription_id=base.provider_subscription_id, renewal_of_order_id=base.id, activated_at=_now(),
        plan_started_on=previous_end, plan_ends_on=add_months(previous_end, 12),
    )
    db.add(renewal)
    await db.flush()
    await _record_payment(db, organization=organization, order=renewal, invoice=None, method=METHOD_CARD,
                          amount_cents=amount, currency=currency, provider_payment_id=polar_order_id, reference=None,
                          actor_user=None, actor_label=ACTOR_WEBHOOK, note="Polar subscription renewal")
    if organization.plan == base.plan:
        await _set_plan(db, organization=organization, plan=base.plan, start=organization.plan_started_on,
                        end=renewal.plan_ends_on, actor_user=None, actor_label=ACTOR_WEBHOOK,
                        reason="Annual plan renewed.", reset_overrides=False)
        organization.billing_status = "paid"
    await _alert(db, organization, "renewed", renewal)
    return "renewed", organization.id


async def refund_order(
    db: AsyncSession, *, order: BillingOrder, note: str, actor_user: User | None, actor_label: str,
    downgrade: bool = True,
) -> None:
    """The order is refunded; when it is the current plan's order, the organization returns to Explore."""
    organization = await db.get(Organization, order.organization_id, with_for_update=True)
    before = {"status": order.status, "plan": organization.plan, "billing_status": organization.billing_status}
    current = await _is_current(db, organization, order)
    order.status, order.refunded_at = "refunded", _now()
    order.refund_note = _clean(note, 1000) or None
    await db.execute(PilotCreditRedemption.__table__.delete().where(PilotCreditRedemption.order_id == order.id))
    if downgrade and current:
        await _set_plan(db, organization=organization, plan=PLAN_EXPLORE, start=None, end=None, actor_user=actor_user,
                        actor_label=actor_label, reason=f"Refund of {order.product}.")
        organization.billing_status = "refunded"
    await db.flush()
    await _audit(db, organization, ACTION_BILLING_REFUND_RECORDED, actor_user=actor_user, actor_label=actor_label,
                 resource_type="BILLING_ORDER", resource_id=order.id, previous_state=before,
                 new_state={"status": "refunded", "plan": organization.plan, "billing_status": organization.billing_status},
                 reason=order.refund_note or "Refunded.")
    await _alert(db, organization, "refunded", order)


async def _on_order_refunded(db: AsyncSession, data: dict[str, Any]) -> tuple[str, UUID | None]:
    payment = await db.scalar(select(BillingPayment).where(
        BillingPayment.provider_payment_id == str(data.get("id") or "")).with_for_update())
    if payment is None:
        return "unmatched_order", None
    if payment.status == "refunded":
        return "duplicate_refund", payment.organization_id
    total = int(data.get("total_amount") or payment.amount_cents or 0)
    refunded = int(data.get("refunded_amount") or 0)
    full = data.get("status") == "refunded" or (total > 0 and refunded >= total)
    payment.refunded_amount_cents = refunded if refunded else (total if full else 0)
    payment.status = "refunded" if full else "partially_refunded"
    order = await db.get(BillingOrder, payment.order_id, with_for_update=True)
    if not full:
        organization = await db.get(Organization, order.organization_id)
        await _alert(db, organization, "partially_refunded", order, refunded_amount_cents=refunded)
        return "partially_refunded", payment.organization_id
    await refund_order(db, order=order, note="Refunded in Polar", actor_user=None, actor_label=ACTOR_WEBHOOK)
    return "refunded", payment.organization_id


async def _on_subscription(db: AsyncSession, event_type: str, data: dict[str, Any]) -> tuple[str, UUID | None]:
    order = await _order_from(db, data) if isinstance(data.get("metadata"), dict) and data["metadata"].get("order_id") else None
    order = order or await _subscription_order(db, data.get("id"))
    if order is None:
        return "unmatched_subscription", None
    if data.get("id") and not order.provider_subscription_id:
        order.provider_subscription_id = str(data["id"])
    organization = await db.get(Organization, order.organization_id, with_for_update=True)
    current = await _is_current(db, organization, order)
    before = organization.billing_status
    if event_type == "subscription.revoked":
        if current:
            await _set_plan(db, organization=organization, plan=PLAN_EXPLORE, start=None, end=None, actor_user=None,
                            actor_label=ACTOR_WEBHOOK, reason="Annual subscription ended.")
            organization.billing_status = "canceled"
        outcome = "subscription_revoked"
    elif event_type == "subscription.canceled":
        # Canceled at the period end: the plan stays until Polar revokes the subscription.
        if current:
            organization.billing_status = "canceled"
        outcome = "subscription_canceled"
    elif event_type in ("subscription.active", "subscription.uncanceled"):
        if current and order.status == "paid":
            organization.billing_status = "paid"
        outcome = "subscription_active"
    else:
        outcome = f"subscription_{str(data.get('status') or 'updated')[:40]}"
    if organization.billing_status != before:
        await _audit(db, organization, ACTION_BILLING_STATUS_CHANGED, actor_user=None, actor_label=ACTOR_WEBHOOK,
                     resource_type="BILLING_ORDER", resource_id=order.id, previous_state={"billing_status": before},
                     new_state={"billing_status": organization.billing_status, "plan": organization.plan},
                     reason=f"Polar {event_type}.")
        await _alert(db, organization, event_type.replace(".", "_"), order)
    await db.flush()
    return outcome, organization.id


RECONCILE_HIGHER_PLANS = ("agent", "enterprise")


async def reconcile_paid_card_order(
    db: AsyncSession, *, order_id: UUID, polar_order: dict[str, Any], today: date | None = None, apply: bool,
) -> dict[str, Any]:
    """Deploy 5.1 (scripts/billing/reconcile_polar.py): a card order Polar shows as **paid** (the caller checked
    ``polar_order`` belongs to this order) that never got its ``order.paid`` webhook.

    - ``activate``: the organization is not on the bought plan → the order.paid path (payment, credit, plan,
      onboarding task, welcome e-mail, team alert), actor ``reconcile``;
    - ``link_only``: the organization is already on the bought plan (an admin activated it by hand) → the Polar
      order and subscription ids are linked and the order marked paid; the plan, its dates and the billing status
      stay as the admin set them (the order takes the organization's dates, so later subscription events apply);
    - ``already_paid``, ``already_linked``, ``not_pending``, ``needs_review`` (a larger plan) → nothing.
    Without ``apply`` only the decision is returned. The caller commits."""
    today = today or billing_today()
    order = await db.get(BillingOrder, order_id, with_for_update=apply)
    polar_order_id = str(polar_order.get("id") or "")
    if order is None or order.method != METHOD_CARD or not polar_order_id:
        return {"action": "not_found"}
    if order.status == "paid":
        return {"action": "already_paid"}
    if order.status != "pending":
        return {"action": "not_pending"}
    if await db.scalar(select(BillingPayment.id).where(BillingPayment.provider_payment_id == polar_order_id)):
        return {"action": "already_linked"}
    organization = await db.get(Organization, order.organization_id, with_for_update=apply)
    if order.plan is not None and organization.plan == order.plan:
        action = "link_only"
    elif order.plan is not None and organization.plan in RECONCILE_HIGHER_PLANS:
        action = "needs_review"  # activating would move a larger plan down to the one bought
    else:
        action = "activate"
    if not apply or action == "needs_review":
        return {"action": action}
    note = "Polar order.paid (reconciled: the webhook never delivered it)"
    if action == "activate":
        data = {**polar_order, "metadata": {**(polar_order.get("metadata") or {}), "order_id": str(order.id),
                                            "organization_id": str(order.organization_id)}}
        outcome, _ = await _on_order_paid(db, data, today, actor_label=ACTOR_RECONCILE, note=note)
        return {"action": action, "outcome": outcome}
    before = {"status": order.status, "provider_subscription_id": order.provider_subscription_id}
    await _record_payment(
        db, organization=organization, order=order, invoice=None, method=METHOD_CARD,
        amount_cents=int(polar_order.get("total_amount") or 0), currency=str(polar_order.get("currency") or "usd").upper()[:3],
        provider_payment_id=polar_order_id, reference=None, actor_user=None, actor_label=ACTOR_RECONCILE, note=note,
    )
    order.status, order.paid_at = "paid", _now()
    if polar_order.get("subscription_id"):
        order.provider_subscription_id = str(polar_order["subscription_id"])
    if order.credit_cents:
        await _redeem_credit(db, organization=organization, order=order, actor_user=None, actor_label=ACTOR_RECONCILE)
    order.activated_at = _now()
    order.plan_started_on, order.plan_ends_on = organization.plan_started_on, organization.plan_ends_on
    await db.flush()
    await _audit(db, organization, ACTION_BILLING_STATUS_CHANGED, actor_user=None, actor_label=ACTOR_RECONCILE,
                 resource_type="BILLING_ORDER", resource_id=order.id, previous_state=before,
                 new_state={"status": "paid", "provider_order_id": polar_order_id,
                            "provider_subscription_id": order.provider_subscription_id,
                            "plan": organization.plan, "billing_status": organization.billing_status,
                            "activation": "kept_manual"},
                 reason="Reconciled with Polar: paid; the plan was already activated by hand, ids linked only.")
    return {"action": action, "outcome": "linked"}


async def process_polar_event(
    db: AsyncSession, event_type: str, data: dict[str, Any], *, today: date | None = None,
) -> tuple[str, UUID | None]:
    today = today or billing_today()
    if event_type == "order.paid":
        return await _on_order_paid(db, data, today)
    if event_type == "order.refunded":
        return await _on_order_refunded(db, data)
    if event_type.startswith("subscription."):
        return await _on_subscription(db, event_type, data)
    return "ignored", None


async def receive_polar_webhook(
    db: AsyncSession, *, body: bytes, headers: dict[str, str], today: date | None = None, now: float | None = None,
) -> dict[str, Any]:
    """Verify, store once, process once. Raises WebhookSignatureError (refuse, store nothing)."""
    event_id = billing_polar.verify_webhook(body, headers, now=now)
    try:
        event = json.loads(body)
    except ValueError as exc:
        raise billing_polar.WebhookSignatureError("webhook_body_invalid") from exc
    if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
        raise billing_polar.WebhookSignatureError("webhook_body_invalid")
    event_type = str(event.get("type") or "")[:80]
    await db.execute(
        pg_insert(BillingEvent).values(
            provider="polar", provider_event_id=event_id, event_type=event_type, signature_verified=True,
            payload=event, attempts=0,
        ).on_conflict_do_nothing(constraint="uq_billing_event_provider_id")
    )
    row = await db.scalar(select(BillingEvent).where(
        BillingEvent.provider == "polar", BillingEvent.provider_event_id == event_id).with_for_update())
    if row.processed_at is not None:
        return {"status": "duplicate", "event_id": event_id, "outcome": row.outcome}
    row.attempts += 1
    outcome, organization_id = await process_polar_event(db, event_type, event["data"], today=today)
    row.outcome, row.organization_id = outcome, organization_id
    row.processing_error, row.processed_at = None, _now()
    await db.flush()
    return {"status": "processed", "event_id": event_id, "outcome": outcome}


async def record_webhook_failure(db: AsyncSession, *, body: bytes, event_id: str, error: str) -> None:
    """After a processing error rolled back: keep the delivery (unprocessed) with the error code."""
    try:
        event = json.loads(body)
    except ValueError:
        return
    if not isinstance(event, dict):
        return
    await db.execute(
        pg_insert(BillingEvent).values(
            provider="polar", provider_event_id=event_id, event_type=str(event.get("type") or "")[:80],
            signature_verified=True, payload=event, attempts=1, processing_error=error[:200],
        ).on_conflict_do_update(
            constraint="uq_billing_event_provider_id",
            set_={"attempts": BillingEvent.attempts + 1, "processing_error": error[:200]},
        )
    )


# ---- bank transfer schedule --------------------------------------------------------------------

async def run_billing_schedule(db: AsyncSession, *, today: date | None = None) -> dict[str, int]:
    """Plan endings and bank-transfer renewals (terms §7), then reminders on days 3 and 6 of an unpaid invoice and
    Explore on day 10 (§4). Idempotent; the caller commits."""
    today = today or billing_today()
    counts = {"reminders": 0, "suspended": 0, "ended": 0, "renewed": 0}
    await _end_and_renew(db, today=today, counts=counts)
    invoices = list((await db.scalars(
        select(BillingInvoice).where(BillingInvoice.status == "issued").order_by(BillingInvoice.issued_on)
        .with_for_update(skip_locked=True)
    )).all())
    for invoice in invoices:
        order = await db.get(BillingOrder, invoice.order_id, with_for_update=True)
        if order is None or order.status != "awaiting_payment":
            continue
        age = (today - invoice.issued_on).days
        if age >= BANK_TRANSFER_SUSPEND_DAY:
            await _lapse(db, invoice=invoice, order=order)
            counts["suspended"] += 1
            continue
        due = [day for day in BANK_TRANSFER_REMINDER_DAYS if age >= day]
        if due and invoice.reminders_sent < due[-1]:
            await _email(db, order, "BILLING_REMINDER", f"reminder:{invoice.id}:{due[-1]}", {
                **_invoice_payload(invoice, order), "day": due[-1],
                "days_left": max(0, (invoice.due_on - today).days),
            })
            invoice.reminders_sent = due[-1]
            counts["reminders"] += 1
    await db.flush()
    return counts


async def _end_and_renew(db: AsyncSession, *, today: date, counts: dict[str, int]) -> None:
    """Bought plans whose term is over. ``plan_ends_on`` is the first day after the term (= the renewal date).

    - Pilot (terms §7: does not renew) → Explore.
    - Pursuit Desk by card: Polar's subscription renews it (``order.paid``) or ends it (``subscription.revoked``).
    - Pursuit Desk by bank transfer: canceled → Explore; otherwise a renewal order and invoice for the next year
      (§4's 7/10-day rules then apply to that invoice).
    A Pursuit Desk an admin set without an order is left to the admin; every Pilot ends on its end date."""
    organizations = list((await db.scalars(
        select(Organization).where(
            Organization.plan.in_((PLAN_PILOT, PLAN_PURSUIT_DESK)), Organization.plan_ends_on.is_not(None),
            Organization.plan_ends_on <= today, Organization.access_state != "disabled",
        ).with_for_update(skip_locked=True)
    )).all())
    for organization in organizations:
        order = await current_plan_order(db, organization.id)
        bought = order is not None and order.plan == organization.plan and order.status in ("paid", "awaiting_payment")
        if organization.plan == PLAN_PILOT:
            # Every pilot ends on its end date: bought, set up by scripts/pilot_setup.py, or set by an admin
            # (an admin moves the end date to extend one).
            await _end_plan(db, organization=organization, order=order if bought else None, status=None,
                            reason="Pilot ended after three months.")
            counts["ended"] += 1
        elif not bought:
            continue
        elif order.method == METHOD_BANK:
            if organization.billing_status == "canceled":
                await _end_plan(db, organization=organization, order=order, status="canceled",
                                reason="Pursuit Desk canceled before its renewal date.")
                counts["ended"] += 1
            elif organization.billing_status == "paid" and await _renew_by_invoice(db, organization, order, today):
                counts["renewed"] += 1


async def _end_plan(
    db: AsyncSession, *, organization: Organization, order: BillingOrder | None, status: str | None, reason: str,
) -> None:
    before = {"plan": organization.plan, "billing_status": organization.billing_status,
              "plan_ends_on": organization.plan_ends_on.isoformat() if organization.plan_ends_on else None}
    await _set_plan(db, organization=organization, plan=PLAN_EXPLORE, start=None, end=None, actor_user=None,
                    actor_label=ACTOR_SCHEDULE, reason=reason)
    organization.billing_status = status
    await db.flush()
    await _audit(db, organization, ACTION_BILLING_STATUS_CHANGED, actor_user=None, actor_label=ACTOR_SCHEDULE,
                 resource_type="BILLING_ORDER" if order is not None else "ORGANIZATION",
                 resource_id=order.id if order is not None else organization.id, previous_state=before,
                 new_state={"plan": organization.plan, "billing_status": status}, reason=reason)
    await _alert(db, organization, "plan_ended", order, ended_plan=before["plan"], ended_on=before["plan_ends_on"])


async def _renew_by_invoice(db: AsyncSession, organization: Organization, order: BillingOrder, today: date) -> bool:
    """Next Pursuit Desk year for a bank-transfer customer: a renewal order, active at once, and its invoice."""
    base = order if order.renewal_of_order_id is None else await db.get(BillingOrder, order.renewal_of_order_id)
    start = organization.plan_ends_on
    exists = await db.scalar(select(BillingOrder.id).where(
        BillingOrder.renewal_of_order_id == base.id, BillingOrder.plan_started_on == start))
    customer = await get_customer(db, organization.id)
    if exists is not None or customer is None:
        return False
    if customer.resident:
        try:
            await usd_rate(db, today)  # no rate yet today: try again at the next run, before creating anything
        except FxUnavailableError:
            return False
    product = PRODUCTS[PRODUCT_PURSUIT_DESK]
    end = add_months(start, product.term_months or 12)
    renewal = BillingOrder(
        organization_id=organization.id, product=product.code, plan=product.plan, method=METHOD_BANK,
        status="awaiting_payment", currency="USD", list_amount_cents=product.amount_cents, credit_cents=0,
        amount_cents=product.amount_cents, terms_acceptance_id=base.terms_acceptance_id,
        created_by_user_id=base.created_by_user_id, renewal_of_order_id=base.id, activated_at=_now(),
        plan_started_on=start, plan_ends_on=end,
    )
    db.add(renewal)
    await db.flush()
    await _set_plan(db, organization=organization, plan=product.plan, start=organization.plan_started_on, end=end,
                    actor_user=None, actor_label=ACTOR_SCHEDULE, reason="Pursuit Desk renewed for another year.",
                    reset_overrides=False)
    organization.billing_status = "awaiting_payment"
    await _audit(db, organization, ACTION_BILLING_ORDER_CREATED, actor_user=None, actor_label=ACTOR_SCHEDULE,
                 resource_type="BILLING_ORDER", resource_id=renewal.id,
                 new_state={"product": renewal.product, "method": METHOD_BANK, "status": renewal.status,
                            "amount_cents": renewal.amount_cents, "renewal_of": str(base.id),
                            "plan_started_on": start.isoformat(), "plan_ends_on": end.isoformat()},
                 reason="Pursuit Desk renews yearly (terms §7).")
    invoice = await issue_invoice(db, organization=organization, customer=customer, order=renewal, today=today)
    await _email(db, renewal, "BILLING_INVOICE", f"invoice:{invoice.id}", _invoice_payload(invoice, renewal))
    await _alert(db, organization, "renewed", renewal, invoice_number=invoice.number)
    return True


async def _lapse(db: AsyncSession, *, invoice: BillingInvoice, order: BillingOrder) -> None:
    organization = await db.get(Organization, order.organization_id, with_for_update=True)
    before = {"plan": organization.plan, "billing_status": organization.billing_status, "order_status": order.status}
    current = await _is_current(db, organization, order)
    order.status, invoice.status = "lapsed", "overdue"
    if current:
        await _set_plan(db, organization=organization, plan=PLAN_EXPLORE, start=None, end=None, actor_user=None,
                        actor_label=ACTOR_SCHEDULE, reason=f"Invoice {invoice.number} unpaid on day {BANK_TRANSFER_SUSPEND_DAY}.")
        organization.billing_status = "suspended"
    await db.flush()
    await _audit(db, organization, ACTION_BILLING_PLAN_SUSPENDED, actor_user=None, actor_label=ACTOR_SCHEDULE,
                 resource_type="BILLING_INVOICE", resource_id=invoice.id, previous_state=before,
                 new_state={"plan": organization.plan, "billing_status": organization.billing_status, "order_status": "lapsed"},
                 reason=f"Invoice {invoice.number} unpaid on day {BANK_TRANSFER_SUSPEND_DAY}.")
    await _email(db, order, "BILLING_SUSPENDED", f"suspended:{invoice.id}", _invoice_payload(invoice, order))
    await _alert(db, organization, "suspended", order, invoice_number=invoice.number)


# ---- admin -------------------------------------------------------------------------------------

async def mark_invoice_paid(
    db: AsyncSession, *, invoice: BillingInvoice, reference: str, actor_user: User, note: str | None = None,
    today: date | None = None,
) -> BillingPayment:
    today = today or billing_today()
    reference = _clean(reference, 200)
    if len(reference) < 3:
        raise BillingError("reference_required", "Enter the bank reference of the payment")
    if invoice.status not in ("issued", "overdue"):
        raise BillingConflictError("invoice_not_open", "This invoice is not waiting for payment")
    order = await db.get(BillingOrder, invoice.order_id, with_for_update=True)
    organization = await db.get(Organization, order.organization_id, with_for_update=True)
    payment = await _record_payment(
        db, organization=organization, order=order, invoice=invoice, method=METHOD_BANK,
        amount_cents=invoice.total_usd_cents, currency="USD", provider_payment_id=None, reference=reference,
        actor_user=actor_user, actor_label="admin", note=_clean(note, 1000) or f"Bank transfer for {invoice.number}",
    )
    lapsed = order.status == "lapsed"
    invoice.status, invoice.paid_at = "paid", _now()
    order.status, order.paid_at = "paid", _now()
    if order.credit_cents:
        await _redeem_credit(db, organization=organization, order=order, actor_user=actor_user, actor_label="admin")
    if lapsed and order.plan is not None and organization.plan == PLAN_EXPLORE:
        # Paid after day 10: the plan comes back with the dates it was bought with.
        await _set_plan(db, organization=organization, plan=order.plan, start=order.plan_started_on,
                        end=order.plan_ends_on, actor_user=actor_user, actor_label="admin",
                        reason=f"Invoice {invoice.number} paid after suspension.")
        organization.billing_status = "paid"
    elif await _is_current(db, organization, order):
        organization.billing_status = "paid"
    await db.flush()
    await _alert(db, organization, "bank_transfer_paid", order, invoice_number=invoice.number)
    return payment


async def record_refund(
    db: AsyncSession, *, order: BillingOrder, note: str, actor_user: User, downgrade: bool,
) -> None:
    if order.status not in ("paid", "awaiting_payment", "lapsed"):
        raise BillingConflictError("order_not_refundable", "Only a paid or invoiced order can be refunded")
    if len(_clean(note, 1000)) < 3:
        raise BillingError("note_required", "Write what was refunded and how")
    for payment in (await db.scalars(select(BillingPayment).where(BillingPayment.order_id == order.id))).all():
        payment.status, payment.refunded_amount_cents = "refunded", payment.amount_cents
    invoice = await db.scalar(select(BillingInvoice).where(BillingInvoice.order_id == order.id))
    if invoice is not None and invoice.status in ("issued", "overdue"):
        invoice.status = "void"
    await refund_order(db, order=order, note=note, actor_user=actor_user, actor_label="admin", downgrade=downgrade)


def default_plan_dates(plan: str, start: date) -> tuple[date | None, date | None]:
    """The term a plan gets when an admin sets it without dates: Pilot 3 months, annual plans 12 months,
    per-tender open-ended, Explore none."""
    period = CATALOG[plan].period
    if period == PERIOD_PLAN_TERM:
        return start, add_months(start, PRODUCTS[PRODUCT_PILOT].term_months or 3)
    if period == PERIOD_PLAN_YEAR:
        return start, add_months(start, PRODUCTS[PRODUCT_PURSUIT_DESK].term_months or 12)
    if period == PERIOD_LIFETIME:
        return start, None
    return None, None


async def override_billing(
    db: AsyncSession, *, organization: Organization, plan: str | None, billing_status: str | None, reason: str,
    actor_user: User, plan_started_on: date | None = None, plan_ends_on: date | None = None,
    today: date | None = None,
) -> None:
    """Manual plan and/or billing status, with a reason (both audited). A changed plan (or one without a start
    date) takes the dates given, the rest from ``default_plan_dates`` starting today (or on the start given); the
    same plan keeps its dates unless new ones are given."""
    reason = _clean(reason, 500)
    if len(reason) < 3:
        raise BillingError("reason_required", "Give a reason")
    if billing_status not in (None, "", "none", "paid", "awaiting_payment", "suspended", "refunded", "canceled"):
        raise BillingError("status_invalid", "Unknown billing status")
    if plan is not None:
        if plan not in CATALOG:
            raise BillingError("plan_invalid", "Unknown plan")
        if plan != organization.plan or organization.plan_started_on is None:
            default_start, default_end = default_plan_dates(plan, plan_started_on or today or billing_today())
            start, end = plan_started_on or default_start, plan_ends_on or default_end
        else:
            start, end = plan_started_on or organization.plan_started_on, plan_ends_on or organization.plan_ends_on
        if start is not None and end is not None and end < start:
            raise BillingError("dates_invalid", f"The plan cannot end ({end.isoformat()}) before it starts ({start.isoformat()})")
        await _set_plan(db, organization=organization, plan=plan, start=start, end=end, actor_user=actor_user,
                        actor_label="admin", reason=reason, reset_overrides=False)
    if billing_status is not None:
        wanted = None if billing_status in ("", "none") else billing_status
        before = organization.billing_status
        organization.billing_status = wanted
        await db.flush()
        await _audit(db, organization, ACTION_BILLING_STATUS_CHANGED, actor_user=actor_user, actor_label=None,
                     resource_type="ORGANIZATION", resource_id=organization.id, previous_state={"billing_status": before},
                     new_state={"billing_status": wanted, "plan": organization.plan}, reason=reason)


async def request_cancel_renewal(db: AsyncSession, *, organization: Organization, user: User) -> BillingOrder:
    """Bank-transfer Pursuit Desk: the customer asks not to renew (terms §7). The team confirms it."""
    order = await current_plan_order(db, organization.id)
    if (order is None or order.product != PRODUCT_PURSUIT_DESK or order.method != METHOD_BANK
            or organization.plan != PLAN_PURSUIT_DESK or organization.billing_status not in ("paid", "awaiting_payment")):
        raise BillingConflictError("not_cancellable", "There is no bank-transfer renewal to cancel")
    if order.cancel_requested_at is not None:
        raise BillingConflictError("cancel_requested", "Cancellation was already requested")
    order.cancel_requested_at, order.cancel_requested_by_user_id = _now(), user.id
    await db.flush()
    await _audit(db, organization, ACTION_BILLING_CANCEL_REQUESTED, actor_user=user, actor_label=None,
                 resource_type="BILLING_ORDER", resource_id=order.id,
                 new_state={"renews_on": organization.plan_ends_on.isoformat() if organization.plan_ends_on else None},
                 reason="Customer asked not to renew Pursuit Desk.")
    await _alert(db, organization, "cancel_requested", order,
                 renews_on=organization.plan_ends_on.isoformat() if organization.plan_ends_on else None)
    return order


async def confirm_cancel_renewal(db: AsyncSession, *, order: BillingOrder, actor_user: User) -> None:
    """The team confirms: no renewal invoice; the plan ends on its renewal date (status canceled)."""
    if order.cancel_requested_at is None:
        raise BillingConflictError("cancel_not_requested", "The customer has not asked to cancel")
    if order.cancel_confirmed_at is not None:
        raise BillingConflictError("cancel_confirmed", "Already confirmed")
    organization = await db.get(Organization, order.organization_id, with_for_update=True)
    before = organization.billing_status
    order.cancel_confirmed_at, order.cancel_confirmed_by_user_id = _now(), actor_user.id
    organization.billing_status = "canceled"
    await db.flush()
    await _audit(db, organization, ACTION_BILLING_CANCEL_CONFIRMED, actor_user=actor_user, actor_label=None,
                 resource_type="BILLING_ORDER", resource_id=order.id, previous_state={"billing_status": before},
                 new_state={"billing_status": "canceled",
                            "ends_on": organization.plan_ends_on.isoformat() if organization.plan_ends_on else None},
                 reason="Renewal canceled at the customer's request.")


async def card_customer(db: AsyncSession, organization_id: UUID) -> bool:
    """Polar knows this organization as a customer (a card order was paid)."""
    return await db.scalar(select(BillingPayment.id).where(
        BillingPayment.organization_id == organization_id, BillingPayment.method == METHOD_CARD).limit(1)) is not None


async def customer_portal_url(db: AsyncSession, *, organization: Organization) -> str:
    if not await card_customer(db, organization.id):
        raise BillingConflictError("not_card_customer", "There is no card subscription to manage")
    try:
        return await billing_polar.polar_client().create_customer_portal_url(external_customer_id=str(organization.id))
    except billing_polar.PolarError as exc:
        raise BillingUnavailableError("portal_unavailable", "The subscription page is not available right now") from exc


async def complete_onboarding(db: AsyncSession, *, task: OnboardingTask, note: str | None, actor_user: User) -> None:
    if task.status == "done":
        raise BillingConflictError("task_done", "This onboarding task is already done")
    task.status, task.done_at, task.done_by_user_id = "done", _now(), actor_user.id
    task.note = _clean(note, 1000) or None
    organization = await db.get(Organization, task.organization_id)
    await db.flush()
    await _audit(db, organization, ACTION_BILLING_ONBOARDING_COMPLETED, actor_user=actor_user, actor_label=None,
                 resource_type="ONBOARDING_TASK", resource_id=task.id, new_state={"status": "done"},
                 reason=task.note or "Onboarding done.")


# ---- views -------------------------------------------------------------------------------------

def order_view(order: BillingOrder) -> dict[str, Any]:
    return {
        "id": order.id, "product": order.product, "plan": order.plan, "method": order.method, "status": order.status,
        "list_amount_cents": order.list_amount_cents, "credit_cents": order.credit_cents,
        "amount_cents": order.amount_cents, "created_at": order.created_at, "paid_at": order.paid_at,
        "activated_at": order.activated_at, "refunded_at": order.refunded_at, "refund_note": order.refund_note,
        "plan_started_on": order.plan_started_on, "plan_ends_on": order.plan_ends_on,
        "renewal": order.renewal_of_order_id is not None,
        "refund_window_ends_on": refund_window_ends_on(order),
        "attribution": order.attribution,
        "cancel_requested_at": order.cancel_requested_at, "cancel_confirmed_at": order.cancel_confirmed_at,
    }


def refund_window_ends_on(order: BillingOrder) -> date | None:
    """Terms §6: Pilot refundable on request within 30 days of activation; annual fees not after 14 days."""
    activated = _local_date(order.activated_at)
    if activated is None or order.product == PRODUCT_EXTRA_PURSUIT:
        return None
    return activated + timedelta(days=PILOT_GUARANTEE_DAYS if order.product == PRODUCT_PILOT else ANNUAL_REFUND_DAYS)


def invoice_view(invoice: BillingInvoice) -> dict[str, Any]:
    return {
        "id": invoice.id, "number": invoice.number, "order_id": invoice.order_id, "currency": invoice.currency,
        "list_amount_cents": invoice.list_amount_cents, "credit_cents": invoice.credit_cents,
        "total_usd_cents": invoice.total_usd_cents, "total_uzs": str(invoice.total_uzs) if invoice.total_uzs is not None else None,
        "fx_rate": str(invoice.fx_rate) if invoice.fx_rate is not None else None, "fx_rate_date": invoice.fx_rate_date,
        "issued_on": invoice.issued_on, "due_on": invoice.due_on, "status": invoice.status, "paid_at": invoice.paid_at,
        "reminders_sent": invoice.reminders_sent,
    }


def payment_view(payment: BillingPayment) -> dict[str, Any]:
    return {
        "id": payment.id, "order_id": payment.order_id, "invoice_id": payment.invoice_id, "method": payment.method,
        "provider_payment_id": payment.provider_payment_id, "reference": payment.reference,
        "amount_cents": payment.amount_cents, "currency": payment.currency, "status": payment.status,
        "refunded_amount_cents": payment.refunded_amount_cents, "paid_at": payment.paid_at, "note": payment.note,
    }


async def billing_summary(db: AsyncSession, organization: Organization, *, today: date | None = None) -> dict[str, Any]:
    """What the app shows next to the plan: the billing status, an open invoice, the annual offer."""
    today = today or billing_today()
    open_invoice = await db.scalar(
        select(BillingInvoice).join(BillingOrder, BillingOrder.id == BillingInvoice.order_id).where(
            BillingInvoice.organization_id == organization.id, BillingInvoice.status.in_(("issued", "overdue")),
            BillingOrder.status.in_(("awaiting_payment", "lapsed")),
        ).order_by(BillingInvoice.issued_on.desc()).limit(1)
    )
    offer = None
    if organization.plan == PLAN_PILOT and organization.plan_started_on is not None \
            and (today - organization.plan_started_on).days >= ANNUAL_OFFER_DAY:
        credit = PILOT_CREDIT_CENTS if await pilot_credit_source(db, organization.id, on=today) is not None else 0
        offer = {"product": PRODUCT_PURSUIT_DESK, "list_amount_cents": PRODUCTS[PRODUCT_PURSUIT_DESK].amount_cents,
                 "credit_cents": credit, "pilot_ends_on": organization.plan_ends_on,
                 "day": (today - organization.plan_started_on).days}
    renewal = None
    if organization.plan == PLAN_PURSUIT_DESK:
        order = await current_plan_order(db, organization.id)
        if order is not None and order.plan == PLAN_PURSUIT_DESK:
            renewal = {"method": order.method, "order_id": order.id, "renews_on": organization.plan_ends_on,
                       "canceled": organization.billing_status == "canceled",
                       "cancel_requested_at": order.cancel_requested_at}
    return {
        "status": organization.billing_status,
        "renewal": renewal,
        "card_customer": await card_customer(db, organization.id),
        "open_invoice": None if open_invoice is None else {
            "id": open_invoice.id, "number": open_invoice.number, "due_on": open_invoice.due_on,
            "days_left": (open_invoice.due_on - today).days, "currency": open_invoice.currency,
            "total_usd_cents": open_invoice.total_usd_cents,
            "total_uzs": str(open_invoice.total_uzs) if open_invoice.total_uzs is not None else None,
            "status": open_invoice.status,
        },
        "annual_offer": offer,
        "extra_pursuit_cents": PRODUCTS[PRODUCT_EXTRA_PURSUIT].amount_cents,
    }


async def overview(db: AsyncSession, organization: Organization, *, today: date | None = None) -> dict[str, Any]:
    orders = list((await db.scalars(select(BillingOrder).where(BillingOrder.organization_id == organization.id)
                                    .order_by(BillingOrder.created_at.desc()))).all())
    invoices = list((await db.scalars(select(BillingInvoice).where(BillingInvoice.organization_id == organization.id)
                                      .order_by(BillingInvoice.issued_on.desc(), BillingInvoice.number.desc()))).all())
    payments = list((await db.scalars(select(BillingPayment).where(BillingPayment.organization_id == organization.id)
                                      .order_by(BillingPayment.paid_at.desc()))).all())
    return {
        "organization_id": organization.id, "plan": organization.plan, "plan_started_on": organization.plan_started_on,
        "plan_ends_on": organization.plan_ends_on, "summary": await billing_summary(db, organization, today=today),
        "customer": customer_view(await get_customer(db, organization.id)),
        "orders": [order_view(order) for order in orders if order.status != "pending" or order.provider_checkout_id],
        "invoices": [invoice_view(invoice) for invoice in invoices],
        "payments": [payment_view(payment) for payment in payments],
        "pilot_credit_available": await pilot_credit_source(db, organization.id, on=today) is not None,
    }


async def admin_customers(db: AsyncSession) -> list[dict[str, Any]]:
    """Every organization with billing details or an order, newest activity first."""
    ids = set((await db.scalars(select(BillingCustomer.organization_id))).all())
    ids |= set((await db.scalars(select(BillingOrder.organization_id))).all())
    rows = []
    for organization in (await db.scalars(select(Organization).where(Organization.id.in_(ids)))).all() if ids else []:
        customer = await get_customer(db, organization.id)
        last = await db.scalar(select(BillingOrder).where(BillingOrder.organization_id == organization.id)
                               .order_by(BillingOrder.created_at.desc()).limit(1))
        open_invoices = await db.scalar(select(func.count()).select_from(BillingInvoice).where(
            BillingInvoice.organization_id == organization.id, BillingInvoice.status.in_(("issued", "overdue"))))
        open_task = await db.scalar(select(OnboardingTask.id).where(
            OnboardingTask.organization_id == organization.id, OnboardingTask.status == "open").limit(1))
        cancel_request = await db.scalar(select(BillingOrder.id).where(
            BillingOrder.organization_id == organization.id, BillingOrder.cancel_requested_at.is_not(None),
            BillingOrder.cancel_confirmed_at.is_(None)).limit(1))
        rows.append({
            "organization_id": organization.id, "organization_name": _display(organization),
            "legal_name": customer.legal_name if customer else None, "country": customer.country if customer else None,
            "resident": customer.resident if customer else None, "plan": organization.plan,
            "access_state": organization.access_state, "billing_status": organization.billing_status,
            "plan_started_on": organization.plan_started_on, "plan_ends_on": organization.plan_ends_on,
            "last_order": order_view(last) if last else None, "open_invoices": int(open_invoices or 0),
            "onboarding_open": open_task is not None, "cancel_requested": cancel_request is not None,
            "last_activity_at": last.updated_at if last else (customer.updated_at if customer else None),
        })
    rows.sort(key=lambda row: row["last_activity_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return rows


async def admin_detail(db: AsyncSession, organization: Organization) -> dict[str, Any]:
    from app.models.audit import AdminActivityEvent

    data = await overview(db, organization)
    acceptances = (await db.scalars(select(TermsAcceptance).where(TermsAcceptance.organization_id == organization.id)
                                    .order_by(TermsAcceptance.accepted_at.desc()))).all()
    users = {user.id: user.email for user in (await db.scalars(select(User).where(
        User.id.in_([row.user_id for row in acceptances if row.user_id])))).all()} if acceptances else {}
    events = (await db.scalars(select(BillingEvent).where(BillingEvent.organization_id == organization.id)
                               .order_by(BillingEvent.received_at.desc()).limit(50))).all()
    tasks = (await db.scalars(select(OnboardingTask).where(OnboardingTask.organization_id == organization.id)
                              .order_by(OnboardingTask.created_at.desc()))).all()
    audit = (await db.scalars(
        select(AdminActivityEvent).where(
            or_(AdminActivityEvent.action.like("BILLING_%"),
                AdminActivityEvent.action.in_(("ORGANIZATION_ACCESS_CHANGED", "ORGANIZATION_PLAN_GRANTED"))),
            or_(AdminActivityEvent.metadata_json["organization_id"].astext == str(organization.id),
                AdminActivityEvent.target_resource_id == str(organization.id)),
        )
        .order_by(AdminActivityEvent.created_at.desc()).limit(60)
    )).all()
    data.update({
        # The console's detail actions (override, offers, invoices) post to this id (Deploy 5.1).
        "organization_id": organization.id,
        "organization_name": _display(organization), "access_state": organization.access_state,
        "billing_status": organization.billing_status,
        "terms_acceptances": [{
            "terms_version": row.terms_version, "text_sha256": row.text_sha256,
            "user_email": users.get(row.user_id), "ip_address": row.ip_address, "accepted_at": row.accepted_at,
            "accepted_via": row.accepted_via, "note": row.note,
        } for row in acceptances],
        "events": [{"id": row.id, "event_type": row.event_type, "provider_event_id": row.provider_event_id,
                    "outcome": row.outcome, "processing_error": row.processing_error, "received_at": row.received_at,
                    "processed_at": row.processed_at} for row in events],
        "onboarding": [{"id": row.id, "order_id": row.order_id, "status": row.status, "note": row.note,
                        "created_at": row.created_at, "done_at": row.done_at} for row in tasks],
        "offers": [{"id": row.id, "product": row.product, "note": row.note, "expires_at": row.expires_at,
                    "order_id": row.order_id, "created_at": row.created_at} for row in (await db.scalars(
                        select(BillingOffer).where(BillingOffer.organization_id == organization.id)
                        .order_by(BillingOffer.created_at.desc()).limit(20))).all()],
        "audit": [{"id": row.id, "action": row.action, "actor": row.actor_email_snapshot or row.actor_label,
                   "reason": row.reason, "created_at": row.created_at, "new_state": row.new_state} for row in audit],
    })
    return data


async def webhook_health(db: AsyncSession, *, now: datetime | None = None) -> dict[str, Any]:
    """Deploy 5.1: is Polar delivering ``order.paid``? Warns when none has arrived 24 hours after the first card
    checkout (the live endpoint was once subscribed to checkout.* only, so paid cards stayed pending)."""
    now = now or _now()
    first_checkout = await db.scalar(select(func.min(BillingOrder.created_at)).where(
        BillingOrder.method == METHOD_CARD, BillingOrder.provider_checkout_id.is_not(None)))
    rows = (await db.execute(
        select(BillingEvent.event_type, func.count(), func.max(BillingEvent.received_at))
        .where(BillingEvent.provider == "polar").group_by(BillingEvent.event_type).order_by(BillingEvent.event_type)
    )).all()
    events = [{"event_type": event_type, "count": int(count), "last_received_at": last} for event_type, count, last in rows]
    order_paid = next((row for row in events if row["event_type"] == "order.paid"), None)
    pending = await db.scalar(select(func.count()).select_from(BillingOrder).where(
        BillingOrder.method == METHOD_CARD, BillingOrder.status == "pending",
        BillingOrder.provider_checkout_id.is_not(None)))
    return {
        "first_card_checkout_at": first_checkout,
        "last_order_paid_at": order_paid["last_received_at"] if order_paid else None,
        "pending_card_orders": int(pending or 0), "events": events,
        "warning": bool(first_checkout is not None and order_paid is None
                        and now - first_checkout >= timedelta(hours=ORDER_PAID_ALERT_HOURS)),
    }


async def admin_onboarding_queue(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(OnboardingTask, Organization, BillingOrder)
        .join(Organization, Organization.id == OnboardingTask.organization_id)
        .join(BillingOrder, BillingOrder.id == OnboardingTask.order_id)
        .order_by((OnboardingTask.status == "open").desc(), OnboardingTask.created_at.desc()).limit(100)
    )).all()
    return [{
        "id": task.id, "organization_id": organization.id, "organization_name": _display(organization),
        "product": order.product, "method": order.method, "order_status": order.status, "status": task.status,
        "note": task.note, "created_at": task.created_at, "done_at": task.done_at,
    } for task, organization, order in rows]
