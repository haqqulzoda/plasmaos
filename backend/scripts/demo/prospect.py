"""S1 prospect preview: "<Firm> — Plasma preview", built from a firm's public records.

    python scripts/demo/seed_demo.py --target local --prospect-file prospect.json --dry-run
    python scripts/demo/seed_demo.py --target local --prospect-file prospect.json --confirm SEED_DEMO
    python scripts/demo/seed_demo.py --target local --prospect-file prospect.json --confirm SEED_DEMO --resume pv20261010-1
    python scripts/demo/seed_demo.py --target local --list-previews
    python scripts/demo/seed_demo.py --target local --archive-preview <organization-id> --confirm SEED_DEMO

The prospect file (see scripts/demo/prospect.example.json) holds only public facts: firm
name, country, services, sectors, 3–8 project references each with the public URL it came
from, and optional experts. Contact details are refused (the schema forbids unknown keys).

What a run does
- creates a private organization "<Firm> — Plasma preview" whose company profile belongs to
  a per-run steward (reserved ``.invalid`` e-mail, can never sign in) and adds the demo user
  (plasmatest0@gmail.com) as an OWNER. Previews coexist: the demo user switches between them
  with the organization switcher; no other organization is touched;
- records the firm, its references and experts as UNVERIFIED with provenance
  ``{"demo": true, "seed": "s1-prospect", "origin": "public_records", ...}``; every visible
  scope and note says "From public records, unverified" and names the source URL;
- picks one open World Bank Request for Expression of Interest (firm-level consulting) that
  matches the firm's sectors (country first), analyses it, confirms the review in bulk as the
  D3-04 seed does, and generates EOI v1 (DOCX + PDF).

Never contacts anyone: it creates no user that can sign in, approves no account, sends no
broadcast or e-mail (event staging is suppressed), and never fetches the source URLs. The
demo user must already exist and be approved. Analysis and the optional EOI relevance notes
use the configured AI provider, like any analysis.

Archive: revokes every membership except the steward's (nobody who can sign in sees it any
more), renames the organization "... (archived YYYY-MM-DD)" and stamps the profile notes.
Records are kept; the analysis and EOI tables are append-only.
"""

from __future__ import annotations

import calendar
from collections import Counter
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import re
import time
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import Tender, TenderDocument, User
from app.models.base import MembershipState
from app.models.candidate_retrieval import CVVersion, Expert, Firm, ProjectReference
from app.models.company import CompanyProfile
from app.models.tenancy import Membership, Organization

SEED = "s1-prospect"
PREVIEW_SUFFIX = " — Plasma preview"
PUBLIC_RECORDS = "From public records, unverified."
LABEL_PREFIX = "pv"
DEFAULT_ANALYSIS_TIMEOUT = 480.0  # the whole run must stay under ten minutes
REOI_NOTICE_TYPE = r"expression\s+of\s+interest"
LEDGER_MIN_NOTICE_CHARACTERS = 5_000
# S1-7: ledger previews look at Central Asian REOIs only (the firm's own bid countries first), unless --allow-global.
CENTRAL_ASIA = ("Uzbekistan", "Kazakhstan", "Kyrgyz Republic", "Tajikistan", "Turkmenistan", "Central Asia")
# S1-8: a Central Asian REOI qualifies from 2,500 characters, but one under LEDGER_MIN_NOTICE_CHARACTERS is
# kept only when its analysis extracts at least SHORT_NOTICE_MIN_REQUIREMENTS requirements. Outside Central
# Asia (--allow-global) the 5,000-character floor stays.
CENTRAL_ASIA_MIN_NOTICE_CHARACTERS = 2_500
SHORT_NOTICE_MIN_REQUIREMENTS = 4
DEFAULT_REPLAY_DAYS = 120
DRAFT_STATUS = "NOT_REVIEWED_BY_TEAM"  # the EOI cover and status read "Draft — not reviewed by your team"

# ---- the prospect file -------------------------------------------------------------------------------

_PARTIAL_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")


def _partial_date(value: str | None, *, end: bool) -> date | None:
    """"2019", "2019-06" or "2019-06-30"; a partial date takes the first (start) or last (end) day."""
    if value is None:
        return None
    match = _PARTIAL_DATE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"dates are YYYY, YYYY-MM or YYYY-MM-DD, got {value!r}")
    year, month, day = int(match.group(1)), match.group(2), match.group(3)
    if day:
        return date(year, int(month), int(day))
    if month:
        m = int(month)
        return date(year, m, calendar.monthrange(year, m)[1] if end else 1)
    return date(year, 12, 31) if end else date(year, 1, 1)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProspectReference(_Strict):
    project_name: str = Field(min_length=2, max_length=700)
    source_url: HttpUrl
    client_name: str | None = Field(default=None, max_length=500)
    country: str | None = Field(default=None, max_length=150)
    sector: str | None = Field(default=None, max_length=300)
    service: str | None = Field(default=None, max_length=300)
    role: Literal["LEAD", "JV_MEMBER", "CONSORTIUM_MEMBER", "SUBCONSULTANT", "SUBCONTRACTOR", "OTHER", "UNKNOWN"] = "UNKNOWN"
    start_date: str | None = None
    completion_date: str | None = None
    contract_value: float | None = Field(default=None, ge=0)
    contract_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    scope: str | None = Field(default=None, max_length=8000)

    @field_validator("start_date", "completion_date")
    @classmethod
    def _dates(cls, value: str | None) -> str | None:
        _partial_date(value, end=False)
        return value

    @model_validator(mode="after")
    def _currency_with_value(self):
        if self.contract_value is not None and self.contract_currency is None:
            raise ValueError(f"{self.project_name!r}: contract_value needs contract_currency")
        return self


class ProspectExpert(_Strict):
    name: str = Field(min_length=2, max_length=500)
    title: str = Field(min_length=2, max_length=300)
    source_url: HttpUrl
    years_experience: int | None = Field(default=None, ge=0, le=70)
    languages: list[str] = Field(default_factory=list, max_length=20)
    specializations: list[str] = Field(default_factory=list, max_length=30)


class Prospect(_Strict):
    firm_name: str = Field(min_length=2, max_length=200)
    country: str = Field(min_length=2, max_length=150)
    services: list[str] = Field(min_length=1, max_length=30)
    sectors: list[str] = Field(min_length=1, max_length=20)
    regions: list[str] = Field(default_factory=list, max_length=20)
    references: list[ProspectReference] = Field(min_length=3, max_length=8)
    experts: list[ProspectExpert] = Field(default_factory=list, max_length=12)

    @field_validator("firm_name")
    @classmethod
    def _not_a_preview_name(cls, value: str) -> str:
        if value.endswith(PREVIEW_SUFFIX.strip()) or "— Plasma preview" in value:
            raise ValueError("firm_name is the firm's own name, without the preview suffix")
        return value

    @model_validator(mode="after")
    def _distinct_projects(self):
        names = [item.project_name.casefold() for item in self.references]
        if len(set(names)) != len(names):
            raise ValueError("reference project_name values must be distinct")
        return self

    @property
    def organization_name(self) -> str:
        return self.firm_name + PREVIEW_SUFFIX


