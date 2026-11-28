"""Orchestration package: the shared task manifest used by the orchestration
engine (Worker 4) and the execution tasks.

The task-manifest data schema is defined by the shared contract at
``docs/ORCHESTRATION.md``. See :mod:`orchestrator.manifest` for the reader and
validator that implement that contract.
"""

from __future__ import annotations

__all__ = ["manifest"]
