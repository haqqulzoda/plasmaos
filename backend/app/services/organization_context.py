"""Validated organization context resolution for private resources."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import MembershipRole, MembershipState
from app.models.company import CompanyProfile
from app.models.tenancy import Membership, Organization
from app.models.private_documents import MembershipLifecycleEvent


class OrganizationContextError(RuntimeError):
    """Base organization context error."""


class OrganizationContextRequiredError(OrganizationContextError):
    """More than one active membership requires an explicit context."""


class OrganizationAccessDeniedError(OrganizationContextError):
    """The user has no active membership in the requested organization."""


@dataclass(frozen=True)
class OrganizationContext:
    organization: Organization
    membership: Membership


def deterministic_uuid(label: str) -> UUID:
    """Match the deterministic md5 UUID used by the additive backfill."""
    return UUID(hashlib.md5(label.encode("utf-8"), usedforsecurity=False).hexdigest())


async def resolve_organization_context(
    db: AsyncSession,
    *,
    user_id: UUID,
    organization_id: UUID | None = None,
) -> OrganizationContext:
    statement = (
        select(Organization, Membership)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(
            Membership.user_id == user_id,
            Membership.state == MembershipState.ACTIVE,
        )
        .order_by(Organization.id)
    )
    if organization_id is not None:
        statement = statement.where(Organization.id == organization_id)
    rows = (await db.execute(statement.limit(2))).all()
    if not rows:
        raise OrganizationAccessDeniedError("active organization membership required")
    if organization_id is None and len(rows) > 1:
        raise OrganizationContextRequiredError(
            "explicit organization context required for a multi-organization user"
        )
    organization, membership = rows[0]
    return OrganizationContext(organization=organization, membership=membership)


async def resolve_legacy_profile_context(
    db: AsyncSession,
    *,
    user_id: UUID,
    company_profile_id: UUID,
) -> OrganizationContext:
    row = (
        await db.execute(
            select(Organization, Membership)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(
                Organization.legacy_company_profile_id == company_profile_id,
                Membership.user_id == user_id,
                Membership.state == MembershipState.ACTIVE,
            )
        )
    ).one_or_none()
    if row is None:
        raise OrganizationAccessDeniedError("legacy profile has no active organization membership")
    return OrganizationContext(organization=row[0], membership=row[1])


async def ensure_profile_organization(
    db: AsyncSession,
    *,
    profile: CompanyProfile,
) -> OrganizationContext:
    """Create the exact profile Organization and initial owner, idempotently."""
    organization_id = deterministic_uuid(f"plasma:w2:organization:{profile.id}")
    now = datetime.now(timezone.utc)
    await db.execute(
        pg_insert(Organization)
        .values(
            id=organization_id,
            legacy_company_profile_id=profile.id,
            display_name=profile.company_name,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_organizations_legacy_company_profile")
    )
    organization = await db.scalar(
        select(Organization).where(Organization.legacy_company_profile_id == profile.id)
    )
    if organization is None:
        raise OrganizationContextError("organization resolution failed")
    if organization.display_name != profile.company_name:
        organization.display_name = profile.company_name
        organization.updated_at = now
    membership_id = deterministic_uuid(
        f"plasma:w2:membership:{organization.id}:{profile.user_id}"
    )
    await db.execute(
        pg_insert(Membership)
        .values(
            id=membership_id,
            organization_id=organization.id,
            user_id=profile.user_id,
            role=MembershipRole.OWNER,
            state=MembershipState.ACTIVE,
            created_at=now,
            updated_at=now,
            activated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_memberships_organization_user")
    )
    membership = await db.scalar(
        select(Membership).where(
            Membership.organization_id == organization.id,
            Membership.user_id == profile.user_id,
        )
    )
    if membership is None:
        raise OrganizationContextError("owner membership resolution failed")
    if await db.scalar(
        select(MembershipLifecycleEvent.id).where(
            MembershipLifecycleEvent.membership_id == membership.id
        ).limit(1)
    ) is None:
        db.add(
            MembershipLifecycleEvent(
                organization_id=organization.id,
                membership_id=membership.id,
                actor_user_id=profile.user_id,
                actor_membership_id=membership.id,
                action="ACTIVATE",
                new_role=membership.role.value,
                new_state=membership.state.value,
                created_at=membership.created_at,
            )
        )
        await db.flush()
    return OrganizationContext(organization=organization, membership=membership)
