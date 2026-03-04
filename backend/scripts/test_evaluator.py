from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.evaluator import (
    DynamicComplianceResult,
    TaxNodeInfo,
    evaluate_compliance,
)


def main() -> None:
    # Simulate taxonomy nodes the AI mapped from the tender
    mapped_uuids = [
        "aaaa-1111-0000-0000",  # ISO 9001 — user HAS this
        "bbbb-2222-0000-0000",  # ISO 27001 — user DOES NOT have this
        "cccc-3333-0000-0000",  # Construction License — user HAS this
        "dddd-4444-0000-0000",  # OSHA Compliance — user DOES NOT have this
    ]

    unmapped = [
        "Must submit a letter of intent within 5 business days",
        "All workers must hold an SRT card",
    ]

    # UUIDs the user holds via CompanyCredential
    credential_uuids = {
        "aaaa-1111-0000-0000",  # ISO 9001
        "cccc-3333-0000-0000",  # Construction License
        "eeee-5555-0000-0000",  # Extra credential, not in tender
    }

    # Full taxonomy lookup
    taxonomy_lookup = {
        "aaaa-1111-0000-0000": TaxNodeInfo(name="ISO 9001", impact_weight=30, is_fatal=False),
        "bbbb-2222-0000-0000": TaxNodeInfo(name="ISO 27001", impact_weight=50, is_fatal=True),
        "cccc-3333-0000-0000": TaxNodeInfo(name="Construction License A", impact_weight=40, is_fatal=True),
        "dddd-4444-0000-0000": TaxNodeInfo(name="OSHA Compliance", impact_weight=20, is_fatal=False),
        "eeee-5555-0000-0000": TaxNodeInfo(name="Fire Safety Cert", impact_weight=15, is_fatal=False),
    }

    result: DynamicComplianceResult = evaluate_compliance(
        mapped_requirement_uuids=mapped_uuids,
        unmapped_custom_requirements=unmapped,
        credential_uuids=credential_uuids,
        taxonomy_lookup=taxonomy_lookup,
    )

    print(result.model_dump_json(indent=2))
    print()
    print(f"is_compliant: {result.is_compliant}")
    print(f"met:          {[r.name for r in result.met_requirements]}")
    print(f"missing:      {[r.name for r in result.missing_requirements]}")
    print(f"unmapped:     {result.unmapped_requirements}")


if __name__ == "__main__":
    main()
