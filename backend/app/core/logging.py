"""Structured logging (structlog over stdlib logging).

JSON in prod/staging, pretty console in dev. A ``request_id`` contextvar is
bound to every line; middleware sets it per request and workers propagate it.
"""

from __future__ import annotations

import contextvars
import logging
import sys

import structlog
from structlog.typing import Processor

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def configure_logging(level: str = "INFO", pretty: bool = True) -> None:
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer = (
        structlog.dev.ConsoleRenderer(colors=True)
        if pretty
        else structlog.processors.JSONRenderer(ensure_ascii=False)
    )
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    logging.basicConfig(level=level.upper(), stream=sys.stdout, format="%(message)s")
    for noisy in ("uvicorn.access", "celery.utils.log"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True
