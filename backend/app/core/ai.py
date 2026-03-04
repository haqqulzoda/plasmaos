"""
Plasma AI - AI Analysis Module

Uses Google Gemini to analyze tender documents and extract structured data.
"""

import json
import logging
import os
from typing import Any

import google.generativeai as genai
from google.genai import errors
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Lazy initialization flag
_gemini_configured = False


# Gemini model configuration
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")


def _resolve_gemini_api_key() -> str | None:
    """Resolve Gemini API key from settings and direct env fallbacks."""
    from app.core.config import settings

    return (
        settings.GEMINI_API_KEY
        or settings.GOOGLE_API_KEY
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    )

# Company context builder
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


def analyze_tender_text(text: str, company_context: dict[str, str] | None = None) -> dict[str, Any]:
    """
    Analyze tender document text using Gemini AI.
    
    Args:
        text: Extracted text from tender document
        
    Returns:
        Structured data dict with summary, items, delivery_days, etc.
    """
    global _gemini_configured
    
    # Lazy initialization - configure Gemini on first call
    if not _gemini_configured:
        api_key = _resolve_gemini_api_key()
        if api_key:
            genai.configure(api_key=api_key)
            _gemini_configured = True
            logger.info("Gemini AI configured successfully (lazy init)")
        else:
            logger.error("Cannot analyze: GOOGLE_API_KEY not configured")
            return {
                "error": "AI not configured",
                "summary": "AI analysis unavailable - API key not configured",
                "items": [],
                "delivery_days": 30,
                "required_licenses": [],
            }
    
    if not text or len(text.strip()) < 100:
        logger.warning("Text too short for meaningful analysis")
        return {
            "error": "Text too short",
            "summary": "Document text too short for analysis",
            "items": [],
            "delivery_days": 30,
            "required_licenses": [],
        }
    
    try:
        model = genai.GenerativeModel(
            MODEL_NAME,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        
        # Truncate if extremely long (though Flash handles 1M tokens)
        max_chars = 100_000  # ~25K tokens for faster processing
        if len(text) > max_chars:
            logger.warning(f"Text truncated from {len(text)} to {max_chars} chars")
            text = text[:max_chars]
        
        company_persona = _build_company_context(company_context)
        prompt = TENDER_ANALYSIS_PROMPT.format(text=text, company_persona=company_persona)
        
        logger.info(f"Sending {len(text)} chars to Gemini {MODEL_NAME}")
        response = model.generate_content(prompt)
        
        # Extract JSON from response
        response_text = response.text.strip()
        logger.debug(f"Raw response (first 500): {response_text[:500]}")
        
        # Clean up response (remove markdown code blocks if present)
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            # Remove first and last lines (```json and ```)
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            response_text = "\n".join(lines)
        
        # Try to find JSON object in response
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx >= 0 and end_idx > start_idx:
            response_text = response_text[start_idx:end_idx]
        
        result = json.loads(response_text)
        logger.info(f"AI analysis complete: {len(result.get('items', []))} items extracted")
        
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response as JSON: {e}")
        logger.error(f"Raw response: {response_text[:1000] if 'response_text' in dir() else 'N/A'}")
        return {
            "error": f"JSON parse error: {e}",
            "summary": "AI response could not be parsed - please try again",
            "items": [],
            "delivery_days": 30,
            "required_licenses": [],
        }
        
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "error": str(e),
            "summary": f"AI analysis failed: {e}",
            "items": [],
            "delivery_days": 30,
            "required_licenses": [],
        }


async def analyze_tender_text_async(text: str, company_context: dict[str, str] | None = None) -> dict[str, Any]:
    """
    Async wrapper for analyze_tender_text.
    
    Uses run_in_executor since google-generativeai is sync.
    """
    import asyncio
    from functools import partial
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(analyze_tender_text, text, company_context))


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


