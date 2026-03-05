"""
Plasma AI - AI Analysis Module

Uses Google Gemini to analyze tender documents and extract structured data.
Model fallback chain: tries multiple models on quota/rate-limit errors.
"""

import json
import logging
import os
import time
from typing import Any

import google.generativeai as genai
from google.genai import errors

logger = logging.getLogger(__name__)

# Lazy initialization flag
_gemini_configured = False


# ---------------------------------------------------------------------------
# Model fallback chain
# ---------------------------------------------------------------------------
# Order: primary → secondary → tertiary.  On 429 / RESOURCE_EXHAUSTED the
# caller advances to the next model automatically.
# ---------------------------------------------------------------------------
GEMINI_MODEL_CHAIN: list[str] = [
    os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview"),
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]

# Deduplicate while preserving order
_seen: set[str] = set()
GEMINI_MODEL_CHAIN = [
    m for m in GEMINI_MODEL_CHAIN if m not in _seen and not _seen.add(m)  # type: ignore[func-returns-value]
]


def _resolve_gemini_api_key() -> str | None:
    """Resolve Gemini API key from settings and direct env fallbacks."""
    from app.core.config import settings

    return (
        settings.GEMINI_API_KEY
        or settings.GOOGLE_API_KEY
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    )


def _ensure_configured() -> bool:
    """Lazily configure the google-generativeai SDK. Returns True on success."""
    global _gemini_configured
    if _gemini_configured:
        return True
    api_key = _resolve_gemini_api_key()
    if api_key:
        genai.configure(api_key=api_key)
        _gemini_configured = True
        logger.info("Gemini AI configured successfully (lazy init)")
        return True
    logger.error("Cannot operate: GOOGLE_API_KEY / GEMINI_API_KEY not configured")
    return False


# ---------------------------------------------------------------------------
# Error classification helpers
# ---------------------------------------------------------------------------
_QUOTA_INDICATORS = {"RESOURCE_EXHAUSTED", "429", "quota"}
_TRANSIENT_INDICATORS = {"UNAVAILABLE", "500", "502", "503", "504"}


def _is_quota_error(exc: Exception) -> bool:
    """Return True when the exception signals quota / rate-limit exhaustion."""
    msg = str(exc).lower()
    code = str(getattr(exc, "code", ""))
    status = str(getattr(exc, "status", ""))
    return (
        "resource_exhausted" in msg
        or "429" in code
        or status == "RESOURCE_EXHAUSTED"
        or "quota" in msg
        or "rate limit" in msg
    )


def _is_transient_error(exc: Exception) -> bool:
    """Return True when the exception signals a transient server error."""
    msg = str(exc).lower()
    code = str(getattr(exc, "code", ""))
    status = str(getattr(exc, "status", ""))
    return (
        "unavailable" in msg
        or any(c in code for c in ("500", "502", "503", "504"))
        or status in _TRANSIENT_INDICATORS
        or "overloaded" in msg
        or "server error" in msg
    )


def _classify_error(exc: Exception) -> str:
    """Return a machine-readable error type string."""
    if _is_quota_error(exc):
        return "quota_exceeded"
    if _is_transient_error(exc):
        return "model_overloaded"
    return "api_error"


