"""Fixture backend package (container smoke test only).

The fixture exists so the container pipeline can be exercised before the real
backend slice is merged.  It implements the same public health endpoint as the
backend (`GET /health`) and nothing else.
"""

from __future__ import annotations

__all__ = ["main"]
