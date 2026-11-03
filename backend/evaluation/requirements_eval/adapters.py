"""Turn stored pipeline outputs into a common prediction shape.

Stored outputs live in a directory with one JSON file per document, named
``<doc_id>.json``. Three shapes are accepted:

1. Harness format (written by ``live``)::

       {"doc_id": "...", "pipeline": "pursuit", "model": "...",
        "items": [{"quote": "...", "obligation": "MANDATORY", "kind": "CORPORATE_REQUIREMENT"}]}

2. A list of pursuit-analyzer facts (``ExtractedFact`` / ``VerifiedFact.fact`` dumps)
   with ``original_quote``, ``kind`` and ``distinction``.

3. A list of compliance-extractor requirements (``TenderRequirement`` dumps) with
   ``exact_quote`` and ``category`` (DQ / NICE_TO_HAVE / COMPLIANT).

Only the quote is needed for extraction scoring. The obligation is mapped to the
gold vocabulary where the source pipeline has an equivalent, and left ``None``
otherwise; obligation agreement is then reported only over items that have one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Prediction:
    quote: str
    obligation: str | None = None
    kind: str | None = None


# Pursuit analyzer: ExtractedFact.distinction is MANDATORY / SCORED / INFORMATIONAL;
# position criteria carry MANDATORY / PREFERRED / DESIRED.
_PURSUIT_OBLIGATION = {
    "MANDATORY": "MANDATORY", "SCORED": "SCORED", "INFORMATIONAL": "INFORMATIONAL",
    "PREFERRED": "PREFERRED", "DESIRED": "PREFERRED",
}
# Compliance extractor: DQ is a disqualification risk; NICE_TO_HAVE covers preferences
# and scoring; COMPLIANT is verified non-risk evidence.
_COMPLIANCE_OBLIGATION = {"DQ": "MANDATORY", "NICE_TO_HAVE": "PREFERRED_OR_SCORED", "COMPLIANT": "INFORMATIONAL"}


def from_record(record: dict) -> Prediction | None:
    if "quote" in record:
        return Prediction(str(record["quote"]), record.get("obligation"), record.get("kind"))
    if "original_quote" in record:
        distinction = record.get("distinction")
        return Prediction(str(record["original_quote"]), _PURSUIT_OBLIGATION.get(str(distinction)), record.get("kind"))
    if "fact" in record and isinstance(record["fact"], dict):
        return from_record(record["fact"])
    if "exact_quote" in record:
        category = str(record.get("category") or record.get("requirement_type") or "")
        return Prediction(str(record["exact_quote"]), _COMPLIANCE_OBLIGATION.get(category), "COMPLIANCE_REQUIREMENT")
    return None


def load_predictions(path: Path) -> tuple[list[Prediction], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    meta: dict = {}
    records = payload
    if isinstance(payload, dict):
        meta = {key: value for key, value in payload.items() if key != "items"}
        records = payload.get("items", [])
    predictions = [prediction for record in records if (prediction := from_record(record)) is not None]
    meta["unparsed_records"] = len(records) - len(predictions)
    return predictions, meta


def load_run(directory: Path) -> dict[str, tuple[list[Prediction], dict]]:
    """All stored outputs in ``directory`` keyed by document id (file stem); ``run.json`` is run metadata."""
    return {
        path.stem: load_predictions(path) for path in sorted(Path(directory).glob("*.json")) if path.name != "run.json"
    }
