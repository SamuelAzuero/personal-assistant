import os
from functools import lru_cache
from typing import Any, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable overrides and sensible defaults."""

    # Server settings
    app_env: str = Field(default="development", description="Application environment")
    log_level: str = Field(default="INFO", description="Logging level")
    secret_key: str = Field(
        default="change_this_to_a_secure_random_string_in_production",
        description="Application secret key",
    )
    host: str = Field(default="0.0.0.0", description="Host to bind server")
    port: int = Field(default=8080, description="Port to listen on")

    # Database settings
    database_path: str = Field(default="data/assistant.db", description="SQLite database file path or :memory:")
    persistent_db_path: Optional[str] = Field(
        default=None,
        description=(
            "Path to persistent storage file (e.g., /app/data/assistant.db on GCS volume mount) "
            "for backup and restore synchronization."
        ),
    )
    sync_on_commit: bool = Field(
        default=True,
        description="Synchronize write transactions to persistent_db_path on commit",
    )

    # Mock services toggle (default True for offline development and testing)
    mock_services: bool = Field(default=True, description="Enable simulated mocks for all external APIs")
    mock_telegram: bool = Field(default=True, description="Mock Telegram Bot API calls")
    mock_gmail: bool = Field(default=True, description="Mock Gmail API calls")
    mock_calendar: bool = Field(default=True, description="Mock Google Calendar API calls")
    mock_stt: bool = Field(default=True, description="Mock Speech-to-Text transcription")
    mock_research: bool = Field(default=True, description="Mock Web search for outing recommendations")

    # Telegram integration
    telegram_bot_token: Optional[str] = Field(default=None, description="Telegram Bot API token")
    telegram_secret_token: Optional[str] = Field(
        default=None, description="Secret token for Telegram webhook validation"
    )
    telegram_webhook_secret: Optional[str] = Field(default=None, description="Alias for webhook secret token")
    telegram_webhook_url: Optional[str] = Field(default=None, description="Public HTTPS URL for Telegram webhook")

    # User profile & localization
    user_name: str = Field(default="Samuel Azuero", description="User full name")
    currency_code: str = Field(default="COP", description="Currency code (e.g. COP, USD)")
    currency_symbol: str = Field(default="$", description="Currency display symbol")

    # Google & Email integrations
    google_client_id: Optional[str] = Field(default=None, description="Google OAuth 2.0 Client ID")
    google_client_secret: Optional[str] = Field(default=None, description="Google OAuth 2.0 Client Secret")
    google_refresh_token: Optional[str] = Field(default=None, description="Google OAuth refresh token")
    gmail_user_email: Optional[str] = Field(
        default=None, description="Primary monitored Gmail address"
    )
    secondary_gmail_user_email: Optional[str] = Field(
        default=None, description="Secondary institutional monitored Gmail address"
    )
    gmail_app_password: Optional[str] = Field(
        default=None, description="Google App Password (16 characters) for IMAP access"
    )
    secondary_gmail_app_password: Optional[str] = Field(
        default=None, description="Google App Password for secondary institutional IMAP access"
    )
    imap_host: str = Field(default="imap.gmail.com", description="IMAP server host")
    imap_port: int = Field(default=993, description="IMAP server SSL port")
    calendar_id: str = Field(default="primary", description="Target Google Calendar ID")

    # AI / LLM configuration
    gemini_api_key: Optional[str] = Field(default=None, description="Google Gemini API key for fallback reasoning")
    enable_llm_fallback: bool = Field(default=False, description="Enable LLM reasoning fallback")
    gemini_model: str = Field(default="gemini-2.5-flash", description="Gemini model name")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def __init__(self, **values: Any):
        if "PYTEST_CURRENT_TEST" in os.environ and "_env_file" not in values:
            values["_env_file"] = None
        super().__init__(**values)

    @property
    def effective_telegram_secret(self) -> Optional[str]:
        """Return the effective webhook secret token considering aliases."""
        return self.telegram_secret_token or self.telegram_webhook_secret


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
