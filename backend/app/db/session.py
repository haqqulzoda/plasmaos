"""
Plasma AI - Database Session Management

Provides async database engine, session factory, and FastAPI dependency
for database session injection.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


# Create async engine with connection pooling
engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    echo=False,  # Set to True for SQL query logging during development
    pool_pre_ping=True,  # Verify connections before use
    pool_size=10,
    max_overflow=20,
)

# Session factory for creating new sessions
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session.
    
    Yields an async session and ensures proper cleanup after request.
    
    Usage:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
