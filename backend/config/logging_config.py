"""Structured logging primitives for HTTP and background workers.

The formatter deliberately keeps a small, allow-listed event schema.  It
never serializes a request object, request body, authorization header, or
query string into logs.
"""

from __future__ import annotations

import contextvars
import json
import logging
from datetime import datetime, timezone
from typing import Any


_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "supplyforge_request_id",
    default="-",
)


def set_request_id(value: str) -> contextvars.Token:
    """Attach an HTTP correlation ID to logs emitted in this context."""
    return _request_id.set(value)


def reset_request_id(token: contextvars.Token) -> None:
    """Remove the HTTP correlation ID after a request finishes."""
    _request_id.reset(token)


def get_request_id() -> str:
    return _request_id.get()


class JsonLogFormatter(logging.Formatter):
    """Emit a stable JSON line without depending on an external formatter."""

    _extra_fields = (
        "event",
        "request_id",
        "method",
        "path",
        "status_code",
        "duration_ms",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=timezone.utc,
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", get_request_id()),
        }
        for field in self._extra_fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def build_logging_config(*, json_format: bool = True) -> dict[str, Any]:
    """Return Django's logging configuration for the configured environment."""
    formatter: dict[str, Any]
    if json_format:
        formatter = {"()": "config.logging_config.JsonLogFormatter"}
    else:
        formatter = {
            "format": "[{asctime}] {levelname} {name} {message}",
            "style": "{",
        }

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"default": formatter},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            },
        },
        "root": {"handlers": ["console"], "level": "INFO"},
        "loggers": {
            "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
            "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
            "supplyforge": {"handlers": ["console"], "level": "INFO", "propagate": False},
            "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
        },
    }
