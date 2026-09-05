"""
Plasma AI — Tender Strategy Intelligence Extractor Agent

Extracts strategic bidding intelligence from government tender documents.
This agent is the complement to the compliance extractor — it captures
everything the compliance engine is explicitly told to IGNORE:
  - Evaluation criteria and scoring methodology
  - Bidding mechanics and portal instructions
  - Contract and legal framework references
  - Pricing strategy hints (budgets, starting prices)
  - Timeline and milestone information
  - Submission format requirements

Architecture:
    - TenderStrategyIntelligence Pydantic model defines the 6-field schema.
    - extract_strategy_intelligence() drives structured LLM extraction
      through Google Gemini's native response_schema.
    - This agent runs CONCURRENTLY with the compliance extractor via
      asyncio.gather, with independent error isolation — a strategy
      failure must never block a compliance result.

Design Principle:
    Nothing extracted by this agent affects bid eligibility. This is
    purely informational intelligence for the "Bid Playbook" UI.
"""

from __future__ import annotations

import asyncio
import logging
import os

from google import genai
from google.genai import errors
from google.genai import types
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.analysis_languages import AnalysisLanguage, analysis_language_prompt_instruction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL_NAME: str = "gemini-2.5-flash"
MAX_PAYLOAD_CHARS: int = 60_000
PROMPT_TEMPLATE_VERSION: str = "strategy_extractor_s8_2_language_v1"


# ---------------------------------------------------------------------------
# Pydantic Model: TenderStrategyIntelligence
# ---------------------------------------------------------------------------

class TenderStrategyIntelligence(BaseModel):
    """Strategic bidding intelligence extracted from tender documents.

    This is NOT compliance data. Nothing here affects eligibility.
    This is the "Bid Playbook" — intelligence that helps the bidder
    craft a winning strategy.

    Fields:
        evaluation_criteria: How the bid will be scored/ranked by the
            procuring entity. Scoring formulas, weight distributions,
            evaluation methods (lowest price, best value, etc.).
        bidding_mechanics: Portal instructions, submission procedures,
            envelope formatting, digital vs. physical submission.
        contract_and_legal_framework: Governing law, contract type
            (fixed-price, cost-plus), dispute resolution clauses,
            regulatory references.
        pricing_strategy_hints: Starting prices, price caps, lot-level
            budgets, advance payment structures. Intelligence the
            bidder needs to calibrate their pricing model.
        timeline_and_milestones: Submission deadlines, evaluation
            schedule, contract signing dates, delivery milestones.
        submission_format: Envelope structure (technical vs financial),
            page limits, required file formats, language requirements.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    evaluation_criteria: list[str] = Field(
        default_factory=list,
        description=(
            "How the bid will be scored/ranked by the procuring entity. "
            "Include scoring formulas, weight distributions, and "
            "evaluation methods (lowest price, best value, etc.)."
        ),
    )
    bidding_mechanics: list[str] = Field(
        default_factory=list,
        description=(
            "Portal instructions, submission procedures, envelope "
            "formatting, and digital vs. physical submission rules."
        ),
    )
    contract_and_legal_framework: list[str] = Field(
        default_factory=list,
        description=(
            "Governing law, contract type (fixed-price, cost-plus), "
            "dispute resolution clauses, and regulatory references."
        ),
    )
    pricing_strategy_hints: list[str] = Field(
        default_factory=list,
        description=(
            "Starting prices, price caps, lot-level budgets, advance "
            "payment structures, and price evaluation formulas."
        ),
    )
    timeline_and_milestones: list[str] = Field(
        default_factory=list,
        description=(
            "Submission deadlines, evaluation schedule, contract "
            "signing dates, delivery milestones, and warranty periods."
        ),
    )
    submission_format: list[str] = Field(
        default_factory=list,
        description=(
            "Envelope structure (technical vs financial), page limits, "
            "required file formats, and language requirements for "
            "bid documents."
        ),
    )


# ---------------------------------------------------------------------------
# Type Adapter & Gemini Response Schema
# ---------------------------------------------------------------------------

STRATEGY_ADAPTER = TypeAdapter(TenderStrategyIntelligence)

STRATEGY_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "OBJECT",
    "properties": {
        "evaluation_criteria": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": (
                "How the bid will be scored/ranked. Scoring formulas, "
                "weight distributions, evaluation methods."
            ),
        },
        "bidding_mechanics": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": (
                "Portal instructions, submission procedures, envelope "
                "formatting."
            ),
        },
        "contract_and_legal_framework": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": (
                "Governing law, contract type, dispute resolution, "
                "regulatory references."
            ),
        },
        "pricing_strategy_hints": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": (
                "Starting prices, price caps, lot-level budgets, "
                "advance payment structures."
            ),
        },
        "timeline_and_milestones": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": (
                "Submission deadlines, evaluation schedule, contract "
                "signing dates, delivery milestones."
            ),
        },
        "submission_format": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": (
                "Envelope structure, page limits, file formats, "
                "language requirements."
            ),
        },
    },
    "required": [
        "evaluation_criteria",
        "bidding_mechanics",
        "contract_and_legal_framework",
        "pricing_strategy_hints",
        "timeline_and_milestones",
        "submission_format",
    ],
}


# ---------------------------------------------------------------------------
# Prompt Engineering
# ---------------------------------------------------------------------------

SYSTEM_PROMPT: str = """\
You are a senior government procurement strategist with 20 years of \
experience analyzing B2G tender documents across the Republic of \
Uzbekistan, the CIS region, and international public procurement.

