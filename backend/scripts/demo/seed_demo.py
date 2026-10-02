#!/usr/bin/env python3
"""D3-04 demo seed: a fresh "Demo Consulting LLC — <yyyymmdd-n>" organization per run.

    python scripts/demo/seed_demo.py --target local --dry-run                 # plan only, no writes
    python scripts/demo/seed_demo.py --target local --confirm SEED_DEMO       # seed
    python scripts/demo/seed_demo.py --target local --confirm SEED_DEMO --resume 20261002-1

Run inside the backend (or pursuit-analysis worker) container: it uses the service
layer directly and waits for the pursuit-analysis worker to complete the analysis.

Safety
- ``--target`` must match the process environment (local: development/test;
  production: production); ``--confirm SEED_DEMO`` is required for any write.
- Writes go into the organization this run creates. Outside it, the run only:
  creates/approves the demo user record (audited, as scripts/smoke_account.py does),
  creates this run's steward user, and, in older demo organizations, revokes the
  demo user's membership and hands their demo company profile to that
  organization's steward.
- Records with a provenance field carry ``{"demo": true, ...}``; the company
  profile notes carry the same marker. No notifications or broadcasts are emitted.

Reset model (the analysis, review and EOI tables are append-only): every run creates
a new organization. A per-run steward user (reserved ``.invalid`` e-mail, non-Google
subject: it can never sign in) is an OWNER, so the demo user can later be revoked
from it. The demo user is an OWNER and, unless they already have a non-demo company
profile, owns the organization's company profile, so the dashboard, company page and
"Matches your profile" show the demo company. ``--resume <label>`` continues an
interrupted run; every step is idempotent within a run.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Awaitable, Callable
from uuid import UUID

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.auth import PREPROVISIONED_GOOGLE_ID_PREFIX
from app.core.access import (
    COMPANY_APPROVAL_APPROVED,
    COMPANY_PILOT_ACTIVE,
    PLATFORM_ROLE_PILOT_USER,
    USER_APPROVAL_APPROVED,
    USER_APPROVAL_PENDING,
    is_disabled_account,
    is_rejected_account,
)
from app.models.all_models import Tender, TenderDocument, User
from app.models.base import MembershipRole, MembershipState, TenderEngagementOrigin, TenderEngagementStatus
from app.models.candidate_retrieval import CVVersion, Expert, Firm, ProjectReference
from app.models.company import CompanyProfile
from app.models.eoi import EoiDraft
from app.models.pursuit_analysis import AnalysisRun
from app.models.tenancy import Membership, Organization, OrganizationPursuit

from scripts.demo import demo_data as data

CONFIRMATION = "SEED_DEMO"
DEMO_EMAIL = "support.plasma@gmail.com"
PROFILE_MARKER = "[plasma-demo-seed]"
STEWARD_DOMAIN = "plasma.invalid"
MIN_DEADLINE = date(2026, 10, 9)
TARGET_ENVIRONMENTS = {"local": {"development", "test"}, "production": {"production"}}
REVIEWABLE = "PROVISIONAL"


class DemoSeedError(RuntimeError):
    """The seed cannot run safely."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def provenance(label: str) -> dict[str, Any]:
    return {"demo": True, "seed": "d3-04", "run": label}


def organization_name(label: str) -> str:
    return data.ORGANIZATION_PREFIX + label


def steward_email(label: str) -> str:
    return f"demo-steward+{label}@{STEWARD_DOMAIN}"


def check_target(target: str, environment: str) -> None:
    allowed = TARGET_ENVIRONMENTS.get(target)
    if allowed is None:
        raise DemoSeedError("--target must be local or production")
    if environment not in allowed:
        raise DemoSeedError(f"--target {target} does not match this process's ENVIRONMENT={environment!r}")


# ---- read side ---------------------------------------------------------------------------------------

async def demo_organizations(db: AsyncSession) -> list[Organization]:
    """Organizations this seed created: the name prefix and the profile marker."""
    return list((await db.scalars(
        select(Organization).join(CompanyProfile, CompanyProfile.id == Organization.legacy_company_profile_id)
        .where(Organization.display_name.startswith(data.ORGANIZATION_PREFIX),
               CompanyProfile.notes.startswith(PROFILE_MARKER))
        .order_by(Organization.created_at, Organization.id)
    )).all())


