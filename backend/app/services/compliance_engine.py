"""
Plasma AI — Hybrid Deterministic Compliance Match Engine

Pure-Python boolean logic that decides bid eligibility. The LLM is NOT
allowed to make pass/fail decisions — it only extracts and classifies
requirements (via ``TenderRequirement``). This module executes the
deterministic verdict.

Hybrid Architecture (strict sequence):
    Step A — UUID Strike:
        If a requirement has a mapped taxonomy UUID, check for strict
        set intersection with the user's ``CompanyCredential`` UUIDs.
        This is 100% precise when taxonomy coverage exists.

    Step B — Structured Vault Match:
        If the requirement is source-verified and bid-affecting, match
        supported certification/license evidence from ``CompanyProfile``.

    Step C — Token Fallback / Manual Guard:
        If token overlap is below threshold, route to manual review.
        We NEVER silently assume pass or fail on uncertain matches.

Design Principles:
    - **Defensive by default**: uncertain ≠ pass. Uncertain = manual review.
    - **No false negatives**: if there's any chance a cert/license covers
      a requirement, it goes to manual review rather than auto-fail.
    - **No false positives**: a "match" requires normalized-text overlap
      above a strict threshold.
    - **Zero LLM calls**: this module is pure Python. Deterministic.
      Auditable. Reproducible.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.core.agents.requirement_extractor import (
    EvidenceValidationStatus,
    RequirementCategory,
    ScopeReviewStatus,
    TenderRequirement,
)
from app.core.evaluator import TaxNodeInfo
from app.models.company import CompanyProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result Models
# ---------------------------------------------------------------------------

class MatchVerdict(str, Enum):
    """Outcome of matching a single requirement against the profile."""

    SATISFIED = "SATISFIED"
    """Deterministic match found — the profile covers this requirement."""

    FAILED = "FAILED"
    """Deterministic absence — the profile definitively lacks this requirement."""

    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
    """Cannot determine programmatically — escalate to human."""


class MatchMethod(str, Enum):
    """How the match verdict was determined."""

    UUID_TAXONOMY = "UUID_TAXONOMY"
    """Resolved via exact UUID set intersection (old taxonomy system)."""

    TOKEN_OVERLAP = "TOKEN_OVERLAP"
    """Resolved via calibrated token overlap on free text."""

    VAULT_DETERMINISTIC = "VAULT_DETERMINISTIC"
    """Resolved via explicit structured Company Vault evidence."""

    SKIPPED = "SKIPPED"
    """Not evaluated (optional / too vague)."""


class VaultRequirementType(str, Enum):
    """Structured evidence class required by a tender requirement."""

    CERTIFICATION = "certification"
    LICENSE = "license"
    FINANCIAL = "financial"
    TAX_CLEARANCE = "tax_clearance"
    BID_SECURITY = "bid_security"
    PERSONNEL = "personnel"
    UNKNOWN = "unknown"


class ComplianceVerdictStatus(str, Enum):
    """Top-level compliance verdict semantics for UI/reporting."""

    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    """At least one verified bid-stage DQ requirement failed."""

    NEEDS_REVIEW = "NEEDS_REVIEW"
    """No fatal failure, but the result is not fully verified."""

    ELIGIBLE_WITH_REVIEW = "ELIGIBLE_WITH_REVIEW"
    """No fatal failure and some requirements pass, but review remains."""

    COMPLIANT = "COMPLIANT"
    """No fatal failure, no manual review, and at least one requirement passed."""


class RequirementMatchDetail(BaseModel):
    """Detailed match result for a single tender requirement."""

    model_config = ConfigDict(extra="forbid")

    category: str
    headline: str
    source_filename: str
    source_page: int
    exact_quote: str
    raw_text_snippet: str
    requirement_type: str
    is_dealbreaker: bool
    confidence_score: float = 1.0
    validation_status: str = "needs_review"
    validation_reason: str = "Evidence has not been validated yet."
    source_verified: bool = False
    requirement_scope: str = "informational"
    scope_review_status: str = "needs_review"
    affects_bid_eligibility: bool = False
    eligibility_reason: str = "Bid-stage eligibility impact has not been classified yet."
    verdict: MatchVerdict
    match_method: MatchMethod = MatchMethod.SKIPPED
    matched_credential: str | None = None
    taxonomy_node_id: str | None = None
    parent_section_header: str | None = None
    vault_match_type: str | None = None
    vault_match_source: str | None = None
    vault_evidence_id: str | None = None
    vault_match_confidence: float | None = None
    vault_missing_reason: str | None = None
    reason: str


class ComplianceResult(BaseModel):
    """
    Final compliance verdict for a tender against a company profile.

    This is the output contract consumed by the API layer and UI.
    """

    model_config = ConfigDict(extra="forbid")

    is_eligible: bool = Field(
        ...,
        description=(
            "Hard boolean. False if ANY mandatory dealbreaker requirement "
            "is definitively missing from the profile."
        ),
    )
    total_requirements: int = Field(
        ...,
        description="Total number of requirements evaluated.",
    )
    satisfied_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    manual_review_count: int = Field(default=0)
    skipped_optional_count: int = Field(default=0)
    recorded_obligations_count: int = Field(default=0)
    skipped_non_bid_obligations_count: int = Field(default=0)
    uuid_match_count: int = Field(
        default=0,
        description="Number of requirements resolved via UUID taxonomy match.",
    )
    token_match_count: int = Field(
        default=0,
        description="Number of requirements resolved via token overlap fallback.",
    )
    verdict_status: ComplianceVerdictStatus = Field(
        default=ComplianceVerdictStatus.NEEDS_REVIEW,
        description=(
            "Additive top-level verdict. Unlike is_eligible, this distinguishes "
            "fully compliant results from results that still require review."
        ),
    )

    failed_dealbreakers: list[RequirementMatchDetail] = Field(
        default_factory=list,
        description=(
            "MANDATORY requirements that are definitively missing. "
            "Each one is a hard disqualification reason."
        ),
    )
    manual_reviews_required: list[RequirementMatchDetail] = Field(
        default_factory=list,
        description=(
            "Requirements that could not be deterministically resolved. "
            "The UI must prompt the user to manually verify these."
        ),
    )
    satisfied_requirements: list[RequirementMatchDetail] = Field(
        default_factory=list,
        description="Requirements confirmed as met by the profile.",
    )
    recorded_obligations: list[RequirementMatchDetail] = Field(
        default_factory=list,
        description=(
            "Verified requirements recorded for awareness but not counted as "
            "credential/profile matches or bid-stage failures."
        ),
    )
    status_message: str = Field(
        default="",
        description="Human-readable summary of the compliance verdict.",
    )


def _category_value(req: TenderRequirement) -> str:
    return req.category.value if isinstance(req.category, RequirementCategory) else str(req.category)


def _is_dq(req: TenderRequirement) -> bool:
    return req.category == RequirementCategory.DQ


def _enum_value(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _is_source_verified(req: TenderRequirement) -> bool:
    return (
        req.validation_status == EvidenceValidationStatus.ACCEPTED
        and req.source_verified
    )


def _scope_needs_review(req: TenderRequirement) -> bool:
    return req.scope_review_status == ScopeReviewStatus.NEEDS_REVIEW


def _affects_bid_eligibility(req: TenderRequirement) -> bool:
    return bool(req.affects_bid_eligibility and _is_source_verified(req))


def _is_bid_dealbreaker(req: TenderRequirement) -> bool:
    return _is_dq(req) and _affects_bid_eligibility(req)


def _build_top_level_verdict(
    *,
    failed_dealbreaker_count: int,
    manual_review_count: int,
    satisfied_count: int,
    skipped_optional_count: int,
    recorded_obligations_count: int = 0,
    uuid_match_count: int,
    token_match_count: int,
) -> tuple[ComplianceVerdictStatus, str]:
    """Return the additive top-level verdict and safe user-facing message."""
    if failed_dealbreaker_count > 0:
        status = ComplianceVerdictStatus.NOT_ELIGIBLE
        parts = [
            f"NOT ELIGIBLE — {failed_dealbreaker_count} mandatory dealbreaker(s) failed",
            f"{satisfied_count} satisfied",
        ]
        if recorded_obligations_count:
            parts.append(f"{recorded_obligations_count} obligations recorded")
        if manual_review_count:
            parts.append(f"{manual_review_count} require manual review")
        if skipped_optional_count:
            parts.append(f"{skipped_optional_count} optional skipped")
        # parts.append(f"[{uuid_match_count} UUID / {token_match_count} token]")
        return status, " | ".join(parts)

    if manual_review_count > 0 and satisfied_count == 0 and recorded_obligations_count == 0:
        return (
            ComplianceVerdictStatus.NEEDS_REVIEW,
            "No verified requirements yet — manual review required.",
        )

    if manual_review_count > 0:
        status = ComplianceVerdictStatus.ELIGIBLE_WITH_REVIEW
        parts = [
            "ELIGIBLE WITH REVIEW — no failed bid-stage dealbreakers",
            f"{satisfied_count} satisfied",
            f"{manual_review_count} require manual review",
        ]
        if recorded_obligations_count:
            parts.append(f"{recorded_obligations_count} obligations recorded")
        if skipped_optional_count:
            parts.append(f"{skipped_optional_count} optional skipped")
        # parts.append(f"[{uuid_match_count} UUID / {token_match_count} token]")
        return status, " | ".join(parts)

    if satisfied_count > 0:
        status = ComplianceVerdictStatus.COMPLIANT
        parts = [
            "ELIGIBLE",
            f"{satisfied_count} satisfied",
        ]
        if skipped_optional_count:
            parts.append(f"{skipped_optional_count} optional skipped")
        # parts.append(f"[{uuid_match_count} UUID / {token_match_count} token]")
        return status, " | ".join(parts)

    if recorded_obligations_count > 0:
        status = ComplianceVerdictStatus.ELIGIBLE_WITH_REVIEW
        parts = [
            "ELIGIBLE WITH REVIEW — no failed bid-stage dealbreakers",
            f"{recorded_obligations_count} obligations recorded",
        ]
        if skipped_optional_count:
            parts.append(f"{skipped_optional_count} optional skipped")
        parts.append(f"[{uuid_match_count} UUID / {token_match_count} token]")
        return status, " | ".join(parts)

    return (
        ComplianceVerdictStatus.NEEDS_REVIEW,
        "No verified requirements yet — manual review required.",
    )


def _detail_base(req: TenderRequirement) -> dict[str, object]:
    category = _category_value(req)
    return {
        "category": category,
        "headline": req.headline,
        "source_filename": req.source_filename,
        "source_page": req.source_page,
        "exact_quote": req.exact_quote,
        # Backward-compatible fields consumed by the existing API/UI.
        "raw_text_snippet": req.exact_quote,
        "requirement_type": category,
        "is_dealbreaker": _is_bid_dealbreaker(req),
        "confidence_score": 1.0,
        "validation_status": _enum_value(req.validation_status),
        "validation_reason": req.validation_reason,
        "source_verified": req.source_verified,
        "requirement_scope": _enum_value(req.requirement_scope),
        "scope_review_status": _enum_value(req.scope_review_status),
        "affects_bid_eligibility": _affects_bid_eligibility(req),
        "eligibility_reason": req.eligibility_reason,
        "parent_section_header": None,
    }


# ---------------------------------------------------------------------------
# Text Normalization
# ---------------------------------------------------------------------------

# Precompiled regex for non-alphanumeric character stripping.
# IMPORTANT: The Uzbek Latin alphabet uses the standard apostrophe (')
# and the Unicode modifier letter turned comma (ʻ U+02BB) as integral
# parts of words (e.g. O'zbek / Oʻzbek, ta'minot, bo'lishi).  Stripping
# these destroys Uzbek tokens, so they are explicitly preserved.
# The Uzbek Cyrillic alphabet extends Russian with: ҳ(U+04B3) қ(U+049B)
# ғ(U+0493) ў(U+045E) and their uppercase forms.
_NON_ALNUM_RE: re.Pattern[str] = re.compile(
    r"[^a-zA-Z0-9"
    r"а-яА-ЯёЁ"           # Russian Cyrillic
    r"\u04b3\u04b2"         # ҳ Ҳ (Uzbek)
    r"\u049b\u049a"         # қ Қ (Uzbek)
    r"\u0493\u0492"         # ғ Ғ (Uzbek)
    r"\u045e\u040e"         # ў Ў (Uzbek)
    r"'\u02BB"              # apostrophe + modifier letter
    r"\s]"
)
_WHITESPACE_RE: re.Pattern[str] = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """
    Aggressively normalize text for fuzzy comparison.

    Steps:
        1. Unicode NFKD decomposition (handles accents, ligatures).
        2. Lowercase.
        3. Strip all non-alphanumeric characters (preserving Cyrillic).
        4. Collapse whitespace.
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.lower()
    text = _NON_ALNUM_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _tokenize(text: str) -> set[str]:
    """Split normalized text into a set of unique tokens."""
    return set(_normalize(text).split())


