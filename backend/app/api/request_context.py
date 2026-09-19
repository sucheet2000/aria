from __future__ import annotations

import uuid

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.observability.metrics import MetricsCollector

REQUEST_ID_HEADER = "X-Request-ID"

logger = structlog.get_logger()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Bind a request id into structlog for the lifetime of each request.

    Reads ``X-Request-ID`` (set by the Go edge on every internal call) or
    generates one, binds it into structlog contextvars so every log line for
    the request carries ``request_id``, stashes it on ``request.state`` for the
    exception handler, and echoes it back on the response.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """App-level catch-all: log, count, and return a consistent error envelope.

    No unhandled 500 leaves the service without a structured log line and an
    error metric. The client only sees a generic message plus the request id
    for correlation; internals are never leaked in the response body.
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    # S2: no ``error=str(exc)`` field — the exception message is already in
    # the rendered traceback, and duplicating it as a searchable field only
    # widens exposure if a library message ever embeds request content.
    logger.error(
        "unhandled_exception",
        request_id=request_id,
        path=request.url.path,
        method=request.method,
        error_type=type(exc).__name__,
        exc_info=exc,
    )
    MetricsCollector().record_error()
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Internal Server Error",
                "request_id": request_id,
            }
        },
        headers={REQUEST_ID_HEADER: request_id},
    )