async def next_label(db: AsyncSession, today: date) -> str:
    stem = today.strftime("%Y%m%d")
    names = (await db.scalars(select(Organization.display_name).where(
        Organization.display_name.startswith(data.ORGANIZATION_PREFIX + stem + "-")))).all()
    numbers = [int(match.group(1)) for name in names if (match := re.fullmatch(re.escape(data.ORGANIZATION_PREFIX + stem) + r"-(\d+)", name or ""))]
    return f"{stem}-{max(numbers, default=0) + 1}"


def _is_demo_profile(profile: CompanyProfile | None) -> bool:
    return profile is not None and (profile.notes or "").startswith(PROFILE_MARKER) \
        and (profile.company_name or "").startswith(data.ORGANIZATION_PREFIX)


async def demo_user_plan(db: AsyncSession, email: str) -> dict[str, Any]:
    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    profile = None if user is None else await db.scalar(select(CompanyProfile).where(CompanyProfile.user_id == user.id))
    if user is not None and (is_disabled_account(user) or is_rejected_account(user)):
        raise DemoSeedError(f"{email} is {user.approval_status}; refusing to re-approve it")
    if user is None:
        action = "create_preprovisioned"
    elif user.approval_status != USER_APPROVAL_APPROVED:
        action = "approve"
    else:
        action = "none"
    # OWN: the demo user owns the new demo profile. MEMBER: they keep their own (non-demo) profile.
    mode = "MEMBER" if profile is not None and not _is_demo_profile(profile) else "OWN"
    return {"user": user, "profile": profile, "user_action": action, "profile_mode": mode}


_CENTRAL_ASIA_MONGOLIA = ("uzbek", "kazakh", "kyrgyz", "tajik", "mongolia")


def reoi_condition(min_deadline: datetime):
    from app.services.tender_sources.uzex_scope import customer_visible_tender_condition

    has_notice = exists().where(
        TenderDocument.tender_id == Tender.id, TenderDocument.source_document_type == "OFFICIAL_NOTICE",
        func.length(func.coalesce(TenderDocument.parsed_text, "")) > 0,
    )
    return and_(
        Tender.source_system == "world_bank",
        customer_visible_tender_condition(Tender),
        Tender.deadline >= min_deadline,
        Tender.notice_type.op("~*")(r"expression of interest|\mREOI\M"),
        or_(Tender.procurement_category.is_(None), ~Tender.procurement_category.op("~*")(r"goods|works|non-consult")),
        or_(*(Tender.country.ilike(f"%{name}%") for name in _CENTRAL_ASIA_MONGOLIA)),
        has_notice,
    )


def sector_score(tender: Tender) -> int:
    """Relevance to the demo firm's sectors (energy first); the title outweighs the description."""
    def score(value: str | None) -> int:
        text = (value or "").casefold()
        return sum(any(word in text for word in words) for words in data.SECTOR_KEYWORDS.values()) + \
            (2 if any(word in text for word in data.SECTOR_KEYWORDS["energy"]) else 0)

    return 10 * score(tender.title) + score(tender.description)


async def pick_tenders(db: AsyncSession, *, min_deadline: date, overrides: list[UUID]) -> list[Tender]:
    """Pursuit B (analysed) first, then pursuit A: open World Bank consulting REOIs in Central Asia/Mongolia."""
    floor = max(datetime.combine(min_deadline, datetime.min.time(), tzinfo=timezone.utc), utcnow())
    if overrides:
        rows = [await db.get(Tender, value) for value in overrides]
        if any(row is None for row in rows):
            raise DemoSeedError("a --tender id does not exist")
        eligible = set((await db.scalars(select(Tender.id).where(Tender.id.in_(overrides), reoi_condition(floor)))).all())
        rejected = [str(row.id) for row in rows if row.id not in eligible]
        if rejected:
            raise DemoSeedError("not an open World Bank consulting REOI in Central Asia/Mongolia with an official notice: " + ", ".join(rejected))
        return rows
    rows = list((await db.scalars(select(Tender).where(reoi_condition(floor)).limit(500))).all())
    rows.sort(key=lambda row: (-sector_score(row), row.deadline, str(row.id)))
    if len(rows) < 2:
        raise DemoSeedError(f"found {len(rows)} open World Bank consulting REOIs in Central Asia/Mongolia; need 2 (or pass --tender)")
    return rows[:2]


# ---- write side --------------------------------------------------------------------------------------

