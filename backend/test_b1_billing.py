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
        "extra_pursuit": (None, 20_000, None, 1), "per_tender": ("per_tender", 40_000, None, 0),
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


def test_polar_env_switch_both_ways(monkeypatch: pytest.MonkeyPatch) -> None:
    """RC-5: production Polar only in a production environment and only with its keys; the API base follows."""
    from app.core.config import Settings, settings

    release = dict(POSTGRES_SERVER="x", POSTGRES_USER="x", POSTGRES_PASSWORD="x", POSTGRES_DB="x",
                   SECRET_KEY="s" * 40, AUTH_BRIDGE_SECRET="b" * 40, TELEGRAM_BOT_TOKEN="x",
                   ENVIRONMENT="production", BACKEND_CORS_ORIGINS=["https://app.example.com"], _env_file=None)
    assert Settings(**release).POLAR_ENV == "sandbox"  # production may still use the sandbox
    with pytest.raises(ValueError, match="requires POLAR_ACCESS_TOKEN"):  # explicit None: the gate's environment has keys
        Settings(**release, POLAR_ENV="production", POLAR_ACCESS_TOKEN=None, POLAR_WEBHOOK_SECRET=None, POLAR_PRODUCT_IDS=None)
    live = Settings(**release, POLAR_ENV="production", POLAR_ACCESS_TOKEN="polar_oat_live",
                    POLAR_WEBHOOK_SECRET="whsec_live", POLAR_PRODUCT_IDS='{"pilot": "p"}')
    assert live.POLAR_ENV == "production"
    monkeypatch.setattr(settings, "POLAR_ENV", "production")
    assert billing_polar.api_base() == "https://api.polar.sh"
    monkeypatch.setattr(settings, "POLAR_ENV", "sandbox")
    assert billing_polar.api_base() == "https://sandbox-api.polar.sh"


def test_polar_checkout_body_allows_codes_unless_the_credit_applies() -> None:
    """A team code (the owner's one-use 100% live-test code) can be entered unless the pilot credit is preset."""
    import httpx

    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "chk", "url": "https://polar.test/chk"})

    client = billing_polar.PolarClient(token="polar_oat_test", transport=httpx.MockTransport(handler))
    for discount in (None, "disc_1"):
        asyncio.run(client.create_checkout(
            product_id="prod", success_url="https://app.test/s", metadata={}, customer_email="a@firm.uz",
            external_customer_id="org", customer_name="Firm", country="UZ", discount_id=discount))
    assert [body["allow_discount_codes"] for body in bodies] == [True, False]
    assert "customer_tax_id" not in bodies[0] and bodies[1]["discount_id"] == "disc_1"


def test_webhook_route_is_public_and_signature_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    """RC-5: POST /api/v1/billing/webhooks/polar needs no session; an unsigned or forged call gets 403."""
    import httpx
    from app.core.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "POLAR_WEBHOOK_SECRET", SECRET)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client:
            forged = await client.post("/api/v1/billing/webhooks/polar", content=b'{"type":"order.paid","data":{}}',
                                       headers={"webhook-id": "msg_x", "webhook-timestamp": str(int(time.time())),
                                                "webhook-signature": "v1,Zm9yZ2Vk", "content-type": "application/json"})
            assert forged.status_code == 403 and forged.json() == {"detail": "webhook_signature_invalid"}
            unsigned = await client.post("/api/v1/billing/webhooks/polar", content=b"{}")
            assert unsigned.status_code == 403 and unsigned.json() == {"detail": "webhook_headers_missing"}
            assert (await client.get("/api/v1/billing/webhooks/polar")).status_code == 405

    asyncio.run(scenario())


def test_deploy5_pilot_end_dates_plan() -> None:
    """The data step: pilot_setup.py pilots get start + 3 months; others are listed; ends flagged."""
    from scripts.deploy5_pilot_end_dates import PROFILE_MARKER, plan_rows

    today = date(2026, 10, 26)
    org = lambda start, end, name: SimpleNamespace(id=uuid4(), display_name=name, plan_started_on=start, plan_ends_on=end)
    profile = lambda ours: SimpleNamespace(notes=f"{PROFILE_MARKER} {{}}" if ours else "approved by hand")
    rows = plan_rows([
        (org(date(2026, 10, 20), None, "A"), profile(True)),
        (org(date(2026, 9, 1), date(2026, 12, 1), "B"), profile(True)),
        (org(date(2026, 7, 1), date(2027, 7, 1), "C"), profile(True)),
        (org(None, None, "D"), profile(True)),
        (org(date(2026, 1, 5), date(2026, 4, 5), "E"), profile(False)),
    ], today)
    assert [(row["name"], row["action"], row["proposed_ends_on"], row["ends_at_first_run"]) for row in rows] == [
        ("A", "set", "2027-01-20", False), ("B", "keep", "2026-12-01", False), ("C", "set", "2026-10-01", True),
        ("D", "no_start_date", None, False), ("E", "listed_only", None, True),
    ]