# ---------------------------------------------------------------------------
# Matching Primitives
# ---------------------------------------------------------------------------

# Minimum fraction of requirement tokens that must appear in a credential
# for us to consider it a deterministic match. Set high to avoid false
# positives — we'd rather send to manual review than auto-pass.
_MATCH_TOKEN_OVERLAP_THRESHOLD: float = 0.65

# Minimum number of meaningful tokens a requirement must have for us to
# even attempt token matching. Below this, the text is too short/vague
# to match deterministically.
_MIN_MEANINGFUL_TOKENS: int = 2

# ---------------------------------------------------------------------------
# Stop Words — Calibrated for B2G Compliance Matching
# ---------------------------------------------------------------------------
#
# CRITICAL DESIGN NOTE:
# We split stop words into two lists. The first list contains generic
# grammatical filler that never carries matching signal. The second list
# (commented out / removed) previously contained domain terms like
# "quality", "management", "construction", etc. that were INCORRECTLY
# stripped — these are the exact tokens that differentiate between
# ISO 9001 (Quality Management) and ISO 14001 (Environmental Management).
# They are now RETAINED for matching.
# ---------------------------------------------------------------------------

_STOP_WORDS: frozenset[str] = frozenset({
    # ── English: articles, prepositions, conjunctions, pronouns ──
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "of", "in", "to",
    "for", "with", "on", "at", "from", "by", "about", "as", "into",
    "through", "during", "before", "after", "and", "but", "or", "not",
    "no", "nor", "if", "then", "than", "that", "this", "these", "those",
    "it", "its", "all", "each", "every", "any", "both", "such",
    # ── English: tender boilerplate (no matching signal) ──
    "required", "requirement", "requirements", "mandatory", "necessary",
    "bidder", "supplier", "contractor", "company", "organization",
    "provide", "submit", "present", "document", "copy",
    "valid", "current", "active", "hold", "possess",
    # ── Russian: grammatical filler ──
    "и", "в", "на", "с", "по", "для", "от", "до", "из", "к", "о",
    "об", "не", "что", "как", "это", "все", "или", "но", "при",
    "также", "должен", "должна", "должно", "должны", "быть",
    # ── Russian: tender boilerplate ──
    "необходимо", "требуется", "обязательно", "наличие",
    "участник", "поставщик", "подрядчик", "организация",
    "предоставить", "представить", "документ", "копия", "копию",
    # ── Uzbek Latin: grammatical filler ──
    "va", "yoki", "ham", "bilan", "uchun", "da", "dan", "ga", "ni", "ning",
    # ── Uzbek Cyrillic: grammatical filler ──
    "ва", "ёки", "ҳам", "билан", "учун", "да", "дан", "га", "ни", "нинг",
    # ── Uzbek Latin: tender boilerplate ──
    "kerak", "lozim", "shart", "bo'lishi", "ta'minlash", "yetkazib",
    "beruvchi", "ishtirokchi", "tashkilot", "hujjat", "nusxa",
    "talab", "etiladi",
    # ── Uzbek Cyrillic: tender boilerplate ──
    "керак", "лозим", "шарт", "бўлиши", "таъминлаш", "етказиб",
    "берувчи", "иштирокчи", "ташкилот", "ҳужжат", "нусха",
    "талаб", "этилади",
    #
    # ── EXPLICITLY NOT STRIPPED (domain-critical B2G terms): ──
    # "quality", "management", "environmental", "construction",
    # "safety", "medical", "audit", "electrical", "fire",
    # "technical", "industrial", "energy", "health", "occupational",
    # "information", "security", "engineering", "installation",
    # "manufacturing", "production", "supply", "equipment",
    # "строительство", "безопасность", "качество", "экологический",
    # "медицинский", "пожарный", "электрический", "технический",
})


