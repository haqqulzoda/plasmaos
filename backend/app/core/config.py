"""
Plasma AI - Application Configuration

Manages all application settings using Pydantic BaseSettings for
environment variable parsing and validation.
"""

from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Build absolute path to .env file
# Current file: backend/app/core/config.py
# Target file:  .env (project root, one level above backend/)
MODULE_DIR = Path(__file__).resolve().parent  # backend/app/core/
APP_DIR = MODULE_DIR.parent                    # backend/app/
BACKEND_DIR = APP_DIR.parent                   # backend/
PROJECT_ROOT = BACKEND_DIR.parent              # plasmaos/ (project root)
ENV_PATH = PROJECT_ROOT / ".env"

print(f"--- LOADING CONFIG FROM: {ENV_PATH} ---")


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
    )
    
    # Database Configuration
    POSTGRES_SERVER: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: int = 6543
    
    # Security
    SECRET_KEY: str
    TELEGRAM_BOT_TOKEN: str
    GOOGLE_API_KEY: str | None = None  # Optional AI integration
    
    # CORS
    BACKEND_CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "https://plasmaos.uz",
    ]
    
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

# Debug: Print connection info (password masked)
print(f"--- DB URI: postgresql+asyncpg://{settings.POSTGRES_USER}:****@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB} ---")
