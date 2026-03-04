"""Standalone test for LLM JSON extraction -- bypasses FastAPI and Postgres."""

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.ai_analyzer import (
    ExtractionError,
    ExtractedTenderRequirements,
    _build_extraction_prompt,
    _resolve_gemini_api_key,
    MODEL_NAME,
)
from google import genai
from google.genai import types

TEST_PAYLOAD = (
    "Техническое задание на закупку серверного оборудования. "
    "Требования к участникам: Участник конкурса должен в обязательном порядке "
    "предоставить действующие сертификаты соответствия стандартам ISO 9001 и ISO 27001. "
    "Финансовые требования: Минимальный среднегодовой оборот компании за последние "
    "3 года должен составлять не менее 5000000000 сум. "
    "Дополнительные требования: Требуется действующая лицензия на проектирование "
    "и эксплуатацию криптографических систем защиты информации. "
    "Срок подачи предложений: 15 марта 2026 года."
)


def main() -> None:
    print("=" * 60)
    print("TEST: extract_tender_requirements (diagnostic)")
    print("=" * 60)

    api_key = _resolve_gemini_api_key()
    if not api_key:
        print("FATAL: No Gemini API key found.")
        sys.exit(1)
    print(f"API key: ...{api_key[-6:]}")
    print(f"Model:   {MODEL_NAME}")
    print(f"Payload: {len(TEST_PAYLOAD)} chars\n")

    prompt = _build_extraction_prompt(TEST_PAYLOAD)
    client = genai.Client(api_key=api_key)

    print("Sending request to Gemini...\n")
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExtractedTenderRequirements,
            temperature=0.0,
        ),
    )

    # -- Diagnostic: dump raw response --
    raw_text = getattr(response, "text", None)
    parsed = getattr(response, "parsed", None)

    print("--- Raw response.text ---")
    print(raw_text or "(None)")
    print()

    print("--- response.parsed ---")
    print(f"Type: {type(parsed).__name__}")
    print(f"Value: {parsed}")
    print()

    # -- Try validation (mirrors production code) --
    print("--- Pydantic validation ---")
    try:
        if parsed is not None:
            result = ExtractedTenderRequirements.model_validate(parsed, strict=False)
        elif raw_text:
            result = ExtractedTenderRequirements.model_validate_json(raw_text, strict=False)
        else:
            print("FAIL: No parsed or text response.")
            sys.exit(1)

        print("[OK] Validation passed\n")
        print(result.model_dump_json(indent=2))
    except Exception as exc:
        print(f"[FAIL]: {exc}\n")

        # -- Retry with raw JSON to show what Gemini returned --
        print("--- Diagnostic: raw JSON field types ---")
        try:
            if raw_text:
                data = json.loads(raw_text)
                for k, v in data.items():
                    print(f"  {k}: {type(v).__name__} = {v!r}")
        except Exception as exc2:
            print(f"  Could not parse raw text: {exc2}")
        sys.exit(1)


if __name__ == "__main__":
    main()
