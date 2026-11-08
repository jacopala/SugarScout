"""Structured logging. JSON in deployed environments, readable console output locally."""

from __future__ import annotations

import logging
import sys

import structlog

from sugarscout.settings import Settings


def configure_logging(settings: Settings, *, configure_stdlib: bool = True) -> None:
    """Configure structlog. `configure_stdlib=False` leaves stdlib logging alone for
    processes (the ARQ worker) whose framework installs its own handlers."""
    level = logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)

    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=settings.service_name, env=settings.env.value)

    if configure_stdlib:
        # Route stdlib logging (uvicorn, sqlalchemy) to stdout at the same level.
        logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
