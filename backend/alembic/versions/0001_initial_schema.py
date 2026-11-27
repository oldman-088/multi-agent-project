"""initial schema — organizations, users, runs, events, tool_calls,
approvals, emergency_stop

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-27

The schema is generated from the models metadata (single source of truth);
hand-written ops begin with the second migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from backend.app.models import Base

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
