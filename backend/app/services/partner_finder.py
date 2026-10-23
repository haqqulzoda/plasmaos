"""P2 partner finder: firms that won similar development-bank contracts, and introduction requests.

For an open analysis Gap the firm cannot close alone (an explicit joint-venture rule, an
experience requirement, or a local-presence requirement) the finder derives the gap's
assignment words, project sector tags, country, procurement category and the presence it
needs, and ranks award-ledger firms by their *awards* only. Everything shown is public
notice data (name, country, assignment title, lender, year, notice link) labelled
"From public award records, unverified"; the ledger holds no contact data and none is shown.

Ranking (``RANKING_VERSION``), deterministic for the same ledger and the same Gap:

* an award is *similar* when it shares with the gap two domain words, a domain word and a project
  sector tag, or one domain word found in at most 1% of the ledger's awards (activity words such
  as "design" or "training" are never enough); when both projects carry sector tags and share
  none, two domain words including a rare one, and never a strong match; words are weighted by
  rarity across the ledger's awards (IDF), activity words half; awards to people (initials,
  surname endings, position titles) or to UN agencies are left out;
* firms sort by: the presence the gap needs (local or foreign firm first), then a similar
  award in the gap's procurement category (consulting first), match strength, a similar award
  in the gap's country, best award relevance, the latest similar award, the number of similar
  awards, and the name.

Excluded: individual consultants, names flagged as a public body or a project (either tier),
notices excluded by the ledger validation, and the requesting organization's own firm.

Requests: "Request introduction" (or, for an expert Gap, "Ask Plasma to source an expert")
stores one request and alerts the Plasma team. Nothing is ever sent to the suggested firm.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import math
import re
import time
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import Tender
from app.models.award_ledger import AwardNoticeSnapshot, AwardOutcome
from app.models.candidate_retrieval import CVVersion, Expert, Firm
from app.models.partner_finder import PartnerRequest, PartnerRequestEvent, TeamScenarioProspectiveMember
from app.models.pursuit_analysis import AnalysisRun, PursuitGap, PursuitPosition
from app.models.team_scenarios import TeamScenario
from app.models.tenancy import Organization, OrganizationPursuit
from app.models.user import User
from app.services.award_ledger_parser import name_flag, normalize_firm_name
from app.services.award_ledger_reports import CONSULTING_GROUP, LENDER_LABELS, country_key
from app.services.own_experience import _ACTIVITY, is_experience_requirement, requirement_statement, terms

RANKING_VERSION = "p2-award-ledger-v2"
SOURCE_LABEL = "From public award records, unverified"
MAX_SUGGESTIONS = 10
MAX_AWARDS_SHOWN = 5
OPEN_COVERAGE = {"GAP", "PARTIAL", "EVIDENCE_MISSING", "NEEDS_INTERPRETATION"}
ACTIVITY_WEIGHT = 0.5
SECTOR_WEIGHT = 1.5
# Procurement and notice filler that says nothing about the assignment's subject.
EXTRA_STOP = frozenset({
    "service", "expression", "interest", "shortlist", "shortlisting", "eoi", "qualification", "qualified",
    "key", "expert", "staff", "personnel", "submit", "submission", "information", "following", "requested",
    "list", "description", "client", "date", "value", "usd", "million", "countrie", "country", "region",
    "regional", "world", "bank", "asian", "adb", "ebrd", "financed", "funded", "loan", "grant", "credit",
    "republic", "government", "local", "presence", "office", "registered", "national", "international",
    "foreign", "strengthening", "strengthen", "approach", "improving", "improve", "enhancing", "enhance",
    "establishment", "establish", "conduct", "conducting", "selection", "hiring", "new", "phase", "stage",
    "final", "additional", "various", "related", "based", "level", "use", "using", "under", "agreement",
    "joint", "venture", "consortium", "association", "subconsultant", "combined", "collectively",
    "consulting", "consultancy", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    # Seen across the preview analyses' gaps (2026-10-23): wording of the criterion, not its subject.
    "accordance", "confirmed", "confirming", "confirmation", "evaluated", "evaluate", "criterion", "criteria",
    "scored", "point", "rating", "non", "considered", "advantage", "during", "between", "above", "applicable",
    "applied", "brief", "organization", "professional", "activity", "performing", "methodological",
    "methodology", "continuous", "implementing", "deliverable", "group", "condition", "completing", "bid",
    "prepared", "determination", "equivalent", "operating", "duration", "covering", "gap", "form", "practical",
    "language", "capable", "major", "developing", "alia", "out", "multi", "carry", "involving", "arrangement",
    "detail", "amendment", "familiarity", "absence", "context", "working", "number", "exclusion", "standard",
    "cis", "ifi", "similar", "relevant", "proven", "track", "record", "demonstrable", "minimum", "pts",
    "confirm", "about", "doc", "enable", "different", "providing", "adapting", "processe", "process",
})
# Activity words beyond own_experience's: the kind of work, not its domain (half weight, never enough alone).
ACTIVITY = _ACTIVITY | frozenset({
    "assistance", "advice", "framework", "mechanism", "measure", "action", "quality", "performance", "data",
    "program", "assessment", "institutional", "operation", "operational", "sustainable", "institution",
    "strategy", "procurement",
})
# One shared domain word is enough only when it is rare in the ledger: in at most 1% of awards.
RARE_SHARE = 0.01
# How a notice titles an assignment ("Procurement of ...", "Consulting services for ..."), not what it is.
_TITLE_PREFIX = re.compile(
    r"^\s*(?:(?:procurement|selection|hiring|recruitment|provision)\s+of\s+|"
    r"(?:consult(?:ing|ancy|ant)\s+)?services?\s+(?:for|on|to)\s+|consult(?:ing|ancy)\s+services\s*[:\-–]\s*)+",
    re.IGNORECASE,
)
# Awards that go to a person, or to an intergovernmental body, are never a partner firm. Names with
# initials ("KARIMOVA MALIKA T."), or two or three name-like words with a patronymic or surname ending
# and no company word, are people; so is any award titled as a single position ("Procurement Specialist").
_INITIALS = re.compile(r"(?:^|\s)[A-Z]\.(?:\s?[A-Z]\.)*\s*$|^[A-Z]\.\s?(?:[A-Z]\.\s?)*\s*[A-Z]")
_SURNAME = re.compile(r"(?:OVA|EVA|YEVA|OV|EV|YEV|INA|ENKO|CHUK|YUK|VICH|OVICH|EVNA|OVNA|YAN|ZADE|ULY|KYZY|QIZI|O'G'LI|UGLI)$")
_COMPANY_WORD = re.compile(
    r"\b(?:LLC|LLP|LTD|INC|JSC|OJSC|CJSC|GMBH|AG|SA|SRL|BV|NV|PLC|CO|CORP|GROUP|CONSULT\w*|ASSOCIATES|PARTNERS|"
    r"SOLUTIONS|SERVICES|ENGINEERING|INTERNATIONAL|INSTITUTE|CENT(?:ER|RE)|FOUNDATION|UNIVERSITY|AGENCY|BUREAU|"
    r"OFFICE|LAB|TECH\w*|SYSTEMS|ADVISORY|MANAGEMENT|DEVELOPMENT|PROJECT\w*|NGO|FUND|AUDIT\w*|COMPANY|HOLDING|"
    r"INVEST\w*|MEDIA|GLOBAL|ARCHITECT\w*|DESIGN|STUDIO|NETWORK|ALLIANCE|UNION|ACADEMY|SCHOOL|TRUST|BANK)\b"
)
_POSITION_TITLE = re.compile(
    r"\b(?:specialist|expert|officer|coordinator|adviser|advisor|accountant|economist|lawyer|translator|"
    r"interpreter|trainer|facilitator|assistant)s?\b|"
    r"\b(?:lead|senior|junior|national|individual|short-term|long-term)\s+(?:[\w-]+\s+){0,2}consultant\b",
    re.IGNORECASE,
)
_AGENCIES = re.compile(
    r"\bUNITED NATIONS\b|\bUNICEF\b|\bUNDP\b|\bUNOPS\b|\bUNESCO\b|\bUNIDO\b|\bUNFPA\b|\bWORLD HEALTH ORGANI[SZ]ATION\b|"
    r"\bFOOD AND AGRICULTURE ORGANI[SZ]ATION\b|\bWORLD BANK\b|\bGOVERNMENT OF\b"
)


def is_person_or_agency(name: str, title: str | None = None) -> bool:
    upper = " ".join((name or "").upper().split())
    if not upper or _AGENCIES.search(upper):
        return bool(upper)
    if _COMPANY_WORD.search(upper) or any(ch.isdigit() for ch in upper) or "&" in upper or '"' in upper:
        return False
    words = [word.strip(",.") for word in upper.split()]
    if _INITIALS.search(upper):
        return True
    if 2 <= len(words) <= 3 and all(re.fullmatch(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", word) and len(word) >= 2 for word in words):
        if any(_SURNAME.search(word) for word in words) or _POSITION_TITLE.search(title or ""):
            return True
    return False
# Country names match project names ("Uzbekistan Water Project"), not the assignment.
COUNTRY_WORDS = ("Uzbekistan", "Kazakhstan", "Kyrgyz Republic", "Kyrgyzstan", "Tajikistan", "Central Asia")
STATUS_TRANSITIONS = {
    "REQUESTED": ("CONTACTED", "DECLINED"),
    "CONTACTED": ("ACCEPTED", "DECLINED"),
    "ACCEPTED": ("INTRODUCED", "DECLINED"),
    "DECLINED": (),
    "INTRODUCED": (),
}
SCENARIO_READY_STATUSES = {"ACCEPTED", "INTRODUCED"}

_LOCAL = re.compile(
    r"\blocal\s+(?:presence|office|partner|firm|company|consult\w*|registration|representation|knowledge|"
    r"experience)\b|\bregistered\s+in\b|\bpresence\s+in\b|\bnational\s+(?:firm|consult\w*|partner)\b|"
    r"местн\w*\s+(?:присутств|офис|партн|компан|фирм|консульт|опыт)|присутстви\w*\s+в\b|mahalliy",
    re.IGNORECASE,
)
_FOREIGN = re.compile(
    r"\binternational\s+(?:firm|consult\w*|partner|company|experience)\b|"
    r"\bforeign\s+(?:firm|consult\w*|partner|company)\b|международн\w*\s+(?:опыт|фирм|компан|консульт)|"
    r"иностранн\w*|xorijiy",
    re.IGNORECASE,
)


class PartnerFinderError(ValueError):
    pass


class PartnerFinderNotFoundError(PartnerFinderError):
    pass


class PartnerFinderEligibilityError(PartnerFinderError):
    pass


# ---- pure ranking -------------------------------------------------------------------------------

@dataclass(frozen=True)
class GapFeatures:
    category: str  # PARTNER_FIRM | EXPERT
    basis: str  # PARTNER_FIRM_RULE | LOCAL_PRESENCE | EXPERIENCE | EXPERT
    summary: str
    keywords: tuple[str, ...]  # stems, sorted
    keyword_words: dict[str, str]  # stem -> a word as written in the gap or the assignment title
    sectors: tuple[str, ...]
    country: str | None
    procurement_group: str
    presence: str  # LOCAL | FOREIGN | ANY


@dataclass(frozen=True)
class AwardFact:
    """One firm's share of one public award (a joint-venture award counts for each member)."""

    lender: str
    notice_id: str
    notice_url: str
    bid_ordinal: int
    country: str | None
    project_name: str | None
    package_title: str | None
    procurement_group: str | None
    award_date: date | None
    notice_date: date | None
    bidder_name: str
    bidder_country: str | None
    member_count: int
    sectors: tuple[str, ...] = ()

    @property
    def when(self) -> date | None:
        return self.award_date or self.notice_date

    @property
    def award_key(self) -> tuple[str, str, int]:
        return self.lender, self.notice_id, self.bid_ordinal


