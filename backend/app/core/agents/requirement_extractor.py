"""
Plasma AI - Forensic Tender Requirement Extractor Agent

Extracts auditable procurement requirements from UzEx tender text. The LLM
is constrained to a strict five-field schema so every claim can be traced
back to a concrete file, page, and short source quote.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import logging
import os
import re
from dataclasses import dataclass
from enum import Enum
from uuid import uuid4

from google import genai
from google.genai import errors
from google.genai import types
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        logger.warning("Invalid integer for %s; using default %s.", name, default)
        return default


MODEL_NAME: str = os.getenv("GEMINI_REQUIREMENT_MODEL", "gemini-3.1-pro-preview")
EXTRACTOR_SCHEMA_VERSION: str = "requirement_extractor_scope_v5"
MAX_PAYLOAD_CHARS: int = _env_int("GEMINI_REQUIREMENT_MAX_PAYLOAD_CHARS", 120_000)
CHUNK_OVERLAP_CHARS: int = _env_int("GEMINI_REQUIREMENT_CHUNK_OVERLAP_CHARS", 1_000)
MAX_CHUNK_CONCURRENCY: int = max(
    1,
    _env_int("GEMINI_REQUIREMENT_CHUNK_CONCURRENCY", 3),
)
MAX_EXACT_QUOTE_WORDS: int = 15
MAX_HEADLINE_WORDS: int = 5
SYNTHETIC_SOURCE_FILENAME: str = "compiled_master_text"

_FILE_MARKER_RE: re.Pattern[str] = re.compile(r"\[\[FILE:\s*([^\]]+?)\s*\]\]")
_PAGE_MARKER_RE: re.Pattern[str] = re.compile(r"\[\[PAGE\s+(\d+)\]\]")
_BRACKETED_FILENAME_RE: re.Pattern[str] = re.compile(
    r"^\s*\[([^\]\n]+\.(?:pdf|docx?|xlsx?|txt|rtf|rar|zip|7z))\]\s*$",
    re.IGNORECASE | re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Enum: RequirementCategory
# ---------------------------------------------------------------------------

class RequirementCategory(str, Enum):
    """
    Strict forensic risk taxonomy.

    DQ            - True disqualification risk only.
    NICE_TO_HAVE  - Non-fatal preference, formatting, scoring, or soft criterion.
    COMPLIANT     - Verified non-risk evidence preserved for audit traceability.
    """

    DQ = "DQ"
    NICE_TO_HAVE = "NICE_TO_HAVE"
    COMPLIANT = "COMPLIANT"


# Backward-compatible import alias for older modules during the sprint.
RequirementType = RequirementCategory


class EvidenceValidationStatus(str, Enum):
    """Backend-owned evidence validation status for extracted requirements."""

    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class RequirementScope(str, Enum):
    """Backend-owned bid-stage scope classification."""

    BID_SUBMISSION = "bid_submission"
    ELIGIBILITY = "eligibility"
    TECHNICAL_COMPLIANCE = "technical_compliance"
    FINANCIAL_SUBMISSION = "financial_submission"
    CONTRACT_EXECUTION = "contract_execution"
    POST_AWARD_OBLIGATION = "post_award_obligation"
    INFORMATIONAL = "informational"


class ScopeReviewStatus(str, Enum):
    """Whether bid-stage scope impact is clear enough to act on."""

    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"


# ---------------------------------------------------------------------------
# Pydantic Model: TenderRequirement
# ---------------------------------------------------------------------------

class TenderRequirement(BaseModel):
    """A single source-traceable requirement or verified evidence item."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    category: RequirementCategory = Field(
        ...,
        description="Strict category. Must be one of: DQ, NICE_TO_HAVE, COMPLIANT.",
    )
    headline: str = Field(
        ...,
        min_length=1,
        description="Punchy requirement summary, maximum 5 words.",
    )
    source_filename: str = Field(
        ...,
        min_length=1,
        description="Exact filename from the nearest [[FILE: ...]] marker.",
    )
    source_page: int = Field(
        ...,
        ge=1,
        strict=True,
        description="Exact 1-based page number from the nearest [[PAGE N]] marker.",
    )
    exact_quote: str = Field(
        ...,
        min_length=1,
        description="Verbatim source quote, maximum 15 words.",
    )
    validation_status: EvidenceValidationStatus = Field(
        default=EvidenceValidationStatus.NEEDS_REVIEW,
        description="Backend evidence validation status.",
    )
    validation_reason: str = Field(
        default="Evidence has not been validated yet.",
        description="Backend evidence validation explanation.",
    )
    source_verified: bool = Field(
        default=False,
        description="True only when the quote is verified against the cited source page.",
    )
    requirement_scope: RequirementScope = Field(
        default=RequirementScope.INFORMATIONAL,
        description="Backend bid-stage/contract-stage requirement scope.",
    )
    scope_review_status: ScopeReviewStatus = Field(
        default=ScopeReviewStatus.NEEDS_REVIEW,
        description="Whether scope and bid-eligibility impact are clear.",
    )
    affects_bid_eligibility: bool = Field(
        default=False,
        description="True only when this requirement can affect bid eligibility.",
    )
    eligibility_reason: str = Field(
        default="Bid-stage eligibility impact has not been classified yet.",
        description="Backend explanation for bid-stage eligibility impact.",
    )
    source_chunk_index: int | None = Field(
        default=None,
        description="Internal zero-based extraction chunk index.",
    )
    source_chunk_start_char: int | None = Field(
        default=None,
        description="Internal approximate chunk start offset in traceable text.",
    )
    source_chunk_end_char: int | None = Field(
        default=None,
        description="Internal approximate chunk end offset in traceable text.",
    )
    extraction_batch_id: str | None = Field(
        default=None,
        description="Internal extraction batch identifier.",
    )

    @field_validator("headline")
    @classmethod
    def enforce_headline_word_limit(cls, value: str) -> str:
        words = value.split()
        if len(words) > MAX_HEADLINE_WORDS:
            return " ".join(words[:MAX_HEADLINE_WORDS]) + "..."
        return value

    @field_validator("exact_quote")
    @classmethod
    def enforce_exact_quote_word_limit(cls, value: str) -> str:
        """Reject long quotes so evidence remains audit-friendly and source-bound."""
        word_count = len(value.split())
        if word_count > MAX_EXACT_QUOTE_WORDS:
            raise ValueError(
                f"exact_quote must be {MAX_EXACT_QUOTE_WORDS} words or fewer; "
                f"got {word_count} words."
            )
        return value

    @property
    def raw_text_snippet(self) -> str:
        """Backward-compatible alias for legacy compliance/UI code."""
        return self.exact_quote

    @property
    def requirement_type(self) -> RequirementCategory:
        """Backward-compatible alias for legacy compliance/UI code."""
        return self.category

    @property
    def is_dealbreaker(self) -> bool:
        """A fatal item must be source-verified and bid-stage affecting."""
        return (
            self.category == RequirementCategory.DQ
            and self.validation_status == EvidenceValidationStatus.ACCEPTED
            and self.source_verified
            and self.affects_bid_eligibility
        )

    @property
    def confidence_score(self) -> float:
        """Legacy compatibility; Pro extraction is schema-bound, not confidence-bound."""
        return 1.0

    @property
    def parent_section_header(self) -> None:
        """Legacy compatibility; source file/page/quote replaces section headers."""
        return None


