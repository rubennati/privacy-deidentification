"""Structured JSON logging with a per-request correlation id.

Never log file contents or PII. Log levels are disciplined: DEBUG < INFO < WARNING < ERROR.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Extra log-record attributes that, when present, are merged into the JSON payload. Used for
# structured request logging (method, path, status, duration) without free-text parsing.
_STRUCTURED_FIELDS = ("http_method", "http_path", "http_status", "duration_ms")


def set_correlation_id(value: str) -> None:
    """Bind the correlation id for the current request context."""
    _correlation_id.set(value)


def get_correlation_id() -> str | None:
    """Return the correlation id bound to the current context, if any."""
    return _correlation_id.get()


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON with a UTC ISO 8601 timestamp."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        correlation_id = get_correlation_id()
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Configure the root logger to emit JSON to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # The application owns structured request logging; silence chatty third-party access logs
    # so we don't emit a second, unstructured line per request. Presidio emits a burst of
    # INFO "recognizer loaded" lines when the analyzer engine initializes; capping it at
    # WARNING drops that noise while still surfacing genuine problems (and never widening the
    # decision-process logging, which stays disabled in the adapter so no analyzed text or
    # entity values can reach the logs).
    for noisy in ("uvicorn.access", "httpx", "httpcore", "presidio-analyzer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
