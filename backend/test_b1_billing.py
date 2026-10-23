"""B1 billing and the instant pilot: the catalogue, webhook signatures, the settings guard, the terms
hash, the invoice PDF (pure), the migration, then one Postgres scenario through the endpoints: card
pilot (terms stored, webhook activation, idempotency, forged and failing deliveries), Pursuit Desk
with the pilot credit applied once, subscription events, refund; bank transfer (UZS invoice, PDF
e-mail, reminders on days 3 and 6, Explore on day 10, admin mark paid), extra pursuit, the day-75
offer, organization isolation and the admin console."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.core.plans import PILOT_CREDIT_CENTS, PRICES, PRODUCTS, PRODUCTS_FOR_SALE
from app.services import billing_polar
from app.services.billing import add_months, billing_today, terms

HEAD = "20261025_0001_b1_billing"
P3_HEAD = "20261024_0001_p3_plans_limits"
SECRET = "whsec_" + "c2VjcmV0LWZvci1iMS10ZXN0cy1vbmx5LW5vdC1yZWFs"  # base64 of a test-only key


# ---- pure ----------------------------------------------------------------------------------------

def test_catalogue_prices_products_and_credit() -> None:
    assert {code: (price.amount_cents, price.billing) for code, price in PRICES.items()} == {
        "explore": (0, "free"), "pilot": (90_000, "one_time"), "pursuit_desk": (600_000, "annual"),
        "agent": (1_800_000, "contact"), "enterprise": (3_600_000, "contact"), "per_tender": (40_000, "contact"),
    }
    assert PRICES["pilot"].monthly_cents * 3 == PRICES["pilot"].amount_cents and PRICES["enterprise"].from_price
    assert PRODUCTS_FOR_SALE == ("pilot", "pursuit_desk", "extra_pursuit")
    assert {code: (p.plan, p.amount_cents, p.term_months, p.extra_pursuits) for code, p in PRODUCTS.items()} == {
        "pilot": ("pilot", 90_000, 3, 0), "pursuit_desk": ("pursuit_desk", 600_000, 12, 0),
        "extra_pursuit": (None, 20_000, None, 1),
    }
    assert PILOT_CREDIT_CENTS == 90_000
    assert add_months(date(2026, 10, 24), 3) == date(2027, 1, 24)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert add_months(date(2027, 2, 28), 12) == date(2028, 2, 28)


def test_webhook_signature_standard_webhooks() -> None:
    body = b'{"type":"order.paid","data":{"id":"x"}}'
    now = time.time()
    stamp = str(int(now))
    for utf8 in (False, True):  # whsec_ base64 key, and older Polar secrets keyed by the whole string
        signature = billing_polar.sign(SECRET, "msg_1", stamp, body, utf8_key=utf8)
        headers = {"Webhook-Id": "msg_1", "Webhook-Timestamp": stamp, "Webhook-Signature": f"v1,bogus {signature}"}
        assert billing_polar.verify_webhook(body, headers, secret=SECRET, now=now) == "msg_1"
    plain = billing_polar.sign("plain-secret", "msg_2", stamp, body)
    assert billing_polar.verify_webhook(body, {"webhook-id": "msg_2", "webhook-timestamp": stamp,
                                               "webhook-signature": plain}, secret="plain-secret", now=now) == "msg_2"
    good = {"webhook-id": "msg_1", "webhook-timestamp": stamp, "webhook-signature": billing_polar.sign(SECRET, "msg_1", stamp, body)}
    failures = [
        (body + b" ", good, SECRET, now),  # tampered body
        (body, {**good, "webhook-id": "msg_9"}, SECRET, now),  # another id
        (body, good, "whsec_b3RoZXI=", now),  # another secret
        (body, good, SECRET, now + 600),  # stale
        (body, {"webhook-id": "msg_1"}, SECRET, now),  # headers missing
        (body, good, "", now),  # no secret configured
    ]
    for payload, headers, secret, at in failures:
        with pytest.raises(billing_polar.WebhookSignatureError):
            billing_polar.verify_webhook(payload, headers, secret=secret, now=at)


def test_settings_refuse_polar_production_outside_production() -> None:
    from app.core.config import Settings

    base = dict(POSTGRES_SERVER="x", POSTGRES_USER="x", POSTGRES_PASSWORD="x", POSTGRES_DB="x",
                SECRET_KEY="x" * 40, TELEGRAM_BOT_TOKEN="x")
    assert Settings(**base, ENVIRONMENT="development").POLAR_ENV == "sandbox"
    with pytest.raises(ValueError, match="Polar production keys"):
        Settings(**base, ENVIRONMENT="development", POLAR_ENV="production")
    with pytest.raises(ValueError, match="POLAR_ENV"):
        Settings(**base, POLAR_ENV="live")
    assert billing_polar.POLAR_API["sandbox"] == "https://sandbox-api.polar.sh"


def test_terms_text_is_the_docs_copy_and_hashed_with_lf() -> None:
    root = Path(__file__).resolve().parents[1]
    docs = (root / "docs" / "legal" / "PILOT_TERMS_v1.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    current = terms()
    assert current["markdown"] == docs and current["version"] == "PILOT_TERMS_v1"
    assert current["sha256"] == hashlib.sha256(docs.encode()).hexdigest()
    assert "credited once, to your first annual invoice" in docs and "30 days" in docs


def test_invoice_pdf_renders_uzs_and_usd() -> None:
    from app.services.billing_invoice_pdf import render_invoice_pdf

    order = SimpleNamespace(product="pilot", plan_started_on=date(2026, 10, 24), plan_ends_on=date(2027, 1, 24))
    for currency in ("UZS", "USD"):
        invoice = SimpleNamespace(
            number="PL-2026-001", issued_on=date(2026, 10, 24), due_on=date(2026, 11, 3), currency=currency,
            customer={"legal_name": "ООО «Тест»", "tin": "123456789", "address": "Tashkent", "country": "UZ",
                      "billing_email": "billing@example.invalid"},
            list_amount_cents=90_000, credit_cents=0, total_usd_cents=90_000,
            fx_rate=Decimal("12650.5") if currency == "UZS" else None,
            fx_rate_date=date(2026, 10, 24) if currency == "UZS" else None,
            total_uzs=Decimal("11385450.00") if currency == "UZS" else None,
        )
        assert render_invoice_pdf(invoice, order).startswith(b"%PDF")


# ---- migration ------------------------------------------------------------------------------------

def test_b1_migration_is_additive_reversible_and_drift_free() -> None:
    from scripts import test_s0_5b4_baseline as support

    async def scenario() -> None:
        database = support.database_name("b1_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                for table in ("billing_customers", "terms_acceptances", "billing_orders", "billing_invoices",
                              "billing_payments", "billing_events", "billing_pilot_credits", "billing_fx_rates",
                              "billing_onboarding_tasks", "billing_invoice_counters"):
                    assert await connection.fetchval("SELECT to_regclass($1)", table), table
                for constraint, word in (("ck_admin_alert_kind", "BILLING"), ("ck_email_delivery_kind", "BILLING_INVOICE"),
                                         ("ck_email_delivery_category", "BILLING")):
                    assert word in await connection.fetchval(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname=$1", constraint)
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", P3_HEAD)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('billing_orders')") is None
                assert await connection.fetchval(
                    "SELECT count(*) FROM information_schema.columns WHERE table_name='organizations' "
                    "AND column_name='billing_status'") == 0
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


# ---- Postgres scenario ----------------------------------------------------------------------------

class FakePolar:
    """Stands in for the Polar sandbox API (the real sandbox run is scripts/billing/polar_sandbox_check.py)."""

    def __init__(self) -> None:
        self.checkouts: list[dict] = []
        self.discounts: list[dict] = []

    async def create_discount(self, **values) -> str:
        self.discounts.append(values)
        return f"disc_{len(self.discounts)}"

    async def create_checkout(self, **values) -> dict[str, str]:
        self.checkouts.append(values)
        number = len(self.checkouts)
        return {"id": f"chk_{number}", "url": f"https://sandbox.polar.sh/checkout/chk_{number}"}


def _request(body: bytes = b"", headers: dict[str, str] | None = None) -> Request:
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    raw = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    raw.append((b"user-agent", b"pytest-b1"))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw, "query_string": b"",
                    "client": ("203.0.113.7", 50000)}, receive)


async def _deliver(db, event_type: str, data: dict, *, event_id: str | None = None, signature: str | None = None):
    from app.api.endpoints import billing as endpoints

    event_id = event_id or f"msg_{uuid4().hex}"
    body = json.dumps({"type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(), "data": data}).encode()
    stamp = str(int(time.time()))
    headers = {"webhook-id": event_id, "webhook-timestamp": stamp,
               "webhook-signature": signature or billing_polar.sign(SECRET, event_id, stamp, body)}
    response = await endpoints.polar_webhook(_request(body, headers), db=db)
    return response.status_code, json.loads(response.body), event_id


def _polar_order(order, polar_id: str, *, amount: int | None = None, subscription_id: str | None = None,
                 refunded: int = 0, status: str = "paid") -> dict:
    return {
        "id": polar_id, "status": status, "paid": True, "total_amount": order.amount_cents if amount is None else amount,
        "refunded_amount": refunded, "currency": "usd", "subscription_id": subscription_id,
        "billing_reason": "subscription_create" if subscription_id else "purchase", "checkout_id": order.provider_checkout_id,
        "metadata": {"organization_id": str(order.organization_id), "order_id": str(order.id), "product": order.product},
    }


def test_postgres_card_bank_transfer_credit_refund_grace_and_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import test_s0_5b4_baseline as support
    from test_w2_organization_pursuit_foundation import W1_HEAD, _seed_w1
    from app.api.endpoints import billing as endpoints
    from app.core.config import settings
    from app.services import billing_fx

    fake = FakePolar()
    monkeypatch.setattr(billing_polar, "polar_client", lambda: fake)
    monkeypatch.setattr(endpoints, "kick_admin_alerts", lambda: None)
    monkeypatch.setattr(endpoints, "app_url", lambda: "https://app.plasma.test")

    async def cbu(currency, day):
        return Decimal("12650.50")

    monkeypatch.setattr(billing_fx, "fetch_cbu_rate", cbu)
    for name, value in {
        "POLAR_ACCESS_TOKEN": "polar_oat_sandbox_test", "POLAR_WEBHOOK_SECRET": SECRET, "POLAR_ENV": "sandbox",
        "POLAR_PRODUCT_IDS": json.dumps({"pilot": "prod_pilot", "pursuit_desk": "prod_desk", "extra_pursuit": "prod_extra"}),
        "INVOICE_BANK_DETAILS_UZS": "Bank: Test Bank | Account: 2020 8000 0000 0000 0001 | MFO: 00000",
        "INVOICE_BANK_DETAILS_USD": "Bank: Test Bank | SWIFT: TESTUZ22 | Account: 2020 8840 0000 0000 0001",
        "SMTP_HOST": "smtp.plasma.test", "SMTP_FROM": "billing@plasma.test",
        "BILLING_KICKOFF_URL": "https://cal.com/plasmahq/30min",
    }.items():
        monkeypatch.setattr(settings, name, value)

    async def scenario() -> None:
        database = support.database_name("b1_billing")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                for key in ("a", "b"):
                    ids[f"org_{key}"] = await connection.fetchval(
                        "SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids[f"profile_{key}"])
                ids["admin"] = uuid4()
                await connection.execute(
                    "INSERT INTO users(id,google_id,email,name,subscription_tier,is_admin,approval_status,platform_role,"
                    "auth_version) VALUES ($1,$2,'admin@plasma.invalid','Plasma Admin','SCOUT',true,'approved','admin',0)",
                    ids["admin"], f"b1-admin-{ids['admin']}")
            finally:
                await connection.close()
            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                await _to_explore(sessions, ids)
                await _card_pilot(sessions, ids, fake, monkeypatch)
                await _desk_credit_subscription_refund(sessions, ids, fake)
                await _bank_transfer_grace_and_mark_paid(sessions, ids)
                await _isolation_and_admin(sessions, ids)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _to_explore(sessions, ids) -> None:
    from app.models.tenancy import Organization
    from app.services.organization_access import set_organization_access

    async with sessions() as db:
        for key in ("a", "b"):
            organization = await db.get(Organization, ids[f"org_{key}"], with_for_update=True)
            await set_organization_access(db, organization=organization, state="explore", plan="explore",
                                          actor_user=None, actor_label="test")
        await db.commit()


async def _user(db, ids, key):
    from app.models.user import User

    return await db.get(User, ids[key], populate_existing=True)


async def _checkout(db, ids, user_key, organization_key, product, method, *, accept=True, sha=None):
    from app.api.endpoints import billing as endpoints
    from app.schemas.billing import CheckoutRequest

    current = terms()
    return await endpoints.billing_checkout(
        CheckoutRequest(product=product, method=method, terms_version=current["version"],
                        terms_sha256=sha or current["sha256"], accept_terms=accept),
        _request(), x_organization_id=ids[f"org_{organization_key}"], current_user=await _user(db, ids, user_key), db=db)


async def _card_pilot(sessions, ids, fake, monkeypatch) -> None:
    from app.api.endpoints import billing as endpoints
    from app.models.admin_alerts import AdminAlert
    from app.models.audit import AdminActivityEvent
    from app.models.billing import BillingEvent, BillingOrder, BillingPayment, OnboardingTask, TermsAcceptance
    from app.models.email import EmailDelivery
    from app.models.tenancy import Organization
    from app.schemas.billing import BillingCustomerIn
    from app.services import billing as service

    today = billing_today()
    async with sessions() as db:
        user_a = await _user(db, ids, "user_a")
        # An Explore organization can open billing; company details first (a non-resident buyer).
        with pytest.raises(HTTPException) as invalid:
            await endpoints.save_billing_customer(
                BillingCustomerIn(legal_name="Alpha Advisory LLP", country="UZ", address="1 Main Street, Tashkent",
                                  billing_email="billing@alpha.invalid", resident=True, tin="12"),
                x_organization_id=ids["org_a"], current_user=user_a, db=db)
        assert invalid.value.status_code == 422 and invalid.value.detail["code"] == "customer_invalid"
        await endpoints.save_billing_customer(
            BillingCustomerIn(legal_name="Alpha Advisory LLP", country="GB", address="1 Main Street, London",
                              billing_email="Billing@Alpha.invalid", resident=False),
            x_organization_id=ids["org_a"], current_user=await _user(db, ids, "user_a"), db=db)

        # Terms: not accepted, or a different text, refuses the checkout and stores nothing.
        with pytest.raises(HTTPException) as refused:
            await _checkout(db, ids, "user_a", "a", "pilot", "card", accept=False)
        assert refused.value.detail["code"] == "terms_not_accepted"
        with pytest.raises(HTTPException) as changed:
            await _checkout(db, ids, "user_a", "a", "pilot", "card", sha="0" * 64)
        assert changed.value.status_code == 409 and changed.value.detail["code"] == "terms_changed"
        assert await db.scalar(select(func.count(TermsAcceptance.id))) == 0
        with pytest.raises(HTTPException) as no_extra:
            await _checkout(db, ids, "user_a", "a", "extra_pursuit", "card")
        assert no_extra.value.detail["code"] == "plan_required"

        started = await _checkout(db, ids, "user_a", "a", "pilot", "card")
        assert started.checkout_url == "https://sandbox.polar.sh/checkout/chk_1" and started.status == "pending"
        sent = fake.checkouts[-1]
        assert sent["product_id"] == "prod_pilot" and sent["discount_id"] is None
        assert sent["metadata"] == {"organization_id": str(ids["org_a"]), "order_id": str(started.order_id), "product": "pilot"}
        assert sent["success_url"].startswith("https://app.plasma.test/dashboard/billing/success?checkout_id=")
        acceptance = await db.scalar(select(TermsAcceptance))
        assert (acceptance.terms_version, acceptance.text_sha256, acceptance.user_id, acceptance.ip_address,
                acceptance.organization_id) == ("PILOT_TERMS_v1", terms()["sha256"], ids["user_a"], "203.0.113.7", ids["org_a"])
        order = await db.get(BillingOrder, started.order_id)
        assert order.terms_acceptance_id == acceptance.id and order.amount_cents == 90_000
        assert (await db.get(Organization, ids["org_a"], populate_existing=True)).plan == "explore"  # not paid yet

        paid = _polar_order(order, "polar_ord_1")  # built now: a refused delivery rolls the session back

        # A forged delivery is refused and stores nothing.
        status, body, _ = await _deliver(db, "order.paid", paid, signature="v1,Zm9yZ2Vk")
        assert status == 403 and body["detail"] == "webhook_signature_invalid"
        assert await db.scalar(select(func.count(BillingEvent.id))) == 0

        # A processing failure keeps the delivery unprocessed; Polar's retry processes it.
        async def boom(*args, **kwargs):
            raise RuntimeError("database hiccup")

        with monkeypatch.context() as patch:
            patch.setattr(service, "_on_order_paid", boom)
            status, body, event_id = await _deliver(db, "order.paid", paid)
        assert status == 500
        failed = await db.scalar(select(BillingEvent).where(BillingEvent.provider_event_id == event_id))
        assert failed.processed_at is None and failed.processing_error == "RuntimeError" and failed.signature_verified

        status, body, _ = await _deliver(db, "order.paid", paid, event_id=event_id)
        assert status == 202 and body == {"status": "processed", "event_id": event_id, "outcome": "activated"}
        organization = await db.get(Organization, ids["org_a"], populate_existing=True)
        assert (organization.plan, organization.access_state, organization.billing_status) == ("pilot", "pilot", "paid")
        assert (organization.plan_started_on, organization.plan_ends_on) == (today, add_months(today, 3))
        assert (organization.pursuit_limit_override, organization.introduction_limit_override) == (None, None)

        # Idempotent: the same delivery again, and the same Polar order under another event id.
        status, body, _ = await _deliver(db, "order.paid", paid, event_id=event_id)
        assert status == 202 and body["status"] == "duplicate"
        status, body, _ = await _deliver(db, "order.paid", paid)
        assert body["outcome"] == "duplicate_payment"
        assert await db.scalar(select(func.count(BillingPayment.id)).where(BillingPayment.order_id == started.order_id)) == 1
        stored = await db.scalar(select(BillingEvent).where(BillingEvent.provider_event_id == event_id))
        assert stored.attempts == 2 and stored.organization_id == ids["org_a"] and stored.payload["type"] == "order.paid"

        # Side effects: one onboarding task, one welcome e-mail with the kickoff link, one team alert.
        assert await db.scalar(select(func.count(OnboardingTask.id)).where(OnboardingTask.organization_id == ids["org_a"])) == 1
        welcome = (await db.scalars(select(EmailDelivery).where(EmailDelivery.kind == "BILLING_WELCOME"))).all()
        assert len(welcome) == 1 and welcome[0].recipient_email == "billing@alpha.invalid"
        assert welcome[0].payload["kickoff_url"] == "https://cal.com/plasmahq/30min"
        alerts = (await db.scalars(select(AdminAlert).where(AdminAlert.kind == "BILLING"))).all()
        assert [alert.payload["event"] for alert in alerts] == ["activated"]
        from app.services.admin_alerts import render_alert
        subject, lines = render_alert(alerts[0])
        assert "bought Pilot (card)" in subject and any("onboarding task" in line for line in lines)
        actions = set((await db.scalars(select(AdminActivityEvent.action).where(
            AdminActivityEvent.metadata_json["organization_id"].astext == str(ids["org_a"])))).all())
        assert {"BILLING_CUSTOMER_UPDATED", "BILLING_TERMS_ACCEPTED", "BILLING_ORDER_CREATED",
                "BILLING_PAYMENT_RECORDED", "BILLING_PLAN_ACTIVATED"} <= actions
        assert await db.scalar(select(func.count(AdminActivityEvent.id)).where(
            AdminActivityEvent.action == "ORGANIZATION_ACCESS_CHANGED", AdminActivityEvent.source == "BILLING",
            AdminActivityEvent.target_resource_id == str(ids["org_a"]))) == 1

        # A second pilot is refused; the success page finds the order by its checkout id.
        with pytest.raises(HTTPException) as again:
            await _checkout(db, ids, "user_a", "a", "pilot", "card")
        assert again.value.detail["code"] == "pilot_used"
        found = await endpoints.billing_order_by_checkout(
            checkout_id="chk_1", x_organization_id=ids["org_a"], current_user=await _user(db, ids, "user_a"), db=db)
        assert found.order.status == "paid" and found.plan == "pilot"


async def _desk_credit_subscription_refund(sessions, ids, fake) -> None:
    from app.api.endpoints import billing as endpoints
    from app.models.billing import BillingOrder, PilotCreditRedemption
    from app.models.tenancy import Organization

    async with sessions() as db:
        quote = await endpoints.billing_quote(product="pursuit_desk", x_organization_id=ids["org_a"],
                                              current_user=await _user(db, ids, "user_a"), db=db)
        assert (quote.list_amount_cents, quote.credit_cents, quote.amount_cents) == (600_000, 90_000, 510_000)
        started = await _checkout(db, ids, "user_a", "a", "pursuit_desk", "card")
        assert fake.discounts[-1]["amount_cents"] == 90_000 and fake.discounts[-1]["product_id"] == "prod_desk"
        assert fake.checkouts[-1]["discount_id"] == "disc_1"
        order = await db.get(BillingOrder, started.order_id)
        assert (order.credit_cents, order.amount_cents, order.provider_discount_id) == (90_000, 510_000, "disc_1")

        status, body, _ = await _deliver(db, "order.paid", _polar_order(order, "polar_ord_2", subscription_id="sub_1"))
        assert body["outcome"] == "activated"
        organization = await db.get(Organization, ids["org_a"], populate_existing=True)
        today = billing_today()
        assert (organization.plan, organization.access_state, organization.plan_ends_on) == (
            "pursuit_desk", "paid", add_months(today, 12))
        assert await db.scalar(select(func.count(PilotCreditRedemption.id))) == 1
        # The credit is applied once: no credit on a later quote.
        later = await endpoints.billing_quote(product="pursuit_desk", x_organization_id=ids["org_a"],
                                              current_user=await _user(db, ids, "user_a"), db=db)
        assert later.credit_cents == 0 and later.blocker == "already_on_plan"

        # Subscription: canceled (to the period end) keeps the plan; resumed; a renewal extends the year.
        status, body, _ = await _deliver(db, "subscription.canceled", {"id": "sub_1", "status": "active",
                                                                         "metadata": {"order_id": str(order.id)}})
        organization = await db.get(Organization, ids["org_a"], populate_existing=True)
        assert body["outcome"] == "subscription_canceled" and (organization.plan, organization.billing_status) == (
            "pursuit_desk", "canceled")
        status, body, _ = await _deliver(db, "subscription.uncanceled", {"id": "sub_1", "status": "active"})
        assert (await db.get(Organization, ids["org_a"], populate_existing=True)).billing_status == "paid"
        renewal = _polar_order(order, "polar_ord_3", amount=600_000, subscription_id="sub_1")
        renewal["billing_reason"] = "subscription_cycle"
        status, body, _ = await _deliver(db, "order.paid", renewal)
        organization = await db.get(Organization, ids["org_a"], populate_existing=True)
        assert body["outcome"] == "renewed" and organization.plan_ends_on == add_months(today, 24)

        # A full refund of the annual order returns the organization to Explore; the credit comes back.
        status, body, _ = await _deliver(db, "order.refunded", _polar_order(order, "polar_ord_2", refunded=510_000,
                                                                            status="refunded"))
        organization = await db.get(Organization, ids["org_a"], populate_existing=True)
        assert body["outcome"] == "refunded"
        assert (organization.plan, organization.access_state, organization.billing_status) == ("explore", "explore", "refunded")
        assert (await db.get(BillingOrder, order.id, populate_existing=True)).status == "refunded"
        assert await db.scalar(select(func.count(PilotCreditRedemption.id))) == 0
        status, body, _ = await _deliver(db, "order.refunded", _polar_order(order, "polar_ord_2", refunded=510_000,
                                                                            status="refunded"))
        assert body["outcome"] == "duplicate_refund"


async def _bank_transfer_grace_and_mark_paid(sessions, ids) -> None:
    from app.api.endpoints import billing as endpoints
    from app.models.billing import BillingInvoice, BillingOrder, BillingPayment
    from app.models.email import EmailDelivery
    from app.models.tenancy import Organization
    from app.schemas.billing import BillingCustomerIn, MarkPaidRequest
    from app.services.billing import billing_summary, run_billing_schedule
    from app.services.email_notifications import attachments_for, build_message
    from app.services.plans import plan_status

    today = billing_today()
    async with sessions() as db:
        await endpoints.save_billing_customer(
            BillingCustomerIn(legal_name="Bravo Muhandislik MChJ", country="UZ", address="Chilonzor 5, Tashkent",
                              billing_email="buh@bravo.invalid", resident=True, tin="301 234 567"),
            x_organization_id=ids["org_b"], current_user=await _user(db, ids, "user_b"), db=db)
        started = await _checkout(db, ids, "user_b", "b", "pilot", "bank_transfer")
        assert started.checkout_url is None and started.status == "awaiting_payment"
        assert started.invoice_number == f"PL-{today.year}-001"
        invoice = await db.get(BillingInvoice, started.invoice_id)
        assert (invoice.currency, invoice.fx_rate, invoice.total_uzs, invoice.fx_rate_date) == (
            "UZS", Decimal("12650.5000"), Decimal("11385450.00"), today)
        assert invoice.customer["tin"] == "301234567" and invoice.due_on == today + timedelta(days=10)
        # Active at once, awaiting payment.
        organization = await db.get(Organization, ids["org_b"], populate_existing=True)
        assert (organization.plan, organization.access_state, organization.billing_status) == ("pilot", "pilot", "awaiting_payment")

        # The invoice e-mail carries the PDF, rendered at send time.
        delivery = await db.scalar(select(EmailDelivery).where(EmailDelivery.kind == "BILLING_INVOICE"))
        assert delivery.recipient_email == "buh@bravo.invalid" and delivery.category == "BILLING"
        files = await attachments_for(db, delivery)
        assert files[0][0] == f"{invoice.number}.pdf" and files[0][1].startswith(b"%PDF")
        message = build_message(delivery, link_base="https://app.plasma.test", attachments=files)
        assert [part.get_filename() for part in message.iter_attachments()] == [f"{invoice.number}.pdf"]
        assert "UZS 11 385 450.00" in message.get_body(("plain",)).get_content()

        # Grace: reminders on days 3 and 6 (once each), Explore on day 10.
        assert await run_billing_schedule(db, today=today + timedelta(days=2)) == {"reminders": 0, "suspended": 0}
        assert await run_billing_schedule(db, today=today + timedelta(days=3)) == {"reminders": 1, "suspended": 0}
        assert await run_billing_schedule(db, today=today + timedelta(days=4)) == {"reminders": 0, "suspended": 0}
        assert await run_billing_schedule(db, today=today + timedelta(days=6)) == {"reminders": 1, "suspended": 0}
        assert await run_billing_schedule(db, today=today + timedelta(days=9)) == {"reminders": 0, "suspended": 0}
        await db.commit()
        reminders = (await db.scalars(select(EmailDelivery).where(EmailDelivery.kind == "BILLING_REMINDER")
                                      .order_by(EmailDelivery.created_at))).all()
        assert [row.payload["day"] for row in reminders] == [3, 6]
        assert (await db.get(Organization, ids["org_b"], populate_existing=True)).plan == "pilot"
        assert await run_billing_schedule(db, today=today + timedelta(days=10)) == {"reminders": 0, "suspended": 1}
        await db.commit()
        organization = await db.get(Organization, ids["org_b"], populate_existing=True)
        assert (organization.plan, organization.access_state, organization.billing_status) == ("explore", "explore", "suspended")
        order = await db.get(BillingOrder, started.order_id, populate_existing=True)
        invoice = await db.get(BillingInvoice, started.invoice_id, populate_existing=True)
        assert (order.status, invoice.status) == ("lapsed", "overdue")
        assert await db.scalar(select(func.count(EmailDelivery.id)).where(EmailDelivery.kind == "BILLING_SUSPENDED")) == 1
        # The in-app notice: the plan endpoint carries the billing status and the open invoice.
        summary = await billing_summary(db, organization, today=today + timedelta(days=10))
        assert summary["status"] == "suspended" and summary["open_invoice"]["number"] == invoice.number
        assert await run_billing_schedule(db, today=today + timedelta(days=11)) == {"reminders": 0, "suspended": 0}

        # An admin marks it paid with the bank reference: the pilot comes back with its dates.
        invoice_id, invoice_number = invoice.id, invoice.number  # a refused request rolls the session back
        with pytest.raises(HTTPException) as blank:
            await endpoints.admin_mark_paid(invoice_id, MarkPaidRequest(reference="   "),
                                            current_user=await _user(db, ids, "admin"), db=db)
        assert blank.value.detail["code"] == "reference_required"
        detail = await endpoints.admin_mark_paid(
            invoice_id, MarkPaidRequest(reference="KAPITALBANK 000123", note="Paid on day 11"),
            current_user=await _user(db, ids, "admin"), db=db)
        organization = await db.get(Organization, ids["org_b"], populate_existing=True)
        assert (organization.plan, organization.billing_status, organization.plan_started_on, organization.plan_ends_on) == (
            "pilot", "paid", today, add_months(today, 3))
        payment = await db.scalar(select(BillingPayment).where(BillingPayment.invoice_id == invoice_id))
        assert (payment.reference, payment.method, payment.recorded_by_user_id) == ("KAPITALBANK 000123", "bank_transfer", ids["admin"])
        assert detail.invoices[0].status == "paid"
        with pytest.raises(HTTPException) as twice:
            await endpoints.admin_mark_paid(invoice_id, MarkPaidRequest(reference="KAPITALBANK 000123"),
                                            current_user=await _user(db, ids, "admin"), db=db)
        assert twice.value.status_code == 409

        # Extra pursuit (bank transfer): invoice 002, +1 pursuit at once.
        extra = await _checkout(db, ids, "user_b", "b", "extra_pursuit", "bank_transfer")
        assert extra.invoice_number == f"PL-{today.year}-002"
        status = await plan_status(db, await db.get(Organization, ids["org_b"], populate_existing=True))
        assert (status["pursuits"]["limit"], status["pursuits"]["extra_granted"]) == (7, 1)

        # Day 75 of the pilot: the Pursuit Desk offer with the $900 credit.
        organization = await db.get(Organization, ids["org_b"], populate_existing=True)
        organization.plan_started_on = today - timedelta(days=75)
        await db.commit()
        summary = await billing_summary(db, organization, today=today)
        assert summary["annual_offer"] == {"product": "pursuit_desk", "list_amount_cents": 600_000, "credit_cents": 90_000,
                                           "pilot_ends_on": organization.plan_ends_on, "day": 75}
        assert (await billing_summary(db, organization, today=today - timedelta(days=1)))["annual_offer"] is None


async def _isolation_and_admin(sessions, ids) -> None:
    from app.api.endpoints import billing as endpoints
    from app.models.billing import BillingInvoice, BillingOrder, OnboardingTask
    from app.schemas.billing import BillingOverrideRequest, OnboardingDoneRequest

    async with sessions() as db:
        order_a = await db.scalar(select(BillingOrder).where(BillingOrder.organization_id == ids["org_a"]).limit(1))
        invoice_b = await db.scalar(select(BillingInvoice).where(BillingInvoice.organization_id == ids["org_b"]).limit(1))
        user_a, user_b = await _user(db, ids, "user_a"), await _user(db, ids, "user_b")
        for call in (
            endpoints.billing_order(order_a.id, x_organization_id=ids["org_b"], current_user=user_b, db=db),
            endpoints.billing_invoice_pdf(invoice_b.id, x_organization_id=ids["org_a"], current_user=user_a, db=db),
            endpoints.billing_overview(x_organization_id=ids["org_b"], current_user=user_a, db=db),
            endpoints.billing_order_by_checkout(checkout_id="chk_1", x_organization_id=ids["org_b"], current_user=user_b, db=db),
        ):
            with pytest.raises(HTTPException) as hidden:
                await call
            assert hidden.value.status_code == 404
        overview_b = await endpoints.billing_overview(x_organization_id=ids["org_b"], current_user=user_b, db=db)
        assert {row.organization_id for row in [overview_b]} == {ids["org_b"]}
        assert all(order.id != order_a.id for order in overview_b.orders)
        pdf = await endpoints.billing_invoice_pdf(invoice_b.id, x_organization_id=ids["org_b"], current_user=user_b, db=db)
        assert pdf.body.startswith(b"%PDF") and invoice_b.number in pdf.headers["content-disposition"]

        # Admin console: customers, detail (terms, events, audit), onboarding, a manual override.
        customers = await endpoints.admin_billing_customers(db=db)
        assert {row.organization_id for row in customers} == {ids["org_a"], ids["org_b"]}
        detail = await endpoints.admin_billing_detail(ids["org_a"], db=db)
        assert detail.terms_acceptances and detail.terms_acceptances[0]["ip_address"] == "203.0.113.7"
        assert {event["outcome"] for event in detail.events} >= {"activated", "refunded", "renewed"}
        assert any(row["action"] == "BILLING_PLAN_ACTIVATED" for row in detail.audit)
        admin = await _user(db, ids, "admin")
        task = await db.scalar(select(OnboardingTask).where(OnboardingTask.organization_id == ids["org_b"]))
        queue = await endpoints.admin_onboarding_done(task.id, OnboardingDoneRequest(note="Kickoff booked"),
                                                      current_user=admin, db=db)
        assert any(row.id == task.id and row.status == "done" for row in queue)
        detail = await endpoints.admin_override(
            ids["org_a"], BillingOverrideRequest(plan="agent", billing_status="paid", reason="Signed Agent agreement"),
            current_user=admin, db=db)
        assert (detail.plan, detail.billing_status) == ("agent", "paid")
        assert any(row["action"] == "BILLING_STATUS_CHANGED" for row in detail.audit)
