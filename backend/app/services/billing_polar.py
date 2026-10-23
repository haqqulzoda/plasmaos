"""B1: Polar (card payments). Checkout and discount creation, and webhook signature verification.

Sandbox by default (POLAR_ENV); production is refused outside a production environment (settings).
Webhooks follow Standard Webhooks: ``webhook-id``, ``webhook-timestamp`` and ``webhook-signature``
("v1,<base64 HMAC-SHA256>" over "<id>.<timestamp>.<body>"). The key is the base64 part of a
``whsec_`` secret, or, for older Polar secrets, the UTF-8 bytes of the whole secret: both are tried,
as Polar's SDKs do. Nothing here logs a token, a secret or a payload.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from typing import Any, Mapping

import httpx

from app.core.config import settings
from app.core.plans import PRODUCTS_FOR_SALE

POLAR_API = {"sandbox": "https://sandbox-api.polar.sh", "production": "https://api.polar.sh"}
WEBHOOK_TOLERANCE_SECONDS = 5 * 60
MAX_WEBHOOK_BYTES = 256 * 1024


class PolarError(RuntimeError):
    """Polar refused or could not be reached; the message is a code, never a response body."""


class WebhookSignatureError(ValueError):
    pass


def product_ids() -> dict[str, str]:
    """POLAR_PRODUCT_IDS as {product code: Polar product id}; unknown codes and blanks are dropped."""
    raw = (settings.POLAR_PRODUCT_IDS or "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    return {code: str(value[code]).strip() for code in PRODUCTS_FOR_SALE if str(value.get(code) or "").strip()}


def card_available(product: str) -> bool:
    return bool((settings.POLAR_ACCESS_TOKEN or "").strip()) and product in product_ids()


def api_base() -> str:
    return POLAR_API["production" if settings.POLAR_ENV == "production" else "sandbox"]


class PolarClient:
    def __init__(self, *, token: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self._token = (token or settings.POLAR_ACCESS_TOKEN or "").strip()
        self._transport = transport

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self._token:
            raise PolarError("polar_not_configured")
        try:
            async with httpx.AsyncClient(
                base_url=api_base(), transport=self._transport, timeout=20,
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
            ) as client:
                response = await client.post(path, json=body)
        except httpx.HTTPError as exc:
            raise PolarError("polar_unreachable") from exc
        if response.status_code >= 400:
            raise PolarError(f"polar_http_{response.status_code}")
        data = response.json()
        if not isinstance(data, dict) or not data.get("id"):
            raise PolarError("polar_bad_response")
        return data

    async def create_discount(self, *, product_id: str, amount_cents: int, name: str, metadata: dict[str, str]) -> str:
        """A one-time fixed discount on one product, redeemable once (the pilot credit)."""
        data = await self._post("/v1/discounts/", {
            "type": "fixed", "duration": "once", "name": name[:100], "amounts": {"usd": amount_cents},
            "max_redemptions": 1, "products": [product_id], "metadata": metadata,
        })
        return str(data["id"])

    async def create_checkout(
        self, *, product_id: str, success_url: str, metadata: dict[str, str], customer_email: str,
        external_customer_id: str, customer_name: str, country: str, tax_id: str | None,
        discount_id: str | None,
    ) -> dict[str, str]:
        body: dict[str, Any] = {
            "products": [product_id], "success_url": success_url, "metadata": metadata,
            "customer_email": customer_email, "external_customer_id": external_customer_id,
            "customer_name": customer_name[:256], "customer_billing_address": {"country": country},
            "allow_discount_codes": False,
        }
        if tax_id:
            body["customer_tax_id"] = tax_id
        if discount_id:
            body["discount_id"] = discount_id
        data = await self._post("/v1/checkouts/", body)
        if not data.get("url"):
            raise PolarError("polar_bad_response")
        return {"id": str(data["id"]), "url": str(data["url"])}


def polar_client() -> PolarClient:
    """The client the billing service uses (tests replace this factory with a fake)."""
    return PolarClient()


def _keys(secret: str) -> list[bytes]:
    keys: list[bytes] = []
    if secret.startswith("whsec_"):
        try:
            keys.append(base64.b64decode(secret[len("whsec_"):], validate=True))
        except (binascii.Error, ValueError):
            pass
    keys.append(secret.encode("utf-8"))
    return keys


def sign(secret: str, msg_id: str, timestamp: str, body: bytes, *, utf8_key: bool = False) -> str:
    """A Standard Webhooks signature header value (for tests and the sandbox check script)."""
    key = secret.encode("utf-8") if utf8_key else _keys(secret)[0]
    digest = hmac.new(key, f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def verify_webhook(
    body: bytes, headers: Mapping[str, str], *, secret: str | None = None, now: float | None = None,
) -> str:
    """Return the event id when the delivery is signed with our secret and fresh; raise otherwise."""
    secret = (secret if secret is not None else settings.POLAR_WEBHOOK_SECRET or "").strip()
    if not secret:
        raise WebhookSignatureError("webhook_secret_not_configured")
    if len(body) > MAX_WEBHOOK_BYTES:
        raise WebhookSignatureError("webhook_too_large")
    lowered = {key.lower(): value for key, value in headers.items()}
    msg_id = (lowered.get("webhook-id") or "").strip()
    timestamp = (lowered.get("webhook-timestamp") or "").strip()
    signatures = (lowered.get("webhook-signature") or "").split()
    if not msg_id or not timestamp or not signatures or len(msg_id) > 200:
        raise WebhookSignatureError("webhook_headers_missing")
    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise WebhookSignatureError("webhook_timestamp_invalid") from exc
    if abs((now if now is not None else time.time()) - sent_at) > WEBHOOK_TOLERANCE_SECONDS:
        raise WebhookSignatureError("webhook_timestamp_out_of_tolerance")
    signed = f"{msg_id}.{timestamp}.".encode() + body
    expected = [
        base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode() for key in _keys(secret)
    ]
    for entry in signatures:
        version, _, value = entry.partition(",")
        if version == "v1" and any(hmac.compare_digest(value, candidate) for candidate in expected):
            return msg_id
    raise WebhookSignatureError("webhook_signature_invalid")
