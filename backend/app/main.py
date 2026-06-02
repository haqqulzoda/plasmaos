"""
Plasma AI - FastAPI Application Entry Point

Main application setup with CORS middleware and core endpoints.
"""

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.endpoints import auth, hunter, proposals, tenders, users, vault
from app.api.routers import audit
from app.core.agents.requirement_extractor import EXTRACTOR_SCHEMA_VERSION
from app.core.config import settings
from app.db.session import engine
from app.models.all_models import Base
from app.models import audit as audit_models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan with startup/shutdown events."""
    print("--- LIFESPAN: STARTING ---")
    print("--- CHECKING DB CONNECTION ---")
    
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        print("--- DB CONNECTION SUCCESS ---")
    except Exception as e:
        print(f"--- DB CONNECTION FAILED: {e} ---")
    
    if settings.AUTO_CREATE_TABLES:
        # Local/dev escape hatch only. Production schema changes should run via Alembic.
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            print("--- TABLES CREATED/VERIFIED ---")
        except Exception as e:
            print(f"--- TABLE CREATION FAILED: {e} ---")
    else:
        print("--- AUTO TABLE CREATION DISABLED; USING ALEMBIC SCHEMA ---")
    
    yield  # App runs here
    
    print("--- LIFESPAN: SHUTTING DOWN ---")


# Application version
VERSION = "0.2.0"

# Initialize FastAPI application
app = FastAPI(
    title="Plasma AI - Autonomous Tender Officer",
    description="B2B SaaS for Tender Automation in Uzbekistan",
    version=VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(tenders.router, prefix="/api/v1/tenders", tags=["Tenders"])
app.include_router(proposals.router, prefix="/api/v1/proposals", tags=["Proposals"])
app.include_router(vault.router, prefix="/api/v1", tags=["Vault"])
app.include_router(audit.router, prefix="/api/v1/audit", tags=["Audit"])
app.include_router(audit.router, prefix="/audit", tags=["Audit"])
app.include_router(hunter.router, prefix="/api/v1/hunter", tags=["Hunter"])


@app.get("/health")
async def health_check() -> dict[str, str]:
    """
    Health check endpoint for load balancers and monitoring.
    
    Returns:
        JSON object with service status, project name, and version.
    """
    return {
        "status": "ok",
        "project": "Plasma AI",
        "version": VERSION,
        "build_sha": os.getenv("PLASMA_BUILD_SHA", "unknown"),
        "build_time": os.getenv("PLASMA_BUILD_TIME", "unknown"),
        "extractor_schema_version": EXTRACTOR_SCHEMA_VERSION,
    }