# ---------------------------------------------------------------------------
# Core fallback helper
# ---------------------------------------------------------------------------
def _call_gemini_with_fallback(
    prompt: str | list,
    *,
    model_chain: list[str] | None = None,
    generation_config: dict | None = None,
) -> tuple[str, str]:
    """
    Try each model in *model_chain* until one succeeds.

    Returns (response_text, model_name_used).
    Raises the last exception if ALL models fail.
    """
    chain = model_chain or GEMINI_MODEL_CHAIN
    gen_cfg = genai.types.GenerationConfig(**(generation_config or {}))
    last_exc: Exception | None = None

    for idx, model_name in enumerate(chain):
        try:
            model = genai.GenerativeModel(model_name, generation_config=gen_cfg)
            logger.info("Trying model %s (%d/%d)", model_name, idx + 1, len(chain))
            response = model.generate_content(prompt)
            logger.info("Model %s succeeded", model_name)
            return response.text.strip(), model_name
        except Exception as exc:
            last_exc = exc
            error_type = _classify_error(exc)

            if error_type == "quota_exceeded" and idx < len(chain) - 1:
                logger.warning(
                    "Model %s quota exceeded, falling back to %s",
                    model_name,
                    chain[idx + 1],
                )
                continue

            if error_type == "model_overloaded" and idx < len(chain) - 1:
                logger.warning(
                    "Model %s overloaded, falling back to %s",
                    model_name,
                    chain[idx + 1],
                )
                time.sleep(1)  # brief pause before fallback
                continue

            # Non-retryable or last model — raise
            raise

    # Should not reach here, but safety net
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Company context builder
# ---------------------------------------------------------------------------
def _build_company_context(company_context: dict[str, str] | None = None) -> str:
    """Build company persona section for AI prompts."""
    if not company_context:
        return "You are an Expert Consultant analyzing technical task documents."

    name = company_context.get("company_name", "")
    services = company_context.get("core_services", "")
    experience = company_context.get("past_experience", "")

    if not name:
        return "You are an Expert Consultant analyzing technical task documents."

    parts = [f"You are the Lead Proposal Writer for {name}."]
    if services:
        parts.append(f"Your company specializes in: {services}.")
    if experience:
        parts.append(f"Key qualifications and past experience: {experience}.")
    parts.append("Use this context to write relevant, company-specific analysis.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------
def _extract_json(response_text: str) -> dict[str, Any]:
    """Extract a JSON object from a potentially wrapped response."""
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    start_idx = text.find("{")
    end_idx = text.rfind("}") + 1
    if start_idx >= 0 and end_idx > start_idx:
        text = text[start_idx:end_idx]

    return json.loads(text)


# ---------------------------------------------------------------------------
# Not-configured fallback
# ---------------------------------------------------------------------------
def _not_configured_result(**overrides: Any) -> dict[str, Any]:
    base = {
        "error": "AI not configured",
        "error_type": "api_error",
        "summary": "AI analysis unavailable - API key not configured",
        "items": [],
        "delivery_days": 30,
        "required_licenses": [],
    }
    base.update(overrides)
    return base


def _too_short_result(**overrides: Any) -> dict[str, Any]:
    base = {
        "error": "Text too short",
        "error_type": "api_error",
        "summary": "Document text too short for analysis",
        "items": [],
        "delivery_days": 30,
        "required_licenses": [],
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# Tender Analysis Prompt
# ═══════════════════════════════════════════════════════════════════════════

TENDER_ANALYSIS_PROMPT = """{company_persona}
The document may be in Uzbek (Cyrillic or Latin), Russian, or English.

Analyze the following tender technical task text and extract structured information.

IMPORTANT: Return ONLY valid JSON, no markdown, no explanation.

Required JSON structure:
{{
    "summary": "A 2-3 sentence technical summary of what this tender is about",
    "items": [
        {{"name": "Item name", "quantity": 10, "unit": "pcs"}},
        {{"name": "Another item", "quantity": 5, "unit": "sets"}}
    ],
    "delivery_days": 30,
    "required_licenses": ["ISO 9001", "Construction License"],
    "estimated_cost_breakdown": {{
        "materials": 0,
        "labor": 0,
        "other": 0
    }},
    "key_requirements": ["Requirement 1", "Requirement 2"],
    "risks": ["Potential risk 1", "Potential risk 2"]
}}

Rules:
- "items": Extract all products/services/equipment mentioned with quantities. If quantity not specified, estimate or use 1.
- "delivery_days": Look for delivery timeline. Default to 30 if not mentioned.
- "required_licenses": Any certifications, licenses, or qualifications required.
- "estimated_cost_breakdown": Rough breakdown if budget info is available, otherwise use zeros.
- "key_requirements": Technical specifications, standards, conditions that must be met.
- "risks": Potential challenges or risks you identify.

TEXT TO ANALYZE:
---
{text}
---

Return ONLY the JSON object, nothing else."""


def analyze_tender_text(
    text: str, company_context: dict[str, str] | None = None
) -> dict[str, Any]:
    """
    Analyze tender document text using Gemini AI with model fallback.

    Returns structured data dict with summary, items, delivery_days, etc.
    """
    if not _ensure_configured():
        return _not_configured_result()

    if not text or len(text.strip()) < 100:
        logger.warning("Text too short for meaningful analysis")
        return _too_short_result()

    try:
        max_chars = 100_000
        if len(text) > max_chars:
            logger.warning("Text truncated from %d to %d chars", len(text), max_chars)
            text = text[:max_chars]

        company_persona = _build_company_context(company_context)
        prompt = TENDER_ANALYSIS_PROMPT.format(text=text, company_persona=company_persona)

        response_text, model_used = _call_gemini_with_fallback(
            prompt,
            generation_config={"response_mime_type": "application/json"},
        )
        logger.info("Tender analysis completed with model %s", model_used)
        result = _extract_json(response_text)
        logger.info("AI analysis complete: %d items extracted", len(result.get("items", [])))
        return result

    except json.JSONDecodeError as e:
        logger.error("Failed to parse AI response as JSON: %s", e)
        return {
            "error": f"JSON parse error: {e}",
            "error_type": "api_error",
            "summary": "AI response could not be parsed - please try again",
            "items": [],
            "delivery_days": 30,
            "required_licenses": [],
        }

    except Exception as e:
        error_type = _classify_error(e)
        logger.error("Gemini API error (%s): %s", error_type, e)
        import traceback
        logger.error(traceback.format_exc())

        if error_type == "quota_exceeded":
            summary = "Monthly AI quota reached across all models. Please try again later or contact support."
        elif error_type == "model_overloaded":
            summary = "AI models are temporarily overloaded. Please retry in a few minutes."
        else:
            summary = f"AI analysis failed: {e}"

        return {
            "error": str(e),
            "error_type": error_type,
            "summary": summary,
            "items": [],
            "delivery_days": 30,
            "required_licenses": [],
        }


async def analyze_tender_text_async(
    text: str, company_context: dict[str, str] | None = None
) -> dict[str, Any]:
    """Async wrapper for analyze_tender_text."""
    import asyncio
    from functools import partial

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, partial(analyze_tender_text, text, company_context)
    )


# ═══════════════════════════════════════════════════════════════════════════
# Strategic Draft Prompt
# ═══════════════════════════════════════════════════════════════════════════

STRATEGIC_DRAFT_PROMPT = """{company_persona}
Act as a Chief Revenue Officer. Write a persuasive, 3-paragraph `strategic_summary`. Emphasize verified credentials. You MUST provide a commercial justification for these accepted liabilities: [{accepted_liabilities}].

You are drafting a commercial proposal with compliance context:
- Tender budget: {tender_budget}
- Compliance ledger snapshot:
{compliance_ledger}

Analyze the tender text and return ONLY valid JSON with this exact shape:
{{
    "strategic_summary": "string",
    "suggested_price": 0,
    "delivery_days": "string",
    "line_items": [
        {{
            "name": "string",
            "quantity": 1,
            "unit": "string",
            "unit_price": 0,
            "total": 0
        }}
    ]
}}

Rules:
- `strategic_summary` must be exactly 3 paragraphs and commercially persuasive.
- Mention verified credentials from the compliance ledger and how they de-risk execution.
- If accepted liabilities are listed, include business rationale for each.
- `suggested_price` must be numeric and competitive for the scope.
- `delivery_days` must be a readable string (e.g., "45 calendar days").
- `line_items` must include practical deliverables with realistic quantities and totals.

TENDER TEXT:
---
{text}
---
"""


def draft_strategic_proposal(
    text: str,
    *,
    company_context: dict[str, str] | None = None,
    compliance_ledger: dict[str, Any] | None = None,
    accepted_liabilities: list[str] | None = None,
    tender_budget: float = 0.0,
) -> dict[str, Any]:
    """Generate a strategic proposal draft with model fallback chain."""
    if not _ensure_configured():
        return {
            "error": "AI not configured",
            "error_type": "api_error",
            "strategic_summary": "AI drafting unavailable - API key not configured.",
            "suggested_price": float(tender_budget or 0.0),
            "delivery_days": "30 calendar days",
            "line_items": [],
        }

    if not text or len(text.strip()) < 100:
        logger.warning("Text too short for strategic drafting")
        return {
            "error": "Text too short",
            "error_type": "api_error",
            "strategic_summary": "Tender text is too short for strategic drafting.",
            "suggested_price": float(tender_budget or 0.0),
            "delivery_days": "30 calendar days",
            "line_items": [],
        }

    liabilities_text = ", ".join(accepted_liabilities or []).strip() or "None recorded"
    ledger_text = json.dumps(compliance_ledger or {}, ensure_ascii=False, indent=2)

    try:
        max_chars = 100_000
        if len(text) > max_chars:
            logger.warning("Text truncated from %s to %s chars", len(text), max_chars)
            text = text[:max_chars]

        company_persona = _build_company_context(company_context)
        prompt = STRATEGIC_DRAFT_PROMPT.format(
            text=text,
            company_persona=company_persona,
            accepted_liabilities=liabilities_text,
            compliance_ledger=ledger_text,
            tender_budget=tender_budget,
        )

        response_text, model_used = _call_gemini_with_fallback(
            prompt,
            generation_config={"response_mime_type": "application/json"},
        )
        logger.info("Strategic draft completed with model %s", model_used)
        result = _extract_json(response_text)

        # ── Normalize result fields ──
        summary = str(result.get("strategic_summary", "")).strip()
        if not summary:
            summary = (
                "We will execute this tender with proven delivery discipline, "
                "validated credentials, and measurable commercial value."
            )

        try:
            suggested_price = float(result.get("suggested_price", tender_budget or 0.0))
        except (TypeError, ValueError):
            suggested_price = float(tender_budget or 0.0)

        delivery_days = str(result.get("delivery_days", "")).strip() or "30 calendar days"
        raw_items = result.get("line_items", [])
        line_items: list[dict[str, Any]] = []
        if isinstance(raw_items, list):
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                quantity = item.get("quantity", 1)
                unit_price = item.get("unit_price", 0)
                total = item.get("total", 0)
                try:
                    quantity = float(quantity)
                except (TypeError, ValueError):
                    quantity = 1.0
                try:
                    unit_price = float(unit_price)
                except (TypeError, ValueError):
                    unit_price = 0.0
                try:
                    total = float(total)
                except (TypeError, ValueError):
                    total = quantity * unit_price
                line_items.append(
                    {
                        "name": str(item.get("name", "Line Item")).strip() or "Line Item",
                        "quantity": quantity,
                        "unit": str(item.get("unit", "lot")).strip() or "lot",
                        "unit_price": unit_price,
                        "total": total,
                    }
                )

        return {
            "strategic_summary": summary,
            "suggested_price": suggested_price,
            "delivery_days": delivery_days,
            "line_items": line_items,
        }

    except json.JSONDecodeError as exc:
        logger.error("Failed to parse strategic draft as JSON: %s", exc)
        return {
            "error": f"JSON parse error: {exc}",
            "error_type": "api_error",
            "strategic_summary": "AI drafting failed due to malformed model response.",
            "suggested_price": float(tender_budget or 0.0),
            "delivery_days": "30 calendar days",
            "line_items": [],
        }
    except Exception as exc:
        error_type = _classify_error(exc)
        logger.error("Strategic drafting error (%s): %s", error_type, exc)

        if error_type == "quota_exceeded":
            msg = "Monthly AI quota reached across all models. Please try again later or contact support."
        elif error_type == "model_overloaded":
            msg = "AI models are temporarily overloaded. Please retry in a few minutes."
        else:
            msg = f"AI drafting failed: {exc}"

        return {
            "error": str(exc),
            "error_type": error_type,
            "strategic_summary": msg,
            "suggested_price": float(tender_budget or 0.0),
            "delivery_days": "30 calendar days",
            "line_items": [],
        }


async def draft_strategic_proposal_async(
    text: str,
    *,
    company_context: dict[str, str] | None = None,
    compliance_ledger: dict[str, Any] | None = None,
    accepted_liabilities: list[str] | None = None,
    tender_budget: float = 0.0,
) -> dict[str, Any]:
    """Async wrapper for draft_strategic_proposal."""
    import asyncio
    from functools import partial

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        partial(
            draft_strategic_proposal,
            text,
            company_context=company_context,
            compliance_ledger=compliance_ledger,
            accepted_liabilities=accepted_liabilities,
            tender_budget=tender_budget,
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════
# File-based analysis (scanned PDFs via vision)
# ═══════════════════════════════════════════════════════════════════════════

# For file analysis we use a chain biased toward vision-capable models.
VISION_MODEL_CHAIN: list[str] = [
    "gemini-3.1-flash-lite-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-flash-lite",
]

FILE_ANALYSIS_PROMPT = """{company_persona}
You are analyzing a Technical Task document.
This document may be a SCANNED IMAGE or a text-based PDF. Use your vision capabilities to read it.
The document may be in Uzbek (Cyrillic or Latin), Russian, or English.

Analyze the attached document and extract structured information.

IMPORTANT: Return ONLY valid JSON, no markdown, no explanation.

Required JSON structure:
{{
    "summary": "A 2-3 sentence technical summary of what this tender is about",
    "items": [
        {{"name": "Item name", "quantity": 10, "unit": "pcs"}},
        {{"name": "Another item", "quantity": 5, "unit": "sets"}}
    ],
    "delivery_days": 30,
    "required_licenses": ["ISO 9001", "Construction License"],
    "estimated_cost_breakdown": {{
        "materials": 0,
        "labor": 0,
        "other": 0
    }},
    "key_requirements": ["Requirement 1", "Requirement 2"],
    "risks": ["Potential risk 1", "Potential risk 2"]
}}

Rules:
- "items": Extract all products/services/equipment mentioned with quantities. If quantity not specified, estimate or use 1.
- "delivery_days": Look for delivery timeline. Default to 30 if not mentioned.
- "required_licenses": Any certifications, licenses, or qualifications required.
- "estimated_cost_breakdown": Rough breakdown if budget info is available, otherwise use zeros.
- "key_requirements": Technical specifications, standards, conditions that must be met.
- "risks": Potential challenges or risks you identify.

Return ONLY the JSON object, nothing else."""


def analyze_tender_file(
    file_path: str, company_context: dict[str, str] | None = None
) -> dict[str, Any]:
    """
    Analyze tender document by uploading directly to Gemini (vision).

    Uses the vision model chain for best OCR/PDF reading results.
    """
    if not _ensure_configured():
        return _not_configured_result()

    chain = VISION_MODEL_CHAIN
    last_exc: Exception | None = None
    company_persona = _build_company_context(company_context)
    file_prompt = FILE_ANALYSIS_PROMPT.format(company_persona=company_persona)

    for idx, model_name in enumerate(chain):
        try:
            logger.info("[AI] Uploading file to Gemini: %s (model: %s)", file_path, model_name)
            uploaded_file = genai.upload_file(file_path)
            logger.info("[AI] File uploaded: %s", uploaded_file.name)

            model = genai.GenerativeModel(
                model_name,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                ),
            )

            response = model.generate_content([uploaded_file, file_prompt])
            response_text = response.text.strip()

            # Cleanup uploaded file
            try:
                genai.delete_file(uploaded_file.name)
            except Exception:
                pass

            result = _extract_json(response_text)
            logger.info(
                "AI file analysis complete with %s: %d items extracted",
                model_name,
                len(result.get("items", [])),
            )
            return result

        except json.JSONDecodeError as e:
            logger.error("Failed to parse AI response as JSON: %s", e)
            return {
                "error": f"JSON parse error: {e}",
                "error_type": "api_error",
                "summary": "AI response could not be parsed - please try again",
                "items": [],
                "delivery_days": 30,
                "required_licenses": [],
            }

        except Exception as e:
            last_exc = e
            error_type = _classify_error(e)
            if error_type in ("quota_exceeded", "model_overloaded") and idx < len(chain) - 1:
                logger.warning(
                    "Model %s %s during file analysis, falling back to %s",
                    model_name,
                    error_type,
                    chain[idx + 1],
                )
                continue

            logger.error("Gemini file analysis error (%s): %s", error_type, e)
            import traceback
            logger.error(traceback.format_exc())

            if error_type == "quota_exceeded":
                summary = "Monthly AI quota reached. Please try again later or contact support."
            elif error_type == "model_overloaded":
                summary = "AI models temporarily overloaded. Please retry in a few minutes."
            else:
                summary = f"AI analysis failed: {e}"

            return {
                "error": str(e),
                "error_type": error_type,
                "summary": summary,
                "items": [],
                "delivery_days": 30,
                "required_licenses": [],
            }

    # Safety net — should not reach here
    return {
        "error": str(last_exc),
        "error_type": "quota_exceeded",
        "summary": "All AI models exhausted. Please try again later.",
        "items": [],
        "delivery_days": 30,
        "required_licenses": [],
    }


async def analyze_tender_file_async(
    file_path: str, company_context: dict[str, str] | None = None
) -> dict[str, Any]:
    """Async wrapper for analyze_tender_file."""
    import asyncio
    from functools import partial

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, partial(analyze_tender_file, file_path, company_context)
    )
