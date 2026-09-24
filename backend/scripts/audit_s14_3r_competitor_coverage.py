"""Deterministic, non-production Sprint 14.3R competitor coverage sample.

Run with PYTHONPATH=backend python3 backend/scripts/audit_s14_3r_competitor_coverage.py.
This is a fixture diagnostic, not a measurement of the deployed Tender corpus.
"""

from __future__ import annotations

import json
from collections import Counter

from app.api.endpoints import tenders
from seed_tenders import MOCK_TENDERS
from test_s14_3r_competitor_intelligence import builder, history, tender


def percentage(numerator: int, denominator: int) -> float | None:
    return round(100 * numerator / denominator, 1) if denominator else None


def main() -> None:
    sources = ("world_bank", "uzex", "giz", "adb", "ebrd")
    rows: list[dict] = []
    observed_candidates = rejected_generic = rejected_unsupported = 0
    qualified = []
    for source in sources:
        cases = (
            ("linked_award", [history(source)]),
            ("unrelated_award", [history(source, buyer="Unrelated Buyer", country="Tanzania")]),
            ("no_evidence", []),
        )
        for label, related in cases:
            result = builder(tender(source), related)
            items = [item for group in result.groups for item in group.competitors]
            qualified.extend(items)
            rows.append({"source": source, "case": label, "state": result.state, "qualified": len(items)})
            if related:
                observed_candidates += 1
                if label == "unrelated_award" and source in tenders.COMPETITOR_VERIFIED_METADATA_SOURCES:
                    rejected_generic += int(not items)
                if source not in tenders.COMPETITOR_VERIFIED_METADATA_SOURCES:
                    rejected_unsupported += int(not items)

    per_source = {}
    for source in sources:
        source_rows = [row for row in rows if row["source"] == source]
        counts = Counter(row["state"] for row in source_rows)
        per_source[source] = {
            "tenders": len(source_rows),
            "available_percent": percentage(counts["AVAILABLE"], len(source_rows)),
            "insufficient_evidence_percent": percentage(counts["INSUFFICIENT_EVIDENCE"], len(source_rows)),
            "unavailable_percent": percentage(counts["UNAVAILABLE"], len(source_rows)),
        }
    counts = Counter(row["state"] for row in rows)
    seed_states = Counter(
        builder(tender(
            "uzex", external_id=item["external_id"], source_url=item["source_url"],
            title=item["title"], description=item["description"],
            country=None, sector=None, buyer=None, procurement_category=None,
            procurement_method=None, category=None, project_id=None,
            source_metadata_json={},
        )).state
        for item in MOCK_TENDERS
    )
    output = {
        "basis": "15 deliberately constructed, deterministic local fixtures; not live-corpus coverage",
        "running_app_tender_corpus": "not_accessed; release uses isolated disposable PostgreSQL",
        "existing_repository_seed_corpus": {
            "basis": "backend/seed_tenders.py MOCK_TENDERS; no public bid/award evidence or populated competitor cache",
            "source": "uzex", "tenders": len(MOCK_TENDERS),
            "available_percent": percentage(seed_states["AVAILABLE"], len(MOCK_TENDERS)),
            "insufficient_evidence_percent": percentage(seed_states["INSUFFICIENT_EVIDENCE"], len(MOCK_TENDERS)),
            "unavailable_percent": percentage(seed_states["UNAVAILABLE"], len(MOCK_TENDERS)),
        },
        "tenders": len(rows),
        "available_percent": percentage(counts["AVAILABLE"], len(rows)),
        "insufficient_evidence_percent": percentage(counts["INSUFFICIENT_EVIDENCE"], len(rows)),
        "unavailable_percent": percentage(counts["UNAVAILABLE"], len(rows)),
        "average_qualified_competitors_per_tender": round(len(qualified) / len(rows), 2),
        "observed_historical_candidates": observed_candidates,
        "rejected_as_unrelated_or_too_generic_percent": percentage(rejected_generic, observed_candidates),
        "rejected_due_to_unverified_source_authority_percent": percentage(rejected_unsupported, observed_candidates),
        "qualified_with_valid_evidence_url_percent": percentage(sum(bool(tenders._safe_competitor_evidence_url(item.evidence_source, item.source)) for item in qualified), len(qualified)),
        "qualified_with_meaningful_rationale_percent": percentage(sum(bool(item.relevance_tier and item.related_tender_title and item.related_tender_title in item.reason) for item in qualified), len(qualified)),
        "by_source": per_source,
        "cases": rows,
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
