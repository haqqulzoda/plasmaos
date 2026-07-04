"""s1_1_access_foundation

Revision ID: 20260624_0001_s1_1_access_foundation
Revises: 20260610_0001_multi_source_tender_foundation
Create Date: 2026-06-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260624_0001_s1_1_access_foundation"
down_revision: Union[str, None] = "20260610_0001_multi_source_tender_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_check_if_missing(*, table: str, name: str, condition: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{name}'
            ) THEN
                ALTER TABLE {table}
                ADD CONSTRAINT {name}
                CHECK ({condition});
            END IF;
        END $$;
        """
    )


def _add_fk_if_missing(
    *,
    table: str,
    name: str,
    column: str,
    referred_table: str = "users",
    referred_column: str = "id",
) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{name}'
            ) THEN
                ALTER TABLE {table}
                ADD CONSTRAINT {name}
                FOREIGN KEY ({column})
                REFERENCES {referred_table}({referred_column})
                ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "approval_status",
            sa.String(length=20),
            server_default="pending",
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "platform_role",
            sa.String(length=30),
            server_default="pilot_user",
            nullable=True,
        ),
    )
    op.add_column("users", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("users", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        UPDATE users
        SET
            approval_status = 'approved',
            platform_role = CASE
                WHEN is_admin IS TRUE THEN 'admin'
                ELSE 'pilot_user'
            END
        """
    )

    op.alter_column("users", "approval_status", nullable=False)
    op.alter_column("users", "platform_role", nullable=False)
    _add_fk_if_missing(
        table="users",
        name="fk_users_approved_by_user_id_users",
        column="approved_by_user_id",
    )
    _add_check_if_missing(
        table="users",
        name="ck_users_approval_status_allowed",
        condition="approval_status IN ('pending', 'approved', 'rejected', 'disabled')",
    )
    _add_check_if_missing(
        table="users",
        name="ck_users_platform_role_allowed",
        condition="platform_role IN ('admin', 'operator', 'pilot_user')",
    )
    op.create_index("ix_users_approval_status", "users", ["approval_status"], unique=False)
    op.create_index("ix_users_platform_role", "users", ["platform_role"], unique=False)

    op.add_column("company_profiles", sa.Column("industry", sa.String(length=255), nullable=True))
    op.add_column("company_profiles", sa.Column("website", sa.String(length=500), nullable=True))
    op.add_column("company_profiles", sa.Column("target_regions", sa.JSON(), nullable=True))
    op.add_column("company_profiles", sa.Column("target_countries", sa.JSON(), nullable=True))
    op.add_column("company_profiles", sa.Column("target_services", sa.JSON(), nullable=True))
    op.add_column(
        "company_profiles",
        sa.Column(
            "pilot_status",
            sa.String(length=30),
            server_default="scoped_pilot",
            nullable=True,
        ),
    )
    op.add_column(
        "company_profiles",
        sa.Column(
            "approval_status",
            sa.String(length=20),
            server_default="pending",
            nullable=True,
        ),
    )
    op.add_column("company_profiles", sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("company_profiles", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("company_profiles", sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("company_profiles", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("company_profiles", sa.Column("rejection_reason", sa.Text(), nullable=True))

    op.execute(
        """
        UPDATE company_profiles
        SET
            approval_status = 'approved',
            pilot_status = 'scoped_pilot',
            created_by_user_id = COALESCE(created_by_user_id, user_id)
        """
    )

    op.alter_column("company_profiles", "approval_status", nullable=False)
    op.alter_column("company_profiles", "pilot_status", nullable=False)
    _add_fk_if_missing(
        table="company_profiles",
        name="fk_company_profiles_created_by_user_id_users",
        column="created_by_user_id",
    )
    _add_fk_if_missing(
        table="company_profiles",
        name="fk_company_profiles_approved_by_user_id_users",
        column="approved_by_user_id",
    )
    _add_check_if_missing(
        table="company_profiles",
        name="ck_company_profiles_pilot_status_allowed",
        condition=(
            "pilot_status IN ('lead', 'scoped_pilot', 'active_pilot', "
            "'at_risk', 'converted', 'paused')"
        ),
    )
    _add_check_if_missing(
        table="company_profiles",
        name="ck_company_profiles_approval_status_allowed",
        condition="approval_status IN ('pending', 'approved', 'rejected', 'disabled')",
    )
    op.create_index(
        "ix_company_profiles_approval_status",
        "company_profiles",
        ["approval_status"],
        unique=False,
    )
    op.create_index(
        "ix_company_profiles_pilot_status",
        "company_profiles",
        ["pilot_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_company_profiles_pilot_status", table_name="company_profiles")
    op.drop_index("ix_company_profiles_approval_status", table_name="company_profiles")
    op.execute("ALTER TABLE company_profiles DROP CONSTRAINT IF EXISTS ck_company_profiles_approval_status_allowed")
    op.execute("ALTER TABLE company_profiles DROP CONSTRAINT IF EXISTS ck_company_profiles_pilot_status_allowed")
    op.execute("ALTER TABLE company_profiles DROP CONSTRAINT IF EXISTS fk_company_profiles_approved_by_user_id_users")
    op.execute("ALTER TABLE company_profiles DROP CONSTRAINT IF EXISTS fk_company_profiles_created_by_user_id_users")
    op.drop_column("company_profiles", "rejection_reason")
    op.drop_column("company_profiles", "rejected_at")
    op.drop_column("company_profiles", "approved_by_user_id")
    op.drop_column("company_profiles", "approved_at")
    op.drop_column("company_profiles", "created_by_user_id")
    op.drop_column("company_profiles", "approval_status")
    op.drop_column("company_profiles", "pilot_status")
    op.drop_column("company_profiles", "target_services")
    op.drop_column("company_profiles", "target_countries")
    op.drop_column("company_profiles", "target_regions")
    op.drop_column("company_profiles", "website")
    op.drop_column("company_profiles", "industry")

    op.drop_index("ix_users_platform_role", table_name="users")
    op.drop_index("ix_users_approval_status", table_name="users")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_platform_role_allowed")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_approval_status_allowed")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS fk_users_approved_by_user_id_users")
    op.drop_column("users", "disabled_at")
    op.drop_column("users", "rejection_reason")
    op.drop_column("users", "rejected_at")
    op.drop_column("users", "approved_by_user_id")
    op.drop_column("users", "approved_at")
    op.drop_column("users", "platform_role")
    op.drop_column("users", "approval_status")