async def _audit(db: AsyncSession, *, action: str, user: User, reason: str, resource: CompanyProfile | None = None) -> None:
    from app.services.admin_activity import (
        ACTOR_SERVER_COMMAND, OUTCOME_SUCCESS, SOURCE_ADMIN_REPAIR_COMMAND, company_role_snapshot,
        record_admin_audit_event, user_role_snapshot,
    )

    await record_admin_audit_event(
        db, action=action, outcome=OUTCOME_SUCCESS, source=SOURCE_ADMIN_REPAIR_COMMAND, actor_type=ACTOR_SERVER_COMMAND,
        actor_label="demo-seed-command", target_user=user, reason=reason,
        target_resource_type="COMPANY_PROFILE" if resource is not None else None,
        target_resource_id=str(resource.id) if resource is not None else None,
        new_state=company_role_snapshot(company_approval_status=resource.approval_status, user=user) if resource is not None
        else user_role_snapshot(user),
        metadata={"demo_seed": True},
    )


async def ensure_demo_user(db: AsyncSession, email: str) -> User:
    """Create (pre-provisioned, bound on first Google sign-in) or approve the demo user."""
    from app.services.admin_activity import ACTION_USER_APPROVED

    plan = await demo_user_plan(db, email)
    user: User | None = plan["user"]
    if user is None:
        user = User(
            google_id=PREPROVISIONED_GOOGLE_ID_PREFIX + email, email=email, name="Plasma Support (demo)",
            platform_role=PLATFORM_ROLE_PILOT_USER, approval_status=USER_APPROVAL_APPROVED, approved_at=utcnow(),
        )
        db.add(user)
        await db.flush()
        await _audit(db, action=ACTION_USER_APPROVED, user=user, reason="Demo account pre-provisioned by the D3-04 demo seed.")
    elif user.approval_status == USER_APPROVAL_PENDING:
        user.approval_status = USER_APPROVAL_APPROVED
        user.approved_at = utcnow()
        await _audit(db, action=ACTION_USER_APPROVED, user=user, reason="Demo account approved by the D3-04 demo seed.")
    await db.commit()
    return user


async def ensure_steward(db: AsyncSession, label: str) -> User:
    email = steward_email(label)
    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        user = User(
            google_id=f"plasma-demo-steward:{label}:not-a-google-account", email=email, name=f"Demo steward {label}",
            platform_role=PLATFORM_ROLE_PILOT_USER, approval_status=USER_APPROVAL_APPROVED, approved_at=utcnow(),
        )
        db.add(user)
        await db.commit()
    return user


async def _steward_membership(db: AsyncSession, organization_id: UUID) -> Membership | None:
    return await db.scalar(
        select(Membership).join(User, User.id == Membership.user_id).where(
            Membership.organization_id == organization_id, Membership.state == MembershipState.ACTIVE,
            Membership.role == MembershipRole.OWNER, User.email.like(f"demo-steward+%@{STEWARD_DOMAIN}"),
        )
    )


async def _add_owner(db: AsyncSession, *, organization_id: UUID, actor: Membership, user_id: UUID) -> Membership:
    from app.services.memberships import activate_invitation, change_membership_role, invite_member

    membership = await invite_member(db, organization_id=organization_id, actor_membership_id=actor.id, user_id=user_id)
    membership = await activate_invitation(db, membership_id=membership.id, user_id=user_id)
    return await change_membership_role(
        db, organization_id=organization_id, actor_membership_id=actor.id, membership_id=membership.id, role=MembershipRole.OWNER,
    )


