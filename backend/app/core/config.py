"""Application settings, loaded from environment variables (and an optional .env file).

Variable names match .env.example. Unknown variables are ignored so that settings
used by later batches do not break this one.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_PREFIX = "replace-with"
_MIN_SECRET_LENGTH = 32
_SUPPORTED_DATABASE_PREFIX = "sqlite+aiosqlite:"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    tokenvault_env: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # "mock" is the free, offline, deterministic provider. "live" is not available yet.
    tokenvault_provider_mode: Literal["mock", "live"] = "mock"

    tokenvault_secret_key: SecretStr = SecretStr("replace-with-a-long-random-string")

    max_request_body_bytes: int = Field(default=1_048_576, ge=1024, le=52_428_800)

    # Comma-separated list of allowed browser origins. "*" is never allowed.
    cors_allowed_origins: str = "http://localhost:3000"

    # Only SQLite (via aiosqlite) is supported in this version. PostgreSQL comes later.
    database_url: str = "sqlite+aiosqlite:///./tokenvault.db"

    # In local development only, create missing tables automatically at startup.
    # Staging and production never do this; they must use migrations.
    database_auto_create: bool = True

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: str) -> str:
        origins = [item.strip() for item in value.split(",") if item.strip()]
        if "*" in origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must list explicit origins; '*' is not allowed.")
        return value

    @field_validator("database_url")
    @classmethod
    def _require_supported_database(cls, value: str) -> str:
        if not value.startswith(_SUPPORTED_DATABASE_PREFIX):
            raise ValueError(
                "DATABASE_URL must start with 'sqlite+aiosqlite:' in this version "
                "(PostgreSQL support is not available yet)."
            )
        return value

    @model_validator(mode="after")
    def _require_real_secret_outside_development(self) -> "Settings":
        if self.tokenvault_env in ("staging", "production"):
            secret = self.tokenvault_secret_key.get_secret_value()
            if secret.startswith(_PLACEHOLDER_PREFIX) or len(secret) < _MIN_SECRET_LENGTH:
                raise ValueError(
                    "TOKENVAULT_SECRET_KEY must be a real random value of at least "
                    f"{_MIN_SECRET_LENGTH} characters in staging and production."
                )
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()]

    @property
    def docs_enabled(self) -> bool:
        """Interactive API docs are only exposed in local development."""
        return self.tokenvault_env == "local"

    @property
    def should_auto_create_tables(self) -> bool:
        """Tables are only auto-created in local development, never anywhere else."""
        return self.database_auto_create and self.tokenvault_env == "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
    
