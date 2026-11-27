"""Password hashing, secret encryption, token minting and credential references.

Security properties (SPEC §3.2):
- passwords are hashed with argon2id, never stored or logged in clear text;
- credentials are encrypted at rest with Fernet (AES-128-CBC + HMAC);
- ``env:VAR_NAME`` indirection keeps API keys out of the database and the logs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings
from app.core.errors import ValidationFailedError

_hasher = PasswordHasher()
_ENV_REF = re.compile(r"^env:[A-Z][A-Z0-9_]*$")

TokenType = Literal["access", "refresh"]


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """Hash a password with argon2id. Returns the encoded hash."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time-ish verification that never raises for bad input."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
def create_token(
    *,
    subject: str,
    token_type: TokenType,
    secret: str,
    algorithm: str = "HS256",
    ttl_seconds: int = 3600,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Mint a signed JWT. ``type`` distinguishes access from refresh tokens."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    if extra_claims:
        payload.update(extra_claims)
    encoded = jwt.encode(payload, secret, algorithm=algorithm)
    return encoded if isinstance(encoded, str) else encoded.decode("utf-8")


def decode_token(token: str, *, secret: str, algorithm: str = "HS256") -> dict[str, Any]:
    """Decode and validate a JWT, raising AuthenticationError-compatible errors."""
    from app.core.errors import AuthenticationError

    try:
        return jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid token", code="invalid_token") from exc


def token_fingerprint(token: str) -> str:
    """SHA-256 of a token so refresh tokens can be stored without the plaintext."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


# --------------------------------------------------------------------------- #
# Secret encryption at rest
# --------------------------------------------------------------------------- #
def _derive_fernet_key(settings: Settings) -> bytes:
    """Use the configured key, or derive a stable development key.

    A production deployment must set ``NEXUS_ENCRYPTION_KEY``; in development we
    derive a deterministic key from the JWT secret so restarting the dev server
    does not invalidate stored credentials.
    """
    configured = settings.encryption_key
    if configured:
        key = configured.encode("utf-8")
        try:
            Fernet(key)
        except (ValueError, TypeError) as exc:
            raise ValidationFailedError(
                "NEXUS_ENCRYPTION_KEY is not a valid Fernet key",
                code="invalid_encryption_key",
            ) from exc
        return key
    seed = f"{settings.jwt_secret}:nexus-dev-encryption".encode()
    return base64.urlsafe_b64encode(hashlib.sha256(seed).digest())


class SecretBox:
    """Encrypt/decrypt secrets at rest. Never logs plaintext."""

    def __init__(self, settings: Settings) -> None:
        self._fernet = Fernet(_derive_fernet_key(settings))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise ValidationFailedError(
                "Stored credential could not be decrypted", code="credential_unreadable"
            ) from exc


# --------------------------------------------------------------------------- #
# Credential references
# --------------------------------------------------------------------------- #
def validate_credential_ref(value: str) -> str:
    """Accept only ``env:VAR_NAME`` references or encrypted blobs.

    Raw keys, passwords and cookies must never be persisted, so anything that
    reaches the database has to be an indirection or already-encrypted text.
    """
    if not value or not isinstance(value, str):
        raise ValidationFailedError("credential reference is required", code="invalid_credential")
    if _ENV_REF.match(value):
        return value
    if value.startswith("fernet:") and len(value) > 20:
        return value
    raise ValidationFailedError(
        "Credential must use env:VAR_NAME indirection or an encrypted value",
        code="invalid_credential",
        details={"hint": "never store raw API keys, passwords or cookies"},
    )


def resolve_credential_ref(value: str) -> str | None:
    """Resolve ``env:VAR_NAME`` to its value. Never call this from a log path."""
    if value.startswith("env:"):
        return os.environ.get(value[4:])
    return None


def generate_pairing_code(length: int = 8) -> str:
    """Human-transferable, unambiguous one-time code (no 0/O/1/I)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def new_id(prefix: str) -> str:
    """Prefixed opaque id, e.g. ``run_3f9c...``."""
    return f"{prefix}_{secrets.token_hex(12)}"
