"""google_oauth_cutover

Revision ID: 20260227_0001_google_oauth_cutover
Revises:
Create Date: 2026-02-27 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260227_0001_google_oauth_cutover"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_id", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("name", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.String(length=500), nullable=True))

    # Backfill new identity columns from legacy data deterministically.
    op.execute(
        """
        UPDATE users
        SET
            email = COALESCE(NULLIF(username, ''), CONCAT('legacy-', id::text, '@local.invalid')),
            google_id = CONCAT('legacy-', id::text),
            name = COALESCE(NULLIF(full_name, ''), 'User')
        WHERE email IS NULL OR google_id IS NULL OR name IS NULL
        """
    )

    op.alter_column("users", "google_id", nullable=False)
    op.alter_column("users", "email", nullable=False)
    op.alter_column("users", "name", nullable=False)

    op.create_index("ix_users_google_id", "users", ["google_id"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_column("users", "telegram_id")
    op.drop_column("users", "username")
    op.drop_column("users", "full_name")
    op.drop_column("users", "phone_number")
    op.drop_column("users", "safety_word")

    op.drop_table("auth_sessions")
    op.execute("DROP TYPE IF EXISTS auth_session_status")


def downgrade() -> None:
    op.execute("CREATE TYPE auth_session_status AS ENUM ('PENDING', 'VERIFIED')")
    op.create_table(
        "auth_sessions",
        sa.Column("code", sa.String(length=4), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "VERIFIED", name="auth_session_status"),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("code"),
    )

    op.add_column("users", sa.Column("telegram_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("username", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("full_name", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("phone_number", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("safety_word", sa.String(length=100), nullable=True))

    op.execute("UPDATE users SET full_name = name WHERE full_name IS NULL")
    op.execute("UPDATE users SET username = email WHERE username IS NULL")
    op.execute("UPDATE users SET telegram_id = floor(random() * 9000000000)::bigint + 1000000000 WHERE telegram_id IS NULL")

    op.alter_column("users", "telegram_id", nullable=False)
    op.alter_column("users", "full_name", nullable=False)
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=False)

    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_google_id", table_name="users")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "name")
    op.drop_column("users", "email")
    op.drop_column("users", "google_id")