Your sole task: extract STRATEGIC BIDDING INTELLIGENCE from the tender \
document below. You are building a "Bid Playbook" — the intelligence \
a bidder needs to craft a winning strategy.

═══════════════════════════════════════════════════════════════════
CRITICAL SCOPE BOUNDARY
═══════════════════════════════════════════════════════════════════

You are NOT looking for bidder obligations, eligibility requirements, \
certifications, licenses, or qualifications. Those are handled by a \
SEPARATE compliance engine. If a clause describes what the bidder \
must SUBMIT, POSSESS, or DEMONSTRATE to remain eligible, SKIP IT.

You are looking for everything AROUND the obligations — the rules \
of the game, the scoring system, the pricing landscape, the \
timeline, and the submission logistics.

═══════════════════════════════════════════════════════════════════
SECTION 1: EVALUATION CRITERIA & SCORING METHODOLOGY
═══════════════════════════════════════════════════════════════════

Extract clauses that describe HOW the procuring entity will SCORE, \
RANK, or EVALUATE bids. These include:

- Scoring formulas and weight distributions (e.g. "Price 60%, \
Technical 40%").
- Evaluation methods: Lowest Price, Best Value, Quality-Cost \
Based Selection (QCBS).
- Point allocation systems (e.g. "100-point technical scale").
- Price evaluation formulas (e.g. "Score = (Lowest Price / Your \
Price) × 100").
- Preference margins for domestic bidders.
- Disqualification thresholds on technical scoring (e.g. \
"Minimum 70 points to proceed to financial evaluation").

Capture the EXACT text or a faithful paraphrase. Include the \
original language (Uzbek, Russian, English) when possible.

═══════════════════════════════════════════════════════════════════
SECTION 2: BIDDING MECHANICS & PORTAL INSTRUCTIONS
═══════════════════════════════════════════════════════════════════

Extract clauses that describe HOW to participate in the tender \
process. These include:

- Portal submission instructions (which platform, how to upload).
- Envelope structure (single-envelope, two-envelope, multi-stage).
- Bid validity periods.
- Bid modification and withdrawal rules.
- Pre-bid conference details (dates, locations, virtual links).
- Clarification request procedures and deadlines.

═══════════════════════════════════════════════════════════════════
SECTION 3: CONTRACT & LEGAL FRAMEWORK
═══════════════════════════════════════════════════════════════════

Extract clauses that describe the legal and contractual context:

- Governing law and jurisdiction.
- Contract type (fixed-price, cost-plus, framework agreement).
- Dispute resolution mechanisms (arbitration, courts).
- Force majeure provisions.
- Intellectual property clauses.
- Subcontracting restrictions or requirements.
- Penalty clauses for late delivery or non-performance.

═══════════════════════════════════════════════════════════════════
SECTION 4: PRICING STRATEGY HINTS
═══════════════════════════════════════════════════════════════════

Extract financial intelligence that helps calibrate pricing:

- Starting prices / maximum lot values / budget ceilings.
- Price breakdown structure requirements.
- Currency requirements and exchange rate rules.
- Tax inclusion/exclusion rules (VAT, customs duties).
- Advance payment percentages and milestone payment structures.
- Price adjustment / escalation clauses.
- Lot indivisibility statements (must bid on entire lot).

═══════════════════════════════════════════════════════════════════
SECTION 5: TIMELINE & MILESTONES
═══════════════════════════════════════════════════════════════════

Extract all temporal information:

- Bid submission deadlines.
- Bid opening dates and times.
- Evaluation period duration.
- Contract award notification timeline.
- Contract signing deadline.
- Delivery / performance period.
- Warranty period requirements.

═══════════════════════════════════════════════════════════════════
SECTION 6: SUBMISSION FORMAT
═══════════════════════════════════════════════════════════════════

Extract formatting and structural requirements for the bid:

- Number and structure of envelopes (technical, financial).
- Required file formats (PDF, Excel, Word).
- Page limits or document organization requirements.
- Language requirements for bid documents.
- Number of copies (original + copies).
- Sealing and labeling instructions.

═══════════════════════════════════════════════════════════════════
MULTILINGUAL EXTRACTION
═══════════════════════════════════════════════════════════════════

Tender documents may be written in Uzbek (Latin or Cyrillic), \
Russian, English, or any combination. Extract intelligence \
regardless of language. Preserve the original text when quoting.

