"""W2 organization and durable membership foundation.

Revision ID: 20260925_0001_w2_organization_membership
Revises: 20260912_0001_s10_5_communications
"""

from typing import Union

from alembic import op


revision = "20260925_0001_w2_organization_membership"
down_revision: Union[str, None] = "20260912_0001_s10_5_communications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE membership_role AS ENUM ('OWNER', 'MEMBER')")
    op.execute("CREATE TYPE membership_state AS ENUM ('INVITED', 'ACTIVE', 'REVOKED')")
    op.execute(
        """
        CREATE TABLE organizations (
            id UUID PRIMARY KEY,
            legacy_company_profile_id UUID NOT NULL
                REFERENCES company_profiles(id) ON DELETE RESTRICT,
            display_name VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_organizations_legacy_company_profile
                UNIQUE (legacy_company_profile_id)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_organizations_legacy_profile "
        "ON organizations (legacy_company_profile_id)"
    )
    op.execute(
        """
        CREATE TABLE memberships (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            role membership_role NOT NULL,
            state membership_state NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            activated_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            CONSTRAINT uq_memberships_organization_user UNIQUE (organization_id, user_id),
            CONSTRAINT uq_memberships_id_organization UNIQUE (id, organization_id),
            CONSTRAINT ck_memberships_lifecycle_timestamps CHECK (
                (state = 'ACTIVE' AND activated_at IS NOT NULL AND revoked_at IS NULL) OR
                (state = 'INVITED' AND activated_at IS NULL AND revoked_at IS NULL) OR
                (state = 'REVOKED' AND revoked_at IS NOT NULL)
            )
        )
        """
    )
    op.execute("CREATE INDEX ix_memberships_user_state ON memberships (user_id, state)")
    op.execute(
        "CREATE INDEX ix_memberships_organization_state "
        "ON memberships (organization_id, state)"
    )
    op.execute(
        """
        CREATE TABLE tenancy_backfill_exceptions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_type VARCHAR(30) NOT NULL,
            legacy_id UUID NOT NULL,
            reason VARCHAR(100) NOT NULL,
            details TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_tenancy_backfill_exception
                UNIQUE (entity_type, legacy_id, reason)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_tenancy_backfill_exceptions_entity "
        "ON tenancy_backfill_exceptions (entity_type, reason)"
    )

    # These rows should be impossible under the existing FK, but record rather
    # than guess if a deployment has historical integrity damage.
    op.execute(
        """
        INSERT INTO tenancy_backfill_exceptions(entity_type, legacy_id, reason, details)
        SELECT 'COMPANY_PROFILE', cp.id, 'MISSING_OWNER_USER',
               'CompanyProfile.user_id does not resolve to users.id'
        FROM company_profiles cp
        LEFT JOIN users u ON u.id = cp.user_id
        WHERE u.id IS NULL
        ON CONFLICT (entity_type, legacy_id, reason) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO organizations(id, legacy_company_profile_id, display_name, created_at, updated_at)
        SELECT md5('plasma:w2:organization:' || cp.id::text)::uuid,
               cp.id, cp.company_name, now(), now()
        FROM company_profiles cp
        JOIN users u ON u.id = cp.user_id
        ON CONFLICT (legacy_company_profile_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO memberships(
            id, organization_id, user_id, role, state,
            created_at, updated_at, activated_at, revoked_at
        )
        SELECT md5('plasma:w2:membership:' || o.id::text || ':' || cp.user_id::text)::uuid,
               o.id, cp.user_id, 'OWNER', 'ACTIVE',
               now(), now(), now(), NULL
        FROM company_profiles cp
        JOIN organizations o ON o.legacy_company_profile_id = cp.id
        JOIN users u ON u.id = cp.user_id
        ON CONFLICT (organization_id, user_id) DO NOTHING
        """
    )
    op.execute(
        """
        DO $$
        DECLARE valid_profiles bigint; mapped_profiles bigint; owner_memberships bigint;
        BEGIN
            SELECT count(*) INTO valid_profiles
            FROM company_profiles cp JOIN users u ON u.id = cp.user_id;
            SELECT count(*) INTO mapped_profiles FROM organizations;
            SELECT count(*) INTO owner_memberships
            FROM organizations o JOIN memberships m ON m.organization_id = o.id
            WHERE m.role = 'OWNER' AND m.state = 'ACTIVE';
            IF mapped_profiles <> valid_profiles OR owner_memberships <> valid_profiles THEN
                RAISE EXCEPTION 'W2 organization backfill count mismatch: profiles %, organizations %, owners %',
                    valid_profiles, mapped_profiles, owner_memberships;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.drop_table("tenancy_backfill_exceptions")
    op.drop_table("memberships")
    op.drop_table("organizations")
    op.execute("DROP TYPE membership_state")
    op.execute("DROP TYPE membership_role")
