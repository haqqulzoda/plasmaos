"""W2 canonical pursuit, lifecycle audit, and legacy engagement backfill.

Revision ID: 20260925_0002_w2_organization_pursuit
Revises: 20260925_0001_w2_organization_membership
"""

from typing import Union

from alembic import op


revision = "20260925_0002_w2_organization_pursuit"
down_revision: Union[str, None] = "20260925_0001_w2_organization_membership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE pursuit_origin AS ENUM ('SOURCE', 'UPLOAD')")
    op.execute(
        """
        CREATE TABLE organization_pursuits (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            source_tender_id UUID REFERENCES tenders(id) ON DELETE RESTRICT,
            origin pursuit_origin NOT NULL,
            legacy_engagement_id UUID UNIQUE,
            legacy_origin tender_engagement_origin,
            owner_membership_id UUID,
            stage tender_engagement_status NOT NULL,
            internal_target_at TIMESTAMPTZ,
            archived_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            stage_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_pursuit_owner_same_organization
                FOREIGN KEY (owner_membership_id, organization_id)
                REFERENCES memberships(id, organization_id) ON DELETE RESTRICT,
            CONSTRAINT ck_organization_pursuits_origin_source CHECK (
                (origin = 'SOURCE' AND source_tender_id IS NOT NULL) OR
                (origin = 'UPLOAD' AND source_tender_id IS NULL)
            ),
            CONSTRAINT ck_organization_pursuits_legacy_source CHECK (
                legacy_engagement_id IS NULL OR origin = 'SOURCE'
            ),
            CONSTRAINT ck_organization_pursuits_distinct_legacy_id CHECK (
                legacy_engagement_id IS NULL OR legacy_engagement_id <> id
            )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_organization_pursuits_source "
        "ON organization_pursuits (organization_id, source_tender_id) "
        "WHERE origin = 'SOURCE'"
    )
    op.execute(
        "CREATE INDEX ix_organization_pursuits_organization_stage "
        "ON organization_pursuits (organization_id, stage)"
    )
    op.execute(
        "CREATE INDEX ix_organization_pursuits_source_tender "
        "ON organization_pursuits (source_tender_id)"
    )
    op.execute(
        "CREATE INDEX ix_organization_pursuits_owner "
        "ON organization_pursuits (owner_membership_id)"
    )
    op.execute(
        """
        CREATE TABLE pursuit_lifecycle_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pursuit_id UUID NOT NULL REFERENCES organization_pursuits(id) ON DELETE RESTRICT,
            actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            actor_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            previous_stage tender_engagement_status,
            new_stage tender_engagement_status NOT NULL,
            action VARCHAR(50) NOT NULL,
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_pursuit_lifecycle_events_pursuit_created "
        "ON pursuit_lifecycle_events (pursuit_id, created_at)"
    )
    op.execute(
        """
        CREATE FUNCTION w2_guard_pursuit_lifecycle_event() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'pursuit_lifecycle_event_immutable' USING ERRCODE = '23514';
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER pursuit_lifecycle_event_immutable "
        "BEFORE UPDATE OR DELETE ON pursuit_lifecycle_events "
        "FOR EACH ROW EXECUTE FUNCTION w2_guard_pursuit_lifecycle_event()"
    )

    op.execute(
        """
        INSERT INTO tenancy_backfill_exceptions(entity_type, legacy_id, reason, details)
        SELECT 'ENGAGEMENT', te.id, 'INVALID_OWNER_SCOPE',
               'Engagement user/profile tuple has no exact Organization owner membership'
        FROM tender_engagements te
        LEFT JOIN organizations o ON o.legacy_company_profile_id = te.company_profile_id
        LEFT JOIN memberships m ON m.organization_id = o.id AND m.user_id = te.user_id
        WHERE o.id IS NULL OR m.id IS NULL
        ON CONFLICT (entity_type, legacy_id, reason) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO tenancy_backfill_exceptions(entity_type, legacy_id, reason, details)
        SELECT 'ENGAGEMENT', te.id, 'MISSING_TENDER',
               'Engagement tender_id does not resolve to tenders.id'
        FROM tender_engagements te
        LEFT JOIN tenders t ON t.id = te.tender_id
        WHERE t.id IS NULL
        ON CONFLICT (entity_type, legacy_id, reason) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO organization_pursuits(
            id, organization_id, source_tender_id, origin,
            legacy_engagement_id, legacy_origin, owner_membership_id, stage,
            created_at, updated_at, stage_changed_at
        )
        SELECT md5('plasma:w2:pursuit:' || te.id::text)::uuid,
               o.id, te.tender_id, 'SOURCE', te.id, te.origin,
               m.id, te.status, te.created_at, te.updated_at, te.status_changed_at
        FROM tender_engagements te
        JOIN organizations o ON o.legacy_company_profile_id = te.company_profile_id
        JOIN memberships m ON m.organization_id = o.id AND m.user_id = te.user_id
        JOIN tenders t ON t.id = te.tender_id
        ON CONFLICT (legacy_engagement_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO pursuit_lifecycle_events(
            pursuit_id, actor_user_id, actor_membership_id,
            previous_stage, new_stage, action, reason, created_at
        )
        SELECT p.id, te.user_id, p.owner_membership_id,
               NULL, p.stage, 'LEGACY_BACKFILL',
               'Migrated exactly from TenderEngagement ' || te.id::text,
               p.created_at
        FROM organization_pursuits p
        JOIN tender_engagements te ON te.id = p.legacy_engagement_id
        WHERE NOT EXISTS (
            SELECT 1 FROM pursuit_lifecycle_events e
            WHERE e.pursuit_id = p.id AND e.action = 'LEGACY_BACKFILL'
        )
        """
    )
    op.execute(
        """
        INSERT INTO tenancy_backfill_exceptions(entity_type, legacy_id, reason, details)
        SELECT 'PROPOSAL', p.id, 'NO_EXACT_SOURCE_PURSUIT',
               'No source pursuit resolves through Proposal.user_id -> CompanyProfile -> Organization + Tender'
        FROM proposals p
        LEFT JOIN company_profiles cp ON cp.user_id = p.user_id
        LEFT JOIN organizations o ON o.legacy_company_profile_id = cp.id
        LEFT JOIN organization_pursuits opu
          ON opu.organization_id = o.id AND opu.source_tender_id = p.tender_id
         AND opu.origin = 'SOURCE'
        WHERE opu.id IS NULL
        ON CONFLICT (entity_type, legacy_id, reason) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO tenancy_backfill_exceptions(entity_type, legacy_id, reason, details)
        SELECT 'ANALYSIS', a.id, 'NO_EXACT_SOURCE_PURSUIT',
               'Owned analysis has no source pursuit for its exact profile Organization + Tender'
        FROM tender_analyses a
        LEFT JOIN organizations o ON o.legacy_company_profile_id = a.company_profile_id
        LEFT JOIN organization_pursuits opu
          ON opu.organization_id = o.id AND opu.source_tender_id = a.tender_id
         AND opu.origin = 'SOURCE'
        WHERE a.ownership_state = 'OWNED' AND opu.id IS NULL
        ON CONFLICT (entity_type, legacy_id, reason) DO NOTHING
        """
    )
    op.execute(
        """
        DO $$
        DECLARE valid_engagements bigint; mapped_engagements bigint;
        BEGIN
            SELECT count(*) INTO valid_engagements
            FROM tender_engagements te
            JOIN organizations o ON o.legacy_company_profile_id = te.company_profile_id
            JOIN memberships m ON m.organization_id = o.id AND m.user_id = te.user_id
            JOIN tenders t ON t.id = te.tender_id;
            SELECT count(*) INTO mapped_engagements
            FROM organization_pursuits WHERE legacy_engagement_id IS NOT NULL;
            IF mapped_engagements <> valid_engagements THEN
                RAISE EXCEPTION 'W2 engagement backfill count mismatch: valid %, mapped %',
                    valid_engagements, mapped_engagements;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER pursuit_lifecycle_event_immutable ON pursuit_lifecycle_events")
    op.execute("DROP FUNCTION w2_guard_pursuit_lifecycle_event()")
    op.drop_table("pursuit_lifecycle_events")
    op.drop_table("organization_pursuits")
    op.execute("DROP TYPE pursuit_origin")
