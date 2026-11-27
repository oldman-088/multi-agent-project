"""Declarative base, naming conventions and shared column mixins."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, String, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# Deterministic constraint names keep Alembic migrations identical on SQLite and
# PostgreSQL (SQLite otherwise auto-names constraints nondeterministically).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetimes on every backend.

    SQLite has no timezone support, so values are normalised to UTC on write and
    re-tagged as UTC on read. PostgreSQL keeps an actual ``timestamptz``.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, _dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, _dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_public_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {datetime: UTCDateTime}


class TimestampMixin:
    """``created_at`` / ``updated_at`` maintained in Python for portability."""

    @declared_attr
    @classmethod
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(UTCDateTime, default=utcnow, nullable=False)

    @declared_attr
    @classmethod
    def updated_at(cls) -> Mapped[datetime]:
        return mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class PublicIdMixin:
    """Opaque string primary key such as ``run_3f9c...``."""

    id_prefix: str = "rec"

    @declared_attr
    @classmethod
    def id(cls) -> Mapped[str]:
        return mapped_column(
            String(64),
            primary_key=True,
            default=lambda: new_public_id(cls.id_prefix),
        )
