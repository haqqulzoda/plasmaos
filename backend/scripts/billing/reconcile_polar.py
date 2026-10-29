#!/usr/bin/env python3
"""Deploy 5.1: reconcile card orders with Polar (the live webhook was subscribed to checkout.* only).

    python scripts/billing/reconcile_polar.py --target production --order <plasma order id> --dry-run
    python scripts/billing/reconcile_polar.py --target production --order <plasma order id>
    python scripts/billing/reconcile_polar.py --target production --all-pending --dry-run

Run inside a one-off backend container (scripts/compose-release.sh run --rm --no-deps -T backend ...). The Polar
token (POLAR_ACCESS_TOKEN) needs checkouts:read (or checkouts:write), orders:read and subscriptions:read.

For each card order (one by id, or every "pending" card order with a Polar checkout) it reads the Polar checkout,
the Polar orders of that checkout and the subscription, then prints one JSON line with ``action``:

- ``not_paid``: Polar shows no paid order (checkout open/expired/failed, order pending/void) → nothing changes;
- ``activate``: paid in Polar, the organization is not on the plan yet → the same path as the order.paid webhook
  (payment, plan and dates, onboarding task, welcome e-mail, team alert), audit actor "reconcile";
- ``link_only``: paid in Polar and the organization is already on the bought plan (activated by hand with an
  audited override) → only the Polar order and subscription ids are linked and the order marked paid. The plan,
  its dates and the billing status stay as set; ``check_dates`` flags dates that are not a full term;
- ``needs_review``: refunded or several paid orders in Polar, or the organization is on a larger plan → nothing;
- ``mismatch``: the Polar checkout or order belongs to another Plasma order → nothing;
- ``already_paid`` / ``already_linked`` / ``not_pending`` / ``no_checkout`` / ``not_card`` / ``not_found`` → nothing;
- ``polar_error``: Polar refused or was unreachable (``error``: e.g. polar_http_403 = a missing token scope).

``--dry-run`` reads Polar and the database and changes nothing. Without it, ``activate`` and ``link_only`` are
applied, each order in its own transaction; a second run reports ``already_paid``. Never activates anything Polar
does not show as paid. Prints ids, statuses and amounts only; never the token. Exit 1 on a polar_error.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
import json
from pathlib import Path
import sys
from typing import Any
from uuid import UUID

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

TARGET_ENVIRONMENTS = {"local": {"development", "test"}, "production": {"production"}}
APPLIED_ACTIONS = ("activate", "link_only")


def _belongs(order_id: str, checkout_id: str, record: dict[str, Any]) -> bool | None:
    """True/False when the Polar record names a Plasma order (metadata) or checkout; None when it names neither."""
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    if metadata.get("order_id"):
        return str(metadata["order_id"]) == order_id
    if record.get("checkout_id"):
        return str(record["checkout_id"]) == checkout_id
    return None


def match_polar(order_id: str, checkout_id: str, checkout: dict[str, Any],
                polar_orders: list[dict[str, Any]]) -> tuple[str, dict[str, Any] | None, str | None]:
    """(decision, the paid Polar order, a note). Decision ``paid`` means Polar shows exactly one paid order for
    this Plasma order; anything else is final and changes nothing. Pure: tested without Polar or a database."""
    if _belongs(order_id, checkout_id, checkout) is False:
        return "mismatch", None, "the Polar checkout carries another order id"
    ours = [record for record in polar_orders if _belongs(order_id, checkout_id, record) is not False]
    if len(ours) != len(polar_orders):
        return "mismatch", None, "a Polar order of this checkout carries another order id"
    paid = [record for record in ours if record.get("status") == "paid" and record.get("paid") is True]
    if any(record.get("status") in ("refunded", "partially_refunded") for record in ours):
        return "needs_review", None, "refunded in Polar"
    if len(paid) > 1:
        return "needs_review", None, "several paid Polar orders for one checkout"
    if not paid:
        states = ", ".join(sorted({str(record.get("status")) for record in ours})) or "no order"
        return "not_paid", None, f"checkout {checkout.get('status')}, {states}"
    return "paid", paid[0], None


def _full_term(start: date | None, end: date | None, months: int | None) -> bool:
    from app.services.billing import add_months

    return bool(start and end and months and end == add_months(start, months))


async def reconcile_one(db, order, *, client, apply: bool, today: date | None = None) -> dict[str, Any]:
    from app.core.plans import PRODUCTS
    from app.models.tenancy import Organization
    from app.services import billing as service
    from app.services.billing_polar import PolarError

    row: dict[str, Any] = {"order_id": str(order.id), "organization_id": str(order.organization_id),
                           "product": order.product, "method": order.method, "status": order.status,
                           "checkout_id": order.provider_checkout_id, "applied": False}
    if order.method != service.METHOD_CARD:
        return {**row, "action": "not_card"}
    if order.status == "paid":
        return {**row, "action": "already_paid"}
    if order.status != "pending":
        return {**row, "action": "not_pending"}
    if not order.provider_checkout_id:
        return {**row, "action": "no_checkout"}
    try:
        checkout = await client.get_checkout(order.provider_checkout_id)
        polar_orders = await client.list_orders(checkout_id=order.provider_checkout_id)
        row["polar_checkout_status"] = checkout.get("status")
        row["polar_orders"] = [{"id": record.get("id"), "status": record.get("status"), "paid": record.get("paid"),
                                "total_amount": record.get("total_amount"), "currency": record.get("currency"),
                                "subscription_id": record.get("subscription_id")} for record in polar_orders]
        decision, polar_order, note = match_polar(str(order.id), order.provider_checkout_id, checkout, polar_orders)
        if decision != "paid":
            return {**row, "action": decision, "note": note}
        row["polar_order_id"] = polar_order.get("id")
        if polar_order.get("subscription_id"):
            subscription = await client.get_subscription(str(polar_order["subscription_id"]))
            row["subscription_id"] = str(polar_order["subscription_id"])
            row["subscription_status"] = subscription.get("status")
    except PolarError as exc:
        return {**row, "action": "polar_error", "error": str(exc)}

    organization = await db.get(Organization, order.organization_id)
    row.update({"organization_plan": organization.plan, "billing_status": organization.billing_status,
                "plan_started_on": organization.plan_started_on.isoformat() if organization.plan_started_on else None,
                "plan_ends_on": organization.plan_ends_on.isoformat() if organization.plan_ends_on else None})
    result = await service.reconcile_paid_card_order(db, order_id=order.id, polar_order=polar_order, today=today,
                                                     apply=apply)
    row["action"] = result["action"]
    if row["action"] == "link_only":
        term = PRODUCTS[order.product].term_months
        row["check_dates"] = not _full_term(organization.plan_started_on, organization.plan_ends_on, term)
        if organization.billing_status != "paid":
            row["note"] = "the billing status stays as the admin set it"
    if row["action"] == "needs_review":
        row["note"] = f"the organization is on {organization.plan}; activating would move it to {order.plan}"
    if "outcome" in result:
        row["outcome"] = result["outcome"]
        row["applied"] = result["outcome"] in ("activated", "linked")
    return row


async def run(target: str, *, order_id: UUID | None, all_pending: bool, dry_run: bool, client=None,
              sessions=None, today: date | None = None) -> list[dict[str, Any]]:
    from app.core.config import settings
    from app.models.billing import BillingOrder
    from app.services import billing_polar
    from app.services.admin_alerts import kick_admin_alerts

    if settings.ENVIRONMENT not in TARGET_ENVIRONMENTS[target]:
        raise SystemExit(f"REFUSED: --target {target} but ENVIRONMENT={settings.ENVIRONMENT}")
    client = client or billing_polar.polar_client()
    engine = None
    if sessions is None:
        from app.db.session import AsyncSessionLocal, engine
        sessions = AsyncSessionLocal
    rows = []
    try:
        async with sessions() as db:
            statement = select(BillingOrder.id).order_by(BillingOrder.created_at)
            statement = (statement.where(BillingOrder.id == order_id) if order_id is not None else statement.where(
                BillingOrder.method == "card", BillingOrder.status == "pending",
                BillingOrder.provider_checkout_id.is_not(None)))
            ids = list((await db.scalars(statement)).all())
        if order_id is not None and not ids:
            return [{"order_id": str(order_id), "action": "not_found", "applied": False}]
        for current in ids:
            async with sessions() as db:  # one transaction per order
                order = await db.get(BillingOrder, current)
                row = await reconcile_one(db, order, client=client, apply=not dry_run, today=today)
                if row.get("applied"):
                    await db.commit()
                else:
                    await db.rollback()
                rows.append(row)
        if any(row.get("applied") for row in rows):
            kick_admin_alerts()
        return rows
    finally:
        if engine is not None:
            await engine.dispose()


def summary(rows: list[dict[str, Any]], dry_run: bool) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    for row in rows:
        counts[row["action"]] = counts.get(row["action"], 0) + 1
    counts["applied"] = sum(1 for row in rows if row.get("applied"))
    counts["dry_run"] = dry_run
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", choices=sorted(TARGET_ENVIRONMENTS), required=True)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--order", type=UUID, help="a Plasma billing order id")
    which.add_argument("--all-pending", action="store_true", help="every pending card order with a Polar checkout")
    parser.add_argument("--dry-run", action="store_true", help="read Polar and the database; change nothing")
    args = parser.parse_args()
    rows = asyncio.run(run(args.target, order_id=args.order, all_pending=args.all_pending, dry_run=args.dry_run))
    for row in rows:
        print(json.dumps(row, ensure_ascii=False, default=str))
    print("SUMMARY " + json.dumps(summary(rows, args.dry_run)))
    return 1 if any(row["action"] == "polar_error" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