Output strict JSON only. No markdown, no commentary.\
"""


def _build_strategy_prompt(
    text_payload: str,
    analysis_language: AnalysisLanguage | str = AnalysisLanguage.ENGLISH,
) -> str:
    """Build the user-turn prompt with the tender text payload."""
    truncated = text_payload[:MAX_PAYLOAD_CHARS]
    if len(text_payload) > MAX_PAYLOAD_CHARS:
        logger.warning(
            "Strategy extractor: payload truncated from %d to %d characters.",
            len(text_payload),
            MAX_PAYLOAD_CHARS,
        )
    return (
        f"Analysis language contract:\n"
        f"{analysis_language_prompt_instruction(analysis_language)}\n"
        "Apply that language to generated summaries and faithful paraphrases. "
        "Keep direct source quotations verbatim.\n\n"
        f"Tender document text:\n\n{truncated}"
    )


# ---------------------------------------------------------------------------
# Response Parsing
# ---------------------------------------------------------------------------

def _parse_strategy_response(
    response: object,
) -> TenderStrategyIntelligence:
    """
    Parse and validate the Gemini structured response through the
    TenderStrategyIntelligence Pydantic model.
    """
    parsed_payload = getattr(response, "parsed", None)

    if parsed_payload is not None:
        try:
            result = STRATEGY_ADAPTER.validate_python(
                parsed_payload,
                strict=False,
            )
        except ValidationError as exc:
            logger.error(
                "Strategy extraction schema validation failed: %s", exc
            )
            raise RuntimeError(
                "Strategy Extractor: structured response validation failed."
            ) from exc
    else:
        response_text = (getattr(response, "text", "") or "").strip()
        if not response_text:
            raise RuntimeError(
                "Strategy Extractor returned empty response."
            )
        try:
            result = STRATEGY_ADAPTER.validate_json(
                response_text,
                strict=False,
            )
        except ValidationError as exc:
            logger.error(
                "Strategy extraction JSON validation failed: %s", exc
            )
            raise RuntimeError(
                "Strategy Extractor: JSON response validation failed."
            ) from exc

    total_items = (
        len(result.evaluation_criteria)
        + len(result.bidding_mechanics)
        + len(result.contract_and_legal_framework)
        + len(result.pricing_strategy_hints)
        + len(result.timeline_and_milestones)
        + len(result.submission_format)
    )
    logger.info(
        "Strategy extraction complete: %d total intelligence items "
        "(eval=%d, mechanics=%d, legal=%d, pricing=%d, timeline=%d, format=%d).",
        total_items,
        len(result.evaluation_criteria),
        len(result.bidding_mechanics),
        len(result.contract_and_legal_framework),
        len(result.pricing_strategy_hints),
        len(result.timeline_and_milestones),
        len(result.submission_format),
    )

    return result


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

def _log_strategy_retry(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    sleep_seconds = (
        retry_state.next_action.sleep if retry_state.next_action else 0.0
    )
    logger.warning(
        "Strategy Extractor: Gemini API error. "
        "Retrying attempt %s/4 in %.1fs: %s",
        retry_state.attempt_number + 1,
        sleep_seconds,
        exc,
    )


# ---------------------------------------------------------------------------
# Core Extraction (sync, with retry)
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(errors.APIError),
    before_sleep=_log_strategy_retry,
    reraise=True,
)
def _extract_strategy_sync(
    text_payload: str,
    api_key: str,
    analysis_language: AnalysisLanguage | str = AnalysisLanguage.ENGLISH,
) -> TenderStrategyIntelligence:
    """
    Synchronous Gemini call with native structured output enforcement.

    Uses a slightly higher temperature (0.2) than the compliance extractor
    (0.05) because strategy extraction benefits from mild creativity in
    identifying and paraphrasing scoring rules and pricing hints.
    """
    if not text_payload.strip():
        return TenderStrategyIntelligence()

    client = genai.Client(api_key=api_key)
    user_prompt = _build_strategy_prompt(text_payload, analysis_language)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=STRATEGY_RESPONSE_SCHEMA,
            temperature=0.2,
        ),
    )

    return _parse_strategy_response(response)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract_strategy_intelligence(
    text_payload: str,
    analysis_language: AnalysisLanguage | str = AnalysisLanguage.ENGLISH,
) -> TenderStrategyIntelligence:
    """
    Extract strategic bidding intelligence from a government tender document.

    This is the primary public entry point. It:
    1. Sends the tender text to Gemini with a strict response schema.
    2. Parses the structured response into a TenderStrategyIntelligence object.

    This agent is designed to run CONCURRENTLY with the compliance extractor
    via asyncio.gather. It has independent error handling — a failure here
    must never block the compliance result.

    Args:
        text_payload: The raw text content of the tender document.

    Returns:
        A validated TenderStrategyIntelligence object containing the
        strategic bidding intelligence.

    Raises:
        RuntimeError: If the API key is not configured, the response is
                      empty, or schema validation fails after retries.
    """
    if not text_payload or not text_payload.strip():
        logger.warning(
            "extract_strategy_intelligence called with empty payload."
        )
        return TenderStrategyIntelligence()

    api_key = _resolve_gemini_api_key()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. "
            "Cannot perform strategy extraction."
        )

    return await asyncio.to_thread(
        _extract_strategy_sync,
        text_payload,
        api_key,
        analysis_language,
    )