async def ensure_organization(db: AsyncSession, *, label: str, demo_user: User, steward: User) -> dict[str, Any]:
    """The run's organization with the steward and the demo user as OWNERs."""
    from app.services.admin_activity import ACTION_COMPANY_APPROVED, bump_auth_version
    from app.services.organization_context import ensure_profile_organization

    name = organization_name(label)
    organization = await db.scalar(select(Organization).where(Organization.display_name == name))
    plan = await demo_user_plan(db, demo_user.email)
    mode = plan["profile_mode"]
    handed_off: list[str] = []
    if organization is None:
        if mode == "OWN" and plan["profile"] is not None:
            # Free the demo user's profile slot: hand their previous demo profile to its steward.
            previous = plan["profile"]
            old_org = await db.scalar(select(Organization).where(Organization.legacy_company_profile_id == previous.id))
            old_steward = None if old_org is None else await _steward_membership(db, old_org.id)
            if old_steward is None:
                raise DemoSeedError(f"previous demo profile {previous.id} has no steward OWNER to hand it to")
            previous.user_id = old_steward.user_id
            handed_off.append(str(previous.id))
            await db.flush()
        owner = demo_user if mode == "OWN" else steward
        profile = CompanyProfile(
            user_id=owner.id, created_by_user_id=demo_user.id, company_name=name,
            notes=f"{PROFILE_MARKER} {json.dumps(provenance(label))} Synthetic demonstration company; every record is invented.",
            approval_status=COMPANY_APPROVAL_APPROVED, pilot_status=COMPANY_PILOT_ACTIVE, approved_at=utcnow(),
            **data.PROFILE,
        )
        db.add(profile)
        await db.flush()
        await _audit(db, action=ACTION_COMPANY_APPROVED, user=owner, resource=profile, reason="Demo company created by the D3-04 demo seed.")
        context = await ensure_profile_organization(db, profile=profile)
        organization = context.organization
        other = steward if mode == "OWN" else demo_user
        await _add_owner(db, organization_id=organization.id, actor=context.membership, user_id=other.id)
        if mode == "OWN":
            bump_auth_version(demo_user)  # the session's company claims change
        await db.commit()
    membership = await db.scalar(select(Membership).where(
        Membership.organization_id == organization.id, Membership.user_id == demo_user.id, Membership.state == MembershipState.ACTIVE))
    if membership is None:
        raise DemoSeedError(f"the demo user has no active membership in {name}")
    return {"organization": organization, "membership": membership, "profile_mode": mode, "profiles_handed_off": handed_off}


async def revoke_older_memberships(db: AsyncSession, *, demo_user: User, keep: UUID) -> list[str]:
    from app.services.memberships import revoke_membership

    revoked = []
    for organization in await demo_organizations(db):
        if organization.id == keep:
            continue
        membership = await db.scalar(select(Membership).where(
            Membership.organization_id == organization.id, Membership.user_id == demo_user.id,
            Membership.state != MembershipState.REVOKED))
        if membership is None:
            continue
        steward = await _steward_membership(db, organization.id)
        if steward is None:
            raise DemoSeedError(f"demo organization {organization.id} has no steward OWNER; cannot revoke the demo user there")
        await revoke_membership(db, organization_id=organization.id, actor_membership_id=steward.id,
                                membership_id=membership.id, transfer_to_membership_id=steward.id)
        await db.commit()
        revoked.append(str(organization.id))
    return revoked


async def seed_library(db: AsyncSession, *, organization_id: UUID, user: User, label: str) -> dict[str, int]:
    from app.schemas.candidate_retrieval import (
        CVVersionCreateRequest, ExpertCreateRequest, FirmCreateRequest, ProjectReferenceCreateRequest, SelfFirmUpsertRequest,
    )
    from app.services.candidate_retrieval import (
        create_cv_version, create_expert, create_firm, create_project_reference, upsert_self_firm,
    )

    tag = provenance(label)
    self_firm = await db.scalar(select(Firm).where(Firm.organization_id == organization_id))
    if self_firm is None:
        await upsert_self_firm(db, organization_id=organization_id, actor_user_id=user.id,
                               payload=SelfFirmUpsertRequest(**data.SELF_FIRM, source_type="MANUAL", source_provenance=tag))
        self_firm = await db.scalar(select(Firm).where(Firm.organization_id == organization_id))

    async def references(firm_id: UUID, rows: list[dict[str, Any]]) -> None:
        existing = set((await db.scalars(select(ProjectReference.project_name).where(ProjectReference.firm_id == firm_id))).all())
        for row in rows:
            if row["project_name"] not in existing:
                await create_project_reference(db, organization_id=organization_id, firm_id=firm_id, actor_user_id=user.id, operator=False,
                                               payload=ProjectReferenceCreateRequest(**row, evidence_provenance=tag))

    await references(self_firm.id, data.OWN_REFERENCES)
    for partner in data.PARTNERS:
        firm = await db.scalar(select(Firm).where(Firm.owner_organization_id == organization_id, Firm.organization_id.is_(None),
                                                  Firm.display_name == partner["display_name"]))
        if firm is None:
            created = await create_firm(db, organization_id=organization_id, actor_user_id=user.id, operator=False, payload=FirmCreateRequest(
                scope="ORGANIZATION_PRIVATE", canonical_name=partner["display_name"], display_name=partner["display_name"],
                country=partner["country"], services=partner["services"], sectors=partner["sectors"],
                capabilities=partner["capabilities"], source_type="MANUAL", source_provenance=tag, evidence_state="UNVERIFIED",
                private_notes="Synthetic demo partner firm."))
            firm_id = created.firm_id
        else:
            firm_id = firm.id
        await references(firm_id, partner["references"])
    for expert in data.EXPERTS:
        row = await db.scalar(select(Expert).where(Expert.owner_organization_id == organization_id, Expert.display_name == expert["display_name"]))
        if row is None:
            created = await create_expert(db, organization_id=organization_id, actor_user_id=user.id, operator=False, payload=ExpertCreateRequest(
                scope="ORGANIZATION_PRIVATE", display_name=expert["display_name"], qualifications=expert["qualifications"],
                languages=expert["languages"], specializations=expert["specializations"], consent_state="NOT_REQUIRED_PRIVATE",
                evidence_state="UNVERIFIED", source_provenance=tag, private_notes="Fictional demo expert."))
            expert_id = created.expert_id
        else:
            expert_id = row.id
        if await db.scalar(select(func.count(CVVersion.id)).where(CVVersion.expert_id == expert_id)) == 0:
            await create_cv_version(db, organization_id=organization_id, expert_id=expert_id, actor_user_id=user.id, operator=False,
                                    payload=CVVersionCreateRequest(**expert["cv"], evidence_provenance=tag, evidence_state="UNVERIFIED"))
    return await library_counts(db, organization_id)


