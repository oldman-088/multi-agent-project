"""Shared response envelopes, pagination and error schemas."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    """Base for response models read from SQLAlchemy rows."""

    model_config = ConfigDict(from_attributes=True)


class ErrorDetail(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str = Field(examples=["Agent not found"])
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Every non-2xx response uses this envelope."""

    error: ErrorDetail


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    version: str
    database: str
    environment: str
    emergency_stop_engaged: bool = False


class OkResponse(BaseModel):
    ok: bool = True
    message: str | None = None
