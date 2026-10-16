#!/usr/bin/env python3
"""P1 pilot setup: create a paying pilot organization "<Firm>", record its plan, invite its users.

    python scripts/pilot_setup.py --target production --firm "Acme Consulting LLC" \\
        --owner ceo@acme.uz --member bd@acme.uz --member analyst@acme.uz \\
        --start 2026-10-20 --success-criteria "Three EOIs submitted with Plasma by the end of the pilot." \\
        --dry-run                                         # the plan only, nothing written
    ... --confirm PILOT_SETUP [--send-invitations]        # write; e-mail the invitations (SMTP)

    python scripts/pilot_setup.py --target production --firm "Acme Consulting LLC" --list    # what exists

Run inside a one-off backend container (scripts/compose-release.sh run --rm --no-deps -T backend ...).

What it writes (all audited, nothing outside the new organization except one steward user):
- A real organization (never a "— Plasma preview", never the demo seed): an approved company
  profile named exactly --firm, state ``pilot``, plan start, plan end (--months, default 3, or
  --end) and the success criteria text. Admins see all of it on /admin/organizations.
- A per-organization steward user (reserved ``.invalid`` address, no Google subject: it can never
  sign in) who owns the company profile and is an OWNER, so the invitations have an inviter and
  the firm's first owner can be invited like everyone else.
- One e-mail invitation per --owner (role OWNER) and --member (role MEMBER). Each binds at that
  address's first sign-in, by Google or by an e-mail code. The invitation links are printed;
  with --send-invitations they are also e-mailed (needs SMTP_* and PUBLIC_APP_URL).

Re-running with the same --firm updates the plan and adds invitations for new addresses only
(an open invitation or an active member is left as it is). --resend re-sends open invitations.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any
import unicodedata

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

CONFIRMATION = "PILOT_SETUP"
PROFILE_MARKER = "[plasma-pilot-setup]"
STEWARD_DOMAIN = "plasma.invalid"
TARGET_ENVIRONMENTS = {"local": {"development", "test"}, "production": {"production"}}
RESERVED_NAME_PATTERNS = (re.compile(r"plasma preview", re.I), re.compile(r"^demo consulting llc", re.I))


class PilotSetupError(RuntimeError):
    """The setup cannot run safely; nothing was written."""


@dataclass
class Options:
    target: str
    firm: str
    owners: list[str] = field(default_factory=list)
    members: list[str] = field(default_factory=list)
    start: date | None = None
    end: date | None = None
    months: int = 3
    success_criteria: str | None = None
    country: str | None = None
    confirm: str = ""
    dry_run: bool = False
    send_invitations: bool = False
    resend: bool = False
    list_only: bool = False


def add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    for day in (start.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise PilotSetupError("cannot compute the plan end")


def slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return value[:40] or "firm"


def steward_email(firm: str, organization_hint: str) -> str:
    return f"pilot-steward+{slug(firm)}-{organization_hint}@{STEWARD_DOMAIN}"


def check_target(target: str, environment: str) -> None:
    allowed = TARGET_ENVIRONMENTS.get(target)
    if allowed is None:
        raise PilotSetupError("--target must be local or production")
    if environment not in allowed:
        raise PilotSetupError(f"--target {target} does not match this process's ENVIRONMENT={environment!r}")


def validate(options: Options) -> dict[str, Any]:
    from app.services.invitations import InvitationError, normalize_email

    firm = " ".join((options.firm or "").split())
    if len(firm) < 2 or len(firm) > 200:
        raise PilotSetupError("--firm must be 2 to 200 characters")
    if any(pattern.search(firm) for pattern in RESERVED_NAME_PATTERNS):
        raise PilotSetupError("--firm looks like a preview or demo name; pilots are real organizations")
    invitees: dict[str, str] = {}
    for role, emails in (("OWNER", options.owners), ("MEMBER", options.members)):
        for raw in emails:
            try:
                email = normalize_email(raw)
            except InvitationError:
                raise PilotSetupError(f"not a valid e-mail address: {raw!r}") from None
            if email.endswith("@" + STEWARD_DOMAIN):
                raise PilotSetupError(f"reserved address: {email}")
            if invitees.get(email) == "OWNER":
                continue
            invitees[email] = role
    if not options.list_only and not any(role == "OWNER" for role in invitees.values()):
        raise PilotSetupError("at least one --owner is required")
    start = options.start or datetime.now(timezone.utc).date()
    if options.months < 1 or options.months > 24:
        raise PilotSetupError("--months must be between 1 and 24")
    end = options.end or add_months(start, options.months)
    if end < start:
        raise PilotSetupError("--end is before --start")
    criteria = (options.success_criteria or "").strip() or None
    if criteria is not None and len(criteria) > 4000:
        raise PilotSetupError("--success-criteria is limited to 4000 characters")
    return {"firm": firm, "invitees": invitees, "start": start, "end": end, "criteria": criteria}


async def find_organization(db: AsyncSession, firm: str):
    from app.models.company import CompanyProfile
    from app.models.tenancy import Organization

    rows = (await db.execute(
        select(Organization, CompanyProfile)
        .join(CompanyProfile, CompanyProfile.id == Organization.legacy_company_profile_id)
        .where(func.lower(Organization.display_name) == firm.lower())
    )).all()
    ours = [(org, profile) for org, profile in rows if (profile.notes or "").startswith(PROFILE_MARKER)]
    if rows and not ours:
        raise PilotSetupError(f"an organization named {firm!r} exists and was not made by this script; refusing to touch it")
    return ours[0] if ours else (None, None)


async def describe(db: AsyncSession, organization) -> dict[str, Any]:
    from app.models.invitations import PendingInvitation
    from app.models.tenancy import Membership
    from app.models.user import User
    from app.models.base import MembershipState
    from app.services.invitations import invitation_status

    members = (await db.execute(
        select(User.email, Membership.role).join(Membership, Membership.user_id == User.id)
        .where(Membership.organization_id == organization.id, Membership.state == MembershipState.ACTIVE)
        .order_by(User.email)
    )).all()
    invitations = (await db.scalars(
        select(PendingInvitation).where(PendingInvitation.organization_id == organization.id)
        .order_by(PendingInvitation.created_at)
    )).all()
    return {
        "organization_id": str(organization.id),
        "name": organization.display_name,
        "access_state": organization.access_state,
        "plan_started_on": organization.plan_started_on.isoformat() if organization.plan_started_on else None,
        "plan_ends_on": organization.plan_ends_on.isoformat() if organization.plan_ends_on else None,
        "success_criteria": organization.success_criteria,
        "members": [{"email": email, "role": role.value} for email, role in members
                    if not email.endswith("@" + STEWARD_DOMAIN)],
        "invitations": [{"email": i.email, "role": i.role.value, "status": invitation_status(i),
                         "expires_at": i.expires_at.isoformat()} for i in invitations],
    }


async def _steward_membership(db: AsyncSession, organization_id):
    from app.models.base import MembershipRole, MembershipState
    from app.models.tenancy import Membership
    from app.models.user import User

    return await db.scalar(
        select(Membership).join(User, User.id == Membership.user_id).where(
            Membership.organization_id == organization_id, Membership.state == MembershipState.ACTIVE,
            Membership.role == MembershipRole.OWNER, User.email.like(f"pilot-steward+%@{STEWARD_DOMAIN}"),
        )
    )


async def run(sessions, options: Options) -> dict[str, Any]:
    from app.core.access import COMPANY_APPROVAL_APPROVED, COMPANY_PILOT_ACTIVE, PLATFORM_ROLE_PILOT_USER, USER_APPROVAL_APPROVED
    from app.core.config import settings
    from app.models.base import MembershipRole
    from app.models.company import CompanyProfile
    from app.models.invitations import PendingInvitation
    from app.models.user import User
    from app.services.admin_activity import (
        ACTION_COMPANY_APPROVED, ACTOR_SERVER_COMMAND, OUTCOME_SUCCESS, SOURCE_ADMIN_REPAIR_COMMAND,
        company_role_snapshot, record_admin_audit_event,
    )
    from app.services.email_notifications import queue_invitation_email
    from app.services.invitations import (
        InvitationConflictError, create_email_invitation, invite_path, invite_url, invitation_status,
        resend_email_invitation,
    )
    from app.services.organization_access import set_organization_access
    from app.services.organization_context import ensure_profile_organization

    check_target(options.target, settings.ENVIRONMENT)
    plan = validate(options)
    async with sessions() as db:
        organization, profile = await find_organization(db, plan["firm"])
        if options.list_only:
            if organization is None:
                return {"status": "NOT_FOUND", "firm": plan["firm"]}
            return {"status": "FOUND", **await describe(db, organization)}
        summary: dict[str, Any] = {
            "mode": "dry-run" if options.dry_run else "write",
            "firm": plan["firm"], "exists": organization is not None,
            "access_state": "pilot", "plan_started_on": plan["start"].isoformat(), "plan_ends_on": plan["end"].isoformat(),
            "success_criteria": plan["criteria"],
            "invitees": [{"email": email, "role": role} for email, role in plan["invitees"].items()],
        }
        if options.dry_run:
            return summary
        if options.confirm != CONFIRMATION:
            raise PilotSetupError(f"pass --confirm {CONFIRMATION} to write (or --dry-run)")

        if organization is None:
            hint = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            steward = User(
                google_id=f"plasma-pilot-steward:{slug(plan['firm'])}:{hint}:not-a-google-account",
                email=steward_email(plan["firm"], hint), name="Plasma (pilot setup)",
                platform_role=PLATFORM_ROLE_PILOT_USER, approval_status=USER_APPROVAL_APPROVED,
                approved_at=datetime.now(timezone.utc),
            )
            db.add(steward)
            await db.flush()
            provenance = {"pilot_setup": True, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            profile = CompanyProfile(
                user_id=steward.id, created_by_user_id=steward.id, company_name=plan["firm"],
                target_countries=[options.country] if options.country else None,
                notes=f"{PROFILE_MARKER} {json.dumps(provenance)}",
                approval_status=COMPANY_APPROVAL_APPROVED, pilot_status=COMPANY_PILOT_ACTIVE,
                approved_at=datetime.now(timezone.utc),
            )
            db.add(profile)
            await db.flush()
            await record_admin_audit_event(
                db, action=ACTION_COMPANY_APPROVED, outcome=OUTCOME_SUCCESS, source=SOURCE_ADMIN_REPAIR_COMMAND,
                actor_type=ACTOR_SERVER_COMMAND, actor_label="pilot-setup-command", target_user=steward,
                target_resource_type="COMPANY_PROFILE", target_resource_id=str(profile.id),
                reason="Pilot organization created by scripts/pilot_setup.py.",
                new_state=company_role_snapshot(company_approval_status=profile.approval_status, user=steward),
                metadata={"pilot_setup": True},
            )
            context = await ensure_profile_organization(db, profile=profile)
            organization = context.organization
            summary["created"] = True
        steward_membership = await _steward_membership(db, organization.id)
        if steward_membership is None:
            raise PilotSetupError("the organization has no steward OWNER; cannot invite")
        steward = await db.get(User, steward_membership.user_id)
        await set_organization_access(
            db, organization=organization, state="pilot", actor_user=None, actor_label="pilot-setup-command",
            reason="Pilot set up by scripts/pilot_setup.py.", plan_started_on=plan["start"], plan_ends_on=plan["end"],
            success_criteria=plan["criteria"],
        )

        results = []
        for email, role in plan["invitees"].items():
            try:
                issued = await create_email_invitation(
                    db, organization_id=organization.id, actor_membership_id=steward_membership.id,
                    email=email, role=MembershipRole(role),
                )
            except InvitationConflictError as conflict:
                entry: dict[str, Any] = {"email": email, "role": role, "result": conflict.code}
                if conflict.code == "ALREADY_INVITED" and options.resend:
                    open_invitation = await db.scalar(select(PendingInvitation).where(
                        PendingInvitation.organization_id == organization.id, PendingInvitation.email == email,
                        PendingInvitation.accepted_at.is_(None), PendingInvitation.revoked_at.is_(None)))
                    if open_invitation is not None and invitation_status(open_invitation) == "OPEN":
                        issued = await resend_email_invitation(
                            db, organization_id=organization.id, actor_membership_id=steward_membership.id,
                            invitation_id=open_invitation.id,
                        )
                        entry.update(result="RESENT", link=invite_url(issued.token) or invite_path(issued.token))
                        if options.send_invitations:
                            entry["email_delivery"] = await queue_invitation_email(
                                db, invitation=issued.invitation, token=issued.token, inviter=steward)
                results.append(entry)
                continue
            entry = {"email": email, "role": role, "result": "INVITED",
                     "link": invite_url(issued.token) or invite_path(issued.token),
                     "expires_at": issued.invitation.expires_at.isoformat()}
            if options.send_invitations:
                entry["email_delivery"] = await queue_invitation_email(
                    db, invitation=issued.invitation, token=issued.token, inviter=steward)
            results.append(entry)
        await db.commit()
        summary["invitations"] = results
        summary["organization"] = await describe(db, organization)
        return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", required=True, choices=sorted(TARGET_ENVIRONMENTS))
    parser.add_argument("--firm", required=True, help="Exact organization name, as the firm writes it.")
    parser.add_argument("--owner", action="append", default=[], metavar="EMAIL", help="Invite as OWNER (repeatable).")
    parser.add_argument("--member", action="append", default=[], metavar="EMAIL", help="Invite as MEMBER (repeatable).")
    parser.add_argument("--start", type=date.fromisoformat, default=None, metavar="YYYY-MM-DD", help="Plan start (default today, UTC).")
    parser.add_argument("--months", type=int, default=3, help="Plan length in months (default 3).")
    parser.add_argument("--end", type=date.fromisoformat, default=None, metavar="YYYY-MM-DD", help="Plan end (overrides --months).")
    criteria = parser.add_mutually_exclusive_group()
    criteria.add_argument("--success-criteria", default=None, help="Success criteria text (up to 4000 characters).")
    criteria.add_argument("--success-criteria-file", type=Path, default=None, help="Read the success criteria from a UTF-8 file.")
    parser.add_argument("--country", default=None, help="A target country for the company profile (e.g. Uzbekistan).")
    parser.add_argument("--send-invitations", action="store_true", help="Also e-mail the invitations (SMTP).")
    parser.add_argument("--resend", action="store_true", help="Re-send open invitations to the listed addresses.")
    parser.add_argument("--list", dest="list_only", action="store_true", help="Show the organization, plan and invitations.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan; write nothing.")
    parser.add_argument("--confirm", default="", help=f"Required for any write: {CONFIRMATION}")
    return parser


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    criteria = args.success_criteria
    if args.success_criteria_file is not None:
        criteria = args.success_criteria_file.read_text(encoding="utf-8")
    options = Options(
        target=args.target, firm=args.firm, owners=args.owner, members=args.member, start=args.start, end=args.end,
        months=args.months, success_criteria=criteria, country=args.country, confirm=args.confirm,
        dry_run=args.dry_run, send_invitations=args.send_invitations, resend=args.resend, list_only=args.list_only,
    )
    from app.db.session import AsyncSessionLocal, engine

    try:
        result = await run(AsyncSessionLocal, options)
    except PilotSetupError as exc:
        print(f"REFUSED: {exc}")
        return 2
    finally:
        await engine.dispose()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