def _meaningful_tokens(text: str) -> set[str]:
    """Extract tokens with actual matching signal (no stop words)."""
    return _tokenize(text) - _STOP_WORDS


def _compute_token_overlap(
    requirement_tokens: set[str],
    credential_tokens: set[str],
) -> float:
    """
    Compute the fraction of requirement tokens found in the credential.

    Returns a value between 0.0 and 1.0. A value of 1.0 means every
    meaningful requirement token appears in the credential text.
    """
    if not requirement_tokens:
        return 0.0
    overlap = requirement_tokens & credential_tokens
    return len(overlap) / len(requirement_tokens)


_CERTIFICATION_TERMS: tuple[str, ...] = (
    "certificate",
    "certification",
    "certified",
    "iso",
    "conformity",
    "сертификат",
    "sertifikat",
)

_LICENSE_TERMS: tuple[str, ...] = (
    "license",
    "licence",
    "licensed",
    "permit",
    "authorization",
    "authorisation",
    "лиценз",
    "разрешени",
    "litsenziya",
)

_FINANCIAL_REQUIREMENT_TERMS: tuple[str, ...] = (
    "turnover",
    "working capital",
    "financial capacity",
    "current assets",
    "current liabilities",
    "balance sheet",
    "revenue",
    "cash flow",
    "оборот",
    "выручк",
)

_TAX_CLEARANCE_TERMS: tuple[str, ...] = (
    "tax debt",
    "tax clearance",
    "tax liabilities",
    "no overdue tax",
    "no outstanding tax",
    "налог",
    "задолженность",
)