@dataclass
class _Scored:
    award: AwardFact
    relevance: float
    domain: tuple[str, ...]
    activity: tuple[str, ...]
    sectors: tuple[str, ...]
    off_sector: bool = False

    @property
    def strong(self) -> bool:
        return not self.off_sector and (len(self.domain) >= 2 or bool(self.domain and self.sectors))


def firm_key(name: str, country: str | None) -> str:
    return f"{normalize_firm_name(name) or name.upper()}|{country_key(country)}"


def _award_stems(award: AwardFact) -> set[str]:
    return terms(" ".join(part for part in (award.package_title, award.project_name) if part))


@dataclass(frozen=True)
class _Corpus:
    """Word statistics over the distinct awards (a joint-venture award once)."""

    frequency: dict[str, int]
    total: int

    def idf(self, stem: str) -> float:
        return math.log((self.total + 1) / (self.frequency.get(stem, 0) + 1)) + 1.0

    def rare(self, stem: str) -> bool:
        return self.frequency.get(stem, 0) <= max(2, RARE_SHARE * self.total)


def _corpus(awards: Iterable[AwardFact]) -> _Corpus:
    documents: dict[tuple[str, str, int], set[str]] = {}
    for award in awards:
        documents.setdefault(award.award_key, _award_stems(award))
    frequency: Counter[str] = Counter()
    for stems in documents.values():
        frequency.update(stems)
    return _Corpus(dict(frequency), len(documents))


