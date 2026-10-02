"""Deterministic "Matches your profile" rule (D1-08).

Replaces the Hunter numeric score on customer surfaces. A tender matches a company
profile when its country is one of the profile's target countries (target regions
are expanded to their countries) or when one of the profile's target services is
found in the tender's classification or notice text.

Because each match is shown to the customer as a fact ("Service match: IT"), terms
are matched on word boundaries, not as raw substrings. The Explorer service filter
uses the same rule (integration fix 3d):

* a country matches as a whole phrase ("Niger" does not match "Nigeria");
* an acronym term (upper case, at most 4 letters: "IT", "ICT") matches only as a
  whole, case-sensitive word (not "furniture", "district" or the pronoun "it");
* any other term matches case-insensitively at the start of a word, so stems still
  work ("consult" → "consulting", "строител" → "строительство") but "road" does not
  match "broadband".

The rule is expressed once as (pattern, case_sensitive) pairs and evaluated both in
PostgreSQL (list membership, counts) and in Python (the per-item facts), so the two
cannot disagree; a test compares them on a real PostgreSQL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, case, literal, or_


@dataclass(frozen=True)
class ProfileTargets:
    countries: tuple[str, ...] = ()
    services: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.countries and not self.services


def profile_targets(
    target_countries: Any,
    target_regions: Any,
    target_services: Any,
) -> ProfileTargets:
    """Normalize a profile's stored targets; unknown shapes are ignored, never guessed."""
    from app.api.endpoints.tenders import _expanded_region_countries

    def strings(value: Any) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    countries: list[str] = []
    seen: set[str] = set()
    for country in [*strings(target_countries), *_expanded_region_countries(strings(target_regions))]:
        key = country.casefold()
        if key not in seen:
            countries.append(country)
            seen.add(key)
    services: list[str] = []
    seen_services: set[str] = set()
    for service in strings(target_services):
        key = service.casefold()
        if key not in seen_services:
            services.append(service)
            seen_services.add(key)
    return ProfileTargets(tuple(countries), tuple(services))


# ---- one rule, two evaluators ---------------------------------------------------------------

_SERVICE_COLUMNS = (
    "sector", "category", "procurement_category", "procurement_method", "notice_type", "title", "description",
)


def _escape(term: str) -> str:
    """Escape regex punctuation; letters, digits and spaces stay literal in both dialects."""
    return re.sub(r"([^\w ])", r"\\\1", term, flags=re.UNICODE)


def _country_rule(country: str) -> tuple[str, bool]:
    return rf"\m{_escape(country)}\M", False


def _service_rules(service: str) -> list[tuple[str, bool]]:
    from app.api.endpoints.tenders import SERVICE_SEARCH_TERMS

    rules = []
    for term in SERVICE_SEARCH_TERMS.get(service, (service,)):
        acronym = term.isupper() and len(term) <= 4
        rules.append((rf"\m{_escape(term)}\M", True) if acronym else (rf"\m{_escape(term)}", False))
    return rules


def _sql(column: Any, rule: tuple[str, bool]):
    pattern, case_sensitive = rule
    return column.op("~" if case_sensitive else "~*")(pattern)


def _python(text_value: str, rule: tuple[str, bool]) -> bool:
    pattern, case_sensitive = rule
    # PostgreSQL \m / \M (start / end of word) as Python look-arounds.
    translated = pattern.replace(r"\m", r"(?<!\w)").replace(r"\M", r"(?!\w)")
    return re.search(translated, text_value, 0 if case_sensitive else re.IGNORECASE) is not None


def _service_predicates(services: Any) -> list[Any]:
    from app.models.all_models import Tender

    return [
        _sql(getattr(Tender, column), rule)
        for service in services
        for rule in _service_rules(service)
        for column in _SERVICE_COLUMNS
    ]


def service_match_condition(services: Any):
    """SQL predicate: at least one service matches by the whole-word rule above.

    The Explorer service *filter* uses this too (integration fix 3d), so a tender
    listed under "Service: IT" is exactly one whose facts say "Service match: IT".
    """
    predicates = _service_predicates(services)
    return or_(*predicates) if predicates else None


def _country_condition(targets: ProfileTargets):
    from app.models.all_models import Tender

    predicates = [_sql(Tender.country, _country_rule(country)) for country in targets.countries]
    return or_(*predicates) if predicates else None


def _service_condition(targets: ProfileTargets):
    return service_match_condition(targets.services)


def profile_match_condition(targets: ProfileTargets):
    """SQL predicate: at least one country or service match. None when there are no targets."""
    conditions = [value for value in (_country_condition(targets), _service_condition(targets)) if value is not None]
    return or_(*conditions) if conditions else None


# Ranking tiers (D2-02): 1 country and service, 2 country only, 3 service only.
TIER_COUNTRY_AND_SERVICE = 1
TIER_COUNTRY = 2
TIER_SERVICE = 3
TIER_NONE = 4


def profile_match_tier_expression(targets: ProfileTargets):
    """SQL tier of a tender under the same rules as ``profile_match_tier``."""
    country = _country_condition(targets)
    service = _service_condition(targets)
    whens = []
    if country is not None and service is not None:
        whens.append((and_(country, service), TIER_COUNTRY_AND_SERVICE))
    if country is not None:
        whens.append((country, TIER_COUNTRY))
    if service is not None:
        whens.append((service, TIER_SERVICE))
    return case(*whens, else_=TIER_NONE) if whens else literal(TIER_NONE)


def profile_match_tier(country: str | None, services: list[str] | tuple[str, ...]) -> int:
    """Tier of one ``tender_profile_match`` result."""
    if country and services:
        return TIER_COUNTRY_AND_SERVICE
    if country:
        return TIER_COUNTRY
    if services:
        return TIER_SERVICE
    return TIER_NONE


def tender_profile_match(tender: Any, targets: ProfileTargets) -> tuple[str | None, list[str]]:
    """``(matched_country, matched_services)`` for one tender, by the same rules as the SQL."""
    country_text = str(getattr(tender, "country", None) or "")
    matched_country = next(
        (country for country in targets.countries if _python(country_text, _country_rule(country))), None
    ) if country_text else None
    texts = [str(getattr(tender, column, None) or "") for column in _SERVICE_COLUMNS]
    matched_services = [
        service
        for service in targets.services
        if any(_python(text_value, rule) for rule in _service_rules(service) for text_value in texts if text_value)
    ]
    return matched_country, matched_services