async def library_counts(db: AsyncSession, organization_id: UUID) -> dict[str, int]:
    self_firm_id = await db.scalar(select(Firm.id).where(Firm.organization_id == organization_id))
    partner_ids = (await db.scalars(select(Firm.id).where(Firm.owner_organization_id == organization_id, Firm.organization_id.is_(None)))).all()
    own = (await db.scalars(select(ProjectReference.evidence_state).where(ProjectReference.firm_id == self_firm_id,
                                                                         ProjectReference.archived_at.is_(None)))).all()
    expert_ids = (await db.scalars(select(Expert.id).where(Expert.owner_organization_id == organization_id))).all()
    return {
        "own_references": len(own), "own_references_reviewed": sum(state == "REVIEWED" for state in own),
        "partner_firms": len(partner_ids),
        "partner_references": await db.scalar(select(func.count(ProjectReference.id)).where(ProjectReference.firm_id.in_(partner_ids))) or 0,
        "experts": len(expert_ids),
        "cv_versions": await db.scalar(select(func.count(CVVersion.id)).where(CVVersion.expert_id.in_(expert_ids))) or 0,
    }


async def ensure_pursuit(db: AsyncSession, *, organization_id: UUID, user: User, membership: Membership, tender: Tender) -> OrganizationPursuit:
    from app.services.pursuits import get_or_create_source_pursuit

    resolution = await get_or_create_source_pursuit(
        db, organization_id=organization_id, actor_user_id=user.id, actor_membership_id=membership.id, tender_id=tender.id,
        stage=TenderEngagementStatus.SAVED, legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
    )
    await db.commit()
    return resolution.pursuit


ProcessInline = Callable[[AsyncSession, UUID], Awaitable[None]]


async def ensure_analysis(
    sessions, *, organization_id: UUID, pursuit_id: UUID, membership: Membership,
    timeout_seconds: float, poll_seconds: float, process_inline: ProcessInline | None,
) -> dict[str, Any]:
    """Reuse the pursuit's completed run, else start one on the official notice and wait for the worker."""
    from app.schemas.tenancy import PursuitAnalysisStartRequest
    from app.services.private_documents import build_analysis_pack_candidate
    from app.services.pursuit_analysis import create_analysis_run

    async with sessions() as db:
        run = await db.scalar(select(AnalysisRun).where(
            AnalysisRun.organization_id == organization_id, AnalysisRun.pursuit_id == pursuit_id,
            AnalysisRun.status.in_(("COMPLETED", "QUEUED", "RUNNING"))).order_by(AnalysisRun.created_at.desc()).limit(1))
        started = time.monotonic()
        if run is None:
            candidate = await build_analysis_pack_candidate(db, organization_id=organization_id, pursuit_id=pursuit_id)
            notices = [item for item in candidate.source_documents if item.role == "OFFICIAL_NOTICE" and item.parse_ready]
            if not notices:
                raise DemoSeedError("pursuit B's tender has no parse-ready official notice")
            response = await create_analysis_run(db, organization_id=organization_id, pursuit_id=pursuit_id, membership_id=membership.id,
                                                 request=PursuitAnalysisStartRequest(candidate_sha256=candidate.candidate_sha256,
                                                                                     analysis_language="en",
                                                                                     source_document_ids=[notices[0].tender_document_id]))
            run_id = response.analysis_run_id
        else:
            run_id = run.id
    if process_inline is not None:
        async with sessions() as db:
            await process_inline(db, run_id)
    deadline = started + timeout_seconds
    while True:
        async with sessions() as db:
            run = await db.get(AnalysisRun, run_id)
            status = run.status
            quality = getattr(run, "quality_state", None)
        if status in {"COMPLETED", "FAILED"} or time.monotonic() >= deadline:
            break
        await asyncio.sleep(poll_seconds)
    if status != "COMPLETED":
        raise DemoSeedError(f"analysis run {run_id} is {status} after {timeout_seconds:.0f} s; rerun with --resume when the worker finishes")
    return {"analysis_run_id": run_id, "status": status, "quality_state": quality, "wait_seconds": round(time.monotonic() - started, 1)}


