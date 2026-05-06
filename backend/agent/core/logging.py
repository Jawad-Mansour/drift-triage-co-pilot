import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

thread_id_ctx: ContextVar[str | None] = ContextVar("thread_id", default=None)


def _add_thread_id(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    tid = thread_id_ctx.get()
    if tid:
        event_dict["thread_id"] = tid
    return event_dict


def configure_logging(level: str = "INFO", env: str = "local") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
        _add_thread_id,
    ]
    if env == "local":
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name) if name else structlog.get_logger()