def score_award(award: AwardFact, features: GapFeatures, corpus: _Corpus) -> _Scored | None:
    """None unless the award is similar: two domain words, a domain word and a project sector tag,
    or one rare domain word (activity words only add weight)."""
    stems = _award_stems(award)
    matched = sorted(set(features.keywords) & stems | {
        # A longer award word that ends with a gap word: "reinsurance" for "insurance".
        keyword for keyword in features.keywords
        if len(keyword) >= 6 and keyword not in ACTIVITY
        and any(len(stem) > len(keyword) and stem.endswith(keyword) for stem in stems)
    })
    domain = tuple(stem for stem in matched if stem not in ACTIVITY)
    activity = tuple(stem for stem in matched if stem in ACTIVITY)
    gap_sectors = {value.casefold(): value for value in features.sectors}
    sectors = tuple(sorted(gap_sectors[value.casefold()] for value in award.sectors if value.casefold() in gap_sectors))
    off_sector = bool(features.sectors and award.sectors and not sectors)
    if off_sector:
        # Both projects are tagged and share no sector: words alone must be specific (one rare).
        similar = len(domain) >= 2 and any(corpus.rare(stem) for stem in domain)
    else:
        similar = len(domain) >= 2 or bool(domain and sectors) or (len(domain) == 1 and corpus.rare(domain[0]))
    if not similar:
        return None
    relevance = sum(corpus.idf(stem) for stem in domain) + ACTIVITY_WEIGHT * sum(corpus.idf(stem) for stem in activity)
    relevance += SECTOR_WEIGHT * min(len(sectors), 2)
    return _Scored(award, round(relevance, 3), domain, activity, sectors, off_sector)


def _presence(bidder_country: str | None, gap_country: str | None) -> str:
    if not bidder_country or not gap_country:
        return "UNKNOWN"
    return "LOCAL" if country_key(bidder_country) == country_key(gap_country) else "FOREIGN"


def rank_firms(
    features: GapFeatures, awards: list[AwardFact], *, exclude_names: Iterable[str] = (),
    limit: int = MAX_SUGGESTIONS,
) -> list[dict[str, Any]]:
    """Pure and deterministic: the same Gap and awards give the same list in the same order."""
    excluded = {normalize_firm_name(name) for name in exclude_names if name and normalize_firm_name(name)}
    eligible = [
        award for award in awards
        if name_flag(award.bidder_name) is None and not is_person_or_agency(award.bidder_name, award.package_title)
        and (normalize_firm_name(award.bidder_name) or "") not in excluded
    ]
    corpus = _corpus(eligible)
    by_firm: dict[str, list[_Scored]] = defaultdict(list)
    names: dict[str, Counter[str]] = defaultdict(Counter)
    countries: dict[str, Counter[str]] = defaultdict(Counter)
    for award in eligible:
        scored = score_award(award, features, corpus)
        if scored is None:
            continue
        key = firm_key(award.bidder_name, award.bidder_country)
        if any(item.award.award_key == award.award_key for item in by_firm[key]):
            continue  # the same firm twice in one bid
        by_firm[key].append(scored)
        names[key][award.bidder_name] += 1
        if award.bidder_country:
            countries[key][award.bidder_country] += 1
    gap_country = country_key(features.country) if features.country else None
    target_group = (features.procurement_group or CONSULTING_GROUP).casefold()
    ranked: list[tuple[tuple, dict[str, Any]]] = []
    for key, scored in by_firm.items():
        scored.sort(key=lambda item: (
            -item.relevance, -(item.award.when or date.min).toordinal(), item.award.lender, item.award.notice_id,
            item.award.bid_ordinal,
        ))
        display = sorted(names[key].items(), key=lambda pair: (-pair[1], pair[0]))[0][0]
        bidder_country = sorted(countries[key].items(), key=lambda pair: (-pair[1], pair[0]))[0][0] if countries[key] else None
        presence = _presence(bidder_country, features.country)
        presence_tier = 0 if features.presence == "ANY" or presence == features.presence else 1
        in_category = any((item.award.procurement_group or "").casefold() == target_group for item in scored)
        strong = any(item.strong for item in scored)
        same_country = gap_country is None or any(country_key(item.award.country) == gap_country for item in scored)
        latest = max((item.award.when for item in scored if item.award.when), default=None)
        best = scored[0]
        sort_key = (
            presence_tier, 0 if in_category else 1, 0 if strong else 1, 0 if same_country else 1,
            -best.relevance, -(latest or date.min).toordinal(), -len(scored), display.casefold(), key,
        )
        matched_terms = sorted({stem for item in scored for stem in item.domain + item.activity})
        ranked.append((sort_key, {
            "firm_key": key,
            "firm_name": display,
            "firm_country": bidder_country,
            "presence": presence,
            "presence_matches_gap": presence_tier == 0,
            "match_strength": "STRONG" if strong else "MODERATE",
            "in_procurement_category": in_category,
            "same_country": bool(gap_country) and same_country,
            "matched_terms": [features.keyword_words.get(stem, stem) for stem in matched_terms],
            "matched_sectors": sorted({sector for item in scored for sector in item.sectors}),
            "similar_award_count": len(scored),
            "latest_award_year": latest.year if latest else None,
            "best_relevance": best.relevance,
            "awards": [_award_view(item) for item in scored[:MAX_AWARDS_SHOWN]],
            "source_label": SOURCE_LABEL,
        }))
    ranked.sort(key=lambda pair: pair[0])
    result = []
    for rank, (_, item) in enumerate(ranked[:limit], start=1):
        result.append({"rank": rank, **item})
    return result


