from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-3-flash-preview"
MAX_TENDER_TEXT_CHARS = 120_000


def _resolve_gemini_api_key() -> str | None:
    """
    Resolve Gemini API key from settings first, then env fallback.

    This keeps behavior consistent across Docker and local runs where
    `.env` may be loaded via Pydantic settings rather than shell exports.
    """
    from app.core.config import settings

    return (
        settings.GEMINI_API_KEY
        or settings.GOOGLE_API_KEY
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    )


class RiskItem(BaseModel):
    risk_type: str
    description: str
    severity: Literal["High", "Medium", "Low"]
    source_quote: str


class GapAnalysisResult(BaseModel):
    is_fully_compliant: bool
    missing_requirements: list[str] = Field(default_factory=list)
    identified_risks: list[RiskItem] = Field(default_factory=list)
    recommended_mitigation_strategy: str


def _fallback_result(
    missing: str,
    risk_type: str,
    description: str,
    severity: Literal["High", "Medium", "Low"],
    mitigation: str,
) -> GapAnalysisResult:
    return GapAnalysisResult(
        is_fully_compliant=False,
        missing_requirements=[missing],
        identified_risks=[
            RiskItem(
                risk_type=risk_type,
                description=description,
                severity=severity,
                source_quote="No reliable source quote available due to fallback handling.",
            )
        ],
        recommended_mitigation_strategy=mitigation,
    )


def _build_prompt(tender_text: str, company_profile: dict[str, Any]) -> str:
    return f"""
You are a strict legal procurement auditor for government tenders.
Your task is to compare the tender requirements against the company profile and identify compliance gaps.

Rules:
- Focus on legal and technical requirements only.
- Ignore OCR artifacts, garbled symbols, duplicated scan noise, and page footer/header artifacts.
- Prioritize missing licenses/certifications, bank guarantee gaps, insurance gaps, and unrealistic delivery/completion deadlines.
- If information is missing from the company profile, treat it as not satisfied.
- Flag missing mandatory legal documents explicitly (licenses, permits, guarantees, compliance certificates).
- Output must be valid JSON only. No markdown, no commentary.
- Do not wrap output in markdown code blocks like ```json.
- Return exactly one JSON object with these keys only:
  is_fully_compliant, missing_requirements, identified_risks, recommended_mitigation_strategy
- Each identified_risks item must include risk_type, description, severity, source_quote.
- severity must be one of: High, Medium, Low.
- source_quote must be an exact verbatim sentence or short paragraph copied from tender text.

Required JSON schema:
{{
  "is_fully_compliant": true,
  "missing_requirements": ["string"],
  "identified_risks": [
    {{
      "risk_type": "string",
      "description": "string",
      "severity": "High|Medium|Low",
      "source_quote": "The exact verbatim sentence or paragraph from the raw text that triggered this risk."
    }}
  ],
  "recommended_mitigation_strategy": "string"
}}

You MUST return your analysis strictly as a valid JSON object matching this exact structure, with no markdown formatting or extra text:
{{
  "is_fully_compliant": false,
  "missing_requirements": ["list of strings"],
  "identified_risks": [
    {{
      "risk_type": "string",
      "description": "string",
      "severity": "High | Medium | Low",
      "source_quote": "The exact verbatim sentence or paragraph from the raw text that triggered this risk."
    }}
  ],
  "recommended_mitigation_strategy": "string"
}}

Company Profile (JSON):
{json.dumps(company_profile, ensure_ascii=False)}

Tender Text:
{tender_text}
""".strip()


def _parse_json_text(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]

    return json.loads(text)


def _is_rate_limited_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True

    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "resource_exhausted" in msg


def _sync_generate_gap_analysis(prompt: str, api_key: str) -> GapAnalysisResult:
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )

    raw_text = getattr(response, "text", "") or ""
    if not raw_text.strip():
        return _fallback_result(
            missing="Model returned an empty response.",
            risk_type="SchemaValidation",
            description="Gemini returned no JSON payload for gap analysis.",
            severity="Medium",
            mitigation="Retry analysis and verify prompt/config constraints.",
        )

    try:
        parsed_result = GapAnalysisResult.model_validate_json(raw_text)
        return parsed_result
    except ValidationError as exc:
        logger.error("GapAnalysisResult.model_validate_json failed: %s", exc)
        try:
            parsed_json = _parse_json_text(raw_text)
            return GapAnalysisResult.model_validate(parsed_json)
        except (json.JSONDecodeError, ValidationError) as second_exc:
            logger.error("Fallback JSON parse/validate failed: %s", second_exc)
            return _fallback_result(
                missing="Model response could not be validated against required schema.",
                risk_type="SchemaValidation",
                description=f"Structured output validation failed: {type(second_exc).__name__}",
                severity="Medium",
                mitigation="Retry and, if persistent, tighten prompt constraints or inspect raw model output.",
            )


async def analyze_tender_gaps(tender_text: str, company_profile: dict[str, Any]) -> GapAnalysisResult:
    api_key = _resolve_gemini_api_key()
    if not api_key:
        logger.error("GEMINI_API_KEY is not set")
        return _fallback_result(
            missing="Gemini API key is not configured.",
            risk_type="System",
            description="Gap analysis could not run because GEMINI_API_KEY is missing.",
            severity="High",
            mitigation="Set GEMINI_API_KEY and retry analysis.",
        )

    cleaned_text = (tender_text or "").strip()
    if not cleaned_text:
        return _fallback_result(
            missing="Tender text is empty.",
            risk_type="InputQuality",
            description="No tender content was provided to the analyzer.",
            severity="High",
            mitigation="Re-run extraction and provide non-empty tender text.",
        )

    if len(cleaned_text) > MAX_TENDER_TEXT_CHARS:
        logger.warning(
            "Tender text truncated from %s to %s characters",
            len(cleaned_text),
            MAX_TENDER_TEXT_CHARS,
        )
        cleaned_text = cleaned_text[:MAX_TENDER_TEXT_CHARS]

    prompt = _build_prompt(cleaned_text, company_profile)

    try:
        return await asyncio.to_thread(_sync_generate_gap_analysis, prompt, api_key)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Gemini response schema parsing failed: %s", exc)
        return _fallback_result(
            missing="Model response could not be validated against schema.",
            risk_type="SchemaValidation",
            description=f"Structured output validation failed: {type(exc).__name__}",
            severity="Medium",
            mitigation="Retry and, if persistent, inspect prompt/schema compatibility.",
        )
    except Exception as exc:
        if _is_rate_limited_error(exc):
            logger.warning("Gemini rate limit reached: %s", exc)
            return _fallback_result(
                missing="Gap analysis temporarily unavailable due to API rate limit (429).",
                risk_type="RateLimit",
                description="Gemini API throttled the request.",
                severity="Medium",
                mitigation="Retry with backoff in 30-60 seconds.",
            )

        logger.exception("Gemini gap analysis failed")
        return _fallback_result(
            missing="Gap analysis could not be completed due to API/system failure.",
            risk_type="System",
            description=f"Gemini analysis failed: {type(exc).__name__}",
            severity="Medium",
            mitigation=(
                "Retry after a short delay. If failures persist, verify GEMINI_API_KEY, "
                "model availability, and network connectivity."
            ),
        )
