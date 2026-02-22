from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.core.parser import process_tender_document

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

PREFERRED_SAMPLE_NAMES: tuple[str, ...] = ("sample_tender.rar", "sample_tender.zip")
FALLBACK_SAMPLE_NAMES: tuple[str, ...] = ("sample-tender.rar", "sample-tender.zip")


def find_sample_archive() -> Path | None:
    search_roots = (Path.cwd(), Path.cwd().parent)

    for root in search_roots:
        for name in PREFERRED_SAMPLE_NAMES:
            candidate = root / name
            if candidate.exists() and candidate.is_file():
                return candidate

    for root in search_roots:
        for name in FALLBACK_SAMPLE_NAMES:
            candidate = root / name
            if candidate.exists() and candidate.is_file():
                return candidate

    return None


async def main() -> None:
    sample_archive = find_sample_archive()
    if sample_archive is None:
        print(
            "Sample archive not found. Expected one of: "
            f"{', '.join(PREFERRED_SAMPLE_NAMES)}"
        )
        return

    logger.info("Parsing archive: %s", sample_archive)
    extracted_text = await process_tender_document(sample_archive)

    preview = extracted_text[:1000]
    print("\n===== PARSED TEXT PREVIEW (first 1000 chars) =====\n")
    print(preview if preview else "[No text extracted]")
    print("\n===== END PREVIEW =====")


if __name__ == "__main__":
    asyncio.run(main())