async def bulk_confirm(db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, run_id: UUID,
                       membership: Membership, reviewer: str) -> dict[str, int]:
    """What "Confirm all in this group" does in the UI, for every group: confirm each provisional
    requirement (and its gap) at its current coverage. Already-confirmed items are skipped."""
    from app.schemas.tenancy import AnalysisReviewAssertionRequest
    from app.services.pursuit_analysis import append_review_assertion, get_analysis_run

    analysis = await get_analysis_run(db, organization_id=organization_id, pursuit_id=pursuit_id, run_id=run_id)
    reason = f"Reviewed in bulk by {reviewer}"
    gaps = {gap.requirement_id: gap for gap in analysis.gaps if gap.requirement_id}
    counts = {"requirements_confirmed": 0, "gaps_confirmed": 0, "already_reviewed": 0}
    for item in [*analysis.requirements, *analysis.submission_and_notes]:
        if item.effective_review_state != REVIEWABLE:
            counts["already_reviewed"] += 1
            continue
        posts = [("REQUIREMENT", item.requirement_id, item.effective_coverage_state)]
        gap = gaps.get(item.requirement_id)
        if gap is not None and gap.effective_review_state == REVIEWABLE:
            posts.append(("GAP", gap.gap_id, gap.effective_coverage_state))
        for kind, target, coverage in posts:
            await append_review_assertion(db, organization_id=organization_id, pursuit_id=pursuit_id, run_id=run_id,
                                          membership_id=membership.id, request=AnalysisReviewAssertionRequest(
                                              target_kind=kind, target_id=target, new_coverage_state=coverage,
                                              new_review_state="CONFIRMED", reason=reason))
            counts["requirements_confirmed" if kind == "REQUIREMENT" else "gaps_confirmed"] += 1
    return counts


def eoi_request(suggestions, *, profile: CompanyProfile, email: str):
    """Suggested own references (rank order) plus the one partner that covers the most criteria
    the own selection leaves open, as a JV member with its matching references."""
    from app.schemas.eoi import EoiDraftCreateRequest

    own = [item for item in suggestions.own_references if item.suggested][:30] or suggestions.own_references[:3]
    covered = {value for item in own for value in item.matched_requirement_ids}
    partners = sorted(suggestions.partner_firms, key=lambda firm: (
        -len([value for value in firm.covers_requirement_ids if value not in covered]), -len(firm.covers_requirement_ids),
        firm.display_name, str(firm.firm_id)))
    chosen = []
    if partners:
        firm = partners[0]
        matched = [item.reference_id for item in firm.references if item.matched_requirement_ids][:15]
        chosen = [{"firm_id": firm.firm_id, "role": "JV_MEMBER",
                   "reference_ids": matched or [item.reference_id for item in firm.references[:2]]}]
    defaults = suggestions.defaults
    return EoiDraftCreateRequest(
        analysis_run_id=suggestions.analysis_run_id, language="en",
        own_reference_ids=[item.reference_id for item in own], partners=chosen, include_relevance_notes=True,
        letter={"addressee_organization": defaults.addressee_organization or "Procurement unit",
                "addressee_name": defaults.addressee_name, "signatory_name": profile.director_name or "Director",
                "signatory_title": "Director", "contact_email": email, "contact_phone": profile.phone_contact,
                "contact_address": profile.address},
    )