class LedgerProspect(Prospect):
    """A prospect built from the award ledger: references are the firm's consulting AWARDS only (one is enough)."""

    references: list[ProspectReference] = Field(min_length=1, max_length=8)
    award_keywords: list[str] = Field(default_factory=list, max_length=300)
    # word -> weight: the number of the firm's assignment titles that contain it; 0.5 for a word found only in
    # project names and sector tags
    award_keyword_weights: dict[str, float] = Field(default_factory=dict)
    award_notice_ids: list[str] = Field(default_factory=list, max_length=50)
    # S1-7: every country the firm bid in (any status, any category): REOIs there are tried first
    bid_countries: list[str] = Field(default_factory=list, max_length=20)


# Words that occur in almost every consulting title: never used to match an REOI to a firm's awards.
_GENERIC_AWARD_WORDS = {
    "services", "service", "consulting", "consultancy", "consultant", "consultants", "project", "projects",
    "development", "support", "program", "programme", "technical", "assistance", "national", "republic",
    "uzbekistan", "kazakhstan", "tajikistan", "kyrgyz", "kyrgyzstan", "preparation", "implementation", "provision",
    "selection", "activities", "including", "within", "under", "their", "other", "phase", "component", "firms",
    "company", "agency", "ministry", "improvement", "strengthening", "framework", "modernization", "modernisation",
    "various", "level", "regional", "region", "district", "districts", "areas", "public",
    # words that describe any assignment, not a firm's specialty
    "international", "group", "integrated", "identification", "system", "systems", "based", "through", "years",
    "access", "enhancing", "sector", "sectors", "plans", "capacity", "building", "institutional", "management",
    "training", "operational", "establishment", "general", "specific", "related", "complete", "existing",
    "experience", "requirements", "implementing", "analysis", "review", "report", "reports", "standard", "standards",
}


def award_keywords(texts: list[str]) -> list[str]:
    words: set[str] = set()
    for text in texts:
        for word in re.findall(r"[^\W\d_]{5,}", (text or "").casefold()):
            if word not in _GENERIC_AWARD_WORDS:
                words.add(word)
    return sorted(words)


async def prospect_from_ledger(db: AsyncSession, name: str, *, country: str | None = None) -> LedgerProspect:
    """The prospect firm and its references from the firm's ledger consulting AWARDS (evaluated or rejected
    bids never become references). ``name`` is the normalized firm name as in the target list."""
    from sqlalchemy import and_

    from app.models.award_ledger import AwardNoticeSnapshot, AwardOutcome
    from app.services.award_ledger import CONSULTING_GROUP
    from app.services.award_ledger_parser import normalize_firm_name
    from app.services.award_ledger_reports import (
        MARKET_SIZING_COUNTRIES, _award_value, _ledger_rows, award_value_flag, country_key,
    )
    from scripts.demo.seed_demo import DemoSeedError

    wanted = normalize_firm_name(name)
    if not wanted:
        raise DemoSeedError("--from-ledger needs a firm name")
    first = wanted.split()[0]
    rows = await _ledger_rows(db, where=and_(
        AwardOutcome.status == "AWARDED", AwardOutcome.procurement_group == CONSULTING_GROUP,
        AwardOutcome.country.in_(MARKET_SIZING_COUNTRIES), AwardOutcome.bidder_name.ilike(f"%{first}%"),
    ))
    rows = [(row, sectors) for row, sectors in rows if normalize_firm_name(row.bidder_name) == wanted]
    if country:
        rows = [(row, sectors) for row, sectors in rows if country_key(row.bidder_country) == country_key(country)]
    if not rows:
        where = f" from {country}" if country else ""
        raise DemoSeedError(f"no consulting award in the ledger for {wanted!r}{where}; only awards become references")
    countries = sorted({row.bidder_country or "" for row, _ in rows})
    if len(countries) > 1:
        raise DemoSeedError(f"{wanted!r} is published with several countries {countries}; pick one with --country")
    agencies = dict((await db.execute(
        select(AwardNoticeSnapshot.id, AwardNoticeSnapshot.raw_metadata["agency_name"].astext)
        .where(AwardNoticeSnapshot.id.in_({row.snapshot_id for row, _ in rows}))
    )).all())
    rows.sort(key=lambda item: (item[0].award_date or item[0].notice_date or date.min, item[0].notice_id), reverse=True)
    names = Counter(row.bidder_name for row, _ in rows if row.member_count == 1) or Counter(row.bidder_name for row, _ in rows)
    firm_name = names.most_common(1)[0][0].replace(PREVIEW_SUFFIX.strip(), "").strip()[:200]
    sectors = Counter(sector for _, row_sectors in rows for sector in row_sectors)
    references, titles, seen_titles, assignment_words = [], [], Counter(), Counter()
    for row, row_sectors in rows[:8]:
        title = (row.package_title or row.project_name or row.notice_id)[:640]
        seen_titles[title.casefold()] += 1
        if seen_titles[title.casefold()] > 1:
            title = f"{title} ({row.notice_id})"
        currency, amount = _award_value(row)
        if award_value_flag(row) is not None:
            currency, amount = None, None  # a flagged source error is not shown as the firm's contract value
        awarded = row.award_date or row.notice_date
        references.append(ProspectReference(
            project_name=title, source_url=row.notice_url, client_name=(agencies.get(row.snapshot_id) or None),
            country=row.country, sector=row_sectors[0] if row_sectors else None, service="Consulting services",
            role="LEAD" if row.member_count == 1 else "JV_MEMBER",
            start_date=awarded.isoformat() if awarded else None,
            contract_value=float(amount) if amount is not None else None, contract_currency=currency if amount is not None else None,
            scope=_reference_scope(row, agencies.get(row.snapshot_id), row_sectors, awarded, currency, amount),
        ))
        titles += [row.package_title or "", row.project_name or "", *row_sectors]
        assignment_words.update(set(award_keywords([row.package_title or ""])))
    bid_rows = await _ledger_rows(db, where=and_(
        AwardOutcome.country.in_(MARKET_SIZING_COUNTRIES), AwardOutcome.bidder_name.ilike(f"%{first}%"),
    ))
    bid_countries = sorted({row.country for row, _ in bid_rows
                            if normalize_firm_name(row.bidder_name) == wanted and row.country
                            and country_key(row.bidder_country) == country_key(countries[0])})
    return LedgerProspect(
        bid_countries=bid_countries,
        firm_name=firm_name, country=countries[0] or "Unknown", services=["Consulting services"],
        sectors=[sector for sector, _ in sectors.most_common(5)] or ["Consulting"], references=references,
        award_keywords=award_keywords(titles), award_notice_ids=[row.notice_id for row, _ in rows],
        award_keyword_weights={word: float(assignment_words[word]) if word in assignment_words else 0.5
                               for word in award_keywords(titles)},
    )


def _reference_scope(row, agency, sectors, awarded, currency, amount) -> str:
    """What the award notice says about the assignment, field by field; nothing is inferred or invented."""
    parts = [f"Assignment: {row.package_title}." if row.package_title else None,
             f"Project: {row.project_name}." if row.project_name else None,
             f"Client: {agency}." if agency else None,
             f"Sectors (project tags): {', '.join(sectors)}." if sectors else None,
             f"Selection method: {row.procurement_method}." if row.procurement_method else None,
             f"Awarded {awarded.year}." if awarded else None,
             f"Contract value as published: {currency} {amount:,.2f}." if amount is not None else None,
             f"World Bank contract award notice {row.notice_id}."]
    return " ".join(part for part in parts if part)[:7_500]