def _log_strategic_draft_retry_warning(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    sleep_seconds = retry_state.next_action.sleep if retry_state.next_action else 0.0
    logger.warning(
        "Strategic draft Gemini API Error. Retrying attempt %s/4 in %.1fs: %s",
        retry_state.attempt_number + 1,
        sleep_seconds,
        exc,
    )


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(errors.APIError),
    before_sleep=_log_strategic_draft_retry_warning,
    reraise=True
)
def draft_strategic_proposal(
    text: str,
    *,
    company_context: dict[str, str] | None = None,
    compliance_ledger: dict[str, Any] | None = None,
    accepted_liabilities: list[str] | None = None,
    tender_budget: float = 0.0,
) -> dict[str, Any]:
    """Generate a strategic proposal draft aligned to compliance ledger context."""
    global _gemini_configured

    if not _gemini_configured:
        api_key = _resolve_gemini_api_key()
        if api_key:
            genai.configure(api_key=api_key)
            _gemini_configured = True
            logger.info("Gemini AI configured successfully (lazy init)")
        else:
            logger.error("Cannot draft: GOOGLE_API_KEY not configured")
            return {
                "error": "AI not configured",
                "strategic_summary": "AI drafting unavailable - API key not configured.",
                "suggested_price": float(tender_budget or 0.0),
                "delivery_days": "30 calendar days",
                "line_items": [],
            }

    if not text or len(text.strip()) < 100:
        logger.warning("Text too short for strategic drafting")
        return {
            "error": "Text too short",
            "strategic_summary": "Tender text is too short for strategic drafting.",
            "suggested_price": float(tender_budget or 0.0),
            "delivery_days": "30 calendar days",
            "line_items": [],
        }

    liabilities_text = ", ".join(accepted_liabilities or []).strip() or "None recorded"
    ledger_text = json.dumps(compliance_ledger or {}, ensure_ascii=False, indent=2)

    try:
        model = genai.GenerativeModel(
            MODEL_NAME,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
            ),
        )

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

        response = model.generate_content(prompt)
        response_text = response.text.strip()

        if response_text.startswith("```"):
            lines = response_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            response_text = "\n".join(lines)

        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx >= 0 and end_idx > start_idx:
            response_text = response_text[start_idx:end_idx]

        result = json.loads(response_text)

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
            "strategic_summary": "AI drafting failed due to malformed model response.",
            "suggested_price": float(tender_budget or 0.0),
            "delivery_days": "30 calendar days",
            "line_items": [],
        }
    except errors.APIError:
        raise
    except Exception as exc:
        logger.error("Strategic drafting error: %s", exc)
        return {
            "error": str(exc),
            "strategic_summary": f"AI drafting failed: {exc}",
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


# Prompt for file-based analysis (handles scanned PDFs)
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


def analyze_tender_file(file_path: str, company_context: dict[str, str] | None = None) -> dict[str, Any]:
    """
    Analyze tender document by uploading directly to Gemini.
    
    Uses Gemini's vision capabilities to read scanned/image PDFs.
    
    Args:
        file_path: Path to the PDF file
        
    Returns:
        Structured data dict with summary, items, delivery_days, etc.
    """
    global _gemini_configured
    
    # Lazy initialization - configure Gemini on first call
    if not _gemini_configured:
        api_key = _resolve_gemini_api_key()
        if api_key:
            genai.configure(api_key=api_key)
            _gemini_configured = True
            logger.info("Gemini AI configured successfully (lazy init)")
        else:
            logger.error("Cannot analyze: GOOGLE_API_KEY not configured")
            return {
                "error": "AI not configured",
                "summary": "AI analysis unavailable - API key not configured",
                "items": [],
                "delivery_days": 30,
                "required_licenses": [],
            }
    
    try:
        print(f"[AI] Uploading file to Gemini: {file_path}")
        
        # Upload file to Gemini
        uploaded_file = genai.upload_file(file_path)
        print(f"[AI] File uploaded: {uploaded_file.name}")
        
        # Create model (use gemini-3-flash-preview for vision + speed)
        model = genai.GenerativeModel(
            MODEL_NAME,  # Uses gemini-3-flash-preview
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        
        print("[AI] Sending to Gemini for analysis...")
        company_persona = _build_company_context(company_context)
        file_prompt = FILE_ANALYSIS_PROMPT.format(company_persona=company_persona)
        response = model.generate_content([uploaded_file, file_prompt])
        
        # Extract JSON from response
        response_text = response.text.strip()
        print(f"[AI] Raw response (first 300): {response_text[:300]}")
        
        # Clean up response (remove markdown code blocks if present)
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            response_text = "\n".join(lines)
        
        # Try to find JSON object in response
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx >= 0 and end_idx > start_idx:
            response_text = response_text[start_idx:end_idx]
        
        result = json.loads(response_text)
        print(f"[AI] Analysis complete: {len(result.get('items', []))} items extracted")
        logger.info(f"AI file analysis complete: {len(result.get('items', []))} items extracted")
        
        # Cleanup uploaded file
        try:
            genai.delete_file(uploaded_file.name)
            print(f"[AI] Cleaned up uploaded file")
        except Exception:
            pass  # Ignore cleanup errors
        
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response as JSON: {e}")
        return {
            "error": f"JSON parse error: {e}",
            "summary": "AI response could not be parsed - please try again",
            "items": [],
            "delivery_days": 30,
            "required_licenses": [],
        }
        
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        print(f"[AI] Error: {e}")
        return {
            "error": str(e),
            "summary": f"AI analysis failed: {e}",
            "items": [],
            "delivery_days": 30,
            "required_licenses": [],
        }


async def analyze_tender_file_async(file_path: str, company_context: dict[str, str] | None = None) -> dict[str, Any]:
    """
    Async wrapper for analyze_tender_file.
    
    Uses run_in_executor since google-generativeai is sync.
    """
    import asyncio
    from functools import partial
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(analyze_tender_file, file_path, company_context))

