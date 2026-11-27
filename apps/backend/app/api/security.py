"""Environment-backed bearer authentication; tokens are never accepted from query strings."""
import os
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class User:
    subject: str
    organization_id: str


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    expected = os.getenv("AATM_API_TOKEN")
    organization = os.getenv("AATM_ORGANIZATION_ID")
    if not expected or not organization:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    if credentials is None or credentials.scheme.lower() != "bearer" or not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=401, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    return User(subject="configured-user", organization_id=organization)