def _award_view(item: _Scored) -> dict[str, Any]:
    award = item.award
    return {
        "title": award.package_title or award.project_name or award.notice_id,
        "project_name": award.project_name,
        "lender": award.lender,
        "lender_label": LENDER_LABELS.get(award.lender, award.lender),
        "country": award.country,
        "year": award.when.year if award.when else None,
        "notice_id": award.notice_id,
        "notice_url": award.notice_url,
        "procurement_group": award.procurement_group,
        "joint_venture": award.member_count > 1,
    }


# ---- gap features -------------------------------------------------------------------------------

def presence_requirement(text: str) -> str:
    local, foreign = bool(_LOCAL.search(text)), bool(_FOREIGN.search(text))
    if local and not foreign:
        return "LOCAL"
    if foreign and not local:
        return "FOREIGN"
    return "ANY"


def gap_basis(gap, requirement, position) -> str | None:
    """Why a firm cannot close this Gap alone, or None when the finder does not apply."""
    if gap.effective_coverage_state not in OPEN_COVERAGE:
        return None
    if gap.effective_resolution_category == "EXPERT" or (position is not None and requirement is None):
        return "EXPERT"
    if requirement is None:
        return None
    if gap.effective_resolution_category == "PARTNER_FIRM":
        return "PARTNER_FIRM_RULE"
    statement = requirement_statement(requirement.effective_normalized_requirement, requirement.original_quote)
    if _LOCAL.search(statement):
        return "LOCAL_PRESENCE"
    if is_experience_requirement(requirement.category, requirement.requirement_type, statement):
        return "EXPERIENCE"
    return None