def rank_by_distinctive_words(candidates: list, prospect: LedgerProspect, corpus: list | None = None) -> list[tuple[float, Any]]:
    """Re-rank REOI candidates by the words of the firm's awards found in the REOI title, each weighted by
    its inverse document frequency over the candidates' titles (a word in many open REOI titles, such as
    "management" or "system", says little) and by how many of the firm's assignment titles contain it (a
    firm's specialty, e.g. "audit" in every title of an audit firm, says a lot): TF-IDF. Words found only in
    project names and sector tags weigh 0.5. Matches in the
    notice text only break ties (descriptions repeat common words), then region, then latest deadline."""
    import math

    # Frequencies over every open REOI (``corpus``), smoothed so a title match always scores above zero, even
    # when a word is in every title of a small open set.
    titles = [set(re.findall(r"[^\W\d_]+", (item.tender.title or "").casefold())) for item in (corpus or candidates)]
    total = max(len(titles), 1)
    frequency = Counter(word for words in titles for word in words)
    weights = prospect.award_keyword_weights or {word: 1.0 for word in prospect.award_keywords}

    def score(item) -> float:
        return round(sum(math.log(1 + total / max(frequency.get(word, 0), 1)) * weights.get(word, 0.5)
                         for word in item.sectors_in_title), 2)

    scored = [(score(item), item) for item in candidates]
    scored.sort(key=lambda pair: (-pair[0], -len(pair[1].sectors_in_text), pair[1].region_rank,
                                  -(pair[1].tender.deadline.timestamp() if pair[1].tender.deadline else 0)))
    return scored


def load_prospect(path: str | Path) -> Prospect:
    from scripts.demo.seed_demo import DemoSeedError

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DemoSeedError(f"--prospect-file {path}: {exc}") from exc
    try:
        return Prospect.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in error['loc']) or 'file'}: {error['msg']}" for error in exc.errors())
        raise DemoSeedError(f"--prospect-file {path} is invalid: {problems}") from exc


# ---- mapping to records ------------------------------------------------------------------------------

def provenance(label: str, source_url: str | None = None) -> dict[str, Any]:
    tag: dict[str, Any] = {"demo": True, "seed": SEED, "run": label, "origin": "public_records",
                           "verification": "unverified", "note": PUBLIC_RECORDS}
    if source_url:
        tag["source_url"] = source_url
    return tag


def profile_values(prospect: Prospect) -> dict[str, Any]:
    """Only what the prospect file states: no director, address, phone or tax number is invented."""
    return {
        "industry": ", ".join(prospect.sectors)[:255],
        "target_regions": prospect.regions,
        "target_countries": [prospect.country],
        "target_services": prospect.services,
    }


def self_firm_values(prospect: Prospect, label: str) -> dict[str, Any]:
    sources = sorted({str(item.source_url) for item in prospect.references})
    return {
        "display_name": prospect.firm_name, "canonical_name": prospect.firm_name, "country": prospect.country,
        "regions": prospect.regions, "services": prospect.services, "sectors": prospect.sectors, "capabilities": [],
        "source_type": "MANUAL", "source_provenance": {**provenance(label), "sources": sources},
        "evidence_state": "UNVERIFIED",
        "private_notes": f"Plasma preview. {PUBLIC_RECORDS} Sources: " + " ".join(sources),
    }


def reference_values(item: ProspectReference, label: str) -> dict[str, Any]:
    url = str(item.source_url)
    scope = f"{item.scope}\n\n" if item.scope else ""
    completion = _partial_date(item.completion_date, end=True)
    return {
        "project_name": item.project_name, "client_name": item.client_name, "country": item.country,
        "sector": item.sector, "service": item.service, "role": item.role,
        "contract_value": Decimal(str(item.contract_value)) if item.contract_value is not None else None, "contract_currency": item.contract_currency if item.contract_value is not None else None,
        "value_basis": "CONTRACT_TOTAL" if item.contract_value is not None else "UNKNOWN",
        "start_date": _partial_date(item.start_date, end=False), "completion_date": completion,
        "completion_state": "COMPLETED" if completion and completion <= date.today() else "UNKNOWN",
        "relevant_scope": f"{scope}{PUBLIC_RECORDS} Source: {url}",
        "evidence_provenance": provenance(label, url), "evidence_state": "UNVERIFIED",
    }


