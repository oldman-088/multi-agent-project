"""Password hashing and JWT issuing/verification (docs/SPEC.md §2 Phase 2).

Passwords are hashed with argon2. Tokens are HS256 JWTs with a ``typ`` claim
distinguishing access tokens from refresh tokens. No secret is ever hard-coded:
the signing key comes from ``Settings.jwt_secret`` (environment).
"""

from __future__ import annotations

import secrets
import time
import uuid
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from backend.app.core.config import Settings

TokenType = Literal["access", "refresh"]

_hasher = PasswordHasher()

# Hash of a random throwaway value, computed once per process. It is used when
# the login email does not exist so that "unknown user" and "wrong password"
# cost the same CPU time (user-enumeration timing guard). This is not a
# credential and hashes nothing meaningful.
CREDENTIALS_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:  # malformed stored hash — never reveal more than "invalid"
        return False


def create_token(
    settings: Settings, *, token_type: TokenType, user_id: str, organization_id: str, role: str
) -> str:
    """Issue a signed JWT for a user."""
    ttl = (
        settings.access_token_ttl_seconds
        if token_type == "access"
        else settings.refresh_token_ttl_seconds
    )
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": user_id,
        "org": organization_id,
        "role": role,
        "typ": token_type,
        "iat": now,
        "exp": now + ttl,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(settings: Settings, token: str, expected_type: TokenType) -> dict[str, Any]:
    """Verify signature/expiry/type and return the claims.

    Raises :class:`jwt.InvalidTokenError` (or ``ValueError`` for a wrong type)
    so callers can map any failure to 401.
    """
    claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if claims.get("typ") != expected_type:
        raise ValueError("wrong token type")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise ValueError("missing subject")
    return claims


__all__ = [
    "CREDENTIALS_DUMMY_HASH",
    "create_token",
    "decode_token",
    "hash_password",
    "verify_password",
]
