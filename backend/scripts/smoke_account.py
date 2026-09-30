#!/usr/bin/env python3
"""Dedicated single-member "Plasma Smoke Test" account for ``analysis_smoke.py --live``.

The live analysis smoke writes a pursuit and one analysis run, so it must never run in a
customer organization. This command creates (idempotently) one approved user that can
never sign in with Google (reserved ``.invalid`` e-mail, non-Google subject), its approved
company profile and the profile's organization, with that user as the only member.

    python scripts/smoke_account.py ensure                                   # report only
    python scripts/smoke_account.py ensure --apply --confirm CREATE_SMOKE_ACCOUNT
    ANALYSIS_SMOKE_TOKEN="$(python scripts/smoke_account.py token)"          # 60-minute bearer token

``ensure`` prints the organization id and exact name (the ``--org-id`` / ``--org-name`` of
the live smoke). ``token`` prints only the token on stdout, so it can be captured into the
environment without being displayed. Both refuse when the e-mail belongs to an account this
command did not create, or when the organization has any other member.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import (
    COMPANY_APPROVAL_APPROVED,
    COMPANY_PILOT_ACTIVE,
    PLATFORM_ROLE_PILOT_USER,
    USER_APPROVAL_APPROVED,
)
from app.models.all_models import User
from app.models.base import MembershipState
from app.models.company import CompanyProfile
from app.models.tenancy import Membership, Organization

CONFIRMATION = "CREATE_SMOKE_ACCOUNT"
SMOKE_EMAIL = "plasma-smoke-test@plasma.invalid"
SMOKE_NAME = "Plasma Smoke Test"
# Google subjects are numeric; this one can never match a Google sign-in.
SMOKE_GOOGLE_ID = "plasma-smoke-test:not-a-google-account"
TOKEN_MINUTES = 60


class SmokeAccountError(RuntimeError):
    """The account exists in a shape this command must not touch."""


async def _state(db: AsyncSession, *, email: str) -> dict[str, Any]:
    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    profile = None if user is None else await db.scalar(
        select(CompanyProfile).where(CompanyProfile.user_id == user.id)
    )
    organization = None if profile is None else await db.scalar(
        select(Organization).where(Organization.legacy_company_profile_id == profile.id)
    )
    return {"user": user, "profile": profile, "organization": organization}


async def _check_single_member(db: AsyncSession, *, user: User, organization: Organization) -> None:
    members = (await db.execute(
        select(Membership.user_id).where(
            Membership.organization_id == organization.id, Membership.state == MembershipState.ACTIVE
        )
    )).scalars().all()
    if list(members) != [user.id]:
        raise SmokeAccountError(
            f"organization {organization.id} has {len(members)} active members; the smoke organization must have exactly one: the smoke user"
        )
    memberships = await db.scalar(
        select(func.count(Membership.id)).where(Membership.user_id == user.id, Membership.state == MembershipState.ACTIVE)
    )
    if memberships != 1:
        raise SmokeAccountError(f"the smoke user has {memberships} active memberships; it must have exactly one")


def _check_owned(state: dict[str, Any], *, name: str) -> None:
    user, profile = state["user"], state["profile"]
    if user is not None and user.google_id != SMOKE_GOOGLE_ID:
        raise SmokeAccountError("the e-mail belongs to an account this command did not create; refusing to touch it")
    if profile is not None and profile.company_name != name:
        raise SmokeAccountError(f"the smoke user's company profile is named {profile.company_name!r}, not {name!r}")


async def ensure_smoke_account(
    db: AsyncSession, *, email: str = SMOKE_EMAIL, name: str = SMOKE_NAME, apply: bool = False
) -> dict[str, Any]:
    """Create or verify the smoke account; report only unless ``apply``. Commits on apply."""
    from app.services.admin_activity import (
        ACTION_COMPANY_APPROVED,
        ACTION_USER_APPROVED,
        ACTOR_SERVER_COMMAND,
        OUTCOME_SUCCESS,
        SOURCE_ADMIN_REPAIR_COMMAND,
        company_role_snapshot,
        record_admin_audit_event,
        user_role_snapshot,
    )
    from app.services.organization_context import ensure_profile_organization

    email = email.strip().lower()
    state = await _state(db, email=email)
    _check_owned(state, name=name)
    missing = [key for key in ("user", "profile", "organization") if state[key] is None]
    if not apply:
        if not missing:
            await _check_single_member(db, user=state["user"], organization=state["organization"])
        report = {
            "status": "would_create" if missing else "exists",
            "missing": missing,
            "organization_id": str(state["organization"].id) if state["organization"] is not None else None,
            "organization_name": name,
        }
        await db.rollback()
        return report

    now = datetime.now(timezone.utc)
    user, profile = state["user"], state["profile"]
    if user is None:
        user = User(
            google_id=SMOKE_GOOGLE_ID, email=email, name=name,
            platform_role=PLATFORM_ROLE_PILOT_USER, approval_status=USER_APPROVAL_APPROVED, approved_at=now,
        )
        db.add(user)
        await db.flush()
        await record_admin_audit_event(
            db, action=ACTION_USER_APPROVED, outcome=OUTCOME_SUCCESS, source=SOURCE_ADMIN_REPAIR_COMMAND,
            actor_type=ACTOR_SERVER_COMMAND, actor_label="smoke-account-command", target_user=user,
            reason="Dedicated analysis smoke test account.", new_state=user_role_snapshot(user),
            metadata={"smoke_account": True},
        )
    if profile is None:
        profile = CompanyProfile(
            user_id=user.id, created_by_user_id=user.id, company_name=name,
            notes="Dedicated single-member organization for scripts/analysis_smoke.py --live.",
            approval_status=COMPANY_APPROVAL_APPROVED, pilot_status=COMPANY_PILOT_ACTIVE, approved_at=now,
        )
        db.add(profile)
        await db.flush()
        await record_admin_audit_event(
            db, action=ACTION_COMPANY_APPROVED, outcome=OUTCOME_SUCCESS, source=SOURCE_ADMIN_REPAIR_COMMAND,
            actor_type=ACTOR_SERVER_COMMAND, actor_label="smoke-account-command", target_user=user,
            target_resource_type="COMPANY_PROFILE", target_resource_id=str(profile.id),
            reason="Dedicated analysis smoke test company.",
            new_state=company_role_snapshot(company_approval_status=profile.approval_status, user=user),
            metadata={"smoke_account": True},
        )
    context = await ensure_profile_organization(db, profile=profile)
    await db.flush()
    await _check_single_member(db, user=user, organization=context.organization)
    await db.commit()
    return {
        "status": "created" if missing else "no_op",
        "created": missing,
        "organization_id": str(context.organization.id),
        "organization_name": context.organization.display_name,
    }


async def smoke_token(
    db: AsyncSession, *, email: str = SMOKE_EMAIL, name: str = SMOKE_NAME, minutes: int = TOKEN_MINUTES
) -> str:
    """A short-lived bearer token for the verified smoke user; read-only."""
    from app.api.endpoints.auth import _token_payload
    from app.core.security import create_access_token

    state = await _state(db, email=email.strip().lower())
    if any(state[key] is None for key in ("user", "profile", "organization")):
        raise SmokeAccountError("the smoke account does not exist; run: ensure --apply --confirm " + CONFIRMATION)
    _check_owned(state, name=name)
    await _check_single_member(db, user=state["user"], organization=state["organization"])
    payload = _token_payload(state["user"], state["profile"])
    await db.rollback()
    return create_access_token(data=payload, expires_delta=timedelta(minutes=minutes))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    ensure = sub.add_parser("ensure", help="Create or verify the smoke account (report only without --apply).")
    ensure.add_argument("--apply", action="store_true")
    ensure.add_argument("--confirm", default="", help=f"Required with --apply: {CONFIRMATION}")
    token = sub.add_parser("token", help="Print a short-lived bearer token for the smoke user (stdout only).")
    token.add_argument("--minutes", type=int, default=TOKEN_MINUTES)
    for command in (ensure, token):
        command.add_argument("--email", default=SMOKE_EMAIL)
        command.add_argument("--name", default=SMOKE_NAME)
    return parser


async def main(argv: list[str] | None = None) -> int:
    from app.db.session import AsyncSessionLocal, engine

    args = build_parser().parse_args(argv)
    if args.mode == "ensure" and args.apply and args.confirm != CONFIRMATION:
        print(f"--apply requires --confirm {CONFIRMATION}", file=sys.stderr)
        return 2
    if args.mode == "token" and not 1 <= args.minutes <= 480:
        print("--minutes must be between 1 and 480", file=sys.stderr)
        return 2
    try:
        async with AsyncSessionLocal() as db:
            if args.mode == "ensure":
                print(json.dumps(await ensure_smoke_account(db, email=args.email, name=args.name, apply=args.apply)))
            else:
                print(await smoke_token(db, email=args.email, name=args.name, minutes=args.minutes))
    except SmokeAccountError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
