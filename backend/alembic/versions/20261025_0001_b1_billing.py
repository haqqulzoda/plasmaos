"""B1: billing. Customers, terms acceptances, orders, invoices (PL-YYYY-NNN), payments, the webhook
inbox, the one-time pilot credit, CBU rates, onboarding tasks; organizations.billing_status; the
BILLING e-mail kinds and category and the BILLING team alert.

Additive; no backfill (plans set by admins keep billing_status NULL). Downgrade drops the tables,
the column, and the e-mails and alerts of the new kinds.

Revision ID: 20261025_0001_b1_billing
Revises: 20261024_0001_p3_plans_limits
Create Date: 2026-10-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261025_0001_b1_billing"
down_revision: Union[str, None] = "20261024_0001_p3_plans_limits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_ALERT_KINDS = "'NEW_SIGNUP','PILOT_REQUEST','ANALYSIS_PROVIDER_ERROR','PARTNER_REQUEST','PLAN_USAGE'"
NEW_ALERT_KINDS = OLD_ALERT_KINDS + ",'BILLING'"
OLD_EMAIL_KINDS = (
    "'TEAM_INVITATION','ANALYSIS_COMPLETED','ANALYSIS_FAILED','EOI_DRAFT_READY','DAILY_DIGEST','SIGN_IN_CODE',"
    "'ADMIN_ALERT'"
)
NEW_EMAIL_KINDS = OLD_EMAIL_KINDS + ",'BILLING_INVOICE','BILLING_REMINDER','BILLING_WELCOME','BILLING_SUSPENDED'"
OLD_EMAIL_CATEGORIES = "'TEAM','ANALYSIS','EOI','DIGEST','AUTH','ADMIN'"
NEW_EMAIL_CATEGORIES = OLD_EMAIL_CATEGORIES + ",'BILLING'"

UUID = postgresql.UUID(as_uuid=True)


def _now() -> sa.Column:
    return sa.text("now()")


def upgrade() -> None:
    op.add_column("organizations", sa.Column("billing_status", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        "ck_organizations_billing_status", "organizations",
        "billing_status IS NULL OR billing_status IN ('paid','awaiting_payment','suspended','refunded','canceled')",
    )

    op.create_table(
        "billing_customers",
        sa.Column("id", UUID, nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("legal_name", sa.String(length=300), nullable=False),
        sa.Column("tin", sa.String(length=40), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("billing_email", sa.String(length=255), nullable=False),
        sa.Column("resident", sa.Boolean(), nullable=False),
        sa.Column("updated_by_user_id", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("length(trim(legal_name)) >= 2", name="ck_billing_customer_name"),
        sa.CheckConstraint("country ~ '^[A-Z]{2}$'", name="ck_billing_customer_country"),
        sa.CheckConstraint("NOT resident OR (country = 'UZ' AND tin IS NOT NULL)", name="ck_billing_customer_resident"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id"),
    )

    op.create_table(
        "terms_acceptances",
        sa.Column("id", UUID, nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("terms_version", sa.String(length=40), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("text_sha256 ~ '^[0-9a-f]{64}$'", name="ck_terms_acceptance_hash"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_terms_acceptances_organization", "terms_acceptances", ["organization_id", "accepted_at"])

    op.create_table(
        "billing_orders",
        sa.Column("id", UUID, nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("product", sa.String(length=20), nullable=False),
        sa.Column("plan", sa.String(length=20), nullable=True),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'USD'"), nullable=False),
        sa.Column("list_amount_cents", sa.Integer(), nullable=False),
        sa.Column("credit_cents", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("terms_acceptance_id", UUID, nullable=True),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column("provider_checkout_id", sa.String(length=100), nullable=True),
        sa.Column("provider_checkout_url", sa.String(length=1000), nullable=True),
        sa.Column("provider_discount_id", sa.String(length=100), nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=100), nullable=True),
        sa.Column("renewal_of_order_id", UUID, nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_started_on", sa.Date(), nullable=True),
        sa.Column("plan_ends_on", sa.Date(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refund_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("product IN ('pilot','pursuit_desk','extra_pursuit')", name="ck_billing_order_product"),
        sa.CheckConstraint("method IN ('card','bank_transfer')", name="ck_billing_order_method"),
        sa.CheckConstraint(
            "status IN ('pending','awaiting_payment','paid','lapsed','refunded','canceled')", name="ck_billing_order_status"
        ),
        sa.CheckConstraint(
            "list_amount_cents >= 0 AND credit_cents >= 0 AND amount_cents = list_amount_cents - credit_cents "
            "AND amount_cents >= 0",
            name="ck_billing_order_amounts",
        ),
        sa.CheckConstraint("(status = 'paid') <= (paid_at IS NOT NULL)", name="ck_billing_order_paid"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["terms_acceptance_id"], ["terms_acceptances.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["renewal_of_order_id"], ["billing_orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_checkout_id"),
    )
    op.create_index("ix_billing_orders_organization_created", "billing_orders", ["organization_id", "created_at"])
    op.create_index("ix_billing_orders_subscription", "billing_orders", ["provider_subscription_id"])

    op.create_table(
        "billing_invoice_counters",
        sa.Column("year", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("year"),
    )

    op.create_table(
        "billing_invoices",
        sa.Column("id", UUID, nullable=False),
        sa.Column("number", sa.String(length=20), nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("order_id", UUID, nullable=False),
        sa.Column("customer", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("list_amount_cents", sa.Integer(), nullable=False),
        sa.Column("credit_cents", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_usd_cents", sa.Integer(), nullable=False),
        sa.Column("fx_rate", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("fx_rate_date", sa.Date(), nullable=True),
        sa.Column("total_uzs", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reminders_sent", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("number ~ '^PL-[0-9]{4}-[0-9]{3,}$'", name="ck_billing_invoice_number"),
        sa.CheckConstraint("currency IN ('UZS','USD')", name="ck_billing_invoice_currency"),
        sa.CheckConstraint("status IN ('issued','paid','overdue','void')", name="ck_billing_invoice_status"),
        sa.CheckConstraint(
            "(currency = 'UZS') = (fx_rate IS NOT NULL AND total_uzs IS NOT NULL AND fx_rate_date IS NOT NULL)",
            name="ck_billing_invoice_fx",
        ),
        sa.CheckConstraint("total_usd_cents = list_amount_cents - credit_cents", name="ck_billing_invoice_amounts"),
        sa.CheckConstraint("jsonb_typeof(customer) = 'object'", name="ck_billing_invoice_customer"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["billing_orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
        sa.UniqueConstraint("order_id"),
    )
    op.create_index("ix_billing_invoices_organization", "billing_invoices", ["organization_id", "issued_on"])
    op.create_index(
        "ix_billing_invoices_open", "billing_invoices", ["issued_on"],
        postgresql_where=sa.text("status IN ('issued','overdue')"),
    )

    op.create_table(
        "billing_payments",
        sa.Column("id", UUID, nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("order_id", UUID, nullable=False),
        sa.Column("invoice_id", UUID, nullable=True),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=100), nullable=True),
        sa.Column("reference", sa.String(length=200), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("refunded_amount_cents", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by_user_id", UUID, nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("method IN ('card','bank_transfer')", name="ck_billing_payment_method"),
        sa.CheckConstraint("status IN ('paid','partially_refunded','refunded')", name="ck_billing_payment_status"),
        sa.CheckConstraint("amount_cents >= 0 AND refunded_amount_cents >= 0", name="ck_billing_payment_amounts"),
        sa.CheckConstraint(
            "method <> 'bank_transfer' OR length(trim(coalesce(reference, ''))) >= 3", name="ck_billing_payment_reference"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["billing_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invoice_id"], ["billing_invoices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_payment_id"),
    )
    op.create_index("ix_billing_payments_order", "billing_payments", ["order_id"])

    op.create_table(
        "billing_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_event_id", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("signature_verified", sa.Boolean(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("organization_id", UUID, nullable=True),
        sa.Column("outcome", sa.String(length=200), nullable=True),
        sa.Column("processing_error", sa.String(length=200), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("provider IN ('polar')", name="ck_billing_event_provider"),
        sa.CheckConstraint("signature_verified", name="ck_billing_event_verified"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_billing_event_payload"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_billing_event_provider_id"),
    )
    op.create_index("ix_billing_events_received", "billing_events", ["received_at"])

    op.create_table(
        "billing_pilot_credits",
        sa.Column("id", UUID, nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("pilot_order_id", UUID, nullable=False),
        sa.Column("order_id", UUID, nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pilot_order_id"], ["billing_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["billing_orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id"),
        sa.UniqueConstraint("order_id"),
    )

    op.create_table(
        "billing_fx_rates",
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("source", sa.String(length=20), server_default=sa.text("'CBU'"), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("rate > 0", name="ck_billing_fx_rate_positive"),
        sa.PrimaryKeyConstraint("currency", "rate_date"),
    )

    op.create_table(
        "billing_onboarding_tasks",
        sa.Column("id", UUID, nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("order_id", UUID, nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'open'"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_by_user_id", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("status IN ('open','done')", name="ck_onboarding_task_status"),
        sa.CheckConstraint("(status = 'done') = (done_at IS NOT NULL)", name="ck_onboarding_task_done"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["billing_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["done_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id"),
    )
    op.create_index("ix_onboarding_tasks_status", "billing_onboarding_tasks", ["status", "created_at"])

    op.drop_constraint("ck_admin_alert_kind", "admin_alerts", type_="check")
    op.create_check_constraint("ck_admin_alert_kind", "admin_alerts", f"kind IN ({NEW_ALERT_KINDS})")
    op.drop_constraint("ck_email_delivery_kind", "email_deliveries", type_="check")
    op.create_check_constraint("ck_email_delivery_kind", "email_deliveries", f"kind IN ({NEW_EMAIL_KINDS})")
    op.drop_constraint("ck_email_delivery_category", "email_deliveries", type_="check")
    op.create_check_constraint(
        "ck_email_delivery_category", "email_deliveries", f"category IN ({NEW_EMAIL_CATEGORIES})"
    )


def downgrade() -> None:
    op.execute("DELETE FROM email_deliveries WHERE category = 'BILLING' OR kind LIKE 'BILLING\\_%'")
    op.drop_constraint("ck_email_delivery_category", "email_deliveries", type_="check")
    op.create_check_constraint(
        "ck_email_delivery_category", "email_deliveries", f"category IN ({OLD_EMAIL_CATEGORIES})"
    )
    op.drop_constraint("ck_email_delivery_kind", "email_deliveries", type_="check")
    op.create_check_constraint("ck_email_delivery_kind", "email_deliveries", f"kind IN ({OLD_EMAIL_KINDS})")
    op.execute("DELETE FROM admin_alerts WHERE kind = 'BILLING'")
    op.drop_constraint("ck_admin_alert_kind", "admin_alerts", type_="check")
    op.create_check_constraint("ck_admin_alert_kind", "admin_alerts", f"kind IN ({OLD_ALERT_KINDS})")
    op.drop_index("ix_onboarding_tasks_status", table_name="billing_onboarding_tasks")
    op.drop_table("billing_onboarding_tasks")
    op.drop_table("billing_fx_rates")
    op.drop_table("billing_pilot_credits")
    op.drop_index("ix_billing_events_received", table_name="billing_events")
    op.drop_table("billing_events")
    op.drop_index("ix_billing_payments_order", table_name="billing_payments")
    op.drop_table("billing_payments")
    op.drop_index("ix_billing_invoices_open", table_name="billing_invoices")
    op.drop_index("ix_billing_invoices_organization", table_name="billing_invoices")
    op.drop_table("billing_invoices")
    op.drop_table("billing_invoice_counters")
    op.drop_index("ix_billing_orders_subscription", table_name="billing_orders")
    op.drop_index("ix_billing_orders_organization_created", table_name="billing_orders")
    op.drop_table("billing_orders")
    op.drop_index("ix_terms_acceptances_organization", table_name="terms_acceptances")
    op.drop_table("terms_acceptances")
    op.drop_table("billing_customers")
    op.drop_constraint("ck_organizations_billing_status", "organizations", type_="check")
    op.drop_column("organizations", "billing_status")