_BID_SECURITY_TERMS: tuple[str, ...] = (
    "bid security",
    "proposal security",
    "tender security",
    "bid guarantee",
    "bank guarantee",
    "tender guarantee",
    "обеспечение заявки",
    "банковск",
    "гарант",
)

_PERSONNEL_TERMS: tuple[str, ...] = (
    "personnel",
    "staff",
    "employee",
    "engineer",
    "specialist",
    "medical book",
    "medical certificate",
    "санитарн",
    "медицинск",
    "ходим",
    "мутахассис",
)


def _contains_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _requirement_text(req: TenderRequirement) -> str:
    return " ".join(part for part in (req.headline, req.exact_quote) if part)


def _classify_vault_requirement_type(req: TenderRequirement) -> VaultRequirementType:
    text = _normalize(_requirement_text(req))

    if _contains_term(text, _BID_SECURITY_TERMS):
        return VaultRequirementType.BID_SECURITY
    if _contains_term(text, _TAX_CLEARANCE_TERMS):
        return VaultRequirementType.TAX_CLEARANCE
    if _contains_term(text, _FINANCIAL_REQUIREMENT_TERMS):
        return VaultRequirementType.FINANCIAL
    if _contains_term(text, _PERSONNEL_TERMS):
        return VaultRequirementType.PERSONNEL
    if _contains_term(text, _LICENSE_TERMS):
        return VaultRequirementType.LICENSE
    if _contains_term(text, _CERTIFICATION_TERMS):
        return VaultRequirementType.CERTIFICATION

    return VaultRequirementType.UNKNOWN


def _compact_key(text: str) -> str:
    return "".join(_normalize(text).split())


_ISO_RE: re.Pattern[str] = re.compile(r"\biso\s*[- ]?\s*(\d{3,5})\b", re.IGNORECASE)


def _iso_aliases(text: str) -> set[str]:
    return {f"iso{match.group(1)}" for match in _ISO_RE.finditer(text)}


def _evidence_id(item: object) -> str | None:
    raw_id = getattr(item, "id", None)
    return str(raw_id) if raw_id is not None else None


def _cert_match_confidence(requirement_text: str, cert_type: str) -> float:
    req_iso = _iso_aliases(requirement_text)
    cert_iso = _iso_aliases(cert_type)
    if req_iso and cert_iso and req_iso & cert_iso:
        return 1.0

    req_key = _compact_key(requirement_text)
    cert_key = _compact_key(cert_type)
    if cert_key and (cert_key in req_key or req_key in cert_key):
        return 1.0

    req_tokens = _meaningful_tokens(requirement_text)
    cert_tokens = _meaningful_tokens(cert_type)
    if not req_tokens or not cert_tokens:
        return 0.0

    if {"conformity", "certificate"} <= req_tokens:
        required = {"conformity"}
        if "food" in req_tokens:
            required.add("food")
        if required <= cert_tokens:
            return min(1.0, len(required) / max(len(required), 1))

    if cert_tokens <= req_tokens:
        return 1.0

    return _compute_token_overlap(req_tokens, cert_tokens)


def _license_match_confidence(requirement_text: str, license_name: str) -> float:
    req_key = _compact_key(requirement_text)
    lic_key = _compact_key(license_name)
    if lic_key and (lic_key in req_key or req_key in lic_key):
        return 1.0

    req_tokens = _meaningful_tokens(requirement_text)
    license_tokens = _meaningful_tokens(license_name)
    if not req_tokens or not license_tokens:
        return 0.0

    return _compute_token_overlap(req_tokens, license_tokens)


def _failed_or_review_for_missing_vault_evidence(
    req: TenderRequirement,
    *,
    vault_type: VaultRequirementType,
    missing_reason: str,
    matched_credential: str | None = None,
    evidence_id: str | None = None,
    confidence: float | None = None,
) -> RequirementMatchDetail:
    verdict = (
        MatchVerdict.FAILED
        if _is_bid_dealbreaker(req)
        else MatchVerdict.NEEDS_MANUAL_REVIEW
    )
    return RequirementMatchDetail(
        **_detail_base(req),
        verdict=verdict,
        match_method=MatchMethod.VAULT_DETERMINISTIC,
        matched_credential=matched_credential,
        vault_match_type=vault_type.value,
        vault_match_source="company_vault",
        vault_evidence_id=evidence_id,
        vault_match_confidence=confidence,
        vault_missing_reason=missing_reason,
        reason=missing_reason,
    )


def _match_certification_requirement(
    req: TenderRequirement,
    profile: CompanyProfile,
) -> RequirementMatchDetail:
    requirement_text = _requirement_text(req)
    best_cert: object | None = None
    best_confidence = 0.0

    for cert in profile.certifications:
        confidence = _cert_match_confidence(requirement_text, cert.cert_type)
        if confidence > best_confidence:
            best_confidence = confidence
            best_cert = cert

    if best_cert is None or best_confidence < _MATCH_TOKEN_OVERLAP_THRESHOLD:
        return _failed_or_review_for_missing_vault_evidence(
            req,
            vault_type=VaultRequirementType.CERTIFICATION,
            missing_reason=(
                "No matching active certification was found in Company Vault."
            ),
            confidence=best_confidence,
        )

    cert_name = best_cert.cert_type
    evidence_id = _evidence_id(best_cert)
    if best_cert.expiry_date < date.today():
        return _failed_or_review_for_missing_vault_evidence(
            req,
            vault_type=VaultRequirementType.CERTIFICATION,
            matched_credential=cert_name,
            evidence_id=evidence_id,
            confidence=best_confidence,
            missing_reason=(
                f"Matching certification '{cert_name}' exists in Company Vault "
                f"but expired on {best_cert.expiry_date.isoformat()}."
            ),
        )

    return RequirementMatchDetail(
        **_detail_base(req),
        verdict=MatchVerdict.SATISFIED,
        match_method=MatchMethod.VAULT_DETERMINISTIC,
        matched_credential=cert_name,
        vault_match_type=VaultRequirementType.CERTIFICATION.value,
        vault_match_source="company_vault",
        vault_evidence_id=evidence_id,
        vault_match_confidence=best_confidence,
        reason=(
            f"Company Vault certification '{cert_name}' satisfies this "
            f"requirement (confidence: {best_confidence:.0%})."
        ),
    )


