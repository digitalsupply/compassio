"""Structured JSON logging to stdout (collected by Alloy -> Loki).

Every record carries the active OTel ``trace_id``/``span_id`` when available so
Grafana can jump between Loki and Tempo.  Sensitive data (passwords, phone
numbers, item text, conclusion full text) must never be logged.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

from app.observability.tracing import current_trace_ids

# Extra fields that, when present on a LogRecord, are promoted to the JSON top
# level.  Endpoints/loggers attach these via ``logger.info(..., extra={...})``.
_EXTRA_FIELDS = (
    "request_id",
    "route",
    "method",
    "status",
    "duration_ms",
    "scale",
    "stage",
    "item_id",
    "outcome",
    "fallback",
    "cache",
    "count",
)

# Standard LogRecord attributes we must not echo verbatim.
_RESERVED = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        trace_id, span_id = current_trace_ids()
        if trace_id:
            payload["trace_id"] = trace_id
        if span_id:
            payload["span_id"] = span_id

        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str | None = None) -> None:
    """Install a single JSON handler on the root logger (idempotent)."""
    if os.getenv("COMPASSIO_JSON_LOGS", "1").lower() in ("0", "false", "no"):
        return
    root = logging.getLogger()
    root.setLevel((level or os.getenv("LOG_LEVEL", "INFO")).upper())
    # Replace any existing handlers so we don't double-log.
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    # Uvicorn installs its own handlers early; route them through the root JSON
    # handler instead of duplicating output.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True


__all__ = ["JsonFormatter", "setup_logging"]