def test_deploy51_reconcile_matches_only_a_paid_polar_order_of_this_order() -> None:
    """Never activate what Polar does not show as paid, or what belongs to another order."""
    from scripts.billing.reconcile_polar import match_polar

    mine, other = str(uuid4()), str(uuid4())
    checkout = {"id": "chk", "status": "succeeded", "metadata": {"order_id": mine}}
    paid = {"id": "po_1", "status": "paid", "paid": True, "checkout_id": "chk", "metadata": {"order_id": mine}}
    assert match_polar(mine, "chk", checkout, [paid]) == ("paid", paid, None)
    assert match_polar(mine, "chk", {**checkout, "metadata": {}}, [{**paid, "metadata": {}}])[0] == "paid"  # by checkout id
    assert match_polar(mine, "chk", {**checkout, "status": "open"}, [])[0] == "not_paid"
    assert match_polar(mine, "chk", checkout, [{**paid, "status": "pending", "paid": False}])[0] == "not_paid"
    assert match_polar(mine, "chk", checkout, [{**paid, "status": "void", "paid": False}])[0] == "not_paid"
    assert match_polar(mine, "chk", checkout, [{**paid, "status": "paid", "paid": False}])[0] == "not_paid"
    assert match_polar(mine, "chk", checkout, [{**paid, "status": "refunded"}])[0] == "needs_review"
    assert match_polar(mine, "chk", checkout, [paid, {**paid, "id": "po_2"}])[0] == "needs_review"
    assert match_polar(mine, "chk", {**checkout, "metadata": {"order_id": other}}, [paid])[0] == "mismatch"
    assert match_polar(mine, "chk", checkout, [{**paid, "metadata": {"order_id": other}}])[0] == "mismatch"


def test_deploy51_override_default_dates() -> None:
    from app.services.billing import default_plan_dates

    day = date(2026, 10, 30)
    assert default_plan_dates("pilot", day) == (day, date(2027, 1, 30))
    for plan in ("pursuit_desk", "agent", "enterprise"):
        assert default_plan_dates(plan, day) == (day, date(2027, 10, 30))
    assert default_plan_dates("per_tender", day) == (day, None)
    assert default_plan_dates("explore", day) == (None, None)


