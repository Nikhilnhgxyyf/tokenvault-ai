"""Structured JSON logging.

Prompts, completions, and authorization headers are never passed to the logger by
this code base. Log only metadata (method, path, status, timing, request ID).
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_HANDLER_NAME = "tokenvault-json"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload["fields"] = fields
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    """Install one JSON handler on the root logger. Safe to call more than once."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == _HANDLER_NAME:
            root.removeHandler(handler)
    new_handler = logging.StreamHandler(sys.stdout)
    new_handler.set_name(_HANDLER_NAME)
    new_handler.setFormatter(JsonFormatter())
    root.addHandler(new_handler)
    root.setLevel(level)
  
