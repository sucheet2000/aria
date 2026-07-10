"""FastAPI dependencies.

`get_current_owner` is the single seam for multi-tenancy. Go is the single
auth boundary: it verifies the Clerk JWT and sets `X-Aria-Owner` on its
internal requests to this service. We trust that header, falling back to
`DEFAULT_OWNER` for local dev when no Go server is in front. Everything
downstream keys data by this owner.
"""
from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status

from app.config import settings

INTERNAL_AUTH_HEADER = "X-Internal-Auth"


def get_current_owner(request: Request) -> str:
    """Return the owner that the current request's data is scoped to."""
    return request.headers.get("X-Aria-Owner") or settings.DEFAULT_OWNER


def require_internal_auth(request: Request) -> None:
    """Enforce the Go<->Python internal trust boundary.

    Go sets `X-Internal-Auth` on every internal request. When
    `INTERNAL_AUTH_SECRET` is configured, a missing or mismatched header is
    rejected with 403. When the secret is empty (local dev), the check is a
    pass-through no-op so development without the Go server keeps working.
    The comparison is constant-time to avoid leaking the secret via timing.
    """
    secret = settings.INTERNAL_AUTH_SECRET
    if not secret:
        return
    provided = request.headers.get(INTERNAL_AUTH_HEADER)
    if provided is None or not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
