"""
Alembic environment configuration for async SQLAlchemy.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import Base and all models so Alembic can detect them
from app.models.all_models import Base
from app.core.config import settings

# Alembic Config object
config = context.config

# Set the sqlalchemy URL from our app settings
config.set_main_option("sqlalchemy.url", settings.SQLALCHEMY_DATABASE_URI)

# Setup logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate
target_metadata = Base.metadata


def _ensure_alembic_version_column_width(connection: Connection) -> None:
    """Allow long human-readable Alembic revision IDs.

    Older deployments created ``alembic_version.version_num`` as VARCHAR(32).
    Newer INT revision names are longer than that, so Alembic can successfully
    run the migration body but fail while updating its own version row.
    """
    connection.execute(
        text(
            """
            DO $$
            BEGIN
                IF to_regclass('alembic_version') IS NOT NULL THEN
                    ALTER TABLE alembic_version
                    ALTER COLUMN version_num TYPE VARCHAR(128);
                END IF;
            END $$;
            """
        )
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _ensure_alembic_version_column_width(connection)
    if connection.in_transaction():
        connection.commit()
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
