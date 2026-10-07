"""Deterministic reading of W4 corporate requirements against the organization's own record.

Two questions, both answered without AI and from persisted facts only:

* Is a requirement an informational statement or a submission instruction? Those
  need no company evidence, so they create no Gap and are listed apart
  (``submission_and_notes``).
* Which of the organization's own project references (its self firm) match an
  experience requirement? A match only makes the requirement PARTIAL: references
  are recorded claims and a reviewer confirms them. Nothing here returns SUPPORTED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import math
import re
from typing import Any

from app.core.geography import COUNTRIES_BY_REGION


NOTE_INFORMATIONAL = "INFORMATIONAL"
NOTE_SUBMISSION_INSTRUCTION = "SUBMISSION_INSTRUCTION"
# requirement_type values that describe only how, where or when the submission is
# delivered. SUBMISSION_INSTRUCTION is the value the extraction prompt asks for;
# the others are the model's own spellings of the same thing seen in live runs.
SUBMISSION_INSTRUCTION_TYPES = frozenset({
    "SUBMISSION_INSTRUCTION", "SUBMISSION_DEADLINE", "SUBMISSION_MANNER", "SUBMISSION_METHOD",
})
MAX_MATCHED_REFERENCES = 20
MAX_NAMED_REFERENCES = 5

_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_STOP = frozenset({
    "and", "the", "for", "with", "from", "that", "this", "these", "those", "into", "over", "under",
    "must", "shall", "should", "will", "have", "has", "been", "being", "are", "was", "were", "its",
    "their", "which", "such", "any", "all", "each", "other", "also", "including", "within", "least",
    "last", "past", "minimum", "maximum", "more", "than", "less", "per", "not", "only", "both",
    "required", "requirement", "requirements", "bidder", "applicant", "consultant", "consultants",
    "firm", "company", "contractor", "experience", "similar", "relevant", "comparable", "year",
    "successful", "successfully", "completed", "completion", "contract", "assignment", "reference",
    "demonstrate", "demonstrated", "provide", "evidence", "general", "specific", "nature", "size",
    "complexity", "field", "area", "sector", "type", "lead", "member", "partner", "role",
})
# Activity words say what kind of work, not in which domain. One shared activity
# word ("design") is too weak to call a reference relevant on its own.
_ACTIVITY = frozenset({
    "design", "engineering", "supervision", "construction", "consulting", "consultancy", "service",
    "work", "management", "study", "assessment", "training", "preparation", "development",
    "implementation", "support", "technical", "capacity", "detailed", "review", "evaluation",
    "monitoring", "planning", "advisory", "project", "program", "programme", "system", "infrastructure",
    "feasibility", "analysi", "analysis", "survey", "document", "documentation", "report", "national",
    "international", "public", "private", "improvement", "rehabilitation", "provision", "delivery",
})
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
}
_WINDOW = re.compile(
    r"\b(?:last|past|previous|preceding|recent|within)\s+(?:the\s+)?(?:last\s+|past\s+)?"
    r"(\d{1,2}|" + "|".join(_NUMBER_WORDS) + r")\s*(?:\(\s*\d{1,2}\s*\)\s*)?years?\b",
    re.IGNORECASE,
)
_COMPLETED = re.compile(r"\b(?:completed|completion|successfully|заверш\w*|yakunlan\w*)\b", re.IGNORECASE)
_LEAD_ONLY = re.compile(
    r"\b(?:as\s+(?:a\s+|the\s+)?lead|lead\s+(?:firm|consultant|partner|member|contractor)|"
    r"prime\s+(?:consultant|contractor)|main\s+contractor)\b",
    re.IGNORECASE,
)
_COUNT_UNITS = ("contract", "project", "assignment", "reference", "job", "engagement")
_CURRENCY_UNITS = ("usd", "us$", "eur", "euro", "dollar", "uzs", "sum", "som", "gbp", "currency", "value")


def _label_tokens(*values: Any) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        tokens.update(token for token in re.split(r"[^A-Z0-9]+", str(value or "").upper()) if token)
    return tokens


def note_kind(distinction: str | None, requirement_type: str | None) -> str | None:
    """INFORMATIONAL, SUBMISSION_INSTRUCTION, or None for an evidence-bearing requirement."""
    if str(distinction or "").upper() == "INFORMATIONAL":
        return NOTE_INFORMATIONAL
    normalized = "_".join(re.split(r"[^A-Z0-9]+", str(requirement_type or "").upper())).strip("_")
    if normalized in SUBMISSION_INSTRUCTION_TYPES:
        return NOTE_SUBMISSION_INSTRUCTION
    return None


# ---- experience scope ---------------------------------------------------------------------------------
#
# Own project references may only address a requirement that asks for similar
# assignments, project experience or a track record. Everything else the firm must
# show (licences, finances, organisation, staff, years in business, certificates,
# documents) is never supported by a project reference, even when its wording or
# the surrounding notice mentions "experience". The decision reads the requirement's
# own statement (normalized text and quote), never the surrounding source context.

EXPERIENCE_SCOPE = "SIMILAR_ASSIGNMENTS"
SCOPE_LICENCE_LEGAL = "LICENCE_OR_LEGAL_STATUS"
SCOPE_FINANCIAL = "FINANCIAL_CAPACITY"
SCOPE_ORGANISATION = "ORGANISATIONAL_CAPACITY"
SCOPE_STAFFING = "STAFFING_OR_KEY_EXPERTS"
SCOPE_CORE_BUSINESS = "CORE_BUSINESS_OR_YEARS"
SCOPE_CERTIFICATION = "CERTIFICATION"
SCOPE_DOCUMENT = "DOCUMENT_OR_SUBMISSION"
SCOPE_OTHER = "OTHER"

_ASSIGNMENT_WORDS = r"(?:assignments?|projects?|contracts?|engagements?|jobs?|works?\s+of\s+a\s+similar)"
# Label tokens (category/requirement_type as the analyzer writes them, split on
# non-alphanumerics) that name the experience scope.
_INCLUDED_LABELS: tuple[frozenset[str], ...] = (
    frozenset({"SIMILAR", "ASSIGNMENT"}), frozenset({"SIMILAR", "ASSIGNMENTS"}), frozenset({"SIMILAR", "PROJECT"}),
    frozenset({"SIMILAR", "PROJECTS"}), frozenset({"SIMILAR", "CONTRACT"}), frozenset({"SIMILAR", "CONTRACTS"}),
    frozenset({"TRACK", "RECORD"}), frozenset({"PAST", "PERFORMANCE"}), frozenset({"PROJECT", "EXPERIENCE"}),
    frozenset({"CORPORATE", "EXPERIENCE"}), frozenset({"SPECIFIC", "EXPERIENCE"}), frozenset({"FIRM", "EXPERIENCE"}),
)
# Label tokens of each excluded class.
_EXCLUDED_LABELS: tuple[tuple[str, frozenset[str]], ...] = (
    (SCOPE_LICENCE_LEGAL, frozenset({"LICENSE", "LICENCE", "LICENSES", "LICENCES", "LICENSING", "LICENCING", "PERMIT",
                                     "PERMITS", "REGISTRATION", "LEGAL", "INCORPORATION", "ELIGIBILITY"})),
    (SCOPE_FINANCIAL, frozenset({"FINANCIAL", "FINANCE", "TURNOVER", "AUDIT", "AUDITED", "REVENUE", "LIQUIDITY"})),
    (SCOPE_ORGANISATION, frozenset({"ORGANIZATIONAL", "ORGANISATIONAL", "ORGANIZATION", "ORGANISATION", "MANAGEMENT",
                                    "MANAGERIAL", "QUALITY", "CAPACITY", "CAPABILITY", "CAPABILITIES", "RESOURCES"})),
    (SCOPE_STAFFING, frozenset({"PERSONNEL", "STAFF", "STAFFING", "EXPERT", "EXPERTS", "TEAM", "CV", "CVS"})),
    (SCOPE_CERTIFICATION, frozenset({"CERTIFICATION", "CERTIFICATE", "CERTIFICATES", "ISO", "ACCREDITATION"})),
    (SCOPE_DOCUMENT, frozenset({"DOCUMENTATION", "DOCUMENT", "DOCUMENTS", "SUBMISSION", "FORM", "FORMS",
                                "DECLARATION", "AFFIDAVIT"})),
)
# Statement wording of each excluded class, in precedence order (core business and
# certification before organisation: "core business, years in operation, and managerial
# capabilities"; "certified to ISO 9001 for its quality management").
_EXCLUDED_TEXT: tuple[tuple[str, re.Pattern[str]], ...] = (
    (SCOPE_LICENCE_LEGAL, re.compile(
        r"\blicen[cs](?:e|es|ed|ing)\b|\bpermits?\b|\bregist(?:ration|ered)\b|\blegal\s+(?:status|entity|capacity)\b|"
        r"\bincorporat|\bconflict\s+of\s+interest\b",
        re.IGNORECASE)),
    (SCOPE_FINANCIAL, re.compile(
        r"\bturnover\b|\bfinancial\s+(?:capacity|standing|statements?|situation|position|resources|soundness)\b|"
        r"\baudited\b|\bannual\s+revenue\b|\bnet\s+worth\b|\bliquidity\b|\bbank\s+(?:guarantee|statement)",
        re.IGNORECASE)),
    (SCOPE_CORE_BUSINESS, re.compile(
        r"\bcore\s+business\b|\byears?\s+(?:in|of)\s+(?:operation|business|existence)\b|\bgeneral\s+experience\b|"
        r"\b(?:\d{1,2}|" + "|".join(_NUMBER_WORDS) + r")\s*(?:\(\s*\d{1,2}\s*\)\s*)?years?\s+of\s+"
        r"(?:continuous\s+|general\s+|overall\s+|professional\s+)?experience\b",
        re.IGNORECASE)),
    (SCOPE_CERTIFICATION, re.compile(r"\bcertif(?:ied|icates?|ication)\b|\bISO\s*\d|\baccredit", re.IGNORECASE)),
    (SCOPE_ORGANISATION, re.compile(
        r"\borgani[sz]ation(?:al)?\s+(?:structure|capacity|capabilit\w*|chart)\b|\bmanagerial\b|"
        r"\bmanagement\s+(?:system|capacit\w*|structure)\b|\bquality\s+(?:management|assurance|control)\b|"
        r"\btechnical\s+(?:resources|capabilit\w*|capacity)\b|\bresources\s+available\b",
        re.IGNORECASE)),
    (SCOPE_STAFFING, re.compile(
        r"\bkey\s+(?:experts?|staff|personnel)\b|\bpersonnel\b|\bstaff(?:ing)?\b|\bteam\s+(?:leader|members?|composition)\b|"
        r"\bcurricul(?:um|a)\s+vitae\b|\bCVs?\b",
        re.IGNORECASE)),
    (SCOPE_DOCUMENT, re.compile(
        r"\bsupporting\s+documents?\b|\bdocumentation\b|\bsubmit(?:ted)?\b|\bbrochures?\b|\baffidavits?\b|"
        r"\b(?:standard|application|submission|prescribed|attached)\s+forms?\b|"
        r"\bdeclarations?\b|\blist\s+of\s+(?:at\s+least\s+)?\S+\s+(?:professional\s+)?references\b",
        re.IGNORECASE)),
)
# Strong statement cues: similar assignments, a count of completed contracts, a track record.
_SIMILAR_ASSIGNMENTS = re.compile(
    r"\b(?:similar|comparable)\b[^.;]{0,60}?\b" + _ASSIGNMENT_WORDS + r"\b|"
    r"\b" + _ASSIGNMENT_WORDS + r"\s+of\s+(?:a\s+)?(?:similar|comparable)\b|"
    r"\b(?:successful(?:ly)?|complet(?:ed|ion))\b[^.;]{0,50}?\b" + _ASSIGNMENT_WORDS + r"\b|"
    r"\b(?:at\s+least|minimum(?:\s+of)?|no\s+fewer\s+than)\s+\S+\s*(?:\(\s*\d{1,2}\s*\)\s*)?" + _ASSIGNMENT_WORDS + r"\b|"
    r"\btrack\s+record\b|\bpast\s+performance\b",
    re.IGNORECASE,
)
# Weaker cue: experience stated in assignments/projects/contracts. Never overrides an excluded class.
_PROJECT_EXPERIENCE = re.compile(
    r"\b(?:experience|опыт\w*|tajriba\w*)\s+(?:in|with|on|of)\s+(?:[^\W\d_]+\s+){0,6}?" + _ASSIGNMENT_WORDS + r"\b",
    re.IGNORECASE,
)


def experience_scope(category: str | None, requirement_type: str | None, statement: str) -> str:
    """EXPERIENCE_SCOPE when own project references may address the requirement, else the class
    that rules them out (or OTHER). ``statement`` is the requirement's own normalized text and
    quote; the surrounding source context must not be passed."""
    tokens = _label_tokens(category, requirement_type)
    text = statement or ""
    # Precedence: a strong statement cue; then excluded wording; then an included label;
    # then an excluded label; then experience stated in assignments/projects/contracts.
    if _SIMILAR_ASSIGNMENTS.search(text):
        return EXPERIENCE_SCOPE
    for scope, pattern in _EXCLUDED_TEXT:
        if pattern.search(text):
            return scope
    if any(labels <= tokens for labels in _INCLUDED_LABELS):
        return EXPERIENCE_SCOPE
    for scope, labels in _EXCLUDED_LABELS:
        if tokens & labels:
            return scope
    return EXPERIENCE_SCOPE if _PROJECT_EXPERIENCE.search(text) else SCOPE_OTHER


def is_experience_requirement(category: str | None, requirement_type: str | None, statement: str) -> bool:
    """Whether own project references may address the requirement (see ``experience_scope``)."""
    return experience_scope(category, requirement_type, statement) == EXPERIENCE_SCOPE


def requirement_statement(normalized: str | None, quote: str | None) -> str:
    """The text ``experience_scope`` reads: the requirement itself, without its source context."""
    return " ".join(part for part in (normalized, quote) if part)


def _stem(word: str) -> str:
    if len(word) > 4 and word.isascii():
        if word.endswith("ies"):
            return word[:-3] + "y"
        if word.endswith("s") and not word.endswith("ss"):
            return word[:-1]
    return word


def terms(text: str | None) -> set[str]:
    """Whole words of three or more letters, case-folded, English plural folded, filler removed."""
    found: set[str] = set()
    for word in _WORD.findall((text or "").casefold()):
        stem = _stem(word)
        if word not in _STOP and stem not in _STOP:
            found.add(stem)
    return found


def _contains_phrase(text: str, phrase: str | None) -> bool:
    phrase = " ".join((phrase or "").split())
    if len(phrase) < 3:
        return False
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, re.IGNORECASE) is not None


def _named_countries(text: str) -> set[str]:
    """Countries a requirement names, directly or through a region the gazetteer knows."""
    named: set[str] = set()
    for region, countries in COUNTRIES_BY_REGION.items():
        if countries and _contains_phrase(text, region):
            named.update(country.casefold() for country in countries)
        for country in countries:
            if _contains_phrase(text, country):
                named.add(country.casefold())
    return named


def recency_window_years(text: str) -> int | None:
    match = _WINDOW.search(text)
    if not match:
        return None
    raw = match.group(1).casefold()
    return int(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw)


def _required_count(predicate: dict[str, Any] | None) -> int | None:
    if not predicate:
        return None
    unit = str(predicate.get("unit") or "").casefold()
    threshold = predicate.get("threshold")
    if not isinstance(threshold, (int, float)) or not any(word in unit for word in _COUNT_UNITS):
        return None
    operator = str(predicate.get("operator") or ">=").strip()
    if operator == ">":
        return int(math.floor(threshold)) + 1
    if operator in {">=", "=", "=="}:
        return max(1, int(math.ceil(threshold)))
    return None


def _other_thresholds(predicate: dict[str, Any] | None) -> list[str]:
    if not predicate or not isinstance(predicate.get("threshold"), (int, float)):
        return []
    unit = str(predicate.get("unit") or "").casefold()
    if "year" in unit:
        return [f"{predicate['threshold']:g} years of experience cannot be established from project references alone"]
    if any(word in unit for word in _CURRENCY_UNITS):
        return ["the contract value threshold is not evaluated automatically (value basis and currency differ)"]
    return []


def _years_ago(as_of: date, years: int) -> date:
    try:
        return as_of.replace(year=as_of.year - years)
    except ValueError:  # 29 February
        return as_of.replace(year=as_of.year - years, day=28)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _describe(reference: dict[str, Any]) -> str:
    details = [str(reference.get(key)) for key in ("client_name", "country") if reference.get(key)]
    finished = _parse_date(reference.get("completion_date"))
    if reference.get("completion_state") == "COMPLETED" and finished:
        details.append(f"completed {finished.year}")
    elif reference.get("completion_state") == "ONGOING":
        details.append("ongoing")
    name = str(reference.get("project_name") or "Unnamed reference")
    return f"{name} ({', '.join(details)})" if details else name


@dataclass
class OwnExperienceMatch:
    matched: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[tuple[dict[str, Any], str]] = field(default_factory=list)
    unproven: list[str] = field(default_factory=list)

    @property
    def reference_ids(self) -> list[str]:
        return [str(item["id"]) for item in self.matched][:MAX_MATCHED_REFERENCES]

    def rationale(self) -> str:
        named = "; ".join(_describe(item) for item in self.matched[:MAX_NAMED_REFERENCES])
        more = len(self.matched) - MAX_NAMED_REFERENCES
        text = (
            f"Own experience: {len(self.matched)} recorded project reference(s) match this requirement: {named}"
            + (f"; and {more} more" if more > 0 else "")
            + "."
        )
        if self.unproven:
            text += " Still unproven: " + "; ".join(self.unproven) + "."
        if self.excluded:
            text += " Not counted: " + "; ".join(
                f"{_describe(item)} - {reason}" for item, reason in self.excluded[:MAX_NAMED_REFERENCES]
            ) + "."
        return text + " A reviewer must confirm before this counts as evidence."


def match_own_references(
    *,
    text: str,
    predicate: dict[str, Any] | None,
    references: list[dict[str, Any]],
    as_of: date,
) -> OwnExperienceMatch:
    """Match the organization's current project references to one experience requirement.

    A reference matches when its sector, service, name or scope shares the
    requirement's subject (one domain word, or two words of any kind) and no
    recorded fact contradicts a condition the requirement states: completion,
    the recency window, a lead-only role, or a named country/region. Facts that
    are missing never exclude a reference; they are reported as still unproven.
    """
    result = OwnExperienceMatch()
    requirement_terms = terms(text)
    if not requirement_terms or not references:
        return result
    window = recency_window_years(text + " " + str((predicate or {}).get("condition") or ""))
    cutoff = _years_ago(as_of, window) if window else None
    completion_required = _COMPLETED.search(text) is not None
    lead_required = _LEAD_ONLY.search(text) is not None
    named_countries = _named_countries(text)
    missing_dates: list[str] = []
    unknown_completion: list[str] = []
    unknown_role: list[str] = []
    unknown_country: list[str] = []
    for reference in references:
        reference_terms = terms(" ".join(
            str(reference.get(key) or "") for key in ("sector", "service", "project_name", "relevant_scope")
        ))
        shared = requirement_terms & reference_terms
        if not (shared - _ACTIVITY) and len(shared) < 2:
            continue
        name = str(reference.get("project_name") or "Unnamed reference")
        completion = str(reference.get("completion_state") or "UNKNOWN")
        if completion == "NOT_COMPLETED":
            result.excluded.append((reference, "recorded as not completed"))
            continue
        if completion_required and completion == "ONGOING":
            result.excluded.append((reference, "still ongoing; the requirement asks for completed work"))
            continue
        if completion_required and completion == "UNKNOWN":
            unknown_completion.append(name)
        if cutoff:
            finished = _parse_date(reference.get("completion_date"))
            ended = as_of if completion == "ONGOING" else finished
            if ended is None:
                missing_dates.append(name)
            elif ended < cutoff:
                result.excluded.append((reference, f"ended {ended.year}, outside the {window}-year window"))
                continue
        role = str(reference.get("role") or "UNKNOWN")
        if lead_required:
            if role == "UNKNOWN":
                unknown_role.append(name)
            elif role != "LEAD":
                result.excluded.append((reference, f"role {role}; the requirement asks for the lead role"))
                continue
        country = " ".join(str(reference.get("country") or "").split()).casefold()
        if named_countries:
            if not country:
                unknown_country.append(name)
            elif country not in named_countries:
                result.excluded.append((reference, "outside the country or region the requirement names"))
                continue
        result.matched.append(reference)
    if not result.matched:
        return result

    unproven: list[str] = ["the references are recorded claims and Plasma has not verified their contents"]
    unreviewed = sum(1 for item in result.matched if item.get("evidence_state") not in {"VERIFIED", "REVIEWED"})
    if unreviewed:
        unproven.append(f"{unreviewed} matched reference(s) are not evidence-reviewed")
    metadata_only = sum(1 for item in result.matched if item.get("evidence_basis") != "FILE_BACKED")
    if metadata_only:
        unproven.append(f"{metadata_only} matched reference(s) have no supporting document on record")
    required = _required_count(predicate)
    if required is not None:
        if len(result.matched) < required:
            unproven.append(f"{len(result.matched)} of the {required} required comparable references are recorded")
        else:
            unproven.append(f"the count of {required} is met by recorded references only")
    if missing_dates:
        unproven.append(f"completion date not recorded for {', '.join(missing_dates[:3])} ({window}-year window)")
    if unknown_completion:
        unproven.append(f"completion not recorded for {', '.join(unknown_completion[:3])}")
    if unknown_role:
        unproven.append(f"role not recorded for {', '.join(unknown_role[:3])} (lead role required)")
    if unknown_country:
        unproven.append(f"country not recorded for {', '.join(unknown_country[:3])}")
    unproven.extend(_other_thresholds(predicate))
    result.unproven = unproven
    return result
