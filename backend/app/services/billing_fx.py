"""B1: the Central Bank of Uzbekistan USD rate of the day, for UZS invoices to residents (cached)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import FxRate

CBU_URL = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/{currency}/{day}/"


class FxUnavailableError(RuntimeError):
    pass


async def fetch_cbu_rate(currency: str, day: date) -> Decimal:
    """UZS per one unit of ``currency`` in effect on ``day`` (CBU publishes the rate per date)."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(CBU_URL.format(currency=currency, day=day.isoformat()))
        response.raise_for_status()
        rows = response.json()
        rate = Decimal(str(rows[0]["Rate"]))
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, InvalidOperation) as exc:
        raise FxUnavailableError("cbu_rate_unavailable") from exc
    if rate <= 0:
        raise FxUnavailableError("cbu_rate_invalid")
    return rate


async def usd_rate(db: AsyncSession, day: date) -> Decimal:
    """The CBU USD rate for ``day``: from the cache, else fetched once and stored."""
    cached = await db.get(FxRate, ("USD", day))
    if cached is not None:
        return Decimal(cached.rate)
    rate = await fetch_cbu_rate("USD", day)
    await db.execute(
        pg_insert(FxRate).values(currency="USD", rate_date=day, rate=rate, source="CBU")
        .on_conflict_do_nothing(index_elements=["currency", "rate_date"])
    )
    stored = await db.get(FxRate, ("USD", day), populate_existing=True)
    return Decimal(stored.rate) if stored is not None else rate
