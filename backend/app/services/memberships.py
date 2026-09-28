"""Organization membership invitation, role, and revocation commands."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import MembershipRole, MembershipState
from app.models.tenancy import Membership, OrganizationPursuit
from app.models.private_documents import MembershipLifecycleEvent
from app.models.user import User


class MembershipError(RuntimeError):
    pass


class MembershipPermissionError(MembershipError):
    pass


class MembershipNotFoundError(MembershipError):
    pass


class LastOwnerError(MembershipError):
    pass


async def _lock_organization(db: AsyncSession, organization_id: UUID) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
        {"identity": f"plasma:w2:membership:{organization_id}"},
    )


async def _require_owner(
    db: AsyncSession, *, organization_id: UUID, actor_membership_id: UUID
) -> Membership:
    actor = await db.scalar(
        select(Membership).where(
            Membership.id == actor_membership_id,
            Membership.organization_id == organization_id,
            Membership.state == MembershipState.ACTIVE,
            Membership.role == MembershipRole.OWNER,
        )
    )
    if actor is None:
        raise MembershipPermissionError("active OWNER membership required")
    return actor


async def invite_member(
    db: AsyncSession,
    *,
    organization_id: UUID,
    actor_membership_id: UUID,
    user_id: UUID,
) -> Membership:
    await _lock_organization(db, organization_id)
    actor = await _require_owner(
        db, organization_id=organization_id, actor_membership_id=actor_membership_id
    )
    if await db.scalar(select(User.id).where(User.id == user_id)) is None:
        raise MembershipNotFoundError("platform user not found")
    now = datetime.now(timezone.utc)
    existing = await db.scalar(
        select(Membership)
        .where(
            Membership.organization_id == organization_id,
            Membership.user_id == user_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.state == MembershipState.ACTIVE:
            return existing
        previous_role = existing.role
        previous_state = existing.state
        existing.role = MembershipRole.MEMBER
        existing.state = MembershipState.INVITED
        existing.activated_at = None
        existing.revoked_at = None
        existing.updated_at = now
        db.add(
            MembershipLifecycleEvent(
                organization_id=organization_id,
                membership_id=existing.id,
                actor_user_id=actor.user_id,
                actor_membership_id=actor.id,
                action="REINVITE" if previous_state == MembershipState.REVOKED else "INVITE",
                previous_role=previous_role.value,
                new_role=MembershipRole.MEMBER.value,
                previous_state=previous_state.value,
                new_state=MembershipState.INVITED.value,
            )
        )
        await db.flush()
        return existing
    membership_id = uuid4()
    await db.execute(
        pg_insert(Membership).values(
            id=membership_id,
            organization_id=organization_id,
            user_id=user_id,
            role=MembershipRole.MEMBER,
            state=MembershipState.INVITED,
            created_at=now,
            updated_at=now,
        )
    )
    membership = await db.get(Membership, membership_id)
    if membership is None:
        raise MembershipError("membership invitation failed")
    db.add(
        MembershipLifecycleEvent(
            organization_id=organization_id,
            membership_id=membership.id,
            actor_user_id=actor.user_id,
            actor_membership_id=actor.id,
            action="INVITE",
            new_role=membership.role.value,
            new_state=membership.state.value,
        )
    )
    await db.flush()
    return membership


async def activate_invitation(
    db: AsyncSession, *, membership_id: UUID, user_id: UUID
) -> Membership:
    membership = await db.scalar(
        select(Membership)
        .where(Membership.id == membership_id, Membership.user_id == user_id)
        .with_for_update()
    )
    if membership is None:
        raise MembershipNotFoundError("membership invitation not found")
    if membership.state == MembershipState.ACTIVE:
        return membership
    if membership.state != MembershipState.INVITED:
        raise MembershipError("revoked membership requires a new invitation")
    now = datetime.now(timezone.utc)
    membership.state = MembershipState.ACTIVE
    membership.activated_at = now
    membership.revoked_at = None
    membership.updated_at = now
    db.add(
        MembershipLifecycleEvent(
            organization_id=membership.organization_id,
            membership_id=membership.id,
            actor_user_id=user_id,
            actor_membership_id=membership.id,
            action="ACTIVATE",
            previous_role=membership.role.value,
            new_role=membership.role.value,
            previous_state=MembershipState.INVITED.value,
            new_state=MembershipState.ACTIVE.value,
        )
    )
    await db.flush()
    return membership


async def change_membership_role(
    db: AsyncSession,
    *,
    organization_id: UUID,
    actor_membership_id: UUID,
    membership_id: UUID,
    role: MembershipRole,
) -> Membership:
    await _lock_organization(db, organization_id)
    actor = await _require_owner(
        db, organization_id=organization_id, actor_membership_id=actor_membership_id
    )
    target = await db.scalar(
        select(Membership)
        .where(
            Membership.id == membership_id,
            Membership.organization_id == organization_id,
        )
        .with_for_update()
    )
    if target is None:
        raise MembershipNotFoundError("membership not found")
    if target.state != MembershipState.ACTIVE:
        raise MembershipError("only active memberships can change role")
    if target.role == role:
        return target
    if target.role == MembershipRole.OWNER and role == MembershipRole.MEMBER:
        active_owners = list(
            (
                await db.execute(
                    select(Membership.id)
                    .where(
                        Membership.organization_id == organization_id,
                        Membership.state == MembershipState.ACTIVE,
                        Membership.role == MembershipRole.OWNER,
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        if len(active_owners) <= 1:
            raise LastOwnerError("final active OWNER cannot be demoted")
    previous_role = target.role
    target.role = role
    target.updated_at = datetime.now(timezone.utc)
    db.add(
        MembershipLifecycleEvent(
            organization_id=organization_id,
            membership_id=target.id,
            actor_user_id=actor.user_id,
            actor_membership_id=actor.id,
            action="ROLE_CHANGE",
            previous_role=previous_role.value,
            new_role=role.value,
            previous_state=target.state.value,
            new_state=target.state.value,
        )
    )
    await db.flush()
    return target


async def revoke_membership(
    db: AsyncSession,
    *,
    organization_id: UUID,
    actor_membership_id: UUID,
    membership_id: UUID,
    transfer_to_membership_id: UUID | None = None,
) -> Membership:
    """Revoke and transfer or unassign owned pursuits in one transaction."""
    await _lock_organization(db, organization_id)
    actor = await _require_owner(
        db, organization_id=organization_id, actor_membership_id=actor_membership_id
    )
    target = await db.scalar(
        select(Membership)
        .where(
            Membership.id == membership_id,
            Membership.organization_id == organization_id,
        )
        .with_for_update()
    )
    if target is None:
        raise MembershipNotFoundError("membership not found")
    if target.state == MembershipState.REVOKED:
        return target
    if target.role == MembershipRole.OWNER and target.state == MembershipState.ACTIVE:
        active_owners = list(
            (
                await db.execute(
                    select(Membership.id)
                    .where(
                        Membership.organization_id == organization_id,
                        Membership.state == MembershipState.ACTIVE,
                        Membership.role == MembershipRole.OWNER,
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        if len(active_owners) <= 1:
            raise LastOwnerError("final active OWNER cannot be revoked")
    replacement_id: UUID | None = None
    if transfer_to_membership_id is not None:
        replacement_id = await db.scalar(
            select(Membership.id).where(
                Membership.id == transfer_to_membership_id,
                Membership.organization_id == organization_id,
                Membership.state == MembershipState.ACTIVE,
            )
        )
        if replacement_id is None or replacement_id == membership_id:
            raise MembershipError("transfer destination must be another active membership")
    await db.execute(
        update(OrganizationPursuit)
        .where(
            OrganizationPursuit.organization_id == organization_id,
            OrganizationPursuit.owner_membership_id == membership_id,
        )
        .values(owner_membership_id=replacement_id, updated_at=datetime.now(timezone.utc))
    )
    now = datetime.now(timezone.utc)
    target.state = MembershipState.REVOKED
    target.revoked_at = now
    target.updated_at = now
    db.add(
        MembershipLifecycleEvent(
            organization_id=organization_id,
            membership_id=target.id,
            actor_user_id=actor.user_id,
            actor_membership_id=actor.id,
            action="REVOKE",
            previous_role=target.role.value,
            new_role=target.role.value,
            previous_state=MembershipState.ACTIVE.value if target.activated_at else MembershipState.INVITED.value,
            new_state=MembershipState.REVOKED.value,
        )
    )
    await db.flush()
    return target
