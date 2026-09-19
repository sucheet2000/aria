from __future__ import annotations

import logging
from typing import TextIO

import structlog

# stdlib loggers that can emit request/response payloads at DEBUG.
_THIRD_PARTY_LOGGERS = ("anthropic", "httpx", "httpcore", "chromadb", "faster_whisper")


def configure_logging(env: str, *, stream: TextIO | None = None) -> None:
    """Configure structlog process-wide.

    Renders machine-readable JSON on every non-local (prod/staging) deploy so
    logs ship cleanly to a collector, and the human-friendly console renderer
    for local development. Called once at startup from ``main.py``; individual
    ``logger.*`` call sites are unchanged.

    Minimum level: INFO on every non-local deploy, DEBUG locally. This is the
    first of two privacy defenses (S2): DEBUG records never reach production
    logs. The second is that no application log *field* carries raw user
    content at any level, so a future level change cannot leak it either.
    Known residual: an ``exc_info`` traceback includes the exception's own
    message, which is library-controlled; no ARIA exception interpolates user
    content into its message.

    Third-party stdlib loggers (anthropic, httpx, httpcore, chromadb,
    faster_whisper) are floored at WARNING on non-local deploys: the Anthropic
    SDK's DEBUG output includes the full request JSON (system prompt and
    messages), so ``ANTHROPIC_LOG=debug`` must not be able to expose it.
    """
    min_level = logging.DEBUG if env == "local" else logging.INFO
    if env != "local":
        for name in _THIRD_PARTY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
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
        # plain_traceback: never render frame locals (S2) — with `rich`
        # installed the default formatter would print every local variable,
        # including prompt text, on any exception in the cognition path.
        render_processors = [
            structlog.dev.ConsoleRenderer(
                exception_formatter=structlog.dev.plain_traceback
            )
        ]
    else:
        render_processors = [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    structlog.configure(
        processors=[*shared_processors, *render_processors],
        wrapper_class=structlog.make_filtering_bound_logger(min_level),
        logger_factory=structlog.PrintLoggerFactory(file=stream),
        cache_logger_on_first_use=False,
    )
