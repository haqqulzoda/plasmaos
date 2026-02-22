from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from app.core.ai_analyzer import analyze_tender_gaps
from app.core.parser import process_tender_document

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

PREFERRED_ARCHIVES: tuple[str, ...] = ("sample_tender.rar", "sample_tender.zip")
FALLBACK_ARCHIVES: tuple[str, ...] = ("sample-tender.rar", "sample-tender.zip")


def _find_sample_archive() -> Path | None:
    search_roots = (Path.cwd(), Path.cwd().parent)

    for root in search_roots:
        for file_name in PREFERRED_ARCHIVES:
            candidate = root / file_name
            if candidate.is_file():
                return candidate

    for root in search_roots:
        for file_name in FALLBACK_ARCHIVES:
            candidate = root / file_name
            if candidate.is_file():
                return candidate

    return None


async def main() -> None:
    company_profile: dict[str, Any] = {
        "name": "Test LLC",
        "licenses": ["Construction License A"],
        "bank_guarantee_available": False,
        "regions_of_operation": ["Tashkent", "Samarkand"],
        "max_delivery_days": 30,
        "past_projects": ["School roof repair", "Hospital renovation"],
    }

    archive_path = _find_sample_archive()
    if archive_path is None:
        print(
            "Sample archive not found. Expected one of: "
            f"{', '.join(PREFERRED_ARCHIVES)}"
        )
        return

    logger.info("Extracting tender text from %s", archive_path)
    tender_text = await process_tender_document(archive_path)
    if not tender_text.strip():
        print("No text extracted from archive; cannot run gap analysis.")
        return

    logger.info("Running gap analysis with Gemini")
    analysis = await analyze_tender_gaps(
        tender_text=tender_text,
        company_profile=company_profile,
    )

    print("\n===== GAP ANALYSIS RESULT =====\n")
    print(json.dumps(analysis.model_dump(), indent=2, ensure_ascii=False))
    print("\n===== END RESULT =====")


if __name__ == "__main__":
    asyncio.run(main())
