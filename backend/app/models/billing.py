"""B1: billing. Customers, accepted terms, orders, invoices (PL-YYYY-NNN), payments, the provider
webhook inbox, the one-time pilot credit, CBU exchange rates and onboarding tasks.

Amounts are USD cents. Every change is also an administrative audit event (app.services.billing).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

BILLING_STATUSES = ("paid", "awaiting_payment", "suspended", "refunded", "canceled")
ORDER_PRODUCTS = ("pilot", "pursuit_desk", "extra_pursuit")
ORDER_METHODS = ("card", "bank_transfer")
# pending: a card checkout not paid yet; awaiting_payment: a bank transfer, plan active; lapsed: the
# transfer did not arrive by day 10 (plan back to Explore; marking it paid later reactivates it).
ORDER_STATUSES = ("pending", "awaiting_payment", "paid", "lapsed", "refunded", "canceled")
INVOICE_STATUSES = ("issued", "paid", "overdue", "void")
PAYMENT_STATUSES = ("paid", "partially_refunded", "refunded")


def _values(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


class BillingCustomer(Base):
    """The organization's invoicing details (one row per organization)."""

    __tablename__ = "billing_customers"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    legal_name: Mapped[str] = mapped_column(String(300), nullable=False)
    tin: Mapped[str | None] = mapped_column(String(40), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    billing_email: Mapped[str] = mapped_column(String(255), nullable=False)
    resident: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("length(trim(legal_name)) >= 2", name="ck_billing_customer_name"),
        CheckConstraint("country ~ '^[A-Z]{2}$'", name="ck_billing_customer_country"),
        CheckConstraint("NOT resident OR (country = 'UZ' AND tin IS NOT NULL)", name="ck_billing_customer_resident"),
    )


class TermsAcceptance(Base):
    """Who accepted which terms text (version and SHA-256 of the exact text shown), when, from where."""

    __tablename__ = "terms_acceptances"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    terms_version: Mapped[str] = mapped_column(String(40), nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("text_sha256 ~ '^[0-9a-f]{64}$'", name="ck_terms_acceptance_hash"),
        Index("ix_terms_acceptances_organization", "organization_id", "accepted_at"),
    )


class BillingOrder(Base):
    __tablename__ = "billing_orders"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    product: Mapped[str] = mapped_column(String(20), nullable=False)
    plan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default=text("'USD'"))
    list_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    credit_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    terms_acceptance_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("terms_acceptances.id", ondelete="RESTRICT")
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    provider_checkout_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    provider_checkout_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    provider_discount_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    renewal_of_order_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("billing_orders.id", ondelete="RESTRICT")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    plan_started_on: Mapped[date | None] = mapped_column(Date)
    plan_ends_on: Mapped[date | None] = mapped_column(Date)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refund_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"product IN ({_values(ORDER_PRODUCTS)})", name="ck_billing_order_product"),
        CheckConstraint(f"method IN ({_values(ORDER_METHODS)})", name="ck_billing_order_method"),
        CheckConstraint(f"status IN ({_values(ORDER_STATUSES)})", name="ck_billing_order_status"),
        CheckConstraint(
            "list_amount_cents >= 0 AND credit_cents >= 0 AND amount_cents = list_amount_cents - credit_cents "
            "AND amount_cents >= 0",
            name="ck_billing_order_amounts",
        ),
        CheckConstraint("(status = 'paid') <= (paid_at IS NOT NULL)", name="ck_billing_order_paid"),
        Index("ix_billing_orders_organization_created", "organization_id", "created_at"),
        Index("ix_billing_orders_subscription", "provider_subscription_id"),
    )


class InvoiceCounter(Base):
    """The last invoice number issued per year (PL-YYYY-NNN), advanced under a row lock."""

    __tablename__ = "billing_invoice_counters"

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False)


class BillingInvoice(Base):
    __tablename__ = "billing_invoices"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("billing_orders.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    # The buyer as invoiced (a copy: later edits of the customer do not change an issued invoice).
    customer: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)  # the payable currency: UZS or USD
    list_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    credit_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    total_usd_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))  # UZS per USD (CBU), residents only
    fx_rate_date: Mapped[date | None] = mapped_column(Date)
    total_uzs: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reminders_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("number ~ '^PL-[0-9]{4}-[0-9]{3,}$'", name="ck_billing_invoice_number"),
        CheckConstraint("currency IN ('UZS','USD')", name="ck_billing_invoice_currency"),
        CheckConstraint(f"status IN ({_values(INVOICE_STATUSES)})", name="ck_billing_invoice_status"),
        CheckConstraint(
            "(currency = 'UZS') = (fx_rate IS NOT NULL AND total_uzs IS NOT NULL AND fx_rate_date IS NOT NULL)",
            name="ck_billing_invoice_fx",
        ),
        CheckConstraint("total_usd_cents = list_amount_cents - credit_cents", name="ck_billing_invoice_amounts"),
        CheckConstraint("jsonb_typeof(customer) = 'object'", name="ck_billing_invoice_customer"),
        Index("ix_billing_invoices_organization", "organization_id", "issued_on"),
        Index("ix_billing_invoices_open", "issued_on", postgresql_where=text("status IN ('issued','overdue')")),
    )


class BillingPayment(Base):
    __tablename__ = "billing_payments"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("billing_orders.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("billing_invoices.id", ondelete="RESTRICT")
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)  # Polar order id
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True)  # bank reference
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    refunded_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(f"method IN ({_values(ORDER_METHODS)})", name="ck_billing_payment_method"),
        CheckConstraint(f"status IN ({_values(PAYMENT_STATUSES)})", name="ck_billing_payment_status"),
        CheckConstraint("amount_cents >= 0 AND refunded_amount_cents >= 0", name="ck_billing_payment_amounts"),
        CheckConstraint(
            "method <> 'bank_transfer' OR length(trim(coalesce(reference, ''))) >= 3", name="ck_billing_payment_reference"
        ),
        Index("ix_billing_payments_order", "order_id"),
    )


class BillingEvent(Base):
    """Webhook inbox: one row per provider event id. Only deliveries whose signature verified are
    stored (a forged delivery is refused and cannot claim an event id); processed_at marks done."""

    __tablename__ = "billing_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    organization_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL")
    )
    outcome: Mapped[str | None] = mapped_column(String(200))
    processing_error: Mapped[str | None] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_billing_event_provider_id"),
        CheckConstraint("provider IN ('polar')", name="ck_billing_event_provider"),
        CheckConstraint("signature_verified", name="ck_billing_event_verified"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_billing_event_payload"),
        Index("ix_billing_events_received", "received_at"),
    )


class PilotCreditRedemption(Base):
    """The paid pilot credited to the first annual order: at most once per organization."""

    __tablename__ = "billing_pilot_credits"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    pilot_order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("billing_orders.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("billing_orders.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FxRate(Base):
    """Central Bank of Uzbekistan rate, UZS per unit, by date (cached)."""

    __tablename__ = "billing_fx_rates"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="CBU", server_default=text("'CBU'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (CheckConstraint("rate > 0", name="ck_billing_fx_rate_positive"),)


class OnboardingTask(Base):
    """Admin queue: kick off a newly activated customer (one task per activated plan order)."""

    __tablename__ = "billing_onboarding_tasks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("billing_orders.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default=text("'open'"))
    note: Mapped[str | None] = mapped_column(Text)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('open','done')", name="ck_onboarding_task_status"),
        CheckConstraint("(status = 'done') = (done_at IS NOT NULL)", name="ck_onboarding_task_done"),
        Index("ix_onboarding_tasks_status", "status", "created_at"),
    )