class RequirementExtractionCoverage(BaseModel):
    """Coverage metadata for full-text requirement extraction."""

    full_text_length: int
    max_chunk_chars: int
    chunk_count: int
    chunks_processed: int
    chunks_failed: int
    coverage_status: str
    coverage_warnings: list[str] = Field(default_factory=list)
    extractor_mode: str
    technical_warnings: list[str] = Field(default_factory=list)


class ExtractionChunkArtifactMetadata(BaseModel):
    """Lightweight extraction chunk metadata without raw chunk text."""

    chunk_index: int
    chunk_start_char: int
    chunk_end_char: int
    chunk_input_sha256: str
    extraction_status: str
    requirements_count: int = 0
    failure_reason: str | None = None


class RequirementExtractionResult(BaseModel):
    """Requirements plus coverage metadata from chunked extraction."""

    requirements: list[TenderRequirement] = Field(default_factory=list)
    coverage_metadata: RequirementExtractionCoverage
    extraction_artifacts_metadata: list[ExtractionChunkArtifactMetadata] = Field(
        default_factory=list
    )


@dataclass(frozen=True)
class _PageBlock:
    source_filename: str
    source_page: int
    body: str

    @property
    def header(self) -> str:
        return f"[[FILE: {self.source_filename}]]\n[[PAGE {self.source_page}]]"

    @property
    def text(self) -> str:
        body = self.body.strip()
        return f"{self.header}\n{body}" if body else self.header


@dataclass(frozen=True)
class _ExtractionChunk:
    text: str
    index: int
    start_char: int
    end_char: int


# ---------------------------------------------------------------------------
# Type Adapter & Gemini Response Schema
# ---------------------------------------------------------------------------

REQUIREMENT_LIST_ADAPTER = TypeAdapter(list[TenderRequirement])

REQUIREMENT_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "category": {
                "type": "STRING",
                "enum": ["DQ", "NICE_TO_HAVE", "COMPLIANT"],
                "description": "Strict risk category.",
            },
            "headline": {
                "type": "STRING",
                "description": "Punchy requirement summary, maximum 5 words.",
            },
            "source_filename": {
                "type": "STRING",
                "description": "Exact filename from the nearest [[FILE: ...]] marker.",
            },
            "source_page": {
                "type": "INTEGER",
                "description": "Exact page number from the nearest [[PAGE N]] marker.",
            },
            "exact_quote": {
                "type": "STRING",
                "description": "Verbatim source quote, maximum 15 words.",
            },
        },
        "required": [
            "category",
            "headline",
            "source_filename",
            "source_page",
            "exact_quote",
        ],
    },
}


# ---------------------------------------------------------------------------
# Prompt Engineering
# ---------------------------------------------------------------------------

SYSTEM_PROMPT: str = """\
You are a forensic legal auditor for B2G procurement. You are mathematically precise.

Your task is to extract source-traceable procurement requirements and verified
evidence from UzEx tender text. The input text includes source markers:

[[FILE: filename.ext]]
[[PAGE N]]

Every JSON object MUST cite the exact source_filename and source_page from the
nearest preceding markers. If a claim cannot be tied to both markers, do not
extract it. Some legacy payloads are wrapped with synthetic source markers;
when present, use those synthetic markers exactly and proceed with extraction.

Output strict JSON only: an array of objects with exactly these fields:
- category
- headline
- source_filename
- source_page
- exact_quote

Schema constraints:
- category MUST be exactly one of: DQ, NICE_TO_HAVE, COMPLIANT.
- headline MUST be a punchy UI summary of 5 words or fewer.
- source_filename MUST exactly match the filename inside [[FILE: ...]].
- source_page MUST be the integer N inside [[PAGE N]].
- exact_quote MUST be copied verbatim from the source and MUST contain no more
  than 15 words.
- Do not output markdown, commentary, confidence scores, booleans, or extra keys.

Anti-Template Rule:
DO NOT extract blank form fields, signature lines (e.g., 'Ф.И.О. ________'), or generic submission templates as requirements. You must only extract actionable legal, technical, or financial prerequisites.
Do not confuse a contract draft with a blank template: ignore only the blank
placeholder fields, but still extract real delivery, acceptance, warranty,
financial, legal, and technical obligations from the surrounding text.

    Evidence-first extraction:
    Extract only source-supported requirements or verified evidence. Do not force
    any number or distribution of DQ, NICE_TO_HAVE, or COMPLIANT items. If the
    source is ambiguous, unclear, or not tied to a concrete quote, do not invent
    a requirement. Leave uncertain claims out rather than guessing.

Risk category rules:
- The `DQ` (Disqualification) category is reserved EXCLUSIVELY for missing mandatory legal licenses, financial guarantees, or hard technical certifications.
- Minor formatting requests, preferred past-performance thresholds, or non-fatal criteria MUST be categorized as `NICE_TO_HAVE`.
- COMPLIANT means verified non-risk evidence that should remain visible in the
  audit trail. COMPLIANT items MUST NOT be fatal and MUST NOT trigger manual
  review blockers.

Extraction filters:
- Extract bidder-side actionable requirements or evidence only.
- Do not extract buyer identity, budget, lot metadata, delivery location,
  payment schedule, procurement timeline, evaluation formulas, blank templates,
  generic form labels, signature blocks, or legal preambles unless the clause
  creates a concrete bidder obligation.
- For lists under one shared preamble, aggregate into one headline when the
  items share the same category and source page.

Multilingual handling:
- Tender text may be Uzbek Latin, Uzbek Cyrillic, Russian, English, or mixed.
- Preserve source_filename exactly; do not translate exact_quote.
- headline may be concise English, but exact_quote must remain verbatim.

Final instruction:
Return a JSON array only. For non-empty tender text, extract the strongest
supported items you can find. Return [] only when the text truly contains no
actionable procurement, contract, technical, legal, or financial clauses.
"""


def _has_trace_markers(text_payload: str) -> bool:
    """Return True when parser traceability markers are already present."""
    return bool(_FILE_MARKER_RE.search(text_payload) and _PAGE_MARKER_RE.search(text_payload))


def _infer_source_filename(text_payload: str) -> str:
    """Infer a stable fallback filename from legacy bracket headers."""
    matches = [match.strip() for match in _BRACKETED_FILENAME_RE.findall(text_payload)]
    if not matches:
        return SYNTHETIC_SOURCE_FILENAME

    for filename in matches:
        if not filename.lower().endswith((".rar", ".zip", ".7z")):
            return filename
    return matches[0]


def _ensure_trace_markers(text_payload: str) -> str:
    """
    Preserve parser traceability markers when present; otherwise wrap legacy
    compiled text in synthetic markers so the prompt cannot zero out extraction.
    """
    normalized = text_payload.strip()
    if not normalized or _has_trace_markers(normalized):
        return normalized

    source_filename = _infer_source_filename(normalized)
    logger.warning(
        "Requirement extractor received markerless tender text; injecting "
        "synthetic source markers source_filename=%s source_page=1.",
        source_filename,
    )
    return f"[[FILE: {source_filename}]]\n[[PAGE 1]]\n{normalized}"


