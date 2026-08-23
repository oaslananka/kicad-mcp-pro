"""Shared sanitization boundary for publishable evaluation evidence."""

from __future__ import annotations

import re

__all__ = ["EvidenceSanitizationError", "validate_sanitized_evidence"]


class EvidenceSanitizationError(ValueError):
    """Raised when an evidence payload contains forbidden sensitive material."""


_FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "authorization",
        "command",
        "credential",
        "credentials",
        "prompt",
        "raw_request",
        "raw_response",
        "required_env",
        "secret",
        "secrets",
        "trace_path",
        "transcript",
    }
)
_SENSITIVE_EVIDENCE_VALUE = re.compile(
    r"(?i)(?:bearer\s+\S+|sk-[A-Za-z0-9_-]{8,}|"
    r"(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S+)"
)
_PRIVATE_ABSOLUTE_PATH = re.compile(
    r"(?:/(?:home|root|srv|tmp|var)/|[A-Za-z]:\\(?:Users|Temp|ProgramData)\\)"
)


def validate_sanitized_evidence(value: object) -> None:
    """Reject evidence keys or string values that could expose sensitive material."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).casefold()
            if normalized_key in _FORBIDDEN_EVIDENCE_KEYS:
                raise EvidenceSanitizationError(f"Forbidden evidence key: {key!r}.")
            validate_sanitized_evidence(child)
        return
    if isinstance(value, list | tuple):
        for child in value:
            validate_sanitized_evidence(child)
        return
    if isinstance(value, str):
        if _SENSITIVE_EVIDENCE_VALUE.search(value) or _PRIVATE_ABSOLUTE_PATH.search(value):
            raise EvidenceSanitizationError("Evidence contains a sensitive string value.")
