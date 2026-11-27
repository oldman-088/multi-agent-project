"""Application settings for the NEXUS AGENT OS backend slice.

Environment variables are prefixed with ``NEXUS_`` (for example
``NEXUS_DATABASE_URL``). Secrets are never hard-coded: ``NEXUS_JWT_SECRET`` is
read from the environment, and when it is absent the backend generates an
ephemeral secret for the process lifetime (local-first dev convenience), which
the app factory surfaces as a warning.
"""

from __future__ import annotations

import secrets

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from ``NEXUS_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="NEXUS_", extra="ignore")

    # --- storage ---------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./nexus.db"

    # --- auth (docs/SPEC.md §2 Phase 2) -----------------------------------
    jwt_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 1800
    refresh_token_ttl_seconds: int = 7 * 24 * 3600

    # Reserved for credentials-at-rest encryption (docs/SPEC.md §3.2). No
    # credential storage exists in this slice yet, so the value is parsed and
    # kept for the future migration; nothing is encrypted with it today.
    encryption_key: str | None = None

    # --- autonomy (docs/SPEC.md §13.1, Level 3 is the default) ------------
    autonomy_level: int = Field(default=3, ge=0, le=3)

    # --- Tool Gateway ------------------------------------------------------
    # Hosts the http_get tool may contact. Anything else is denied by the
    # gateway allow-list policy (SSRF guard, docs/SPEC.md §2 Phase 2 item 7).
    http_get_allow_hosts: list[str] = ["127.0.0.1", "localhost"]
    tool_http_timeout_seconds: float = 10.0
    tool_http_max_bytes: int = 100_000

    # --- app ----------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    org_name: str = "NEXUS"
    app_name: str = "NEXUS AGENT OS"
    version: str = "0.1.0"

    #: True when NEXUS_JWT_SECRET was not provided and an ephemeral secret was
    #: generated. The app factory logs a warning in that case.
    ephemeral_jwt_secret: bool = False

    @field_validator("http_get_allow_hosts", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept either a JSON list or a comma-separated string from env."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("encryption_key")
    @classmethod
    def _validate_encryption_key(cls, value: str | None) -> str | None:
        """Cheap format check only — no crypto consumes this value yet."""
        if value is not None and not value.strip():
            raise ValueError("NEXUS_ENCRYPTION_KEY must be a non-empty value when set")
        return value

    @model_validator(mode="after")
    def _mark_ephemeral_secret(self) -> Settings:
        if "jwt_secret" not in self.model_fields_set:
            object.__setattr__(self, "ephemeral_jwt_secret", True)
        return self


__all__ = ["Settings"]
