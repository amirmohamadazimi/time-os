"""Process configuration from environment variables (``TIMEOS_*``).

User-facing preferences (timezone, working hours, modes) live in the database as
``UserSettings``; this module only holds deployment configuration and secrets.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TIMEOS_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/timeos.db"
    auto_migrate: bool = True
    api_token: str | None = None
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    default_timezone: str = "UTC"
    max_upload_mb: int = 20

    # Encrypts stored secrets (calendar links, later OAuth tokens). When unset, a random key is created
    # in secret_key_file on first use; hosts without a persistent disk must set it.
    secret_key: str | None = None
    secret_key_file: str = "./data/secret.key"

    # Phase 5 (unused until it lands)
    ai_model: str = "claude-opus-5-5"


@lru_cache
def get_config() -> Config:
    return Config()