def test_terms_text_is_the_docs_copy_and_hashed_with_lf() -> None:
    root = Path(__file__).resolve().parents[1]
    docs = (root / "docs" / "legal" / "PILOT_TERMS_v1.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    current = terms()
    assert current["markdown"] == docs and current["version"] == "PILOT_TERMS_v1"
    assert current["sha256"] == hashlib.sha256(docs.encode()).hexdigest()
    # The owner-approved Plasma Pilot and Subscription Terms, version 1, effective 26 Oct 2026, and its PDF.
    assert docs.startswith("# Plasma Pilot and Subscription Terms\n\n**Version 1 · effective 26 October 2026**")
    for clause in ("Payment is due within 7 days", "still unpaid 10 days after it was issued",
                   "within 30 days after the Pilot ends", "within 30 days of activation",
                   "Pursuit Desk renews for another year", "6 pursuits", "1 partner or expert introduction"):
        assert clause in docs, clause
    pdf = (root / "docs" / "legal" / "PILOT_TERMS_v1.pdf").read_bytes()
    from app.services.billing import TERMS_PDF_PATH
    assert pdf.startswith(b"%PDF") and TERMS_PDF_PATH.read_bytes() == pdf


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
        pdf = render_invoice_pdf(invoice, order)
        assert pdf.startswith(b"%PDF")
        import fitz
        document = fitz.open(stream=pdf, filetype="pdf")
        text = " ".join(page.get_text() for page in document)
        assert "Payment invoice (proforma) PL-2026-001" in text
        assert "The official electronic invoice is issued after payment." in text
        assert "Payment is due within 7 days" in " ".join(text.split())


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
        # Deploy 5.1 reads (reconcile_polar.py): what Polar shows per checkout id.
        self.checkout_reads: dict[str, dict] = {}
        self.orders_by_checkout: dict[str, list[dict]] = {}
        self.subscriptions: dict[str, dict] = {}
        self.refuse_reads = False

    async def get_checkout(self, checkout_id: str) -> dict:
        if self.refuse_reads:
            raise billing_polar.PolarError("polar_http_403")
        return self.checkout_reads[checkout_id]

    async def list_orders(self, *, checkout_id: str) -> list[dict]:
        return self.orders_by_checkout.get(checkout_id, [])

    async def get_subscription(self, subscription_id: str) -> dict:
        return self.subscriptions[subscription_id]

    async def create_discount(self, **values) -> str:
        self.discounts.append(values)
        return f"disc_{len(self.discounts)}"

    async def create_checkout(self, **values) -> dict[str, str]:
        self.checkouts.append(values)
        number = len(self.checkouts)
        return {"id": f"chk_{number}", "url": f"https://sandbox.polar.sh/checkout/chk_{number}"}

    async def create_customer_portal_url(self, *, external_customer_id: str) -> str:
        return f"https://sandbox.polar.sh/portal/{external_customer_id}"


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
        "POLAR_PRODUCT_IDS": json.dumps({"pilot": "prod_pilot", "pursuit_desk": "prod_desk", "extra_pursuit": "prod_extra",
                                          "per_tender": "prod_per_tender"}),
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


async def _checkout(db, ids, user_key, organization_key, product, method, *, accept=True, sha=None, offer=None,
                    attribution=None):
    from app.api.endpoints import billing as endpoints
    from app.schemas.billing import CheckoutRequest

    current = terms()
    return await endpoints.billing_checkout(
        CheckoutRequest(product=product, method=method, terms_version=current["version"],
                        terms_sha256=sha or current["sha256"], accept_terms=accept, offer=offer,
                        attribution=attribution),
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

        # RC-5: no USD bank transfer until INVOICE_USD_ENABLED (non-residents: card only).
        from app.core.config import settings
        usd = await endpoints.billing_quote(product="pilot", offer=None, x_organization_id=ids["org_a"],
                                            current_user=await _user(db, ids, "user_a"), db=db)
        assert (usd.invoice_currency, usd.methods.card, usd.methods.bank_transfer) == ("USD", True, False)
        settings.INVOICE_USD_ENABLED = True
        try:
            usd = await endpoints.billing_quote(product="pilot", offer=None, x_organization_id=ids["org_a"],
                                                current_user=await _user(db, ids, "user_a"), db=db)
            assert usd.methods.bank_transfer is True
        finally:
            settings.INVOICE_USD_ENABLED = False

        started = await _checkout(db, ids, "user_a", "a", "pilot", "card", attribution={
            "ref": "landing-pricing", "utm_source": "linkedin", "utm_campaign": "pilot-oct", "evil": "x" * 500})
        assert started.checkout_url == "https://sandbox.polar.sh/checkout/chk_1" and started.status == "pending"
        sent = fake.checkouts[-1]
        assert sent["product_id"] == "prod_pilot" and sent["discount_id"] is None
        assert sent["metadata"] == {"organization_id": str(ids["org_a"]), "order_id": str(started.order_id), "product": "pilot"}
        assert sent["success_url"].startswith("https://app.plasma.test/dashboard/billing/success?checkout_id=")
        # Deploy 5.1: no order.paid 24 hours after the first card checkout → the admin console warns.
        health = await service.webhook_health(db)
        assert health["first_card_checkout_at"] is not None and health["pending_card_orders"] == 1
        assert health["warning"] is False  # not 24 hours yet
        later = health["first_card_checkout_at"] + timedelta(hours=24)
        assert (await service.webhook_health(db, now=later))["warning"] is True
        acceptance = await db.scalar(select(TermsAcceptance))
        assert (acceptance.terms_version, acceptance.text_sha256, acceptance.user_id, acceptance.ip_address,
                acceptance.organization_id) == ("PILOT_TERMS_v1", terms()["sha256"], ids["user_a"], "203.0.113.7", ids["org_a"])
        order = await db.get(BillingOrder, started.order_id)
        assert order.terms_acceptance_id == acceptance.id and order.amount_cents == 90_000
        assert order.attribution == {"ref": "landing-pricing", "utm_source": "linkedin", "utm_campaign": "pilot-oct"}
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
        health = await endpoints.admin_webhook_health(db=db)
        assert health.warning is False and health.last_order_paid_at is not None and health.pending_card_orders == 0
        assert (await service.webhook_health(db, now=later + timedelta(days=30)))["warning"] is False
        assert {row.event_type: row.count for row in health.events} == {"order.paid": 2}

        # Side effects: one onboarding task, one welcome e-mail with the kickoff link, one team alert.
        assert await db.scalar(select(func.count(OnboardingTask.id)).where(OnboardingTask.organization_id == ids["org_a"])) == 1
        welcome = (await db.scalars(select(EmailDelivery).where(EmailDelivery.kind == "BILLING_WELCOME"))).all()
        assert len(welcome) == 1 and welcome[0].recipient_email == "billing@alpha.invalid"
        assert welcome[0].payload["kickoff_url"] == "https://cal.com/plasmahq/30min"
        from app.services.email_notifications import attachments_for
        from app.services.billing import TERMS_PDF_NAME, TERMS_PDF_PATH
        attached = await attachments_for(db, welcome[0])
        assert attached == [(TERMS_PDF_NAME, TERMS_PDF_PATH.read_bytes(), "application/pdf")]
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
        quote = await endpoints.billing_quote(product="pursuit_desk", offer=None, x_organization_id=ids["org_a"],
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
        later = await endpoints.billing_quote(product="pursuit_desk", offer=None, x_organization_id=ids["org_a"],
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
        assert invoice.customer["tin"] == "301234567" and invoice.due_on == today + timedelta(days=7)
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
        assert await run_billing_schedule(db, today=today + timedelta(days=2)) == {"reminders": 0, "suspended": 0, "ended": 0, "renewed": 0}
        assert await run_billing_schedule(db, today=today + timedelta(days=3)) == {"reminders": 1, "suspended": 0, "ended": 0, "renewed": 0}
        assert await run_billing_schedule(db, today=today + timedelta(days=4)) == {"reminders": 0, "suspended": 0, "ended": 0, "renewed": 0}
        assert await run_billing_schedule(db, today=today + timedelta(days=6)) == {"reminders": 1, "suspended": 0, "ended": 0, "renewed": 0}
        assert await run_billing_schedule(db, today=today + timedelta(days=9)) == {"reminders": 0, "suspended": 0, "ended": 0, "renewed": 0}
        await db.commit()
        reminders = (await db.scalars(select(EmailDelivery).where(EmailDelivery.kind == "BILLING_REMINDER")
                                      .order_by(EmailDelivery.created_at))).all()
        assert [row.payload["day"] for row in reminders] == [3, 6]
        assert (await db.get(Organization, ids["org_b"], populate_existing=True)).plan == "pilot"
        assert await run_billing_schedule(db, today=today + timedelta(days=10)) == {"reminders": 0, "suspended": 1, "ended": 0, "renewed": 0}
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
        assert await run_billing_schedule(db, today=today + timedelta(days=11)) == {"reminders": 0, "suspended": 0, "ended": 0, "renewed": 0}

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

    await _credit_window_end_renewal_and_cancel(sessions, ids)


async def _credit_window_end_renewal_and_cancel(sessions, ids) -> None:
    from app.api.endpoints import billing as endpoints
    from app.models.billing import BillingInvoice, BillingOrder
    from app.models.tenancy import Organization
    from app.schemas.billing import BillingOverrideRequest, MarkPaidRequest
    from app.services.billing import pilot_credit_source, run_billing_schedule

    today = billing_today()
    async with sessions() as db:
        organization = await db.get(Organization, ids["org_b"], populate_existing=True)
        pilot_end = organization.plan_ends_on
        assert pilot_end == add_months(today, 3)
        # Terms §5: the credit only for an annual plan ordered within 30 days after the pilot ends.
        assert await pilot_credit_source(db, ids["org_b"], on=pilot_end + timedelta(days=30)) is not None
        assert await pilot_credit_source(db, ids["org_b"], on=pilot_end + timedelta(days=31)) is None
        # Terms §7: a Pilot ends after three months (no renewal): Explore.
        assert (await run_billing_schedule(db, today=pilot_end - timedelta(days=1)))["ended"] == 0
        counts = await run_billing_schedule(db, today=pilot_end)
        await db.commit()
        assert counts["ended"] == 1
        organization = await db.get(Organization, ids["org_b"], populate_existing=True)
        assert (organization.plan, organization.access_state, organization.billing_status) == ("explore", "explore", None)

        # Pursuit Desk by bank transfer, ordered within the window: the $900 credit, once.
        desk = await _checkout(db, ids, "user_b", "b", "pursuit_desk", "bank_transfer")
        invoice = await db.get(BillingInvoice, desk.invoice_id)
        assert (invoice.list_amount_cents, invoice.credit_cents, invoice.total_usd_cents) == (600_000, 90_000, 510_000)
        await endpoints.admin_mark_paid(invoice.id, MarkPaidRequest(reference="KAPITALBANK 000555"),
                                        current_user=await _user(db, ids, "admin"), db=db)
        organization = await db.get(Organization, ids["org_b"], populate_existing=True)
        desk_end = organization.plan_ends_on
        assert (organization.plan, organization.billing_status, desk_end) == ("pursuit_desk", "paid", add_months(today, 12))

        # Terms §7: Pursuit Desk renews yearly. By bank transfer: a renewal order and invoice on the renewal date,
        # the plan extended at once and awaiting payment; once only.
        assert (await run_billing_schedule(db, today=desk_end - timedelta(days=1)))["renewed"] == 0
        assert (await run_billing_schedule(db, today=desk_end))["renewed"] == 1
        assert (await run_billing_schedule(db, today=desk_end))["renewed"] == 0
        await db.commit()
        renewal = await db.scalar(select(BillingOrder).where(
            BillingOrder.organization_id == ids["org_b"], BillingOrder.renewal_of_order_id == desk.order_id))
        assert (renewal.status, renewal.amount_cents, renewal.credit_cents, renewal.plan_started_on, renewal.plan_ends_on) == (
            "awaiting_payment", 600_000, 0, desk_end, add_months(desk_end, 12))
        renewal_invoice = await db.scalar(select(BillingInvoice).where(BillingInvoice.order_id == renewal.id))
        assert (renewal_invoice.issued_on, renewal_invoice.due_on, renewal_invoice.total_usd_cents) == (
            desk_end, desk_end + timedelta(days=7), 600_000)
        organization = await db.get(Organization, ids["org_b"], populate_existing=True)
        assert (organization.plan, organization.billing_status, organization.plan_ends_on) == (
            "pursuit_desk", "awaiting_payment", add_months(desk_end, 12))

        # Canceled before the next renewal date: the plan ends there (Explore), no new invoice.
        await endpoints.admin_mark_paid(renewal_invoice.id, MarkPaidRequest(reference="KAPITALBANK 000777"),
                                        current_user=await _user(db, ids, "admin"), db=db)
        # RC-5: the customer asks (Cancel renewal), the team confirms; both audited, the team alerted.
        with pytest.raises(HTTPException) as early:
            await endpoints.admin_confirm_cancel(renewal.id, current_user=await _user(db, ids, "admin"), db=db)
        assert early.value.detail["code"] == "cancel_not_requested"
        overview = await endpoints.billing_cancel_renewal(x_organization_id=ids["org_b"],
                                                          current_user=await _user(db, ids, "user_b"), db=db)
        assert overview.summary.renewal.cancel_requested_at is not None and overview.summary.renewal.canceled is False
        with pytest.raises(HTTPException) as twice:
            await endpoints.billing_cancel_renewal(x_organization_id=ids["org_b"],
                                                   current_user=await _user(db, ids, "user_b"), db=db)
        assert twice.value.detail["code"] == "cancel_requested"
        customers = await endpoints.admin_billing_customers(db=db)
        assert next(row for row in customers if row.organization_id == ids["org_b"]).cancel_requested is True
        detail = await endpoints.admin_confirm_cancel(renewal.id, current_user=await _user(db, ids, "admin"), db=db)
        assert detail.billing_status == "canceled"
        assert {"BILLING_CANCEL_REQUESTED", "BILLING_CANCEL_CONFIRMED"} <= {row["action"] for row in detail.audit}
        from app.models.admin_alerts import AdminAlert
        assert await db.scalar(select(func.count(AdminAlert.id)).where(
            AdminAlert.kind == "BILLING", AdminAlert.payload["event"].astext == "cancel_requested")) == 1
        counts = await run_billing_schedule(db, today=add_months(desk_end, 12))
        await db.commit()
        assert (counts["ended"], counts["renewed"]) == (1, 0)
        organization = await db.get(Organization, ids["org_b"], populate_existing=True)
        assert (organization.plan, organization.billing_status) == ("explore", "canceled")


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

    await _portal_per_tender_and_pilot_without_order(sessions, ids)


async def _portal_per_tender_and_pilot_without_order(sessions, ids) -> None:
    from app.api.endpoints import billing as endpoints
    from app.models.billing import BillingOrder, TermsAcceptance
    from app.models.tenancy import Organization
    from app.schemas.billing import AdminInvoiceRequest, BillingOverrideRequest, OfferCreateRequest
    from app.services.billing import run_billing_schedule

    async with sessions() as db:
        # Card customers get Polar's customer portal; a bank-only customer is refused.
        portal = await endpoints.billing_portal(x_organization_id=ids["org_a"], current_user=await _user(db, ids, "user_a"), db=db)
        assert portal.url == f"https://sandbox.polar.sh/portal/{ids['org_a']}"
        with pytest.raises(HTTPException) as bank_only:
            await endpoints.billing_portal(x_organization_id=ids["org_b"], current_user=await _user(db, ids, "user_b"), db=db)
        assert bank_only.value.detail["code"] == "not_card_customer"

        # Per-tender review: not self-serve; an admin's one-use link, then the usual checkout.
        quote = await endpoints.billing_quote(product="per_tender", offer=None, x_organization_id=ids["org_b"],
                                              current_user=await _user(db, ids, "user_b"), db=db)
        assert quote.blocker == "offer_required" and quote.amount_cents == 40_000
        with pytest.raises(HTTPException) as no_offer:
            await _checkout(db, ids, "user_b", "b", "per_tender", "card")
        assert no_offer.value.detail["code"] == "offer_required"
        made = await endpoints.admin_create_offer(ids["org_b"], OfferCreateRequest(product="per_tender", note="Tender X"),
                                                  current_user=await _user(db, ids, "admin"), db=db)
        token = made.url.split("offer=")[1]
        assert made.url.startswith("https://app.plasma.test/billing/start?plan=per_tender&offer=")
        quote = await endpoints.billing_quote(product="per_tender", offer=token, x_organization_id=ids["org_b"],
                                              current_user=await _user(db, ids, "user_b"), db=db)
        assert quote.blocker is None
        other = await endpoints.billing_quote(product="per_tender", offer=token, x_organization_id=ids["org_a"],
                                              current_user=await _user(db, ids, "user_a"), db=db)
        assert other.blocker == "offer_required"  # the link is bound to its organization
        started = await _checkout(db, ids, "user_b", "b", "per_tender", "card", offer=token)
        order = await db.get(BillingOrder, started.order_id)
        status, body, _ = await _deliver(db, "order.paid", _polar_order(order, "polar_ord_pt1"))
        assert body["outcome"] == "activated"
        organization = await db.get(Organization, ids["org_b"], populate_existing=True)
        assert (organization.plan, organization.access_state, organization.pursuit_limit_override) == ("per_tender", "paid", 1)
        reused = await endpoints.billing_quote(product="per_tender", offer=token, x_organization_id=ids["org_b"],
                                               current_user=await _user(db, ids, "user_b"), db=db)
        assert reused.blocker == "offer_required"  # used once
        # Or an admin invoice, with the signed order form as the terms acceptance: one more pursuit.
        detail = await endpoints.admin_issue_invoice(ids["org_b"], AdminInvoiceRequest(
            product="per_tender", signed_note="Order form signed 26 Oct by the director"),
            current_user=await _user(db, ids, "admin"), db=db)
        organization = await db.get(Organization, ids["org_b"], populate_existing=True)
        assert (organization.plan, organization.pursuit_limit_override, organization.billing_status) == (
            "per_tender", 2, "awaiting_payment")
        signed = await db.scalar(select(TermsAcceptance).where(TermsAcceptance.accepted_via == "signed"))
        assert (signed.user_id, signed.ip_address, signed.note) == (None, None, "Order form signed 26 Oct by the director")
        assert detail.invoices[0].currency == "UZS"

        # A pilot set up without an order (pilot_setup.py or an admin) ends on its end date too.
        today = billing_today()
        await endpoints.admin_override(ids["org_a"], BillingOverrideRequest(
            plan="pilot", billing_status="none", reason="pilot_setup-style pilot",
            plan_started_on=today - timedelta(days=95), plan_ends_on=today - timedelta(days=3)),
            current_user=await _user(db, ids, "admin"), db=db)
        counts = await run_billing_schedule(db, today=today)
        await db.commit()
        assert counts["ended"] >= 1
        organization = await db.get(Organization, ids["org_a"], populate_existing=True)
        assert (organization.plan, organization.access_state) == ("explore", "explore")

    await _deploy51_reconcile_override_and_detail_ids(sessions, ids)


def _polar_reads(fake: FakePolar, order, *, polar_id: str | None, subscription_id: str | None = None,
                 checkout_status: str = "succeeded") -> None:
    """What Polar shows for this order's checkout: a paid order (polar_id) or none."""
    metadata = {"organization_id": str(order.organization_id), "order_id": str(order.id), "product": order.product}
    fake.checkout_reads[order.provider_checkout_id] = {"id": order.provider_checkout_id, "status": checkout_status,
                                                       "metadata": metadata, "subscription_id": subscription_id}
    fake.orders_by_checkout[order.provider_checkout_id] = [] if polar_id is None else [{
        **_polar_order(order, polar_id, subscription_id=subscription_id), "metadata": metadata}]
    if subscription_id:
        fake.subscriptions[subscription_id] = {"id": subscription_id, "status": "active"}


async def _deploy51_reconcile_override_and_detail_ids(sessions, ids) -> None:
    """Deploy 5.1: reconcile_polar.py (dry run, activate, link only after a manual override, not paid, Polar
    refusing, idempotent), the override's default dates and messages, organization_id in every detail."""
    from app.api.endpoints import billing as endpoints
    from app.models.audit import AdminActivityEvent
    from app.models.billing import BillingOrder, BillingPayment, OnboardingTask
    from app.models.email import EmailDelivery
    from app.models.tenancy import Organization
    from app.schemas.billing import AdminBillingDetail, AdminInvoiceRequest, BillingOverrideRequest
    from app.services import admin_alerts
    from scripts.billing import reconcile_polar as script

    fake = billing_polar.polar_client()
    today = billing_today()
    kicks = []
    original_kick = admin_alerts.kick_admin_alerts
    admin_alerts.kick_admin_alerts = lambda: kicks.append(1)
    reconcile = lambda order_id, *, dry_run, all_pending=False: script.run(  # noqa: E731
        "local", order_id=order_id, all_pending=all_pending, dry_run=dry_run, client=fake, sessions=sessions, today=today)
    try:
        # 1. A paid Pursuit Desk card order whose order.paid never arrived (org A, in Explore): activate.
        async with sessions() as db:
            started = await _checkout(db, ids, "user_a", "a", "pursuit_desk", "card")
            order = await db.get(BillingOrder, started.order_id)
            _polar_reads(fake, order, polar_id="polar_ord_r1", subscription_id="sub_r1")
            desk_a = order.id
        dry = await reconcile(desk_a, dry_run=True)
        assert [(row["action"], row["applied"], row["polar_order_id"], row["subscription_status"]) for row in dry] == [
            ("activate", False, "polar_ord_r1", "active")]
        async with sessions() as db:
            assert (await db.get(BillingOrder, desk_a)).status == "pending"  # the dry run changed nothing
            assert (await db.get(Organization, ids["org_a"])).plan == "explore"
        applied = await reconcile(desk_a, dry_run=False)
        assert [(row["action"], row["outcome"], row["applied"]) for row in applied] == [("activate", "activated", True)]
        assert kicks == [1]
        async with sessions() as db:
            order = await db.get(BillingOrder, desk_a)
            organization = await db.get(Organization, ids["org_a"])
            assert (order.status, order.provider_subscription_id) == ("paid", "sub_r1")
            assert (organization.plan, organization.billing_status, organization.plan_ends_on) == (
                "pursuit_desk", "paid", add_months(today, 12))
            payment = await db.scalar(select(BillingPayment).where(BillingPayment.order_id == desk_a))
            assert payment.provider_payment_id == "polar_ord_r1" and "reconciled" in payment.note
            assert await db.scalar(select(func.count(OnboardingTask.id)).where(OnboardingTask.order_id == desk_a)) == 1
            actors = dict((await db.execute(select(AdminActivityEvent.action, AdminActivityEvent.actor_label).where(
                AdminActivityEvent.target_resource_id.in_((str(desk_a), str(payment.id), str(ids["org_a"]))),
                AdminActivityEvent.action.in_(("BILLING_PLAN_ACTIVATED", "BILLING_PAYMENT_RECORDED", "BILLING_CREDIT_APPLIED")),
                AdminActivityEvent.created_at >= order.created_at))).all())
            assert actors == {"BILLING_PLAN_ACTIVATED": "reconcile", "BILLING_PAYMENT_RECORDED": "reconcile",
                              "BILLING_CREDIT_APPLIED": "reconcile"}
            # Idempotent: a second run, and a late order.paid delivery once the endpoint is subscribed.
            assert [row["action"] for row in await reconcile(desk_a, dry_run=False)] == ["already_paid"]
            status, body, _ = await _deliver(db, "order.paid", _polar_order(order, "polar_ord_r1", subscription_id="sub_r1"))
            assert body["outcome"] == "duplicate_payment"

        # 2. Activated by hand first (org B), then reconciled: ids linked, the admin's plan and dates kept.
        async with sessions() as db:
            started = await _checkout(db, ids, "user_b", "b", "pursuit_desk", "card")
            order = await db.get(BillingOrder, started.order_id)
            _polar_reads(fake, order, polar_id="polar_ord_r2", subscription_id="sub_r2")
            desk_b = order.id
            admin = await _user(db, ids, "admin")
            detail = await endpoints.admin_override(ids["org_b"], BillingOverrideRequest(
                plan="pursuit_desk", billing_status="paid", reason="Paid in Polar; order.paid missing"),
                current_user=admin, db=db)
            # No dates given, a new plan: today + 12 months (it was per-tender, open-ended).
            assert (detail.plan, detail.plan_started_on, detail.plan_ends_on) == ("pursuit_desk", today, add_months(today, 12))
            welcomes = await db.scalar(select(func.count(EmailDelivery.id)).where(EmailDelivery.kind == "BILLING_WELCOME"))
        dry = await reconcile(desk_b, dry_run=True)
        assert [(row["action"], row["applied"]) for row in dry] == [("link_only", False)]
        linked = await reconcile(desk_b, dry_run=False)
        assert [(row["action"], row["outcome"], row["check_dates"]) for row in linked] == [("link_only", "linked", False)]
        async with sessions() as db:
            order = await db.get(BillingOrder, desk_b)
            organization = await db.get(Organization, ids["org_b"])
            assert (order.status, order.provider_subscription_id, order.plan_started_on, order.plan_ends_on) == (
                "paid", "sub_r2", today, add_months(today, 12))
            assert order.activated_at is not None
            assert (organization.plan, organization.billing_status, organization.plan_ends_on) == (
                "pursuit_desk", "paid", add_months(today, 12))
            assert await db.scalar(select(BillingPayment.provider_payment_id).where(BillingPayment.order_id == desk_b)) == "polar_ord_r2"
            # Not activated again: no onboarding task, no second welcome e-mail.
            assert await db.scalar(select(func.count(OnboardingTask.id)).where(OnboardingTask.order_id == desk_b)) == 0
            assert await db.scalar(select(func.count(EmailDelivery.id)).where(EmailDelivery.kind == "BILLING_WELCOME")) == welcomes
            audit = await db.scalar(select(AdminActivityEvent).where(
                AdminActivityEvent.action == "BILLING_STATUS_CHANGED", AdminActivityEvent.target_resource_id == str(desk_b)))
            assert audit.actor_label == "reconcile" and audit.new_state["activation"] == "kept_manual"
            # Linked: the subscription's later events now apply to the plan.
            status, body, _ = await _deliver(db, "subscription.canceled", {"id": "sub_r2", "status": "active"})
            assert (await db.get(Organization, ids["org_b"], populate_existing=True)).billing_status == "canceled"

        # 3. Not paid in Polar (an open checkout), and Polar refusing the token: nothing changes.
        async with sessions() as db:
            started = await _checkout(db, ids, "user_a", "a", "extra_pursuit", "card")
            order = await db.get(BillingOrder, started.order_id)
            _polar_reads(fake, order, polar_id=None, checkout_status="open")
            extra = order.id
        rows = await reconcile(None, dry_run=False, all_pending=True)
        assert [(row["order_id"], row["action"], row["applied"]) for row in rows] == [(str(extra), "not_paid", False)]
        fake.refuse_reads = True
        assert [(row["action"], row["error"]) for row in await reconcile(extra, dry_run=True)] == [("polar_error", "polar_http_403")]
        fake.refuse_reads = False
        async with sessions() as db:
            assert (await db.get(BillingOrder, extra)).status == "pending"
        assert [row["action"] for row in await reconcile(uuid4(), dry_run=True)] == ["not_found"]

        # 4. Override: messages instead of a schema refusal, default and kept dates; organization_id everywhere.
        async with sessions() as db:
            with pytest.raises(HTTPException) as short:
                await endpoints.admin_override(ids["org_a"], BillingOverrideRequest(plan="pilot", reason=" x "),
                                               current_user=await _user(db, ids, "admin"), db=db)
            assert (short.value.status_code, short.value.detail) == (422, {"code": "reason_required", "message": "Give a reason"})
            with pytest.raises(HTTPException) as backwards:
                await endpoints.admin_override(ids["org_a"], BillingOverrideRequest(
                    plan="pilot", plan_started_on=today, plan_ends_on=today - timedelta(days=1), reason="Wrong dates"),
                    current_user=await _user(db, ids, "admin"), db=db)
            assert backwards.value.detail["code"] == "dates_invalid" and "cannot end" in backwards.value.detail["message"]
            pilot = await endpoints.admin_override(ids["org_a"], BillingOverrideRequest(plan="pilot", reason="Back to a pilot"),
                                                   current_user=await _user(db, ids, "admin"), db=db)
            assert (pilot.plan_started_on, pilot.plan_ends_on) == (today, add_months(today, 3))
            kept = await endpoints.admin_override(ids["org_a"], BillingOverrideRequest(
                plan="pilot", billing_status="paid", reason="Status only"), current_user=await _user(db, ids, "admin"), db=db)
            assert (kept.plan_started_on, kept.plan_ends_on, kept.billing_status) == (today, add_months(today, 3), "paid")
            moved = await endpoints.admin_override(ids["org_a"], BillingOverrideRequest(
                plan="pilot", plan_ends_on=add_months(today, 4), reason="Extended a month"), current_user=await _user(db, ids, "admin"), db=db)
            assert (moved.plan_started_on, moved.plan_ends_on) == (today, add_months(today, 4))
            with pytest.raises(HTTPException) as unsigned:
                await endpoints.admin_issue_invoice(ids["org_b"], AdminInvoiceRequest(product="per_tender", signed_note=""),
                                                    current_user=await _user(db, ids, "admin"), db=db)
            assert unsigned.value.detail == {"code": "note_required", "message": "Describe the signed order form (date, signatory)"}
            for detail, organization_id in (
                (await endpoints.admin_billing_detail(ids["org_a"], db=db), ids["org_a"]), (pilot, ids["org_a"]),
                (await endpoints.admin_billing_detail(ids["org_b"], db=db), ids["org_b"]),
            ):
                assert detail.organization_id == organization_id
                assert AdminBillingDetail.model_validate(detail).model_dump(mode="json")["organization_id"] == str(organization_id)
    finally:
        admin_alerts.kick_admin_alerts = original_kick
