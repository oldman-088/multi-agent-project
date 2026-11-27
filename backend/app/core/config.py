"""Typed application settings.

Every secret is read from the environment. Nothing sensitive is ever written to
disk by this module, and calling ``redacted_dump`` is the only supported way to
log configuration.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = ""  # empty in production unless NEXUS_JWT_SECRET is set


class Settings(BaseSettings):
    """Runtime configuration for the backend."""

    model_config = SettingsConfigDict(
        env_prefix="NEXUS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./nexus.db"
    db_echo: bool = False

    # Auth
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_ttl_seconds: int = 3600
    refresh_token_ttl_seconds: int = 2_592_000  # 30 days
    max_failed_logins: int = 5
    lockout_seconds: int = 300

    # Encryption of credentials at rest (Fernet key, base64 url-safe 32 bytes)
    encryption_key: str | None = None

    # Bridge
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 8790
    bridge_allowed_origins: list[str] = Field(default_factory=list)

    # Providers (all off by default)
    openai_enabled: bool = False
    openai_base_url: str | None = None
    openai_api_key_ref: str | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"

    @field_validator("bridge_host")
    @classmethod
    def _bridge_must_be_loopback(cls, value: str) -> str:
        """The bridge must bind loopback only (SPEC §3.2)."""
        if value not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError(
                "bridge_host must be a loopback address; the bridge never listens publicly"
            )
        return value

    @field_validator("bridge_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def redacted_dump(self) -> dict[str, object]:
        """Configuration safe to log: secrets are always replaced."""
        data = self.model_dump()
        for key in ("jwt_secret", "encryption_key", "openai_api_key_ref"):
            if data.get(key):
                data[key] = "***redacted***"
        return data


@lru_cache
def get_settings() -> Settings:
    return Settings()
