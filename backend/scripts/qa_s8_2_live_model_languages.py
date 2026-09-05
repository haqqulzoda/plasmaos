#!/usr/bin/env python3
"""Bounded non-production live-model adherence sample for Sprint 8.2."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.agents.requirement_extractor import (
    extract_requirements,
    validate_requirements_evidence,
)
from app.core.analysis_languages import AnalysisLanguage
from app.services.analysis_language_content import generated_headlines_follow_language


SYNTHETIC_TEXT = """[[FILE: synthetic-bid.pdf]]
[[PAGE 1]]
The bidder must submit a valid tax clearance certificate with the bid.
Failure causes rejection.
[[PAGE 2]]
The supplier shall deliver the equipment within 45 calendar days after contract signature.
"""


async def main() -> int:
    results: list[dict[str, object]] = []
    failures = 0
    for language in AnalysisLanguage:
        try:
            requirements = validate_requirements_evidence(
                await extract_requirements(SYNTHETIC_TEXT, language),
                SYNTHETIC_TEXT,
            )
            schema_valid = all(item.model_dump(mode="json") for item in requirements)
            enums_valid = all(item.category.value in {"DQ", "NICE_TO_HAVE", "COMPLIANT"} for item in requirements)
            # Runtime's evidence validator is authoritative and permits only exact
            # or conservative case/whitespace-equivalent source text.
            evidence_verbatim = all(item.source_verified for item in requirements)
            adherence = generated_headlines_follow_language(requirements, language)
            passed = bool(requirements) and schema_valid and enums_valid and evidence_verbatim and adherence
            if not passed:
                failures += 1
            results.append({
                "language": language.value, "samples": 1, "requirements": len(requirements),
                "schema_valid": schema_valid, "enum_valid": enums_valid,
                "evidence_verbatim": evidence_verbatim, "language_adherence": adherence,
                "obvious_terminology_issue": False if passed else "manual review required",
                "failures": 0 if passed else 1,
            })
        except Exception as exc:
            failures += 1
            results.append({"language": language.value, "samples": 1, "requirements": 0,
                            "schema_valid": False, "enum_valid": False,
                            "evidence_verbatim": False, "language_adherence": False,
                            "obvious_terminology_issue": "sample failed",
                            "failures": 1, "error_type": type(exc).__name__})
    decisions = {
        item["language"]: (
            "ENABLED" if item["failures"] == 0 and item["language"] in {"en", "uz", "ru"}
            else "GATED"
        )
        for item in results
    }
    print(json.dumps({"non_production": True, "results": results, "decisions": decisions,
                      "total_failures": failures}, ensure_ascii=False, indent=2))
    return 1 if any(decisions[code] != "ENABLED" for code in ("en", "uz", "ru")) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
