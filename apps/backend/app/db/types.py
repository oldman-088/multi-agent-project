"""Portable column types shared by SQLite and PostgreSQL models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

# JSONB on PostgreSQL, JSON (text) on SQLite — same Python behaviour either way.
JSONType = JSON().with_variant(JSONB(), "postgresql")


class EnumValue(TypeDecorator[str]):
    """Store a python ``StrEnum`` as a plain string column.

    Using VARCHAR instead of a native ``ENUM`` type keeps ``alembic downgrade``
    working on PostgreSQL without extra type-dropping steps.
    """

    impl = String(48)
    cache_ok = True

    def __init__(self, enum_class: type[StrEnum], length: int = 48) -> None:
        super().__init__(length)
        self.enum_class = enum_class

    def process_bind_param(self, value: Any, _dialect: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, self.enum_class):
            return str(value.value)
        return str(value)

    def process_result_value(self, value: Any, _dialect: object) -> Any:
        if value is None:
            return None
        try:
            return self.enum_class(str(value))
        except ValueError:
            return value


#: Portable free-form text column.
LongText = Text
