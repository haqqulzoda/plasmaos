"""
Plasma AI - Application Configuration

Manages all application settings using Pydantic BaseSettings for
environment variable parsing and validation.
"""

from pathlib import Path

import os
from urllib.parse import urlparse
from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Build absolute path to .env file
# Current file: backend/app/core/config.py
# Target file:  .env (project root, one level above backend/)
MODULE_DIR = Path(__file__).resolve().parent  # backend/app/core/
APP_DIR = MODULE_DIR.parent                    # backend/app/
BACKEND_DIR = APP_DIR.parent                   # backend/
PROJECT_ROOT = BACKEND_DIR.parent              # plasmaos/ (project root)
ENV_PATH = PROJECT_ROOT / ".env"




class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Uses Pydantic's BaseSettings for automatic environment variable parsing
    with validation and type coercion.
    """

    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    # Database Configuration
    POSTGRES_SERVER: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: int = 6543

    ENVIRONMENT: str = "development"

    # Security
    SECRET_KEY: str
    AUTH_BRIDGE_SECRET: str | None = None
    TELEGRAM_BOT_TOKEN: str
    GEMINI_API_KEY: str | None = None  # Preferred key for compliance analyzer
    GOOGLE_API_KEY: str | None = None  # Legacy alias used by older AI modules

    # CORS
    BACKEND_CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
    ]

    # Schema management
    # Keep disabled in production so Alembic remains the single source of truth.
    AUTO_CREATE_TABLES: bool = False
    DEMO_OCR_BYPASS: bool = False
    PLASMA_ENABLE_PSEUDO_LOCALE: bool = False

    @model_validator(mode="after")
    def validate_release(self):
        if self.ENVIRONMENT not in {"development", "test", "production", "release"}:
            raise ValueError("Unsupported environment")
        if self.ENVIRONMENT in {"production", "release"}:
            dangerous = self.AUTO_CREATE_TABLES or self.DEMO_OCR_BYPASS or self.PLASMA_ENABLE_PSEUDO_LOCALE or any(
                os.getenv(name, "").lower() in {"1", "true", "yes", "on"}
                for name in ("DEMO_OCR_BYPASS", "PLASMA_ENABLE_PSEUDO_LOCALE", "NEXT_PUBLIC_ENABLE_PSEUDO_LOCALE", "ENABLE_PSEUDO_LOCALE")
            )
            if dangerous:
                raise ValueError("Unsafe release flag")
            if not self.AUTH_BRIDGE_SECRET or len(self.AUTH_BRIDGE_SECRET) < 32 or len(self.SECRET_KEY) < 32:
                raise ValueError("Release secrets must be explicitly configured")
            if not self.BACKEND_CORS_ORIGINS or any(
                urlparse(origin).scheme != "https" or not urlparse(origin).hostname
                or urlparse(origin).path or "*" in origin or urlparse(origin).username
                for origin in self.BACKEND_CORS_ORIGINS
            ):
                raise ValueError("Release requires explicit HTTPS origins")
        return self

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """
        Constructs the async PostgreSQL connection URI.
        Uses asyncpg driver for async SQLAlchemy support.
        """
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


# Global settings instance
settings = Settings()