def _match_license_requirement(
    req: TenderRequirement,
    profile: CompanyProfile,
) -> RequirementMatchDetail:
    requirement_text = _requirement_text(req)
    best_license: object | None = None
    best_confidence = 0.0

    for license_item in profile.licenses:
        confidence = _license_match_confidence(
            requirement_text,
            license_item.license_name,
        )
        if confidence > best_confidence:
            best_confidence = confidence
            best_license = license_item

    if best_license is None or best_confidence < _MATCH_TOKEN_OVERLAP_THRESHOLD:
        return _failed_or_review_for_missing_vault_evidence(
            req,
            vault_type=VaultRequirementType.LICENSE,
            missing_reason="No matching active license was found in Company Vault.",
            confidence=best_confidence,
        )

    license_name = best_license.license_name
    evidence_id = _evidence_id(best_license)
    if not best_license.is_active:
        return _failed_or_review_for_missing_vault_evidence(
            req,
            vault_type=VaultRequirementType.LICENSE,
            matched_credential=license_name,
            evidence_id=evidence_id,
            confidence=best_confidence,
            missing_reason=(
                f"Matching license '{license_name}' exists in Company Vault "
                "but is marked inactive."
            ),
        )

    return RequirementMatchDetail(
        **_detail_base(req),
        verdict=MatchVerdict.SATISFIED,
        match_method=MatchMethod.VAULT_DETERMINISTIC,
        matched_credential=license_name,
        vault_match_type=VaultRequirementType.LICENSE.value,
        vault_match_source="company_vault",
        vault_evidence_id=evidence_id,
        vault_match_confidence=best_confidence,
        reason=(
            f"Company Vault license '{license_name}' satisfies this "
            f"requirement (confidence: {best_confidence:.0%})."
        ),
    )


_UNSTRUCTURED_VAULT_TYPE_REASON: dict[VaultRequirementType, str] = {
    VaultRequirementType.FINANCIAL: (
        "Financial threshold matching is not yet structured in Company Vault "
        "for this requirement type."
    ),
    VaultRequirementType.TAX_CLEARANCE: (
        "Tax clearance evidence is not yet structured in Company Vault."
    ),
    VaultRequirementType.BID_SECURITY: (
        "Bid/proposal security or bank guarantee evidence is not yet "
        "structured in Company Vault."
    ),
    VaultRequirementType.PERSONNEL: (
        "Personnel/staff evidence is not yet structured in Company Vault."
    ),
    VaultRequirementType.UNKNOWN: (
        "This requirement could not be mapped to a supported Company Vault "
        "evidence type."
    ),
}


def _match_via_structured_vault(
    req: TenderRequirement,
    profile: CompanyProfile,
) -> RequirementMatchDetail:
    vault_type = _classify_vault_requirement_type(req)

    if vault_type == VaultRequirementType.CERTIFICATION:
        return _match_certification_requirement(req, profile)
    if vault_type == VaultRequirementType.LICENSE:
        return _match_license_requirement(req, profile)

    return _failed_or_review_for_missing_vault_evidence(
        req,
        vault_type=vault_type,
        missing_reason=_UNSTRUCTURED_VAULT_TYPE_REASON[vault_type],
    )


# ---------------------------------------------------------------------------
# Credential Inventory Builder (for Token Fallback)
# ---------------------------------------------------------------------------

class _CredentialEntry:
    """Internal representation of a single user credential for matching."""

    __slots__ = (
        "source_type",
        "raw_name",
        "tokens",
        "is_active",
        "is_expired",
        "evidence_id",
    )

    def __init__(
        self,
        source_type: str,
        raw_name: str,
        tokens: set[str],
        is_active: bool,
        is_expired: bool,
        evidence_id: str | None = None,
    ) -> None:
        self.source_type = source_type
        self.raw_name = raw_name
        self.tokens = tokens
        self.is_active = is_active
        self.is_expired = is_expired
        self.evidence_id = evidence_id


def _build_credential_inventory(
    profile: CompanyProfile,
) -> list[_CredentialEntry]:
    """
    Flatten the profile's certifications and licenses into a unified
    list of credential entries for token matching.
    """
    today = date.today()
    inventory: list[_CredentialEntry] = []

    for cert in profile.certifications:
        inventory.append(
            _CredentialEntry(
                source_type="certification",
                raw_name=cert.cert_type,
                tokens=_meaningful_tokens(cert.cert_type),
                is_active=True,  # Certifications don't have is_active
                is_expired=cert.expiry_date < today,
                evidence_id=_evidence_id(cert),
            )
        )

    for lic in profile.licenses:
        inventory.append(
            _CredentialEntry(
                source_type="license",
                raw_name=lic.license_name,
                tokens=_meaningful_tokens(lic.license_name),
                is_active=lic.is_active,
                is_expired=False,  # Licenses don't have expiry_date
                evidence_id=_evidence_id(lic),
            )
        )

    return inventory


# ---------------------------------------------------------------------------
# Step A: UUID Taxonomy Strike
# ---------------------------------------------------------------------------

