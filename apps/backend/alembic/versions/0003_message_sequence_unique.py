"""Make the per-conversation message sequence unique (SPEC §8.3-D chat ordering).

``messages.sequence`` was allocated with ``MAX(sequence) + 1``. Two concurrent
sends could read the same maximum, so a conversation could end up with two
messages carrying sequence 1 and the client-side ordering became ambiguous.

The unique index makes the database the arbiter: the service retries the insert
when a concurrent writer won the race, so every message gets a distinct,
gap-free, monotonically increasing sequence.

Any duplicate sequence already present is renumbered first (oldest row of each
``(conversation_id, sequence)`` group keeps the value, the others take the next
free numbers), otherwise the index could not be created on an existing database.

Revision ID: 0003_message_sequence_unique
Revises: 0002_run_event_cursor
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_message_sequence_unique"
down_revision: str | None = "0002_run_event_cursor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Renumber duplicates deterministically: rank within the conversation, keep the
#: first occurrence of a sequence and push later duplicates above the maximum.
RENUMBER_DUPLICATES = r"""
UPDATE messages
SET sequence = (
    SELECT base FROM (
        SELECT m2.id AS mid,
               (SELECT MAX(m3.sequence) FROM messages m3
                 WHERE m3.conversation_id = m2.conversation_id) + 1000 * m2.rn AS base
        FROM (
            SELECT id, conversation_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY conversation_id, sequence ORDER BY created_at, id
                   ) AS rn
            FROM messages
        ) m2
        WHERE m2.rn > 1
    ) ranked
    WHERE ranked.mid = messages.id
)
WHERE id IN (
    SELECT id FROM (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY conversation_id, sequence ORDER BY created_at, id
               ) AS rn
        FROM messages
    ) dupes
    WHERE dupes.rn > 1
)
"""

CREATE_INDEX = (
    "CREATE UNIQUE INDEX uq_messages_conversation_sequence "
    "ON messages (conversation_id, sequence)"
)
DROP_INDEX = "DROP INDEX IF EXISTS uq_messages_conversation_sequence"


def upgrade() -> None:
    op.execute(RENUMBER_DUPLICATES)
    op.execute(CREATE_INDEX)


def downgrade() -> None:
    op.execute(DROP_INDEX)
