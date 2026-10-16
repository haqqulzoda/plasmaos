#!/usr/bin/env python3
"""P1: build the Explore view's guided demo analysis from one completed analysis run.

    python scripts/export_explore_demo.py --run-id <analysis run uuid> --out app/services/explore_demo_analysis.json

The run must belong to a demo-seed organization ("Demo Consulting LLC — ..." with the seed's
profile marker): its firm, references and experts are invented, and the notice is public, so
the JSON can be shown to every explore organization. The script refuses any other run. It
reads only: the public notice fields, the run's requirements and gaps, the shortlisted experts
(names of the fictional demo experts) and the first paragraphs of the newest EOI draft.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from uuid import UUID

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

STATUS = {"SUPPORTED": "MET", "PARTIAL": "PARTIAL"}  # everything else open is a gap for the demo
SKIPPED = {"NOT_APPLICABLE", "LATER_STAGE_OBLIGATION"}
SOURCES = {"world_bank": "World Bank", "adb": "ADB", "ebrd": "EBRD", "giz": "GIZ", "uzex": "UzEx"}


async def build(run_id: UUID, *, max_items: int = 12) -> dict:
    from app.db.session import AsyncSessionLocal, engine
    from app.models.all_models import Tender
    from app.models.candidate_retrieval import CandidateMatch, CandidateSearchRun, Expert
    from app.models.company import CompanyProfile
    from app.models.eoi import EoiDraft
    from app.models.pursuit_analysis import AnalysisRun, PursuitGap, PursuitRequirement
    from app.models.tenancy import Organization, OrganizationPursuit
    from app.services.eoi_document import letter_paragraphs
    from scripts.demo.seed_demo import PROFILE_MARKER

    try:
        async with AsyncSessionLocal() as db:
            run = await db.get(AnalysisRun, run_id)
            if run is None or run.status != "COMPLETED":
                raise SystemExit("REFUSED: no completed analysis run with that id")
            # Column selects only: the script also runs against a database one schema behind.
            profile_id = await db.scalar(select(Organization.legacy_company_profile_id).where(Organization.id == run.organization_id))
            profile = await db.get(CompanyProfile, profile_id)
            if not (profile.notes or "").startswith(PROFILE_MARKER):
                raise SystemExit("REFUSED: the run's organization is not a demo-seed organization")
            pursuit = await db.get(OrganizationPursuit, run.pursuit_id)
            tender = await db.get(Tender, pursuit.source_tender_id) if pursuit.source_tender_id else None
            requirements = (await db.scalars(select(PursuitRequirement).where(PursuitRequirement.analysis_run_id == run.id)
                                             .order_by(PursuitRequirement.created_at, PursuitRequirement.id))).all()
            gaps = (await db.scalars(select(PursuitGap).where(PursuitGap.analysis_run_id == run.id)
                                     .order_by(PursuitGap.created_at, PursuitGap.id))).all()
            matches = (await db.execute(
                select(Expert.display_name, CandidateMatch.proposed_contribution, CandidateMatch.qualification_state)
                .join(CandidateSearchRun, CandidateSearchRun.id == CandidateMatch.candidate_search_run_id)
                .join(Expert, Expert.id == CandidateMatch.expert_id)
                .where(CandidateSearchRun.analysis_run_id == run.id)
                .order_by(CandidateMatch.qualification_state, Expert.display_name)
            )).all()
            eoi = await db.scalar(select(EoiDraft).where(EoiDraft.pursuit_id == pursuit.id)
                                  .order_by(EoiDraft.created_at.desc()).limit(1))
    finally:
        await engine.dispose()

    shown = [r for r in requirements if r.coverage_state not in SKIPPED]
    req_items = [{"text": r.normalized_requirement, "category": r.category,
                  "status": STATUS.get(r.coverage_state, "GAP"),
                  "evidence": (r.generated_interpretation or "")[:400] or None} for r in shown][:max_items]
    gap_items = [{"text": g.missing_contribution, "action": (g.rationale or "")[:400] or None}
                 for g in gaps if g.coverage_state not in SKIPPED][:max_items]
    seen, team = set(), []
    for name, contribution, state in matches:
        if name in seen:
            continue
        seen.add(name)
        team.append({"name": name, "role": (contribution or "")[:160], "match": state.replace("_", " ").lower()})
    excerpt, status_label = None, None
    if eoi is not None:
        letter = letter_paragraphs(eoi.manifest)
        excerpt = "\n\n".join([letter["subject"], letter["salutation"], *letter["body"]])
        status_label = "Draft — not reviewed by your team"
    counts = {"MET": 0, "PARTIAL": 0, "GAP": 0}
    for item in (STATUS.get(r.coverage_state, "GAP") for r in shown):
        counts[item] += 1
    return {
        "label": "demo",
        "tender": {
            "title": tender.title if tender else "Uploaded notice",
            "client": getattr(tender, "buyer", None) or getattr(tender, "procuring_entity", None),
            "country": getattr(tender, "country", None),
            "source": SOURCES.get(getattr(tender, "source_system", ""), getattr(tender, "source_system", None)),
            "reference": getattr(tender, "external_id", None),
            "notice_type": (tender.source_metadata_json or {}).get("notice_type") if tender and isinstance(tender.source_metadata_json, dict) else None,
            "deadline": tender.deadline.date().isoformat() if tender and tender.deadline else None,
            "source_url": getattr(tender, "source_url", None),
        },
        "firm": {"name": "Demo Consulting LLC",
                 "note": "Demo Consulting LLC is fictional: its references, partners and experts are invented for this walkthrough."},
        "metrics": {"requirements": len(shown), "met": counts["MET"], "partial": counts["PARTIAL"], "gaps": counts["GAP"]},
        "steps": {"requirements": req_items, "gaps": gap_items, "team": team[:8],
                  **({"eoi": {"excerpt": excerpt, "status_label": status_label}} if excerpt else {})},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True, type=UUID)
    parser.add_argument("--out", type=Path, default=BACKEND_DIR / "app" / "services" / "explore_demo_analysis.json")
    parser.add_argument("--max-items", type=int, default=12)
    args = parser.parse_args(argv)
    data = asyncio.run(build(args.run_id, max_items=args.max_items))
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({data['metrics']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