async def ensure_eoi(db: AsyncSession, *, organization_id: UUID, pursuit_id: UUID, run_id: UUID, membership: Membership,
                     email: str, note_call=None) -> dict[str, Any]:
    from app.services.eoi import create_eoi_draft, eoi_suggestions, get_eoi_draft

    existing = await db.scalar(select(EoiDraft).where(EoiDraft.organization_id == organization_id, EoiDraft.pursuit_id == pursuit_id,
                                                      EoiDraft.analysis_run_id == run_id).order_by(EoiDraft.version).limit(1))
    if existing is not None:
        draft = await get_eoi_draft(db, organization_id=organization_id, pursuit_id=pursuit_id, draft_id=existing.id)
        return {"draft": draft, "generation_seconds": None, "reused": True}
    suggestions = await eoi_suggestions(db, organization_id=organization_id, pursuit_id=pursuit_id, analysis_run_id=run_id)
    organization = await db.get(Organization, organization_id)
    profile = await db.get(CompanyProfile, organization.legacy_company_profile_id)
    request = eoi_request(suggestions, profile=profile, email=email)
    started = time.monotonic()
    draft = await create_eoi_draft(db, organization_id=organization_id, pursuit_id=pursuit_id, membership_id=membership.id,
                                   request=request, note_call=note_call)
    return {"draft": draft, "generation_seconds": round(time.monotonic() - started, 1), "reused": False}


# ---- orchestration -----------------------------------------------------------------------------------

@dataclass
class Options:
    target: str
    confirm: str = ""
    dry_run: bool = False
    resume: str | None = None
    tenders: tuple[UUID, ...] = ()
    email: str = DEMO_EMAIL
    min_deadline: date = MIN_DEADLINE
    analysis_timeout: float = 900.0
    poll_seconds: float = 5.0


async def plan(sessions, options: Options, *, today: date | None = None) -> dict[str, Any]:
    """Everything the run would do; no writes."""
    async with sessions() as db:
        label = options.resume or await next_label(db, today or utcnow().date())
        user_plan = await demo_user_plan(db, options.email)
        tenders = await pick_tenders(db, min_deadline=options.min_deadline, overrides=list(options.tenders))
        existing = await db.scalar(select(Organization.id).where(Organization.display_name == organization_name(label)))
        older = [str(item.id) for item in await demo_organizations(db) if item.display_name != organization_name(label)]
        picked = [_tender_summary(item) for item in tenders]
        await db.rollback()
    return {
        "mode": "dry-run" if options.dry_run else "seed", "target": options.target, "label": label,
        "organization_name": organization_name(label), "organization_exists": existing is not None,
        "demo_user": options.email, "demo_user_action": user_plan["user_action"], "profile_mode": user_plan["profile_mode"],
        "older_demo_organizations": older,
        "pursuit_b_tender": picked[0], "pursuit_a_tender": picked[1],
        "will_create": {"own_references": len(data.OWN_REFERENCES), "partner_firms": len(data.PARTNERS),
                        "partner_references": sum(len(item["references"]) for item in data.PARTNERS),
                        "experts": len(data.EXPERTS), "cv_versions": len(data.EXPERTS), "pursuits": 2},
    }


def _tender_summary(tender: Tender) -> dict[str, Any]:
    return {"tender_id": str(tender.id), "external_id": tender.external_id, "title": tender.title, "country": tender.country,
            "deadline": tender.deadline.isoformat() if tender.deadline else None}


