"""B1: check the Polar **sandbox** setup before Deploy 5 (never production).

usage (backend directory, the .env holding the sandbox values):
    python scripts/polar_sandbox_check.py                 # products match the plan catalogue
    python scripts/polar_sandbox_check.py --checkout      # + one pilot checkout URL to pay with a test card
    python scripts/polar_sandbox_check.py --webhook-selftest

1. Refuses unless POLAR_ENV=sandbox (the API base is https://sandbox-api.polar.sh).
2. Reads each product in POLAR_PRODUCT_IDS and compares its price with app.core.plans.PRODUCTS
   (pilot USD 900 one-time, pursuit_desk USD 6,000 yearly, extra_pursuit USD 200 one-time).
3. --checkout creates a sandbox checkout for the pilot (metadata marked "sandbox-check", no
   organization) and prints its URL: pay with Polar's test card 4242 4242 4242 4242, any future date,
   any CVC. The order.paid webhook then reaches the app and is stored as "unmatched_order" (no
   organization): that proves delivery and the signature without touching a customer.
4. --webhook-selftest signs a sample event with POLAR_WEBHOOK_SECRET and verifies it locally.

Prints ids, names, amounts and codes only; never the token or the secret.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.plans import PRODUCTS, BILLING_ANNUAL  # noqa: E402
from app.services import billing_polar  # noqa: E402


async def product(client: httpx.AsyncClient, product_id: str) -> dict:
    response = await client.get(f"/v1/products/{product_id}")
    if response.status_code != 200:
        raise SystemExit(f"product {product_id}: HTTP {response.status_code}")
    return response.json()


def price_of(data: dict) -> tuple[int | None, str | None]:
    for price in data.get("prices") or []:
        if price.get("amount_type") == "fixed" and not price.get("is_archived"):
            return int(price.get("price_amount") or 0), str(price.get("price_currency") or "").lower()
    return None, None


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", action="store_true")
    parser.add_argument("--webhook-selftest", action="store_true")
    args = parser.parse_args()
    if settings.POLAR_ENV != "sandbox" or billing_polar.api_base() != billing_polar.POLAR_API["sandbox"]:
        print("REFUSED: POLAR_ENV must be sandbox for this check")
        return 2
    if not (settings.POLAR_ACCESS_TOKEN or "").strip():
        print("POLAR_ACCESS_TOKEN is not set (a sandbox organization access token)")
        return 2
    ids = billing_polar.product_ids()
    problems = 0
    async with httpx.AsyncClient(base_url=billing_polar.api_base(), timeout=20,
                                 headers={"Authorization": f"Bearer {settings.POLAR_ACCESS_TOKEN.strip()}"}) as client:
        for code, expected in PRODUCTS.items():
            if code not in ids:
                print(f"MISSING  {code}: no id in POLAR_PRODUCT_IDS")
                problems += 1
                continue
            data = await product(client, ids[code])
            amount, currency = price_of(data)
            recurring = data.get("recurring_interval") or None
            wanted_recurring = "year" if expected.billing == BILLING_ANNUAL else None
            ok = amount == expected.amount_cents and currency == "usd" and recurring == wanted_recurring
            problems += 0 if ok else 1
            print(f"{'OK      ' if ok else 'MISMATCH'} {code}: '{data.get('name')}' {amount} {currency} "
                  f"recurring={recurring} (want {expected.amount_cents} usd recurring={wanted_recurring})")
    if args.checkout and "pilot" in ids:
        checkout = await billing_polar.PolarClient().create_checkout(
            product_id=ids["pilot"], success_url=f"{(settings.PUBLIC_APP_URL or 'https://example.invalid').rstrip('/')}/dashboard/billing",
            metadata={"purpose": "sandbox-check"}, customer_email="sandbox-check@plasma.invalid",
            external_customer_id=f"sandbox-check-{int(time.time())}", customer_name="Plasma sandbox check",
            country="UZ", tax_id=None, discount_id=None,
        )
        print(f"CHECKOUT {checkout['id']}: {checkout['url']}")
        print("Pay with 4242 4242 4242 4242; then look for an 'unmatched_order' order.paid row in billing_events.")
    if args.webhook_selftest:
        secret = (settings.POLAR_WEBHOOK_SECRET or "").strip()
        if not secret:
            print("POLAR_WEBHOOK_SECRET is not set")
            return 2
        body = json.dumps({"type": "order.paid", "data": {"id": "selftest"}}).encode()
        stamp = str(int(time.time()))
        headers = {"webhook-id": "msg_selftest", "webhook-timestamp": stamp,
                   "webhook-signature": billing_polar.sign(secret, "msg_selftest", stamp, body)}
        print("WEBHOOK  signature self-test:", billing_polar.verify_webhook(body, headers) == "msg_selftest")
    print("problems:", problems)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
