from __future__ import annotations

import asyncio
import json
import logging
import os
from functools import partial
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model fallback chain for compliance extraction
# ---------------------------------------------------------------------------
EXTRACTION_MODEL_CHAIN: list[str] = [
    os.getenv("GEMINI_EXTRACTION_MODEL", "gemini-3.1-flash-lite-preview"),
    "gemini-3-flash-preview",
    "gemini-2.5-flash-lite",
]
# Deduplicate while preserving order
_seen: set[str] = set()
EXTRACTION_MODEL_CHAIN = [
    m for m in EXTRACTION_MODEL_CHAIN if m not in _seen and not _seen.add(m)  # type: ignore[func-returns-value]
]

MAX_TENDER_TEXT_CHARS = 120_000
GENAI_MAX_RETRY_ATTEMPTS = 3
GENAI_RETRY_BACKOFF_BASE_SECONDS = 1.5
GENAI_RETRY_BACKOFF_MAX_SECONDS = 12.0
GENAI_RETRYABLE_CODES = {429, 500, 502, 503, 504}
LLM_CALL_TIMEOUT: float = 45.0


class ExtractionError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 500, error_type: str = "api_error"):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


class DynamicTenderRequirements(BaseModel):
    model_config = ConfigDict(strict=False)

    mapped_requirement_uuids: list[str] = []
    unmapped_custom_requirements: list[str] = []

    @property
    def required_isos(self) -> list[str]:
        return []

    @property
    def min_turnover_uzs(self) -> int | None:
        return None

    @property
    def required_licenses(self) -> list[str]:
        return []


ExtractedTenderRequirements = DynamicTenderRequirements
GapAnalysisResult = DynamicTenderRequirements


def _resolve_gemini_api_key() -> str | None:
    from app.core.config import settings

    return (
        settings.GEMINI_API_KEY
        or settings.GOOGLE_API_KEY
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    )


def _build_extraction_prompt(tender_text: str, available_taxonomy: list[dict]) -> str:
    taxonomy_json = json.dumps(available_taxonomy)
    return f"""
You are a strict procurement classifier. Read the tender text. If a requirement matches an item in the Provided Taxonomy, output its exact UUID in the `mapped_requirement_uuids` array. Do not invent UUIDs. If you find a mandatory requirement that does NOT exist in the taxonomy, summarize it as a string in the `unmapped_custom_requirements` array.

Output only valid JSON with exactly these keys:
- mapped_requirement_uuids (array of strings)
- unmapped_custom_requirements (array of strings)

Provided Taxonomy (JSON):
{taxonomy_json}

Tender text:
{tender_text}
""".strip()


def _validate_structured_response(response: Any) -> DynamicTenderRequirements:
    parsed_payload = getattr(response, "parsed", None)
    if parsed_payload is not None:
        try:
            return DynamicTenderRequirements.model_validate(parsed_payload, strict=False)
        except ValidationError as exc:
            raise ExtractionError(
                "LLM response failed DynamicTenderRequirements schema validation."
            ) from exc

    response_text = (getattr(response, "text", "") or "").strip()
    if not response_text:
        raise ExtractionError("LLM returned no structured extraction payload.")

    try:
        return DynamicTenderRequirements.model_validate_json(response_text, strict=False)
    except ValidationError as exc:
        raise ExtractionError(
            "LLM response failed DynamicTenderRequirements schema validation."
        ) from exc


def _is_quota_error(exc: genai_errors.APIError) -> bool:
    """Return True when the error signals quota / rate-limit exhaustion."""
    code = int(getattr(exc, "code", 0) or 0)
    status = str(getattr(exc, "status", "") or "")
    msg = str(getattr(exc, "message", "") or "").lower()
    return code == 429 or status == "RESOURCE_EXHAUSTED" or "quota" in msg


