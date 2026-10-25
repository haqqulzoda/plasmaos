#!/usr/bin/env python3
"""Deploy 5 data step: pilots end like bought pilots (terms §7: a Pilot ends after three months).

    python scripts/deploy5_pilot_end_dates.py --target production                     # list only (default)
    python scripts/deploy5_pilot_end_dates.py --target production --apply --confirm PILOT_END_DATES

Run inside a one-off backend container (scripts/compose-release.sh run --rm --no-deps -T backend ...).

Lists every organization on the Pilot plan: whether scripts/pilot_setup.py created it (its company profile notes
start with "[plasma-pilot-setup]"), its start and end dates, the end date it gets (start + 3 months) and what
happens. ``--apply`` sets that end date on the pilot_setup.py pilots only (audited as ORGANIZATION_ACCESS_CHANGED,
actor "deploy5-pilot-end-dates"); other pilots are listed for the owner to decide in /admin/organizations.

From Deploy 5 the hourly billing job moves every Pilot whose end date has come to Explore, so the list also
flags pilots that would end at the first run ("ends_at_first_run"): extend those first if that is not intended.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
import json
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

CONFIRMATION = "PILOT_END_DATES"
PROFILE_MARKER = "[plasma-pilot-setup]"
ACTOR_LABEL = "deploy5-pilot-end-dates"
TARGET_ENVIRONMENTS = {"local": {"development", "test"}, "production": {"production"}}


def plan_rows(organizations_with_profiles, today: date) -> list[dict]:
    """What the step would do for each pilot organization (pure: tested without a database)."""
    from app.services.billing import add_months

    rows = []
    for organization, profile in organizations_with_profiles:
        ours = bool(profile is not None and (profile.notes or "").startswith(PROFILE_MARKER))
        start, end = organization.plan_started_on, organization.plan_ends_on
        proposed = add_months(start, 3) if start else None
        if not ours:
            action = "listed_only"
        elif start is None:
            action = "no_start_date"
        elif end == proposed:
            action = "keep"
        else:
            action = "set"
        final_end = proposed if action == "set" else end
        rows.append({
            "organization_id": str(organization.id), "name": organization.display_name,
            "pilot_setup": ours, "plan_started_on": start.isoformat() if start else None,
            "plan_ends_on": end.isoformat() if end else None,
            "proposed_ends_on": proposed.isoformat() if proposed and ours else None, "action": action,
            "ends_at_first_run": bool(final_end and final_end <= today),
        })
    return rows


async def run(target: str, apply: bool, today: date | None = None) -> list[dict]:
    from app.core.config import settings
    from app.db.session import AsyncSessionLocal, engine
    from app.models.company import CompanyProfile
    from app.models.tenancy import Organization
    from app.services.billing import billing_today
    from app.services.organization_access import set_organization_access

    if settings.ENVIRONMENT not in TARGET_ENVIRONMENTS[target]:
        raise SystemExit(f"REFUSED: --target {target} but ENVIRONMENT={settings.ENVIRONMENT}")
    today = today or billing_today()
    try:
        async with AsyncSessionLocal() as db:
            pairs = (await db.execute(
                select(Organization, CompanyProfile)
                .outerjoin(CompanyProfile, CompanyProfile.id == Organization.legacy_company_profile_id)
                .where(Organization.plan == "pilot").order_by(Organization.plan_started_on, Organization.id)
            )).all()
            rows = plan_rows(pairs, today)
            if apply:
                by_id = {str(organization.id): organization for organization, _ in pairs}
                for row in rows:
                    if row["action"] != "set":
                        continue
                    organization = by_id[row["organization_id"]]
                    await set_organization_access(  # the state stays (a disabled pilot stays disabled)
                        db, organization=organization, state=organization.access_state, plan="pilot",
                        plan_ends_on=date.fromisoformat(row["proposed_ends_on"]), actor_user=None,
                        actor_label=ACTOR_LABEL, reason="Deploy 5: pilots end three months after their start (terms §7).",
                    )
                    row["applied"] = True
                await db.commit()
            return rows
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", choices=sorted(TARGET_ENVIRONMENTS), required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args()
    if args.apply and args.confirm != CONFIRMATION:
        print(f"REFUSED: --apply needs --confirm {CONFIRMATION}")
        return 2
    rows = asyncio.run(run(args.target, args.apply))
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    summary = {action: sum(1 for row in rows if row["action"] == action)
               for action in ("set", "keep", "no_start_date", "listed_only")}
    summary["ends_at_first_run"] = sum(1 for row in rows if row["ends_at_first_run"])
    summary["applied"] = sum(1 for row in rows if row.get("applied"))
    print("SUMMARY " + json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
