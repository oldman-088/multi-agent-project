"""Shared FastAPI dependencies: DB session, settings, auth and RBAC."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings
from backend.app.core.security import CREDENTIALS_DUMMY_HASH, decode_token, verify_password
from backend.app.models import User

_bearer = HTTPBearer(auto_error=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Authenticate via ``Authorization: Bearer <access token>`` (401 otherwise)."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    settings: Settings = request.app.state.settings
    try:
        claims = decode_token(settings, credentials.credentials, "access")
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    user = await session.get(User, claims["sub"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return user


def verify_login_password(password: str, password_hash: str | None) -> bool:
    """Verify a password, always spending argon2 time (timing guard)."""
    return verify_password(password, password_hash or CREDENTIALS_DUMMY_HASH)


def require_roles(*allowed_roles: str):
    """RBAC dependency factory (docs/SPEC.md §2 Phase 2 service-layer checks)."""

    async def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency


async def get_org_run_or_404(session: AsyncSession, run_id: str, user: User):
    """Fetch a run scoped to the caller's organization; 404 avoids existence leaks."""
    from backend.app.models import Run

    run = await session.get(Run, run_id)
    if run is None or run.organization_id != user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


__all__ = [
    "get_current_user",
    "get_db",
    "get_org_run_or_404",
    "get_settings",
    "require_roles",
    "verify_login_password",
]