async def seed(sessions, options: Options, *, today: date | None = None, process_inline: ProcessInline | None = None,
               note_call=None) -> dict[str, Any]:
    if options.confirm != CONFIRMATION:
        raise DemoSeedError(f"writes require --confirm {CONFIRMATION}")
    summary = await plan(sessions, options, today=today)
    label = summary["label"]
    if options.resume is not None and not summary["organization_exists"]:
        raise DemoSeedError(f"--resume {label}: no organization named {organization_name(label)!r}")
    async with sessions() as db:
        demo_user = await ensure_demo_user(db, options.email.strip().lower())
        steward = await ensure_steward(db, label)
        context = await ensure_organization(db, label=label, demo_user=demo_user, steward=steward)
        organization, membership = context["organization"], context["membership"]
        revoked = await revoke_older_memberships(db, demo_user=demo_user, keep=organization.id)
        counts = await seed_library(db, organization_id=organization.id, user=demo_user, label=label)
        tender_b = await db.get(Tender, UUID(summary["pursuit_b_tender"]["tender_id"]))
        tender_a = await db.get(Tender, UUID(summary["pursuit_a_tender"]["tender_id"]))
        pursuit_b = await ensure_pursuit(db, organization_id=organization.id, user=demo_user, membership=membership, tender=tender_b)
        pursuit_a = await ensure_pursuit(db, organization_id=organization.id, user=demo_user, membership=membership, tender=tender_a)
        reviewer = demo_user.name or demo_user.email
        ids = (organization.id, pursuit_b.id, membership.id)
    analysis = await ensure_analysis(sessions, organization_id=ids[0], pursuit_id=ids[1], membership=membership,
                                     timeout_seconds=options.analysis_timeout, poll_seconds=options.poll_seconds,
                                     process_inline=process_inline)
    async with sessions() as db:
        membership = await db.get(Membership, ids[2])
        reviews = await bulk_confirm(db, organization_id=ids[0], pursuit_id=ids[1], run_id=analysis["analysis_run_id"],
                                     membership=membership, reviewer=reviewer)
        eoi = await ensure_eoi(db, organization_id=ids[0], pursuit_id=ids[1], run_id=analysis["analysis_run_id"],
                               membership=membership, email=options.email, note_call=note_call)
    draft = eoi["draft"]
    return {
        "label": label, "organization_id": str(ids[0]), "organization_name": organization_name(label),
        "demo_user_id": str(demo_user.id), "profile_mode": context["profile_mode"],
        "profiles_handed_off": context["profiles_handed_off"], "revoked_in_older_organizations": revoked,
        "pursuit_a_id": str(pursuit_a.id), "pursuit_a_tender": summary["pursuit_a_tender"],
        "pursuit_b_id": str(ids[1]), "pursuit_b_tender": summary["pursuit_b_tender"],
        "counts": counts, "analysis": {**analysis, "analysis_run_id": str(analysis["analysis_run_id"])}, "reviews": reviews,
        "eoi_draft_id": str(draft.draft_id), "eoi_version": draft.version, "eoi_reused": eoi["reused"],
        "eoi_generation_seconds": eoi["generation_seconds"], "eoi_summary": draft.summary.model_dump(),
        "eoi_artifacts": [{"artifact_id": str(item.artifact_id), "format": item.format, "byte_size": item.byte_size}
                          for item in draft.artifacts],
        "notifications_emitted": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", required=True, choices=sorted(TARGET_ENVIRONMENTS))
    parser.add_argument("--confirm", default="", help=f"Required for any write: {CONFIRMATION}")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan; write nothing.")
    parser.add_argument("--resume", metavar="YYYYMMDD-N", help="Continue an interrupted run with this label.")
    parser.add_argument("--tender", action="append", type=UUID, default=[],
                        help="Pin the tenders: first is pursuit B (analysed), second pursuit A.")
    parser.add_argument("--email", default=DEMO_EMAIL)
    parser.add_argument("--min-deadline", type=date.fromisoformat, default=MIN_DEADLINE)
    parser.add_argument("--analysis-timeout", type=float, default=900.0)
    return parser


async def main(argv: list[str] | None = None) -> int:
    from app.core.config import settings

    args = build_parser().parse_args(argv)
    if args.resume and not re.fullmatch(r"\d{8}-\d+", args.resume):
        print("--resume takes a run label such as 20261002-1", file=sys.stderr)
        return 2
    if args.tender and len(args.tender) != 2:
        print("--tender is given twice (pursuit B, then pursuit A) or not at all", file=sys.stderr)
        return 2
    options = Options(target=args.target, confirm=args.confirm, dry_run=args.dry_run, resume=args.resume,
                      tenders=tuple(args.tender), email=args.email.strip().lower(), min_deadline=args.min_deadline,
                      analysis_timeout=args.analysis_timeout)
    try:
        check_target(options.target, settings.ENVIRONMENT)
        if not options.dry_run and options.confirm != CONFIRMATION:
            raise DemoSeedError(f"writes require --confirm {CONFIRMATION} (or use --dry-run)")
        from app.db.session import AsyncSessionLocal, engine

        try:
            result = await (plan(AsyncSessionLocal, options) if options.dry_run else seed(AsyncSessionLocal, options))
        finally:
            await engine.dispose()
    except DemoSeedError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
