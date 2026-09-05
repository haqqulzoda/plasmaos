"""Canonical analysis-language capabilities, independent from UI locales."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AnalysisLanguage(str, Enum):
    ENGLISH = "en"
    UZBEK = "uz"
    RUSSIAN = "ru"
    ARABIC = "ar"


class AnalysisDirection(str, Enum):
    LTR = "ltr"
    RTL = "rtl"
    AUTO = "auto"


@dataclass(frozen=True)
class AnalysisLanguageDefinition:
    code: AnalysisLanguage
    display_name_native: str
    prompt_name: str
    generation_supported: bool
    customer_selectable: bool
    direction: AnalysisDirection


ANALYSIS_LANGUAGE_REGISTRY: dict[AnalysisLanguage, AnalysisLanguageDefinition] = {
    AnalysisLanguage.ENGLISH: AnalysisLanguageDefinition(
        code=AnalysisLanguage.ENGLISH,
        display_name_native="English",
        prompt_name="English",
        generation_supported=True,
        customer_selectable=True,
        direction=AnalysisDirection.LTR,
    ),
    AnalysisLanguage.UZBEK: AnalysisLanguageDefinition(
        code=AnalysisLanguage.UZBEK,
        display_name_native="O‘zbekcha",
        prompt_name="Uzbek (Latin script)",
        generation_supported=True,
        customer_selectable=True,
        direction=AnalysisDirection.LTR,
    ),
    AnalysisLanguage.RUSSIAN: AnalysisLanguageDefinition(
        code=AnalysisLanguage.RUSSIAN,
        display_name_native="Русский",
        prompt_name="Russian",
        generation_supported=True,
        customer_selectable=True,
        direction=AnalysisDirection.LTR,
    ),
    # Generation is technically supported, but customer selection remains gated
    # until Arabic model quality and PDF shaping/bidi both pass their release gate.
    AnalysisLanguage.ARABIC: AnalysisLanguageDefinition(
        code=AnalysisLanguage.ARABIC,
        display_name_native="العربية",
        prompt_name="Arabic",
        generation_supported=True,
        customer_selectable=False,
        direction=AnalysisDirection.RTL,
    ),
}

ANALYSIS_LANGUAGE_VALUES = tuple(item.value for item in AnalysisLanguage)
CUSTOMER_SELECTABLE_ANALYSIS_LANGUAGES = tuple(
    language
    for language, definition in ANALYSIS_LANGUAGE_REGISTRY.items()
    if definition.customer_selectable
)
CUSTOMER_SELECTABLE_ANALYSIS_LANGUAGE_VALUES = tuple(
    item.value for item in CUSTOMER_SELECTABLE_ANALYSIS_LANGUAGES
)
DEFAULT_ANALYSIS_LANGUAGE = AnalysisLanguage.ENGLISH


def analysis_language_definition(
    value: AnalysisLanguage | str,
) -> AnalysisLanguageDefinition:
    return ANALYSIS_LANGUAGE_REGISTRY[AnalysisLanguage(value)]


def is_customer_selectable_analysis_language(
    value: AnalysisLanguage | str,
) -> bool:
    try:
        definition = analysis_language_definition(value)
    except (KeyError, ValueError):
        return False
    return definition.generation_supported and definition.customer_selectable


def resolve_analysis_language(
    explicit: AnalysisLanguage | str | None,
    saved_default: AnalysisLanguage | str | None,
) -> AnalysisLanguage:
    """Resolve one customer execution language without consulting UI locale."""
    if explicit is not None:
        language = AnalysisLanguage(explicit)
        if not is_customer_selectable_analysis_language(language):
            raise ValueError("analysis language is not customer-selectable")
        return language
    if saved_default is not None:
        language = AnalysisLanguage(saved_default)
        if is_customer_selectable_analysis_language(language):
            return language
    return DEFAULT_ANALYSIS_LANGUAGE


def analysis_direction(value: AnalysisLanguage | str | None) -> AnalysisDirection:
    if value is None:
        return AnalysisDirection.AUTO
    try:
        return analysis_language_definition(value).direction
    except (KeyError, ValueError):
        return AnalysisDirection.AUTO


def analysis_language_prompt_instruction(
    value: AnalysisLanguage | str,
) -> str:
    definition = analysis_language_definition(value)
    return (
        f"Write every generated natural-language analysis field in "
        f"{definition.prompt_name}. Keep JSON field names and enum values exactly "
        "as defined. Copy source_filename and exact_quote verbatim from the source; "
        "never translate or paraphrase source evidence."
    )