def _build_extraction_prompt(text_payload: str) -> str:
    """Build the user-turn prompt with the tender text payload."""
    traceable_payload = _ensure_trace_markers(text_payload)
    if len(traceable_payload) > MAX_PAYLOAD_CHARS:
        logger.warning(
            "Tender extraction chunk exceeds target size (%d > %d characters).",
            len(traceable_payload),
            MAX_PAYLOAD_CHARS,
        )
    return f"Tender document text:\n\n{traceable_payload}"


def build_extraction_warnings(
    text_payload: str,
    coverage_metadata: (
        RequirementExtractionCoverage | dict[str, object] | None
    ) = None,
) -> list[str]:
    """Return non-fatal extraction warnings to persist with analysis output."""
    if isinstance(coverage_metadata, RequirementExtractionCoverage):
        return list(coverage_metadata.coverage_warnings)
    if isinstance(coverage_metadata, dict):
        warnings = coverage_metadata.get("coverage_warnings")
        return [str(warning) for warning in warnings or []]
    return []


# ---------------------------------------------------------------------------
# Full-Coverage Chunking
# ---------------------------------------------------------------------------

def _parse_traceable_page_blocks(traceable_payload: str) -> list[_PageBlock]:
    """Parse traceable text into file/page blocks while preserving context."""
    blocks: list[_PageBlock] = []
    current_file: str | None = None
    current_page: int | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        if current_file and current_page is not None:
            blocks.append(
                _PageBlock(
                    source_filename=current_file,
                    source_page=current_page,
                    body="\n".join(current_lines).strip(),
                )
            )
        current_lines = []

    for line in traceable_payload.splitlines():
        file_match = _FILE_MARKER_RE.search(line)
        if file_match:
            flush()
            current_file = file_match.group(1).strip()
            current_page = None
            continue

        page_match = _PAGE_MARKER_RE.search(line)
        if page_match:
            flush()
            current_page = int(page_match.group(1))
            continue

        if current_file and current_page is not None:
            current_lines.append(line)

    flush()
    return blocks


