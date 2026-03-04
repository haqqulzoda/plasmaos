from __future__ import annotations

import asyncio
import json
import logging
import os
from uuid import UUID

from google import genai
from google.genai import errors
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.models.all_models import Tender
from app.models.company import CompanyProfile

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash-lite" 
MAX_DESCRIPTION_CHARS = 4_000


class TenderRecommendationItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tender_id: str
    match_score: int = Field(ge=0, le=100)
    strategic_rationale: str = Field(min_length=1)


TENDER_RECOMMENDATION_LIST_ADAPTER = TypeAdapter(list[TenderRecommendationItem])
TENDER_RECOMMENDATION_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "tender_id": {"type": "STRING"},
            "match_score": {"type": "INTEGER", "minimum": 0, "maximum": 100},
            "strategic_rationale": {"type": "STRING", "minLength": "1"},
        },
        "required": ["tender_id", "match_score", "strategic_rationale"],
    },
}


def _resolve_gemini_api_key() -> str | None:
    from app.core.config import settings

    return (
        settings.GEMINI_API_KEY
        or settings.GOOGLE_API_KEY
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    )


def _build_company_profile_payload(profile: CompanyProfile) -> dict[str, object]:
    return {
        "company_profile_id": str(profile.id),
        "company_name": profile.company_name,
        "director_name": profile.director_name,
        "address": profile.address,
        "phone_contact": profile.phone_contact,
        "bank_name": profile.bank_name,
        "mfo": profile.mfo,
        "account_number": profile.account_number,
        "inn": profile.inn,
        "licenses": [
            {
                "license_name": license_item.license_name,
                "is_active": license_item.is_active,
            }
            for license_item in profile.licenses
        ],
        "certifications": [
            {
                "cert_type": cert.cert_type,
                "issue_date": cert.issue_date.isoformat(),
                "expiry_date": cert.expiry_date.isoformat(),
            }
            for cert in profile.certifications
        ],
        "financial_history": [
            {
                "year": item.year,
                "turnover_uzs": item.turnover_uzs,
            }
            for item in profile.financial_history
        ],
    }


def _build_tender_payload(tender: Tender) -> dict[str, object]:
    description = (tender.description or "").strip()
    return {
        "tender_id": str(tender.id),
        "title": tender.title,
        "description": description[:MAX_DESCRIPTION_CHARS],
        "budget": tender.budget,
    }


def _build_prompt(tenders: list[Tender], profile: CompanyProfile) -> str:
    payload = {
        "company_profile": _build_company_profile_payload(profile),
        "tenders": [_build_tender_payload(tender) for tender in tenders],
    }
    payload_json = json.dumps(payload, ensure_ascii=False)

    return f"""
You are The Hunter Agent for procurement opportunities.
Evaluate each tender against the company profile and score strategic fit from 0-100.

Output strict JSON only with this exact schema:
[
  {{
    "tender_id": "uuid",
    "match_score": 0,
    "strategic_rationale": "short rationale"
  }}
]

Rules:
- Include one recommendation item for every tender in the input.
- Do not add extra keys.
- match_score must be an integer between 0 and 100.
- strategic_rationale must be concise and specific.

Input payload:
{payload_json}
""".strip()


def _parse_recommendation_response(
    response: object,
    expected_tender_ids: set[str],
) -> list[dict]:
    parsed_payload = getattr(response, "parsed", None)
    if parsed_payload is not None:
        try:
            parsed_items = TENDER_RECOMMENDATION_LIST_ADAPTER.validate_python(
                parsed_payload,
                strict=False,
            )
        except ValidationError as exc:
            raise RuntimeError("Hunter Agent response schema validation failed.") from exc
    else:
        response_text = (getattr(response, "text", "") or "").strip()
        if not response_text:
            raise RuntimeError("Hunter Agent returned empty response.")
        try:
            parsed_items = TENDER_RECOMMENDATION_LIST_ADAPTER.validate_json(
                response_text,
                strict=False,
            )
        except ValidationError as exc:
            raise RuntimeError("Hunter Agent response schema validation failed.") from exc

    filtered: list[dict] = []
    seen_tender_ids: set[str] = set()

    for item in parsed_items:
        tender_id_text = item.tender_id.strip()
        if tender_id_text not in expected_tender_ids:
            continue
        if tender_id_text in seen_tender_ids:
            continue
        try:
            UUID(tender_id_text)
        except ValueError:
            continue

        seen_tender_ids.add(tender_id_text)
        filtered.append(
            {
                "tender_id": tender_id_text,
                "match_score": int(item.match_score),
                "strategic_rationale": item.strategic_rationale.strip(),
            }
        )

    return filtered


def _log_hunter_retry_warning(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    sleep_seconds = retry_state.next_action.sleep if retry_state.next_action else 0.0
    logger.warning(
        "Hunter Agent Gemini API Error. Retrying attempt %s/4 in %.1fs: %s",
        retry_state.attempt_number + 1,
        sleep_seconds,
        exc,
    )


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(errors.APIError),
    before_sleep=_log_hunter_retry_warning,
    reraise=True
)
def _evaluate_tenders_batch_sync(
    tenders: list[Tender],
    profile: CompanyProfile,
    api_key: str,
) -> list[dict]:
    if not tenders:
        return []

    client = genai.Client(api_key=api_key)
    prompt = _build_prompt(tenders=tenders, profile=profile)
    expected_tender_ids = {str(tender.id) for tender in tenders}
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=TENDER_RECOMMENDATION_RESPONSE_SCHEMA,
            temperature=0.1,
        ),
    )

    return _parse_recommendation_response(
        response=response,
        expected_tender_ids=expected_tender_ids,
    )


async def evaluate_tenders_batch(tenders: list[Tender], profile: CompanyProfile) -> list[dict]:
    if not tenders:
        return []

    api_key = _resolve_gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    return await asyncio.to_thread(
        _evaluate_tenders_batch_sync,
        tenders,
        profile,
        api_key,
    )