def _words(text: str, stop: set[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for word in re.findall(r"[^\W\d_]{3,}", text or "", flags=re.UNICODE):
        stems = terms(word)
        for stem in stems:
            if stem not in stop and stem not in EXTRA_STOP:
                found.setdefault(stem, word.casefold())
    return found


def build_features(
    *, gap, requirement, position, basis: str, tender: Tender | None, project_sectors: Iterable[str] = (),
) -> GapFeatures:
    if requirement is not None:
        summary = requirement.effective_normalized_requirement
        statement = requirement_statement(requirement.effective_normalized_requirement, requirement.original_quote)
    elif position is not None:
        summary = position.effective_title
        statement = " ".join(filter(None, [
            position.effective_title, position.specific_experience, position.relevant_assignments,
        ]))
    else:
        summary, statement = gap.missing_contribution, gap.missing_contribution
    country = (tender.country if tender is not None else None) or None
    stop: set[str] = set()
    for value in (country or "", *COUNTRY_WORDS):
        stop |= terms(value)
    words = _words(f"{statement} {gap.missing_contribution}", stop)
    if tender is not None:
        for stem, word in _words(_TITLE_PREFIX.sub("", tender.title or ""), stop).items():
            words.setdefault(stem, word)
    sectors: list[str] = []
    metadata = tender.source_metadata_json if tender is not None and isinstance(tender.source_metadata_json, dict) else {}
    for item in metadata.get("sector") or []:
        if isinstance(item, dict) and str(item.get("sector_description") or "").strip():
            sectors.append(" ".join(str(item["sector_description"]).split()))
    if not sectors and tender is not None and tender.sector:
        sectors.extend(part.strip() for part in re.split(r"[;,]", tender.sector) if part.strip())
    sectors.extend(project_sectors)
    group = (tender.procurement_category if tender is not None else None) or CONSULTING_GROUP
    return GapFeatures(
        category="EXPERT" if basis == "EXPERT" else "PARTNER_FIRM",
        basis=basis,
        summary=" ".join((summary or "").split()),
        keywords=tuple(sorted(words)),
        keyword_words=words,
        sectors=tuple(sorted(set(sectors), key=str.casefold)),
        country=" ".join(country.split()) if country else None,
        procurement_group=group,
        presence=presence_requirement(statement),
    )


# ---- ledger reads -------------------------------------------------------------------------------

_LEDGER_CACHE: dict[str, Any] = {"key": None, "at": 0.0, "awards": []}
LEDGER_CACHE_SECONDS = 900


async def ledger_awards(db: AsyncSession) -> list[AwardFact]:
    """Awarded firm rows of the latest snapshots, validated notices only. Cached per ledger state."""
    from app.services.award_ledger_reports import _ledger_rows

    state = tuple((await db.execute(
        select(func.count(AwardNoticeSnapshot.id), func.max(AwardNoticeSnapshot.created_at))
    )).one())
    if _LEDGER_CACHE["key"] == state and time.monotonic() - _LEDGER_CACHE["at"] < LEDGER_CACHE_SECONDS:
        return _LEDGER_CACHE["awards"]
    awards = [
        AwardFact(
            lender=row.lender, notice_id=row.notice_id, notice_url=row.notice_url, bid_ordinal=row.bid_ordinal,
            country=row.country, project_name=row.project_name, package_title=row.package_title,
            procurement_group=row.procurement_group, award_date=row.award_date, notice_date=row.notice_date,
            bidder_name=row.bidder_name, bidder_country=row.bidder_country, member_count=row.member_count,
            sectors=tuple(str(item) for item in sectors if item),
        )
        for row, sectors in await _ledger_rows(db, where=AwardOutcome.status == "AWARDED")
    ]
    _LEDGER_CACHE.update(key=state, at=time.monotonic(), awards=awards)
    return awards


async def _project_sectors(db: AsyncSession, project_id: str | None) -> list[str]:
    if not project_id:
        return []
    rows = (await db.scalars(
        select(AwardNoticeSnapshot.sectors).where(AwardNoticeSnapshot.project_id == project_id).limit(20)
    )).all()
    return sorted({str(item) for sectors in rows for item in (sectors or []) if item}, key=str.casefold)


async def _own_names(db: AsyncSession, organization_id: UUID) -> list[str]:
    names: list[str] = []
    firm = await db.scalar(select(Firm).where(Firm.organization_id == organization_id))
    if firm is not None:
        names += [firm.canonical_name, firm.display_name, firm.legal_name or ""]
    organization = await db.get(Organization, organization_id)
    if organization is not None and organization.display_name:
        names.append(organization.display_name)
    return [name for name in names if name]


# ---- the Gap, for one organization -------------------------------------------------------------

@dataclass
class GapContext:
    run_id: UUID
    gap: Any
    requirement: Any
    position: Any
    basis: str
    tender: Tender | None
    features: GapFeatures


async def require_pursuit(db: AsyncSession, organization_id: UUID, pursuit_id: UUID) -> OrganizationPursuit:
    pursuit = await db.scalar(select(OrganizationPursuit).where(
        OrganizationPursuit.id == pursuit_id, OrganizationPursuit.organization_id == organization_id,
    ))
    if pursuit is None:
        raise PartnerFinderNotFoundError("Pursuit not found")
    return pursuit


async def _analysis(db: AsyncSession, organization_id: UUID, pursuit_id: UUID, run_id: UUID | None):
    from app.services.pursuit_analysis import get_analysis_run

    await require_pursuit(db, organization_id, pursuit_id)
    analysis = await get_analysis_run(db, organization_id=organization_id, pursuit_id=pursuit_id, run_id=run_id)
    if analysis is None or analysis.status != "COMPLETED":
        raise PartnerFinderNotFoundError("Completed analysis run not found")
    return analysis


async def _tender(db: AsyncSession, organization_id: UUID, pursuit_id: UUID) -> Tender | None:
    pursuit = await require_pursuit(db, organization_id, pursuit_id)
    return await db.get(Tender, pursuit.source_tender_id) if pursuit.source_tender_id else None


async def gap_context(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, analysis_run_id: UUID, gap_id: UUID,
) -> GapContext:
    analysis = await _analysis(db, organization_id, pursuit_id, analysis_run_id)
    gap = next((item for item in analysis.gaps if item.gap_id == gap_id), None)
    if gap is None:
        raise PartnerFinderNotFoundError("Gap not found in this analysis run")
    requirements = {item.requirement_id: item for item in [*analysis.requirements, *analysis.submission_and_notes]}
    positions = {item.position_id: item for item in analysis.positions}
    requirement = requirements.get(gap.requirement_id) if gap.requirement_id else None
    position = positions.get(gap.position_id) if gap.position_id else None
    basis = gap_basis(gap, requirement, position)
    if basis is None:
        raise PartnerFinderEligibilityError("This Gap is not one a partner firm or an expert can close")
    tender = await _tender(db, organization_id, pursuit_id)
    features = build_features(
        gap=gap, requirement=requirement, position=position, basis=basis, tender=tender,
        project_sectors=await _project_sectors(db, tender.project_id if tender else None),
    )
    return GapContext(analysis.analysis_run_id, gap, requirement, position, basis, tender, features)


def _features_view(features: GapFeatures) -> dict[str, Any]:
    return {
        "category": features.category, "basis": features.basis, "summary": features.summary,
        "keywords": sorted(set(features.keyword_words.values())), "sectors": list(features.sectors),
        "country": features.country, "procurement_group": features.procurement_group,
        "presence": features.presence,
    }


async def list_partner_gaps(db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID) -> dict[str, Any]:
    """The latest completed analysis's Gaps the finder applies to, with this organization's requests."""
    from app.services.pursuit_analysis import get_analysis_run

    await require_pursuit(db, organization_id, pursuit_id)
    analysis = await get_analysis_run(db, organization_id=organization_id, pursuit_id=pursuit_id)
    if analysis is None or analysis.status != "COMPLETED":
        return {"analysis_run_id": None, "gaps": [], "requests": await list_requests(
            db, organization_id=organization_id, pursuit_id=pursuit_id)}
    requirements = {item.requirement_id: item for item in [*analysis.requirements, *analysis.submission_and_notes]}
    positions = {item.position_id: item for item in analysis.positions}
    tender = await _tender(db, organization_id, pursuit_id)
    sectors = await _project_sectors(db, tender.project_id if tender else None)
    gaps = []
    for gap in analysis.gaps:
        requirement = requirements.get(gap.requirement_id) if gap.requirement_id else None
        position = positions.get(gap.position_id) if gap.position_id else None
        basis = gap_basis(gap, requirement, position)
        if basis is None:
            continue
        features = build_features(gap=gap, requirement=requirement, position=position, basis=basis,
                                  tender=tender, project_sectors=sectors)
        gaps.append({
            "gap_id": gap.gap_id, "requirement_id": gap.requirement_id, "position_id": gap.position_id,
            "coverage_state": gap.effective_coverage_state, "review_state": gap.effective_review_state,
            "resolution_category": gap.effective_resolution_category,
            "distinction": getattr(requirement or position, "distinction", None),
            "missing_contribution": gap.missing_contribution, "features": _features_view(features),
        })
    return {
        "analysis_run_id": analysis.analysis_run_id, "inputs_changed": analysis.inputs_changed, "gaps": gaps,
        "requests": await list_requests(db, organization_id=organization_id, pursuit_id=pursuit_id),
    }


async def partner_suggestions(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, analysis_run_id: UUID, gap_id: UUID,
) -> dict[str, Any]:
    context = await gap_context(
        db, organization_id=organization_id, pursuit_id=pursuit_id, analysis_run_id=analysis_run_id, gap_id=gap_id,
    )
    if context.features.category != "PARTNER_FIRM":
        raise PartnerFinderEligibilityError("Firm suggestions are for partner Gaps; ask Plasma to source an expert")
    awards = await ledger_awards(db)
    suggestions = rank_firms(context.features, awards, exclude_names=await _own_names(db, organization_id))
    requested = {
        row.firm_key: row for row in (await db.scalars(select(PartnerRequest).where(
            PartnerRequest.organization_id == organization_id, PartnerRequest.gap_id == gap_id,
            PartnerRequest.kind == "INTRODUCTION",
        ))).all()
    }
    for item in suggestions:
        request = requested.get(item["firm_key"])
        item["request"] = {"request_id": request.id, "status": request.status} if request else None
    return {
        "analysis_run_id": context.run_id, "gap_id": gap_id, "gap": _features_view(context.features),
        "ranking_version": RANKING_VERSION, "source_label": SOURCE_LABEL,
        "jv_rule_check": context.basis != "PARTNER_FIRM_RULE",
        "awards_considered": len({award.award_key for award in awards}),
        "suggestions": suggestions,
    }


async def expert_suggestions(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, analysis_run_id: UUID, gap_id: UUID,
) -> dict[str, Any]:
    """Experts from the organization's library and the shared network, ranked read-only (nothing stored)."""
    from app.services.candidate_retrieval import MAX_RETRIEVAL_POOL, _evaluate_experts, _visible

    context = await gap_context(
        db, organization_id=organization_id, pursuit_id=pursuit_id, analysis_run_id=analysis_run_id, gap_id=gap_id,
    )
    if context.features.category != "EXPERT" or context.gap.position_id is None:
        raise PartnerFinderEligibilityError("Expert suggestions are for key-expert Gaps")
    gap = await db.get(PursuitGap, context.gap.gap_id)
    position = await db.get(PursuitPosition, context.gap.position_id)
    experts = list((await db.scalars(
        select(Expert).where(
            _visible(Expert.scope, Expert.owner_organization_id, organization_id),
            Expert.consent_state != "WITHDRAWN",
        ).order_by(Expert.updated_at.desc(), Expert.id).limit(MAX_RETRIEVAL_POOL)
    )).all())
    versions = list((await db.scalars(
        select(CVVersion).where(CVVersion.expert_id.in_([row.id for row in experts]))
        .order_by(CVVersion.expert_id, CVVersion.version_number.desc())
    )).all()) if experts else []
    evaluated = _evaluate_experts(experts, versions, position, gap, context.position.effective_title, MAX_SUGGESTIONS)
    sourcing = await db.scalar(select(PartnerRequest).where(
        PartnerRequest.organization_id == organization_id, PartnerRequest.gap_id == gap_id,
        PartnerRequest.kind == "EXPERT_SOURCING",
    ))
    return {
        "analysis_run_id": context.run_id, "gap_id": gap_id, "gap": _features_view(context.features),
        "experts": [{
            "rank": rank, "expert_id": item["expert"].id, "display_name": item["expert"].display_name,
            "scope": item["expert"].scope, "qualification_state": item["state"], "rationale": item["rationale"],
            "missing_or_weak_evidence": item["missing"],
        } for rank, item in enumerate(evaluated, start=1)],
        "sourcing_request": {"request_id": sourcing.id, "status": sourcing.status} if sourcing else None,
    }


# ---- requests -----------------------------------------------------------------------------------

def _event_view(row: PartnerRequestEvent) -> dict[str, Any]:
    return {"from_status": row.from_status, "to_status": row.to_status, "message": row.message, "at": row.created_at}


def _request_view(row: PartnerRequest, events: list[PartnerRequestEvent]) -> dict[str, Any]:
    snapshot = row.suggestion_snapshot or {}
    return {
        "request_id": row.id, "pursuit_id": row.pursuit_id, "analysis_run_id": row.analysis_run_id,
        "gap_id": row.gap_id, "kind": row.kind, "gap_category": row.gap_category, "gap_summary": row.gap_summary,
        "firm_key": row.firm_key, "firm_name": row.firm_name, "firm_country": row.firm_country,
        "awards": snapshot.get("awards", []), "source_label": SOURCE_LABEL if row.kind == "INTRODUCTION" else None,
        "note": row.note, "status": row.status, "status_changed_at": row.status_changed_at,
        "created_at": row.created_at, "requester_membership_id": row.requester_membership_id,
        "history": [_event_view(event) for event in events],
    }


async def _events(db: AsyncSession, request_ids: list[UUID]) -> dict[UUID, list[PartnerRequestEvent]]:
    result: dict[UUID, list[PartnerRequestEvent]] = defaultdict(list)
    if request_ids:
        for row in (await db.scalars(select(PartnerRequestEvent).where(
            PartnerRequestEvent.request_id.in_(request_ids)
        ).order_by(PartnerRequestEvent.created_at, PartnerRequestEvent.id))).all():
            result[row.request_id].append(row)
    return result


async def list_requests(db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID) -> list[dict[str, Any]]:
    rows = list((await db.scalars(select(PartnerRequest).where(
        PartnerRequest.organization_id == organization_id, PartnerRequest.pursuit_id == pursuit_id,
    ).order_by(PartnerRequest.created_at, PartnerRequest.id))).all())
    events = await _events(db, [row.id for row in rows])
    return [_request_view(row, events[row.id]) for row in rows]


async def create_request(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, membership_id: UUID, user: User,
    analysis_run_id: UUID, gap_id: UUID, kind: str, firm_key: str | None, note: str | None,
) -> tuple[dict[str, Any], bool]:
    """(request, created). A repeated request for the same Gap and firm returns the first one."""
    from app.services.admin_activity import (
        ACTION_PARTNER_REQUEST_CREATED, OUTCOME_SUCCESS, SOURCE_ORGANIZATION_API, record_admin_audit_event,
    )
    from app.services.admin_alerts import stage_admin_alert

    note = " ".join((note or "").split()) or None
    if note and len(note) > 2000:
        raise PartnerFinderError("The note is limited to 2000 characters")
    context = await gap_context(
        db, organization_id=organization_id, pursuit_id=pursuit_id, analysis_run_id=analysis_run_id, gap_id=gap_id,
    )
    existing_filter = [PartnerRequest.organization_id == organization_id, PartnerRequest.gap_id == gap_id,
                       PartnerRequest.kind == kind]
    snapshot: dict[str, Any] = {"ranking_version": RANKING_VERSION, "gap": _features_view(context.features)}
    firm_name = firm_country = None
    if kind == "INTRODUCTION":
        if context.features.category != "PARTNER_FIRM":
            raise PartnerFinderEligibilityError("Introductions are for partner Gaps; ask Plasma to source an expert")
        suggestions = rank_firms(context.features, await ledger_awards(db), exclude_names=await _own_names(db, organization_id))
        chosen = next((item for item in suggestions if item["firm_key"] == firm_key), None)
        if chosen is None:
            raise PartnerFinderNotFoundError("This firm is not among the suggestions for the Gap")
        firm_name, firm_country = chosen["firm_name"], chosen["firm_country"]
        snapshot.update({key: value for key, value in chosen.items() if key != "request"})
        existing_filter.append(PartnerRequest.firm_key == firm_key)
    elif kind == "EXPERT_SOURCING":
        if context.features.category != "EXPERT":
            raise PartnerFinderEligibilityError("Expert sourcing is for key-expert Gaps")
        firm_key = None
    else:
        raise PartnerFinderError("kind must be INTRODUCTION or EXPERT_SOURCING")
    existing = await db.scalar(select(PartnerRequest).where(*existing_filter))
    if existing is not None:
        return _request_view(existing, (await _events(db, [existing.id]))[existing.id]), False

    now = datetime.now(timezone.utc)
    row = PartnerRequest(
        organization_id=organization_id, pursuit_id=pursuit_id, analysis_run_id=context.run_id, gap_id=gap_id,
        kind=kind, gap_category=context.features.category, gap_summary=context.features.summary[:4000],
        firm_key=firm_key, firm_name=firm_name, firm_country=firm_country,
        suggestion_snapshot=_json_safe(snapshot), requester_membership_id=membership_id, requester_user_id=user.id,
        note=note, status="REQUESTED", status_changed_at=now,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(select(PartnerRequest).where(*existing_filter))
        if existing is None:
            raise
        return _request_view(existing, (await _events(db, [existing.id]))[existing.id]), False
    event = PartnerRequestEvent(
        organization_id=organization_id, request_id=row.id, from_status=None, to_status="REQUESTED",
        actor_user_id=user.id, message=None,
    )
    db.add(event)
    organization = await db.get(Organization, organization_id)
    tender = context.tender
    await stage_admin_alert(db, kind="PARTNER_REQUEST", dedupe_key=f"admin-alert:partner-request:{row.id}", payload={
        "request_id": str(row.id), "kind": kind, "organization_name": (organization.display_name if organization else "")[:200],
        "requester_email": user.email, "firm_name": firm_name or "", "firm_country": firm_country or "",
        "tender_reference": (tender.external_id if tender else "")[:80], "tender_title": (tender.title if tender else "")[:300],
        "gap_summary": context.features.summary[:600], "note": (note or "")[:600],
        "at": now.isoformat(timespec="seconds"),
    })
    await record_admin_audit_event(
        db, action=ACTION_PARTNER_REQUEST_CREATED, outcome=OUTCOME_SUCCESS, source=SOURCE_ORGANIZATION_API,
        actor_user=user, target_user=user, target_resource_type="PARTNER_REQUEST", target_resource_id=str(row.id),
        previous_state=None, new_state={"status": "REQUESTED", "kind": kind},
        metadata={"organization_id": str(organization_id), "pursuit_id": str(pursuit_id), "gap_id": str(gap_id),
                  "firm_name": firm_name},
    )
    await db.commit()
    await db.refresh(row)
    return _request_view(row, [event]), True


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (UUID, date, datetime)):
        return str(value)
    return value


# ---- the Plasma team's queue --------------------------------------------------------------------

async def admin_queue(db: AsyncSession, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    statement = select(PartnerRequest)
    if status:
        statement = statement.where(PartnerRequest.status == status)
    rows = list((await db.scalars(
        statement.order_by(PartnerRequest.created_at.desc(), PartnerRequest.id).limit(limit)
    )).all())
    events = await _events(db, [row.id for row in rows])
    organizations = {row.id: row for row in (await db.scalars(select(Organization).where(
        Organization.id.in_({row.organization_id for row in rows})))).all()} if rows else {}
    users = {row.id: row for row in (await db.scalars(select(User).where(
        User.id.in_({row.requester_user_id for row in rows})))).all()} if rows else {}
    pursuits = {row.id: row for row in (await db.scalars(select(OrganizationPursuit).where(
        OrganizationPursuit.id.in_({row.pursuit_id for row in rows})))).all()} if rows else {}
    tender_ids = {row.source_tender_id for row in pursuits.values() if row.source_tender_id}
    tenders = {row.id: row for row in (await db.scalars(select(Tender).where(Tender.id.in_(tender_ids)))).all()} if tender_ids else {}
    result = []
    for row in rows:
        organization = organizations.get(row.organization_id)
        requester = users.get(row.requester_user_id)
        pursuit = pursuits.get(row.pursuit_id)
        tender = tenders.get(pursuit.source_tender_id) if pursuit and pursuit.source_tender_id else None
        result.append({
            **_request_view(row, events[row.id]),
            "organization_id": row.organization_id,
            "organization_name": organization.display_name if organization else None,
            "requester_name": requester.name if requester else None,
            "requester_email": requester.email if requester else None,
            "tender_reference": tender.external_id if tender else None,
            "tender_title": tender.title if tender else None,
            "tender_url": tender.source_url if tender else None,
            "next_statuses": list(STATUS_TRANSITIONS.get(row.status, ())),
        })
    return result


async def change_status(
    db: AsyncSession, *, request_id: UUID, status: str, message: str | None, actor: User,
) -> dict[str, Any]:
    from app.services.admin_activity import (
        ACTION_PARTNER_REQUEST_STATUS_CHANGED, OUTCOME_SUCCESS, SOURCE_ADMIN_API, record_admin_audit_event,
    )

    row = await db.scalar(select(PartnerRequest).where(PartnerRequest.id == request_id).with_for_update())
    if row is None:
        raise PartnerFinderNotFoundError("Partner request not found")
    if status not in STATUS_TRANSITIONS.get(row.status, ()):
        raise PartnerFinderEligibilityError(f"A {row.status.lower()} request cannot move to {status.lower()}")
    message = " ".join((message or "").split()) or None
    if message and len(message) > 2000:
        raise PartnerFinderError("The message is limited to 2000 characters")
    previous = row.status
    row.status = status
    row.status_changed_at = datetime.now(timezone.utc)
    db.add(PartnerRequestEvent(
        organization_id=row.organization_id, request_id=row.id, from_status=previous, to_status=status,
        actor_user_id=actor.id, message=message,
    ))
    requester = await db.get(User, row.requester_user_id)
    await record_admin_audit_event(
        db, action=ACTION_PARTNER_REQUEST_STATUS_CHANGED, outcome=OUTCOME_SUCCESS, source=SOURCE_ADMIN_API,
        actor_user=actor, target_user=requester, target_resource_type="PARTNER_REQUEST",
        target_resource_id=str(row.id), previous_state={"status": previous}, new_state={"status": status},
        reason=message, metadata={"organization_id": str(row.organization_id), "kind": row.kind,
                                  "firm_name": row.firm_name},
    )
    await db.commit()
    view = _request_view(row, (await _events(db, [row.id]))[row.id])
    view["next_statuses"] = list(STATUS_TRANSITIONS[status])
    return view


# ---- prospective JV members in a team scenario --------------------------------------------------

async def _scenario(db: AsyncSession, organization_id: UUID, pursuit_id: UUID, scenario_id: UUID) -> TeamScenario:
    row = await db.scalar(select(TeamScenario).where(
        TeamScenario.id == scenario_id, TeamScenario.organization_id == organization_id,
        TeamScenario.pursuit_id == pursuit_id,
    ))
    if row is None:
        raise PartnerFinderNotFoundError("Team scenario not found")
    return row


async def add_prospective_member(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, scenario_id: UUID, membership_id: UUID,
    partner_request_id: UUID,
) -> None:
    scenario = await _scenario(db, organization_id, pursuit_id, scenario_id)
    if scenario.archived_at is not None:
        raise PartnerFinderEligibilityError("Archived team scenarios cannot change")
    request = await db.scalar(select(PartnerRequest).where(
        PartnerRequest.id == partner_request_id, PartnerRequest.organization_id == organization_id,
        PartnerRequest.pursuit_id == pursuit_id,
    ))
    if request is None:
        raise PartnerFinderNotFoundError("Partner request not found")
    if request.kind != "INTRODUCTION" or request.status not in SCENARIO_READY_STATUSES:
        raise PartnerFinderEligibilityError("Only a partner who accepted an introduction can join a scenario")
    exists = await db.scalar(select(TeamScenarioProspectiveMember.id).where(
        TeamScenarioProspectiveMember.scenario_id == scenario.id,
        TeamScenarioProspectiveMember.partner_request_id == request.id,
        TeamScenarioProspectiveMember.removed_at.is_(None),
    ))
    if exists is not None:
        return
    db.add(TeamScenarioProspectiveMember(
        organization_id=organization_id, scenario_id=scenario.id, partner_request_id=request.id,
        display_name_snapshot=request.firm_name or "Partner", added_by_membership_id=membership_id,
    ))
    await db.commit()


async def remove_prospective_member(
    db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, scenario_id: UUID, member_id: UUID,
) -> None:
    await _scenario(db, organization_id, pursuit_id, scenario_id)
    row = await db.scalar(select(TeamScenarioProspectiveMember).where(
        TeamScenarioProspectiveMember.id == member_id, TeamScenarioProspectiveMember.scenario_id == scenario_id,
        TeamScenarioProspectiveMember.organization_id == organization_id,
    ))
    if row is None:
        raise PartnerFinderNotFoundError("Prospective member not found")
    if row.removed_at is None:
        row.removed_at = datetime.now(timezone.utc)
        await db.commit()


async def prospective_members(
    db: AsyncSession, *, organization_id: UUID, scenario_ids: list[UUID],
) -> dict[UUID, list[dict[str, Any]]]:
    """Active prospective members per scenario, each with the Gaps its accepted requests target.

    A firm accepted for several Gaps of the pursuit would close each of them; the basis is the
    request itself, never evidence (the member stays "not yet confirmed").
    """
    if not scenario_ids:
        return {}
    members = list((await db.scalars(select(TeamScenarioProspectiveMember).where(
        TeamScenarioProspectiveMember.organization_id == organization_id,
        TeamScenarioProspectiveMember.scenario_id.in_(scenario_ids),
        TeamScenarioProspectiveMember.removed_at.is_(None),
    ).order_by(TeamScenarioProspectiveMember.created_at, TeamScenarioProspectiveMember.id))).all())
    if not members:
        return {}
    requests = {row.id: row for row in (await db.scalars(select(PartnerRequest).where(
        PartnerRequest.id.in_([row.partner_request_id for row in members]),
        PartnerRequest.organization_id == organization_id,
    ))).all()}
    same_firm: dict[tuple[UUID, str], list[PartnerRequest]] = defaultdict(list)
    keys = {row.firm_key for row in requests.values() if row.firm_key}
    if keys:
        for row in (await db.scalars(select(PartnerRequest).where(
            PartnerRequest.organization_id == organization_id, PartnerRequest.firm_key.in_(keys),
            PartnerRequest.kind == "INTRODUCTION", PartnerRequest.status.in_(SCENARIO_READY_STATUSES),
        ).order_by(PartnerRequest.created_at, PartnerRequest.id))).all():
            same_firm[(row.pursuit_id, row.firm_key)].append(row)
    result: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for member in members:
        request = requests.get(member.partner_request_id)
        if request is None:
            continue
        targets = same_firm.get((request.pursuit_id, request.firm_key), [request])
        result[member.scenario_id].append({
            "prospective_member_id": member.id, "partner_request_id": request.id,
            "display_name": member.display_name_snapshot, "firm_country": request.firm_country,
            "request_status": request.status, "confirmation": "NOT_YET_CONFIRMED",
            "targets": [{"gap_id": row.gap_id, "analysis_run_id": row.analysis_run_id, "gap_summary": row.gap_summary}
                        for row in targets],
            "awards": (request.suggestion_snapshot or {}).get("awards", []),
            "source_label": SOURCE_LABEL, "added_at": member.created_at,
        })
    return result
