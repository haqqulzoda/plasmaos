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

    # Organization-private uploads. The default is outside every public webroot.
    PRIVATE_DOCUMENT_STORAGE_ROOT: str = str(PROJECT_ROOT / ".private-storage")
    PRIVATE_DOCUMENT_SCAN_HOST: str = "clamav"
    PRIVATE_DOCUMENT_SCAN_PORT: int = 3310
    PRIVATE_DOCUMENT_SCAN_TIMEOUT_SECONDS: int = 30
    PRIVATE_DOCUMENT_OCR_MAX_PAGES: int = 25
    # Absolute origin of the customer app (https://app.example), used for links in
    # invitations and e-mails. Unset: invitation links are returned as relative paths.
    PUBLIC_APP_URL: str | None = None
    # R3 Task 4: SMTP e-mail channel. Disabled unless SMTP_HOST and SMTP_FROM are set.
    # SMTP_TLS: "starttls" (default, port 587), "ssl" (implicit TLS, port 465) or
    # "none" (development and tests only; refused in production).
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str | None = None
    SMTP_TLS: str = "starttls"
    SMTP_TIMEOUT_SECONDS: int = 20
    # P1: alerts to the Plasma team (new self sign-up, pilot requests). Telegram when the chat id
    # is set (bot token: ADMIN_ALERT_TELEGRAM_BOT_TOKEN, else TELEGRAM_BOT_TOKEN); otherwise
    # e-mail to PLASMA_ADMIN_EMAILS through the SMTP channel.
    ADMIN_ALERT_TELEGRAM_CHAT_ID: str | None = None
    ADMIN_ALERT_TELEGRAM_BOT_TOKEN: str | None = None
    # P1: the Explore view's "Book a call" link (a scheduling page); unset: the button sends a
    # call request to the team instead.
    PUBLIC_BOOK_CALL_URL: str | None = None
    # B1: billing. Card payments through Polar: the sandbox (https://sandbox-api.polar.sh) unless
    # POLAR_ENV=production, which only a production/release ENVIRONMENT accepts. POLAR_PRODUCT_IDS is
    # JSON: {"pilot": "<uuid>", "pursuit_desk": "<uuid>", "extra_pursuit": "<uuid>"}. Card checkout is
    # offered when the token and the product ids are set; webhooks need POLAR_WEBHOOK_SECRET.
    POLAR_ACCESS_TOKEN: str | None = None
    POLAR_WEBHOOK_SECRET: str | None = None
    POLAR_ENV: str = "sandbox"
    POLAR_PRODUCT_IDS: str | None = None
    # Bank transfer invoices: the seller, and the bank details per currency (lines separated by " | ").
    # Bank transfer is offered when the details for the invoice's currency are set.
    INVOICE_SELLER_NAME: str = "Plasma AI Solutions"
    INVOICE_SELLER_ADDRESS: str = "Tashkent, Uzbekistan"
    INVOICE_SELLER_TIN: str | None = None
    INVOICE_SELLER_EMAIL: str = "hq@plasmaos.uz"
    INVOICE_SELLER_PHONE: str = "+998 94 877 87 83"
    INVOICE_BANK_DETAILS_UZS: str | None = None
    INVOICE_BANK_DETAILS_USD: str | None = None
    # The kickoff booking link in the welcome e-mail; unset: PUBLIC_BOOK_CALL_URL.
    BILLING_KICKOFF_URL: str | None = None

    @model_validator(mode="after")
    def validate_release(self):
        if self.ENVIRONMENT not in {"development", "test", "production", "release"}:
            raise ValueError("Unsupported environment")
        if self.POLAR_ENV not in {"sandbox", "production"}:
            raise ValueError("POLAR_ENV must be sandbox or production")
        if self.POLAR_ENV == "production" and self.ENVIRONMENT not in {"production", "release"}:
            raise ValueError("Polar production keys are refused outside a production environment")
        if self.ENVIRONMENT in {"production", "release"}:
            dangerous = self.AUTO_CREATE_TABLES or self.DEMO_OCR_BYPASS or self.PLASMA_ENABLE_PSEUDO_LOCALE or any(
                os.getenv(name, "").lower() in {"1", "true", "yes", "on"}
                for name in ("DEMO_OCR_BYPASS", "PLASMA_ENABLE_PSEUDO_LOCALE", "NEXT_PUBLIC_ENABLE_PSEUDO_LOCALE", "ENABLE_PSEUDO_LOCALE")
            )
            if dangerous:
                raise ValueError("Unsafe release flag")
            if not self.AUTH_BRIDGE_SECRET or len(self.AUTH_BRIDGE_SECRET) < 32 or len(self.SECRET_KEY) < 32:
                raise ValueError("Release secrets must be explicitly configured")
            if not self.PRIVATE_DOCUMENT_SCAN_HOST or not (1 <= self.PRIVATE_DOCUMENT_SCAN_PORT <= 65535):
                raise ValueError("Release requires a private document malware scanner")
            if self.SMTP_HOST and self.SMTP_TLS not in {"starttls", "ssl"}:
                raise ValueError("Release e-mail requires SMTP_TLS starttls or ssl")
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