def _match_via_uuid(
    req: TenderRequirement,
    credential_uuids: set[str],
    taxonomy_lookup: dict[str, TaxNodeInfo],
    taxonomy_uuid: str,
) -> RequirementMatchDetail:
    """
    Attempt 100%-precise UUID set intersection matching.

    This is the preferred path — if a requirement maps to a taxonomy
    node, we check if the user holds that credential UUID. No ambiguity.
    """
    if not _is_source_verified(req):
        return RequirementMatchDetail(
            **_detail_base(req),
            verdict=MatchVerdict.NEEDS_MANUAL_REVIEW,
            match_method=MatchMethod.SKIPPED,
            matched_credential=None,
            taxonomy_node_id=taxonomy_uuid,
            reason=(
                "Requirement source evidence is not verified; manual review "
                f"required before eligibility impact can be trusted: {req.validation_reason}"
            ),
        )

    if _scope_needs_review(req):
        return RequirementMatchDetail(
            **_detail_base(req),
            verdict=MatchVerdict.NEEDS_MANUAL_REVIEW,
            match_method=MatchMethod.SKIPPED,
            matched_credential=None,
            taxonomy_node_id=taxonomy_uuid,
            reason=(
                "Requirement source evidence is verified, but bid-stage "
                f"eligibility impact needs review: {req.eligibility_reason}"
            ),
        )

    if not _affects_bid_eligibility(req):
        return RequirementMatchDetail(
            **_detail_base(req),
            verdict=MatchVerdict.SATISFIED,
            match_method=MatchMethod.SKIPPED,
            matched_credential=None,
            taxonomy_node_id=taxonomy_uuid,
            reason=(
                "Requirement recorded as non-bid obligation/evidence; "
                f"not evaluated as a fatal eligibility blocker. {req.eligibility_reason}"
            ),
        )

    node_info = taxonomy_lookup.get(taxonomy_uuid)
    node_name = node_info.name if node_info else taxonomy_uuid

    if taxonomy_uuid in credential_uuids:
        return RequirementMatchDetail(
            **_detail_base(req),
            verdict=MatchVerdict.SATISFIED,
            match_method=MatchMethod.UUID_TAXONOMY,
            matched_credential=node_name,
            taxonomy_node_id=taxonomy_uuid,
            reason=(
                f"UUID taxonomy match: credential '{node_name}' "
                f"(node_id={taxonomy_uuid}) is held by the user."
            ),
        )

    # UUID exists in taxonomy but user doesn't hold it. Only source-verified
    # bid-stage DQ items can be fatal.
    is_fatal = _is_bid_dealbreaker(req) and (node_info.is_fatal if node_info else True)
    verdict = MatchVerdict.FAILED if is_fatal else MatchVerdict.NEEDS_MANUAL_REVIEW

    return RequirementMatchDetail(
        **_detail_base(req),
        verdict=verdict,
        match_method=MatchMethod.UUID_TAXONOMY,
        matched_credential=None,
        taxonomy_node_id=taxonomy_uuid,
        reason=(
            f"UUID taxonomy miss: credential '{node_name}' "
            f"(node_id={taxonomy_uuid}) is NOT held by the user. "
            f"{'Fatal requirement.' if is_fatal else 'Non-fatal — routed to manual review.'}"
        ),
    )


# ---------------------------------------------------------------------------
# Step B: Token Overlap Fallback
# ---------------------------------------------------------------------------

