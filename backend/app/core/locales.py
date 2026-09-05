from __future__ import annotations

from enum import Enum


class UiLocale(str, Enum):
    """Canonical product locale codes accepted by persistence."""

    ENGLISH = "en"
    UZBEK = "uz"
    RUSSIAN = "ru"
    ARABIC = "ar"


KNOWN_UI_LOCALES = tuple(locale.value for locale in UiLocale)
CUSTOMER_SELECTABLE_UI_LOCALES = (
    UiLocale.ENGLISH,
    UiLocale.UZBEK,
    UiLocale.RUSSIAN,
    UiLocale.ARABIC,
)
CUSTOMER_SELECTABLE_UI_LOCALE_VALUES = tuple(
    locale.value for locale in CUSTOMER_SELECTABLE_UI_LOCALES
)


def is_customer_selectable_ui_locale(locale: UiLocale) -> bool:
    return locale in CUSTOMER_SELECTABLE_UI_LOCALES
