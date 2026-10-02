"""Process configuration from environment variables (``TIMEOS_*``).

User-facing preferences (timezone, working hours, modes) live in the database as
``UserSettings``; this module only holds deployment configuration and secrets.
"""

from functools import lru_cache

from pydantic import Field, field_validator
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
    static_dir: str | None = None  # built frontend to serve; defaults to ../frontend/dist when present

    # Encrypts stored secrets (calendar links, later OAuth tokens). When unset, a random key is created
    # in secret_key_file on first use; hosts without a persistent disk must set it.
    secret_key: str | None = None
    secret_key_file: str = "./data/secret.key"

    # Phase 5 (unused until it lands)
    ai_model: str = "claude-opus-5-5"

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, url: str) -> str:
        """Hosted Postgres (Neon, Render, …) hands out ``postgres://`` URLs; use the psycopg 3 driver."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url


@lru_cache
def get_config() -> Config:
    return Config()
