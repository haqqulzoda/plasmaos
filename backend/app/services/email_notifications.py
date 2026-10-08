"""E-mail notifications. R3 Task 4 adds the SMTP channel; until then nothing is queued."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invitations import PendingInvitation
from app.models.user import User

EMAIL_DELIVERY_QUEUED = "QUEUED"
EMAIL_DELIVERY_DISABLED = "DISABLED"


async def queue_invitation_email(
    db: AsyncSession, *, invitation: PendingInvitation, token: str, inviter: User
) -> str:
    """Queue the team invitation e-mail. Without an e-mail channel the link is copied by hand."""
    return EMAIL_DELIVERY_DISABLED