async def _extract_tender_requirements_impl(
    tender_text: str, available_taxonomy: list[dict], api_key: str
) -> DynamicTenderRequirements:
    """Async extraction with asyncio.sleep backoff and per-call timeouts."""
    prompt = _build_extraction_prompt(
        tender_text=tender_text, available_taxonomy=available_taxonomy
    )
    client = genai.Client(api_key=api_key)

    last_exc: Exception | None = None

    for model_idx, model_name in enumerate(EXTRACTION_MODEL_CHAIN):
        logger.info(
            "Extraction: trying model %s (%d/%d)",
            model_name, model_idx + 1, len(EXTRACTION_MODEL_CHAIN),
        )

        for attempt in range(1, GENAI_MAX_RETRY_ATTEMPTS + 1):
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        partial(
                            client.models.generate_content,
                            model=model_name,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                response_schema=DynamicTenderRequirements,
                                temperature=0.0,
                            ),
                        )
                    ),
                    timeout=LLM_CALL_TIMEOUT,
                )
                return _validate_structured_response(response)
            except asyncio.TimeoutError:
                last_exc = TimeoutError(f"Model {model_name} timed out after {LLM_CALL_TIMEOUT}s")
                logger.warning(
                    "Model %s timed out after %.0fs during extraction, %s",
                    model_name, LLM_CALL_TIMEOUT,
                    f"falling back to {EXTRACTION_MODEL_CHAIN[model_idx + 1]}"
                    if model_idx < len(EXTRACTION_MODEL_CHAIN) - 1 else "no more models",
                )
                if model_idx < len(EXTRACTION_MODEL_CHAIN) - 1:
                    break  # advance to next model
                raise ExtractionError(
                    f"All models timed out during extraction.",
                    status_code=504,
                    error_type="model_overloaded",
                ) from last_exc
            except ValidationError as exc:
                raise ExtractionError(
                    "LLM response failed DynamicTenderRequirements schema validation."
                ) from exc
            except ExtractionError:
                raise
            except genai_errors.APIError as exc:
                last_exc = exc
                error_code = int(getattr(exc, "code", 0) or 0)
                error_status = str(getattr(exc, "status", "") or "")
                error_message = str(getattr(exc, "message", "") or "").strip()

                # ── Quota exhausted → skip to next model immediately ──
                if _is_quota_error(exc):
                    if model_idx < len(EXTRACTION_MODEL_CHAIN) - 1:
                        logger.warning(
                            "Model %s quota exceeded, falling back to %s",
                            model_name,
                            EXTRACTION_MODEL_CHAIN[model_idx + 1],
                        )
                        break  # break retry loop → advance model
                    # Last model — raise
                    raise ExtractionError(
                        f"Monthly AI quota reached across all models. "
                        f"Last error: {error_message or 'RESOURCE_EXHAUSTED'}",
                        status_code=429,
                        error_type="quota_exceeded",
                    ) from exc

                # ── Transient server error → retry same model ──
                is_retryable = error_code in GENAI_RETRYABLE_CODES
                if is_retryable and attempt < GENAI_MAX_RETRY_ATTEMPTS:
                    delay_seconds = min(
                        GENAI_RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
                        GENAI_RETRY_BACKOFF_MAX_SECONDS,
                    )
                    logger.warning(
                        "Extraction transient error (code=%s status=%s). "
                        "Retrying attempt %s/%s on %s in %.1fs.",
                        error_code, error_status,
                        attempt + 1, GENAI_MAX_RETRY_ATTEMPTS,
                        model_name, delay_seconds,
                    )
                    await asyncio.sleep(delay_seconds)
                    continue

                # ── Transient but retries exhausted → try next model ──
                if is_retryable and model_idx < len(EXTRACTION_MODEL_CHAIN) - 1:
                    logger.warning(
                        "Model %s retries exhausted (code=%s), falling back to %s",
                        model_name, error_code, EXTRACTION_MODEL_CHAIN[model_idx + 1],
                    )
                    break  # advance model

                # ── Non-retryable or last model ──
                mapped_status_code = 500
                error_type = "api_error"
                if error_code == 429 or error_status == "RESOURCE_EXHAUSTED":
                    mapped_status_code = 429
                    error_type = "quota_exceeded"
                elif error_code in {500, 502, 503, 504} or error_status in {"UNAVAILABLE"}:
                    mapped_status_code = 503
                    error_type = "model_overloaded"

                raise ExtractionError(
                    (
                        f"Tender requirement extraction failed (Gemini API {error_code} "
                        f"{error_status}): {error_message or 'no error message'}"
                    ),
                    status_code=mapped_status_code,
                    error_type=error_type,
                ) from exc
            except Exception as exc:
                logger.exception("Tender requirement extraction failed")
                raise ExtractionError("Tender requirement extraction failed.") from exc
        else:
            # Retry loop exhausted without break → advance via outer loop
            continue

    raise ExtractionError(
        "Tender requirement extraction failed after all models exhausted.",
        status_code=503,
        error_type="quota_exceeded",
    )


def extract_tender_requirements_sync(
    tender_text: str, available_taxonomy: list[dict]
) -> DynamicTenderRequirements:
    """Sync wrapper — uses asyncio.run() over the async implementation."""
    api_key = _resolve_gemini_api_key()
    if not api_key:
        raise ExtractionError("GEMINI_API_KEY is not configured.")

    cleaned_text = (tender_text or "").strip()
    if not cleaned_text:
        raise ExtractionError("Tender text is empty.")

    if len(cleaned_text) > MAX_TENDER_TEXT_CHARS:
        cleaned_text = cleaned_text[:MAX_TENDER_TEXT_CHARS]

    return asyncio.run(
        _extract_tender_requirements_impl(cleaned_text, available_taxonomy, api_key)
    )


async def extract_tender_requirements(
    tender_text: str, available_taxonomy: list[dict]
) -> DynamicTenderRequirements:
    """Async entry point — calls native async implementation directly."""
    api_key = _resolve_gemini_api_key()
    if not api_key:
        raise ExtractionError("GEMINI_API_KEY is not configured.")

    cleaned_text = (tender_text or "").strip()
    if not cleaned_text:
        raise ExtractionError("Tender text is empty.")

    if len(cleaned_text) > MAX_TENDER_TEXT_CHARS:
        cleaned_text = cleaned_text[:MAX_TENDER_TEXT_CHARS]

    return await _extract_tender_requirements_impl(
        cleaned_text,
        available_taxonomy,
        api_key,
    )


async def analyze_tender_gaps(
    tender_text: str,
    company_profile: dict[str, Any] | None = None,
) -> DynamicTenderRequirements:
    _ = company_profile
    return await extract_tender_requirements(tender_text, [])


def validate_with_dummy_tender_text() -> ExtractedTenderRequirements:
    dummy_tender_text = """
Tender requirements:
- Bidder must hold ISO 9001 and ISO 27001 certificates.
- Minimum annual turnover: 5,000,000,000 UZS.
- Required licenses: Construction License Category A, Electrical Installation License.
- Submission deadline: 2026-03-15 18:00 Tashkent time.
"""
    return extract_tender_requirements_sync(dummy_tender_text, [])
