"""Auth routes: first-run bootstrap, login, refresh, me (docs/SPEC.md §2).

Public by nature: ``/api/auth/bootstrap`` (first run only), ``/api/auth/login``
and ``/api/auth/refresh``. Everything else in the API requires a bearer token
(enforced by :func:`backend.app.api.deps.get_current_user`).
"""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_user, get_db, get_settings, verify_login_password
from backend.app.core.config import Settings
from backend.app.core.security import create_token, decode_token, hash_password
from backend.app.models import Organization, User
from backend.app.schemas import (
    BootstrapRequest,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
    UserOut,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token_response(settings: Settings, user: User) -> TokenResponse:
    access = create_token(
        settings,
        token_type="access",
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role,
    )
    refresh = create_token(
        settings,
        token_type="refresh",
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role,
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user=UserOut(
            id=user.id,
            email=user.email,
            role=user.role,  # type: ignore[arg-type]
            organization_id=user.organization_id,
        ),
    )


@router.post("/bootstrap", response_model=TokenResponse)
async def bootstrap(
    payload: BootstrapRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Create the first organization + owner account (first run only).

    Returns 409 once any user exists — the local owner account is created on
    first run exactly once (docs/SPEC.md §2 Phase 2 item 1).
    """
    user_count = await session.scalar(select(func.count()).select_from(User))
    if user_count and user_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already bootstrapped; log in instead",
        )
    org = Organization(name=payload.org_name or settings.org_name)
    session.add(org)
    await session.flush()  # assigns org.id (column defaults apply at flush)
    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role="owner",
        organization_id=org.id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return _token_response(settings, user)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Password login; unknown user and wrong password return the same 401."""
    user = await session.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None:
        verify_login_password(payload.password, None)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not verify_login_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return _token_response(settings, user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Exchange a valid refresh token for a fresh token pair."""
    try:
        decode_token(settings, payload.refresh_token, "refresh")
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        ) from None
    claims = jwt.decode(
        payload.refresh_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
    user = await session.get(User, str(claims["sub"]))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    return _token_response(settings, user)


@router.get("/me", response_model=MeResponse)
async def me(user: Annotated[User, Depends(get_current_user)]) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        role=user.role,  # type: ignore[arg-type]
        organization_id=user.organization_id,
    )
