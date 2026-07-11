from __future__ import annotations

import structlog


def configure_logging(env: str) -> None:
    """Configure structlog process-wide.

    Renders machine-readable JSON on every non-local (prod/staging) deploy so
    logs ship cleanly to a collector, and the human-friendly console renderer
    for local development. Called once at startup from ``main.py``; individual
    ``logger.*`` call sites are unchanged.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    render_processors: list[structlog.types.Processor]
    if env == "local":
        # ConsoleRenderer pretty-prints exc_info itself, so format_exc_info
        # must not run ahead of it.
        render_processors = [structlog.dev.ConsoleRenderer()]
    else:
        render_processors = [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    structlog.configure(
        processors=[*shared_processors, *render_processors],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
