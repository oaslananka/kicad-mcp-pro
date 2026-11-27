"""Shared helpers for KiCad S-expression text handling."""

from __future__ import annotations

import re
from collections.abc import Iterator


def _escape_sexpr_string(value: str) -> str:
    """Escape a Python string for inclusion in a KiCad S-expression."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )


def _sexpr_string(value: str) -> str:
    """Wrap an escaped KiCad S-expression string in quotes."""
    return f'"{_escape_sexpr_string(value)}"'


def _unescape_sexpr_string(value: str) -> str:
    """Unescape a KiCad S-expression string payload."""
    chars: list[str] = []
    escaped = False
    for char in value:
        if escaped:
            chars.append("\n" if char == "n" else char)
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            chars.append(char)
    if escaped:
        chars.append("\\")
    return "".join(chars)


def _extract_block(content: str, start: int) -> tuple[str, int]:
    """Extract a balanced S-expression block starting at ``start``."""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return content[start : index + 1], index - start + 1
    return "", 0


_HEAD = re.compile(r"[a-zA-Z0-9_-]+")


def iter_root_children(content: str) -> Iterator[tuple[str, str]]:
    """Yield immediate child blocks in one pass, ignoring quoted parentheses."""
    depth = 0
    in_string = False
    escaped = False
    start = 0
    for index, char in enumerate(content):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "(":
            if depth == 1:
                start = index
            depth += 1
        elif char == ")":
            if depth == 2:
                head = _HEAD.match(content, start + 1)
                if head is not None:
                    yield head.group(), content[start : index + 1]
            depth -= 1
            if depth == 0:
                return


__all__ = [
    "_escape_sexpr_string",
    "_extract_block",
    "_sexpr_string",
    "_unescape_sexpr_string",
    "iter_root_children",
]
