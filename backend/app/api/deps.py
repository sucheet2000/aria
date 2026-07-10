"""FastAPI dependencies.

`get_current_owner` is the single seam for multi-tenancy. Go is the single
auth boundary: it verifies the Clerk JWT and sets `X-Aria-Owner` on its
internal requests to this service. We trust that header, falling back to
`DEFAULT_OWNER` for local dev when no Go server is in front. Everything
downstream keys data by this owner.
"""
from __future__ import annotations

from fastapi import Request

from app.config import settings


def get_current_owner(request: Request) -> str:
    """Return the owner that the current request's data is scoped to."""
    return request.headers.get("X-Aria-Owner") or settings.DEFAULT_OWNER
