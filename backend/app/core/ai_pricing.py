"""Sprint 1: the price table used to estimate AI cost per call (USD per million tokens).

Configured by ``AI_PRICE_TABLE_JSON`` (a JSON object ``{"version": "...", "models":
{"<model>": {"input": 0.75, "output": 3.75}}}``); the default below is used otherwise.
Thinking tokens are billed at the output rate. A model missing from the table gets no
estimate (NULL), never a guess.

Default values: the official Gemini API price page, https://ai.google.dev/gemini-api/docs/pricing
("Last updated 2026-10-09 UTC", read 2026-10-12), paid tier, Standard, text input; output includes
thinking. Only models listed on that page are here; gemini-3.7-flash (a configured fallback) is not
listed there, so its calls get no estimate. gemini-3.8-flash and gemini-3.6-flash are at the
introductory price, valid through 2026-12-31 (USD 1.50 / 7.50 from 2027-01-01): set
AI_PRICE_TABLE_JSON before then. gemini-3.1-pro-preview is at the <= 200k-token prompt rate (USD
4.00 / 18.00 above 200k tokens).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from decimal import Decimal

logger = logging.getLogger(__name__)

DEFAULT_PRICE_TABLE = {
    "version": "gemini-api-pricing-2026-10-09",
    "models": {
        "gemini-3.8-flash": {"input": "0.75", "output": "3.75"},
        "gemini-3.6-flash": {"input": "0.75", "output": "3.75"},
        "gemini-3.1-pro-preview": {"input": "2.00", "output": "12.00"},
        "gemini-3-flash-preview": {"input": "0.50", "output": "3.00"},
        "gemini-2.5-flash": {"input": "0.30", "output": "2.50"},
        "gemini-2.5-flash-lite": {"input": "0.10", "output": "0.40"},
    },
}
_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class PriceTable:
    version: str
    models: dict[str, tuple[Decimal, Decimal]]

    def estimate(
        self, model_name: str, input_tokens: int | None, output_tokens: int | None, thinking_tokens: int | None
    ) -> Decimal | None:
        prices = self.models.get(model_name)
        if prices is None or (input_tokens is None and output_tokens is None):
            return None
        input_rate, output_rate = prices
        billed_output = (output_tokens or 0) + (thinking_tokens or 0)
        cost = (Decimal(input_tokens or 0) * input_rate + Decimal(billed_output) * output_rate) / _MILLION
        return cost.quantize(Decimal("0.000001"))


def _parse(raw: dict) -> PriceTable:
    models = {}
    for name, entry in (raw.get("models") or {}).items():
        models[str(name)] = (Decimal(str(entry["input"])), Decimal(str(entry["output"])))
    return PriceTable(version=str(raw.get("version") or "custom")[:40], models=models)


def price_table() -> PriceTable:
    configured = os.getenv("AI_PRICE_TABLE_JSON", "").strip()
    if configured:
        try:
            return _parse(json.loads(configured))
        except (ValueError, KeyError, TypeError, ArithmeticError):
            logger.error("ai_price_table_invalid: using the default table")
    return _parse(DEFAULT_PRICE_TABLE)