def expert_values(item: ProspectExpert, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    url = str(item.source_url)
    qualifications = [f"{item.years_experience} years of professional experience"] if item.years_experience is not None else []
    expert = {
        "scope": "ORGANIZATION_PRIVATE", "display_name": item.name, "qualifications": qualifications,
        "languages": item.languages, "specializations": [item.title, *item.specializations],
        "consent_state": "NOT_REQUIRED_PRIVATE", "evidence_state": "UNVERIFIED",
        "source_provenance": provenance(label, url), "private_notes": f"{PUBLIC_RECORDS} Source: {url}",
    }
    qualification: dict[str, Any] = {"title": item.title}
    if item.years_experience is not None:
        qualification["years_experience"] = item.years_experience
    cv = {"education": [], "qualifications": [qualification], "certifications": [], "assignments": [],
          "languages": [{"language": language} for language in item.languages],
          "evidence_provenance": provenance(label, url), "evidence_state": "UNVERIFIED"}
    return expert, cv


def sector_keywords(prospect: Prospect) -> dict[str, tuple[str, ...]]:
    """Ranking words per stated sector: the sector's own words, plus the D3-04 keyword group it names."""
    from scripts.demo import demo_data as data

    groups: dict[str, tuple[str, ...]] = {}
    for sector in prospect.sectors:
        value = sector.casefold()
        words = {word for word in re.findall(r"[^\W\d_]{4,}", value) if word not in {"and", "services", "sector", "other"}}
        for name, keywords in data.SECTOR_KEYWORDS.items():
            if name in value or any(keyword in value for keyword in keywords):
                words.update(keywords)
        if words:
            groups[sector] = tuple(sorted(words))
    return groups


_GENERIC_SERVICE_WORDS = {"services", "service", "consulting", "consultancy", "other", "general", "and"}


def service_keywords(prospect: Prospect) -> dict[str, tuple[str, ...]]:
    """Words of each stated service (e.g. "supervision", "feasibility"), a tie-breaker between notices."""
    groups = {}
    for service in prospect.services:
        words = {word for word in re.findall(r"[^\W\d_]{4,}", service.casefold()) if word not in _GENERIC_SERVICE_WORDS}
        if words:
            groups[service] = tuple(sorted(words))
    return groups


# ---- labels and lookups ------------------------------------------------------------------------------

def is_prospect_label(value: str) -> bool:
    return re.fullmatch(LABEL_PREFIX + r"\d{8}-\d+", value or "") is not None


async def next_label(db: AsyncSession, today: date) -> str:
    from scripts.demo.seed_demo import STEWARD_DOMAIN

    stem = LABEL_PREFIX + today.strftime("%Y%m%d")
    emails = (await db.scalars(select(User.email).where(User.email.like(f"demo-steward+{stem}-%@{STEWARD_DOMAIN}")))).all()
    numbers = [int(match.group(1)) for email in emails if (match := re.fullmatch(rf"demo-steward\+{stem}-(\d+)@.*", email or ""))]
    return f"{stem}-{max(numbers, default=0) + 1}"


def _marker(label: str) -> str:
    from scripts.demo.seed_demo import PROFILE_MARKER

    return f"{PROFILE_MARKER} {json.dumps(provenance(label))}"


async def preview_organizations(db: AsyncSession) -> list[tuple[Organization, CompanyProfile]]:
    from scripts.demo.seed_demo import PROFILE_MARKER

    rows = (await db.execute(
        select(Organization, CompanyProfile).join(CompanyProfile, CompanyProfile.id == Organization.legacy_company_profile_id)
        .where(CompanyProfile.notes.startswith(PROFILE_MARKER), CompanyProfile.notes.contains(f'"seed": "{SEED}"'))
        .order_by(Organization.created_at, Organization.id)
    )).all()
    return [(row[0], row[1]) for row in rows]


def _label_of(profile: CompanyProfile) -> str | None:
    match = re.search(r'"run": "([^"]+)"', profile.notes or "")
    return match.group(1) if match else None


def _is_archived(profile: CompanyProfile) -> bool:
    return '"archived_at"' in (profile.notes or "")


async def _organization_for_label(db: AsyncSession, label: str) -> Organization | None:
    for organization, profile in await preview_organizations(db):
        if _label_of(profile) == label:
            return organization
    return None


async def demo_user_ready(db: AsyncSession, email: str) -> User:
    from app.core.access import USER_APPROVAL_APPROVED, is_disabled_account, is_rejected_account
    from scripts.demo.seed_demo import DemoSeedError

    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or user.approval_status != USER_APPROVAL_APPROVED or is_disabled_account(user) or is_rejected_account(user):
        state = "missing" if user is None else user.approval_status
        raise DemoSeedError(f"{email} is {state}; the prospect seed never creates or approves accounts "
                            "(approve it in the admin console, or run the D3-04 seed once)")
    return user


# ---- tender ------------------------------------------------------------------------------------------

def scope_tier(country: str | None, prospect: Prospect, allow_global: bool) -> int | None:
    """0 = one of the firm's own bid countries, 1 = elsewhere in Central Asia, 2 = outside (only with --allow-global)."""
    if country in getattr(prospect, "bid_countries", []):
        return 0
    if country in CENTRAL_ASIA:
        return 1
    return 2 if allow_global else None


async def replay_candidates(db: AsyncSession, prospect: "LedgerProspect", *, demo_date: date, days: int,
                            keywords: dict[str, tuple[str, ...]]) -> list:
    """S1-8: CLOSED firm-level Central Asian consulting REOIs published within ``days`` of the demo date, with
    an official notice (stored, or derived from the tender as a refresh would) of at least 2,500 characters;
    own bid countries first, then by the distinctive words of the firm's awards, then the latest deadline."""
    from datetime import datetime as _datetime
    from datetime import time as _time
    from datetime import timedelta, timezone

    from app.core.deadline_truth import deadline_not_passed_sql
    from app.services.official_notice import build_official_notice_text
    from scripts.demo.seed_demo import Candidate, _notice_characters, _region, _sectors, firm_level_consulting_condition

    since = _datetime.combine(demo_date - timedelta(days=days), _time.min, tzinfo=timezone.utc)
    rows = (await db.execute(select(Tender, _notice_characters()).where(
        firm_level_consulting_condition(REOI_NOTICE_TYPE), Tender.country.in_(CENTRAL_ASIA),
        Tender.publication_date >= since, Tender.deadline.is_not(None), ~deadline_not_passed_sql(Tender),
    ).limit(2_000))).all()
    items = []
    for tender, characters in rows:
        characters = int(characters or 0) or len(build_official_notice_text(tender) or "")
        if characters < CENTRAL_ASIA_MIN_NOTICE_CHARACTERS:
            continue
        in_title = _sectors(tender.title or "", keywords, whole_words=True)
        in_text = tuple(name for name in _sectors(f"{tender.sector or ''} {tender.description or ''}", keywords,
                                                  whole_words=True) if name not in in_title)
        region, rank = _region(tender.country, prospect.country)
        item = Candidate(tender, characters, in_title, in_text, region, rank)
        item.__dict__["_closed_on"] = tender.deadline.date()
        items.append(item)
    scored = rank_by_distinctive_words(items, prospect, corpus=items)
    for score, item in scored:
        item.__dict__["_score"] = score
        item.__dict__["_tier"] = scope_tier(item.tender.country, prospect, False)
    scored.sort(key=lambda pair: (pair[1].__dict__["_tier"], -pair[0], pair[1].region_rank, -pair[1].tender.deadline.timestamp()))
    return [item for _score, item in scored]


async def candidate_pools(db: AsyncSession, prospect: Prospect, *, demo_date: date, exclude: set, allow_global: bool = False,
                          replay_days: int = 0) -> list[tuple[str, list]]:
    """Ledger previews (S1-8), in order: open Central Asian REOIs (own bid countries first; notice >= 2,500
    characters), CLOSED Central Asian REOIs published within ``replay_days`` (replay), then, with
    --allow-global only, open REOIs outside Central Asia sharing a word with the firm's awards (>= 5,000)."""
    from scripts.demo.seed_demo import ranked_candidates

    keywords = {word: (word,) for word in prospect.award_keywords}
    candidates = await ranked_candidates(db, demo_date=demo_date, exclude=exclude, keywords=keywords,
                                         home_country=prospect.country, notice_type=REOI_NOTICE_TYPE,
                                         whole_words=True, title_only=True,
                                         min_notice_characters=CENTRAL_ASIA_MIN_NOTICE_CHARACTERS)
    in_scope = [item for item in candidates if scope_tier(item.tender.country, prospect, allow_global) is not None]
    scored = rank_by_distinctive_words(in_scope, prospect, corpus=candidates)
    for score, item in scored:
        item.__dict__["_score"] = score
        item.__dict__["_tier"] = scope_tier(item.tender.country, prospect, allow_global)
    scored.sort(key=lambda pair: (pair[1].__dict__["_tier"], -pair[0], pair[1].region_rank))
    open_central_asia = [item for _score, item in scored if item.__dict__["_tier"] < 2]
    outside = [item for score, item in scored if item.__dict__["_tier"] == 2 and score > 0
               and item.notice_characters >= LEDGER_MIN_NOTICE_CHARACTERS]
    replay = (await replay_candidates(db, prospect, demo_date=demo_date, days=replay_days, keywords=keywords)
              if replay_days > 0 and isinstance(prospect, LedgerProspect) else [])
    pools = [("open", open_central_asia), ("replay", replay)]
    if allow_global:
        pools.append(("global", outside))
    return pools


async def pick_tender(db: AsyncSession, prospect: Prospect, *, demo_date: date, externals: list[str],
                      allow_global: bool = False, replay_days: int = 0):
    """The pinned tender, else the best-matching firm-level World Bank REOI; and the candidates of its pool
    (ledger previews: see candidate_pools; the pool name is in each candidate's ``_pool``)."""
    from scripts.demo.seed_demo import DemoSeedError, ranked_candidates, resolve_pinned

    if len(externals) > 1:
        raise DemoSeedError("a prospect preview has one pursuit: give --tender-external at most once")
    ledger = isinstance(prospect, LedgerProspect)
    pinned = [await resolve_pinned(db, value, allow_closed=ledger and replay_days > 0) for value in externals]
    if ledger:
        pools = await candidate_pools(db, prospect, demo_date=demo_date, exclude={item.id for item in pinned},
                                      allow_global=allow_global, replay_days=replay_days)
        for name, items in pools:
            for item in items:
                item.__dict__["_pool"] = name
        matching = next((items for _name, items in pools if items), [])
    else:
        keywords = sector_keywords(prospect)
        candidates = await ranked_candidates(db, demo_date=demo_date, exclude={item.id for item in pinned},
                                             keywords=keywords, home_country=prospect.country, notice_type=REOI_NOTICE_TYPE,
                                             whole_words=True, title_only=True, service_keywords=service_keywords(prospect))
        matching = [item for item in candidates if item.sectors_in_title or item.sectors_in_text]
    if pinned:
        return pinned[0], matching
    if not matching:
        if ledger:
            replay = (f"and none closed within the last {replay_days} days to replay" if replay_days > 0
                      else "replay is off (--replay-days 0)")
            widen = "" if allow_global else ", or widen with --allow-global"
            raise DemoSeedError(
                f"no Central Asian World Bank REOI is open for {prospect.firm_name} (firm-level, closing on or after "
                f"{demo_date.isoformat()} + 7 days, official notice of at least {CENTRAL_ASIA_MIN_NOTICE_CHARACTERS:,} "
                f"characters; own bid countries {prospect.bid_countries or 'none'}, then the rest of Central Asia) {replay}"
                f"{'; nothing outside Central Asia shares a word with its awards' if allow_global else ''}. No fallback: "
                f"pin a tender with --tender-external world_bank:OP...{widen}")
        raise DemoSeedError(
            f"no open firm-level World Bank REOI closing on or after {demo_date.isoformat()} + 7 days matches the sectors "
            f"{prospect.sectors} (keywords {sorted({w for words in keywords.values() for w in words})}); "
            "pin one with --tender-external world_bank:OP...")
    return matching[0].tender, matching


def closed_on(tender: Tender) -> date | None:
    """The closing date of a tender whose deadline has passed (a replay), else None."""
    from app.core.deadline_truth import derived_status
    from app.models.base import TenderStatus

    status, _ = derived_status(tender.status, tender.source_system, tender.deadline, country=tender.country)
    if status in (TenderStatus.OPEN, TenderStatus.UNKNOWN) or tender.deadline is None:
        return None
    return tender.deadline.date()


# ---- plan, seed, archive -----------------------------------------------------------------------------

async def plan(sessions, options, prospect: Prospect, *, today: date | None = None) -> dict[str, Any]:
    from scripts.demo.seed_demo import CANDIDATES_SHOWN, _tender_summary, utcnow

    today = today or utcnow().date()
    demo_date = options.demo_date or today
    async with sessions() as db:
        label = options.resume or await next_label(db, today)
        user = await db.scalar(select(User).where(func.lower(User.email) == options.email))
        replay_days = getattr(options, "replay_days", 0) if isinstance(prospect, LedgerProspect) else 0
        tender, candidates = await pick_tender(db, prospect, demo_date=demo_date, externals=list(options.externals),
                                               allow_global=getattr(options, "allow_global", False), replay_days=replay_days)
        existing = await _organization_for_label(db, label)
        same_name = [str(org.id) for org, profile in await preview_organizations(db)
                     if org.display_name == prospect.organization_name and not _is_archived(profile) and _label_of(profile) != label]
        picked = _tender_summary(tender)
        replay_closed_on = closed_on(tender)
        picked["replay_closed_on"] = replay_closed_on.isoformat() if replay_closed_on else None
        pool = candidates[0].__dict__.get("_pool") if candidates else None
        shown = [{**item.summary(), "scope_tier": item.__dict__.get("_tier"), "score": item.__dict__.get("_score"),
                  "pool": item.__dict__.get("_pool"),
                  "closed_on": item.__dict__["_closed_on"].isoformat() if item.__dict__.get("_closed_on") else None}
                 for item in candidates[:max(CANDIDATES_SHOWN, getattr(options, "candidates", 1))]]
        top = next(({**item.summary(), "score": item.__dict__.get("_score"), "tier": item.__dict__.get("_tier")}
                    for item in candidates if item.tender.id == tender.id), None)
        await db.rollback()
    if top is None:
        why = ((f"replay on a closed notice (closed {replay_closed_on.isoformat()}); " if replay_closed_on else "")
               + "pinned with --tender-external")
    else:
        reasons = top["reasons"]
        tier = {0: "one of the firm's own bid countries", 1: "elsewhere in Central Asia", 2: "outside Central Asia"}
        tier_label = tier.get(top.get("tier"))
        replayed = (f"replay on a closed notice (closed {replay_closed_on.isoformat()}; no open Central Asian REOI "
                    "qualified); " if replay_closed_on else "")
        why = (replayed + (f"{tier_label}; " if tier_label else "") +
               (f"distinctive-word score {top['score']}; " if top.get("score") is not None else "") +
               f"words of the firm's awards in the REOI title: {reasons['sector_match_title'] or 'none'}; in the project "
               f"sectors or notice text: {reasons['sector_match_text'] or 'none'}; country {picked['country']} "
               f"({reasons['region']}); official notice {reasons['notice_characters']:,} characters; deadline {picked['deadline']}")
    return {
        "mode": "dry-run" if options.dry_run else "seed", "kind": "prospect-preview", "target": options.target, "label": label,
        "organization_name": prospect.organization_name, "organization_exists": existing is not None,
        "active_previews_with_this_name": same_name,
        "demo_user": options.email, "demo_user_ready": user is not None,
        "pursuit_tender": picked, "pinned": list(options.externals), "demo_date": demo_date.isoformat(),
        "source": "award ledger (awards only)" if isinstance(prospect, LedgerProspect) else "prospect file",
        "pick_reason": why,
        "match_rule": ("World Bank Request for Expression of Interest, consulting, firm-level. Pools in order: open "
                       "Central Asian REOIs closing on or after demo date + 7 days (official notice >= 2,500 characters; under "
                       "5,000 kept only if the analysis extracts >= 4 requirements); closed Central Asian REOIs published "
                       "within --replay-days (replay, labelled); with --allow-global, open REOIs elsewhere (>= 5,000 "
                       "characters, at least one word shared with the firm's awards in the title). Inside a pool, own bid "
                       "countries first, then ranked by a distinctive-word score (inverse frequency over the open "
                       "REOI titles times the number of the firm's assignment titles with the word; words only in project names "
                       "and sector tags weigh 0.5), then by words shared with the notice text, then region, then latest deadline") if isinstance(prospect, LedgerProspect) else (
                      "World Bank Request for Expression of Interest, consulting, firm-level, open, closing on or after demo date "
                      "+ 7 days, official notice >= 2,000 characters, at least one sector keyword (whole words); ranked by sector "
                      "words in the title, then service words in the title, then sector words in the project sectors and "
                      "notice text, then the firm's country, then region, then latest deadline"),
        "award_notice_ids": getattr(prospect, "award_notice_ids", []),
        "bid_countries": getattr(prospect, "bid_countries", []),
        "scope": "global (--allow-global)" if getattr(options, "allow_global", False) else
                 "Central Asia: own bid countries first, then the rest of Central Asia",
        "pool": pool, "replay_days": getattr(options, "replay_days", 0) if isinstance(prospect, LedgerProspect) else 0,
        "replay": {"closed_on": replay_closed_on.isoformat(), "label": replay_text(replay_closed_on)} if replay_closed_on else None,
        "sector_keywords": sector_keywords(prospect), "service_keywords": service_keywords(prospect),
        "candidates": shown,
        "will_create": {"own_references": len(prospect.references), "experts": len(prospect.experts),
                        "cv_versions": len(prospect.experts), "pursuits": 1, "eoi_drafts": 1},
        "contacts_anyone": False,
    }


async def seed_library(db: AsyncSession, *, organization_id: UUID, user: User, prospect: Prospect, label: str) -> dict[str, int]:
    from app.schemas.candidate_retrieval import (
        CVVersionCreateRequest, ExpertCreateRequest, ProjectReferenceCreateRequest, SelfFirmUpsertRequest,
    )
    from app.services.candidate_retrieval import create_cv_version, create_expert, create_project_reference, upsert_self_firm

    firm = await db.scalar(select(Firm).where(Firm.organization_id == organization_id))
    if firm is None:
        await upsert_self_firm(db, organization_id=organization_id, actor_user_id=user.id,
                               payload=SelfFirmUpsertRequest(**self_firm_values(prospect, label)))
        firm = await db.scalar(select(Firm).where(Firm.organization_id == organization_id))
    existing = set((await db.scalars(select(ProjectReference.project_name).where(ProjectReference.firm_id == firm.id))).all())
    for item in prospect.references:
        if item.project_name not in existing:
            await create_project_reference(db, organization_id=organization_id, firm_id=firm.id, actor_user_id=user.id, operator=False,
                                           payload=ProjectReferenceCreateRequest(**reference_values(item, label)))
    for item in prospect.experts:
        expert_payload, cv_payload = expert_values(item, label)
        row = await db.scalar(select(Expert).where(Expert.owner_organization_id == organization_id, Expert.display_name == item.name))
        expert_id = row.id if row is not None else (await create_expert(
            db, organization_id=organization_id, actor_user_id=user.id, operator=False,
            payload=ExpertCreateRequest(**expert_payload))).expert_id
        if await db.scalar(select(func.count(CVVersion.id)).where(CVVersion.expert_id == expert_id)) == 0:
            await create_cv_version(db, organization_id=organization_id, expert_id=expert_id, actor_user_id=user.id, operator=False,
                                    payload=CVVersionCreateRequest(**cv_payload))
    expert_ids = (await db.scalars(select(Expert.id).where(Expert.owner_organization_id == organization_id))).all()
    return {
        "own_references": await db.scalar(select(func.count(ProjectReference.id)).where(ProjectReference.firm_id == firm.id)) or 0,
        "experts": len(expert_ids),
        "cv_versions": await db.scalar(select(func.count(CVVersion.id)).where(CVVersion.expert_id.in_(expert_ids))) or 0,
    }


async def ensure_organization(db: AsyncSession, *, prospect: Prospect, label: str, demo_user: User, steward: User,
                              replay: tuple[str, date] | None = None):
    """The run's organization: the steward owns the profile (initial OWNER), the demo user is added as OWNER.
    A replay (canonical source key, closing date) names it "... · Replay on a closed notice (closed <date>) —
    for illustration" and leaves the marker the pursuit API reads (app.services.preview_replay)."""
    from app.services.preview_replay import replay_marker
    from app.core.access import COMPANY_APPROVAL_APPROVED, COMPANY_PILOT_ACTIVE
    from app.services.admin_activity import ACTION_COMPANY_APPROVED
    from app.services.organization_context import ensure_profile_organization
    from scripts.demo.seed_demo import DemoSeedError, _add_owner, _audit, utcnow

    organization = await _organization_for_label(db, label)
    if organization is None:
        name = prospect.organization_name + (f" · {replay_text(replay[1])}" if replay else "")
        marker = f" {replay_marker(*replay)}" if replay else ""
        profile = CompanyProfile(
            user_id=steward.id, created_by_user_id=demo_user.id, company_name=name,
            notes=f"{_marker(label)}{marker} Plasma preview for {prospect.firm_name}. {PUBLIC_RECORDS}",
            approval_status=COMPANY_APPROVAL_APPROVED, pilot_status=COMPANY_PILOT_ACTIVE, approved_at=utcnow(),
            **profile_values(prospect),
        )
        db.add(profile)
        await db.flush()
        await _audit(db, action=ACTION_COMPANY_APPROVED, user=steward, resource=profile,
                     reason="Prospect preview created by the S1 prospect seed.")
        context = await ensure_profile_organization(db, profile=profile)
        organization = context.organization
        await _add_owner(db, organization_id=organization.id, actor=context.membership, user_id=demo_user.id)
        await db.commit()
    membership = await db.scalar(select(Membership).where(
        Membership.organization_id == organization.id, Membership.user_id == demo_user.id, Membership.state == MembershipState.ACTIVE))
    if membership is None:
        raise DemoSeedError(f"the demo user has no active membership in {organization.display_name} (archived?)")
    return organization, membership


async def seed(sessions, options, prospect: Prospect, *, today: date | None = None, process_inline=None, note_call=None,
               prospect_build_seconds: float | None = None) -> dict[str, Any]:
    from app.services.notifications import SUPPRESS_EVENT_STAGING
    from scripts.demo.seed_demo import (
        CONFIRMATION, DemoSeedError, bulk_confirm, ensure_analysis, ensure_eoi, ensure_pursuit, ensure_steward,
    )

    if options.confirm != CONFIRMATION:
        raise DemoSeedError(f"writes require --confirm {CONFIRMATION}")
    started = time.monotonic()
    timings: dict[str, float] = {}

    def lap(name: str, since: float) -> float:
        now = time.monotonic()
        timings[name] = round(now - since, 1)
        return now

    SUPPRESS_EVENT_STAGING.set(True)
    if options.externals and isinstance(prospect, LedgerProspect) and getattr(options, "replay_days", 0) > 0:
        await ensure_official_notices(sessions, list(options.externals))
    summary = await plan(sessions, options, prospect, today=today)
    label = summary["label"]
    if options.resume is not None and not summary["organization_exists"]:
        raise DemoSeedError(f"--resume {label}: no prospect preview with that label")
    if options.resume is None and summary["active_previews_with_this_name"] and not getattr(options, "comparing", False):
        raise DemoSeedError(f"an active preview named {prospect.organization_name!r} already exists "
                            f"({', '.join(summary['active_previews_with_this_name'])}); archive it or --resume its label")
    mark = lap("plan", started)
    archived_others: list[dict[str, Any]] = []
    if options.resume is None and not getattr(options, "keep_others", False) and not getattr(options, "comparing", False):
        # Exclusive by default: the organization switcher never shows another prospect's name.
        async with sessions() as db:
            demo_user = await demo_user_ready(db, options.email)
            for organization, profile in await preview_organizations(db):
                active = await db.scalar(select(Membership.id).where(
                    Membership.organization_id == organization.id, Membership.user_id == demo_user.id,
                    Membership.state == MembershipState.ACTIVE))
                if active is not None and not _is_archived(profile):
                    archived_others.append(await _archive_one(db, organization, profile, today or utcnow_date()))
    mark = lap("archive_other_previews", mark)
    async with sessions() as db:
        demo_user = await demo_user_ready(db, options.email)
        steward = await ensure_steward(db, label)
        tender = await db.get(Tender, UUID(summary["pursuit_tender"]["tender_id"]))
        replay_closed_on = closed_on(tender)
        organization, membership = await ensure_organization(
            db, prospect=prospect, label=label, demo_user=demo_user, steward=steward,
            replay=(tender.canonical_source_key, replay_closed_on) if replay_closed_on else None)
        counts = await seed_library(db, organization_id=organization.id, user=demo_user, prospect=prospect, label=label)
        pursuit = await ensure_pursuit(db, organization_id=organization.id, user=demo_user, membership=membership, tender=tender)
        ids = (organization.id, pursuit.id, membership.id)
        organization_name = organization.display_name
        reviewer = demo_user.name or demo_user.email
    mark = lap("organization_and_records", mark)
    analysis = await ensure_analysis(sessions, organization_id=ids[0], pursuit_id=ids[1], membership=membership,
                                     timeout_seconds=options.analysis_timeout, poll_seconds=options.poll_seconds,
                                     process_inline=process_inline)
    mark = lap("analysis", mark)
    async with sessions() as db:
        membership = await db.get(Membership, ids[2])
        reviews = await bulk_confirm(db, organization_id=ids[0], pursuit_id=ids[1], run_id=analysis["analysis_run_id"],
                                     membership=membership, reviewer=reviewer)
        requirements = await requirement_count(db, organization_id=ids[0], pursuit_id=ids[1], run_id=analysis["analysis_run_id"])
        notice_characters = await db.scalar(
            select(func.max(func.length(func.coalesce(TenderDocument.parsed_text, "")))).where(
                TenderDocument.tender_id == UUID(summary["pursuit_tender"]["tender_id"]),
                TenderDocument.source_document_type == "OFFICIAL_NOTICE"))
        eoi = await ensure_eoi(db, organization_id=ids[0], pursuit_id=ids[1], run_id=analysis["analysis_run_id"],
                               membership=membership, email=options.email, note_call=note_call, draft_status=DRAFT_STATUS,
                               replay_closed_on=replay_closed_on)
    lap("review_and_eoi", mark)
    draft = eoi["draft"]
    return {
        "kind": "prospect-preview", "label": label, "organization_id": str(ids[0]), "organization_name": organization_name,
        "replay": {"closed_on": replay_closed_on.isoformat(), "label": replay_text(replay_closed_on)} if replay_closed_on else None,
        "requirements_extracted": requirements, "notice_characters": notice_characters,
        "demo_user_id": str(demo_user.id), "pursuit_id": str(ids[1]), "pursuit_tender": summary["pursuit_tender"],
        "counts": counts, "analysis": {**analysis, "analysis_run_id": str(analysis["analysis_run_id"])}, "reviews": reviews,
        "eoi_draft_id": str(draft.draft_id), "eoi_version": draft.version, "eoi_reused": eoi["reused"],
        "eoi_summary": draft.summary.model_dump(), "eoi_draft_status": draft.draft_status,
        "archived_other_previews": archived_others, "pick_reason": summary["pick_reason"],
        "eoi_artifacts": [{"artifact_id": str(item.artifact_id), "format": item.format, "byte_size": item.byte_size}
                          for item in draft.artifacts],
        "timings_seconds": {**({"ledger_prospect": prospect_build_seconds} if prospect_build_seconds is not None else {}),
                            **timings},
        "total_seconds": round(time.monotonic() - started + (prospect_build_seconds or 0), 1),
        "notifications_emitted": 0, "broadcasts_emitted": 0, "contacts_anyone": False,
    }


def replay_text(closed: date) -> str:
    from app.services.preview_replay import replay_text as text

    return text(closed)


async def requirement_count(db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, run_id: UUID) -> int:
    """Requirements the analysis extracted (submission notes not counted)."""
    from app.services.pursuit_analysis import get_analysis_run

    analysis = await get_analysis_run(db, organization_id=organization_id, pursuit_id=pursuit_id, run_id=run_id)
    return len(analysis.requirements)


async def ensure_official_notices(sessions, externals: list[str]) -> None:
    """A replayed (closed) tender may predate the stored official notice: store it as a refresh would."""
    from app.services.official_notice import sync_official_notices
    from scripts.demo.seed_demo import parse_tender_external

    async with sessions() as db:
        tenders = []
        for value in externals:
            source, external_id = parse_tender_external(value)
            tender = await db.scalar(select(Tender).where(Tender.source_system == source, Tender.external_id == external_id))
            if tender is not None:
                tenders.append(tender)
        if tenders:
            await sync_official_notices(db, tenders)
            await db.commit()


async def list_previews(sessions) -> list[dict[str, Any]]:
    async with sessions() as db:
        rows = []
        for organization, profile in await preview_organizations(db):
            members = await db.scalar(select(func.count(Membership.id)).where(
                Membership.organization_id == organization.id, Membership.state == MembershipState.ACTIVE))
            rows.append({"organization_id": str(organization.id), "name": organization.display_name, "label": _label_of(profile),
                         "created_at": organization.created_at.isoformat(), "archived": _is_archived(profile),
                         "active_members": members})
        return rows


async def archive(sessions, *, organization_id: UUID, confirm: str, today: date | None = None) -> dict[str, Any]:
    from scripts.demo.seed_demo import CONFIRMATION, DemoSeedError, utcnow

    if confirm != CONFIRMATION:
        raise DemoSeedError(f"archiving requires --confirm {CONFIRMATION}")
    today = today or utcnow().date()
    async with sessions() as db:
        found = [(org, profile) for org, profile in await preview_organizations(db) if org.id == organization_id]
        if not found:
            raise DemoSeedError(f"{organization_id} is not a prospect preview organization; nothing archived")
        return await _archive_one(db, found[0][0], found[0][1], today)


def utcnow_date() -> date:
    from scripts.demo.seed_demo import utcnow

    return utcnow().date()


async def _archive_one(db: AsyncSession, organization: Organization, profile: CompanyProfile, today: date) -> dict[str, Any]:
    """Revoke every membership but the steward's, rename the organization and stamp the profile notes."""
    from app.services.memberships import revoke_membership
    from scripts.demo.seed_demo import DemoSeedError, _steward_membership

    steward = await _steward_membership(db, organization.id)
    if steward is None:
        raise DemoSeedError(f"preview {organization.id} has no steward OWNER; cannot revoke its members")
    others = (await db.scalars(select(Membership).where(
        Membership.organization_id == organization.id, Membership.id != steward.id,
        Membership.state != MembershipState.REVOKED))).all()
    revoked = []
    for membership in others:
        await revoke_membership(db, organization_id=organization.id, actor_membership_id=steward.id,
                                membership_id=membership.id, transfer_to_membership_id=steward.id)
        revoked.append(str(membership.user_id))
    already = _is_archived(profile)
    if not already:
        name = f"{organization.display_name} (archived {today.isoformat()})"[:255]
        profile.company_name = name
        organization.display_name = name
        profile.notes = re.sub(r'(\{[^}]*"seed": "' + SEED + r'"[^}]*)\}', rf'\1, "archived_at": "{today.isoformat()}"}}',
                               profile.notes or "", count=1)
    await db.commit()
    return {"organization_id": str(organization.id), "name": organization.display_name, "already_archived": already,
            "revoked_user_ids": revoked, "records_kept": True}



# ---- S1-7: analyse the top N candidates, keep the best -----------------------------------------------

async def pursuit_ai_cost(db: AsyncSession, pursuit_id: UUID) -> dict[str, Any]:
    """AI cost of one pursuit from the AI cost ledger (analysis chunks and EOI notes)."""
    from app.models.product_analytics import AICallCost

    rows = (await db.execute(select(
        func.count(AICallCost.id), func.sum(AICallCost.estimated_cost_usd), func.count(AICallCost.estimated_cost_usd),
        func.sum(AICallCost.input_tokens), func.sum(AICallCost.output_tokens),
    ).where(AICallCost.pursuit_id == pursuit_id))).one()
    calls, cost, priced, tokens_in, tokens_out = rows
    return {"calls": int(calls or 0), "estimated_usd": float(cost) if cost is not None else None,
            "calls_without_price": int(calls or 0) - int(priced or 0),
            "input_tokens": int(tokens_in or 0), "output_tokens": int(tokens_out or 0)}


async def seed_best_of(sessions, options, prospect: Prospect, *, candidates: int, today: date | None = None,
                       process_inline=None, note_call=None, prospect_build_seconds: float | None = None) -> dict[str, Any]:
    """Run one preview per top candidate of the first non-empty pool (candidate_pools), keep the acceptable one
    with the most criteria matched, archive the others. A run on a notice under 5,000 characters is acceptable
    only if its analysis extracted >= 4 requirements; when no run of a pool is acceptable, the next pool is tried."""
    from dataclasses import replace

    from scripts.demo.seed_demo import DemoSeedError, _tender_summary

    started = time.monotonic()
    today_value = today or utcnow_date()
    demo_date = options.demo_date or today_value
    replay_days = getattr(options, "replay_days", 0) if isinstance(prospect, LedgerProspect) else 0
    plan_options = replace(options, dry_run=True)
    plan_options.__dict__["candidates"] = candidates
    summary = await plan(sessions, plan_options, prospect, today=today)  # refuses clearly when nothing qualifies
    if options.externals:
        pools = [("pinned", [summary["pursuit_tender"]["external_id"]])]
    else:
        async with sessions() as db:
            found = await candidate_pools(db, prospect, demo_date=demo_date, exclude=set(),
                                          allow_global=getattr(options, "allow_global", False), replay_days=replay_days)
            pools = [(name, [item.tender.external_id for item in items[:candidates]]) for name, items in found if items]
            await db.rollback()
    # Exclusive once, before the comparison: the demo user's other previews are archived.
    archived_before: list[dict[str, Any]] = []
    if not getattr(options, "keep_others", False):
        async with sessions() as db:
            demo_user = await demo_user_ready(db, options.email)
            for organization, profile in await preview_organizations(db):
                active = await db.scalar(select(Membership.id).where(
                    Membership.organization_id == organization.id, Membership.user_id == demo_user.id,
                    Membership.state == MembershipState.ACTIVE))
                if active is not None and not _is_archived(profile):
                    archived_before.append(await _archive_one(db, organization, profile, today_value))
    runs: list[dict[str, Any]] = []
    best = None
    for pool, tender_ids in pools:
        pool_runs = []
        for external_id in tender_ids:
            run_options = replace(options, externals=(f"world_bank:{external_id}",), dry_run=False)
            run_options.__dict__["comparing"] = True
            result = await seed(sessions, run_options, prospect, today=today, process_inline=process_inline,
                                note_call=note_call, prospect_build_seconds=None)
            async with sessions() as db:
                cost = await pursuit_ai_cost(db, UUID(result["pursuit_id"]))
            summary_eoi = result["eoi_summary"]
            characters = result.get("notice_characters")
            requirements = result["requirements_extracted"]
            acceptable = pool == "pinned" or (characters or 0) >= LEDGER_MIN_NOTICE_CHARACTERS or \
                requirements >= SHORT_NOTICE_MIN_REQUIREMENTS
            pool_runs.append({
                "pool": pool, "tender": external_id, "title": result["pursuit_tender"]["title"],
                "country": result["pursuit_tender"]["country"],
                "status": f"closed {result['replay']['closed_on']}" if result["replay"] else "open",
                "notice_characters": characters, "requirements_extracted": requirements, "acceptable": acceptable,
                "criteria_matched": summary_eoi["criteria_with_references"], "criteria_total": summary_eoi["criteria_total"],
                "ai_cost": cost, "seconds": result["total_seconds"], "organization_id": result["organization_id"],
                "organization_name": result["organization_name"], "pursuit_id": result["pursuit_id"], "label": result["label"],
                "pick_reason": result["pick_reason"], "replay": result["replay"], "kept": False,
            })
        runs += pool_runs
        accepted = [run for run in pool_runs if run["acceptable"]]
        if accepted:
            best = max(accepted, key=lambda run: (run["criteria_matched"],
                                                  run["criteria_matched"] / run["criteria_total"] if run["criteria_total"] else 0,
                                                  -pool_runs.index(run)))
            break
    async with sessions() as db:
        for run in runs:
            if run is best:
                run["kept"] = True
                continue
            found = [(org, profile) for org, profile in await preview_organizations(db)
                     if str(org.id) == run["organization_id"]]
            if found and not _is_archived(found[0][1]):
                await _archive_one(db, found[0][0], found[0][1], today_value)
    result = {"kind": "prospect-preview-best-of", "firm": prospect.firm_name, "candidates": runs,
              "kept": {key: best[key] for key in ("tender", "country", "status", "organization_id", "organization_name",
                                                  "pursuit_id", "label", "replay")} if best else None,
              "archived_other_previews": archived_before, "bid_countries": getattr(prospect, "bid_countries", []),
              "scope": summary["scope"], "replay_days": replay_days,
              "total_seconds": round(time.monotonic() - started + (prospect_build_seconds or 0), 1),
              "ledger_prospect_seconds": prospect_build_seconds}
    if best is None:
        raise BestOfRefused(result, f"none of the {len(runs)} analysed candidates is acceptable for {prospect.firm_name}: "
                                    f"a notice under {LEDGER_MIN_NOTICE_CHARACTERS:,} characters needs at least "
                                    f"{SHORT_NOTICE_MIN_REQUIREMENTS} extracted requirements; all were archived")
    return result


class BestOfRefused(RuntimeError):
    """No analysed candidate was acceptable; ``result`` carries the runs (all archived) for the table."""

    def __init__(self, result: dict[str, Any], message: str) -> None:
        super().__init__(message)
        self.result = result


def candidates_table(result: dict[str, Any]) -> str:
    lines = [f"{result['firm']} — {result['scope']}; own bid countries: {', '.join(result['bid_countries']) or 'none'}; "
             f"replay window {result.get('replay_days', 0)} days",
             f"{'tender':<12} {'country':<18} {'status':<17} {'criteria':>9} {'reqs':>5} {'AI cost USD':>12} {'seconds':>8}  kept  title"]
    for run in result["candidates"]:
        cost = run["ai_cost"]["estimated_usd"]
        cost_text = "n/a" if cost is None else f"{cost:.4f}"
        kept = "yes " if run["kept"] else ("no  " if run.get("acceptable", True) else "no* ")
        lines.append(f"{run['tender']:<12} {run['country'][:18]:<18} {run.get('status', 'open'):<17} "
                     f"{run['criteria_matched']:>4}/{run['criteria_total']:<4} {run.get('requirements_extracted', ''):>5} "
                     f"{cost_text:>12} {run['seconds']:>8}  {kept}  {run['title'][:60]}")
    if any(not run.get("acceptable", True) for run in result["candidates"]):
        lines.append(f"no* = notice under {LEDGER_MIN_NOTICE_CHARACTERS:,} characters and fewer than "
                     f"{SHORT_NOTICE_MIN_REQUIREMENTS} requirements extracted: not acceptable")
    lines.append(f"total {result['total_seconds']} s")
    return "\n".join(lines)
