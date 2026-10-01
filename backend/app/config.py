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
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    default_timezone: str = "UTC"
    max_upload_mb: int = 20

    # Phase 3 / 5 (unused until those phases land)
    secret_key: str | None = None
    ai_model: str = "claude-opus-5-5"


@lru_cache
def get_config() -> Config:
    return Config()
