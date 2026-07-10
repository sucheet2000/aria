"""FastAPI dependencies.

`get_current_owner` is the single seam for multi-tenancy: it returns the
`DEFAULT_OWNER` constant today, and Phase 4 replaces the body with the
authenticated identity. Everything downstream keys data by this owner.
"""
from __future__ import annotations

from app.config import settings


def get_current_owner() -> str:
    """Return the owner that the current request's data is scoped to."""
    return settings.DEFAULT_OWNER