def _match_via_token_overlap(
    req: TenderRequirement,
    inventory: list[_CredentialEntry],
) -> RequirementMatchDetail:
    """
    Attempt token-overlap matching against the credential inventory.
    Used when no UUID taxonomy mapping exists for the requirement.

    Decision tree:
        1. If requirement is NICE_TO_HAVE or COMPLIANT → preserve as evidence.
        2. Extract meaningful tokens from the requirement snippet.
        3. If too few meaningful tokens → NEEDS_MANUAL_REVIEW.
        4. Scan inventory for token overlap above threshold.
           a. Strong match + credential active/valid → SATISFIED.
           b. Strong match + credential expired/inactive → FAILED.
           c. Partial overlap → NEEDS_MANUAL_REVIEW.
           d. No overlap → FAILED (if dealbreaker) or MANUAL_REVIEW.
    """
    category = req.category
    snippet = req.exact_quote

    if not _is_source_verified(req):
        return RequirementMatchDetail(
            **_detail_base(req),
            verdict=MatchVerdict.NEEDS_MANUAL_REVIEW,
            match_method=MatchMethod.SKIPPED,
            matched_credential=None,
            reason=(
                "Requirement source evidence is not verified; manual review "
                f"required before eligibility impact can be trusted: {req.validation_reason}"
            ),
        )

    if _scope_needs_review(req):
        return RequirementMatchDetail(
            **_detail_base(req),
            verdict=MatchVerdict.NEEDS_MANUAL_REVIEW,
            match_method=MatchMethod.SKIPPED,
            matched_credential=None,
            reason=(
                "Requirement source evidence is verified, but bid-stage "
                f"eligibility impact needs review: {req.eligibility_reason}"
            ),
        )

    if not _affects_bid_eligibility(req):
        return RequirementMatchDetail(
            **_detail_base(req),
            verdict=MatchVerdict.SATISFIED,
            match_method=MatchMethod.SKIPPED,
            matched_credential=None,
            reason=(
                "Requirement recorded as non-bid obligation/evidence; "
                f"not evaluated as a fatal eligibility blocker. {req.eligibility_reason}"
            ),
        )

    # ── 1. Non-DQ items: preserve as visible evidence, never as blockers ──
    if category in (RequirementCategory.NICE_TO_HAVE, RequirementCategory.COMPLIANT):
        return RequirementMatchDetail(
            **_detail_base(req),
            verdict=MatchVerdict.SATISFIED,
            match_method=MatchMethod.SKIPPED,
            matched_credential=None,
            reason=(
                "Verified non-fatal evidence preserved for audit trail; "
                "not evaluated as a disqualification blocker."
            ),
        )

    # ── 2. Extract meaningful tokens ─────────────────────────────────
    req_tokens = _meaningful_tokens(snippet)

    # ── 3. Too few tokens → can't match deterministically ────────────
    if len(req_tokens) < _MIN_MEANINGFUL_TOKENS:
        return RequirementMatchDetail(
            **_detail_base(req),
            verdict=MatchVerdict.NEEDS_MANUAL_REVIEW,
            match_method=MatchMethod.TOKEN_OVERLAP,
            matched_credential=None,
            reason=(
                f"Requirement text too short/generic for deterministic matching "
                f"({len(req_tokens)} meaningful token(s)). Manual review required."
            ),
        )

    # ── 4. Scan inventory for matches ────────────────────────────────
    if not inventory:
        return RequirementMatchDetail(
            **_detail_base(req),
            verdict=MatchVerdict.FAILED,
            match_method=MatchMethod.TOKEN_OVERLAP,
            matched_credential=None,
            vault_match_type=_classify_vault_requirement_type(req).value,
            vault_match_source="company_vault",
            vault_match_confidence=0.0,
            vault_missing_reason="Profile contains zero Company Vault credentials.",
            reason="Profile contains zero credentials. Cannot satisfy any requirement.",
        )

    best_overlap: float = 0.0
    best_entry: _CredentialEntry | None = None

    for entry in inventory:
        overlap = _compute_token_overlap(req_tokens, entry.tokens)
        if overlap > best_overlap:
            best_overlap = overlap
            best_entry = entry

    # ── 5a. Strong match found ───────────────────────────────────────
    if best_overlap >= _MATCH_TOKEN_OVERLAP_THRESHOLD and best_entry is not None:
        if best_entry.is_expired:
            return RequirementMatchDetail(
                **_detail_base(req),
                verdict=MatchVerdict.FAILED,
                match_method=MatchMethod.TOKEN_OVERLAP,
                matched_credential=best_entry.raw_name,
                vault_match_type=best_entry.source_type,
                vault_match_source="company_vault",
                vault_evidence_id=best_entry.evidence_id,
                vault_match_confidence=best_overlap,
                vault_missing_reason=(
                    f"Matched {best_entry.source_type} is expired."
                ),
                reason=(
                    f"Matched {best_entry.source_type} '{best_entry.raw_name}' "
                    f"(overlap: {best_overlap:.0%}) but it is EXPIRED. "
                    "Requirement not satisfied."
                ),
            )
        if not best_entry.is_active:
            return RequirementMatchDetail(
                **_detail_base(req),
                verdict=MatchVerdict.FAILED,
                match_method=MatchMethod.TOKEN_OVERLAP,
                matched_credential=best_entry.raw_name,
                vault_match_type=best_entry.source_type,
                vault_match_source="company_vault",
                vault_evidence_id=best_entry.evidence_id,
                vault_match_confidence=best_overlap,
                vault_missing_reason=(
                    f"Matched {best_entry.source_type} is inactive."
                ),
                reason=(
                    f"Matched {best_entry.source_type} '{best_entry.raw_name}' "
                    f"(overlap: {best_overlap:.0%}) but it is INACTIVE. "
                    "Requirement not satisfied."
                ),
            )

        # Valid, active match
        return RequirementMatchDetail(
            **_detail_base(req),
            verdict=MatchVerdict.SATISFIED,
            match_method=MatchMethod.TOKEN_OVERLAP,
            matched_credential=best_entry.raw_name,
            vault_match_type=best_entry.source_type,
            vault_match_source="company_vault",
            vault_evidence_id=best_entry.evidence_id,
            vault_match_confidence=best_overlap,
            reason=(
                f"Token match: {best_entry.source_type} "
                f"'{best_entry.raw_name}' covers this requirement "
                f"(token overlap: {best_overlap:.0%})."
            ),
        )

    # ── 5c. Partial overlap → manual review ──────────────────────────
    _PARTIAL_OVERLAP_FLOOR: float = 0.30

    if best_overlap >= _PARTIAL_OVERLAP_FLOOR and best_entry is not None:
        return RequirementMatchDetail(
            **_detail_base(req),
            verdict=MatchVerdict.NEEDS_MANUAL_REVIEW,
            match_method=MatchMethod.TOKEN_OVERLAP,
            matched_credential=best_entry.raw_name,
            vault_match_type=best_entry.source_type,
            vault_match_source="company_vault",
            vault_evidence_id=best_entry.evidence_id,
            vault_match_confidence=best_overlap,
            vault_missing_reason=(
                "Potential Company Vault credential match is below the "
                "deterministic threshold."
            ),
            reason=(
                f"Partial match with {best_entry.source_type} "
                f"'{best_entry.raw_name}' (overlap: {best_overlap:.0%}), "
                f"below auto-pass threshold ({_MATCH_TOKEN_OVERLAP_THRESHOLD:.0%}). "
                "Manual verification required."
            ),
        )

    # ── 5d. No meaningful overlap → definitive failure ───────────────
    return RequirementMatchDetail(
        **_detail_base(req),
        verdict=MatchVerdict.FAILED,
        match_method=MatchMethod.TOKEN_OVERLAP,
        matched_credential=None,
        vault_match_type=_classify_vault_requirement_type(req).value,
        vault_match_source="company_vault",
        vault_match_confidence=best_overlap,
        vault_missing_reason="No matching Company Vault credential found.",
        reason=(
            "No matching credential found in profile. "
            f"Best overlap: {best_overlap:.0%} "
            f"(threshold: {_MATCH_TOKEN_OVERLAP_THRESHOLD:.0%})."
        ),
    )


# ---------------------------------------------------------------------------
# Public API: Hybrid Compliance Evaluation
# ---------------------------------------------------------------------------

