"""B1: billing as the app and the admin console read and write it."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class BillingCustomerIn(BaseModel):
    legal_name: str = Field(max_length=300)
    tin: str | None = Field(default=None, max_length=40)
    country: str = Field(max_length=2)
    address: str = Field(max_length=500)
    billing_email: str = Field(max_length=255)
    resident: bool


class BillingCustomerOut(BaseModel):
    legal_name: str
    tin: str | None = None
    country: str
    address: str
    billing_email: str
    resident: bool
    updated_at: datetime | None = None


class TermsResponse(BaseModel):
    version: str
    sha256: str
    markdown: str


class QuoteMethods(BaseModel):
    card: bool
    bank_transfer: bool


class QuoteResponse(BaseModel):
    product: str
    plan: str | None = None
    list_amount_cents: int
    credit_cents: int
    amount_cents: int
    billing: str
    term_months: int | None = None
    blocker: str | None = None
    methods: QuoteMethods
    invoice_currency: Literal["UZS", "USD"]


class CheckoutRequest(BaseModel):
    product: Literal["pilot", "pursuit_desk", "extra_pursuit"]
    method: Literal["card", "bank_transfer"]
    terms_version: str = Field(max_length=40)
    terms_sha256: str = Field(min_length=64, max_length=64)
    accept_terms: bool


class CheckoutResponse(BaseModel):
    order_id: UUID
    method: str
    status: str
    checkout_url: str | None = None
    invoice_id: UUID | None = None
    invoice_number: str | None = None


class OrderOut(BaseModel):
    id: UUID
    product: str
    plan: str | None = None
    method: str
    status: str
    list_amount_cents: int
    credit_cents: int
    amount_cents: int
    created_at: datetime
    paid_at: datetime | None = None
    activated_at: datetime | None = None
    refunded_at: datetime | None = None
    refund_note: str | None = None
    plan_started_on: date | None = None
    plan_ends_on: date | None = None
    renewal: bool = False


class InvoiceOut(BaseModel):
    id: UUID
    number: str
    order_id: UUID
    currency: str
    list_amount_cents: int
    credit_cents: int
    total_usd_cents: int
    total_uzs: str | None = None
    fx_rate: str | None = None
    fx_rate_date: date | None = None
    issued_on: date
    due_on: date
    status: str
    paid_at: datetime | None = None
    reminders_sent: int = 0


class PaymentOut(BaseModel):
    id: UUID
    order_id: UUID
    invoice_id: UUID | None = None
    method: str
    provider_payment_id: str | None = None
    reference: str | None = None
    amount_cents: int
    currency: str
    status: str
    refunded_amount_cents: int
    paid_at: datetime
    note: str | None = None


class OpenInvoice(BaseModel):
    id: UUID
    number: str
    due_on: date
    days_left: int
    currency: str
    total_usd_cents: int
    total_uzs: str | None = None
    status: str


class AnnualOffer(BaseModel):
    product: str
    list_amount_cents: int
    credit_cents: int
    pilot_ends_on: date | None = None
    day: int


class BillingSummary(BaseModel):
    status: str | None = None
    open_invoice: OpenInvoice | None = None
    annual_offer: AnnualOffer | None = None
    extra_pursuit_cents: int | None = None


class BillingOverview(BaseModel):
    organization_id: UUID
    plan: str
    plan_started_on: date | None = None
    plan_ends_on: date | None = None
    summary: BillingSummary
    customer: BillingCustomerOut | None = None
    orders: list[OrderOut]
    invoices: list[InvoiceOut]
    payments: list[PaymentOut]
    pilot_credit_available: bool


class OrderStatusResponse(BaseModel):
    order: OrderOut
    plan: str
    billing_status: str | None = None


class CatalogResponse(BaseModel):
    currency: str
    plans: list[dict[str, Any]]
    products: list[dict[str, Any]]
    pilot_credit_cents: int
    bank_transfer: dict[str, bool]
    polar_env: str


class AdminBillingCustomer(BaseModel):
    organization_id: UUID
    organization_name: str
    legal_name: str | None = None
    country: str | None = None
    resident: bool | None = None
    plan: str
    access_state: str
    billing_status: str | None = None
    plan_started_on: date | None = None
    plan_ends_on: date | None = None
    last_order: OrderOut | None = None
    open_invoices: int
    onboarding_open: bool
    last_activity_at: datetime | None = None


class AdminBillingDetail(BillingOverview):
    organization_name: str
    access_state: str
    billing_status: str | None = None
    terms_acceptances: list[dict[str, Any]]
    events: list[dict[str, Any]]
    onboarding: list[dict[str, Any]]
    audit: list[dict[str, Any]]


class OnboardingTaskOut(BaseModel):
    id: UUID
    organization_id: UUID
    organization_name: str
    product: str
    method: str
    order_status: str
    status: str
    note: str | None = None
    created_at: datetime
    done_at: datetime | None = None


class MarkPaidRequest(BaseModel):
    reference: str = Field(min_length=3, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class RefundNoteRequest(BaseModel):
    note: str = Field(min_length=3, max_length=1000)
    downgrade: bool = True


class BillingOverrideRequest(BaseModel):
    plan: Literal["explore", "pilot", "pursuit_desk", "agent", "enterprise", "per_tender"] | None = None
    billing_status: Literal["none", "paid", "awaiting_payment", "suspended", "refunded", "canceled"] | None = None
    plan_started_on: date | None = None
    plan_ends_on: date | None = None
    reason: str = Field(min_length=3, max_length=500)


class OnboardingDoneRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)
