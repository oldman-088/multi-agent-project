"""Per-run counters for an atomic event sequence (SPEC §7 "sequence is monotonic per run").

``events.sequence`` was allocated by reading ``runs.last_sequence`` and adding one.
Two concurrent appends could read the same value, and the ``uq_events_run_sequence``
constraint then turned the loser into an opaque 500. The counter is now bumped with
a single ``UPDATE ... RETURNING`` statement, which the database serialises, and the
new value is reserved on the row before any event is inserted.

A run that starts later must still never reuse a sequence, so ``last_sequence`` is
backfilled to the highest sequence actually persisted (and to the highest reserved
value, whichever is greater) before the new behaviour takes over.

Revision ID: 0002_run_event_cursor
Revises: 0001_initial
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_run_event_cursor"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Portable on SQLite (3.35+) and PostgreSQL 16: table-level subqueries are not
#: used, so no dialect branching is needed for the backfill.
BACKFILL = r"""
UPDATE runs
SET last_sequence = CASE
    WHEN last_sequence IS NULL THEN COALESCE(
        (SELECT MAX(events.sequence) FROM events WHERE events.run_id = runs.id), 0)
    WHEN last_sequence < COALESCE(
        (SELECT MAX(events.sequence) FROM events WHERE events.run_id = runs.id), 0)
        THEN COALESCE(
        (SELECT MAX(events.sequence) FROM events WHERE events.run_id = runs.id), 0)
    ELSE last_sequence
END
"""


def upgrade() -> None:
    op.execute(BACKFILL)


def downgrade() -> None:
    # Nothing structural changed: the counters are a superset of the events that
    # exist, so rolling back is a no-op rather than a destructive rewrite.
    pass
