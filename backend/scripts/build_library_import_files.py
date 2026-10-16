#!/usr/bin/env python3
"""P1: write the library import template and a filled sample (the fictional demo firm).

    python scripts/build_library_import_files.py --out-dir ../docs/ops/p1

Writes plasma-library-import-template.xlsx (empty sheets, as served by
GET /candidates/library-import/template), the three CSV templates, and
plasma-library-import-sample.xlsx: the D3-04 demo firm's own references, partner firms'
references and twelve experts with their assignments, all invented.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

ROLE = {"LEAD": "Lead", "JV_MEMBER": "JV member", "CONSORTIUM_MEMBER": "Consortium member", "SUBCONSULTANT": "Subconsultant",
        "SUBCONTRACTOR": "Subcontractor", "OTHER": "Other", "UNKNOWN": "Other"}
BASIS = {"FIRM_SHARE": "Firm share", "CONSORTIUM_TOTAL": "Consortium total", "CONTRACT_TOTAL": "Contract total", "UNKNOWN": ""}
STATUS = {"COMPLETED": "Completed", "ONGOING": "Ongoing", "NOT_COMPLETED": "Not completed", "UNKNOWN": "Unknown"}


def _reference_row(firm: str | None, ref: dict) -> list:
    return [
        firm or "", ref["project_name"], ref.get("client_name") or "", ref.get("country") or "", ref.get("service") or "",
        ref.get("sector") or "", ROLE[ref["role"]],
        int(ref["contract_value"]) if ref.get("contract_value") is not None else "", ref.get("contract_currency") or "",
        BASIS[ref.get("value_basis") or "UNKNOWN"],
        int(ref["contract_share_percent"]) if ref.get("contract_share_percent") is not None else "",
        ref["start_date"].isoformat() if ref.get("start_date") else "",
        ref["completion_date"].isoformat() if ref.get("completion_date") else "",
        STATUS[ref.get("completion_state") or "UNKNOWN"], ref.get("relevant_scope") or "",
    ]


def sample_rows() -> dict[str, list[list]]:
    from scripts.demo import demo_data as data

    references = [_reference_row(None, ref) for ref in data.OWN_REFERENCES]
    for partner in data.PARTNERS:
        references += [_reference_row(partner["display_name"], ref) for ref in partner["references"]]
    experts, assignments = [], []
    for expert in data.EXPERTS:
        cv = expert["cv"]
        title = cv["qualifications"][0]["title"] if cv["qualifications"] else ""
        years = cv["qualifications"][0].get("years_experience") if cv["qualifications"] else ""
        experts.append([
            expert["display_name"], title, years, "; ".join(item["degree"] for item in cv["education"]), "",
            "; ".join(s for s in expert["specializations"] if s != title), "; ".join(expert["languages"]), "", "",
        ])
        for item in cv["assignments"]:
            assignments.append([expert["display_name"], item["role"], item["project"], "", item.get("country") or "",
                                item.get("start") or "", item.get("end") or "", ""])
    return {"references": references, "experts": experts, "assignments": assignments}


def main(argv: list[str] | None = None) -> int:
    from app.services import library_import

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "plasma-library-import-template.xlsx").write_bytes(library_import.build_template_xlsx())
    for kind in library_import.KINDS:
        (args.out_dir / f"plasma-{kind}-template.csv").write_bytes(library_import.build_template_csv(kind))
    rows = sample_rows()
    (args.out_dir / "plasma-library-import-sample.xlsx").write_bytes(library_import.build_template_xlsx(rows))
    print({kind: len(value) for kind, value in rows.items()}, "->", args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
