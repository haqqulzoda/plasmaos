"""Honest budget display for backend-rendered exports (D1-05).

A missing, zero or negative budget means the source did not publish one; it is
never rendered as an amount (the frontend uses the same rule, lib/tenderTruth.ts).
"""

from __future__ import annotations

import math
from typing import Any

NOT_PUBLISHED = {
    "en": "Not published",
    "ru": "Не опубликован",
    "uz": "E'lon qilinmagan",
    "ar": "غير منشور",
}


def budget_is_published(value: Any) -> bool:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(amount) and amount > 0


def not_published_label(language: str = "en") -> str:
    return NOT_PUBLISHED.get(language, NOT_PUBLISHED["en"])
