"""Structured logging setup using structlog."""

from __future__ import annotations

import logging
import re
import sys
import traceback
from collections.abc import Mapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Literal, cast

import structlog

_SENSITIVE_KEY_PATTERN = re.compile(r"(token|secret|key|pass|cred)", re.IGNORECASE)
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)(?:api[-_ ]?key|token|secret|password|credential)\s*[:=]\s*\S+"
)
_PROJECT_PATH_KEY_PATTERN = re.compile(
    r"(?i)(?:^|_)(?:cli|dir|file|path|root)$|^(?:kicad_cli|workspace_root)$"
)
_PAYLOAD_KEY_PATTERN = re.compile(r"(?i)(?:payload|body|content|arguments?|result)")
_MAX_LOG_TEXT_CHARS = 1024
_STANDARD_FIELDS = ("request_id", "mcp_session_id", "tool", "latency_ms", "error")
_REDACTED = "***REDACTED***"
_REDACTED_PATH = "***REDACTED_PATH***"
_TRUNCATED = "***TRUNCATED***"
LogFormat = Literal["json", "text", "console"]


def _redact_text(value: str) -> str:
    sanitized = _SENSITIVE_TEXT_PATTERN.sub(_REDACTED, value)
    if len(sanitized) > _MAX_LOG_TEXT_CHARS:
        return f"{_TRUNCATED} ({len(sanitized)} chars)"
    return sanitized


def _structured_error(error: BaseException) -> dict[str, str]:
    rendered = {
        "type": type(error).__name__,
        "message": _redact_text(str(error)),
    }
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        rendered["stack"] = "".join(traceback.format_exception(error))
    return rendered


def _sanitize_value(key: str, value: object) -> object:
    if _SENSITIVE_KEY_PATTERN.search(key):
        return _REDACTED
    if value is None:
        return None
    if _PROJECT_PATH_KEY_PATTERN.search(key):
        return _REDACTED_PATH
    if isinstance(value, BaseException):
        return _structured_error(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        if _PAYLOAD_KEY_PATTERN.search(key) or len(value) > _MAX_LOG_TEXT_CHARS:
            return _redact_text(value)
        return _redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(child_key): _sanitize_value(str(child_key), child)
            for child_key, child in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [_sanitize_value(key, item) for item in value]
    return value


def _normalize_log_schema(
    _logger: structlog.typing.WrappedLogger,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    for field in _STANDARD_FIELDS:
        event_dict.setdefault(field, None)
    return event_dict


def redact_sensitive_keys(
    _logger: structlog.typing.WrappedLogger,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Redact values of sensitive log fields before rendering."""
    return {key: _sanitize_value(key, value) for key, value in event_dict.items()}


def _build_handlers(
    log_file: Path | None,
    log_max_bytes: int,
    log_backup_count: int,
) -> list[logging.Handler]:
    formatter = logging.Formatter("%(message)s")
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    handlers: list[logging.Handler] = [stream_handler]
    if log_file is None:
        return handlers

    resolved_log_file = log_file.expanduser()
    resolved_log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        resolved_log_file,
        maxBytes=log_max_bytes,
        backupCount=log_backup_count,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setFormatter(formatter)
    handlers.append(file_handler)
    return handlers


class _SchematicItemTraceFilter(logging.Filter):
    """Suppress only the two noisy per-item DEBUG events from kicad-sch-api."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "kicad_sch_api.collections.base" or record.levelno != logging.DEBUG:
            return True
        message = record.getMessage()
        return message != "Indexes marked dirty" and not message.startswith("Added item with UUID ")


def setup_logging(
    level: str = "INFO",
    format: LogFormat = "text",
    log_file: Path | None = None,
    log_max_bytes: int = 5_000_000,
    log_backup_count: int = 3,
    schematic_item_details: bool = False,
) -> None:
    """Configure structured logging for the MCP server."""
    processors: list[object] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", key="ts"),
        _normalize_log_schema,
        redact_sensitive_keys,
        structlog.processors.StackInfoRenderer(),
    ]

    if format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()))

    structlog.configure(
        processors=cast(Any, processors),
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handlers = _build_handlers(log_file, log_max_bytes, log_backup_count)
    if not schematic_item_details:
        for handler in handlers:
            handler.addFilter(_SchematicItemTraceFilter())
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        handlers=handlers,
        force=True,
    )