def evaluate_tender_compliance(
    extracted_reqs: list[TenderRequirement],
    profile: CompanyProfile,
    *,
    credential_uuids: set[str] | None = None,
    taxonomy_lookup: dict[str, TaxNodeInfo] | None = None,
    mapped_requirement_uuids: list[str] | None = None,
) -> ComplianceResult:
    """
    Execute hybrid deterministic compliance evaluation.

    This is the primary public entry point. It runs a strict sequence:

    1. **UUID Strike** — For requirements with taxonomy mappings, perform
       exact UUID set intersection (100% precise, zero ambiguity).
    2. **Structured Vault Match** — For source-verified bid-stage requirements,
       deterministically match supported certification/license evidence.
    3. **Token Fallback** — Preserve legacy token matching for non-bid
       records and unstructured paths.
    4. **Manual Guard** — Anything below the overlap threshold is routed
       to manual review.

    Args:
        extracted_reqs: Requirements extracted by the LLM, already
                        validated through TenderRequirement's safeguard
                        validators.
        profile: A fully-hydrated CompanyProfile with certifications,
                 licenses, and financial_history loaded via
                 ``get_profile_for_compliance_match()``.
        credential_uuids: Optional set of taxonomy node UUIDs the user
                          holds via ``CompanyCredential``. Enables the
                          UUID Strike path.
        taxonomy_lookup: Optional dict mapping taxonomy_node_id to
                         TaxNodeInfo. Required for UUID Strike.
        mapped_requirement_uuids: Optional list of taxonomy UUIDs that
                                  the old AI extractor mapped from the
                                  tender text. These are matched 1:1
                                  against the extracted_reqs in order.

    Returns:
        A ComplianceResult with the deterministic verdict and full
        traceability for every requirement.
    """
    if not extracted_reqs:
        return ComplianceResult(
            is_eligible=True,
            total_requirements=0,
            verdict_status=ComplianceVerdictStatus.NEEDS_REVIEW,
            status_message="No verified requirements yet — manual review required.",
        )

    # Prepare both matching engines
    inventory = _build_credential_inventory(profile)
    uuid_matching_enabled = bool(
        credential_uuids is not None
        and taxonomy_lookup
        and mapped_requirement_uuids
    )

    # Build a set of taxonomy UUIDs for O(1) lookup
    mapped_uuid_set: set[str] = set()
    if mapped_requirement_uuids:
        mapped_uuid_set = set(mapped_requirement_uuids)

    logger.info(
        "Hybrid compliance engine: evaluating %d requirements against "
        "%d token credentials + %d taxonomy UUIDs (profile_id=%s). "
        "UUID matching: %s.",
        len(extracted_reqs),
        len(inventory),
        len(credential_uuids or set()),
        profile.id,
        "ENABLED" if uuid_matching_enabled else "DISABLED",
    )

    satisfied: list[RequirementMatchDetail] = []
    failed_dealbreakers: list[RequirementMatchDetail] = []
    manual_reviews: list[RequirementMatchDetail] = []
    recorded_obligations: list[RequirementMatchDetail] = []
    skipped_optional: int = 0
    skipped_non_bid_obligations: int = 0
    uuid_matches: int = 0
    token_matches: int = 0

    # We attempt to correlate extracted_reqs with mapped_requirement_uuids
    # by index. If the lists are misaligned, we fall back to token matching.
    for idx, req in enumerate(extracted_reqs):
        detail: RequirementMatchDetail | None = None

        # ── Step A: UUID Strike ──────────────────────────────────────
        if uuid_matching_enabled:
            # Try to find a UUID for this requirement.
            # Strategy: if mapped_requirement_uuids has a UUID at this index,
            # use it. Otherwise check if any mapped UUID text-matches this req.
            taxonomy_uuid: str | None = None

            if (
                mapped_requirement_uuids
                and idx < len(mapped_requirement_uuids)
            ):
                candidate = mapped_requirement_uuids[idx]
                if candidate and candidate in (taxonomy_lookup or {}):
                    taxonomy_uuid = candidate

            if taxonomy_uuid is not None:
                assert credential_uuids is not None
                assert taxonomy_lookup is not None
                detail = _match_via_uuid(
                    req, credential_uuids, taxonomy_lookup, taxonomy_uuid,
                )
                uuid_matches += 1
                logger.debug(
                    "UUID Strike [%s]: req=%s → %s",
                    taxonomy_uuid,
                    req.raw_text_snippet[:60],
                    detail.verdict.value,
                )

        # ── Step B: Structured Vault Match, then legacy fallback ──────
        if detail is None:
            if (
                _is_source_verified(req)
                and not _scope_needs_review(req)
                and _affects_bid_eligibility(req)
            ):
                detail = _match_via_structured_vault(req, profile)
            else:
                detail = _match_via_token_overlap(req, inventory)
            if detail.match_method == MatchMethod.TOKEN_OVERLAP:
                token_matches += 1

        # ── Step C: Route verdicts ───────────────────────────────────
        if detail.verdict == MatchVerdict.SATISFIED:
            if detail.match_method == MatchMethod.SKIPPED:
                recorded_obligations.append(detail)
                if not detail.affects_bid_eligibility:
                    skipped_non_bid_obligations += 1
                skipped_optional += 1
            else:
                satisfied.append(detail)

        elif detail.verdict == MatchVerdict.NEEDS_MANUAL_REVIEW:
            manual_reviews.append(detail)

        elif detail.verdict == MatchVerdict.FAILED:
            if detail.is_dealbreaker:
                failed_dealbreakers.append(detail)
                logger.warning(
                    "DEALBREAKER FAILED [%s]: '%s' — %s",
                    detail.match_method.value,
                    detail.raw_text_snippet[:100],
                    detail.reason,
                )
            else:
                # Non-dealbreaker failure → route to manual review
                detail_as_review = detail.model_copy(
                    update={
                        "verdict": MatchVerdict.NEEDS_MANUAL_REVIEW,
                        "reason": (
                            f"[Downgraded from FAILED] {detail.reason} "
                            "Non-dealbreaker — routed to manual review."
                        ),
                    }
                )
                manual_reviews.append(detail_as_review)

    # ── Final verdict ────────────────────────────────────────────────
    is_eligible = len(failed_dealbreakers) == 0
    verdict_status, status_message = _build_top_level_verdict(
        failed_dealbreaker_count=len(failed_dealbreakers),
        manual_review_count=len(manual_reviews),
        satisfied_count=len(satisfied),
        skipped_optional_count=skipped_optional,
        recorded_obligations_count=len(recorded_obligations),
        uuid_match_count=uuid_matches,
        token_match_count=token_matches,
    )
    logger.info("Compliance verdict: %s", status_message)

    return ComplianceResult(
        is_eligible=is_eligible,
        total_requirements=len(extracted_reqs),
        satisfied_count=len(satisfied),
        failed_count=len(failed_dealbreakers),
        manual_review_count=len(manual_reviews),
        skipped_optional_count=skipped_optional,
        recorded_obligations_count=len(recorded_obligations),
        skipped_non_bid_obligations_count=skipped_non_bid_obligations,
        uuid_match_count=uuid_matches,
        token_match_count=token_matches,
        verdict_status=verdict_status,
        failed_dealbreakers=failed_dealbreakers,
        manual_reviews_required=manual_reviews,
        satisfied_requirements=satisfied,
        recorded_obligations=recorded_obligations,
        status_message=status_message,
    )
