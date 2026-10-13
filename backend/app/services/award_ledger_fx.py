"""S1-6: one dated exchange-rate table for USD equivalents in the award-ledger reports.

The table is the Central Bank of the Republic of Uzbekistan's official rates for one date
(award_ledger_fx_2026-10-09.json: UZS per unit of every currency it publishes). Every
conversion uses that one date, so totals are comparable and reproducible; cross rates to USD
go through UZS. Amounts stay as published in the ledger; USD figures are labelled equivalents.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
import json
from pathlib import Path

_TABLE = json.loads(Path(__file__).with_name("award_ledger_fx_2026-10-09.json").read_text(encoding="utf-8"))

FX_DATE: str = _TABLE["date"]
FX_SOURCE: str = _TABLE["source"]
FX_URL: str = _TABLE["url"]
UZS_PER_UNIT: dict[str, Decimal] = {code: Decimal(str(rate)) for code, rate in _TABLE["uzs_per_unit"].items()}


def usd_per_unit(currency: str) -> Decimal | None:
    rate = UZS_PER_UNIT.get((currency or "").upper())
    return None if rate is None else rate / UZS_PER_UNIT["USD"]


def to_usd(currency: str | None, amount: Decimal | None) -> Decimal | None:
    """The USD equivalent at the table's date, or None for an unknown currency or no amount."""
    if amount is None or not currency:
        return None
    rate = usd_per_unit(currency)
    if rate is None:
        return None
    return (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
