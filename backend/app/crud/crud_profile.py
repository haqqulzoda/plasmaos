"""
Plasma AI — Company Profile Repository

Centralised data-access layer for CompanyProfile retrieval with
guaranteed deep hydration of all compliance-critical relationships.

This module exists to eliminate the class of bugs where a profile is
fetched via a bare ``select(CompanyProfile)`` — producing a shell object
with empty relationship collections — and then passed to the compliance
matching engine, which silently produces false negatives.

Every public function in this module uses ``selectinload`` to eagerly
load certifications, licenses, and financial history in a single
async-safe round-trip.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud.exceptions import ProfileNotFoundException
from app.models.company import CompanyProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal: Canonical eager-loading options
# ---------------------------------------------------------------------------

def _compliance_load_options() -> list:
    """
    Return the canonical set of SQLAlchemy loader options that guarantee
    full hydration of all compliance-critical relationships.

    Centralised here so that every call site uses the identical strategy.
    Adding a new relationship to CompanyProfile that is compliance-relevant
    requires a single edit in this function.
    """
    return [
        selectinload(CompanyProfile.certifications),
        selectinload(CompanyProfile.licenses),
        selectinload(CompanyProfile.financial_history),
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_profile_for_compliance_match(
    db: AsyncSession,
    user_id: UUID,
) -> CompanyProfile:
    """
    Retrieve a fully-hydrated CompanyProfile for compliance matching.

    This is the **only** function that should be used when a profile is
    needed for tender requirement extraction, compliance evaluation, or
    any AI-driven matching pipeline.

    Guarantees:
        1. All compliance relationships (certifications, licenses,
           financial_history) are eagerly loaded via ``selectinload``.
        2. If no profile exists for the user, ``ProfileNotFoundException``
           is raised — callers must handle this explicitly.
        3. If the profile exists but has zero certifications or zero
           licenses, a WARNING is emitted to the structured logger.
           The profile is still returned (some tenders may not require
           certifications), but downstream match quality will degrade.

    Args:
        db: An active async SQLAlchemy session.
        user_id: The UUID of the authenticated user.

    Returns:
        A CompanyProfile instance with all compliance relationships loaded.

    Raises:
        ProfileNotFoundException: If no profile exists for the given user.
    """
    result = await db.execute(
        select(CompanyProfile)
        .options(*_compliance_load_options())
        .where(CompanyProfile.user_id == user_id)
    )
    profile: CompanyProfile | None = result.scalar_one_or_none()

    # ── Hard failure: no profile at all ──────────────────────────────
    if profile is None:
        raise ProfileNotFoundException(user_id)

    # ── Soft warnings: profile exists but compliance data is sparse ──
    if not profile.certifications:
        logger.warning(
            "Hydrated profile for user %s (profile_id=%s) contains zero "
            "certifications. Compliance match will likely fail.",
            user_id,
            profile.id,
        )

    if not profile.licenses:
        logger.warning(
            "Hydrated profile for user %s (profile_id=%s) contains zero "
            "licenses. Compliance match may produce false negatives.",
            user_id,
            profile.id,
        )

    if not profile.financial_history:
        logger.warning(
            "Hydrated profile for user %s (profile_id=%s) contains zero "
            "financial history records. Financial eligibility checks will "
            "be skipped.",
            user_id,
            profile.id,
        )

    logger.info(
        "Profile hydrated for user %s: %d certifications, %d licenses, "
        "%d financial history records.",
        user_id,
        len(profile.certifications),
        len(profile.licenses),
        len(profile.financial_history),
    )

    return profile


async def get_profile_for_compliance_match_or_none(
    db: AsyncSession,
    user_id: UUID,
) -> CompanyProfile | None:
    """
    Same as ``get_profile_for_compliance_match`` but returns ``None``
    instead of raising when no profile exists.

    Use this in contexts where a missing profile is acceptable (e.g.
    building an analysis ownership key) but you still need full
    hydration when the profile *does* exist.
    """
    try:
        return await get_profile_for_compliance_match(db, user_id)
    except ProfileNotFoundException:
        return None