def _split_text_with_overlap(
    text: str,
    *,
    max_chars: int,
    overlap_chars: int,
) -> list[str]:
    """Split oversized page text with bounded overlap and line-aware cut points."""
    normalized = text.strip()
    if not normalized:
        return [""]
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    start = 0
    safe_overlap = max(0, min(overlap_chars, max_chars // 3))
    while start < len(normalized):
        hard_end = min(start + max_chars, len(normalized))
        end = hard_end
        if hard_end < len(normalized):
            window = normalized[start:hard_end]
            newline_at = window.rfind("\n")
            sentence_at = max(
                window.rfind(". "),
                window.rfind("; "),
                window.rfind(", "),
            )
            split_at = max(newline_at, sentence_at)
            if split_at > max_chars // 2:
                end = start + split_at + 1

        segment = normalized[start:end].strip()
        if segment:
            chunks.append(segment)

        if end >= len(normalized):
            break
        next_start = max(end - safe_overlap, start + 1)
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks


def _split_oversized_page_block(block: _PageBlock, max_chars: int) -> list[str]:
    header = block.header
    body_budget = max_chars - len(header) - 1
    if body_budget <= 0:
        raise RuntimeError(
            "Source marker header exceeds maximum extraction chunk size."
        )

    return [
        f"{header}\n{segment}".strip()
        for segment in _split_text_with_overlap(
            block.body,
            max_chars=body_budget,
            overlap_chars=CHUNK_OVERLAP_CHARS,
        )
    ]


def _split_traceable_payload_chunks(
    text_payload: str,
    *,
    max_chars: int = MAX_PAYLOAD_CHARS,
) -> list[str]:
    """
    Split tender text into extraction chunks under max_chars.

    Chunks prefer parser file/page boundaries. Oversized pages are split with
    overlap and keep their original source markers in every segment.
    """
    traceable_payload = _ensure_trace_markers(text_payload)
    if not traceable_payload:
        return []
    if len(traceable_payload) <= max_chars:
        return [traceable_payload]

    page_blocks = _parse_traceable_page_blocks(traceable_payload)
    if not page_blocks:
        return _split_text_with_overlap(
            traceable_payload,
            max_chars=max_chars,
            overlap_chars=CHUNK_OVERLAP_CHARS,
        )

    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    def flush_current() -> None:
        nonlocal current_parts, current_len
        if current_parts:
            chunks.append("\n\n".join(current_parts).strip())
            current_parts = []
            current_len = 0

    for block in page_blocks:
        block_text = block.text
        block_len = len(block_text)
        if block_len > max_chars:
            flush_current()
            chunks.extend(_split_oversized_page_block(block, max_chars))
            continue

        separator_len = 2 if current_parts else 0
        if current_parts and current_len + separator_len + block_len > max_chars:
            flush_current()

        current_parts.append(block_text)
        current_len += (2 if current_len else 0) + block_len

    flush_current()
    return chunks


def _locate_chunk_span(
    traceable_payload: str,
    chunk_text: str,
    *,
    search_start: int,
) -> tuple[int, int]:
    """Best-effort chunk offset lookup for internal provenance."""
    start = traceable_payload.find(chunk_text, max(0, search_start - CHUNK_OVERLAP_CHARS))
    if start < 0:
        marker_lines = [
            line
            for line in chunk_text.splitlines()[:3]
            if _FILE_MARKER_RE.search(line) or _PAGE_MARKER_RE.search(line)
        ]
        marker_sample = "\n".join(marker_lines)
        if marker_sample:
            start = traceable_payload.find(
                marker_sample,
                max(0, search_start - CHUNK_OVERLAP_CHARS),
            )
    if start < 0:
        non_empty_lines = [line for line in chunk_text.splitlines() if line.strip()]
        for sample in non_empty_lines[:3]:
            start = traceable_payload.find(
                sample[:200],
                max(0, search_start - CHUNK_OVERLAP_CHARS),
            )
            if start >= 0:
                break
    if start < 0:
        start = min(search_start, len(traceable_payload))
    end = min(len(traceable_payload), start + len(chunk_text))
    return start, end


def _split_traceable_payload_chunk_metadata(
    text_payload: str,
    *,
    max_chars: int = MAX_PAYLOAD_CHARS,
) -> list[_ExtractionChunk]:
    traceable_payload = _ensure_trace_markers(text_payload)
    chunks = _split_traceable_payload_chunks(
        traceable_payload,
        max_chars=max_chars,
    )
    metadata: list[_ExtractionChunk] = []
    search_start = 0
    for index, chunk_text in enumerate(chunks):
        start, end = _locate_chunk_span(
            traceable_payload,
            chunk_text,
            search_start=search_start,
        )
        metadata.append(
            _ExtractionChunk(
                text=chunk_text,
                index=index,
                start_char=start,
                end_char=end,
            )
        )
        search_start = max(end, search_start)
    return metadata


def _with_chunk_metadata(
    req: TenderRequirement,
    *,
    chunk: _ExtractionChunk,
    extraction_batch_id: str,
) -> TenderRequirement:
    return req.model_copy(
        update={
            "source_chunk_index": chunk.index,
            "source_chunk_start_char": chunk.start_char,
            "source_chunk_end_char": chunk.end_char,
            "extraction_batch_id": extraction_batch_id,
        }
    )


def _requirement_dedupe_key(req: TenderRequirement) -> tuple[str, int, str]:
    return (
        _normalize_evidence_text(req.source_filename),
        req.source_page,
        _normalize_evidence_text(req.exact_quote),
    )


def _requirement_strength(req: TenderRequirement) -> tuple[int, int]:
    category_strength = {
        RequirementCategory.DQ: 3,
        RequirementCategory.NICE_TO_HAVE: 2,
        RequirementCategory.COMPLIANT: 1,
    }
    return (category_strength.get(req.category, 0), len(req.headline))


def _deduplicate_requirements(
    requirements: list[TenderRequirement],
) -> list[TenderRequirement]:
    """Deduplicate repeated source/quote evidence, preserving safer categories."""
    deduped: dict[tuple[str, int, str], TenderRequirement] = {}
    order: list[tuple[str, int, str]] = []

    for req in requirements:
        key = _requirement_dedupe_key(req)
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = req
            order.append(key)
            continue
        if _requirement_strength(req) > _requirement_strength(existing):
            deduped[key] = req

    return [deduped[key] for key in order]


# ---------------------------------------------------------------------------
# Evidence Validation
# ---------------------------------------------------------------------------

def _normalize_evidence_text(value: str) -> str:
    """Conservative matching normalization: casefold and collapse whitespace."""
    normalized = value.replace("\u00a0", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.casefold().strip()


def _quote_is_safe_for_normalized_match(quote: str) -> bool:
    normalized = _normalize_evidence_text(quote)
    compact_len = len(normalized.replace(" ", ""))
    return compact_len >= 8 or len(normalized.split()) >= 2


def _build_source_page_index(text_payload: str) -> dict[tuple[str, int], str]:
    """
    Build a filename/page -> text map from parser trace markers.

    Markerless legacy text is indexed under a synthetic page-1 source so it can
    be preserved as review-only evidence instead of being silently discarded.
    """
    index: dict[tuple[str, int], list[str]] = {}
    current_file: str | None = None
    current_page: int | None = None

    for line in text_payload.splitlines():
        if _BRACKETED_FILENAME_RE.match(line):
            current_file = None
            current_page = None
            continue

        file_match = _FILE_MARKER_RE.search(line)
        if file_match:
            current_file = file_match.group(1).strip()
            current_page = None
            continue

        page_match = _PAGE_MARKER_RE.search(line)
        if page_match:
            current_page = int(page_match.group(1))
            if current_file:
                index.setdefault((current_file, current_page), [])
            continue

        if current_file and current_page is not None:
            index.setdefault((current_file, current_page), []).append(line)

    if index:
        return {
            key: "\n".join(lines).strip()
            for key, lines in index.items()
            if "\n".join(lines).strip()
        }

    normalized = text_payload.strip()
    if not normalized:
        return {}

    fallback_filename = _infer_source_filename(normalized)
    return {(fallback_filename, 1): normalized}


def _find_casefold_source_key(
    source_index: dict[tuple[str, int], str],
    filename: str,
    page: int,
) -> tuple[str, int] | None:
    wanted = (filename.casefold(), page)
    for source_filename, source_page in source_index:
        if (source_filename.casefold(), source_page) == wanted:
            return (source_filename, source_page)
    return None


def _quote_matches_block(quote: str, block_text: str) -> tuple[bool, str]:
    if quote in block_text:
        return True, "Exact quote found in cited source page."

    if not _quote_is_safe_for_normalized_match(quote):
        return False, "Quote not exact and too short for conservative normalized matching."

    normalized_quote = _normalize_evidence_text(quote)
    normalized_block = _normalize_evidence_text(block_text)
    if normalized_quote and normalized_quote in normalized_block:
        return True, "Quote found after conservative case/whitespace normalization."

    return False, "Quote was not found in cited source page."


def _find_quote_elsewhere(
    req: TenderRequirement,
    source_index: dict[tuple[str, int], str],
) -> tuple[str, int] | None:
    for (source_filename, source_page), block_text in source_index.items():
        matches, _ = _quote_matches_block(req.exact_quote, block_text)
        if matches:
            return (source_filename, source_page)
    return None


def _with_validation(
    req: TenderRequirement,
    *,
    status: EvidenceValidationStatus,
    reason: str,
    source_verified: bool,
) -> TenderRequirement:
    return req.model_copy(
        update={
            "validation_status": status,
            "validation_reason": reason,
            "source_verified": source_verified,
        }
    )


def validate_requirement_evidence(
    req: TenderRequirement,
    text_payload: str,
) -> TenderRequirement:
    """Validate one requirement's quote against the cited source marker block."""
    source_index = _build_source_page_index(text_payload)
    if not source_index:
        return _with_validation(
            req,
            status=EvidenceValidationStatus.REJECTED,
            reason="No parsed source text was available for evidence validation.",
            source_verified=False,
        )

    has_real_markers = _has_trace_markers(text_payload)
    exact_key = (req.source_filename, req.source_page)
    block_text = source_index.get(exact_key)

    if block_text is not None:
        matches, reason = _quote_matches_block(req.exact_quote, block_text)
        if matches and has_real_markers:
            return _with_validation(
                req,
                status=EvidenceValidationStatus.ACCEPTED,
                reason=reason,
                source_verified=True,
            )
        if matches:
            return _with_validation(
                req,
                status=EvidenceValidationStatus.NEEDS_REVIEW,
                reason=(
                    f"{reason} Source text has no parser trace markers, so "
                    "file/page provenance is synthetic."
                ),
                source_verified=False,
            )

        elsewhere = _find_quote_elsewhere(req, source_index)
        if elsewhere is not None:
            found_filename, found_page = elsewhere
            return _with_validation(
                req,
                status=EvidenceValidationStatus.NEEDS_REVIEW,
                reason=(
                    "Quote was not found on the cited source page, but it was "
                    f"found in {found_filename} page {found_page}."
                ),
                source_verified=False,
            )

        return _with_validation(
            req,
            status=EvidenceValidationStatus.REJECTED,
            reason=reason,
            source_verified=False,
        )

    casefold_key = _find_casefold_source_key(
        source_index,
        req.source_filename,
        req.source_page,
    )
    if casefold_key is not None:
        matches, reason = _quote_matches_block(req.exact_quote, source_index[casefold_key])
        if matches:
            return _with_validation(
                req,
                status=EvidenceValidationStatus.NEEDS_REVIEW,
                reason=(
                    f"{reason} Source filename matched only by case-insensitive "
                    f"comparison ({casefold_key[0]} page {casefold_key[1]})."
                ),
                source_verified=False,
            )

    elsewhere = _find_quote_elsewhere(req, source_index)
    if elsewhere is not None:
        found_filename, found_page = elsewhere
        return _with_validation(
            req,
            status=EvidenceValidationStatus.NEEDS_REVIEW,
            reason=(
                "Cited source block was not found, but the quote was found in "
                f"{found_filename} page {found_page}."
            ),
            source_verified=False,
        )

    return _with_validation(
        req,
        status=EvidenceValidationStatus.REJECTED,
        reason=(
            f"Cited source block was not found: "
            f"{req.source_filename} page {req.source_page}."
        ),
        source_verified=False,
    )


def validate_requirements_evidence(
    requirements: list[TenderRequirement],
    text_payload: str,
) -> list[TenderRequirement]:
    """Validate all extracted requirements against parser source markers."""
    return [
        validate_requirement_evidence(req, text_payload)
        for req in requirements
    ]


# ---------------------------------------------------------------------------
# Requirement Scope Classification
# ---------------------------------------------------------------------------

_EXPLICIT_BID_SUBMISSION_TERMS: tuple[str, ...] = (
    "submitted with the bid",
    "submitted with bid",
    "submitted with its bid",
    "submitted with the proposal",
    "submitted with its proposal",
    "submit with the bid",
    "submit with its bid",
    "submit with the proposal",
    "submit as part of the bid",
    "submit as part of its bid",
    "included in the bid",
    "included in its bid",
    "included in the proposal",
    "attached to the bid",
    "attached with the bid",
    "attached to the proposal",
    "part of the bid",
    "as part of the bid",
    "as part of its bid",
    "part of the proposal",
    "as part of the proposal",
    "bid must include",
    "proposal must include",
    "bid shall include",
    "proposal shall include",
    "bidder shall submit",
    "bidder must submit",
    "tenderer shall submit",
    "tenderer must submit",
    "required with the bid",
    "required for bid submission",
    "required for tender submission",
    "required for proposal submission",
    "documents to be submitted with the bid",
    "documents required for submission",
    "required submission document",
    "non-responsive bid",
)

_REJECTION_TERMS: tuple[str, ...] = (
    "reject",
    "rejected",
    "rejection",
    "disqualif",
    "not eligible",
    "will not be considered",
    "shall not be considered",
    "grounds for rejection",
    "grounds for disqualification",
    "отклон",
    "дисквалифик",
    "не допуска",
    "rad et",
)

_EVALUATION_TERMS: tuple[str, ...] = (
    "evaluation",
    "evaluated",
    "scored",
    "qualification criteria",
    "selection criteria",
    "technical specification compliance",
    "technical compliance",
    "оценк",
    "критери",
    "квалификацион",
)

_ELIGIBILITY_TERMS: tuple[str, ...] = (
    "license",
    "licence",
    "certificate",
    "certification",
    "permit",
    "authorization",
    "authorisation",
    "qualified",
    "qualification",
    "eligible",
    "experience",
    "similar work",
    "лиценз",
    "сертификат",
    "разрешени",
    "опыт",
    "tajriba",
    "sertifikat",
    "litsenziya",
)

_HARD_ELIGIBILITY_TERMS: tuple[str, ...] = (
    "license",
    "licence",
    "certificate",
    "certification",
    "permit",
    "authorization",
    "authorisation",
    "qualified",
    "qualification",
    "eligible",
    "лиценз",
    "сертификат",
    "разрешени",
    "квалификацион",
    "sertifikat",
    "litsenziya",
)

_TECHNICAL_TERMS: tuple[str, ...] = (
    "technical",
    "specification",
    "standard",
    "compliance",
    "iso",
    "equipment",
    "methodology",
    "техническ",
    "спецификац",
    "стандарт",
)

_FINANCIAL_TERMS: tuple[str, ...] = (
    "bid security",
    "tender security",
    "bid guarantee",
    "tender guarantee",
    "bank guarantee",
    "financial proposal",
    "price proposal",
    "обеспечение заявки",
    "банковск",
    "гарант",
)

_PERFORMANCE_SECURITY_TERMS: tuple[str, ...] = (
    "performance security",
    "performance guarantee",
    "performance bond",
    "contract performance security",
    "security for performance",
    "обеспечение исполнения",
    "обеспечения исполнения",
    "гарантия исполнения",
    "исполнение договора",
)

_PERFORMANCE_SECURITY_BID_TERMS: tuple[str, ...] = (
    "with the bid",
    "with its bid",
    "with their bid",
    "with a bid",
    "with the proposal",
    "with its proposal",
    "in the bid",
    "in its bid",
    "as part of the bid",
    "as part of its bid",
    "as part of the proposal",
    "bid must include",
    "proposal must include",
    "submitted with the bid",
    "submitted with bid",
    "submitted with the proposal",
    "submit performance security with",
)

_POST_AWARD_TERMS: tuple[str, ...] = (
    "after award",
    "upon award",
    "post-award",
    "post award",
    "successful bidder",
    "winning bidder",
    "contract signing",
    "signing of the contract",
    "after signing",
    "before signing the contract",
    "before contract signing",
    "contract execution",
    "contract performance",
    "during performance",
    "during contract",
    "after delivery",
    "acceptance",
    "commissioning",
    "warranty",
    "исполнени",
    "заключени",
    "подписани",
    "победител",
    "после",
    "шартнома",
)

_OPERATIONAL_TECHNICAL_TERMS: tuple[str, ...] = (
    "contractor shall",
    "contractor's documents",
    "contractor documents",
    "subcontract",
    "subcontractor",
    "subcontractors have been approved",
    "approved subcontractor",
    "approved subcontractors",
    "approved in writing by the employer",
    "approved by the employer",
    "employer approval",
    "approval by the employer",
    "whole of the works",
    "works",
    "site",
    "accident prevention",
    "accident prevention officer",
    "safety officer",
    "monthly report",
    "monthly reports",
    "as-built",
    "as built",
    "as-built records",
    "as built records",
    "record drawings",
    "execution deliverable",
    "execution deliverables",
    "o&m",
    "operation and maintenance",
    "maintenance manual",
    "manuals",
    "site safety",
    "safety procedures",
    "quality assurance system",
    "quality assurance",
    "time programme",
    "commencement date",
    "program",
    "programme",
    "environmental obligation",
    "environmental obligations",
    "environmental management during",
    "progress report",
    "completion report",
    "акт выполненных работ",
    "исполнительная документация",
)

_INFORMATIONAL_TERMS: tuple[str, ...] = (
    "buyer",
    "customer",
    "procuring entity",
    "budget",
    "estimated price",
    "delivery location",
    "payment schedule",
    "evaluation formula",
    "заказчик",
    "бюджет",
    "место поставки",
)

_WORD_BOUNDARY_SCOPE_TERMS: frozenset[str] = frozenset({"bid", "bids", "iso"})


def _normalize_scope_text(value: str) -> str:
    normalized = value.replace("\u00a0", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.casefold().strip()


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    for needle in needles:
        if needle in _WORD_BOUNDARY_SCOPE_TERMS:
            if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", value):
                return True
            continue
        if needle in value:
            return True
    return False


def _source_block_for_requirement(
    req: TenderRequirement,
    text_payload: str,
) -> str:
    source_index = _build_source_page_index(text_payload)
    exact_key = (req.source_filename, req.source_page)
    block = source_index.get(exact_key)
    if block is not None:
        return block

    casefold_key = _find_casefold_source_key(
        source_index,
        req.source_filename,
        req.source_page,
    )
    if casefold_key is not None:
        return source_index[casefold_key]

    return req.exact_quote


def _context_window(block_text: str, quote: str, radius: int = 700) -> str:
    exact_index = block_text.find(quote)
    if exact_index >= 0:
        start = max(0, exact_index - radius)
        end = min(len(block_text), exact_index + len(quote) + radius)
        return block_text[start:end]

    normalized_block = _normalize_scope_text(block_text)
    normalized_quote = _normalize_scope_text(quote)
    normalized_index = normalized_block.find(normalized_quote)
    if normalized_index >= 0:
        start = max(0, normalized_index - radius)
        end = min(len(normalized_block), normalized_index + len(normalized_quote) + radius)
        return normalized_block[start:end]

    return block_text[: max(radius * 2, 1)]


def _scope_payload(
    req: TenderRequirement,
    text_payload: str,
    *,
    radius: int = 700,
) -> str:
    block_text = _source_block_for_requirement(req, text_payload)
    return _normalize_scope_text(
        " ".join(
            part
            for part in (
                req.headline,
                req.exact_quote,
                _context_window(block_text, req.exact_quote, radius=radius),
            )
            if part
        )
    )


def _with_scope(
    req: TenderRequirement,
    *,
    scope: RequirementScope,
    review_status: ScopeReviewStatus,
    affects_bid_eligibility: bool,
    reason: str,
) -> TenderRequirement:
    return req.model_copy(
        update={
            "requirement_scope": scope,
            "scope_review_status": review_status,
            "affects_bid_eligibility": affects_bid_eligibility,
            "eligibility_reason": reason,
        }
    )


def _explicit_bid_stage_context(text: str) -> bool:
    return (
        _contains_any(text, _REJECTION_TERMS)
        or _contains_any(text, _EVALUATION_TERMS)
        or _contains_any(text, _EXPLICIT_BID_SUBMISSION_TERMS)
    )


def classify_requirement_scope(
    req: TenderRequirement,
    text_payload: str,
) -> TenderRequirement:
    """Classify whether a verified requirement can affect bid eligibility."""
    if not (
        req.validation_status == EvidenceValidationStatus.ACCEPTED
        and req.source_verified
    ):
        return _with_scope(
            req,
            scope=RequirementScope.INFORMATIONAL,
            review_status=ScopeReviewStatus.NEEDS_REVIEW,
            affects_bid_eligibility=False,
            reason=(
                "Source evidence is not accepted; bid-stage eligibility impact "
                "was not evaluated."
            ),
        )

    text = _scope_payload(req, text_payload)
    local_text = _scope_payload(req, text_payload, radius=300)
    has_rejection_context = _contains_any(local_text, _REJECTION_TERMS)
    has_evaluation_context = _contains_any(local_text, _EVALUATION_TERMS)
    has_eligibility_context = _contains_any(text, _ELIGIBILITY_TERMS)
    has_hard_eligibility_context = _contains_any(local_text, _HARD_ELIGIBILITY_TERMS)
    has_technical_context = _contains_any(text, _TECHNICAL_TERMS)
    has_financial_context = _contains_any(local_text, _FINANCIAL_TERMS)
    has_performance_security = _contains_any(local_text, _PERFORMANCE_SECURITY_TERMS)
    has_performance_security_bid_context = _contains_any(
        local_text,
        _PERFORMANCE_SECURITY_BID_TERMS,
    )
    has_post_award_context = _contains_any(local_text, _POST_AWARD_TERMS)
    has_operational_context = _contains_any(local_text, _OPERATIONAL_TECHNICAL_TERMS)
    has_informational_context = _contains_any(text, _INFORMATIONAL_TERMS)

    bid_stage_is_explicit = _explicit_bid_stage_context(local_text)

    if has_performance_security:
        if has_performance_security_bid_context or has_rejection_context:
            return _with_scope(
                req,
                scope=RequirementScope.FINANCIAL_SUBMISSION,
                review_status=ScopeReviewStatus.ACCEPTED,
                affects_bid_eligibility=True,
                reason=(
                    "Performance security is explicitly tied to bid/proposal "
                    "submission or rejection/disqualification language."
                ),
            )
        if has_post_award_context:
            return _with_scope(
                req,
                scope=RequirementScope.POST_AWARD_OBLIGATION,
                review_status=ScopeReviewStatus.ACCEPTED,
                affects_bid_eligibility=False,
                reason=(
                    "Performance security is tied to award, contract signing, "
                    "or contract performance rather than bid submission."
                ),
            )
        return _with_scope(
            req,
            scope=RequirementScope.POST_AWARD_OBLIGATION,
            review_status=ScopeReviewStatus.NEEDS_REVIEW,
            affects_bid_eligibility=False,
            reason=(
                "Source evidence is verified, but bid-stage eligibility impact "
                "is not explicit."
            ),
        )

    if has_operational_context and not bid_stage_is_explicit:
        return _with_scope(
            req,
            scope=RequirementScope.CONTRACT_EXECUTION,
            review_status=ScopeReviewStatus.ACCEPTED,
            affects_bid_eligibility=False,
            reason=(
                "Technical obligation appears to govern contract execution, "
                "not bid-stage eligibility."
            ),
        )

    if has_post_award_context and not bid_stage_is_explicit:
        return _with_scope(
            req,
            scope=RequirementScope.POST_AWARD_OBLIGATION,
            review_status=ScopeReviewStatus.ACCEPTED,
            affects_bid_eligibility=False,
            reason=(
                "Requirement is tied to award, contract signing, delivery, "
                "acceptance, warranty, or contract performance."
            ),
        )

    if has_financial_context and bid_stage_is_explicit:
        return _with_scope(
            req,
            scope=RequirementScope.FINANCIAL_SUBMISSION,
            review_status=ScopeReviewStatus.ACCEPTED,
            affects_bid_eligibility=True,
            reason=(
                "Financial requirement is explicitly tied to bid/proposal "
                "submission, evaluation, or rejection."
            ),
        )

    if bid_stage_is_explicit and not (has_technical_context or has_financial_context):
        return _with_scope(
            req,
            scope=RequirementScope.BID_SUBMISSION,
            review_status=ScopeReviewStatus.ACCEPTED,
            affects_bid_eligibility=True,
            reason=(
                "Requirement is explicitly tied to bid/proposal submission."
            ),
        )

    if has_hard_eligibility_context and (
        bid_stage_is_explicit
        or req.category == RequirementCategory.DQ
    ):
        return _with_scope(
            req,
            scope=RequirementScope.ELIGIBILITY,
            review_status=ScopeReviewStatus.ACCEPTED,
            affects_bid_eligibility=True,
            reason=(
                "Requirement concerns bidder qualification, license, "
                "certification, permit, or eligibility."
            ),
        )

    if has_eligibility_context and bid_stage_is_explicit:
        return _with_scope(
            req,
            scope=RequirementScope.ELIGIBILITY,
            review_status=ScopeReviewStatus.ACCEPTED,
            affects_bid_eligibility=True,
            reason=(
                "Requirement is explicitly tied to bidder qualification, "
                "evaluation, submission, or rejection."
            ),
        )

    if has_technical_context:
        if bid_stage_is_explicit:
            return _with_scope(
                req,
                scope=RequirementScope.TECHNICAL_COMPLIANCE,
                review_status=ScopeReviewStatus.ACCEPTED,
                affects_bid_eligibility=True,
                reason=(
                    "Technical requirement is explicitly tied to bid/proposal "
                    "evaluation, submission, qualification, or rejection."
                ),
            )
        return _with_scope(
            req,
            scope=RequirementScope.TECHNICAL_COMPLIANCE,
            review_status=ScopeReviewStatus.NEEDS_REVIEW,
            affects_bid_eligibility=False,
            reason=(
                "Source evidence is verified, but bid-stage eligibility impact "
                "is not explicit."
            ),
        )

    if has_informational_context and req.category != RequirementCategory.DQ:
        return _with_scope(
            req,
            scope=RequirementScope.INFORMATIONAL,
            review_status=ScopeReviewStatus.ACCEPTED,
            affects_bid_eligibility=False,
            reason="Requirement is informational and does not affect bid eligibility.",
        )

    if req.category == RequirementCategory.DQ:
        return _with_scope(
            req,
            scope=RequirementScope.ELIGIBILITY,
            review_status=ScopeReviewStatus.NEEDS_REVIEW,
            affects_bid_eligibility=False,
            reason=(
                "Source evidence is verified, but bid-stage eligibility impact "
                "is not explicit."
            ),
        )

    return _with_scope(
        req,
        scope=RequirementScope.INFORMATIONAL,
        review_status=ScopeReviewStatus.ACCEPTED,
        affects_bid_eligibility=False,
        reason="Requirement does not create a bid-stage eligibility blocker.",
    )


def classify_requirements_scope(
    requirements: list[TenderRequirement],
    text_payload: str,
) -> list[TenderRequirement]:
    """Classify all extracted requirements by bid-stage scope."""
    return [
        classify_requirement_scope(req, text_payload)
        for req in requirements
    ]


# ---------------------------------------------------------------------------
# Response Parsing
# ---------------------------------------------------------------------------

def _parse_extraction_response(response: object) -> list[TenderRequirement]:
    """Parse and validate Gemini structured output through Pydantic."""
    parsed_payload = getattr(response, "parsed", None)

    if parsed_payload is not None:
        try:
            items = REQUIREMENT_LIST_ADAPTER.validate_python(
                parsed_payload,
                strict=False,
            )
        except ValidationError as exc:
            logger.error("Requirement extraction schema validation failed: %s", exc)
            raise RuntimeError(
                "Requirement Extractor: structured response validation failed."
            ) from exc
    else:
        response_text = (getattr(response, "text", "") or "").strip()
        if not response_text:
            raise RuntimeError("Requirement Extractor returned empty response.")
        try:
            items = REQUIREMENT_LIST_ADAPTER.validate_json(
                response_text,
                strict=False,
            )
        except ValidationError as exc:
            logger.error("Requirement extraction JSON validation failed: %s", exc)
            raise RuntimeError(
                "Requirement Extractor: JSON response validation failed."
            ) from exc

    logger.info(
        "Extracted %d forensic requirement items (%d DQ, %d NICE_TO_HAVE, %d COMPLIANT).",
        len(items),
        sum(1 for r in items if r.category == RequirementCategory.DQ),
        sum(1 for r in items if r.category == RequirementCategory.NICE_TO_HAVE),
        sum(1 for r in items if r.category == RequirementCategory.COMPLIANT),
    )
    return items


# ---------------------------------------------------------------------------
# API Key Resolution
# ---------------------------------------------------------------------------

def _resolve_gemini_api_key() -> str | None:
    """Resolve Gemini API key from settings or environment."""
    from app.core.config import settings

    return (
        settings.GEMINI_API_KEY
        or settings.GOOGLE_API_KEY
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    )


# ---------------------------------------------------------------------------
# Retry Infrastructure
# ---------------------------------------------------------------------------

def _log_extraction_retry(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    sleep_seconds = retry_state.next_action.sleep if retry_state.next_action else 0.0
    logger.warning(
        "Requirement Extractor: Gemini Pro API error. Retrying attempt %s/4 in %.1fs: %s",
        retry_state.attempt_number + 1,
        sleep_seconds,
        exc,
    )


# ---------------------------------------------------------------------------
# Core Extraction
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(errors.APIError),
    before_sleep=_log_extraction_retry,
    reraise=True,
)
def _extract_requirements_sync(
    text_payload: str,
    api_key: str,
) -> list[TenderRequirement]:
    """Synchronous Gemini Pro call with native structured output enforcement."""
    if not text_payload.strip():
        return []

    client = genai.Client(api_key=api_key)
    user_prompt = _build_extraction_prompt(text_payload)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=REQUIREMENT_RESPONSE_SCHEMA,
            temperature=0.0,
        ),
    )

    return _parse_extraction_response(response)


def _coverage_metadata(
    *,
    full_text_length: int,
    max_chunk_chars: int,
    chunk_count: int,
    chunks_processed: int,
    chunks_failed: int,
    technical_warnings: list[str] | None = None,
) -> RequirementExtractionCoverage:
    if chunks_failed == 0:
        coverage_status = "complete"
        coverage_warnings: list[str] = []
    elif chunks_processed > 0:
        coverage_status = "partial"
        coverage_warnings = [
            "Some document sections require manual review due to processing failure."
        ]
    else:
        coverage_status = "failed"
        coverage_warnings = [
            "Document requirement extraction failed; manual review is required."
        ]

    return RequirementExtractionCoverage(
        full_text_length=full_text_length,
        max_chunk_chars=max_chunk_chars,
        chunk_count=chunk_count,
        chunks_processed=chunks_processed,
        chunks_failed=chunks_failed,
        coverage_status=coverage_status,
        coverage_warnings=coverage_warnings,
        extractor_mode="chunked" if chunk_count > 1 else "single_chunk",
        technical_warnings=technical_warnings or [],
    )


def build_failed_extraction_coverage(
    text_payload: str,
    *,
    error: str,
) -> RequirementExtractionCoverage:
    technical_warnings = [error]
    try:
        chunks = _split_traceable_payload_chunk_metadata(text_payload)
        full_text_length = len(_ensure_trace_markers(text_payload))
    except Exception as chunk_exc:
        chunks = []
        full_text_length = len(text_payload or "")
        technical_warnings.append(
            f"Coverage chunking failed: {type(chunk_exc).__name__}: {chunk_exc}"
        )
    chunk_count = len(chunks)
    return _coverage_metadata(
        full_text_length=full_text_length,
        max_chunk_chars=MAX_PAYLOAD_CHARS,
        chunk_count=chunk_count,
        chunks_processed=0,
        chunks_failed=chunk_count or 1,
        technical_warnings=technical_warnings,
    )


def _chunk_input_sha256(chunk_text: str) -> str:
    return hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()


def build_failed_extraction_artifacts_metadata(
    text_payload: str,
    *,
    error: str,
) -> list[ExtractionChunkArtifactMetadata]:
    """Return chunk failure metadata for setup-level extraction failures."""
    try:
        chunks = _split_traceable_payload_chunk_metadata(text_payload)
    except Exception as chunk_exc:
        return [
            ExtractionChunkArtifactMetadata(
                chunk_index=0,
                chunk_start_char=0,
                chunk_end_char=len(text_payload or ""),
                chunk_input_sha256=_chunk_input_sha256(text_payload or ""),
                extraction_status="failed",
                requirements_count=0,
                failure_reason=(
                    f"{error}; chunk metadata failed: "
                    f"{type(chunk_exc).__name__}: {chunk_exc}"
                ),
            )
        ]

    return [
        ExtractionChunkArtifactMetadata(
            chunk_index=chunk.index,
            chunk_start_char=chunk.start_char,
            chunk_end_char=chunk.end_char,
            chunk_input_sha256=_chunk_input_sha256(chunk.text),
            extraction_status="failed",
            requirements_count=0,
            failure_reason=error,
        )
        for chunk in chunks
    ]


def _extract_requirements_full_coverage_sync(
    text_payload: str,
    api_key: str,
) -> RequirementExtractionResult:
    """Extract requirements from all traceable chunks and report coverage."""
    traceable_payload = _ensure_trace_markers(text_payload)
    chunks = _split_traceable_payload_chunk_metadata(traceable_payload)
    if not chunks:
        return RequirementExtractionResult(
            requirements=[],
            coverage_metadata=_coverage_metadata(
                full_text_length=0,
                max_chunk_chars=MAX_PAYLOAD_CHARS,
                chunk_count=0,
                chunks_processed=0,
                chunks_failed=0,
            ),
        )

    all_requirements: list[TenderRequirement] = []
    chunks_processed = 0
    chunks_failed = 0
    technical_warnings: list[str] = []
    extraction_batch_id = str(uuid4())
    requirements_by_chunk_index: dict[int, list[TenderRequirement]] = {}
    artifacts_by_chunk_index: dict[int, ExtractionChunkArtifactMetadata] = {}

    def _record_chunk_success(
        chunk: _ExtractionChunk,
        chunk_requirements: list[TenderRequirement],
    ) -> None:
        nonlocal chunks_processed
        chunks_processed += 1
        requirements_by_chunk_index[chunk.index] = [
            _with_chunk_metadata(
                req,
                chunk=chunk,
                extraction_batch_id=extraction_batch_id,
            )
            for req in chunk_requirements
        ]
        artifacts_by_chunk_index[chunk.index] = ExtractionChunkArtifactMetadata(
            chunk_index=chunk.index,
            chunk_start_char=chunk.start_char,
            chunk_end_char=chunk.end_char,
            chunk_input_sha256=_chunk_input_sha256(chunk.text),
            extraction_status="succeeded",
            requirements_count=len(chunk_requirements),
            failure_reason=None,
        )

    def _record_chunk_failure(
        chunk: _ExtractionChunk,
        exc: Exception,
    ) -> None:
        nonlocal chunks_failed
        chunks_failed += 1
        failure_reason = f"{type(exc).__name__}: {exc}"
        technical_warnings.append(
            (
                f"Requirement extraction chunk {chunk.index + 1}/{len(chunks)} failed: "
                f"{failure_reason}"
            )
        )
        artifacts_by_chunk_index[chunk.index] = ExtractionChunkArtifactMetadata(
            chunk_index=chunk.index,
            chunk_start_char=chunk.start_char,
            chunk_end_char=chunk.end_char,
            chunk_input_sha256=_chunk_input_sha256(chunk.text),
            extraction_status="failed",
            requirements_count=0,
            failure_reason=failure_reason,
        )
        logger.exception(
            "Requirement extraction chunk %d/%d failed.",
            chunk.index + 1,
            len(chunks),
        )

    if len(chunks) == 1 or MAX_CHUNK_CONCURRENCY == 1:
        for chunk in chunks:
            try:
                _record_chunk_success(
                    chunk,
                    _extract_requirements_sync(chunk.text, api_key),
                )
            except Exception as exc:
                _record_chunk_failure(chunk, exc)
    else:
        max_workers = min(MAX_CHUNK_CONCURRENCY, len(chunks))
        logger.info(
            "Requirement extraction processing %d chunks with concurrency=%d.",
            len(chunks),
            max_workers,
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_chunk = {
                executor.submit(_extract_requirements_sync, chunk.text, api_key): chunk
                for chunk in chunks
            }
            for future in concurrent.futures.as_completed(future_to_chunk):
                chunk = future_to_chunk[future]
                try:
                    _record_chunk_success(chunk, future.result())
                except Exception as exc:
                    _record_chunk_failure(chunk, exc)

    for chunk in chunks:
        all_requirements.extend(requirements_by_chunk_index.get(chunk.index, []))

    coverage = _coverage_metadata(
        full_text_length=len(traceable_payload),
        max_chunk_chars=MAX_PAYLOAD_CHARS,
        chunk_count=len(chunks),
        chunks_processed=chunks_processed,
        chunks_failed=chunks_failed,
        technical_warnings=technical_warnings,
    )
    return RequirementExtractionResult(
        requirements=_deduplicate_requirements(all_requirements),
        coverage_metadata=coverage,
        extraction_artifacts_metadata=[
            artifacts_by_chunk_index[chunk.index]
            for chunk in chunks
            if chunk.index in artifacts_by_chunk_index
        ],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract_requirements(
    text_payload: str,
) -> list[TenderRequirement]:
    """
    Extract forensic requirement/evidence items from tender text.

    Raises:
        RuntimeError: If the API key is not configured, response is empty, or
                      schema validation fails after retries.
    """
    if not text_payload or not text_payload.strip():
        logger.warning("extract_requirements called with empty payload.")
        return []

    api_key = _resolve_gemini_api_key()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. Cannot perform requirement extraction."
        )

    result = await asyncio.to_thread(
        _extract_requirements_full_coverage_sync,
        text_payload,
        api_key,
    )
    return result.requirements


async def extract_requirements_with_coverage(
    text_payload: str,
) -> RequirementExtractionResult:
    """
    Extract requirements from the full tender text and return coverage metadata.

    Chunk failures are reported in ``coverage_metadata``. Total setup failures
    (for example a missing API key) still raise so callers can mark analysis
    failed cleanly.
    """
    if not text_payload or not text_payload.strip():
        logger.warning("extract_requirements_with_coverage called with empty payload.")
        return RequirementExtractionResult(
            requirements=[],
            coverage_metadata=_coverage_metadata(
                full_text_length=0,
                max_chunk_chars=MAX_PAYLOAD_CHARS,
                chunk_count=0,
                chunks_processed=0,
                chunks_failed=0,
            ),
        )

    api_key = _resolve_gemini_api_key()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. Cannot perform requirement extraction."
        )

    return await asyncio.to_thread(
        _extract_requirements_full_coverage_sync,
        text_payload,
        api_key,
    )
