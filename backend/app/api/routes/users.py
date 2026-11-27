"""User and organization management (docs/SPEC.md §2 Phase 2 RBAC).

- ``POST /api/users`` creates a user in the caller's organization (admin+).
- ``POST /api/organizations`` creates a new organization (owner only).
- ``POST /api/organizations/{org_id}/users`` provisions a user into ANY
  organization (owner only) — in this local-first slice the bootstrap owner is
  the platform owner and may provision test/admin users across organizations.
  admin/member/viewer roles remain strictly organization-scoped.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_user, get_db
from backend.app.core.security import hash_password
from backend.app.models import Organization, User
from backend.app.schemas import (
    OrganizationCreateRequest,
    OrganizationOut,
    UserCreateRequest,
    UserOut,
)

router = APIRouter(tags=["users"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,  # type: ignore[arg-type]
        organization_id=user.organization_id,
    )


@router.post("/api/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> UserOut:
    """Create a user in the caller's organization. Requires admin or owner."""
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    existing = await session.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    new_user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        organization_id=user.organization_id,
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)
    return _user_out(new_user)


@router.post(
    "/api/organizations", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED
)
async def create_organization(
    payload: OrganizationCreateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> OrganizationOut:
    """Create an additional organization. Owner-only."""
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    org = Organization(name=payload.name)
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return OrganizationOut.model_validate(org)


@router.post(
    "/api/organizations/{org_id}/users", response_model=UserOut, status_code=status.HTTP_201_CREATED
)
async def create_user_in_organization(
    org_id: str,
    payload: UserCreateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> UserOut:
    """Provision a user into the given organization. Owner-only (platform owner)."""
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    existing = await session.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    new_user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        organization_id=org.id,
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)
    return _user_out(new_user)
