"""Transactional Proposal/TenderEngagement integration for explicit preparation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tender_actionability import is_tender_actionable
from app.models.all_models import Proposal, Tender
from app.models.base import (
    ProposalStatus,
    TenderEngagementOrigin,
    TenderEngagementStatus,
)
from app.models.company import CompanyProfile
from app.models.engagement import TenderEngagement
from app.services.tender_engagements import (
    TenderEngagementTransitionError,
    get_or_create_tender_engagement,
    get_tender_engagement,
    set_tender_engagement_status,
)


class BidPreparationError(RuntimeError):
    """Base error for the explicit Bid Preparation command."""


class BidPreparationOwnershipError(BidPreparationError):
    """Raised when the actor cannot authoritatively own the requested artifact."""


class BidPreparationNotFoundError(BidPreparationError):
    """Raised when a Tender or owned Proposal does not exist."""


class BidPreparationNotActionableError(BidPreparationError):
    """Raised when a new artifact cannot be created for the source Tender."""


@dataclass(frozen=True)
class ProposalArtifactResolution:
    proposal: Proposal
    created: bool


@dataclass(frozen=True)
class PrepareBidResult:
    proposal: Proposal
    tender: Tender
    engagement: TenderEngagement
    proposal_created: bool
    engagement_created: bool


async def get_or_create_proposal_artifact(
    db: AsyncSession,
    *,
    user_id: UUID,
    tender: Tender,
) -> ProposalArtifactResolution:
    """Resolve the repository's one-per-user/Tender Proposal without a race.

    This artifact-only helper deliberately does not create or mutate a
    TenderEngagement. The caller owns the transaction.
    """
    existing = await db.scalar(
        select(Proposal).where(
            Proposal.user_id == user_id,
            Proposal.tender_id == tender.id,
        )
    )
    if existing is not None:
        return ProposalArtifactResolution(proposal=existing, created=False)
    if not is_tender_actionable(tender):
        raise BidPreparationNotActionableError("Tender is not open for preparation")

    proposal_id = uuid4()
    inserted_id = await db.scalar(
        pg_insert(Proposal)
        .values(
            id=proposal_id,
            user_id=user_id,
            tender_id=tender.id,
            status=ProposalStatus.DRAFT,
            ai_confidence_score=0,
            structured_data={},
            margin_percent=20.0,
            include_vat=True,
            currency="UZS",
        )
        .on_conflict_do_nothing(constraint="uq_proposals_user_tender")
        .returning(Proposal.id)
    )
    proposal = await db.scalar(
        select(Proposal).where(
            Proposal.user_id == user_id,
            Proposal.tender_id == tender.id,
        )
    )
    if proposal is None:
        raise BidPreparationError("Proposal artifact resolution failed")
    return ProposalArtifactResolution(
        proposal=proposal,
        created=inserted_id == proposal_id,
    )


async def prepare_bid(
    db: AsyncSession,
    *,
    user_id: UUID,
    company_profile_id: UUID,
    tender_id: UUID | None = None,
    proposal_id: UUID | None = None,
) -> PrepareBidResult:
    """Atomically express current preparation intent and resolve its artifact.

    Exactly one of ``tender_id`` or ``proposal_id`` identifies the command.
    A Proposal ID is used for the explicit legacy Continue action and is never
    interpreted as a Tender ID.
    """
    if (tender_id is None) == (proposal_id is None):
        raise ValueError("exactly one of tender_id or proposal_id is required")

    profile_id = await db.scalar(
        select(CompanyProfile.id).where(
            CompanyProfile.id == company_profile_id,
            CompanyProfile.user_id == user_id,
        )
    )
    if profile_id is None:
        raise BidPreparationOwnershipError("Company profile is not owned by user")

    existing_proposal: Proposal | None = None
    if proposal_id is not None:
        existing_proposal = await db.scalar(
            select(Proposal).where(
                Proposal.id == proposal_id,
                Proposal.user_id == user_id,
            )
        )
        if existing_proposal is None:
            raise BidPreparationNotFoundError("Bid Preparation not found")
        tender_id = existing_proposal.tender_id

    tender = await db.scalar(select(Tender).where(Tender.id == tender_id))
    if tender is None:
        raise BidPreparationNotFoundError("Tender not found")
    if existing_proposal is None:
        existing_proposal = await db.scalar(
            select(Proposal).where(
                Proposal.user_id == user_id,
                Proposal.tender_id == tender.id,
            )
        )
        if existing_proposal is None and not is_tender_actionable(tender):
            raise BidPreparationNotActionableError(
                "Tender is not open for preparation"
            )

    engagement_resolution = await get_or_create_tender_engagement(
        db,
        user_id=user_id,
        company_profile_id=company_profile_id,
        tender_id=tender.id,
        status=TenderEngagementStatus.PREPARING,
        origin=TenderEngagementOrigin.BID_PREPARATION,
    )
    engagement = engagement_resolution.engagement
    if engagement.status in {
        TenderEngagementStatus.SAVED,
        TenderEngagementStatus.EVALUATING,
        TenderEngagementStatus.DISMISSED,
    }:
        try:
            engagement = await set_tender_engagement_status(
                db,
                user_id=user_id,
                company_profile_id=company_profile_id,
                tender_id=tender.id,
                status=TenderEngagementStatus.PREPARING,
            )
        except TenderEngagementTransitionError:
            # A concurrent Prepare may have completed the same transition while
            # this transaction waited for the row lock. Accept only PREPARING.
            engagement = await get_tender_engagement(
                db,
                user_id=user_id,
                company_profile_id=company_profile_id,
                tender_id=tender.id,
            )
            if engagement is None or engagement.status != TenderEngagementStatus.PREPARING:
                raise

    if existing_proposal is None:
        proposal_resolution = await get_or_create_proposal_artifact(
            db,
            user_id=user_id,
            tender=tender,
        )
        proposal = proposal_resolution.proposal
        proposal_created = proposal_resolution.created
    else:
        proposal = existing_proposal
        proposal_created = False

    return PrepareBidResult(
        proposal=proposal,
        tender=tender,
        engagement=engagement,
        proposal_created=proposal_created,
        engagement_created=engagement_resolution.created,
    )
